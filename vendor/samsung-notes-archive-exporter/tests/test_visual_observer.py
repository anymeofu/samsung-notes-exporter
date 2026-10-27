from __future__ import annotations

import xml.etree.ElementTree as ET
import unittest

from sn_archive_exporter.visual_observer import compact_candidates, fingerprint_observation


class VisualObserverTests(unittest.TestCase):
    def test_compact_candidates_skip_plain_layouts(self) -> None:
        root = ET.fromstring(
            """
            <hierarchy>
              <node class="android.widget.FrameLayout" bounds="[0,0][1080,2400]" />
              <node class="android.widget.TextView" text="Codex" resource-id="com.samsung.android.app.notes:id/folderpath_text" bounds="[10,20][200,80]" />
              <node class="android.widget.Button" text="파일로 저장" clickable="true" bounds="[100,100][300,180]" />
              <node class="android.widget.EditText" text="Notes_260101_120000" resource-id="com.samsung.android.app.notes:id/text_input_dialog" bounds="[50,200][900,280]" />
              <node class="android.widget.ScrollView" scrollable="true" bounds="[0,300][1080,2200]" />
            </hierarchy>
            """
        )
        candidates = compact_candidates(root)
        texts = {item.get("text") for item in candidates}

        self.assertEqual(len(candidates), 4)
        self.assertIn("Codex", texts)
        self.assertIn("파일로 저장", texts)
        self.assertTrue(any("editable" in item.get("states", []) for item in candidates))
        self.assertTrue(any("scrollable" in item.get("states", []) for item in candidates))

    def test_fingerprint_is_stable_for_same_compact_screen(self) -> None:
        root = ET.fromstring(
            """
            <hierarchy>
              <node package="com.samsung.android.app.notes" class="android.widget.TextView" text="Codex" resource-id="com.samsung.android.app.notes:id/folderpath_text" bounds="[10,20][200,80]" />
              <node package="com.samsung.android.app.notes" class="android.widget.Button" text="전체" clickable="true" bounds="[0,0][100,80]" />
            </hierarchy>
            """
        )
        candidates = compact_candidates(root)

        first = fingerprint_observation(
            package_activity="mCurrentFocus=com.samsung.android.app.notes/.Main",
            screen_size=(1080, 2400),
            root=root,
            candidates=candidates,
        )
        second = fingerprint_observation(
            package_activity="mCurrentFocus=com.samsung.android.app.notes/.Main",
            screen_size=(1080, 2400),
            root=root,
            candidates=candidates,
        )

        self.assertEqual(first, second)
        self.assertEqual(len(first), 16)


if __name__ == "__main__":
    unittest.main()
