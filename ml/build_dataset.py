"""Assemble a YOLO training set (player, ball, paddle) from hand labels and public datasets.

    .venv/bin/python ml/build_dataset.py [--spec ml/dataset.yaml] [--overwrite]

Sources (see ml/dataset.yaml):
- Hand labels (ml/labels/*.json): every labeled frame is extracted from its video. Frames
  marked "no ball" are kept as negatives. Holdout videos are excluded entirely.
- External YOLO datasets (ml/external/<dir>, from fetch_roboflow.py), class-mapped by name.
Classes a source does not label are pseudo-labeled by the teacher (generic COCO model).

Writes ml/datasets/<name>/{images,labels}/{train,val}, data.yaml, and manifest.json.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import shutil
import sys

import cv2
import yaml

from labeling import ROOT, load_labels
from vantage_classes import TRAIN_CLASSES, vantage_class

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def yolo_line(class_name, box, width, height):
    """YOLO label row: class cx cy w h, normalized and clipped to the image."""
    x1, y1, x2, y2 = (max(0.0, min(float(v), limit)) for v, limit in zip(box, (width, height, width, height)))
    if x2 <= x1 or y2 <= y1:
        return None
    return (f"{TRAIN_CLASSES.index(class_name)} {(x1 + x2) / 2 / width:.6f} {(y1 + y2) / 2 / height:.6f} "
            f"{(x2 - x1) / width:.6f} {(y2 - y1) / height:.6f}")


def split_for(key, val_fraction):
    """Deterministic train/val assignment from a stable key (no randomness between builds)."""
    value = int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "val" if value < val_fraction else "train"


def video_samples(labels_dir, holdout, val_fraction):
    """(split, key, source, video path, frame index, ball box or None) for hand labels."""
    samples = []
    for path in sorted(Path(labels_dir).glob("*.json")):
        if path.stem in holdout:
            continue
        data = json.loads(path.read_text())
        video = ROOT / data["video"] if not Path(data["video"]).is_absolute() else Path(data["video"])
        for frame, label in sorted(load_labels(path).items()):
            # 2-second blocks keep near-duplicate neighbouring frames in the same split.
            block = int(label["time_s"] // 2)
            samples.append((split_for(f"{path.stem}:{block}", val_fraction), f"{path.stem}__{frame:06d}",
                            f"labels/{path.stem}", video, frame, label["ball"]))
    return samples


def external_samples(external_root, entries):
    """(split, key, source, image path, label rows(class, box px)) for external YOLO datasets."""
    samples = []
    for entry in entries:
        root = Path(external_root) / entry["dir"]
        meta = yaml.safe_load((root / "data.yaml").read_text())
        names = meta["names"] if isinstance(meta["names"], list) else [meta["names"][i] for i in sorted(meta["names"])]
        mapping = {i: entry["classes"].get(name) or None for i, name in enumerate(names)}
        unknown = [c for c in entry["classes"].values() if c not in TRAIN_CLASSES]
        if unknown:
            raise SystemExit(f"{entry['dir']}: unknown target classes {unknown}; use {TRAIN_CLASSES}")
        per_split = {"train": [], "val": []}
        for folder, split in (("train", "train"), ("test", "train"), ("valid", "val")):
            for image in sorted((root / folder / "images").glob("*")) if (root / folder / "images").exists() else []:
                if image.suffix.lower() not in IMAGE_SUFFIXES:
                    continue
                rows = []
                label_file = root / folder / "labels" / f"{image.stem}.txt"
                for line in (label_file.read_text().splitlines() if label_file.exists() else []):
                    parts = line.split()
                    if len(parts) != 5:  # skip polygon/segmentation rows
                        continue
                    target = mapping.get(int(parts[0]))
                    if target:
                        rows.append((target, [float(v) for v in parts[1:]]))
                # Datasets that leave many visible balls unlabeled would teach the model to
                # ignore real balls; only_with_ball keeps just the images with a ball label.
                if entry.get("only_with_ball") and not any(c == "ball" for c, _ in rows):
                    continue
                per_split[split].append((split, f"{entry['dir']}__{folder}__{image.stem}", entry["dir"], image, rows,
                                         set(entry["classes"].values())))
        for split, items in per_split.items():
            cap = entry.get(f"max_{split}")
            if cap is not None and len(items) > cap:
                # Deterministic subsample: same images on every build.
                items = sorted(items, key=lambda s: hashlib.sha1(s[1].encode()).hexdigest())[:cap]
            samples.extend(sorted(items, key=lambda s: s[1]))
    return samples


class Teacher:
    """Generic COCO model that fills in classes a source does not label."""

    def __init__(self, spec):
        from ultralytics import YOLO
        self.model = YOLO(str(ROOT / spec["weights"]))
        self.imgsz = spec["imgsz"]
        self.device = spec.get("device")
        self.confidence = spec["confidence"]
        self.ids = {i: vantage_class(n) for i, n in self.model.names.items() if vantage_class(n) in self.confidence}

    def boxes(self, image, classes):
        wanted = [i for i, c in self.ids.items() if c in classes]
        if not wanted:
            return []
        result = self.model.predict(image, imgsz=self.imgsz, conf=min(self.confidence.values()),
                                    classes=wanted, device=self.device, verbose=False)[0]
        return [(self.ids[int(c)], b) for b, c, s in zip(result.boxes.xyxy.tolist(), result.boxes.cls.tolist(),
                                                         result.boxes.conf.tolist())
                if s >= self.confidence[self.ids[int(c)]]]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--spec", type=Path, default=ROOT / "ml" / "dataset.yaml")
    parser.add_argument("--output-root", type=Path, default=ROOT / "ml" / "datasets")
    parser.add_argument("--external-root", type=Path, default=ROOT / "ml" / "external")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    spec = yaml.safe_load(args.spec.read_text())
    out = args.output_root / spec["name"]
    if out.exists():
        if not args.overwrite:
            raise SystemExit(f"{out} exists; pass --overwrite to rebuild.")
        shutil.rmtree(out)
    for split in ("train", "val"):
        (out / "images" / split).mkdir(parents=True)
        (out / "labels" / split).mkdir(parents=True)

    holdout = set(spec.get("holdout_videos") or [])
    labels_dir = ROOT / spec["labels"] if spec.get("labels") else None
    videos = video_samples(labels_dir, holdout, spec.get("val_fraction", 0.15)) if labels_dir else []
    externals = external_samples(args.external_root, spec.get("external") or [])
    if not videos and not externals:
        raise SystemExit("No training samples: label non-holdout videos or add external datasets.")
    teacher = Teacher(spec["teacher"])
    pseudo = set(spec["teacher"]["confidence"])
    counts = defaultdict(Counter)

    def write(split, key, source, image, rows):
        h, w = image.shape[:2]
        lines = [line for cls, box in rows if (line := yolo_line(cls, box, w, h))]
        cv2.imwrite(str(out / "images" / split / f"{key}.jpg"), image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        (out / "labels" / split / f"{key}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
        counts[source][f"{split}_images"] += 1
        for line in lines:
            counts[source][f"{split}_{TRAIN_CLASSES[int(line.split()[0])]}"] += 1

    captures = {}
    for i, (split, key, source, video, frame, ball) in enumerate(videos):
        capture = captures.setdefault(video, cv2.VideoCapture(str(video)))
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame)
        ok, image = capture.read()
        if not ok:
            raise SystemExit(f"Cannot read frame {frame} of {video}")
        rows = ([("ball", ball)] if ball else []) + teacher.boxes(image, pseudo)
        write(split, key, source, image, rows)
        if i % 50 == 0:
            print(f"hand labels: {i + 1}/{len(videos)}", file=sys.stderr)
    for i, (split, key, source, path, rows, provided) in enumerate(externals):
        image = cv2.imread(str(path))
        if image is None:
            print(f"skipping unreadable {path}", file=sys.stderr)
            continue
        h, w = image.shape[:2]
        pixel_rows = [(c, [(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h])
                      for c, (cx, cy, bw, bh) in rows]
        write(split, key, source, image, pixel_rows + teacher.boxes(image, pseudo - provided))
        if i % 200 == 0:
            print(f"external: {i + 1}/{len(externals)}", file=sys.stderr)

    (out / "data.yaml").write_text(yaml.safe_dump({
        "path": str(out), "train": "images/train", "val": "images/val",
        "names": dict(enumerate(TRAIN_CLASSES))}, sort_keys=False))
    sources = {}
    for entry in spec.get("external") or []:
        source_file = args.external_root / entry["dir"] / "SOURCE.json"
        sources[entry["dir"]] = json.loads(source_file.read_text()) if source_file.exists() else None
    manifest = {"spec": spec, "holdout_videos": sorted(holdout), "counts": {k: dict(v) for k, v in counts.items()},
                "totals": dict(sum(counts.values(), Counter())), "external_sources": sources}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest["totals"], indent=2))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
