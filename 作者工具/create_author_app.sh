#!/bin/bash
# 作者版 .app —— python3 直跑，无终端，翻译正常
TOOLS_DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$TOOLS_DIR/说AI懂的话-作者版.app"

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundleIdentifier</key>
    <string>com.sayai.author</string>
    <key>CFBundleName</key>
    <string>说AI懂的话-作者版</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/launcher" << 'LAUNCHER'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$(dirname "$(dirname "$DIR")")"
cd "$TOOLS"
exec /usr/bin/python3 "$TOOLS/PromptBridge.py" &
LAUNCHER

chmod +x "$APP/Contents/MacOS/launcher"
echo "✅ 作者版 .app 就绪: $APP"
