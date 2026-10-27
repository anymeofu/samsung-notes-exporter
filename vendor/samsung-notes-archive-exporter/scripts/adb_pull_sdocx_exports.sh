#!/usr/bin/env bash
set -euo pipefail

ADB="${ADB:-adb}"
BATCH_NAME="${BATCH_NAME:-manual_batch}"
OUT_ROOT="${OUT_ROOT:-input_exports}"

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

require_device() {
  local device_count
  device_count="$("$ADB" devices | awk 'NR > 1 && $2 == "device" { count++ } END { print count + 0 }')"
  if [[ "$device_count" -eq 0 ]]; then
    echo "ERROR: no authorized Android device detected." >&2
    echo "Connect the phone, enable USB debugging, and approve the computer on the device." >&2
    exit 2
  fi
}

usage() {
  cat <<'EOF'
Usage:
  BATCH_NAME=batch_001 ./scripts/adb_pull_sdocx_exports.sh /sdcard/Documents/Notes_260101_120000.sdocx [...]

Copy-only pulls exact .sdocx paths from the device into:
  input_exports/<BATCH_NAME>/

This script does not delete, move, open, or inspect note contents.
EOF
}

require_adb

if [[ "$#" -eq 0 ]]; then
  usage >&2
  exit 64
fi

for remote_path in "$@"; do
  case "$remote_path" in
    *.sdocx | *.SDOCX) ;;
    *)
      echo "ERROR: refusing non-.sdocx path: $remote_path" >&2
      exit 65
      ;;
  esac
done

require_device

out_dir="$OUT_ROOT/$BATCH_NAME"
mkdir -p "$out_dir"

printf 'Copy-only pulling %s file(s) into %s\n' "$#" "$out_dir"

for remote_path in "$@"; do
  "$ADB" pull "$remote_path" "$out_dir/"
done

printf '\nPulled files:\n'
find "$out_dir" -maxdepth 1 -type f -name '*.sdocx' -print | sort
