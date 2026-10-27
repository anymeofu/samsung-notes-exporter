from __future__ import annotations

import unittest

from sn_archive_exporter.recovery_policy import decide_recovery_action


class RecoveryPolicyTests(unittest.TestCase):
    def test_exports_when_stable_unseen_notes_are_available(self) -> None:
        self.assertEqual(
            decide_recovery_action({"recommended_select_count": 2}, empty_scrolls=0, max_empty_scrolls=3),
            {"action": "export", "reason": "stable_unseen_notes_available"},
        )

    def test_stops_on_repeated_screen(self) -> None:
        self.assertEqual(
            decide_recovery_action(
                {"recommended_select_count": 0},
                empty_scrolls=0,
                max_empty_scrolls=3,
                repeated_screen_count=2,
                max_repeated_screens=2,
            ),
            {"action": "stop", "reason": "screen_repeated"},
        )

    def test_stops_on_empty_scroll_limit(self) -> None:
        self.assertEqual(
            decide_recovery_action({"recommended_select_count": 0}, empty_scrolls=3, max_empty_scrolls=3),
            {"action": "stop", "reason": "empty_scroll_limit"},
        )

    def test_nudges_edge_only_missing_notes(self) -> None:
        self.assertEqual(
            decide_recovery_action(
                {
                    "recommended_select_count": 0,
                    "gap": {"target_missing_count": 10, "edge_only_missing_count": 2},
                },
                empty_scrolls=0,
                max_empty_scrolls=3,
            ),
            {"action": "nudge", "reason": "edge_only_missing_notes_visible"},
        )

    def test_nudges_when_target_missing_is_not_visible(self) -> None:
        self.assertEqual(
            decide_recovery_action(
                {
                    "recommended_select_count": 0,
                    "gap": {"target_missing_count": 10, "edge_only_missing_count": 0},
                },
                empty_scrolls=0,
                max_empty_scrolls=3,
            ),
            {"action": "nudge", "reason": "target_missing_notes_not_visible"},
        )


if __name__ == "__main__":
    unittest.main()
