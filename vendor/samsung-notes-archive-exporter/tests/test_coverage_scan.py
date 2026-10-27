from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sn_archive_exporter.coverage_scan import CoverageScanConfig, run_coverage_scan


class CoverageScanTests(unittest.TestCase):
    def test_run_coverage_scan_stops_before_nudge_on_stable_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_path = tmp_path / "state.json"
            state_path.write_text(
                json.dumps({"run_id": "run", "folder_path": "Folder", "seen_fingerprints": [], "batches": []}),
                encoding="utf-8",
            )
            config = CoverageScanConfig(
                folder_path="Folder",
                run_id="run",
                state_path=state_path,
                target_globs=("target.xml",),
                out_dir=tmp_path / "ui",
                execute=True,
                max_steps=3,
                max_repeated_screens=2,
                wait_seconds=0.0,
                nudge_sequence=("large-forward",),
                stop_on_stable_missing=True,
            )
            summary = {
                "packages": ["com.samsung.android.app.notes"],
                "is_samsung_notes_visible": True,
                "folder_path": "Folder",
                "note_card_count": 1,
                "note_cards": [{"fingerprint": "missing", "bounds": "[24,529][540,1139]"}],
                "bottom_overflow_available": False,
                "dangerous_actions_present": [],
            }

            with mock.patch("sn_archive_exporter.coverage_scan.expand_globs", return_value=[]), mock.patch(
                "sn_archive_exporter.coverage_scan.fingerprints_from_xmls", return_value={"missing"}
            ), mock.patch("sn_archive_exporter.coverage_scan.dump_summary", return_value=(tmp_path / "screen.xml", summary)), mock.patch(
                "sn_archive_exporter.coverage_scan.apply_nudge"
            ) as nudge:
                result = run_coverage_scan(config)

        self.assertEqual(result["stop_reason"], "stable_missing_found")
        self.assertEqual(result["steps"][0]["stable_missing_count"], 1)
        nudge.assert_not_called()

    def test_run_coverage_scan_counts_observed_missing_without_exporting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_path = tmp_path / "state.json"
            state_path.write_text(
                json.dumps({"run_id": "run", "folder_path": "Folder", "seen_fingerprints": ["seen"], "batches": []}),
                encoding="utf-8",
            )
            config = CoverageScanConfig(
                folder_path="Folder",
                run_id="run",
                state_path=state_path,
                target_globs=("target.xml",),
                out_dir=tmp_path / "ui",
                execute=True,
                max_steps=1,
                max_repeated_screens=2,
                wait_seconds=0.0,
                nudge_sequence=("large-forward",),
            )
            summary = {
                "packages": ["com.samsung.android.app.notes"],
                "is_samsung_notes_visible": True,
                "folder_path": "Folder",
                "note_card_count": 2,
                "note_cards": [
                    {"fingerprint": "seen", "bounds": "[24,529][540,1139]"},
                    {"fingerprint": "missing", "bounds": "[540,529][1056,1139]"},
                ],
                "bottom_overflow_available": False,
                "dangerous_actions_present": [],
            }

            with mock.patch("sn_archive_exporter.coverage_scan.expand_globs", return_value=[]), mock.patch(
                "sn_archive_exporter.coverage_scan.fingerprints_from_xmls", return_value={"seen", "missing"}
            ), mock.patch("sn_archive_exporter.coverage_scan.dump_summary", return_value=(tmp_path / "screen.xml", summary)), mock.patch(
                "sn_archive_exporter.coverage_scan.apply_nudge"
            ) as nudge, mock.patch(
                "sn_archive_exporter.coverage_scan.time.sleep"
            ):
                result = run_coverage_scan(config)

        self.assertEqual(result["target_universe_count"], 2)
        self.assertEqual(result["target_missing_count"], 1)
        self.assertEqual(result["observed_missing_total"], 1)
        self.assertEqual(result["observed_stable_missing_total"], 1)
        nudge.assert_called_once_with("large-forward")


if __name__ == "__main__":
    unittest.main()
