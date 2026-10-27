import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sn_archive_exporter.guarded_export_driver import (
    DriverConfig,
    adb,
    can_skip_select_all_after_first,
    checkbox_target_signature,
    detect_filename_dialog,
    ensure_output_targets_available,
    find_select_all_target,
    is_selection_context,
    is_stably_visible_checkbox_target,
    is_stably_tappable_note_card,
    main,
    note_card_is_selectable,
    record_event_workflow,
    require_export_format,
    require_export_selection_limit,
    require_selection_context,
    require_export_overflow_available,
    selected_count_for_select_all,
    selected_count_for_select_all_after_subfolder_deselect,
    set_quiet,
    stable_checkbox_targets,
    summarize_export_result,
    unstable_checkbox_targets,
    validate_export_file_count,
    verify_note_only_selection_after_subfolder_deselect,
    wait_for_new_public_sdocx,
    wait_for_new_public_exports,
    workflow_counts_for_export_event,
    workflow_phase_for_export_action,
    write_archive_mapping,
)
from sn_archive_exporter.workflow_state import WorkflowPhase, initial_workflow_state


class GuardedExportDriverTests(unittest.TestCase):
    def test_partial_txt_export_can_continue_with_nonzero_files(self):
        result = validate_export_file_count(
            expected=10,
            actual=7,
            extension=".txt",
            allow_partial=True,
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["missing_file_count"], 3)

    def test_partial_export_still_refuses_zero_files(self):
        with self.assertRaisesRegex(SystemExit, "found 0"):
            validate_export_file_count(
                expected=10,
                actual=0,
                extension=".txt",
                allow_partial=True,
            )

    def test_partial_export_summary_is_not_reported_as_ok(self):
        summary = summarize_export_result(
            {
                "exported_files": ["one.txt"],
                "partial_export": {
                    "status": "partial",
                    "expected_file_count": 2,
                    "exported_file_count": 1,
                    "missing_file_count": 1,
                },
            }
        )

        self.assertEqual(summary["status"], "partial")
        self.assertEqual(summary["partial_export"]["missing_file_count"], 1)

    def test_write_archive_mapping_uses_pulled_filenames_and_folder_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pulled = [
                tmp_path / "Notes_260630_195832 (1).sdocx",
                tmp_path / "Notes_260630_195836 (3).sdocx",
            ]
            for path in pulled:
                path.write_bytes(b"sample")

            mapping_path = tmp_path / "mapping.json"
            mapping = write_archive_mapping(pulled, mapping_path, "Codex/Export")

            self.assertEqual(mapping, json.loads(mapping_path.read_text(encoding="utf-8")))
            self.assertEqual(len(mapping["notes"]), 2)
            self.assertEqual(mapping["notes"][0]["source"], "Notes_260630_195832 (1).sdocx")
            self.assertEqual(mapping["notes"][0]["folder_path"], "Codex/Export")
            self.assertEqual(mapping["notes"][1]["source"], "Notes_260630_195836 (3).sdocx")

    def test_existing_output_targets_are_refused_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pull_to = tmp_path / "existing_pull"
            archive_output = tmp_path / "existing_archive"
            pull_to.mkdir()
            archive_output.mkdir()

            with self.assertRaises(SystemExit) as raised:
                ensure_output_targets_available(
                    pull_to,
                    archive_output,
                    allow_existing_output=False,
                )

            self.assertIn("already exists", str(raised.exception))

    def test_existing_output_targets_can_be_explicitly_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pull_to = tmp_path / "existing_pull"
            pull_to.mkdir()

            ensure_output_targets_available(
                pull_to,
                None,
                allow_existing_output=True,
            )

    def test_set_quiet_is_callable_for_cli_log_suppression(self):
        set_quiet(True)
        set_quiet(False)

    def test_main_requires_run_id_with_skip_note_state(self):
        with self.assertRaises(SystemExit) as raised:
            main(["--allowed-path", "Codex", "--skip-note-state", "state.json"])

        self.assertIn("--skip-note-state requires --run-id", str(raised.exception))

    def test_adb_timeout_reports_guarded_failure(self):
        with mock.patch("sn_archive_exporter.guarded_export_driver.ui_guard.adb_path", return_value="adb"), mock.patch(
            "sn_archive_exporter.guarded_export_driver.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["adb"], 1.0),
        ):
            with self.assertRaises(SystemExit) as raised:
                adb(["shell", "uiautomator", "dump"], timeout_seconds=1.0)

        self.assertIn("timed out", str(raised.exception))

    def test_adb_nonzero_exit_reports_guarded_failure(self):
        with mock.patch("sn_archive_exporter.guarded_export_driver.ui_guard.adb_path", return_value="adb"), mock.patch(
            "sn_archive_exporter.guarded_export_driver.subprocess.run",
            side_effect=subprocess.CalledProcessError(137, ["adb"], stderr="Killed"),
        ):
            with self.assertRaises(SystemExit) as raised:
                adb(["shell", "uiautomator", "dump"], timeout_seconds=1.0)

        message = str(raised.exception)
        self.assertIn("failed with exit 137", message)
        self.assertIn("Killed", message)

    def test_wait_for_new_public_sdocx_polls_until_expected_count(self):
        before = {"/sdcard/Documents/existing.sdocx": "old"}
        snapshots = [
            {
                "/sdcard/Documents/existing.sdocx": "old",
                "/sdcard/Documents/a.sdocx": "new",
            },
            {
                "/sdcard/Documents/existing.sdocx": "old",
                "/sdcard/Documents/a.sdocx": "new",
                "/sdcard/Documents/b.sdocx": "new",
            },
        ]

        with mock.patch("sn_archive_exporter.guarded_export_driver.list_public_exports", side_effect=snapshots), mock.patch(
            "sn_archive_exporter.guarded_export_driver.time.sleep"
        ):
            exported, after = wait_for_new_public_sdocx(
                "Documents",
                before,
                expected_min=2,
                timeout_seconds=5,
                poll_seconds=0.01,
            )

        self.assertEqual(exported, ["/sdcard/Documents/a.sdocx", "/sdcard/Documents/b.sdocx"])
        self.assertEqual(len(after), 3)

    def test_wait_for_new_public_txt_uses_requested_extension(self):
        before = {"/sdcard/Documents/existing.txt": "old"}
        after = {
            "/sdcard/Documents/existing.txt": "old",
            "/sdcard/Documents/new.txt": "new",
        }

        with mock.patch(
            "sn_archive_exporter.guarded_export_driver.list_public_exports",
            return_value=after,
        ) as list_exports:
            exported, snapshot = wait_for_new_public_exports(
                "Documents",
                before,
                expected_min=1,
                extension=".txt",
                timeout_seconds=1,
                poll_seconds=0.01,
            )

        self.assertEqual(exported, ["/sdcard/Documents/new.txt"])
        self.assertEqual(snapshot, after)
        list_exports.assert_called_once_with("Documents", ".txt")

    def test_export_format_specs_include_sdocx_and_txt(self):
        self.assertEqual(require_export_format("sdocx")["menu_text"], "삼성 노트 파일")
        self.assertEqual(require_export_format("txt")["extension"], ".txt")

    def test_workflow_counts_for_export_event_keeps_small_numeric_fields(self):
        counts = workflow_counts_for_export_event(
            {
                "action": "confirm_selected_note_count",
                "visible_note_count": 8,
                "selected_count": 8,
                "requested_select_count": "all",
                "target": {"bounds": "[0,0][1,1]"},
            }
        )

        self.assertEqual(counts["visible_note_count"], 8)
        self.assertEqual(counts["selected_count"], 8)
        self.assertEqual(counts["select_all"], 1)
        self.assertNotIn("target", counts)

    def test_workflow_phase_for_export_action_groups_export_steps(self):
        self.assertEqual(workflow_phase_for_export_action("long_press_first_note"), WorkflowPhase.SELECT_NOTES)
        self.assertEqual(workflow_phase_for_export_action("tap_save_as_file"), WorkflowPhase.OPEN_EXPORT_MENU)
        self.assertEqual(workflow_phase_for_export_action("tap_samsung_notes_file"), WorkflowPhase.CHOOSE_EXPORT_FORMAT)
        self.assertEqual(workflow_phase_for_export_action("tap_text_file"), WorkflowPhase.CHOOSE_EXPORT_FORMAT)
        self.assertEqual(workflow_phase_for_export_action("tap_myfiles_done"), WorkflowPhase.CHOOSE_DESTINATION)

    def test_selected_count_for_select_all_allows_missing_count_when_visible_cards_checked(self):
        summary = {
            "selection_info": {"text": "노트 선택", "selected_count": None},
            "note_card_count": 1,
        }

        self.assertEqual(selected_count_for_select_all(summary, checked_count=1), 1)

    def test_selected_count_for_select_all_refuses_missing_count_when_visible_cards_unchecked(self):
        summary = {
            "selection_info": {"text": "노트 선택", "selected_count": None},
            "note_card_count": 2,
        }

        with self.assertRaises(SystemExit):
            selected_count_for_select_all(summary, checked_count=1)

    def test_require_export_overflow_available_explains_partition_needed(self):
        summary = {
            "bottom_overflow_available": False,
            "dangerous_actions_present": [
                "com.samsung.android.app.notes:id/action_move",
                "com.samsung.android.app.notes:id/action_delete",
            ],
        }

        with self.assertRaises(SystemExit) as raised:
            require_export_overflow_available(summary, 407)

        message = str(raised.exception)
        self.assertIn("not exposing export overflow", message)
        self.assertIn("selected_count=407", message)
        self.assertIn("smaller batch", message)

    def test_require_export_selection_limit_refuses_100_or_more(self):
        require_export_selection_limit(99)

        with self.assertRaises(SystemExit) as raised:
            require_export_selection_limit(100)

        self.assertIn("safe Samsung Notes export batch limit of 99", str(raised.exception))

    def test_selected_count_after_subfolder_deselect_refuses_remaining_subfolders(self):
        summary = {
            "selection_info": {"text": "23", "selected_count": None},
            "selected_subfolder_count": 1,
        }

        with self.assertRaises(SystemExit):
            selected_count_for_select_all_after_subfolder_deselect(summary, checked_count=2)

    def test_selected_count_after_subfolder_deselect_allows_checked_notes_without_label(self):
        summary = {
            "selection_info": {"text": "노트 선택", "selected_count": None},
            "selected_subfolder_count": 0,
            "visible_counts": {"note_count": None},
            "bottom_overflow_available": True,
        }

        self.assertEqual(selected_count_for_select_all_after_subfolder_deselect(summary, checked_count=2), 2)

    def test_verify_note_only_selection_matches_ui_note_count_and_overflow(self):
        summary = {
            "selection_info": {"text": "2개 선택됨", "selected_count": 2},
            "selected_subfolder_count": 0,
            "visible_counts": {"note_count": 2},
            "bottom_overflow_available": True,
        }

        verification = verify_note_only_selection_after_subfolder_deselect(summary, checked_count=2)

        self.assertEqual(verification["selected_count"], 2)
        self.assertEqual(verification["ui_note_count"], 2)
        self.assertTrue(verification["bottom_overflow_available"])

    def test_verify_note_only_selection_allows_notes_offscreen_when_count_matches(self):
        summary = {
            "selection_info": {"text": "2개 선택됨", "selected_count": 2},
            "selected_subfolder_count": 0,
            "visible_counts": {"note_count": 2},
            "bottom_overflow_available": True,
        }

        verification = verify_note_only_selection_after_subfolder_deselect(summary, checked_count=0)

        self.assertEqual(verification["selected_count"], 2)
        self.assertEqual(verification["checked_count"], 0)

    def test_verify_note_only_selection_allows_notes_offscreen_with_positive_count_and_overflow(self):
        summary = {
            "selection_info": {"text": "2개 선택됨", "selected_count": 2},
            "selected_subfolder_count": 0,
            "visible_counts": {"note_count": None},
            "bottom_overflow_available": True,
        }

        verification = verify_note_only_selection_after_subfolder_deselect(summary, checked_count=0)

        self.assertEqual(verification["selected_count"], 2)
        self.assertEqual(verification["checked_count"], 0)

    def test_verify_note_only_selection_refuses_note_count_mismatch(self):
        summary = {
            "selection_info": {"text": "3개 선택됨", "selected_count": 3},
            "selected_subfolder_count": 0,
            "visible_counts": {"note_count": 2},
            "bottom_overflow_available": True,
        }

        with self.assertRaises(SystemExit) as raised:
            verify_note_only_selection_after_subfolder_deselect(summary, checked_count=2)

        self.assertIn("does not match UI note count", str(raised.exception))

    def test_verify_note_only_selection_refuses_missing_export_overflow(self):
        summary = {
            "selection_info": {"text": "2개 선택됨", "selected_count": 2},
            "selected_subfolder_count": 0,
            "visible_counts": {"note_count": 2},
            "bottom_overflow_available": False,
        }

        with self.assertRaises(SystemExit) as raised:
            verify_note_only_selection_after_subfolder_deselect(summary, checked_count=2)

        self.assertIn("not exposing export overflow", str(raised.exception))

    def test_selected_count_after_subfolder_deselect_refuses_no_checked_notes(self):
        summary = {
            "selection_info": {"text": "노트 선택", "selected_count": None},
            "selected_subfolder_count": 0,
            "bottom_overflow_available": True,
        }

        with self.assertRaises(SystemExit):
            selected_count_for_select_all_after_subfolder_deselect(summary, checked_count=0)

    def test_stably_visible_checkbox_target_rejects_edge_targets(self):
        self.assertFalse(is_stably_visible_checkbox_target({"bounds": "[54,31][109,86]"}))
        self.assertFalse(is_stably_visible_checkbox_target({"bounds": "[312,309][367,364]"}))
        self.assertTrue(is_stably_visible_checkbox_target({"bounds": "[312,587][367,642]"}))
        self.assertFalse(is_stably_visible_checkbox_target({"bounds": "[54,2200][109,2260]"}))

    def test_stably_tappable_note_card_rejects_bottom_toolbar_overlap(self):
        self.assertTrue(is_stably_tappable_note_card({"bounds": "[24,1181][540,1791]"}))
        self.assertFalse(is_stably_tappable_note_card({"bounds": "[24,1937][540,2340]"}))

    def test_note_card_is_selectable_rejects_skipped_fingerprint(self):
        card = {
            "bounds": "[24,1181][540,1791]",
            "fingerprint": "abc123",
        }

        self.assertFalse(note_card_is_selectable(card, {"abc123"}))
        self.assertTrue(note_card_is_selectable(card, {"other"}))

    def test_stable_and_unstable_checkbox_targets_split_by_safe_region(self):
        targets = [
            {"title": "폴더 12", "bounds": "[312,309][367,364]"},
            {"title": "폴더 16", "bounds": "[54,587][109,642]"},
        ]

        self.assertEqual([target["title"] for target in stable_checkbox_targets(targets)], ["폴더 16"])
        self.assertEqual([target["title"] for target in unstable_checkbox_targets(targets)], ["폴더 12"])

    def test_checkbox_target_signature_is_order_independent(self):
        left = [
            {"title": "폴더 16", "bounds": "[54,587][109,642]"},
            {"title": "폴더 12", "bounds": "[312,309][367,364]"},
        ]
        right = list(reversed(left))

        self.assertEqual(checkbox_target_signature(left), checkbox_target_signature(right))

    def test_selection_context_detects_selected_subfolders_or_checked_notes(self):
        self.assertTrue(is_selection_context({"selected_subfolder_count": 1, "note_cards": []}))
        self.assertTrue(
            is_selection_context(
                {"selected_subfolder_count": 0, "selection_info": {"text": "23"}, "note_cards": []}
            )
        )
        self.assertTrue(
            is_selection_context(
                {"selected_subfolder_count": 0, "selection_info": {"text": ""}, "note_cards": [{"checked": True}]}
            )
        )
        self.assertFalse(
            is_selection_context(
                {"selected_subfolder_count": 0, "selection_info": {"text": ""}, "note_cards": [{"checked": False}]}
            )
        )

    def test_require_selection_context_refuses_lost_selection(self):
        with self.assertRaises(SystemExit) as raised:
            require_selection_context(
                {
                    "is_samsung_notes_visible": True,
                    "folder_path": "",
                    "selected_subfolder_count": 0,
                    "selection_info": {"text": ""},
                    "note_cards": [],
                },
                "Codex",
            )

        self.assertIn("selection context was lost", str(raised.exception))

    def test_find_select_all_target_ignores_date_section_checkbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            xml_path = Path(tmp) / "selection.xml"
            xml_path.write_text(
                """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node resource-id="com.samsung.android.app.notes:id/checkbox_withtext" text="전체" content-desc="선택 안 됨, 모두 선택하려면 두 번 누르세요." bounds="[32,738][211,906]" enabled="true" />
  <node resource-id="com.samsung.android.app.notes:id/checkbox_withtext" text="이번 주" content-desc="이번 주" bounds="[24,1037][1056,1141]" enabled="true" />
</hierarchy>
""",
                encoding="utf-8",
            )

            target = find_select_all_target(xml_path)

        self.assertEqual(target["text"], "전체")
        self.assertEqual(target["bounds"], "[32,738][211,906]")

    def test_detect_filename_dialog_allows_title_based_samsung_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            xml_path = Path(tmp) / "filename.xml"
            xml_path.write_text(
                """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node resource-id="com.samsung.android.app.notes:id/alertTitle" text="파일 이름" bounds="[90,899][990,962]" enabled="true" />
  <node resource-id="com.samsung.android.app.notes:id/text_input_dialog" text="코리안 네그로니_190309_175241" bounds="[74,1017][990,1138]" enabled="true" />
  <node resource-id="android:id/button1" text="저장" bounds="[541,1180][990,1275]" enabled="true" />
</hierarchy>
""",
                encoding="utf-8",
            )

            filename, target = detect_filename_dialog(xml_path)

            self.assertEqual(filename, "코리안 네그로니_190309_175241")
            self.assertEqual(target["text"], "저장")

    def test_find_select_all_target_reads_descendant_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            xml_path = Path(tmp) / "selection.xml"
            xml_path.write_text(
                """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node resource-id="com.samsung.android.app.notes:id/checkbox_withtext"
        content-desc="1 선택 완료, 선택을 모두 해제하려면 두 번 누르세요."
        bounds="[32,126][211,294]"
        enabled="true">
    <node text="전체" bounds="[32,215][211,259]" />
  </node>
  <node resource-id="com.samsung.android.app.notes:id/checkbox_withtext"
        text="이번 달"
        content-desc="이번 달"
        bounds="[24,425][1056,529]"
        enabled="true" />
</hierarchy>
""",
                encoding="utf-8",
            )

            target = find_select_all_target(xml_path)

            self.assertEqual(target["label"], "1 선택 완료, 선택을 모두 해제하려면 두 번 누르세요. 전체")
            self.assertEqual(target["bounds"], "[32,126][211,294]")

    def test_find_select_all_target_refuses_only_date_section_checkbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            xml_path = Path(tmp) / "selection.xml"
            xml_path.write_text(
                """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy>
  <node resource-id="com.samsung.android.app.notes:id/checkbox_withtext" text="이번 주" content-desc="이번 주" bounds="[24,1037][1056,1141]" enabled="true" />
</hierarchy>
""",
                encoding="utf-8",
            )

            with self.assertRaises(SystemExit):
                find_select_all_target(xml_path)

    def test_can_skip_select_all_after_first_when_all_visible_notes_are_selected(self):
        summary = {
            "note_card_count": 1,
            "note_cards": [{"checked": True}],
            "selection_info": {"selected_count": 1},
        }

        self.assertTrue(
            can_skip_select_all_after_first(summary, deselect_subfolders_after_select_all=False)
        )

    def test_can_skip_select_all_after_first_refuses_mixed_folder_deselect_strategy(self):
        summary = {
            "note_card_count": 1,
            "note_cards": [{"checked": True}],
            "selection_info": {"selected_count": 1},
        }

        self.assertFalse(
            can_skip_select_all_after_first(summary, deselect_subfolders_after_select_all=True)
        )

    def test_record_event_workflow_adds_artifact_path_without_full_event(self):
        config = DriverConfig(
            allowed_path="Codex/Export",
            destination="Documents",
            out_dir=Path("ui_dumps"),
            label="export_run",
            execute=False,
            select_count=2,
            select_all=False,
            wait_seconds=0.1,
            pull_to=None,
            mapping_path=None,
            archive_output=None,
        )
        workflow_events = []
        state = initial_workflow_state(config.label, config.allowed_path)

        next_state = record_event_workflow(
            state,
            workflow_events,
            config,
            {
                "step": "00_select_first",
                "xml": "ui_dumps/export_run_00_select_first.xml",
                "action": "long_press_first_note",
                "visible_note_count": 6,
                "target": {"x": 100, "y": 200},
            },
        )

        self.assertIsNot(next_state, state)
        self.assertEqual(workflow_events[0]["sequence"], 1)
        self.assertEqual(workflow_events[0]["phase"], "select_notes")
        self.assertEqual(workflow_events[0]["counts"]["visible_note_count"], 6)
        self.assertEqual(workflow_events[0]["artifacts"][0]["kind"], "ui_dump")
        self.assertNotIn("target", workflow_events[0])

    def test_summarize_export_result_ignores_workflow_details(self):
        summary = summarize_export_result(
            {
                "allowed_path": "Codex/Export",
                "destination": "Documents",
                "export_format": "txt",
                "execute": False,
                "select_count": 2,
                "events": [{"action": "confirm_selected_note_count", "selected_count": 2}],
                "workflow": {"phase": "done"},
                "workflow_recent_events": [{"phase": "select_notes"}, {"phase": "done"}],
                "planned_actions": ["long_press_first_note"],
            }
        )

        self.assertEqual(summary["selected_count"], 2)
        self.assertFalse(summary["selection_probe_only"])
        self.assertEqual(summary["workflow_phase"], "done")
        self.assertEqual(summary["workflow_event_count"], 2)
        self.assertEqual(summary["export_format"], "txt")
        self.assertNotIn("workflow_recent_events", summary)

    def test_summarize_export_result_marks_selection_probe_only(self):
        summary = summarize_export_result(
            {
                "allowed_path": "Codex",
                "destination": "Documents",
                "execute": True,
                "selection_probe_only": True,
                "select_count": "all",
                "events": [{"action": "confirm_selected_note_count", "selected_count": 10}],
                "workflow": {"phase": "done"},
                "workflow_recent_events": [{"phase": "select_notes"}, {"phase": "done"}],
                "exported_files": [],
            }
        )

        self.assertTrue(summary["selection_probe_only"])
        self.assertEqual(summary["selected_count"], 10)
        self.assertEqual(summary["exported_file_count"], 0)


if __name__ == "__main__":
    unittest.main()
