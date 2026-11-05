"""Export a COPY of the desktop checkpoint; never write beside the original."""

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("YOLO_AUTOINSTALL", "false")
os.environ.setdefault("YOLO_CONFIG_DIR", str(ROOT / ".cache/ultralytics"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, default=ROOT / "yolo26n.pt")
    parser.add_argument("--size", type=int, default=1280)
    parser.add_argument("--precision", type=int, choices=[16, 32], default=16)
    parser.add_argument(
        "--ball-confidence",
        type=float,
        default=0.10,
        help="minimum ball confidence the app keeps for this model (stored in model metadata)",
    )
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/yolo26n-1280")
    args = parser.parse_args(argv)
    if not args.weights.is_file():
        parser.error("Weights must already exist locally; downloads are not implicit.")
    if args.size <= 0 or args.size % 32:
        parser.error("Size must be a positive multiple of 32.")
    if not 0 <= args.ball_confidence <= 1:
        parser.error("Ball confidence must be finite and between 0 and 1.")
    if args.output.exists():
        raise FileExistsError(f"{args.output} already exists; choose a new output directory.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".coreml-export-", dir=args.output.parent) as temporary:
        work_dir = (Path(temporary) / "export").resolve()
        work_dir.mkdir()
        package = export_model(args, work_dir)
        work_dir.rename(args.output)
    print(f"Exported {package}")


def export_model(args, work_dir):
    """Build in a private directory; return the package's final published path."""
    checkpoint = work_dir / "VantageDetector.pt"
    shutil.copy2(args.weights, checkpoint)
    Path(os.environ["YOLO_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)
    import coremltools as ct
    import torch
    import ultralytics
    from ultralytics import YOLO

    yolo = YOLO(str(checkpoint))
    names = {int(k): v for k, v in yolo.names.items()}
    package = yolo.export(
        format="coreml",
        imgsz=args.size,
        batch=1,
        dynamic=False,
        nms=False,
        quantize=args.precision,
        device="cpu",
        max_det=100,
    )
    model = ct.models.MLModel(str(package), skip_model_load=True)
    # Model-specific operating point, read by the app's Detector (VantageKit).
    model.user_defined_metadata["vantage_ball_confidence"] = str(args.ball_confidence)
    # MLModel.save() deletes the destination first, so never save over the source package.
    staged = Path(package).with_name("staged-" + Path(package).name)
    model.save(str(staged))
    shutil.rmtree(package)
    staged.rename(package)
    final_package = args.output / Path(package).relative_to(work_dir)
    spec = model.get_spec()
    manifest = {
        "source_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "source": str(args.weights.resolve()),
        "package": str(final_package.resolve()),
        "size": args.size,
        "precision": f"FP{args.precision}",
        "nms": False,
        "max_detections": 100,
        "model_classes": names,
        "note": "The app maps classes to canonical IDs by name (DetectionClass.canonicalMap).",
        "confidence": 0.10,
        "ball_confidence": args.ball_confidence,
        "ultralytics": ultralytics.__version__,
        "torch": torch.__version__,
        "coremltools": ct.__version__,
        "inputs": [str(x) for x in spec.description.input],
        "outputs": [str(x) for x in spec.description.output],
    }
    (work_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    return final_package


if __name__ == "__main__":
    main()
