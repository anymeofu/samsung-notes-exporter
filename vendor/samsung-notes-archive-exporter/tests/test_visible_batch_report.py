from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sn_archive_exporter.archive_builder import build_archive
from sn_archive_exporter.archive_merger import merge_folder_archive_outputs
from sn_archive_exporter.visible_batch_report import build_report, summarize_archive_outputs


def write_mapping(path: Path, source: str, folder_path: str, note_id: str) -> None:
    path.write_text(
        json.dumps(
            {
                "notes": [
                    {
                        "id": note_id,
                        "title": Path(source).stem,
                        "source": source,
                        "folder_path": folder_path,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


class VisibleBatchReportTests(unittest.TestCase):
    def make_archive(self, root: Path, name: str, note_id: str) -> Path:
        input_dir = root / "input" / name
        input_dir.mkdir(parents=True)
        source = f"{name}.sdocx"
        (input_dir / source).write_bytes(name.encode("utf-8"))
        write_mapping(input_dir / "mapping.json", source, "TestTasting/커피", note_id)
        archive_dir = root / "output" / name
        build_archive(input_dir, input_dir / "mapping.json", archive_dir, dry_run=False)
        return archive_dir

    def test_summarize_archive_outputs_counts_notes_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            first = self.make_archive(tmp_path, "first", "note-1")
            second = self.make_archive(tmp_path, "second", "note-2")

            result = summarize_archive_outputs([first, second])

            self.assertEqual(result["archive_output_count"], 2)
            self.assertEqual(result["counts"]["notes"], 2)
            self.assertEqual(result["counts"]["files"], 2)

    def test_build_report_compares_state_archives_and_merged_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            first = self.make_archive(tmp_path, "first", "note-1")
            second = self.make_archive(tmp_path, "second", "note-2")
            merged = tmp_path / "merged"
            merge_folder_archive_outputs([first, second], merged, dry_run=False, folder_paths=["TestTasting/커피"])
            state_path = tmp_path / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "run_id": "run",
                        "folder_path": "TestTasting/커피",
                        "seen_fingerprints": ["a", "b"],
                        "batches": [{"batch_id": "batch001"}, {"batch_id": "batch002"}],
                    }
                ),
                encoding="utf-8",
            )

            result = build_report(
                folder_path="TestTasting/커피",
                state_path=state_path,
                viewport_patterns=[],
                archive_patterns=[str(first), str(second)],
                merged_archive_path=merged,
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["comparison"]["expected_count"], 2)
            self.assertEqual(result["comparison"]["mismatch_count"], 0)


if __name__ == "__main__":
    unittest.main()
