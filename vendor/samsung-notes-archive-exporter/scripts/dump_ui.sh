#!/usr/bin/env bash
set -euo pipefail

NOTES_PACKAGE="${NOTES_PACKAGE:-com.samsung.android.app.notes}"
LABEL="${1:-ui_dump}"
OUT_DIR="${OUT_DIR:-ui_dumps}"
REMOTE_XML="/sdcard/window_dump.xml"
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

safe_label() {
  printf '%s' "$1" | tr -c '[:alnum:]_.-' '_'
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
mkdir -p "$OUT_DIR"

SAFE_LABEL="$(safe_label "$LABEL")"
LOCAL_XML="$OUT_DIR/${SAFE_LABEL}.xml"

cat <<'NOTICE'
Read-only UI hierarchy dump helper.

Legacy raw UI hierarchy dump helper.

Prefer scripts/observe_screen.sh for normal screenshot-first observation.
This script can launch Samsung Notes if requested with LAUNCH_NOTES=1, then
dumps the currently visible UI hierarchy. UI dumps may contain private folder
or note titles. Keep them local unless scrubbed or explicitly approved.
NOTICE

section "ADB devices"
"$ADB" devices
require_device

if [[ "${LAUNCH_NOTES:-0}" == "1" ]]; then
  section "Launch Samsung Notes"
  "$ADB" shell monkey -p "$NOTES_PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null
  sleep "${LAUNCH_WAIT_SECONDS:-2}"
fi

section "Dump visible UI hierarchy"
"$ADB" shell uiautomator dump "$REMOTE_XML"

section "Pull dump"
"$ADB" pull "$REMOTE_XML" "$LOCAL_XML" >/dev/null
printf 'Wrote %s\n' "$LOCAL_XML"

section "Local summary"
if [[ "${SUMMARY_LINES:-0}" -gt 0 ]]; then
  grep -Eo 'text="[^"]*"|resource-id="[^"]*"|content-desc="[^"]*"' "$LOCAL_XML" \
    | sed 's/^/  /' \
    | head -n "${SUMMARY_LINES:-120}" || true
else
  echo "Skipped by default. Set SUMMARY_LINES=N only for local debugging."
fi

cat <<'EOF'

Review the XML locally and summarize observed controls in
docs/samsung_notes_ui_map.md under Known / Unknown / Risk.
EOF
