import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from sn_archive_exporter.archive_builder import build_archive, sanitize_folder_path, sanitize_path_part


def write_mapping(path: Path, filename: str, folder_path: str = "Folder A/Subfolder B") -> None:
    path.write_text(
        json.dumps(
            {
                "notes": [
                    {
                        "id": "note-test-001",
                        "title": "Test Note",
                        "source": filename,
                        "folder_path": folder_path,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def write_duplicate_mapping(path: Path, filename: str) -> None:
    path.write_text(
        json.dumps(
            {
                "notes": [
                    {
                        "id": "note-test-001",
                        "title": "Test Note 1",
                        "source": filename,
                        "folder_path": "Folder A",
                    },
                    {
                        "id": "note-test-002",
                        "title": "Test Note 2",
                        "source": filename,
                        "folder_path": "Folder A",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )


def write_multi_folder_mapping(path: Path, first: str, second: str) -> None:
    path.write_text(
        json.dumps(
            {
                "notes": [
                    {
                        "id": "note-test-001",
                        "title": "Folder A Note",
                        "source": first,
                        "folder_path": "Folder A",
                    },
                    {
                        "id": "note-test-002",
                        "title": "Folder B Note",
                        "source": second,
                        "folder_path": "Folder B/Subfolder C",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )


class ArchiveBuilderTests(unittest.TestCase):
    def test_sanitize_path_part(self):
        self.assertEqual(sanitize_path_part(" A/B:C* "), "A_B_C_")
        self.assertEqual(sanitize_path_part(".."), "_")

    def test_sanitize_folder_path(self):
        self.assertEqual(sanitize_folder_path("Folder A/Sub:Folder"), Path("Folder A") / "Sub_Folder")
        self.assertEqual(sanitize_folder_path(""), Path("_unfiled"))

    def test_build_archive_copies_file_and_writes_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_dir = tmp_path / "input"
            input_dir.mkdir()
            source = input_dir / "Notes_260416_231358.sdocx"
            source.write_bytes(b"sample")
            mapping = tmp_path / "mapping.json"
            write_mapping(mapping, source.name)

            output_dir = tmp_path / "archive_out"
            result = build_archive(input_dir, mapping, output_dir, dry_run=False)

            archived = output_dir / "archive" / "Folder A" / "Subfolder B" / source.name
            self.assertEqual(archived.read_bytes(), b"sample")
            self.assertEqual(result["manifest"]["counts"], {"folders": 2, "notes": 1, "files": 1})
            self.assertTrue((output_dir / "manifest.json").exists())
            self.assertTrue((output_dir / "folders.json").exists())
            self.assertTrue((output_dir / "notes_index.json").exists())

    def test_dry_run_does_not_copy_or_write_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_dir = tmp_path / "input"
            input_dir.mkdir()
            source = input_dir / "note.sdocx"
            source.write_bytes(b"sample")
            mapping = tmp_path / "mapping.json"
            write_mapping(mapping, source.name)

            output_dir = tmp_path / "archive_out"
            result = build_archive(input_dir, mapping, output_dir, dry_run=True)

            self.assertTrue(result["dry_run"])
            self.assertFalse(output_dir.exists())

    def test_duplicate_target_names_get_numbered_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_dir = tmp_path / "input"
            input_dir.mkdir()
            source = input_dir / "note.sdocx"
            source.write_bytes(b"sample")
            mapping = tmp_path / "mapping.json"
            write_duplicate_mapping(mapping, source.name)

            output_dir = tmp_path / "archive_out"
            build_archive(input_dir, mapping, output_dir, dry_run=False)

            folder = output_dir / "archive" / "Folder A"
            self.assertTrue((folder / "note.sdocx").exists())
            self.assertTrue((folder / "note (2).sdocx").exists())

    def test_build_archive_preserves_multiple_folder_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_dir = tmp_path / "input"
            input_dir.mkdir()
            first = input_dir / "first.sdocx"
            second = input_dir / "second.sdocx"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            mapping = tmp_path / "mapping.json"
            write_multi_folder_mapping(mapping, first.name, second.name)

            output_dir = tmp_path / "archive_out"
            result = build_archive(input_dir, mapping, output_dir, dry_run=False)

            self.assertTrue((output_dir / "archive" / "Folder A" / "first.sdocx").exists())
            self.assertTrue((output_dir / "archive" / "Folder B" / "Subfolder C" / "second.sdocx").exists())
            self.assertEqual(result["manifest"]["counts"], {"folders": 3, "notes": 2, "files": 2})

    def test_build_archive_records_sdocx_date_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_dir = tmp_path / "input"
            input_dir.mkdir()
            source = input_dir / "Notes_260505_015648.sdocx"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr(zipfile.ZipInfo("note.note", (2026, 5, 5, 1, 56, 48)), b"metadata")
                archive.writestr(zipfile.ZipInfo("page-id.page", (2026, 5, 5, 0, 50, 22)), b"page")
            mapping = tmp_path / "mapping.json"
            write_mapping(mapping, source.name)

            output_dir = tmp_path / "archive_out"
            result = build_archive(input_dir, mapping, output_dir, dry_run=False)
            note = result["manifest"]["notes"][0]
            metadata = note["exported_files"][0]["sdocx_metadata"]

            self.assertEqual(note["display_datetime"], "2026-05-05 01:56:48")
            self.assertEqual(metadata["filename_datetime"], "2026-05-05 01:56:48")
            self.assertEqual(metadata["zip_page_datetimes"], ["2026-05-05 00:50:22"])

    def test_build_archive_records_txt_filename_date_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_dir = tmp_path / "input"
            input_dir.mkdir()
            source = input_dir / "Notes_260630_215514.txt"
            source.write_text("8", encoding="utf-8")
            mapping = tmp_path / "mapping.json"
            write_mapping(mapping, source.name)

            output_dir = tmp_path / "archive_out"
            result = build_archive(input_dir, mapping, output_dir, dry_run=False)
            note = result["manifest"]["notes"][0]
            exported_file = note["exported_files"][0]

            self.assertEqual(note["display_datetime"], "2026-06-30 21:55:14")
            self.assertEqual(exported_file["filename_datetime"], "2026-06-30 21:55:14")
            self.assertNotIn("sdocx_metadata", exported_file)


if __name__ == "__main__":
    unittest.main()
