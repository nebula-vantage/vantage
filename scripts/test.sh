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

# Signing lives in ios/Config/Local.xcconfig. A team or bundle ID in the shared project file
# (e.g. from Xcode's Signing & Capabilities tab) would override everyone's local settings.
echo "== ios project: no hard-coded signing"
if grep -nE "DEVELOPMENT_TEAM|PRODUCT_BUNDLE_IDENTIFIER" ios/VantageMobile.xcodeproj/project.pbxproj; then
    echo "Move these settings to ios/Config/Local.xcconfig (see ios/README.md)." >&2
    status=1
fi

if [ "$(uname)" = "Darwin" ]; then
    # Prefer full Xcode over the Command Line Tools (no XCTest) unless DEVELOPER_DIR is set.
    if [ -z "${DEVELOPER_DIR:-}" ] && [ -d /Applications/Xcode.app ]; then
        export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
    fi
    # Everyone builds with the Xcode in .xcode-version (CI does too); different compilers
    # have disagreed on this code before.
    want="$(cat .xcode-version)"
    have="$(xcodebuild -version 2>/dev/null | awk 'NR==1 {print $2}' || true)"
    if [ "$have" != "$want" ]; then
        echo "warning: this repo uses Xcode $want (.xcode-version) but you have Xcode ${have:-none}." >&2
    fi
    run "ios/VantageKit (swift test)" bash -c \
        'cd ios/VantageKit && swift test --scratch-path "$HOME/Library/Caches/VantageKit-build"'
else
    echo "== ios/VantageKit (swift test): skipped, needs macOS with Xcode"
fi

exit "$status"
