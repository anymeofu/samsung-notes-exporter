from __future__ import annotations

from typing import Any


def decide_recovery_action(
    observation: dict[str, Any],
    *,
    empty_scrolls: int,
    max_empty_scrolls: int,
    repeated_screen_count: int = 0,
    max_repeated_screens: int = 2,
) -> dict[str, Any]:
    recommended = int(observation.get("recommended_select_count") or 0)
    if recommended > 0:
        return {"action": "export", "reason": "stable_unseen_notes_available"}

    if repeated_screen_count >= max_repeated_screens:
        return {"action": "stop", "reason": "screen_repeated"}

    if empty_scrolls >= max_empty_scrolls:
        return {"action": "stop", "reason": "empty_scroll_limit"}

    gap = observation.get("gap") or {}
    if int(gap.get("stable_missing_count") or 0) > 0:
        return {"action": "export", "reason": "stable_missing_notes_available"}
    if int(gap.get("edge_only_missing_count") or 0) > 0:
        return {"action": "nudge", "reason": "edge_only_missing_notes_visible"}
    if int(gap.get("target_missing_count") or 0) > 0:
        return {"action": "nudge", "reason": "target_missing_notes_not_visible"}

    return {"action": "nudge", "reason": "no_stable_unseen_notes_visible"}
