#!/bin/bash
# Build, sign (free Personal Team), install, and launch VantageMobile on a USB/Wi-Fi paired iPhone.
# Signing comes from ios/Config/Local.xcconfig (git-ignored; see ios/README.md).
# DerivedData lives OUTSIDE ~/Documents: iCloud-synced folders add extended attributes that make
# codesign fail with "resource fork, Finder information, or similar detritus not allowed".
set -euo pipefail
export DEVELOPER_DIR="${DEVELOPER_DIR:-/Applications/Xcode.app/Contents/Developer}"
cd "$(dirname "$0")/../.."  # repository root
[ -f ios/Config/Local.xcconfig ] || {
    echo "Missing ios/Config/Local.xcconfig. Copy ios/Config/Local.xcconfig.example and set your" >&2
    echo "team ID and bundle ID suffix (see ios/README.md)." >&2
    exit 1
}
DERIVED="$HOME/Library/Developer/Xcode/DerivedData/VantageMobile-device"
APP="$DERIVED/Build/Products/Debug-iphoneos/VantageMobile.app"
DEVICE="${1:-$(xcrun devicectl list devices 2>/dev/null | awk '/physical/ && (/available/ || /connected/) && !/unavailable/ && /iPhone/ {for(i=1;i<=NF;i++) if ($i ~ /^[0-9A-F]{8}-[0-9A-F]{16}$/) print $i}' | head -1)}"
[ -n "$DEVICE" ] || { echo "No available iPhone. Connect/unlock it, trust this Mac, enable Developer Mode." >&2; exit 1; }
echo "Device: $DEVICE"
xcodebuild -project ios/VantageMobile.xcodeproj -scheme VantageMobile -configuration Debug \
  -destination "id=$DEVICE" -derivedDataPath "$DERIVED" -allowProvisioningUpdates -quiet build
BUNDLE_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$APP/Info.plist")"
xcrun devicectl device install app --device "$DEVICE" "$APP"
xcrun devicectl device process launch --device "$DEVICE" "$BUNDLE_ID" || cat >&2 <<'MSG'

Installed, but could not launch (see the reason above). Common causes:
- "Locked": unlock the iPhone, then tap the app icon.
- "Security"/"not been explicitly trusted" (first install with a free Apple ID): on the iPhone open
  Settings > General > VPN & Device Management > Apple Development: <your email> > Trust.
MSG
