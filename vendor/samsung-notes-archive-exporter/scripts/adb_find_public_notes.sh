#!/usr/bin/env bash
set -euo pipefail

ADB="${ADB:-adb}"

detect_adb() {
  if command -v "$ADB" >/dev/null 2>&1; then
    return 0
  fi

  for candidate in \
    "$HOME/Library/Android/sdk/platform-tools/adb" \
    "/opt/homebrew/bin/adb" \
    "/usr/local/bin/adb"; do
    if [[ -x "$candidate" ]]; then
      ADB="$candidate"
      return 0
    fi
  done

  return 1
}

require_adb() {
  if ! detect_adb; then
    echo "ERROR: adb not found in PATH." >&2
    echo "Set ADB=/path/to/adb or install Android platform tools." >&2
    exit 127
  fi
}

section() {
  printf '\n== %s ==\n' "$1"
}

require_device() {
  local device_count
  device_count="$("$ADB" devices | awk 'NR > 1 && $2 == "device" { count++ } END { print count + 0 }')"
  if [[ "$device_count" -eq 0 ]]; then
    echo "ERROR: no authorized Android device detected." >&2
    echo "Connect the phone, enable USB debugging, and approve the computer on the device." >&2
    exit 2
  fi
}

require_adb

cat <<'NOTICE'
Read-only public storage filename search.

This script lists paths only. It does not open, copy, move, delete, or inspect
file contents.
NOTICE

SEARCH_ROOTS=(
  "/sdcard"
  "/sdcard/Download"
  "/sdcard/Documents"
  "/sdcard/Android/media"
  "/sdcard/Samsung"
)

FIND_EXPR='-iname "*.sdocx" -o -iname "*.sdoc" -o -iname "*.spd" -o -iname "*.pdf" -o -iname "*.docx" -o -iname "*Samsung*Notes*" -o -iname "*notes*"'

section "ADB devices"
"$ADB" devices
require_device

section "Public storage path candidates"
for root in "${SEARCH_ROOTS[@]}"; do
  printf '\n-- %s --\n' "$root"
  "$ADB" shell "if [ -d '$root' ]; then find '$root' -maxdepth 6 -type f \\( $FIND_EXPR \\) -print 2>/dev/null; else echo 'missing'; fi" \
    | tr -d '\r' \
    | sed '/^$/d'
done

section "Done"
cat <<'EOF'
Record only a summary in docs/device_probe.md unless the user explicitly
approves storing path lists.
EOF
