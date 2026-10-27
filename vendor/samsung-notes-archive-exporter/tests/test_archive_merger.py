from __future__ import annotations

import json
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from sn_archive_exporter.archive_builder import build_archive, main as archive_builder_main
from sn_archive_exporter.archive_merger import (
    collect_archive_outputs,
    collect_archive_outputs_from_summaries,
    collect_folder_paths,
    merge_folder_archives,
    merge_folder_archives_from_summaries,
)


def write_mapping(path: Path, source: str, folder_path: str) -> None:
    path.write_text(
        json.dumps(
            {
                "notes": [
                    {
                        "id": "exported-note-000001",
                        "title": Path(source).stem,
                        "source": source,
                        "folder_path": folder_path,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


class ArchiveMergerTests(unittest.TestCase):
    def test_collect_archive_outputs_from_run_summary_tree(self) -> None:
        tree = {
            "folder_path": "Codex",
            "children": [
                {
                    "folder_path": "Codex/Export",
                    "export": {"handoff": {"archive_output": "output_archive/run/Codex__Export"}},
                    "children": [],
                },
                {"folder_path": "Codex/Empty", "children": []},
            ],
        }

        self.assertEqual(
            collect_archive_outputs(tree),
            [Path("output_archive/run/Codex__Export")],
        )
        self.assertEqual(collect_folder_paths(tree), ["Codex", "Codex/Export", "Codex/Empty"])

    def test_merge_folder_archives_combines_manifests_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_root = tmp_path / "input"
            input_root.mkdir()

            first_input = input_root / "first"
            second_input = input_root / "second"
            first_input.mkdir()
            second_input.mkdir()
            (first_input / "a.sdocx").write_bytes(b"first")
            (second_input / "b.sdocx").write_bytes(b"second")
            write_mapping(first_input / "mapping.json", "a.sdocx", "Codex/Export")
            write_mapping(second_input / "mapping.json", "b.sdocx", "Codex/Other")

            first_archive = tmp_path / "output" / "run_001" / "Codex__Export"
            second_archive = tmp_path / "output" / "run_001" / "Codex__Other"
            build_archive(first_input, first_input / "mapping.json", first_archive, dry_run=False)
            build_archive(second_input, second_input / "mapping.json", second_archive, dry_run=False)

            run_summary = tmp_path / "output" / "run_001" / "run_summary.json"
            run_summary.parent.mkdir(parents=True, exist_ok=True)
            run_summary.write_text(
                json.dumps(
                    {
                        "tree": {
                            "folder_path": "Codex",
                            "children": [
                                {
                                    "folder_path": "Codex/Export",
                                    "export": {"handoff": {"archive_output": str(first_archive)}},
                                    "children": [],
                                },
                                {
                                    "folder_path": "Codex/Empty",
                                    "children": [],
                                },
                                {
                                    "folder_path": "Codex/Other",
                                    "export": {"handoff": {"archive_output": str(second_archive)}},
                                    "children": [],
                                },
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            merged = tmp_path / "merged"
            result = merge_folder_archives(run_summary, merged, dry_run=False)

            self.assertEqual(result["manifest"]["counts"], {"folders": 4, "notes": 2, "files": 2})
            self.assertTrue((merged / "archive" / "Codex" / "Export" / "a.sdocx").exists())
            self.assertTrue((merged / "archive" / "Codex" / "Other" / "b.sdocx").exists())
            notes = json.loads((merged / "notes_index.json").read_text(encoding="utf-8"))["notes"]
            self.assertEqual(len({note["id"] for note in notes}), 2)
            folders = json.loads((merged / "folders.json").read_text(encoding="utf-8"))["folders"]
            self.assertIn("Codex/Empty", {folder["path"] for folder in folders})

    def test_merge_multiple_run_summaries_for_partitioned_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_root = tmp_path / "input"
            input_root.mkdir()

            first_input = input_root / "first"
            second_input = input_root / "second"
            first_input.mkdir()
            second_input.mkdir()
            (first_input / "a.sdocx").write_bytes(b"first")
            (second_input / "b.sdocx").write_bytes(b"second")
            write_mapping(first_input / "mapping.json", "a.sdocx", "Codex/Export")
            write_mapping(second_input / "mapping.json", "b.sdocx", "Codex/폴더 13/폴더 2")

            first_archive = tmp_path / "output" / "run_001" / "Codex__Export"
            second_archive = tmp_path / "output" / "run_002" / "Codex__폴더 13__폴더 2"
            build_archive(first_input, first_input / "mapping.json", first_archive, dry_run=False)
            build_archive(second_input, second_input / "mapping.json", second_archive, dry_run=False)

            first_summary = tmp_path / "output" / "run_001" / "run_summary.json"
            second_summary = tmp_path / "output" / "run_002" / "run_summary.json"
            first_summary.parent.mkdir(parents=True, exist_ok=True)
            second_summary.parent.mkdir(parents=True, exist_ok=True)
            first_summary.write_text(
                json.dumps({"tree": {"export": {"handoff": {"archive_output": str(first_archive)}}}}),
                encoding="utf-8",
            )
            second_summary.write_text(
                json.dumps({"tree": {"export": {"handoff": {"archive_output": str(second_archive)}}}}),
                encoding="utf-8",
            )

            self.assertEqual(
                collect_archive_outputs_from_summaries([first_summary, second_summary]),
                [first_archive, second_archive],
            )

            merged = tmp_path / "merged"
            result = merge_folder_archives_from_summaries([first_summary, second_summary], merged, dry_run=False)

            self.assertEqual(result["run_summary_paths"], [str(first_summary), str(second_summary)])
            self.assertEqual(result["manifest"]["counts"], {"folders": 4, "notes": 2, "files": 2})
            self.assertTrue((merged / "archive" / "Codex" / "Export" / "a.sdocx").exists())
            self.assertTrue((merged / "archive" / "Codex" / "폴더 13" / "폴더 2" / "b.sdocx").exists())

    def test_merge_refuses_existing_output_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_summary = tmp_path / "run_summary.json"
            run_summary.write_text(json.dumps({"tree": {}}), encoding="utf-8")
            output = tmp_path / "merged"
            output.mkdir()

            with self.assertRaises(SystemExit):
                merge_folder_archives(run_summary, output, dry_run=False)

    def test_cli_merge_archive_outputs_combines_explicit_archive_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_root = tmp_path / "input"
            first_input = input_root / "first"
            second_input = input_root / "second"
            first_input.mkdir(parents=True)
            second_input.mkdir()
            (first_input / "a.sdocx").write_bytes(b"first")
            (second_input / "b.sdocx").write_bytes(b"second")
            write_mapping(first_input / "mapping.json", "a.sdocx", "TestTasting/커피")
            write_mapping(second_input / "mapping.json", "b.sdocx", "TestTasting/커피")

            first_archive = tmp_path / "output" / "batch001"
            second_archive = tmp_path / "output" / "batch002"
            build_archive(first_input, first_input / "mapping.json", first_archive, dry_run=False)
            build_archive(second_input, second_input / "mapping.json", second_archive, dry_run=False)

            merged = tmp_path / "merged"
            with contextlib.redirect_stdout(io.StringIO()):
                archive_builder_main(
                    [
                        "merge-archive-outputs",
                        "--archive-output",
                        str(first_archive),
                        "--archive-output",
                        str(second_archive),
                        "--folder-path",
                        "TestTasting/커피",
                        "--output",
                        str(merged),
                        "--summary-only",
                    ]
                )

            manifest = json.loads((merged / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["counts"], {"folders": 2, "notes": 2, "files": 2})
            self.assertTrue((merged / "archive" / "TestTasting" / "커피" / "a.sdocx").exists())
            self.assertTrue((merged / "archive" / "TestTasting" / "커피" / "b.sdocx").exists())


if __name__ == "__main__":
    unittest.main()
