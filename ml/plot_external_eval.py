"""Chart evaluate_external.py results: per-source recall/precision and why balls were missed.

    R=ml/results/external-eval-$(date +%F)
    uv run python ml/evaluate_external.py --weights yolo26n.pt --json > $R/yolo26n.json
    uv run python ml/evaluate_external.py --json > $R/pickleball-v1.json
    uv run python ml/plot_external_eval.py "COCO yolo26n=$R/yolo26n.json" "pickleball-v1=$R/pickleball-v1.json" \\
        --output $R

Writes recall_precision.png (every run; the last is drawn on top and labeled) and miss_causes.png
(last run). Only sources and sports present in every run are drawn.
Colors are a colorblind-checked categorical palette; every value is also labeled or tabled.
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SURFACE, INK, INK_2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
RUN_COLORS = ("#eb6834", "#2a78d6")  # baseline orange, model blue
CAUSES = (("correct", "Tracked correctly", "#2a78d6"),
          ("not_selected", "Ball detected, tracker picked something else", "#eb6834"),
          ("elsewhere", "Only false detections elsewhere", "#1baf7a"),
          ("no_detection", "No ball detection at all", "#eda100"))
SPORTS = ("pickleball", "tennis", "badminton")


def rows_by_sport(runs):
    """[(label, result key, is sport header)] present in every run, sources sorted by the last
    run's tracked recall within each sport."""
    last = runs[-1]
    present = lambda key: all(key in run["results"] for run in runs)
    rows = []
    for sport in SPORTS:
        sources = sorted((s for s, sp in last["sports"].items() if sp == sport and present(f"source:{s}")),
                         key=lambda s: last["results"][f"source:{s}"]["tracked"]["recall"] or 0)
        if sources:
            rows.append((f"{sport.upper()} (all)", f"sport:{sport}", True))
            rows += [(s, f"source:{s}", False) for s in sources]
    return rows


def style(ax):
    ax.set_facecolor(SURFACE)
    ax.set_xlim(0, 1.08)
    ax.set_xticks([0, .25, .5, .75, 1], ["0%", "25%", "50%", "75%", "100%"])
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(axis="y", length=0, colors=INK_2)
    ax.tick_params(axis="x", colors=MUTED)


def recall_precision(runs, path):
    names, results = list(runs), list(runs.values())
    rows = rows_by_sport(results)
    y = {key: len(rows) - i for i, (_, key, _) in enumerate(rows)}
    fig, axes = plt.subplots(1, 2, figsize=(11, 0.42 * len(rows) + 1.6), sharey=True, facecolor=SURFACE)
    for ax, metric in zip(axes, ("recall", "precision")):
        style(ax)
        for _, key, header in rows:
            values = [run["results"][key]["tracked"][metric] for run in results]
            drawn = [v for v in values if v is not None]
            if not drawn:
                continue
            ax.plot([min(drawn), max(drawn)], [y[key]] * 2, color=AXIS, lw=2, zorder=1)
            for value, color in zip(values, RUN_COLORS[-len(values):]):
                if value is not None:
                    ax.scatter(value, y[key], s=90 if header else 64, color=color, edgecolor=SURFACE, lw=2, zorder=3)
            if (header or metric == "recall") and values[-1] is not None:
                # The label describes the last run; say so when its dot is not the rightmost one.
                lower = len(drawn) > 1 and values[-1] < max(drawn)
                text = f"{values[-1]:.0%}" + (f" (down from {max(drawn):.0%})" if lower else "")
                ax.text(max(drawn) + 0.025, y[key], text, va="center", fontsize=9,
                        color=INK if header else INK_2, fontweight="bold" if header else "normal")
        ax.set_title(f"Tracked {metric}", loc="left", fontsize=11, fontweight="bold", color=INK)
    axes[0].set_yticks(list(y.values()), [label for label, _, _ in rows])
    for tick, (_, _, header) in zip(axes[0].get_yticklabels(), rows):
        tick.set_fontweight("bold" if header else "normal")
    fig.legend(handles=[plt.Line2D([], [], marker="o", ls="", ms=8, color=color, label=f"{name}: {run['setup']}")
                        for name, run, color in zip(names, results, RUN_COLORS[-len(runs):])],
               loc="lower left", bbox_to_anchor=(0.01, 1.0), frameon=False, fontsize=8.5)
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE, bbox_inches="tight")


def miss_causes(name, run, path):
    rows = [(label, key) for label, key, header in rows_by_sport([run])
            if not header and run["results"][key]["tracked"]["visible"]]
    fig, ax = plt.subplots(figsize=(11, 0.42 * len(rows) + 1.4), facecolor=SURFACE)
    style(ax)
    ax.set_xlim(0, 1)
    ax.grid(False)
    for yy, (label, key) in zip(range(len(rows) - 1, -1, -1), rows):
        tracked, left = run["results"][key]["tracked"], 0
        for cause, _, color in CAUSES:
            width = tracked[cause] / tracked["visible"]
            ax.barh(yy, width, left=left, color=color, edgecolor=SURFACE, lw=2, height=0.7)
            if width >= 0.08:
                ax.text(left + width / 2, yy, f"{width:.0%}", ha="center", va="center", fontsize=8.5,
                        color="white" if cause == "correct" else INK)
            left += width
    ax.set_yticks(range(len(rows) - 1, -1, -1), [f"{label} ({run['sports'][label]})" for label, _ in rows])
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=color, label=text) for _, text, color in CAUSES],
              loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2, frameon=False, fontsize=9)
    ax.set_title(f"{name}: outcome on frames where the ball is visible", loc="left", fontsize=11,
                 fontweight="bold", color=INK, pad=44)
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE, bbox_inches="tight")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="+", help="NAME=results.json from evaluate_external.py --json (1 or 2)")
    parser.add_argument("--output", type=Path, required=True, help="directory for the PNGs")
    args = parser.parse_args()
    if len(args.runs) > len(RUN_COLORS) or any("=" not in r for r in args.runs):
        parser.error("pass one or two NAME=results.json")
    pairs = [r.split("=", 1) for r in args.runs]
    if len({name for name, _ in pairs}) != len(pairs):
        parser.error("run NAMEs must be unique")
    runs = {name: json.loads(Path(path).read_text()) for name, path in pairs}
    args.output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "sans-serif", "font.size": 10, "text.color": INK})
    recall_precision(runs, args.output / "recall_precision.png")
    miss_causes(*list(runs.items())[-1], args.output / "miss_causes.png")
    print(f"Wrote {args.output / 'recall_precision.png'} and {args.output / 'miss_causes.png'}")


if __name__ == "__main__":
    main()
