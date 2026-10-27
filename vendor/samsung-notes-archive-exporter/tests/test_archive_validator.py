from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from sn_archive_exporter.archive_validator import validate_archive


class ArchiveValidatorTests(unittest.TestCase):
    def make_archive(self, root: Path) -> Path:
        archive_dir = root / "archive_output"
        file_path = archive_dir / "archive" / "Codex" / "note.sdocx"
        file_path.parent.mkdir(parents=True)
        payload = b"sample sdocx"
        file_path.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        manifest = {
            "counts": {"folders": 1, "notes": 1, "files": 1},
            "notes": [
                {
                    "id": "note-1",
                    "folder_path": "Codex",
                    "exported_files": [
                        {
                            "path": "archive/Codex/note.sdocx",
                            "sha256": digest,
                            "size_bytes": len(payload),
                        }
                    ],
                }
            ],
        }
        folders = {"folders": [{"id": "folder-1", "path": "Codex", "depth": 0}]}
        notes_index = {"notes": [{"id": "note-1", "folder_path": "Codex"}]}
        (archive_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (archive_dir / "folders.json").write_text(json.dumps(folders), encoding="utf-8")
        (archive_dir / "notes_index.json").write_text(json.dumps(notes_index), encoding="utf-8")
        return archive_dir

    def add_empty_folder(self, archive_dir: Path, folder_path: str = "Codex/Empty") -> None:
        folders_path = archive_dir / "folders.json"
        manifest_path = archive_dir / "manifest.json"
        folders = json.loads(folders_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        folders["folders"].append({"id": "folder-2", "path": folder_path, "depth": 1})
        manifest["counts"]["folders"] = len(folders["folders"])
        folders_path.write_text(json.dumps(folders), encoding="utf-8")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_validate_archive_accepts_matching_hashes_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_dir = self.make_archive(Path(tmp))

            result = validate_archive(archive_dir)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["counts"], {"folders": 1, "notes": 1, "files": 1})
            self.assertEqual(result["quality"]["notes_missing_display_datetime"], 1)
            self.assertEqual(result["quality"]["empty_folder_count"], 0)
            self.assertEqual(result["errors"], [])

    def test_validate_archive_reports_quality_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_dir = self.make_archive(Path(tmp))
            self.add_empty_folder(archive_dir)
            manifest_path = archive_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            note = manifest["notes"][0]
            note["display_datetime"] = "2026-07-08 12:00:00"
            note["exported_files"][0]["sdocx_metadata"] = {"inferred_display_datetime": "2026-07-08 12:00:00"}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = validate_archive(archive_dir)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["quality"]["notes_with_display_datetime"], 1)
            self.assertEqual(result["quality"]["notes_missing_display_datetime"], 0)
            self.assertEqual(result["quality"]["files_with_sdocx_metadata"], 1)
            self.assertEqual(result["quality"]["empty_folder_count"], 1)
            self.assertEqual(result["quality"]["empty_folder_paths"], ["Codex/Empty"])

    def test_validate_archive_accepts_preserved_source_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_dir = self.make_archive(Path(tmp))
            manifest_path = archive_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["notes"][0]["exported_files"][0]["source_path"] = "input/note.sdocx"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = validate_archive(archive_dir)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["warnings"], [])

    def test_validate_archive_warns_when_archived_filename_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_dir = self.make_archive(Path(tmp))
            manifest_path = archive_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["notes"][0]["exported_files"][0]["source_path"] = "input/original.sdocx"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = validate_archive(archive_dir)

            self.assertEqual(result["status"], "ok")
            self.assertTrue(any("archived filename differs" in warning for warning in result["warnings"]))

    def test_validate_archive_reports_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive_dir = self.make_archive(Path(tmp))
            manifest_path = archive_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["notes"][0]["exported_files"][0]["sha256"] = "bad"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = validate_archive(archive_dir)

            self.assertEqual(result["status"], "error")
            self.assertTrue(any("sha256 mismatch" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
