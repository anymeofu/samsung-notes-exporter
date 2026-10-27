from __future__ import annotations

import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from sn_archive_exporter.root_export_runner import (
    RootRunnerConfig,
    audit_run_completion,
    bind_export_format,
    child_path,
    classify_folder,
    collect_archive_outputs_from_state,
    collect_folder_paths_from_state,
    empty_state,
    finalize_run_archive,
    find_unique_folder_tree_row,
    find_subfolder_by_title,
    direct_notes_already_exported,
    is_safe_subfolder_title,
    load_seed_entries,
    load_runner_state,
    max_folder_limit_reached,
    navigate_to_top_level_folder,
    normalized_folder_path,
    is_completed,
    normalize_transient_states,
    record_folder,
    run_current_folder,
    run_recursive_current_folder,
    run_visible_subfolders,
    safe_slug,
    seed_completed_folders,
    save_runner_state,
    tap_subfolder,
    visible_child_titles,
    verify_current_folder_completion,
)


def summary(
    folder_path: str,
    *,
    note_count: int | None = None,
    folder_count: int | None = None,
    note_cards: int = 0,
    subfolders: list[str] | None = None,
    show_all: bool = False,
) -> dict:
    subfolders = subfolders or []
    return {
        "is_samsung_notes_visible": True,
        "packages": ["com.samsung.android.app.notes"],
        "folder_path": folder_path,
        "visible_counts": {"note_count": note_count, "folder_count": folder_count},
        "note_card_count": note_cards,
        "subfolder_count": len(subfolders),
        "subfolders": [{"title": title} for title in subfolders],
        "subfolder_expand": {
            "available": show_all,
            "is_show_all": show_all,
            "ambiguous": False,
            "enabled": True,
            "center": [540, 1500],
        },
    }


class RootExportRunnerTests(unittest.TestCase):
    def test_find_unique_folder_tree_row_uses_clickable_ancestor_bounds(self) -> None:
        root = ET.fromstring(
            '<hierarchy><node resource-id="com.samsung.android.app.notes:id/selected_holder" '
            'clickable="true" bounds="[63,1039][895,1146]">'
            '<node resource-id="com.samsung.android.app.notes:id/title" text="Codex" '
            'bounds="[279,1060][417,1125]" /></node></hierarchy>'
        )

        target = find_unique_folder_tree_row(root, "Codex")

        self.assertEqual(target["bounds"], "[63,1039][895,1146]")
        self.assertEqual(target["center"], [479, 1092])

    def test_find_unique_folder_tree_row_refuses_duplicate_titles(self) -> None:
        root = ET.fromstring(
            '<hierarchy>'
            '<node resource-id="com.samsung.android.app.notes:id/selected_holder" clickable="true" bounds="[0,0][10,10]">'
            '<node resource-id="com.samsung.android.app.notes:id/title" text="Codex" /></node>'
            '<node resource-id="com.samsung.android.app.notes:id/selected_holder" clickable="true" bounds="[0,10][10,20]">'
            '<node resource-id="com.samsung.android.app.notes:id/title" text="Codex" /></node>'
            '</hierarchy>'
        )

        with self.assertRaisesRegex(SystemExit, "ambiguous title"):
            find_unique_folder_tree_row(root, "Codex")

    def test_navigate_to_top_level_folder_skips_actions_when_already_there(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=True,
                wait_seconds=0.0,
                max_visible_batches=2,
                max_empty_scrolls=2,
            )

            with mock.patch("sn_archive_exporter.root_export_runner.dump_navigation_xml") as dump:
                result = navigate_to_top_level_folder(
                    config,
                    "Codex",
                    summary_provider=lambda _config, _label, _allowed: summary("Codex"),
                )

        self.assertEqual(result["status"], "already_at_target")
        dump.assert_not_called()

    def test_navigate_to_top_level_folder_rejects_nested_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=False,
                wait_seconds=0.0,
                max_visible_batches=2,
                max_empty_scrolls=2,
            )

            with self.assertRaisesRegex(SystemExit, "top-level"):
                navigate_to_top_level_folder(config, "Codex/Export")

    def test_classify_small_leaf_from_note_count(self) -> None:
        result = classify_folder(summary("TestEscape", note_count=23, note_cards=4))

        self.assertEqual(result["strategy"], "small_leaf_all_select")
        self.assertEqual(result["note_count"], 23)
        self.assertFalse(result["has_subfolders"])

    def test_classify_large_leaf_uses_visible_batches(self) -> None:
        result = classify_folder(summary("TestTasting/커피", note_count=408, note_cards=4))

        self.assertEqual(result["strategy"], "large_leaf_visible_batches")

    def test_classify_mixed_tree_when_notes_and_folders_are_visible(self) -> None:
        result = classify_folder(summary("Codex", note_count=2, folder_count=3, note_cards=2, subfolders=["Export"]))

        self.assertEqual(result["strategy"], "mixed_tree")

    def test_safe_slug_is_filesystem_friendly(self) -> None:
        self.assertEqual(safe_slug("TestTasting/커피"), "TestTasting_커피")

    def test_child_path_treats_root_folder_label_as_empty(self) -> None:
        self.assertEqual(child_path("폴더", "TestEscape"), "TestEscape")
        self.assertEqual(child_path("TestTasting", "커피"), "TestTasting/커피")

    def test_safe_subfolder_title_filters_path_like_pseudo_entries(self) -> None:
        self.assertTrue(is_safe_subfolder_title("."))
        self.assertTrue(is_safe_subfolder_title(".."))
        self.assertFalse(is_safe_subfolder_title("/"))
        self.assertTrue(is_safe_subfolder_title("형"))

    def test_visible_child_titles_preserves_dot_named_folders(self) -> None:
        self.assertEqual(visible_child_titles(summary("TestMaterials", subfolders=[".", "형", "..", "/"])), [".", "형", ".."])

    def test_find_subfolder_by_title(self) -> None:
        item = find_subfolder_by_title(summary("TestMaterials", subfolders=["레서피", "여행"]), "여행")

        self.assertIsNotNone(item)
        self.assertEqual(item["title"], "여행")

    def test_tap_subfolder_uses_left_biased_point_when_bounds_available(self) -> None:
        subfolder = {"bounds": "[814,932][1040,1158]", "center": [927, 1045]}

        with mock.patch("sn_archive_exporter.ui_guard.tap") as tap:
            tap_subfolder(subfolder)

        tap.assert_called_once_with(870, 1045)

    def test_normalized_folder_path_treats_empty_breadcrumb_with_subfolders_as_root(self) -> None:
        root_summary = summary("", folder_count=2, subfolders=["TestEscape", "TestClub"])

        self.assertEqual(normalized_folder_path(root_summary), "폴더")
        self.assertEqual(classify_folder(root_summary)["folder_path"], "폴더")

    def test_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = empty_state("run")
            state["folders"]["TestEscape"] = {"status": "completed"}

            save_runner_state(path, state)
            loaded = load_runner_state(path, "run")

            self.assertEqual(loaded["folders"]["TestEscape"]["status"], "completed")

    def test_load_runner_state_recovers_entering_to_planned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = empty_state("run")
            state["folders"]["TestClub/베이킹"] = {
                "status": "entering",
                "strategy": "recursive_child",
                "detail": {"parent_path": "TestClub"},
            }
            path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

            loaded = load_runner_state(path, "run")

            record = loaded["folders"]["TestClub/베이킹"]
            self.assertEqual(record["status"], "planned")
            self.assertEqual(record["detail"]["recovered_from_transient_status"], "entering")

    def test_normalize_transient_states_is_noop_for_completed(self) -> None:
        state = empty_state("run")
        state["folders"]["TestClub/TestClubA"] = {"status": "completed", "detail": {}}

        normalize_transient_states(state)

        self.assertEqual(state["folders"]["TestClub/TestClubA"]["status"], "completed")

    def test_record_folder_preserves_existing_archive_detail_during_reentry(self) -> None:
        state = empty_state("run")
        state["folders"]["Codex"] = {
            "status": "direct_notes_completed",
            "strategy": "mixed_tree",
            "detail": {
                "archive_output": "output_archive/codex",
                "validation": {"status": "ok"},
            },
        }

        record_folder(
            state,
            "Codex",
            status="entering",
            strategy="recursive_child",
            detail={"parent_path": "폴더", "depth": 1},
        )

        detail = state["folders"]["Codex"]["detail"]
        self.assertEqual(detail["archive_output"], "output_archive/codex")
        self.assertEqual(detail["validation"]["status"], "ok")
        self.assertEqual(detail["parent_path"], "폴더")

    def test_load_seed_entries_accepts_strings_and_archive_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "seed.json"
            path.write_text(
                json.dumps(
                    {
                        "folders": [
                            "TestEscape",
                            {"folder_path": "TestTasting", "archive_output": "output_archive/sieum_all"},
                            {
                                "folder_path": "TestClub",
                                "status": "direct_notes_completed",
                                "strategy": "mixed_tree",
                                "archive_output": "output_archive/club",
                            },
                            {"path": "TestCraft"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            entries = load_seed_entries(path)

            self.assertEqual(entries[0], {"folder_path": "TestEscape"})
            self.assertEqual(entries[1], {"folder_path": "TestTasting", "archive_output": "output_archive/sieum_all"})
            self.assertEqual(
                entries[2],
                {
                    "folder_path": "TestClub",
                    "archive_output": "output_archive/club",
                    "status": "direct_notes_completed",
                    "strategy": "mixed_tree",
                },
            )
            self.assertEqual(entries[3], {"folder_path": "TestCraft"})

    def test_seed_completed_folders_marks_skip_and_archive_output(self) -> None:
        state = empty_state("run")

        result = seed_completed_folders(
            state,
            [{"folder_path": "TestTasting", "archive_output": "output_archive/sieum_all"}],
            source="seed.json",
        )

        self.assertEqual(result["seeded_count"], 1)
        self.assertTrue(isinstance(state["folders"]["TestTasting"], dict))
        self.assertEqual(state["folders"]["TestTasting"]["status"], "completed")
        self.assertEqual(state["folders"]["TestTasting"]["strategy"], "seeded_completed")
        self.assertEqual(state["folders"]["TestTasting"]["detail"]["archive_output"], "output_archive/sieum_all")

    def test_seed_direct_notes_completed_keeps_mixed_folder_traversable(self) -> None:
        state = empty_state("run")

        seed_completed_folders(
            state,
            [
                {
                    "folder_path": "TestClub",
                    "status": "direct_notes_completed",
                    "strategy": "mixed_tree",
                    "archive_output": "output_archive/club",
                }
            ],
            source="seed.json",
        )

        self.assertFalse(is_completed(state, "TestClub"))
        self.assertTrue(direct_notes_already_exported(state, "TestClub"))
        self.assertEqual(state["folders"]["TestClub"]["status"], "direct_notes_completed")

    def test_excluded_from_run_is_skipped_without_entering_archive_merge(self) -> None:
        state = empty_state("run")
        seed_completed_folders(
            state,
            [
                {
                    "folder_path": "TestEscape",
                    "status": "excluded_from_run",
                    "strategy": "test_scope_exclusion",
                }
            ],
            source="e2e-seed.json",
        )

        self.assertTrue(is_completed(state, "TestEscape"))
        self.assertEqual(collect_archive_outputs_from_state(state), [])
        self.assertEqual(collect_folder_paths_from_state(state), [])

    def test_collect_archive_outputs_and_folder_paths_from_state(self) -> None:
        state = empty_state("run")
        state["folders"] = {
            "TestTasting": {"status": "traversing", "detail": {}},
            "TestTasting/커피": {"status": "completed", "detail": {"archive_output": "output/coffee"}},
            "TestTasting/와인": {
                "status": "completed",
                "detail": {"export": {"handoff": {"archive_output": "output/wine"}}},
            },
            "TestTasting/차": {"status": "planned", "detail": {}},
            "폴더": {"status": "deferred_current_export", "detail": {}},
            "TestMaterials/.": {"status": "ignored_bad_path", "detail": {"archive_output": "output/bad"}},
            "TestMaterials/형": {"status": "needs_review", "detail": {"archive_output": "output/review"}},
        }

        self.assertEqual(
            [str(path) for path in collect_archive_outputs_from_state(state)],
            ["output/coffee", "output/wine"],
        )
        self.assertEqual(collect_folder_paths_from_state(state), ["TestTasting", "TestTasting/커피", "TestTasting/와인"])

    def test_max_folder_limit_ignores_entering_transient_state(self) -> None:
        state = empty_state("run")
        state["folders"] = {
            "폴더": {"status": "deferred_current_export"},
            "TestEscape": {"status": "entering"},
            "TestTasting": {"status": "completed", "strategy": "seeded_completed"},
            "TestMaterials": {"status": "excluded_from_run", "strategy": "test_scope_exclusion"},
        }
        config = RootRunnerConfig(
            run_id="run",
            state_path=Path("state.json"),
            input_root=Path("input"),
            archive_root=Path("archive"),
            out_dir=Path("ui"),
            execute=True,
            wait_seconds=0.1,
            max_visible_batches=2,
            max_empty_scrolls=2,
            max_folders=2,
        )

        self.assertFalse(max_folder_limit_reached(state, config))

    def test_bind_export_format_rejects_reusing_old_sdocx_state_for_txt(self) -> None:
        state = empty_state("run")
        state["folders"]["Codex"] = {"status": "completed"}

        with self.assertRaisesRegex(SystemExit, "state export_format='sdocx'"):
            bind_export_format(state, "txt")

    def test_run_current_folder_dry_run_records_small_leaf_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=False,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
                export_format="txt",
            )

            result = run_current_folder(
                config,
                summary_provider=lambda _config, _label, _allowed: summary("TestEscape", note_count=23, note_cards=4),
            )

            self.assertEqual(result["status"], "planned")
            self.assertEqual(result["strategy"], "small_leaf_all_select")
            saved = json.loads(config.state_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["folders"]["TestEscape"]["status"], "planned")
            self.assertTrue(saved["folders"]["TestEscape"]["detail"]["dry_run"])

    def test_run_current_folder_large_leaf_calls_visible_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=True,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
                export_format="txt",
            )

            with mock.patch(
                "sn_archive_exporter.root_export_runner.run_visible_batches",
                return_value={
                    "status": "ok",
                    "run_id": "root_run_TestTasting_커피",
                    "seen_fingerprint_count": 4,
                    "batch_count": 1,
                    "new_batches": [{"batch_id": "batch001_4notes"}],
                    "observations": [{}],
                },
            ) as run_batches:
                result = run_current_folder(
                    config,
                    summary_provider=lambda _config, _label, _allowed: summary("TestTasting/커피", note_count=408, note_cards=4),
                )

            self.assertEqual(result["status"], "in_progress")
            self.assertEqual(result["strategy"], "large_leaf_visible_batches")
            run_batches.assert_called_once()
            self.assertEqual(run_batches.call_args.args[0].export_format, "txt")

    def test_run_current_folder_resumes_large_leaf_strategy_when_count_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=True,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
                export_format="txt",
            )
            state = empty_state("root_run")
            state["folders"]["TestTasting/커피"] = {
                "status": "in_progress",
                "strategy": "large_leaf_visible_batches",
                "detail": {},
            }

            with mock.patch(
                "sn_archive_exporter.root_export_runner.run_large_leaf",
                return_value={"visible_batches": {"status": "ok"}},
            ) as run_large:
                result = run_current_folder(
                    config,
                    state=state,
                    summary_provider=lambda _config, _label, _allowed: summary(
                        "TestTasting/커피", note_count=None, note_cards=4
                    ),
                )

            self.assertEqual(result["strategy"], "large_leaf_visible_batches")
            self.assertEqual(result["classification"]["strategy_source"], "resumed_visible_batch_state")
            run_large.assert_called_once()

    def test_run_current_folder_recovers_visible_batch_strategy_after_planned_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=True,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
                export_format="txt",
            )
            state = empty_state("root_run")
            state["folders"]["TestTasting/커피"] = {
                "status": "planned",
                "strategy": "small_leaf_all_select",
                "detail": {
                    "state_path": "archive/root_run/coffee.visible_state.json",
                    "visible_batches": {"seen_fingerprint_count": 330, "batch_count": 84},
                },
            }

            with mock.patch(
                "sn_archive_exporter.root_export_runner.run_large_leaf",
                return_value={"visible_batches": {"status": "ok"}},
            ) as run_large:
                result = run_current_folder(
                    config,
                    state=state,
                    summary_provider=lambda _config, _label, _allowed: summary(
                        "TestTasting/커피", note_count=None, note_cards=4
                    ),
                )

            self.assertEqual(result["strategy"], "large_leaf_visible_batches")
            self.assertEqual(result["classification"]["strategy_source"], "resumed_visible_batch_state")
            run_large.assert_called_once()

    def test_run_current_folder_skips_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=False,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
            )
            state = empty_state("root_run")
            state["folders"]["TestEscape"] = {"status": "completed"}

            result = run_current_folder(
                config,
                state=state,
                summary_provider=lambda _config, _label, _allowed: summary("TestEscape", note_count=23, note_cards=4),
            )

            self.assertEqual(result["status"], "skipped_completed")

    def test_partial_mixed_tree_completed_record_is_not_subtree_completed(self) -> None:
        state = empty_state("root_run")
        state["folders"]["TestClub"] = {
            "status": "completed",
            "strategy": "mixed_tree",
            "detail": {
                "archive_output": "output_archive/club",
                "classification": {"has_subfolders": True},
            },
        }

        self.assertFalse(is_completed(state, "TestClub"))
        self.assertTrue(direct_notes_already_exported(state, "TestClub"))

    def test_run_visible_subfolders_dry_run_records_visible_children(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=False,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
            )

            result = run_visible_subfolders(
                config,
                summary_provider=lambda _config, _label, _allowed: summary(
                    "폴더",
                    folder_count=2,
                    subfolders=["TestEscape", "TestClub"],
                ),
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["subfolder_count"], 2)
            saved = json.loads(config.state_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["folders"]["TestEscape"]["status"], "planned")
            self.assertEqual(saved["folders"]["TestClub"]["status"], "planned")

    def test_run_visible_subfolders_execute_enters_each_uncompleted_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=True,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
            )

            with mock.patch("sn_archive_exporter.root_export_runner.tap_subfolder") as tap, mock.patch(
                "sn_archive_exporter.root_export_runner.back_to_parent"
            ) as back:
                result = run_visible_subfolders(
                    config,
                    summary_provider=lambda _config, _label, _allowed: summary(
                        "폴더",
                        folder_count=1,
                        subfolders=["TestEscape"],
                    ),
                    current_folder_runner=lambda _config, _state: {"status": "completed", "folder_path": "TestEscape"},
                )

            self.assertEqual(result["processed_count"], 1)
            tap.assert_called_once()
            back.assert_called_once()

    def test_run_recursive_current_folder_dry_run_plans_nested_children(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=False,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
                max_depth=2,
            )

            result = run_recursive_current_folder(
                config,
                summary_provider=lambda _config, _label, _allowed: summary(
                    "TestTasting",
                    folder_count=2,
                    subfolders=["커피", "와인"],
                ),
            )

            self.assertEqual(result["status"], "traversed")
            self.assertEqual(len(result["children"]), 2)
            saved = json.loads(config.state_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["folders"]["TestTasting"]["status"], "traversing")
            self.assertEqual(saved["folders"]["TestTasting/커피"]["status"], "planned")
            self.assertEqual(saved["folders"]["TestTasting/와인"]["status"], "planned")

    def test_verify_current_folder_completion_reports_complete_visible_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=False,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
            )
            state = empty_state("root_run")
            state["folders"] = {
                "폴더": {"status": "direct_notes_completed", "strategy": "mixed_tree", "detail": {"archive_output": "root"}},
                "TestEscape": {"status": "completed", "strategy": "small_leaf_all_select", "detail": {"archive_output": "bangtal"}},
                "TestClub": {"status": "direct_notes_completed", "strategy": "mixed_tree", "detail": {"archive_output": "club"}},
            }

            result = verify_current_folder_completion(
                config,
                state=state,
                summary_provider=lambda _config, _label, _allowed: summary(
                    "폴더",
                    note_count=2,
                    folder_count=2,
                    note_cards=2,
                    subfolders=["TestEscape", "TestClub"],
                ),
            )

            self.assertEqual(result["status"], "complete_visible")
            self.assertEqual(result["missing_visible_child_count"], 0)
            self.assertTrue(result["direct_notes"]["accounted"])

    def test_audit_run_completion_reports_complete_for_valid_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=False,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
            )
            state = empty_state("root_run")
            state["folders"] = {
                "TestEscape": {"status": "completed", "detail": {"archive_output": "output/bangtal"}},
                "TestMaterials/학교": {"status": "empty_or_unknown", "detail": {}},
                "TestMaterials/형": {"status": "ignored_bad_path", "detail": {"replaced_by": "TestMaterials/./형"}},
                "TestTasting": {"status": "excluded_from_run", "strategy": "test_scope_exclusion", "detail": {}},
                "TestFood": {"status": "traversed", "strategy": "nested_tree", "detail": {}},
            }

            with mock.patch(
                "sn_archive_exporter.root_export_runner.validate_archive",
                return_value={"status": "ok", "counts": {"folders": 1, "notes": 2, "files": 2}, "errors": [], "warnings": []},
            ):
                result = audit_run_completion(config, state=state)

            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["archive_output_count"], 1)
            self.assertEqual(result["ignored_bad_path_count"], 1)

    def test_audit_allows_deferred_starting_folder_when_config_skips_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=False,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
                skip_current_folder_export=True,
            )
            state = empty_state("root_run")
            state["folders"] = {
                "폴더": {"status": "deferred_current_export", "strategy": "mixed_tree", "detail": {}},
                "Codex": {"status": "completed", "detail": {"archive_output": "output/codex"}},
            }

            with mock.patch(
                "sn_archive_exporter.root_export_runner.validate_archive",
                return_value={"status": "ok", "counts": {"folders": 1, "notes": 2, "files": 2}, "errors": [], "warnings": []},
            ):
                result = audit_run_completion(config, state=state)

            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["pending_count"], 0)
            self.assertEqual(collect_folder_paths_from_state(state), ["Codex"])

    def test_audit_run_completion_reports_pending_missing_and_invalid_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=False,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
            )
            state = empty_state("root_run")
            state["folders"] = {
                "대기": {"status": "planned", "detail": {}},
                "누락": {"status": "completed", "detail": {}},
                "손상": {"status": "completed", "detail": {"archive_output": "output/broken"}},
            }

            with mock.patch(
                "sn_archive_exporter.root_export_runner.validate_archive",
                return_value={"status": "error", "counts": None, "errors": ["missing"], "warnings": []},
            ):
                result = audit_run_completion(config, state=state)

            self.assertEqual(result["status"], "needs_review")
            self.assertEqual(result["pending_count"], 1)
            self.assertEqual(result["missing_archive_count"], 1)
            self.assertEqual(result["invalid_archive_count"], 1)

    def test_verify_current_folder_completion_reports_missing_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=False,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
            )
            state = empty_state("root_run")
            state["folders"]["TestEscape"] = {"status": "completed", "detail": {"archive_output": "bangtal"}}

            result = verify_current_folder_completion(
                config,
                state=state,
                summary_provider=lambda _config, _label, _allowed: summary(
                    "폴더",
                    folder_count=2,
                    subfolders=["TestEscape", "TestClub"],
                ),
            )

            self.assertEqual(result["status"], "pending_visible_children")
            self.assertEqual([item["folder_path"] for item in result["missing_visible_children"]], ["TestClub"])

    def test_verify_current_folder_completion_reports_pending_direct_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=False,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
            )

            result = verify_current_folder_completion(
                config,
                state=empty_state("root_run"),
                summary_provider=lambda _config, _label, _allowed: summary("TestResearch", note_count=2, note_cards=2),
            )

            self.assertEqual(result["status"], "pending_direct_notes")
            self.assertFalse(result["direct_notes"]["accounted"])

    def test_verify_current_folder_completion_reports_hidden_children(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=False,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
            )
            state = empty_state("root_run")
            state["folders"]["Codex/폴더 1"] = {"status": "completed", "detail": {"archive_output": "one"}}

            result = verify_current_folder_completion(
                config,
                state=state,
                summary_provider=lambda _config, _label, _allowed: summary(
                    "Codex",
                    folder_count=12,
                    subfolders=["폴더 1"],
                    show_all=True,
                ),
            )

            self.assertEqual(result["status"], "unknown_hidden_children")
            self.assertTrue(result["hidden_children_may_exist"])

    def test_run_recursive_current_folder_execute_enters_child_and_returns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=True,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
                max_depth=2,
            )
            summaries = iter(
                [
                    summary("TestTasting", folder_count=1, subfolders=["와인"]),
                    summary("TestTasting", folder_count=1, subfolders=["와인"]),
                    summary("TestTasting/와인", note_count=33, note_cards=4),
                ]
            )

            with mock.patch("sn_archive_exporter.root_export_runner.tap_subfolder") as tap, mock.patch(
                "sn_archive_exporter.root_export_runner.back_to_parent"
            ) as back, mock.patch(
                "sn_archive_exporter.root_export_runner.run_small_leaf",
                return_value={
                    "export": {"status": "ok"},
                    "validation": {"status": "ok"},
                    "archive_output": "archive",
                },
            ):
                result = run_recursive_current_folder(
                    config,
                    summary_provider=lambda _config, _label, _allowed: next(summaries),
                )

            self.assertEqual(result["children"][0]["status"], "completed")
            saved = json.loads(config.state_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["folders"]["TestTasting"]["status"], "traversed")
            tap.assert_called_once()
            back.assert_called_once()

    def test_run_recursive_current_folder_expands_show_all_before_children(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=True,
                wait_seconds=0.0,
                max_visible_batches=2,
                max_empty_scrolls=2,
                max_depth=1,
            )
            summaries = iter(
                [
                    summary("Codex", folder_count=12, subfolders=["폴더 1"], show_all=True),
                    summary("Codex", folder_count=12, subfolders=["폴더 1", "폴더 2"]),
                    summary("Codex", folder_count=12, subfolders=["폴더 1", "폴더 2"]),
                    summary("Codex/폴더 1"),
                    summary("Codex", folder_count=12, subfolders=["폴더 1", "폴더 2"]),
                    summary("Codex/폴더 2"),
                ]
            )

            with mock.patch("sn_archive_exporter.root_export_runner.tap_subfolder_expand") as expand, mock.patch(
                "sn_archive_exporter.root_export_runner.tap_subfolder"
            ) as tap, mock.patch("sn_archive_exporter.root_export_runner.back_to_parent"):
                result = run_recursive_current_folder(
                    config,
                    summary_provider=lambda _config, _label, _allowed: next(summaries),
                )

            expand.assert_called_once()
            self.assertEqual(tap.call_count, 2)
            self.assertEqual([child["folder_path"] for child in result["children"]], ["Codex/폴더 1", "Codex/폴더 2"])

    def test_recursive_refreshes_parent_before_each_child_tap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=True,
                wait_seconds=0.0,
                max_visible_batches=2,
                max_empty_scrolls=2,
                max_depth=1,
            )
            summaries = iter(
                [
                    summary("TestMaterials", folder_count=2, subfolders=["레서피", "여행"]),
                    summary("TestMaterials", folder_count=2, subfolders=["레서피", "여행"]),
                    summary("TestMaterials/레서피"),
                    summary("TestMaterials", folder_count=2, subfolders=["레서피", "여행"]),
                    summary("TestMaterials/여행"),
                ]
            )

            with mock.patch("sn_archive_exporter.root_export_runner.tap_subfolder") as tap, mock.patch(
                "sn_archive_exporter.root_export_runner.back_to_parent"
            ):
                result = run_recursive_current_folder(
                    config,
                    summary_provider=lambda _config, _label, _allowed: next(summaries),
                )

            self.assertEqual(tap.call_count, 2)
            self.assertEqual([child["folder_path"] for child in result["children"]], ["TestMaterials/레서피", "TestMaterials/여행"])

    def test_recursive_preserves_dot_child_titles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=False,
                wait_seconds=0.0,
                max_visible_batches=2,
                max_empty_scrolls=2,
                max_depth=1,
            )

            result = run_recursive_current_folder(
                config,
                summary_provider=lambda _config, _label, _allowed: summary(
                    "TestMaterials",
                    folder_count=3,
                    subfolders=[".", "형", "/"],
                ),
            )

            self.assertEqual([child["folder_path"] for child in result["children"]], ["TestMaterials/.", "TestMaterials/형"])

    def test_run_recursive_current_folder_respects_max_depth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=False,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
                max_depth=0,
            )

            result = run_recursive_current_folder(
                config,
                summary_provider=lambda _config, _label, _allowed: summary(
                    "TestTasting",
                    folder_count=1,
                    subfolders=["커피"],
                ),
            )

            self.assertEqual(result["status"], "traversed")
            saved = json.loads(config.state_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["folders"]["TestTasting"]["status"], "skipped_children_max_depth")
            self.assertNotIn("TestTasting/커피", saved["folders"])

    def test_mixed_tree_large_direct_notes_needs_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=True,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
            )

            result = run_current_folder(
                config,
                summary_provider=lambda _config, _label, _allowed: summary(
                    "TestMaterials",
                    note_count=150,
                    folder_count=1,
                    note_cards=4,
                    subfolders=["하위"],
                ),
            )

            self.assertEqual(result["status"], "needs_review")
            self.assertEqual(result["strategy"], "mixed_tree")

    def test_mixed_tree_direct_export_marks_direct_notes_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=True,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
            )

            with mock.patch(
                "sn_archive_exporter.root_export_runner.run_mixed_folder_direct_notes",
                return_value={"export": {"status": "ok"}, "validation": {"status": "ok"}, "archive_output": "archive"},
            ):
                result = run_current_folder(
                    config,
                    summary_provider=lambda _config, _label, _allowed: summary(
                        "TestClub",
                        note_count=8,
                        folder_count=4,
                        note_cards=3,
                        subfolders=["TestClubB"],
                    ),
                )

            self.assertEqual(result["status"], "direct_notes_completed")
            saved = json.loads(config.state_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["folders"]["TestClub"]["status"], "direct_notes_completed")

    def test_recursive_mixed_tree_with_existing_direct_export_traverses_children(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=False,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
                max_depth=1,
            )
            state = empty_state("root_run")
            state["folders"]["TestClub"] = {
                "status": "completed",
                "strategy": "mixed_tree",
                "detail": {
                    "archive_output": "output_archive/club",
                    "classification": {"has_subfolders": True},
                },
            }

            result = run_recursive_current_folder(
                config,
                state=state,
                summary_provider=lambda _config, _label, _allowed: summary(
                    "TestClub",
                    note_count=8,
                    folder_count=1,
                    note_cards=3,
                    subfolders=["TestClubA"],
                ),
            )

            self.assertIsNone(result["direct_result"])
            self.assertEqual(result["children"][0]["folder_path"], "TestClub/TestClubA")
            saved = json.loads(config.state_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["folders"]["TestClub"]["status"], "direct_notes_completed")

    def test_recursive_mixed_tree_refreshes_child_bounds_after_direct_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=False,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
                max_depth=1,
            )
            summaries = iter(
                [
                    summary("TestMaterials", note_count=16, folder_count=1, note_cards=1, subfolders=["레서피"]),
                    summary("TestMaterials", note_count=16, folder_count=1, note_cards=1, subfolders=["레서피"]),
                ]
            )

            result = run_recursive_current_folder(
                config,
                summary_provider=lambda _config, _label, _allowed: next(summaries),
            )

            self.assertEqual(result["children"][0]["folder_path"], "TestMaterials/레서피")

    def test_recursive_child_refuses_unexpected_folder_after_tap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=False,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
                max_depth=1,
            )

            with self.assertRaises(SystemExit) as raised:
                run_recursive_current_folder(
                    config,
                    depth=1,
                    expected_path="TestHospital",
                    summary_provider=lambda _config, _label, _allowed: summary(
                        "폴더",
                        folder_count=10,
                        subfolders=["TestHospital"],
                    ),
                )

            self.assertIn("expected child folder", str(raised.exception))

    def test_recursive_skip_current_folder_export_defers_parent_and_plans_children(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=False,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
                max_depth=1,
                skip_current_folder_export=True,
            )

            result = run_recursive_current_folder(
                config,
                summary_provider=lambda _config, _label, _allowed: summary(
                    "폴더",
                    note_count=8,
                    folder_count=2,
                    note_cards=1,
                    subfolders=["TestEscape", "TestClub"],
                ),
            )

            self.assertIsNone(result["direct_result"])
            saved = json.loads(config.state_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["folders"]["폴더"]["status"], "deferred_current_export")
            self.assertEqual(saved["folders"]["TestEscape"]["status"], "planned")

    def test_recursive_skip_current_folder_export_does_not_skip_child_depth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=True,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
                max_depth=1,
                skip_current_folder_export=True,
            )

            with mock.patch(
                "sn_archive_exporter.root_export_runner.run_small_leaf",
                return_value={"export": {"status": "ok"}, "validation": {"status": "ok"}},
            ) as run_leaf:
                result = run_recursive_current_folder(
                    config,
                    depth=1,
                    summary_provider=lambda _config, _label, _allowed: summary("TestEscape", note_count=23, note_cards=4),
                )

            self.assertEqual(result["status"], "completed")
            run_leaf.assert_called_once()

    def test_finalize_run_archive_merges_state_outputs_and_validates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=True,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
            )
            state = empty_state("root_run")
            state["folders"] = {
                "TestEscape": {"status": "completed", "detail": {"archive_output": "output/bangtal"}},
            }

            with mock.patch(
                "sn_archive_exporter.root_export_runner.merge_folder_archive_outputs",
                return_value={
                    "planned_copies": [{"source": "a", "target": "b"}],
                    "manifest": {"counts": {"folders": 1, "notes": 23, "files": 23}},
                },
            ) as merge, mock.patch(
                "sn_archive_exporter.root_export_runner.validate_archive",
                return_value={"status": "ok", "counts": {"folders": 1, "notes": 23, "files": 23}},
            ) as validate:
                result = finalize_run_archive(config, state=state, output=tmp_path / "merged")

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["archive_output_count"], 1)
            self.assertEqual(result["planned_copy_count"], 1)
            merge.assert_called_once()
            validate.assert_called_once_with(tmp_path / "merged")

    def test_finalize_run_archive_reports_no_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            config = RootRunnerConfig(
                run_id="root_run",
                state_path=tmp_path / "state.json",
                input_root=tmp_path / "input",
                archive_root=tmp_path / "archive",
                out_dir=tmp_path / "ui",
                execute=True,
                wait_seconds=0.1,
                max_visible_batches=2,
                max_empty_scrolls=2,
            )

            result = finalize_run_archive(config, state=empty_state("root_run"))

            self.assertEqual(result["status"], "no_archives")


if __name__ == "__main__":
    unittest.main()
