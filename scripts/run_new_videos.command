#!/bin/bash
set -u
cd '/Users/muneebfarrukh/Documents/4A.nosync/vantage.nosync' || exit 1
failures=0
printf 'Processing three videos locally, one at a time.\n'
printf 'For each new camera view, click the OUTER court corners:\nnear-left, near-right, far-right, far-left. Press Enter to start.\n\n'
for input in assets/backcorner60fps.mov assets/topcorner60fps.mov assets/sideview.MOV; do
    filename="${input##*/}"
    name="${filename%.*}"
    output="output/$name"
    mkdir -p "$output" || exit 1
    printf '\nProcessing %s\nOutputs: %s\n' "$input" "$output"
    printf 'RUNNING\n' > "$output/status.txt"
    if .venv/bin/python main.py --input "$input" --output-dir "$output" > "$output/run-stats.json" 2> >(tee "$output/run.log" >&2); then
        printf 'COMPLETED\n' > "$output/status.txt"
        printf 'Completed: %s\n' "$input"
    else
        result=$?
        printf 'FAILED (exit %s)\n' "$result" > "$output/status.txt"
        printf 'Failed: %s. See %s/run.log\n' "$input" "$output"
        failures=$((failures + 1))
        if [ "$result" -eq 130 ]; then
            printf 'Batch cancelled.\n'
            exit 130
        fi
    fi
done
printf '\nBatch finished: %s failed. Results are under output/<video-name>/.\n' "$failures"
read -r -p 'Press Enter to close this terminal job.' ignored
exit "$failures"
