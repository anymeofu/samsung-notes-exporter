from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from sn_archive_exporter.sdocx_metadata import extract_sdocx_metadata, parse_notes_filename_datetime


class SdocxMetadataTests(unittest.TestCase):
    def test_parse_notes_filename_datetime(self) -> None:
        self.assertEqual(
            parse_notes_filename_datetime(Path("Notes_260505_015648.sdocx")),
            "2026-05-05 01:56:48",
        )
        self.assertIsNone(parse_notes_filename_datetime(Path("plain.sdocx")))

    def test_parse_named_txt_filename_datetime(self) -> None:
        self.assertEqual(
            parse_notes_filename_datetime(Path("Named note_260505_015648 (2).txt")),
            "2026-05-05 01:56:48",
        )

    def test_extract_sdocx_metadata_uses_filename_and_zip_timestamps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Notes_260505_015648.sdocx"
            with zipfile.ZipFile(path, "w") as archive:
                note = zipfile.ZipInfo("note.note", (2026, 5, 5, 1, 56, 48))
                page = zipfile.ZipInfo("page-id.page", (2026, 5, 5, 0, 50, 22))
                archive.writestr(note, b"metadata")
                archive.writestr(page, b"page")

            metadata = extract_sdocx_metadata(path)

            self.assertEqual(metadata["filename_datetime"], "2026-05-05 01:56:48")
            self.assertEqual(metadata["zip_note_datetime"], "2026-05-05 01:56:48")
            self.assertEqual(metadata["zip_page_datetimes"], ["2026-05-05 00:50:22"])
            self.assertEqual(metadata["inferred_display_datetime"], "2026-05-05 01:56:48")


if __name__ == "__main__":
    unittest.main()
