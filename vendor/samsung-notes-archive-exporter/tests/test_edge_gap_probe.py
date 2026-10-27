from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sn_archive_exporter.edge_gap_probe import EdgeGapProbeConfig, fingerprints_from_xmls, run_edge_gap_probe


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_state(path: Path, *, seen: list[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "run_id": "run",
                "folder_path": "Folder",
                "seen_fingerprints": seen,
                "batches": [],
            }
        ),
        encoding="utf-8",
    )


def write_target_xml(path: Path) -> None:
    path.write_text(
        """
<hierarchy>
  <node package="com.samsung.android.app.notes" resource-id="com.samsung.android.app.notes:id/folderpath_text" text="Folder" bounds="[0,0][1,1]" />
  <node package="com.samsung.android.app.notes" resource-id="com.samsung.android.app.notes:id/root_cardview" content-desc="seen" bounds="[24,529][540,1139]" />
  <node package="com.samsung.android.app.notes" resource-id="com.samsung.android.app.notes:id/root_cardview" content-desc="missing" bounds="[540,529][1056,1139]" />
</hierarchy>
""",
        encoding="utf-8",
    )


class EdgeGapProbeTests(unittest.TestCase):
    def make_config(self, tmp_path: Path, *, execute: bool = False) -> EdgeGapProbeConfig:
        return EdgeGapProbeConfig(
            folder_path="Folder",
            run_id="run",
            state_path=tmp_path / "state.json",
            target_globs=(str(tmp_path / "target.xml"),),
            out_dir=tmp_path / "ui",
            current_xml=None,
            execute=execute,
            max_steps=3,
            wait_seconds=0.0,
            nudge_sequence=("small-forward",),
        )

    def test_fingerprints_from_xmls_hashes_content_desc_without_returning_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            xml_path = Path(tmp) / "target.xml"
            write_target_xml(xml_path)

            result = fingerprints_from_xmls([xml_path], "Folder")

        self.assertEqual(result, {fingerprint("seen"), fingerprint("missing")})

    def test_run_edge_gap_probe_dry_run_reports_missing_without_nudging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            write_state(tmp_path / "state.json", seen=[fingerprint("seen")])
            write_target_xml(tmp_path / "target.xml")
            summary = {
                "is_samsung_notes_visible": True,
                "packages": ["com.samsung.android.app.notes"],
                "folder_path": "Folder",
                "note_card_count": 1,
                "note_cards": [
                    {"fingerprint": fingerprint("missing"), "bounds": "[24,1937][540,2340]"},
                ],
                "bottom_overflow_available": False,
                "dangerous_actions_present": [],
            }

            with mock.patch("sn_archive_exporter.edge_gap_probe.observe_current", return_value=(tmp_path / "screen.xml", summary)), mock.patch(
                "sn_archive_exporter.edge_gap_probe.apply_nudge"
            ) as nudge:
                result = run_edge_gap_probe(self.make_config(tmp_path, execute=False))

        self.assertEqual(result["target_universe_count"], 2)
        self.assertEqual(result["target_missing_count"], 1)
        self.assertEqual(result["steps"][0]["observation"]["edge_only_missing_count"], 1)
        self.assertEqual(result["steps"][0]["planned_nudge"], "small-forward")
        nudge.assert_not_called()

    def test_run_edge_gap_probe_stops_when_stable_missing_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            write_state(tmp_path / "state.json", seen=[fingerprint("seen")])
            write_target_xml(tmp_path / "target.xml")
            summary = {
                "is_samsung_notes_visible": True,
                "packages": ["com.samsung.android.app.notes"],
                "folder_path": "Folder",
                "note_card_count": 1,
                "note_cards": [
                    {"fingerprint": fingerprint("missing"), "bounds": "[24,529][540,1139]"},
                ],
                "bottom_overflow_available": False,
                "dangerous_actions_present": [],
            }

            with mock.patch("sn_archive_exporter.edge_gap_probe.observe_current", return_value=(tmp_path / "screen.xml", summary)), mock.patch(
                "sn_archive_exporter.edge_gap_probe.apply_nudge"
            ) as nudge:
                result = run_edge_gap_probe(self.make_config(tmp_path, execute=True))

        self.assertEqual(result["best_stable_missing_count"], 1)
        self.assertEqual(result["steps"][0]["stop_reason"], "stable_missing_notes_available")
        nudge.assert_not_called()


if __name__ == "__main__":
    unittest.main()
