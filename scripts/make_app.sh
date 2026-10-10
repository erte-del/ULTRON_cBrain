#!/bin/bash
# Build Ultron.app in the project folder.
#   scripts/make_app.sh
# Run it again if you move the project folder (the app remembers where it is).
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/Ultron.app"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

chmod +x "$ROOT/scripts/start_ultron.sh" "$ROOT/scripts/stop_ultron.sh"

# The app itself: a menu bar app (scripts/Ultron.swift; needs the Xcode command line
# tools: xcode-select --install). LSUIElement keeps it
# out of the Dock.
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O "$ROOT/scripts/Ultron.swift" -o "$APP/Contents/MacOS/Ultron"
cat >"$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleIdentifier</key><string>local.ultron.app</string>
	<key>CFBundleName</key><string>Ultron</string>
	<key>CFBundleExecutable</key><string>Ultron</string>
	<key>CFBundleIconFile</key><string>Ultron</string>
	<key>CFBundlePackageType</key><string>APPL</string>
	<key>CFBundleVersion</key><string>1</string>
	<key>LSUIElement</key><true/>
	<key>NSScreenCaptureUsageDescription</key><string>Ultron looks at your screen when you ask it about what you see.</string>
</dict>
</plist>
EOF
plutil -insert UltronRoot -string "$ROOT" "$APP/Contents/Info.plist"

# Its icon in Finder: the purple orb.
"$ROOT/backend/.venv/bin/python" "$ROOT/scripts/make_icon.py" "$TMP/Ultron.iconset"
iconutil -c icns "$TMP/Ultron.iconset" -o "$APP/Contents/Resources/Ultron.icns"

# Sign it locally: macOS won't open an unsigned app on Apple silicon. With the certificate from
# scripts/make_cert.sh the app keeps the same identity on every rebuild, so macOS remembers its
# Screen Recording permission. Without it, "ad hoc" works but macOS asks for that permission again.
if security find-certificate -c "Ultron Local Signing" >/dev/null 2>&1; then
  codesign --force --sign "Ultron Local Signing" "$APP"
else
  echo "No signing certificate: run scripts/make_cert.sh once so macOS stops asking for Screen Recording." >&2
  codesign --force --sign - "$APP"
fi
codesign --verify "$APP"
touch "$APP"  # tells Finder to pick up the new icon

echo "Built $APP"
