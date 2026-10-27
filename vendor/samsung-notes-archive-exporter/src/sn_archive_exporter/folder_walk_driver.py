from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import ui_guard
from .archive_builder import sanitize_folder_path, sanitize_path_part
from .guarded_export_driver import (
    EXPORT_FORMATS,
    DriverConfig,
    dump_ui,
    log,
    run_guarded_export,
    set_quiet,
    summarize_export_result,
)
from .workflow_state import ArtifactRef, SkippedCandidate, WorkflowPhase, WorkflowRunState, initial_workflow_state


@dataclass
class WalkConfig:
    root_path: str
    run_id: str
    input_root: Path
    archive_root: Path | None
    out_dir: Path
    execute: bool
    max_depth: int
    max_subfolder_scrolls: int
    wait_seconds: float
    export_format: str = "sdocx"
    max_folders: int | None = None
    export_enabled: bool = True
    mixed_folder_select_all: bool = False
    deselect_scroll_attempts: int = 4
    deselect_max_taps: int = 80
    observation_dir: Path | None = None
    observation_level: int = 0
    observation_max_candidates: int = 35
    run_summary_path: Path | None = None
    allow_existing_output: bool = False
    visited: set[str] = field(default_factory=set)
    workflow_state: WorkflowRunState | None = None
    workflow_events: list[dict[str, Any]] = field(default_factory=list)


def assert_under_root(folder_path: str, root_path: str) -> None:
    if folder_path != root_path and not folder_path.startswith(root_path.rstrip("/") + "/"):
        raise SystemExit(f"Refusing action: folder_path={folder_path!r} is outside root_path={root_path!r}")


def folder_slug(folder_path: str) -> str:
    safe = sanitize_folder_path(folder_path)
    return sanitize_path_part(str(safe).replace("/", "__"))


def subfolder_tap_point(subfolder: dict[str, Any]) -> tuple[int, int]:
    bounds = ui_guard.parse_bounds(subfolder.get("bounds", ""))
    if bounds is None:
        raise SystemExit(f"Refusing action: subfolder target has invalid bounds: {subfolder}")
    x = bounds.left + max(24, (bounds.right - bounds.left) // 4)
    y = (bounds.top + bounds.bottom) // 2
    return x, y


def tap_subfolder(subfolder: dict[str, Any]) -> None:
    if not subfolder.get("enabled"):
        raise SystemExit(f"Refusing action: subfolder target disabled: {subfolder}")
    x, y = subfolder_tap_point(subfolder)
    ui_guard.tap(x, y)


def tap_subfolder_expand(target: dict[str, Any]) -> None:
    if target.get("ambiguous"):
        raise SystemExit(f"Refusing action: ambiguous subfolder expand target: {target}")
    if not target.get("enabled"):
        raise SystemExit(f"Refusing action: subfolder expand target disabled: {target}")
    x, y = target["center"]
    ui_guard.tap(x, y)


def press_back() -> None:
    from .guarded_export_driver import adb

    adb(["shell", "input", "keyevent", "KEYCODE_BACK"], capture=True)


def press_notes_up_button() -> None:
    from .guarded_export_driver import adb

    adb(["shell", "input", "tap", "79", "178"], capture=True)


def swipe_subfolders_down() -> None:
    from .guarded_export_driver import adb

    adb(["shell", "input", "swipe", "540", "1850", "540", "650", "750"], capture=True)


def subfolder_key(subfolder: dict[str, Any]) -> tuple[str, str]:
    return (subfolder.get("title", ""), subfolder.get("content_desc", ""))


def subfolder_page_signature(subfolders: list[dict[str, Any]]) -> tuple[tuple[str, str, tuple[int, int]], ...]:
    return tuple((item.get("title", ""), item.get("content_desc", ""), tuple(item["center"])) for item in subfolders)


def record_workflow(config: WalkConfig, phase: WorkflowPhase, **kwargs: Any) -> WorkflowRunState:
    if config.workflow_state is None:
        config.workflow_state = initial_workflow_state(config.run_id, config.root_path)
    config.workflow_state = config.workflow_state.transition(phase, **kwargs)
    event = config.workflow_state.compact(artifact_limit=3, skipped_limit=3)
    event["sequence"] = len(config.workflow_events) + 1
    config.workflow_events.append(event)
    return config.workflow_state


def summarize_current(config: WalkConfig, step: str) -> tuple[Path, dict[str, Any]]:
    xml_path = dump_ui(
        DriverConfig(
            allowed_path=config.root_path,
            destination="Documents",
            out_dir=config.out_dir,
            label=f"{config.run_id}_{step}",
            execute=False,
            select_count=1,
            select_all=False,
            wait_seconds=config.wait_seconds,
            pull_to=None,
            mapping_path=None,
            archive_output=None,
            observation_dir=config.observation_dir,
            observation_level=config.observation_level,
            observation_max_candidates=config.observation_max_candidates,
            allow_existing_output=config.allow_existing_output,
            export_format=config.export_format,
        ),
        "screen",
    )
    summary = ui_guard.summarize(xml_path, [ui_guard.extract_folder_path(ui_guard.load_xml(xml_path))])
    folder_path = summary["folder_path"]
    if not summary["is_samsung_notes_visible"]:
        raise SystemExit(f"Refusing action: Samsung Notes is not visible. Packages: {summary['packages']}")
    assert_under_root(folder_path, config.root_path)
    record_workflow(
        config,
        WorkflowPhase.CLASSIFY_SCREEN,
        current_folder_path=folder_path,
        last_action=step,
        next_action="decide_folder_step",
        counts={
            "visible_note_cards": summary["note_card_count"],
            "visible_subfolders": len(summary["subfolders"]),
            "subfolder_expand_available": 1 if summary["subfolder_expand"].get("available") else 0,
        },
        artifacts=[ArtifactRef("ui_dump", xml_path, note=step)],
    )
    return xml_path, summary


def export_current_folder(
    config: WalkConfig,
    folder_path: str,
    note_count: int,
    *,
    select_all: bool,
    folder_has_subfolders: bool = False,
) -> dict[str, Any] | None:
    if not config.export_enabled:
        return None
    if note_count < 1:
        return None
    record_workflow(
        config,
        WorkflowPhase.EXPORT_CURRENT_FOLDER_NOTES,
        current_folder_path=folder_path,
        last_action="classify_screen",
        next_action="run_guarded_export",
        counts={
            "note_count_for_export": note_count,
            "select_all": 1 if select_all else 0,
        },
        exported_folder=folder_path,
    )
    slug = folder_slug(folder_path)
    pull_to = config.input_root / config.run_id / slug
    archive_output = config.archive_root / config.run_id / slug if config.archive_root is not None else None
    export_config = DriverConfig(
        allowed_path=folder_path,
        destination="Documents",
        out_dir=config.out_dir,
        label=f"{config.run_id}_{slug}_export",
        execute=config.execute,
        select_count=1 if select_all else note_count,
        select_all=select_all,
        wait_seconds=config.wait_seconds,
        pull_to=pull_to if config.execute else None,
        mapping_path=None,
        archive_output=archive_output if config.execute else None,
        observation_dir=config.observation_dir,
        observation_level=config.observation_level,
        observation_max_candidates=config.observation_max_candidates,
        allow_existing_output=config.allow_existing_output,
        deselect_visible_subfolders_after_select_all=folder_has_subfolders and config.mixed_folder_select_all,
        deselect_scroll_attempts=config.deselect_scroll_attempts,
        deselect_max_taps=config.deselect_max_taps,
        export_format=config.export_format,
        allow_partial_export=config.export_format == "txt",
    )
    return run_guarded_export(export_config)


def should_use_select_all_for_note_export(*, folder_has_subfolders: bool, mixed_folder_select_all: bool) -> bool:
    return not folder_has_subfolders or mixed_folder_select_all


def expand_subfolders_if_available(config: WalkConfig, folder_path: str, depth: int) -> dict[str, Any]:
    _, summary = summarize_current(config, f"depth{depth}_expand_check")
    if summary["folder_path"] != folder_path:
        raise SystemExit(f"Refusing action: expected {folder_path!r}, found {summary['folder_path']!r}")
    expand = summary["subfolder_expand"]
    if not expand.get("available"):
        return summary
    if not expand.get("is_show_all"):
        return summary
    if not config.execute:
        return summary
    record_workflow(
        config,
        WorkflowPhase.CLASSIFY_SCREEN,
        current_folder_path=folder_path,
        last_action="detect_show_all",
        next_action="tap_show_all",
        counts={"subfolder_expand_available": 1},
    )
    log("[walk] expanding hidden subfolders with 모두 보기")
    tap_subfolder_expand(expand)
    time.sleep(config.wait_seconds)
    _, expanded = summarize_current(config, f"depth{depth}_expanded")
    if expanded["folder_path"] != folder_path:
        raise SystemExit(f"Refusing action: expected {folder_path!r} after expand, found {expanded['folder_path']!r}")
    return expanded


def walk_folder(config: WalkConfig, depth: int = 0) -> dict[str, Any]:
    if depth > config.max_depth:
        raise SystemExit(f"Refusing action: max depth exceeded at depth {depth}")

    _, summary = summarize_current(config, f"depth{depth}_pre")
    folder_path = summary["folder_path"]
    if folder_path in config.visited:
        return {"folder_path": folder_path, "skipped": "already_visited"}
    config.visited.add(folder_path)
    record_workflow(
        config,
        WorkflowPhase.OBSERVE_SCREEN,
        current_folder_path=folder_path,
        last_action=f"depth{depth}_pre",
        next_action="export_or_walk_children",
        visited_folder=folder_path,
    )

    note_count = summary["note_card_count"]
    folder_has_subfolders = bool(summary["subfolders"])
    result: dict[str, Any] = {
        "folder_path": folder_path,
        "depth": depth,
        "visible_note_cards": note_count,
        "folder_has_subfolders": folder_has_subfolders,
        "direct_note_card_pages": [],
        "visible_subfolders": [{"title": item["title"], "center": item["center"]} for item in summary["subfolders"]],
        "export": None,
        "children": [],
    }

    result["export"] = export_current_folder(
        config,
        folder_path,
        note_count,
        folder_has_subfolders=folder_has_subfolders,
        select_all=should_use_select_all_for_note_export(
            folder_has_subfolders=folder_has_subfolders,
            mixed_folder_select_all=config.mixed_folder_select_all,
        ),
    )
    expanded_summary = expand_subfolders_if_available(config, folder_path, depth)
    folder_has_subfolders = folder_has_subfolders or bool(expanded_summary["subfolders"])
    result["folder_has_subfolders"] = folder_has_subfolders
    result["visible_subfolders"] = [
        {"title": item["title"], "center": item["center"]} for item in expanded_summary["subfolders"]
    ]

    processed_child_keys: set[tuple[str, str]] = set()
    previous_page_signature: tuple[tuple[str, str, tuple[int, int]], ...] | None = None
    scroll_index = 0

    while True:
        _, parent_summary = summarize_current(config, f"depth{depth}_page{scroll_index}_parent")
        if parent_summary["folder_path"] != folder_path:
            raise SystemExit(
                f"Refusing action: expected to be at {folder_path!r}, "
                f"found {parent_summary['folder_path']!r}"
            )
        page_note_count = parent_summary["note_card_count"]
        if page_note_count:
            result["visible_note_cards"] = max(result["visible_note_cards"], page_note_count)
            result["direct_note_card_pages"].append(
                {
                    "page": scroll_index,
                    "visible_note_cards": page_note_count,
                }
            )
            if result["export"] is None:
                log(f"[walk] found {page_note_count} direct note card(s) in {folder_path!r}")
                result["export"] = export_current_folder(
                    config,
                    folder_path,
                    page_note_count,
                    folder_has_subfolders=folder_has_subfolders,
                    select_all=should_use_select_all_for_note_export(
                        folder_has_subfolders=folder_has_subfolders,
                        mixed_folder_select_all=config.mixed_folder_select_all,
                    ),
                )
                if config.execute and config.export_enabled:
                    _, parent_summary = summarize_current(config, f"depth{depth}_page{scroll_index}_after_export")
                    if parent_summary["folder_path"] != folder_path:
                        raise SystemExit(
                            f"Refusing action: expected to remain at {folder_path!r} after export, "
                            f"found {parent_summary['folder_path']!r}"
                        )
        subfolders = parent_summary["subfolders"]
        if not subfolders:
            break
        page_signature = subfolder_page_signature(subfolders)
        if page_signature == previous_page_signature:
            break
        previous_page_signature = page_signature

        if not config.execute:
            for subfolder in subfolders:
                key = subfolder_key(subfolder)
                if key in processed_child_keys:
                    continue
                processed_child_keys.add(key)
                result["children"].append(
                    {
                        "folder_path": f"{folder_path}/{subfolder['title']}",
                        "dry_run": True,
                    }
                )
            break

        for index, subfolder in enumerate(subfolders, start=1):
            key = subfolder_key(subfolder)
            if key in processed_child_keys:
                continue
            processed_child_keys.add(key)
            child_path = f"{folder_path}/{subfolder['title']}"
            if config.max_folders is not None and len(config.visited) >= config.max_folders:
                result["children"].append(
                    {
                        "folder_path": child_path,
                        "skipped": "max_folder_limit",
                    }
                )
                record_workflow(
                    config,
                    WorkflowPhase.CLASSIFY_SCREEN,
                    current_folder_path=folder_path,
                    last_action="classify_subfolder_tile",
                    next_action="skip_child_over_max_folders",
                    skipped_candidates=[
                        SkippedCandidate(
                            folder_path=child_path,
                            reason="max_folder_limit",
                        )
                    ],
                )
                continue
            if depth + 1 > config.max_depth:
                result["children"].append(
                    {
                        "folder_path": child_path,
                        "skipped": "max_depth_limit",
                    }
                )
                record_workflow(
                    config,
                    WorkflowPhase.CLASSIFY_SCREEN,
                    current_folder_path=folder_path,
                    last_action="classify_subfolder_tile",
                    next_action="skip_child_over_max_depth",
                    skipped_candidates=[
                        SkippedCandidate(
                            folder_path=child_path,
                            reason="max_depth_limit",
                        )
                    ],
                )
                continue
            _, parent_summary = summarize_current(config, f"depth{depth}_child{len(processed_child_keys)}_parent")
            if parent_summary["folder_path"] != folder_path:
                raise SystemExit(
                    f"Refusing action: expected to be at {folder_path!r}, "
                    f"found {parent_summary['folder_path']!r}"
                )
            current_matches = [item for item in parent_summary["subfolders"] if subfolder_key(item) == key]
            if len(current_matches) != 1:
                raise SystemExit(f"Refusing action: expected one visible subfolder match for {key!r}, found {len(current_matches)}")
            current_subfolder = current_matches[0]
            if config.execute:
                log(f"[walk] entering subfolder {len(processed_child_keys)}: {current_subfolder['title']!r}")
                record_workflow(
                    config,
                    WorkflowPhase.ENTER_SUBFOLDER,
                    current_folder_path=folder_path,
                    last_action="classify_subfolder_tile",
                    next_action="tap_subfolder",
                    counts={"processed_child_count": len(processed_child_keys)},
                )
                tap_subfolder(current_subfolder)
                time.sleep(config.wait_seconds)
            try:
                child = walk_folder(config, depth + 1)
            except SystemExit as exc:
                if not config.execute:
                    raise
                message = str(exc)
                if "outside root_path" not in message and "Samsung Notes is not visible" not in message:
                    raise
                log(f"[walk] skipping {current_subfolder['title']!r}: non-folder screen after tap: {message}")
                press_notes_up_button()
                time.sleep(config.wait_seconds)
                _, recovered_summary = summarize_current(config, f"depth{depth}_child{len(processed_child_keys)}_recovered")
                if recovered_summary["folder_path"] != folder_path:
                    raise SystemExit(
                        f"Refusing action: recovery expected {folder_path!r}, "
                        f"found {recovered_summary['folder_path']!r}"
                    )
                result["children"].append(
                    {
                        "folder_path": child_path,
                        "skipped": "non_folder_screen_after_tap",
                        "error": message,
                    }
                )
                record_workflow(
                    config,
                    WorkflowPhase.RECOVER_FROM_NON_FOLDER,
                    current_folder_path=folder_path,
                    last_action="press_notes_up_button",
                    next_action="continue_sibling_walk",
                    skipped_candidates=[
                        SkippedCandidate(
                            folder_path=child_path,
                            reason="non_folder_screen_after_tap",
                        )
                    ],
                )
                continue
            result["children"].append(child)
            log(f"[walk] returning to {folder_path!r}")
            record_workflow(
                config,
                WorkflowPhase.RETURN_TO_PARENT,
                current_folder_path=folder_path,
                last_action="child_walk_complete",
                next_action="press_back",
            )
            press_back()
            time.sleep(config.wait_seconds)
            _, back_summary = summarize_current(config, f"depth{depth}_child{len(processed_child_keys)}_back")
            if back_summary["folder_path"] != folder_path:
                raise SystemExit(
                    f"Refusing action: back navigation expected {folder_path!r}, "
                    f"found {back_summary['folder_path']!r}"
                )

        if not config.execute or scroll_index >= config.max_subfolder_scrolls:
            break
        scroll_index += 1
        log(f"[walk] scrolling subfolder list page {scroll_index}/{config.max_subfolder_scrolls}")
        swipe_subfolders_down()
        time.sleep(config.wait_seconds)

    return result


def summarize_walk_result(result: dict[str, Any]) -> dict[str, Any]:
    totals = {
        "folders": 0,
        "dry_run_children": 0,
        "folders_with_notes": 0,
        "exported_files": 0,
        "pulled_files": 0,
        "skipped": 0,
    }
    max_depth = 0

    def visit(node: dict[str, Any]) -> None:
        nonlocal max_depth
        if node.get("skipped"):
            totals["skipped"] += 1
            return
        if node.get("dry_run"):
            totals["dry_run_children"] += 1
            return
        totals["folders"] += 1
        max_depth = max(max_depth, int(node.get("depth") or 0))
        export = node.get("export")
        if export:
            totals["folders_with_notes"] += 1
            export_summary = summarize_export_result(export)
            totals["exported_files"] += export_summary["exported_file_count"]
            handoff = export_summary.get("handoff") or {}
            totals["pulled_files"] += handoff.get("pulled_file_count") or 0
        for child in node.get("children") or []:
            visit(child)

    visit(result)
    return {
        "status": "ok",
        "root_path": result.get("folder_path"),
        "max_depth_seen": max_depth,
        "visible_note_cards_at_root": result.get("visible_note_cards"),
        "direct_note_card_page_count_at_root": len(result.get("direct_note_card_pages") or []),
        "visible_subfolder_count_at_root": len(result.get("visible_subfolders") or []),
        "child_count_at_root": len(result.get("children") or []),
        "totals": totals,
    }


def compact_walk_tree(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("skipped") or result.get("dry_run"):
        return dict(result)
    export = result.get("export")
    compact: dict[str, Any] = {
        "folder_path": result.get("folder_path"),
        "depth": result.get("depth"),
        "visible_note_cards": result.get("visible_note_cards"),
        "direct_note_card_pages": result.get("direct_note_card_pages") or [],
        "visible_subfolder_count": len(result.get("visible_subfolders") or []),
        "children": [],
    }
    if export:
        compact["export"] = summarize_export_result(export)
    for child in result.get("children") or []:
        compact["children"].append(compact_walk_tree(child))
    return compact


def build_run_summary(config: WalkConfig, result: dict[str, Any]) -> dict[str, Any]:
    summary = summarize_walk_result(result)
    base_workflow_state = config.workflow_state or initial_workflow_state(config.run_id, config.root_path)
    workflow_state = base_workflow_state.transition(
        WorkflowPhase.DONE,
        current_folder_path=result.get("folder_path"),
        last_action="walk_folder",
        next_action="review_run_summary",
        counts={
            "folders": summary["totals"]["folders"],
            "dry_run_children": summary["totals"]["dry_run_children"],
            "folders_with_notes": summary["totals"]["folders_with_notes"],
            "exported_files": summary["totals"]["exported_files"],
            "pulled_files": summary["totals"]["pulled_files"],
            "skipped": summary["totals"]["skipped"],
        },
        visited_folder=result.get("folder_path"),
    )
    return {
        "schema": "sn_archive_exporter.folder_walk_run_summary.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_id": config.run_id,
        "root_path": config.root_path,
        "execute": config.execute,
        "export_enabled": config.export_enabled,
        "export_format": config.export_format,
        "max_depth": config.max_depth,
        "max_subfolder_scrolls": config.max_subfolder_scrolls,
        "max_folders": config.max_folders,
        "mixed_folder_select_all": config.mixed_folder_select_all,
        "deselect_scroll_attempts": config.deselect_scroll_attempts,
        "deselect_max_taps": config.deselect_max_taps,
        "input_root": str(config.input_root),
        "archive_root": str(config.archive_root) if config.archive_root is not None else None,
        "observation_dir": str(config.observation_dir) if config.observation_dir is not None else None,
        "workflow": workflow_state.compact(),
        "workflow_recent_events": config.workflow_events[-20:],
        "summary": summary,
        "tree": compact_walk_tree(result),
    }


def default_run_summary_path(config: WalkConfig) -> Path:
    if config.run_summary_path is not None:
        return config.run_summary_path
    if config.archive_root is not None:
        return config.archive_root / config.run_id / "run_summary.json"
    return config.input_root / config.run_id / "run_summary.json"


def write_run_summary(config: WalkConfig, result: dict[str, Any]) -> Path:
    path = default_run_summary_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = build_run_summary(config, result)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guarded folder-by-folder Samsung Notes export walker.")
    parser.add_argument("--root-path", required=True, help="Exact root breadcrumb path where walking may start.")
    parser.add_argument("--run-id", required=True, help="Local run id for ignored input/output directories.")
    parser.add_argument("--input-root", type=Path, default=Path("input_exports"))
    parser.add_argument("--archive-root", type=Path, default=Path("output_archive"))
    parser.add_argument("--out-dir", type=Path, default=Path("ui_dumps"))
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--max-subfolder-scrolls", type=int, default=3)
    parser.add_argument("--max-folders", type=int, help="Stop after visiting this many folders, counting the root.")
    parser.add_argument("--wait-seconds", type=float, default=1.0)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--export-format", choices=sorted(EXPORT_FORMATS), default="sdocx")
    parser.add_argument("--skip-export", action="store_true", help="Traverse folders without exporting notes.")
    parser.add_argument(
        "--mixed-folder-select-all",
        action="store_true",
        help="Use guarded select-all plus selected-folder deselection for mixed folders.",
    )
    parser.add_argument("--deselect-scroll-attempts", type=int, default=4)
    parser.add_argument("--deselect-max-taps", type=int, default=80)
    parser.add_argument("--summary-only", action="store_true", help="Print compact counts instead of the full walked tree.")
    parser.add_argument("--quiet", action="store_true", help="Suppress step-by-step stderr progress logs.")
    parser.add_argument("--observe-screens", action="store_true", help="Save screenshot-first local observation logs for each guarded step.")
    parser.add_argument("--observation-dir", type=Path, default=Path("observations"))
    parser.add_argument("--observation-level", type=int, choices=[0, 1, 2], default=0)
    parser.add_argument("--observation-max-candidates", type=int, default=35)
    parser.add_argument("--run-summary-path", type=Path, help="Write the compact run summary JSON here.")
    parser.add_argument("--no-run-summary", action="store_true", help="Do not write a local run summary JSON.")
    parser.add_argument("--allow-existing-output", action="store_true", help="Allow per-folder pull/archive directories to already exist.")
    args = parser.parse_args(argv)

    config = WalkConfig(
        root_path=args.root_path,
        run_id=args.run_id,
        input_root=args.input_root,
        archive_root=args.archive_root,
        out_dir=args.out_dir,
        execute=args.execute,
        max_depth=args.max_depth,
        max_subfolder_scrolls=args.max_subfolder_scrolls,
        max_folders=args.max_folders,
        wait_seconds=args.wait_seconds,
        export_enabled=not args.skip_export,
        export_format=args.export_format,
        mixed_folder_select_all=args.mixed_folder_select_all,
        deselect_scroll_attempts=args.deselect_scroll_attempts,
        deselect_max_taps=args.deselect_max_taps,
        observation_dir=args.observation_dir if args.observe_screens else None,
        observation_level=args.observation_level,
        observation_max_candidates=args.observation_max_candidates,
        run_summary_path=args.run_summary_path,
        allow_existing_output=args.allow_existing_output,
    )
    set_quiet(args.quiet)
    result = walk_folder(config)
    run_summary_path = None
    if not args.no_run_summary:
        run_summary_path = write_run_summary(config, result)
    if args.summary_only:
        result = summarize_walk_result(result)
        if run_summary_path is not None:
            result["run_summary_path"] = str(run_summary_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
