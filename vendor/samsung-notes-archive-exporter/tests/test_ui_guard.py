import tempfile
import unittest
import hashlib
from pathlib import Path

from sn_archive_exporter import ui_guard


class UiGuardTests(unittest.TestCase):
    def test_safe_export_filename_allows_title_based_names(self):
        self.assertTrue(ui_guard.is_safe_export_filename("코리안 네그로니_190309_175241"))
        self.assertTrue(ui_guard.is_safe_export_filename("Notes_260701_141445"))
        self.assertFalse(ui_guard.is_safe_export_filename(""))
        self.assertFalse(ui_guard.is_safe_export_filename("../bad"))
        self.assertFalse(ui_guard.is_safe_export_filename("bad/name"))

    def test_allowed_path_accepts_descendants_but_not_siblings(self):
        self.assertTrue(ui_guard.is_allowed_path("Codex", ["Codex"]))
        self.assertTrue(ui_guard.is_allowed_path("Codex/폴더 13/폴더 2", ["Codex"]))
        self.assertFalse(ui_guard.is_allowed_path("CodexOther", ["Codex"]))
        self.assertFalse(ui_guard.is_allowed_path("Other/Codex", ["Codex"]))

    def test_allowed_path_accepts_empty_breadcrumb_for_root_folder_alias(self):
        self.assertTrue(ui_guard.is_allowed_path("", ["폴더"]))
        self.assertFalse(ui_guard.is_allowed_path("", ["TestMaterials"]))

    def test_summarize_marks_descendant_paths_allowed(self):
        xml = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy>
  <node resource-id="com.samsung.android.app.notes:id/folderpath_text"
        package="com.samsung.android.app.notes"
        text="Codex"
        bounds="[0,0][10,10]" />
  <node resource-id="com.samsung.android.app.notes:id/folderpath_text"
        package="com.samsung.android.app.notes"
        text="폴더 13"
        bounds="[10,0][20,10]" />
</hierarchy>
"""
        with tempfile.TemporaryDirectory() as tmp:
            xml_path = Path(tmp) / "dump.xml"
            xml_path.write_text(xml, encoding="utf-8")
            summary = ui_guard.summarize(xml_path, ["Codex"])

        self.assertEqual(summary["folder_path"], "Codex/폴더 13")
        self.assertTrue(summary["allowed"])

    def test_extract_subfolders_reads_titles_and_centers(self):
        xml = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy>
  <node resource-id="com.samsung.android.app.notes:id/sub_folder_list_item2"
        class="android.widget.FrameLayout"
        package="com.samsung.android.app.notes"
        content-desc="Folder, Coffee, 3"
        clickable="true"
        enabled="true"
        bounds="[540,500][1056,900]">
    <node resource-id="com.samsung.android.app.notes:id/title"
          text="Coffee"
          bounds="[600,800][900,860]" />
  </node>
  <node resource-id="com.samsung.android.app.notes:id/sub_folder_list_item1"
        class="android.widget.FrameLayout"
        package="com.samsung.android.app.notes"
        content-desc="Folder, Wine, 2"
        clickable="true"
        enabled="true"
        bounds="[24,500][540,900]">
    <node resource-id="com.samsung.android.app.notes:id/title"
          text="Wine"
          bounds="[80,800][300,860]" />
  </node>
  <node resource-id="com.samsung.android.app.notes:id/sub_folder_list_item_container"
        class="android.widget.LinearLayout"
        package="com.samsung.android.app.notes"
        bounds="[0,400][1080,1000]" />
</hierarchy>
"""
        with tempfile.TemporaryDirectory() as tmp:
            xml_path = Path(tmp) / "dump.xml"
            xml_path.write_text(xml, encoding="utf-8")
            root = ui_guard.load_xml(xml_path)
            subfolders = ui_guard.extract_subfolders(root)

        self.assertEqual([item["title"] for item in subfolders], ["Wine", "Coffee"])
        self.assertEqual(subfolders[0]["center"], [282, 700])
        self.assertTrue(subfolders[0]["clickable"])

    def test_extract_note_cards_adds_content_hash_without_text(self):
        content_desc = "private title and body 7월 7일"
        xml = f"""<?xml version='1.0' encoding='UTF-8'?>
<hierarchy>
  <node resource-id="com.samsung.android.app.notes:id/root_cardview"
        class="android.widget.CheckBox"
        package="com.samsung.android.app.notes"
        content-desc="{content_desc}"
        clickable="true"
        long-clickable="true"
        checked="false"
        bounds="[24,529][540,1139]" />
</hierarchy>
"""
        with tempfile.TemporaryDirectory() as tmp:
            xml_path = Path(tmp) / "dump.xml"
            xml_path.write_text(xml, encoding="utf-8")
            root = ui_guard.load_xml(xml_path)
            cards = ui_guard.extract_note_cards(root)

        self.assertEqual(cards[0]["fingerprint"], hashlib.sha256(content_desc.encode("utf-8")).hexdigest())
        self.assertNotIn("content_desc", cards[0])

    def test_extract_subfolders_skips_clipped_items_without_title(self):
        xml = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy>
  <node resource-id="com.samsung.android.app.notes:id/sub_folder_list_item1"
        class="android.widget.FrameLayout"
        package="com.samsung.android.app.notes"
        content-desc="폴더, 폴더 16 , 0"
        clickable="true"
        enabled="true"
        bounds="[40,2175][266,2340]">
    <node resource-id="com.samsung.android.app.notes:id/title"
          text=""
          bounds="[66,2300][120,2340]" />
  </node>
</hierarchy>
"""
        with tempfile.TemporaryDirectory() as tmp:
            xml_path = Path(tmp) / "dump.xml"
            xml_path.write_text(xml, encoding="utf-8")
            root = ui_guard.load_xml(xml_path)

        self.assertEqual(ui_guard.extract_subfolders(root), [])

    def test_extract_subfolder_expand_reads_show_all_button(self):
        xml = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy>
  <node resource-id="com.samsung.android.app.notes:id/expand_bar_layout"
        class="androidx.appcompat.widget.LinearLayoutCompat"
        package="com.samsung.android.app.notes"
        content-desc="모두 보기"
        clickable="true"
        enabled="true"
        bounds="[409,1291][670,1392]">
    <node resource-id="com.samsung.android.app.notes:id/expand_bar_header"
          text="모두 보기"
          bounds="[451,1312][606,1371]" />
  </node>
</hierarchy>
"""
        with tempfile.TemporaryDirectory() as tmp:
            xml_path = Path(tmp) / "dump.xml"
            xml_path.write_text(xml, encoding="utf-8")
            root = ui_guard.load_xml(xml_path)
            expand = ui_guard.extract_subfolder_expand(root)

        self.assertTrue(expand["available"])
        self.assertFalse(expand["ambiguous"])
        self.assertEqual(expand["center"], [539, 1341])
        self.assertEqual(expand["content_desc"], "모두 보기")
        self.assertTrue(expand["is_show_all"])
        self.assertFalse(expand["is_collapse"])

    def test_extract_subfolder_expand_detects_collapse_state(self):
        xml = """<?xml version='1.0' encoding='UTF-8'?>
<hierarchy>
  <node resource-id="com.samsung.android.app.notes:id/expand_bar_layout"
        class="androidx.appcompat.widget.LinearLayoutCompat"
        package="com.samsung.android.app.notes"
        content-desc="접기"
        clickable="true"
        enabled="true"
        bounds="[450,2125][629,2226]" />
</hierarchy>
"""
        with tempfile.TemporaryDirectory() as tmp:
            xml_path = Path(tmp) / "dump.xml"
            xml_path.write_text(xml, encoding="utf-8")
            root = ui_guard.load_xml(xml_path)
            expand = ui_guard.extract_subfolder_expand(root)

        self.assertTrue(expand["available"])
        self.assertFalse(expand["is_show_all"])
        self.assertTrue(expand["is_collapse"])


if __name__ == "__main__":
    unittest.main()
