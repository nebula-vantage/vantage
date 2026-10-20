#!/bin/bash
# Build, sign (free Personal Team), install, and launch VantageMobile on a USB/Wi-Fi paired iPhone.
# DerivedData lives OUTSIDE ~/Documents: iCloud-synced folders add extended attributes that make
# codesign fail with "resource fork, Finder information, or similar detritus not allowed".
set -euo pipefail
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
cd "$(dirname "$0")/../.."  # repository root
BUNDLE_ID=com.vantage.detectorprototype
DERIVED="$HOME/Library/Developer/Xcode/DerivedData/VantageMobile-device"
DEVICE="${1:-$(xcrun devicectl list devices 2>/dev/null | awk '/physical/ && (/available/ || /connected/) && /iPhone/ {for(i=1;i<=NF;i++) if ($i ~ /^[0-9A-F]{8}-[0-9A-F]{16}$/) print $i}' | head -1)}"
[ -n "$DEVICE" ] || { echo "No available iPhone. Connect/unlock it, trust this Mac, enable Developer Mode." >&2; exit 1; }
echo "Device: $DEVICE"
xcodebuild -project mobile/ios/VantageMobile.xcodeproj -scheme VantageMobile -configuration Debug \
  -destination "id=$DEVICE" -derivedDataPath "$DERIVED" -allowProvisioningUpdates -quiet build
xcrun devicectl device install app --device "$DEVICE" "$DERIVED/Build/Products/Debug-iphoneos/VantageMobile.app"
xcrun devicectl device process launch --device "$DEVICE" "$BUNDLE_ID" || cat >&2 <<'EOF'

Installed, but could not launch (see the reason above). Common causes:
- "Locked": unlock the iPhone, then tap the app icon.
- "Security"/"not been explicitly trusted" (first install with a free Apple ID): on the iPhone open
  Settings > General > VPN & Device Management > Apple Development: <your email> > Trust.
EOF
