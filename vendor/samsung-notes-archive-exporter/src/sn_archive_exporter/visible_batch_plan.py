from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import ui_guard
from .guarded_export_driver import note_card_is_selectable
from .selection_limits import MAX_EXPORT_SELECTION_COUNT
from .visible_batch_state import load_state


def plan_visible_batch(
    summary: dict[str, Any],
    *,
    seen_fingerprints: set[str] | frozenset[str] | None = None,
    max_count: int | None = None,
) -> dict[str, Any]:
    seen_fingerprints = seen_fingerprints or set()
    selectable_cards = [
        card for card in summary.get("note_cards", []) if note_card_is_selectable(card, seen_fingerprints)
    ]
    requested_limit = MAX_EXPORT_SELECTION_COUNT if max_count is None else min(max_count, MAX_EXPORT_SELECTION_COUNT)
    requested_count = min(requested_limit, len(selectable_cards))
    selected_cards = selectable_cards[:requested_count]
    return {
        "folder_path": summary.get("folder_path", ""),
        "visible_note_count": summary.get("note_card_count", 0),
        "visible_subfolder_count": summary.get("subfolder_count", 0),
        "safe_unseen_note_count": len(selectable_cards),
        "recommended_select_count": requested_count,
        "max_export_selection_count": MAX_EXPORT_SELECTION_COUNT,
        "selected_fingerprints": [
            card.get("fingerprint") for card in selected_cards if card.get("fingerprint")
        ],
        "skipped_seen_count": sum(
            1
            for card in summary.get("note_cards", [])
            if card.get("fingerprint") and card.get("fingerprint") in seen_fingerprints
        ),
        "skipped_unsafe_count": sum(
            1
            for card in summary.get("note_cards", [])
            if card.get("fingerprint") not in seen_fingerprints
            and not note_card_is_selectable(card, seen_fingerprints)
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan a safe visible-note Samsung Notes export batch.")
    parser.add_argument("--xml", type=Path, required=True)
    parser.add_argument("--allowed-path", required=True)
    parser.add_argument("--seen-fingerprint", action="append", default=[])
    parser.add_argument("--state", type=Path, help="Optional visible-batch state JSON to read seen fingerprints from.")
    parser.add_argument("--run-id", help="Required with --state.")
    parser.add_argument("--max-count", type=int)
    args = parser.parse_args(argv)
    if args.state and not args.run_id:
        raise SystemExit("Refusing action: --state requires --run-id")

    summary = ui_guard.summarize(args.xml, [args.allowed_path])
    if not summary["is_samsung_notes_visible"]:
        raise SystemExit(f"Refusing action: Samsung Notes is not visible. Packages: {summary['packages']}")
    ui_guard.assert_allowed_path(summary["folder_path"], [args.allowed_path])
    if args.max_count is not None and args.max_count < 1:
        raise SystemExit("Refusing action: --max-count must be positive")

    seen_fingerprints = set(args.seen_fingerprint)
    if args.state:
        state = load_state(args.state, run_id=args.run_id, folder_path=args.allowed_path)
        seen_fingerprints.update(state.get("seen_fingerprints") or [])

    plan = plan_visible_batch(
        summary,
        seen_fingerprints=frozenset(seen_fingerprints),
        max_count=args.max_count,
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
