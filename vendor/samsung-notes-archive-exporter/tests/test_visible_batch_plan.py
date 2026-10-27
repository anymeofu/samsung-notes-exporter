import unittest
from unittest import mock

from sn_archive_exporter.visible_batch_plan import main, plan_visible_batch


class VisibleBatchPlanTests(unittest.TestCase):
    def test_plan_visible_batch_counts_safe_unseen_cards(self):
        summary = {
            "folder_path": "TestTasting/커피",
            "note_card_count": 4,
            "subfolder_count": 0,
            "note_cards": [
                {"bounds": "[24,529][540,1139]", "fingerprint": "a"},
                {"bounds": "[540,529][1056,1139]", "fingerprint": "b"},
                {"bounds": "[24,1181][540,1791]", "fingerprint": "c"},
                {"bounds": "[24,1937][540,2340]", "fingerprint": "d"},
            ],
        }

        plan = plan_visible_batch(summary, seen_fingerprints={"b"}, max_count=10)

        self.assertEqual(plan["visible_note_count"], 4)
        self.assertEqual(plan["safe_unseen_note_count"], 2)
        self.assertEqual(plan["recommended_select_count"], 2)
        self.assertEqual(plan["selected_fingerprints"], ["a", "c"])
        self.assertEqual(plan["skipped_seen_count"], 1)
        self.assertEqual(plan["skipped_unsafe_count"], 1)

    def test_plan_visible_batch_respects_max_count(self):
        summary = {
            "folder_path": "Codex",
            "note_card_count": 2,
            "subfolder_count": 0,
            "note_cards": [
                {"bounds": "[24,529][540,1139]", "fingerprint": "a"},
                {"bounds": "[540,529][1056,1139]", "fingerprint": "b"},
            ],
        }

        plan = plan_visible_batch(summary, max_count=1)

        self.assertEqual(plan["recommended_select_count"], 1)
        self.assertEqual(plan["selected_fingerprints"], ["a"])

    def test_plan_visible_batch_caps_default_recommendation_below_100(self):
        summary = {
            "folder_path": "Codex",
            "note_card_count": 120,
            "subfolder_count": 0,
            "note_cards": [
                {"bounds": "[24,529][540,1139]", "fingerprint": f"note-{index}"}
                for index in range(120)
            ],
        }

        plan = plan_visible_batch(summary)

        self.assertEqual(plan["safe_unseen_note_count"], 120)
        self.assertEqual(plan["recommended_select_count"], 99)
        self.assertEqual(plan["max_export_selection_count"], 99)

    def test_plan_visible_batch_caps_explicit_max_count_at_export_limit(self):
        summary = {
            "folder_path": "Codex",
            "note_card_count": 120,
            "subfolder_count": 0,
            "note_cards": [
                {"bounds": "[24,529][540,1139]", "fingerprint": f"note-{index}"}
                for index in range(120)
            ],
        }

        plan = plan_visible_batch(summary, max_count=150)

        self.assertEqual(plan["recommended_select_count"], 99)

    def test_main_requires_run_id_with_state(self):
        with self.assertRaises(SystemExit) as raised:
            main(["--xml", "screen.xml", "--allowed-path", "Codex", "--state", "state.json"])

        self.assertIn("--state requires --run-id", str(raised.exception))

    def test_main_combines_state_and_cli_seen_fingerprints(self):
        summary = {
            "packages": ["com.samsung.android.app.notes"],
            "is_samsung_notes_visible": True,
            "folder_path": "Codex",
            "note_card_count": 2,
            "subfolder_count": 0,
            "note_cards": [
                {"bounds": "[24,529][540,1139]", "fingerprint": "a"},
                {"bounds": "[540,529][1056,1139]", "fingerprint": "b"},
            ],
        }

        with mock.patch("sn_archive_exporter.visible_batch_plan.ui_guard.summarize", return_value=summary), mock.patch(
            "sn_archive_exporter.visible_batch_plan.ui_guard.assert_allowed_path"
        ), mock.patch(
            "sn_archive_exporter.visible_batch_plan.load_state",
            return_value={"run_id": "run", "folder_path": "Codex", "seen_fingerprints": ["a"]},
        ), mock.patch(
            "sn_archive_exporter.visible_batch_plan.print"
        ) as printed:
            main(
                [
                    "--xml",
                    "screen.xml",
                    "--allowed-path",
                    "Codex",
                    "--state",
                    "state.json",
                    "--run-id",
                    "run",
                    "--seen-fingerprint",
                    "b",
                ]
            )

        self.assertIn('"recommended_select_count": 0', printed.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
