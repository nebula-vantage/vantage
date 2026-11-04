#!/bin/bash
# Scores ball tracking on the CI eval suite for this checkout and, optionally, a base commit, and
# writes a Markdown comparison (what .github/workflows/eval.yml posts on pull requests):
#   scripts/eval_pr.sh [BASE_REF] [OUTPUT_DIR]        e.g. scripts/eval_pr.sh origin/main
# Writes OUTPUT_DIR (default reports/eval-pr)/{head,base}.json and report.md.
#
# Both runs score the same downloaded clips and labels and share the detection cache (keyed by the
# model, the detection code, and library versions), so a change that keeps those only re-scores
# (seconds). The base runs with its own pipeline code (tracker, config), evaluator, and default
# model weights, through a temporary git worktree; with its own environment if uv.lock differs.
# The checkout is scored as it is, uncommitted changes included.
set -uo pipefail
cd "$(dirname "$0")/.."  # repository root
BASE_REF=${1:-}
OUT=${2:-reports/eval-pr}
CACHE=${EVAL_CACHE_DIR:-reports/external-eval}
case "$CACHE" in /*) ;; *) CACHE="$PWD/$CACHE" ;; esac
mkdir -p "$OUT"
rm -f "$OUT/head.json" "$OUT/base.json" "$OUT/report.md"

# A host that is down only removes its source from both runs; the report says which.
uv run --locked python ml/fetch_eval_data.py --suite ci || echo "Some eval sources could not be downloaded." >&2
uv run --locked python ml/evaluate_external.py --suite ci --cache-dir "$CACHE" --json > "$OUT/head.json" || exit 1

head_label="this change ($(git rev-parse --short HEAD))"
base_args=()
if [ -n "$BASE_REF" ]; then
    base_sha=$(git rev-parse --verify "$BASE_REF^{commit}") || exit 1
    base_dir="$(mktemp -d)/base"
    git worktree add --detach --quiet "$base_dir" "$base_sha" || exit 1
    trap 'git worktree remove --force "$base_dir"' EXIT
    ln -s "$PWD/ml/external" "$base_dir/ml/external"  # the same clips and labels
    if git diff --quiet "$base_sha" HEAD -- uv.lock; then
        # Same dependencies: reuse this environment; PYTHONPATH puts the base's vantage package
        # ahead of this checkout's installed one.
        run_base=(env PYTHONPATH="$base_dir/pipeline" uv run --locked python)
    else
        run_base=(uv run --locked --project "$base_dir" python)
    fi
    # The base's progress goes to the log too (it detects again if its model or detection code differs).
    if "${run_base[@]}" "$base_dir/ml/evaluate_external.py" --suite ci --cache-dir "$CACHE" --json \
            > "$OUT/base.json" 2> >(tee "$OUT/base.err" >&2); then
        base_args=(--base "$OUT/base.json" --base-label "${EVAL_BASE_LABEL:-$BASE_REF} ($(git rev-parse --short "$base_sha"))")
    else
        if grep -q -- "--suite" "$base_dir/ml/evaluate_external.py" 2>/dev/null; then
            reason="the base could not be scored (see the log)"
        else
            reason="the base predates this check"
        fi
        echo "::warning::No comparison: $reason." >&2
        base_args=(--base-error "$reason")
    fi
fi
uv run --locked python ml/compare_eval.py --head "$OUT/head.json" --head-label "${EVAL_HEAD_LABEL:-$head_label}" \
    ${base_args[@]+"${base_args[@]}"} > "$OUT/report.md" || exit 1  # bash 3.2-safe empty array
echo "Wrote $OUT/report.md" >&2
