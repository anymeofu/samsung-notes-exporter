import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sn_archive_exporter.visible_batch_runner import VisibleBatchRunConfig, run_visible_batches


class VisibleBatchRunnerTests(unittest.TestCase):
    def make_config(self, tmp_path: Path, *, execute: bool = True) -> VisibleBatchRunConfig:
        return VisibleBatchRunConfig(
            folder_path="TestTasting/커피",
            run_id="run",
            state_path=tmp_path / "state.json",
            input_root=tmp_path / "input",
            archive_root=tmp_path / "archive",
            out_dir=tmp_path / "ui",
            execute=execute,
            max_batches=1,
            max_empty_scrolls=1,
            wait_seconds=0.01,
            allow_existing_output=True,
        )

    def test_run_visible_batches_exports_and_marks_seen(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = self.make_config(tmp_path)
            config = VisibleBatchRunConfig(**{**config.__dict__, "export_format": "txt"})
            plan = {
                "xml": "screen.xml",
                "visible_note_count": 2,
                "safe_unseen_note_count": 2,
                "recommended_select_count": 2,
                "selected_fingerprints": ["a", "b"],
                "skipped_seen_count": 0,
                "skipped_unsafe_count": 0,
            }
            summary = {"note_cards": [{"fingerprint": "a"}, {"fingerprint": "b"}]}
            export_result = {
                "allowed_path": "TestTasting/커피",
                "destination": "Documents",
                "execute": True,
                "select_count": 2,
                "events": [{"action": "confirm_selected_note_count", "selected_count": 2}],
                "workflow": {"phase": "done"},
                "workflow_recent_events": [],
                "exported_files": ["/sdcard/Documents/a.sdocx", "/sdcard/Documents/b.sdocx"],
                "handoff": {"archive_output": str(tmp_path / "archive" / "run" / "batch001_2notes")},
            }

            with mock.patch("sn_archive_exporter.visible_batch_runner.dump_and_plan", return_value=(tmp_path / "screen.xml", plan, summary)), mock.patch(
                "sn_archive_exporter.visible_batch_runner.run_guarded_export", return_value=export_result
            ) as guarded_export:
                result = run_visible_batches(config)

            self.assertEqual(result["seen_fingerprint_count"], 2)
            self.assertEqual(result["batch_count"], 1)
            self.assertEqual(result["new_batches"][0]["batch_id"], "batch001_2notes")
            self.assertEqual(result["export_format"], "txt")
            self.assertEqual(guarded_export.call_args.args[0].export_format, "txt")

    def test_run_visible_batches_rejects_state_from_another_export_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = self.make_config(tmp_path)
            config.state_path.write_text(
                '{"run_id":"run","folder_path":"TestTasting/커피","export_format":"txt","seen_fingerprints":[],"batches":[]}',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "state export_format='txt'"):
                run_visible_batches(config)

    def test_run_visible_batches_scrolls_on_empty_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = self.make_config(tmp_path)
            plan = {
                "xml": "screen.xml",
                "visible_note_count": 4,
                "safe_unseen_note_count": 0,
                "recommended_select_count": 0,
                "selected_fingerprints": [],
                "skipped_seen_count": 4,
                "skipped_unsafe_count": 0,
            }
            summary = {"note_cards": [{"fingerprint": "a"}]}

            with mock.patch("sn_archive_exporter.visible_batch_runner.dump_and_plan", return_value=(tmp_path / "screen.xml", plan, summary)), mock.patch(
                "sn_archive_exporter.visible_batch_runner.swipe_notes_down"
            ) as swipe, mock.patch("sn_archive_exporter.visible_batch_runner.time.sleep"):
                result = run_visible_batches(config)

            swipe.assert_called_once_with("small-forward")
            self.assertEqual(result["seen_fingerprint_count"], 0)
            self.assertEqual(result["new_batches"], [])

    def test_run_visible_batches_uses_configured_nudge_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = self.make_config(tmp_path)
            config = VisibleBatchRunConfig(
                **{
                    **config.__dict__,
                    "max_empty_scrolls": 2,
                    "nudge_sequence": ("medium-forward", "small-forward"),
                }
            )
            plan = {
                "xml": "screen.xml",
                "visible_note_count": 4,
                "safe_unseen_note_count": 0,
                "recommended_select_count": 0,
                "selected_fingerprints": [],
                "skipped_seen_count": 4,
                "skipped_unsafe_count": 0,
            }
            summaries = [
                {"note_cards": [{"fingerprint": "a"}]},
                {"note_cards": [{"fingerprint": "b"}]},
                {"note_cards": [{"fingerprint": "c"}]},
            ]

            with mock.patch("sn_archive_exporter.visible_batch_runner.dump_and_plan", side_effect=[(tmp_path / f"screen{index}.xml", plan, summary) for index, summary in enumerate(summaries)]), mock.patch(
                "sn_archive_exporter.visible_batch_runner.swipe_notes_down"
            ) as swipe, mock.patch("sn_archive_exporter.visible_batch_runner.time.sleep"):
                run_visible_batches(config)

            self.assertEqual([call.args[0] for call in swipe.call_args_list], ["medium-forward", "small-forward"])

    def test_run_visible_batches_stops_on_repeated_screen(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = self.make_config(tmp_path)
            config = VisibleBatchRunConfig(
                **{
                    **config.__dict__,
                    "max_empty_scrolls": 5,
                    "max_repeated_screens": 1,
                }
            )
            plan = {
                "xml": "screen.xml",
                "visible_note_count": 1,
                "safe_unseen_note_count": 0,
                "recommended_select_count": 0,
                "selected_fingerprints": [],
                "skipped_seen_count": 1,
                "skipped_unsafe_count": 0,
            }
            summary = {"note_cards": [{"fingerprint": "a"}]}

            with mock.patch("sn_archive_exporter.visible_batch_runner.dump_and_plan", return_value=(tmp_path / "screen.xml", plan, summary)), mock.patch(
                "sn_archive_exporter.visible_batch_runner.swipe_notes_down"
            ) as swipe, mock.patch("sn_archive_exporter.visible_batch_runner.time.sleep"):
                result = run_visible_batches(config)

            self.assertEqual(swipe.call_count, 1)
            self.assertEqual(result["observations"][-1]["decision"], {"action": "stop", "reason": "screen_repeated"})


if __name__ == "__main__":
    unittest.main()
