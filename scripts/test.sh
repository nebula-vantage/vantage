#!/bin/bash
# Runs all mobile tests: VantageKit Swift tests (tracker parity with the desktop Python
# tracker, behavior, timeline) and the Python model-tooling tests.
# SwiftPM's scratch path lives outside the iCloud-synced ~/Documents tree, where
# codesigning the test bundle otherwise fails ("resource fork ... detritus").
set -euo pipefail
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
cd "$(dirname "$0")/../.."  # repository root
echo "== VantageKit (swift test)"
(cd mobile/ios/VantageKit && swift test --scratch-path "$HOME/Library/Caches/VantageKit-build" 2>&1 \
  | grep -E "error|failed|Executed .* tests" | tail -5)
echo "== mobile/model (python)"
.venv/bin/python -m unittest discover -s mobile/model 2>&1 | tail -3
