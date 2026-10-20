#!/bin/bash
# Runs every test suite in the repository from one command:
#   scripts/test.sh
# Python suites run anywhere after `uv sync`. VantageKit's Swift tests need macOS with Xcode
# (Core ML, Vision, AVFoundation): they are skipped on other systems and fail the run on a
# Mac without Xcode, so a passing run on a Mac always includes the tracker parity tests.
# SwiftPM's scratch path lives outside the iCloud-synced ~/Documents tree, where codesigning
# the test bundle otherwise fails ("resource fork ... detritus").
set -uo pipefail
cd "$(dirname "$0")/.."  # repository root
status=0

run() {
    echo "== $1"
    shift
    "$@" || status=1
}

# --locked fails instead of silently rewriting uv.lock when pyproject.toml changed without it.
run "pipeline (python)" uv run --locked python -m unittest discover -s pipeline/tests
run "ml (python)" uv run --locked python -m unittest discover -s ml
run "tools/coreml (python)" uv run --locked python -m unittest discover -s tools/coreml

if [ "$(uname)" = "Darwin" ]; then
    # Prefer full Xcode over the Command Line Tools (no XCTest) unless DEVELOPER_DIR is set.
    if [ -z "${DEVELOPER_DIR:-}" ] && [ -d /Applications/Xcode.app ]; then
        export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
    fi
    run "ios/VantageKit (swift test)" bash -c \
        'cd ios/VantageKit && swift test --scratch-path "$HOME/Library/Caches/VantageKit-build"'
else
    echo "== ios/VantageKit (swift test): skipped, needs macOS with Xcode"
fi

exit "$status"
