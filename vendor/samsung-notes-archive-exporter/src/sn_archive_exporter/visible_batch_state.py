from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def empty_state(*, run_id: str, folder_path: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "folder_path": folder_path,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seen_fingerprints": [],
        "batches": [],
    }


def load_state(path: Path, *, run_id: str, folder_path: str) -> dict[str, Any]:
    if not path.exists():
        return empty_state(run_id=run_id, folder_path=folder_path)
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("run_id") != run_id:
        raise SystemExit(f"Refusing state: run_id mismatch in {path}")
    if state.get("folder_path") != folder_path:
        raise SystemExit(f"Refusing state: folder_path mismatch in {path}")
    return state


def mark_seen(state: dict[str, Any], fingerprints: list[str], *, batch_id: str, note: str | None = None) -> dict[str, Any]:
    seen = list(state.get("seen_fingerprints") or [])
    seen_set = set(seen)
    added = []
    for fingerprint in fingerprints:
        if fingerprint and fingerprint not in seen_set:
            seen.append(fingerprint)
            seen_set.add(fingerprint)
            added.append(fingerprint)
    state["seen_fingerprints"] = seen
    state.setdefault("batches", []).append(
        {
            "batch_id": batch_id,
            "marked_at": datetime.now(timezone.utc).isoformat(),
            "fingerprint_count": len(fingerprints),
            "new_fingerprint_count": len(added),
            "note": note,
        }
    )
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Maintain local visible-batch fingerprint state.")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--folder-path", required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--fingerprint", action="append", default=[])
    parser.add_argument("--note")
    args = parser.parse_args(argv)

    state = load_state(args.state, run_id=args.run_id, folder_path=args.folder_path)
    state = mark_seen(state, args.fingerprint, batch_id=args.batch_id, note=args.note)
    save_state(args.state, state)
    print(
        json.dumps(
            {
                "state": str(args.state),
                "run_id": state["run_id"],
                "folder_path": state["folder_path"],
                "seen_fingerprint_count": len(state["seen_fingerprints"]),
                "batch_count": len(state["batches"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
