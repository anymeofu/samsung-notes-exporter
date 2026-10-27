from __future__ import annotations

import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from sn_archive_exporter.selection_count_probe import (
    checked_checkbox_breakdown,
    compact_selection_probe,
    state_probe,
)


class SelectionCountProbeTests(unittest.TestCase):
    def test_checked_checkbox_breakdown_splits_select_all_headers_and_notes(self) -> None:
        root = ET.fromstring(
            """
<hierarchy>
  <node resource-id="com.samsung.android.app.notes:id/checkbox_all" class="android.widget.CheckBox" checked="true" bounds="[1,1][10,10]" />
  <node resource-id="com.samsung.android.app.notes:id/sub_header_title" text="Header" bounds="[20,100][300,160]" />
  <node resource-id="com.samsung.android.app.notes:id/inflate_checkbox" class="android.widget.CheckBox" checked="true" bounds="[25,105][75,155]" />
  <node resource-id="com.samsung.android.app.notes:id/root_cardview" class="android.view.ViewGroup" checked="true" bounds="[20,200][300,500]" content-desc="dummy note">
    <node resource-id="com.samsung.android.app.notes:id/inflate_checkbox" class="android.widget.CheckBox" checked="true" bounds="[25,205][75,255]" />
  </node>
</hierarchy>
"""
        )

        self.assertEqual(
            checked_checkbox_breakdown(root),
            {
                "note_card_checkboxes": 1,
                "section_header_checkboxes": 1,
                "select_all_checkbox": 1,
                "total_checked_checkboxes": 3,
            },
        )

    def test_compact_selection_probe_omits_note_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            xml_path = Path(tmp) / "selection.xml"
            xml_path.write_text(
                """
<hierarchy>
  <node package="com.samsung.android.app.notes" resource-id="com.samsung.android.app.notes:id/folderpath_text" text="Codex" bounds="[0,0][1,1]" />
  <node package="com.samsung.android.app.notes" resource-id="com.samsung.android.app.notes:id/folderpath_text" text="Export" bounds="[0,0][1,1]" />
  <node package="com.samsung.android.app.notes" resource-id="com.samsung.android.app.notes:id/check_info" text="407개 선택됨" bounds="[0,0][1,1]" />
  <node package="com.samsung.android.app.notes" resource-id="com.samsung.android.app.notes:id/root_cardview" checked="true" content-desc="private dummy title" bounds="[0,10][100,200]" />
</hierarchy>
""",
                encoding="utf-8",
            )

            result = compact_selection_probe(xml_path, ["Codex/Export"])

        encoded = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("private dummy title", encoded)
        self.assertEqual(result["folder_path"], "Codex/Export")
        self.assertEqual(result["selection_info"]["selected_count"], 407)
        self.assertEqual(result["visible_checked_note_cards"], 1)

    def test_state_probe_reports_counts_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "run_id": "run",
                        "folder_path": "Folder",
                        "seen_fingerprints": ["a", "b"],
                        "batches": [{"batch_id": "batch001"}, {"batch_id": "batch002"}],
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(
                state_probe(state_path),
                {
                    "state": str(state_path),
                    "run_id": "run",
                    "folder_path": "Folder",
                    "seen_fingerprint_count": 2,
                    "batch_count": 2,
                    "first_batch": "batch001",
                    "last_batch": "batch002",
                },
            )


if __name__ == "__main__":
    unittest.main()
