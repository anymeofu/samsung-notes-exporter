from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sn_archive_exporter.folder_walk_driver import (
    WalkConfig,
    build_run_summary,
    compact_walk_tree,
    default_run_summary_path,
    record_workflow,
    should_use_select_all_for_note_export,
    summarize_walk_result,
    subfolder_tap_point,
    write_run_summary,
)
from sn_archive_exporter.workflow_state import WorkflowPhase


class FolderWalkDriverTests(unittest.TestCase):
    def test_subfolder_tap_point_uses_left_biased_safe_point(self) -> None:
        subfolder = {
            "bounds": "[814,1897][1040,2123]",
            "center": [927, 2010],
        }

        self.assertEqual(subfolder_tap_point(subfolder), (870, 2010))

    def test_compact_walk_tree_keeps_export_counts_not_full_events(self) -> None:
        result = {
            "folder_path": "Codex",
            "depth": 0,
            "visible_note_cards": 1,
            "direct_note_card_pages": [{"page": 1, "visible_note_cards": 1}],
            "visible_subfolders": [{"title": "Export"}],
            "export": {
                "allowed_path": "Codex",
                "destination": "Documents",
                "execute": True,
                "select_count": "all",
                "events": [{"action": "confirm_selected_note_count", "selected_count": 2}],
                "exported_files": ["/sdcard/Documents/a.sdocx", "/sdcard/Documents/b.sdocx"],
                "handoff": {"pulled_files": ["a.sdocx", "b.sdocx"], "archive_counts": {"notes": 2}},
            },
            "children": [{"folder_path": "Codex/Export", "dry_run": True}],
        }

        compact = compact_walk_tree(result)

        self.assertEqual(compact["visible_subfolder_count"], 1)
        self.assertEqual(compact["direct_note_card_pages"], [{"page": 1, "visible_note_cards": 1}])
        self.assertEqual(compact["export"]["exported_file_count"], 2)
        self.assertNotIn("events", compact["export"])
        self.assertEqual(compact["children"][0]["folder_path"], "Codex/Export")

    def test_write_run_summary_defaults_to_archive_run_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = WalkConfig(
                root_path="Codex",
                run_id="run_001",
                input_root=tmp_path / "input_exports",
                archive_root=tmp_path / "output_archive",
                out_dir=tmp_path / "ui_dumps",
                execute=False,
                max_depth=1,
                max_subfolder_scrolls=3,
                wait_seconds=0.1,
            )
            result = {
                "folder_path": "Codex",
                "depth": 0,
                "visible_note_cards": 0,
                "direct_note_card_pages": [],
                "visible_subfolders": [],
                "export": None,
                "children": [{"folder_path": "Codex/Export", "dry_run": True}],
            }

            path = write_run_summary(config, result)
            payload = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(path, default_run_summary_path(config))
            self.assertEqual(payload["schema"], "sn_archive_exporter.folder_walk_run_summary.v1")
            self.assertEqual(payload["run_id"], "run_001")
            self.assertFalse(payload["mixed_folder_select_all"])
            self.assertEqual(payload["max_depth"], 1)
            self.assertEqual(payload["workflow"]["phase"], "done")
            self.assertEqual(payload["workflow"]["counts"]["dry_run_children"], 1)
            self.assertEqual(payload["summary"]["totals"]["dry_run_children"], 1)
            self.assertEqual(payload["tree"]["children"][0]["folder_path"], "Codex/Export")

    def test_build_run_summary_records_observation_dir(self) -> None:
        config = WalkConfig(
            root_path="Codex",
            run_id="run_002",
            input_root=Path("input_exports"),
            archive_root=Path("output_archive"),
            out_dir=Path("ui_dumps"),
            execute=False,
            max_depth=0,
            max_subfolder_scrolls=1,
            wait_seconds=0.1,
            export_format="txt",
            observation_dir=Path("observations"),
        )
        result = {
            "folder_path": "Codex",
            "depth": 0,
            "visible_note_cards": 0,
            "direct_note_card_pages": [],
            "visible_subfolders": [],
            "export": None,
            "children": [],
        }

        summary = build_run_summary(config, result)

        self.assertEqual(summary["observation_dir"], "observations")
        self.assertTrue(summary["export_enabled"])
        self.assertEqual(summary["export_format"], "txt")
        self.assertEqual(summary["summary"]["root_path"], "Codex")

    def test_record_workflow_adds_compact_events(self) -> None:
        config = WalkConfig(
            root_path="Codex",
            run_id="run_workflow",
            input_root=Path("input_exports"),
            archive_root=Path("output_archive"),
            out_dir=Path("ui_dumps"),
            execute=False,
            max_depth=0,
            max_subfolder_scrolls=1,
            wait_seconds=0.1,
        )

        state = record_workflow(
            config,
            WorkflowPhase.CLASSIFY_SCREEN,
            current_folder_path="Codex",
            last_action="depth0_pre",
            next_action="decide_folder_step",
            counts={"visible_note_cards": 2, "visible_subfolders": 21},
        )

        self.assertIs(config.workflow_state, state)
        self.assertEqual(config.workflow_events[0]["sequence"], 1)
        self.assertEqual(config.workflow_events[0]["phase"], "classify_screen")
        self.assertEqual(config.workflow_events[0]["counts"]["visible_note_cards"], 2)

    def test_build_run_summary_keeps_recent_workflow_events(self) -> None:
        config = WalkConfig(
            root_path="Codex",
            run_id="run_recent",
            input_root=Path("input_exports"),
            archive_root=Path("output_archive"),
            out_dir=Path("ui_dumps"),
            execute=False,
            max_depth=0,
            max_subfolder_scrolls=1,
            wait_seconds=0.1,
        )
        for index in range(25):
            record_workflow(
                config,
                WorkflowPhase.CLASSIFY_SCREEN,
                current_folder_path="Codex",
                last_action=f"step{index}",
                next_action="decide_folder_step",
            )
        result = {
            "folder_path": "Codex",
            "depth": 0,
            "visible_note_cards": 0,
            "direct_note_card_pages": [],
            "visible_subfolders": [],
            "export": None,
            "children": [],
        }

        summary = build_run_summary(config, result)

        self.assertEqual(len(summary["workflow_recent_events"]), 20)
        self.assertEqual(summary["workflow_recent_events"][0]["sequence"], 6)
        self.assertEqual(summary["workflow_recent_events"][-1]["sequence"], 25)
        self.assertEqual(summary["workflow"]["phase"], "done")

    def test_summarize_walk_result_counts_max_depth_skips(self) -> None:
        result = {
            "folder_path": "Codex/폴더 13",
            "depth": 1,
            "visible_note_cards": 2,
            "direct_note_card_pages": [],
            "visible_subfolders": [{"title": "폴더 1"}],
            "export": None,
            "children": [
                {
                    "folder_path": "Codex/폴더 13/폴더 1",
                    "skipped": "max_depth_limit",
                }
            ],
        }

        summary = summarize_walk_result(result)

        self.assertEqual(summary["totals"]["folders"], 1)
        self.assertEqual(summary["totals"]["skipped"], 1)

    def test_export_current_folder_uses_select_count_for_mixed_folders(self) -> None:
        config = WalkConfig(
            root_path="Codex",
            run_id="run_003",
            input_root=Path("input_exports"),
            archive_root=Path("output_archive"),
            out_dir=Path("ui_dumps"),
            execute=True,
            max_depth=0,
            max_subfolder_scrolls=1,
            wait_seconds=0.1,
        )

        with patch("sn_archive_exporter.folder_walk_driver.run_guarded_export") as guarded:
            guarded.return_value = {"ok": True}
            from sn_archive_exporter.folder_walk_driver import export_current_folder

            export_current_folder(config, "Codex", 2, select_all=False)

        driver_config = guarded.call_args.args[0]
        self.assertFalse(driver_config.select_all)
        self.assertEqual(driver_config.select_count, 2)

    def test_export_current_folder_can_use_select_all_without_subfolders(self) -> None:
        config = WalkConfig(
            root_path="Codex/Export",
            run_id="run_004",
            input_root=Path("input_exports"),
            archive_root=Path("output_archive"),
            out_dir=Path("ui_dumps"),
            execute=True,
            max_depth=0,
            max_subfolder_scrolls=1,
            wait_seconds=0.1,
            export_format="txt",
        )

        with patch("sn_archive_exporter.folder_walk_driver.run_guarded_export") as guarded:
            guarded.return_value = {"ok": True}
            from sn_archive_exporter.folder_walk_driver import export_current_folder

            export_current_folder(config, "Codex/Export", 8, select_all=True)

        driver_config = guarded.call_args.args[0]
        self.assertTrue(driver_config.select_all)
        self.assertEqual(driver_config.select_count, 1)
        self.assertEqual(driver_config.export_format, "txt")

    def test_export_current_folder_wires_mixed_folder_deselect_options(self) -> None:
        config = WalkConfig(
            root_path="Codex",
            run_id="run_005",
            input_root=Path("input_exports"),
            archive_root=Path("output_archive"),
            out_dir=Path("ui_dumps"),
            execute=True,
            max_depth=0,
            max_subfolder_scrolls=1,
            wait_seconds=0.1,
            mixed_folder_select_all=True,
            deselect_scroll_attempts=6,
            deselect_max_taps=90,
        )

        with patch("sn_archive_exporter.folder_walk_driver.run_guarded_export") as guarded:
            guarded.return_value = {"ok": True}
            from sn_archive_exporter.folder_walk_driver import export_current_folder

            export_current_folder(config, "Codex", 2, select_all=True, folder_has_subfolders=True)

        driver_config = guarded.call_args.args[0]
        self.assertTrue(driver_config.select_all)
        self.assertTrue(driver_config.deselect_visible_subfolders_after_select_all)
        self.assertEqual(driver_config.deselect_scroll_attempts, 6)
        self.assertEqual(driver_config.deselect_max_taps, 90)

    def test_select_all_strategy_is_disabled_for_mixed_folders(self) -> None:
        self.assertFalse(
            should_use_select_all_for_note_export(
                folder_has_subfolders=True,
                mixed_folder_select_all=False,
            )
        )

    def test_select_all_strategy_can_be_enabled_for_mixed_folders(self) -> None:
        self.assertTrue(
            should_use_select_all_for_note_export(
                folder_has_subfolders=True,
                mixed_folder_select_all=True,
            )
        )

    def test_select_all_strategy_is_allowed_for_note_only_folders(self) -> None:
        self.assertTrue(
            should_use_select_all_for_note_export(
                folder_has_subfolders=False,
                mixed_folder_select_all=False,
            )
        )


if __name__ == "__main__":
    unittest.main()
