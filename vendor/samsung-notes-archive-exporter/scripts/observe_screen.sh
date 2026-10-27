#!/usr/bin/env bash
set -euo pipefail

LABEL="${1:-screen}"
LEVEL="${LEVEL:-0}"
MAX_CANDIDATES="${MAX_CANDIDATES:-35}"
OUT_DIR="${OUT_DIR:-observations}"
PRINT_MODE="${PRINT_MODE:-summary}"

args=(
  --label "$LABEL"
  --level "$LEVEL"
  --max-candidates "$MAX_CANDIDATES"
  --out-dir "$OUT_DIR"
  --print-mode "$PRINT_MODE"
)

if [[ -n "${LAST_ACTION:-}" ]]; then
  args+=(--last-action "$LAST_ACTION")
fi

if [[ -n "${TASK_STATE:-}" ]]; then
  args+=(--task-state "$TASK_STATE")
fi

PYTHONPATH="${PYTHONPATH:-src}" python3 -m sn_archive_exporter.visual_observer "${args[@]}"
