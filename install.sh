#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
UUID="gnome-cursor-usage@local"
EXT_SRC="$ROOT/gnome-extension/$UUID"
EXT_DST="$HOME/.local/share/gnome-shell/extensions/$UUID"
LEGACY_UUIDS=(cursor-usage@rodrigota cursor-usage@local)
ZIP="$ROOT/gnome-extension/${UUID}.zip"
AUTOSTART_DIR="$HOME/.config/autostart"
CONFIG_DIR="$HOME/.config/gnome-cursor-usage"
CACHE_DIR="$HOME/.cache/gnome-cursor-usage"
DAEMON_LOG="$CACHE_DIR/daemon.log"
BIN="$ROOT/bin/gnome-cursor-usage"
DAEMON_MATCH="gnome-cursor-usage --daemon"
LEGACY_DAEMON_PATTERNS=(
  "cursor-usage-indicator --daemon"
  "cursor_usage_indicator --daemon"
  "gnome_cursor_usage --daemon"
)

chmod +x "$BIN"

echo "==> Binary path (extension)"
mkdir -p "$CONFIG_DIR"
printf '%s\n' "$BIN" > "$CONFIG_DIR/bin-path"
echo "    $CONFIG_DIR/bin-path"

read -r REFRESH_INTERVAL_SEC CACHE_POLL_SEC <<EOF
$(PYTHONPATH="$ROOT" /usr/bin/python3 -c "
from gnome_cursor_usage.constants import REFRESH_INTERVAL_SEC, CACHE_POLL_SEC
print(REFRESH_INTERVAL_SEC, CACHE_POLL_SEC)
")
EOF
echo "==> Intervals (constants.py): refresh=${REFRESH_INTERVAL_SEC}s  cache_poll=${CACHE_POLL_SEC}s"

echo "==> Initial cache"
"$BIN" --write-cache

echo "==> GNOME Shell extension ($UUID)"
for old in "${LEGACY_UUIDS[@]}"; do
  rm -rf "$HOME/.local/share/gnome-shell/extensions/$old"
done
rm -f "$AUTOSTART_DIR/cursor-usage-indicator-daemon.desktop"
mkdir -p "$(dirname "$EXT_DST")"
rm -rf "$EXT_DST"
cp -a "$EXT_SRC" "$EXT_DST"
chmod -R a+rX "$EXT_DST"

rm -f "$ZIP"
(
  cd "$ROOT/gnome-extension"
  zip -qr "$(basename "$ZIP")" "$UUID"
)

if command -v gnome-extensions >/dev/null 2>&1; then
  gnome-extensions install --force "$ZIP" 2>/dev/null || true
  gnome-extensions enable "$UUID" 2>/dev/null || true
fi

echo "==> Daemon autostart"
mkdir -p "$AUTOSTART_DIR" "$CACHE_DIR"
cat > "$AUTOSTART_DIR/gnome-cursor-usage-daemon.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=GNOME Cursor Usage Daemon
Comment=Refreshes Cursor usage cache for the GNOME panel extension
Exec=$BIN --daemon --interval $REFRESH_INTERVAL_SEC
Terminal=false
Hidden=false
X-GNOME-Autostart-enabled=true
EOF

echo "==> Restart daemon"
for pat in "${LEGACY_DAEMON_PATTERNS[@]}" "$DAEMON_MATCH"; do
  pkill -f "$pat" 2>/dev/null || true
done
sleep 2
for pat in "${LEGACY_DAEMON_PATTERNS[@]}" "$DAEMON_MATCH"; do
  if pgrep -f "$pat" >/dev/null; then
    pkill -9 -f "$pat" 2>/dev/null || true
  fi
done
sleep 1
nohup "$BIN" --daemon --interval "$REFRESH_INTERVAL_SEC" \
  >>"$DAEMON_LOG" 2>&1 &
sleep 0.5
if pgrep -f "gnome_cursor_usage --daemon" >/dev/null; then
  echo "    daemon running (log: $DAEMON_LOG)"
else
  echo "    warning: daemon did not start — see $DAEMON_LOG"
fi

echo "==> Reload panel extension"
reload_ok=0
if command -v gnome-extensions >/dev/null 2>&1; then
  if gnome-extensions disable "$UUID" 2>/dev/null && gnome-extensions enable "$UUID" 2>/dev/null; then
    reload_ok=1
    echo "    extension reloaded (disable/enable)."
  fi
fi
if [[ "$reload_ok" -eq 0 ]]; then
  echo "    Alt+F2 → r → Enter if the panel does not update."
fi

echo ""
echo "Done."
echo "  • Extension: Cursor Usage ($UUID)"
echo "  • Test: $ROOT/bin/gnome-cursor-usage --fetch"
