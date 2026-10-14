"""Fine-tune YOLO26n on a dataset from build_dataset.py (Apple GPU via MPS by default).

    .venv/bin/python ml/train.py --data ml/datasets/pickleball-v1/data.yaml --name pickleball-v1

Starts from the generic COCO checkpoint, so player/paddle features carry over. Trains at
1280 px because pickleballs are only a few pixels wide. Results go to ml/runs/<name>/
(weights/best.pt, metrics, plots) with a manifest recording data and settings.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from labeling import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--weights", type=Path, default=ROOT / "yolo26n.pt")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--patience", type=int, default=20, help="stop after this many epochs without improvement")
    parser.add_argument("--hours", type=float, help="time budget; overrides --epochs and fits the LR schedule to it")
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default="mps")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    project = ROOT / "ml" / "runs"
    if (project / args.name).exists() and not args.overwrite:
        raise SystemExit(f"{project / args.name} exists; choose another --name or pass --overwrite.")

    from ultralytics import YOLO
    import ultralytics
    model = YOLO(str(args.weights))
    model.train(data=str(args.data), epochs=args.epochs, patience=args.patience, imgsz=args.imgsz,
                batch=args.batch, device=args.device, workers=args.workers, project=str(project),
                name=args.name, exist_ok=args.overwrite, seed=0, deterministic=False, plots=True,
                **({"time": args.hours} if args.hours else {}))

    run = project / args.name
    data_manifest = Path(args.data).parent / "manifest.json"
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    manifest = {
        "base_weights": str(args.weights), "base_sha256": hashlib.sha256(args.weights.read_bytes()).hexdigest(),
        "data": str(args.data), "data_manifest": json.loads(data_manifest.read_text()) if data_manifest.exists() else None,
        "args": {k: str(v) for k, v in vars(args).items()}, "git_commit": commit,
        "ultralytics": ultralytics.__version__, "python": sys.version.split()[0],
    }
    (run / "vantage-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Best weights: {run / 'weights' / 'best.pt'}")


if __name__ == "__main__":
    main()
