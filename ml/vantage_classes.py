"""Class names and IDs shared by the dataset builder, training, and evaluation.

Two ID spaces:
- Training IDs (TRAIN_CLASSES): the fine-tuned model's own classes, 0 player, 1 ball, 2 paddle.
- Canonical IDs (CANONICAL): what detections.jsonl always uses, regardless of model. They
  follow COCO numbering so runs made with the generic COCO model remain valid. Mirrors
  DetectionClass in mobile/ios/VantageKit/Sources/VantageKit/Detection.swift.
"""

TRAIN_CLASSES = ["player", "ball", "paddle"]
CANONICAL = {"player": 0, "ball": 32, "paddle": 38}

# Model / dataset class names accepted for each Vantage class (case-insensitive).
ALIASES = {
    "person": "player", "player": "player",
    "sports ball": "ball", "ball": "ball", "pickleball": "ball",
    "tennis racket": "paddle", "paddle": "paddle",
}


def vantage_class(name):
    """Vantage class name for a model/dataset class name, or None if unrelated."""
    return ALIASES.get(str(name).strip().lower())


def canonical_map(names):
    """{model class index: canonical ID} for an Ultralytics `names` dict."""
    return {int(i): CANONICAL[v] for i, n in names.items() if (v := vantage_class(n))}
