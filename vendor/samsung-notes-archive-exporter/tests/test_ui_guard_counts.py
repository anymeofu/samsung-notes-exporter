from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from sn_archive_exporter.ui_guard import (
    extract_selection_info,
    extract_selected_subfolder_checkboxes,
    extract_visible_folder_note_counts,
    selected_subfolder_checkbox_tap_plan,
    summarize_xml_root,
)


class UiGuardCountTests(unittest.TestCase):
    def test_extract_visible_folder_note_counts_reads_mixed_count_label(self) -> None:
        root = ET.fromstring(
            """
<hierarchy>
  <node text="폴더 2개, 노트 13개" content-desc="" />
</hierarchy>
"""
        )

        self.assertEqual(extract_visible_folder_note_counts(root), {"folder_count": 2, "note_count": 13})

    def test_extract_visible_folder_note_counts_reads_note_only_label(self) -> None:
        root = ET.fromstring(
            """
<hierarchy>
  <node text="노트 8개" content-desc="" />
</hierarchy>
"""
        )

        self.assertEqual(extract_visible_folder_note_counts(root), {"folder_count": None, "note_count": 8})

    def test_summarize_xml_root_includes_visible_counts(self) -> None:
        root = ET.fromstring(
            """
<hierarchy>
  <node package="com.samsung.android.app.notes" text="폴더 2개, 노트 3개" content-desc="" />
</hierarchy>
"""
        )

        summary = summarize_xml_root(root)

        self.assertEqual(summary["visible_counts"], {"folder_count": 2, "note_count": 3})

    def test_extract_selection_info_reads_bare_count_text(self) -> None:
        root = ET.fromstring(
            """
<hierarchy>
  <node resource-id="com.samsung.android.app.notes:id/check_info" text="23" />
</hierarchy>
"""
        )

        self.assertEqual(extract_selection_info(root), {"text": "23", "selected_count": 23})

    def test_summarize_xml_root_includes_bottom_overflow_availability(self) -> None:
        root = ET.fromstring(
            """
<hierarchy>
  <node package="com.samsung.android.app.notes" resource-id="com.samsung.android.app.notes:id/bottom_overflow" bounds="[1,1][2,2]" />
</hierarchy>
"""
        )

        summary = summarize_xml_root(root)

        self.assertTrue(summary["bottom_overflow_available"])

    def test_extract_selected_subfolder_checkboxes_reads_checkbox_child_bounds(self) -> None:
        root = ET.fromstring(
            """
<hierarchy>
  <node resource-id="com.samsung.android.app.notes:id/sub_folder_list_item2" bounds="[298,275][524,501]">
    <node resource-id="com.samsung.android.app.notes:id/title" text="폴더 13" bounds="[0,0][1,1]" />
    <node resource-id="com.samsung.android.app.notes:id/inflate_checkbox" class="android.widget.CheckBox" bounds="[312,309][367,364]" checked="true" enabled="true" />
  </node>
  <node resource-id="com.samsung.android.app.notes:id/sub_folder_list_item3" bounds="[556,275][782,501]">
    <node resource-id="com.samsung.android.app.notes:id/title" text="폴더 14" bounds="[0,0][1,1]" />
    <node resource-id="com.samsung.android.app.notes:id/inflate_checkbox" class="android.widget.CheckBox" bounds="[570,309][625,364]" checked="false" enabled="true" />
  </node>
</hierarchy>
"""
        )

        selected = extract_selected_subfolder_checkboxes(root)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["title"], "폴더 13")
        self.assertEqual(selected[0]["center"], [339, 336])

    def test_extract_selected_subfolder_checkboxes_keeps_title_when_checkbox_comes_first(self) -> None:
        root = ET.fromstring(
            """
<hierarchy>
  <node resource-id="com.samsung.android.app.notes:id/sub_folder_list_item2" bounds="[298,275][524,501]">
    <node resource-id="com.samsung.android.app.notes:id/inflate_checkbox" class="android.widget.CheckBox" bounds="[312,309][367,364]" checked="true" enabled="true" />
    <node resource-id="com.samsung.android.app.notes:id/title" text="폴더 13" bounds="[0,0][1,1]" />
  </node>
</hierarchy>
"""
        )

        selected = extract_selected_subfolder_checkboxes(root)

        self.assertEqual(selected[0]["title"], "폴더 13")

    def test_summarize_xml_root_includes_selected_subfolder_count(self) -> None:
        root = ET.fromstring(
            """
<hierarchy>
  <node package="com.samsung.android.app.notes" resource-id="com.samsung.android.app.notes:id/sub_folder_list_item1" bounds="[40,0][266,223]">
    <node resource-id="com.samsung.android.app.notes:id/title" text="폴더 8" bounds="[0,0][1,1]" />
    <node resource-id="com.samsung.android.app.notes:id/inflate_checkbox" bounds="[54,31][109,86]" checked="true" enabled="true" />
  </node>
</hierarchy>
"""
        )

        summary = summarize_xml_root(root)

        self.assertEqual(summary["selected_subfolder_count"], 1)
        self.assertEqual(summary["selected_subfolder_checkboxes"][0]["title"], "폴더 8")

    def test_selected_subfolder_checkbox_tap_plan_refuses_empty_targets(self) -> None:
        with self.assertRaises(SystemExit):
            selected_subfolder_checkbox_tap_plan({"selected_subfolder_checkboxes": []})

    def test_selected_subfolder_checkbox_tap_plan_limits_target_count(self) -> None:
        summary = {
            "selected_subfolder_checkboxes": [
                {"title": "A", "center": [1, 1], "enabled": True},
                {"title": "B", "center": [2, 2], "enabled": True},
            ]
        }

        with self.assertRaises(SystemExit):
            selected_subfolder_checkbox_tap_plan(summary, max_count=1)

    def test_selected_subfolder_checkbox_tap_plan_returns_enabled_targets(self) -> None:
        summary = {
            "selected_subfolder_checkboxes": [
                {"title": "A", "center": [1, 1], "enabled": True},
            ]
        }

        self.assertEqual(selected_subfolder_checkbox_tap_plan(summary), summary["selected_subfolder_checkboxes"])


if __name__ == "__main__":
    unittest.main()
