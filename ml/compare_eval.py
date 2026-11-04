"""Markdown report comparing two evaluate_external.py --json results (base vs this change).

    uv run python ml/compare_eval.py --head head.json --base base.json \
        --head-label "this PR (abc1234)" --base-label "main (def5678)" > report.md

Used by .github/workflows/eval.yml for the pull request comment; works without --base too.
A change is flagged when it is at least SIGNIFICANT percentage points (as displayed) and moves at
least MIN_FRAMES frames. When both runs score the same frames with the same labels, a difference
comes from the code or model under test, not noise; the report says when the frames differ.
"""
import argparse
import json
from pathlib import Path

MARKER = "<!-- vantage-accuracy-report -->"
SIGNIFICANT = 0.5  # percentage points
MIN_FRAMES = 5  # so a single frame on a small source is not flagged
SPORTS = ("pickleball", "tennis", "badminton")
METRICS = (("tracked", "recall", "Tracked recall"), ("tracked", "precision", "Tracked precision"),
           ("raw best", "recall", "Detector recall"), ("raw best", "precision", "Detector precision"))
CAUSES = (("no_detection", "No ball detection"), ("elsewhere", "Only detections elsewhere"),
          ("not_selected", "Detected, not picked"))


def value(run, key, predictor, metric):
    """(rate, frames behind it) for a metric, or (None, None) when the run has no such group."""
    group = (run or {}).get("results", {}).get(key)
    if not group:
        return None, None
    totals = group[predictor]
    if metric == "recall":
        return totals["recall"], totals["correct"]
    if metric == "precision":  # moves with both correct and false detections
        return totals["precision"], (totals["correct"], totals["false_detection"])
    return (totals[metric] / totals["visible"] if totals["visible"] else None), totals[metric]


def frames_moved(head, base):
    if isinstance(head, tuple):
        return max(abs(h - b) for h, b in zip(head, base))
    return abs(head - base)


def cell(head, base, higher_is_better=True):
    """'61.2%', or with a base '61.2% (+1.5, 23 frames)', bold with 🟢/🔴 when significant.
    head and base are (rate, frames) from value()."""
    (rate, frames), (base_rate, base_frames) = head, base
    if rate is None:
        return "-"
    text = f"{rate:.1%}"
    if base_rate is None:
        return text
    delta = round((rate - base_rate) * 100, 1)  # judge the number that is shown
    moved = frames_moved(frames, base_frames)
    if not delta:
        return f"{text} (=)"
    detail = f"{delta:+.1f}, {moved} frame{'s' if moved != 1 else ''}"
    if abs(delta) < SIGNIFICANT or moved < MIN_FRAMES:
        return f"{text} ({detail})"
    good = (delta > 0) == higher_is_better
    return f"**{text} ({detail} {'🟢' if good else '🔴'})**"


def rows(head, base, keys, columns):
    lines = []
    for key, label in keys:
        if key not in head["results"] and key not in (base or {}).get("results", {}):
            continue
        cells = [cell(value(head, key, *col[:2]), value(base, key, *col[:2]), col[2]) for col in columns]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return lines


def report(head, base=None, head_label="this change", base_label="base", base_error=None):
    sport_keys = [("all:all", "**All**")] + [(f"sport:{s}", s.capitalize()) for s in SPORTS]
    sports = {**(base or {}).get("sports", {}), **head["sports"]}
    source_keys = sorted((k, f"{k[7:]} ({sports.get(k[7:], '?')})")
                         for k in set(head["results"]) | set((base or {}).get("results", {})) if k.startswith("source:"))
    metric_columns = [(predictor, metric, True) for predictor, metric, _ in METRICS]
    labeled = head["results"]["all:all"]["tracked"]["labeled"]
    lines = [MARKER, "## Ball tracking accuracy", ""]
    if base:
        lines.append(f"**{head_label}** compared with **{base_label}**, on the `{head.get('suite') or 'full'}` "
                     f"eval suite: {len(source_keys)} public sources, {labeled:,} labeled frames. Changes show "
                     f"points and frames; {SIGNIFICANT} points or more and at least {MIN_FRAMES} frames are bold "
                     "(🟢 better, 🔴 worse).")
    else:
        lines.append(f"**{head_label}** on the `{head.get('suite') or 'full'}` eval suite: {len(source_keys)} "
                     f"public sources, {labeled:,} labeled frames. No comparison: "
                     f"{base_error or 'no base was given'}.")
    notes = []
    def scored(run, key):
        tracked = run["results"].get(key, {}).get("tracked", {})
        return tracked.get("labeled"), tracked.get("visible")
    if base and any(scored(head, key) != scored(base, key)
                    for key in set(head["results"]) | set(base["results"]) if not key.startswith("clip:")):
        notes.append("The scored frames differ between the two runs (the suite or the labels changed), "
                     "so differences are not only from the code or model.")
    for run, label in ((head, head_label), (base, base_label)):
        if run and run.get("unfetched"):
            notes.append(f"Not scored for {label}: {', '.join(run['unfetched'])} (download failed).")
        if run and run.get("skipped"):
            notes.append(f"Skipped for {label}: {', '.join(run['skipped'])}.")
    lines += [""] + [f"> {note}" for note in notes] + ([""] if notes else [])
    lines += ["| | " + " | ".join(name for _, _, name in METRICS) + " |", "| --- |" + " ---: |" * len(METRICS)]
    lines += rows(head, base, sport_keys, metric_columns)
    lines += ["", "<details><summary>Per source</summary>", "",
              "| Source | " + " | ".join(name for _, _, name in METRICS) + " |", "| --- |" + " ---: |" * len(METRICS)]
    lines += rows(head, base, source_keys, metric_columns)
    lines += ["", "</details>", "", "<details><summary>Why the tracker missed visible balls (% of visible)</summary>",
              "", "| | " + " | ".join(name for _, name in CAUSES) + " |", "| --- |" + " ---: |" * len(CAUSES)]
    lines += rows(head, base, sport_keys + source_keys, [("tracked", cause, False) for cause, _ in CAUSES])
    lines += ["", "No ball detection and detections elsewhere are detector misses; detected-but-not-picked "
              "are tracker misses.", "", "</details>", ""]
    setups = [f"{label}: {run['setup']}" for run, label in ((head, head_label), (base, base_label)) if run]
    lines.append("<sub>" + "<br>".join(setups) + "<br>Tracked = detector plus BallTracker, what the app shows; "
                 "detector = its best raw candidate per frame. A prediction is correct within 1% of the frame "
                 "diagonal. Sources and caveats: <code>ml/EVAL_DATA.md</code>.</sub>")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--head", type=Path, required=True, help="evaluate_external.py --json for the change")
    parser.add_argument("--base", type=Path, help="the same for its base, if it could be scored")
    parser.add_argument("--head-label", default="this change")
    parser.add_argument("--base-label", default="base")
    parser.add_argument("--base-error", help="why there is no base to compare with, for the report")
    args = parser.parse_args()
    base = json.loads(args.base.read_text()) if args.base and args.base.is_file() and args.base.stat().st_size else None
    print(report(json.loads(args.head.read_text()), base, args.head_label, args.base_label, args.base_error), end="")


if __name__ == "__main__":
    main()
