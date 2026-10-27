from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sn_archive_exporter.folder_run_plan import (
    build_folder_run_plan,
    build_next_run_specs,
    collect_tree_plan,
    shell_quote,
    summarize_plan,
)


class FolderRunPlanTests(unittest.TestCase):
    def test_collect_tree_plan_splits_visited_exported_and_skipped(self) -> None:
        tree = {
            "folder_path": "Codex",
            "depth": 0,
            "visible_note_cards": 2,
            "visible_subfolder_count": 2,
            "export": {
                "selected_count": 2,
                "exported_file_count": 2,
                "handoff": {
                    "pulled_file_count": 2,
                    "archive_output": "output_archive/run/Codex",
                },
            },
            "children": [
                {"folder_path": "Codex/Empty", "depth": 1, "children": []},
                {"folder_path": "Codex/TooDeep", "skipped": "max_depth_limit"},
                {"folder_path": "Codex/Dry", "dry_run": True},
            ],
        }

        plan = collect_tree_plan(tree)

        self.assertEqual([item["folder_path"] for item in plan["visited"]], ["Codex", "Codex/Empty"])
        self.assertEqual(plan["exported"][0]["archive_output"], "output_archive/run/Codex")
        self.assertEqual(plan["skipped"][0]["reason"], "max_depth_limit")
        self.assertEqual(plan["dry_run_children"][0]["folder_path"], "Codex/Dry")

    def test_build_folder_run_plan_combines_summaries_and_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            first = tmp_path / "first.json"
            second = tmp_path / "second.json"
            first.write_text(
                json.dumps(
                    {
                        "tree": {
                            "folder_path": "Codex",
                            "depth": 0,
                            "export": {"exported_file_count": 2, "handoff": {"archive_output": "out/Codex"}},
                            "children": [{"folder_path": "Codex/Skip", "skipped": "max_folder_limit"}],
                        }
                    }
                ),
                encoding="utf-8",
            )
            second.write_text(
                json.dumps(
                    {
                        "tree": {
                            "folder_path": "Codex",
                            "depth": 0,
                            "export": {"exported_file_count": 2, "handoff": {"archive_output": "out/Codex"}},
                            "children": [{"folder_path": "Codex/Leaf", "depth": 1, "children": []}],
                        }
                    }
                ),
                encoding="utf-8",
            )

            plan = build_folder_run_plan([first, second])

        self.assertEqual(plan["counts"]["visited"], 2)
        self.assertEqual(plan["counts"]["exported"], 1)
        self.assertEqual(plan["counts"]["skipped"], 1)
        self.assertEqual(plan["incomplete_folder_paths"], ["Codex/Skip"])
        self.assertIn("Codex/Leaf", plan["completed_folder_paths"])

    def test_build_folder_run_plan_resolves_skips_seen_in_later_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            first = tmp_path / "first.json"
            second = tmp_path / "second.json"
            first.write_text(
                json.dumps(
                    {
                        "tree": {
                            "folder_path": "Codex",
                            "depth": 0,
                            "children": [{"folder_path": "Codex/ResumeMe", "skipped": "max_folder_limit"}],
                        }
                    }
                ),
                encoding="utf-8",
            )
            second.write_text(
                json.dumps(
                    {
                        "tree": {
                            "folder_path": "Codex/ResumeMe",
                            "depth": 0,
                            "children": [],
                        }
                    }
                ),
                encoding="utf-8",
            )

            plan = build_folder_run_plan([first, second])

        self.assertEqual(plan["counts"]["skipped"], 1)
        self.assertEqual(plan["counts"]["resolved_skipped"], 1)
        self.assertEqual(plan["counts"]["pending"], 0)
        self.assertEqual(plan["incomplete_folder_paths"], [])

    def test_summarize_plan_keeps_counts_and_incomplete_paths(self) -> None:
        plan = {
            "schema": "sn_archive_exporter.folder_run_plan.v1",
            "run_summary_paths": ["a.json", "b.json"],
            "counts": {"visited": 1, "pending": 1},
            "incomplete_folder_paths": ["Codex/Skip"],
            "next_runs": [{"folder_path": "Codex/Skip"}],
        }

        summary = summarize_plan(plan)

        self.assertEqual(summary["run_summary_count"], 2)
        self.assertEqual(summary["counts"]["pending"], 1)
        self.assertEqual(summary["incomplete_folder_paths"], ["Codex/Skip"])
        self.assertEqual(summary["next_run_count"], 1)

    def test_shell_quote_handles_korean_spaces_and_quotes(self) -> None:
        self.assertEqual(shell_quote("Codex/폴더 13"), "'Codex/폴더 13'")
        self.assertEqual(shell_quote("Codex/Bob's"), "'Codex/Bob'\"'\"'s'")

    def test_build_next_run_specs_creates_commands_for_pending_paths(self) -> None:
        plan = {
            "pending": [
                {"folder_path": "Codex/폴더 13", "reason": "max_folder_limit"},
                {"folder_path": "Codex/Dry", "reason": "dry_run_child"},
            ]
        }

        specs = build_next_run_specs(
            plan,
            run_id_prefix="resume_20260708",
            max_depth=5,
            max_folders=10,
            max_subfolder_scrolls=4,
            mixed_folder_select_all=True,
            wait_seconds=0.5,
        )

        self.assertEqual([spec["run_id"] for spec in specs], ["resume_20260708_001", "resume_20260708_002"])
        self.assertEqual(specs[0]["folder_path"], "Codex/폴더 13")
        self.assertIn("--root-path 'Codex/폴더 13'", specs[0]["command"])
        self.assertIn("--max-folders 10", specs[0]["command"])
        self.assertIn("--mixed-folder-select-all", specs[0]["command"])


if __name__ == "__main__":
    unittest.main()
