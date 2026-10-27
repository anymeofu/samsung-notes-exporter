#!/usr/bin/env bash
set -euo pipefail

NOTES_PACKAGE="${NOTES_PACKAGE:-com.samsung.android.app.notes}"
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

adb_shell() {
  "$ADB" shell "$@"
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
Read-only Samsung Notes device probe.

This script prints device/package facts only. It does not copy files, modify
device data, open note contents, or access Samsung Cloud.
NOTICE

section "ADB devices"
"$ADB" devices
require_device

section "Device properties"
printf 'manufacturer: '
adb_shell getprop ro.product.manufacturer | tr -d '\r'
printf 'model: '
adb_shell getprop ro.product.model | tr -d '\r'
printf 'android_release: '
adb_shell getprop ro.build.version.release | tr -d '\r'

section "Note-related packages"
adb_shell pm list packages | grep -i note || true

section "Samsung Notes package summary"
if adb_shell pm path "$NOTES_PACKAGE" >/dev/null 2>&1; then
  adb_shell dumpsys package "$NOTES_PACKAGE" \
    | sed -n \
      -e '/Package \[/p' \
      -e '/versionCode=/p' \
      -e '/versionName=/p' \
      -e '/firstInstallTime=/p' \
      -e '/lastUpdateTime=/p' \
      -e '/targetSdk=/p' \
      -e '/requested permissions:/,/install permissions:/p'
else
  echo "Package not found: $NOTES_PACKAGE"
fi

section "Private app directory permission probe"
cat <<EOF
Checking only whether private paths are visible. This does not copy or read
database files.
EOF
adb_shell ls -ld "/data/data/$NOTES_PACKAGE" 2>&1 || true

section "run-as permission probe"
adb_shell run-as "$NOTES_PACKAGE" pwd 2>&1 || true

section "Done"
cat <<'EOF'
Summarize safe facts in docs/device_probe.md. Do not paste full private output
or personal note data into project docs.
EOF
