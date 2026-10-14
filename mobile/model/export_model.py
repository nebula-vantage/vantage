"""Export a COPY of the desktop checkpoint; never write beside the original."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("YOLO_AUTOINSTALL", "false")
os.environ.setdefault("YOLO_CONFIG_DIR", str(ROOT / "mobile/.cache/ultralytics"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, default=ROOT / "yolo26n.pt")
    parser.add_argument("--size", type=int, default=1280)
    parser.add_argument("--precision", type=int, choices=[16, 32], default=16)
    parser.add_argument("--output", type=Path, default=ROOT / "mobile/artifacts/yolo26n-1280")
    args = parser.parse_args()
    if not args.weights.is_file():
        parser.error("Weights must already exist locally; downloads are not implicit.")
    if args.size <= 0 or args.size % 32:
        parser.error("Size must be a positive multiple of 32.")
    # Refuse existing destinations so no previous artifact is silently replaced.
    args.output.mkdir(parents=True, exist_ok=False)
    checkpoint = args.output / "VantageDetector.pt"
    shutil.copy2(args.weights, checkpoint)
    Path(os.environ["YOLO_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)
    from ultralytics import YOLO
    import coremltools as ct
    import ultralytics
    import torch

    yolo = YOLO(str(checkpoint))
    names = {int(k): v for k, v in yolo.names.items()}
    package = yolo.export(
        format="coreml", imgsz=args.size, batch=1, dynamic=False,
        nms=False, quantize=args.precision, device="cpu", max_det=100,
    )
    model = ct.models.MLModel(str(package), skip_model_load=True)
    spec = model.get_spec()
    manifest = {
        "source_sha256": hashlib.sha256(args.weights.read_bytes()).hexdigest(),
        "source": str(args.weights.resolve()), "package": str(Path(package).resolve()),
        "size": args.size, "precision": f"FP{args.precision}", "nms": False,
        "max_detections": 100, "model_classes": names,
        "note": "The app maps classes to canonical IDs by name (DetectionClass.canonicalMap).",
        "confidence": 0.10, "ultralytics": ultralytics.__version__,
        "torch": torch.__version__, "coremltools": ct.__version__,
        "inputs": [str(x) for x in spec.description.input],
        "outputs": [str(x) for x in spec.description.output],
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Exported {package}")


if __name__ == "__main__":
    main()
