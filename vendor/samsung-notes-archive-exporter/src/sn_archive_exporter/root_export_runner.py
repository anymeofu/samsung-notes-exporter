from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .archive_validator import validate_archive
from .archive_merger import merge_folder_archive_outputs
from . import ui_guard
from .guarded_export_driver import (
    EXPORT_FORMATS,
    DriverConfig,
    adb,
    dump_ui,
    run_guarded_export,
    set_quiet,
    summarize_export_result,
)
from .ui_guard import summarize
from .visible_batch_runner import VisibleBatchRunConfig, run_visible_batches


SMALL_LEAF_NOTE_LIMIT = 99
NAVIGATION_MENU_DESC = "내비게이션 메뉴"
FOLDER_TREE_ROW_ID = f"{ui_guard.NOTES_PACKAGE}:id/selected_holder"
FOLDER_TREE_TITLE_ID = f"{ui_guard.NOTES_PACKAGE}:id/title"


@dataclass(frozen=True)
class RootRunnerConfig:
    run_id: str
    state_path: Path
    input_root: Path
    archive_root: Path
    out_dir: Path
    execute: bool
    wait_seconds: float
    max_visible_batches: int
    max_empty_scrolls: int
    max_subfolder_scrolls: int = 3
    export_format: str = "sdocx"
    max_count: int | None = None
    max_depth: int = 5
    max_folders: int | None = None
    skip_current_folder_export: bool = False
    allow_existing_output: bool = False
    quiet: bool = False


def exact_text(node: Any) -> str:
    return str(node.attrib.get("text") or node.attrib.get("content-desc") or "").strip()


def find_unique_node_target(root: Any, *, text: str | None = None, content_desc: str | None = None) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for node in root.iter("node"):
        if text is not None and exact_text(node) != text:
            continue
        if content_desc is not None and str(node.attrib.get("content-desc") or "").strip() != content_desc:
            continue
        bounds = ui_guard.parse_bounds(str(node.attrib.get("bounds") or ""))
        if bounds is None:
            continue
        matches.append({"bounds": node.attrib.get("bounds"), "center": list(bounds.center)})
    if len(matches) != 1:
        label = text if text is not None else content_desc
        raise SystemExit(f"Refusing action: expected one navigation target {label!r}, found {len(matches)}")
    return matches[0]


def find_unique_folder_tree_row(root: Any, title: str) -> dict[str, Any] | None:
    matches: list[dict[str, Any]] = []
    for row in root.iter("node"):
        if row.attrib.get("resource-id") != FOLDER_TREE_ROW_ID:
            continue
        titles = [
            exact_text(node)
            for node in row.iter("node")
            if node.attrib.get("resource-id") == FOLDER_TREE_TITLE_ID and exact_text(node)
        ]
        if title not in titles:
            continue
        bounds = ui_guard.parse_bounds(str(row.attrib.get("bounds") or ""))
        if bounds is None or row.attrib.get("clickable") != "true":
            continue
        matches.append({"title": title, "bounds": row.attrib.get("bounds"), "center": list(bounds.center)})
    if len(matches) > 1:
        raise SystemExit(f"Refusing action: folder tree contains ambiguous title {title!r}")
    return matches[0] if matches else None


def folder_tree_signature(root: Any) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    for row in root.iter("node"):
        if row.attrib.get("resource-id") != FOLDER_TREE_ROW_ID:
            continue
        title = next(
            (
                exact_text(node)
                for node in row.iter("node")
                if node.attrib.get("resource-id") == FOLDER_TREE_TITLE_ID and exact_text(node)
            ),
            "",
        )
        if title:
            rows.append((title, str(row.attrib.get("bounds") or "")))
    return tuple(rows)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_slug(value: str) -> str:
    chars = []
    for char in value:
        if char.isalnum() or char in "._-":
            chars.append(char)
        else:
            chars.append("_")
    return "_".join(part for part in "".join(chars).split("_") if part) or "folder"


def empty_state(run_id: str) -> dict[str, Any]:
    return {
        "schema": "sn_archive_exporter.root_export_runner.v1",
        "run_id": run_id,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "folders": {},
        "events": [],
    }


def load_runner_state(path: Path, run_id: str) -> dict[str, Any]:
    if not path.exists():
        return empty_state(run_id)
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("run_id") != run_id:
        raise SystemExit(f"Refusing action: state run_id={state.get('run_id')!r} does not match {run_id!r}")
    state.setdefault("folders", {})
    state.setdefault("events", [])
    normalize_transient_states(state)
    return state


def normalize_transient_states(state: dict[str, Any]) -> None:
    for record in (state.get("folders") or {}).values():
        if record.get("status") != "entering":
            continue
        detail = dict(record.get("detail") or {})
        detail["recovered_from_transient_status"] = "entering"
        record["status"] = "planned"
        record["detail"] = detail


def save_runner_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def bind_export_format(state: dict[str, Any], export_format: str) -> None:
    stored = state.get("export_format")
    if stored is None and state.get("folders"):
        stored = "sdocx"
    if stored not in {None, export_format}:
        raise SystemExit(f"Refusing action: state export_format={stored!r} does not match {export_format!r}")
    state["export_format"] = export_format


def load_seed_entries(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        if isinstance(data.get("folders"), list):
            data = data["folders"]
        elif isinstance(data.get("completed_folders"), list):
            data = data["completed_folders"]
    if not isinstance(data, list):
        raise ValueError("seed JSON must be a list or contain a folders/completed_folders list")
    entries: list[dict[str, Any]] = []
    for index, item in enumerate(data, start=1):
        if isinstance(item, str):
            folder_path = item
            archive_output = None
        elif isinstance(item, dict):
            folder_path = item.get("folder_path") or item.get("path")
            archive_output = item.get("archive_output")
            status = item.get("status")
            strategy = item.get("strategy")
        else:
            raise ValueError(f"seed entry {index} must be a string or object")
        if not isinstance(item, dict):
            status = None
            strategy = None
        folder_path = str(folder_path or "").strip()
        if not folder_path:
            raise ValueError(f"seed entry {index} is missing folder_path")
        entry = {"folder_path": folder_path}
        if archive_output:
            entry["archive_output"] = str(archive_output)
        if status:
            entry["status"] = str(status)
        if strategy:
            entry["strategy"] = str(strategy)
        entries.append(entry)
    return entries


def seed_completed_folders(state: dict[str, Any], entries: list[dict[str, Any]], *, source: str) -> dict[str, Any]:
    seeded: list[str] = []
    for entry in entries:
        folder_path = str(entry["folder_path"]).strip()
        detail: dict[str, Any] = {"seed_source": source}
        if entry.get("archive_output"):
            detail["archive_output"] = str(entry["archive_output"])
        status = str(entry.get("status") or "completed")
        strategy = str(entry.get("strategy") or ("mixed_tree" if status == "direct_notes_completed" else "seeded_completed"))
        record_folder(
            state,
            folder_path,
            status=status,
            strategy=strategy,
            detail=detail,
        )
        seeded.append(folder_path)
    return {"seeded_count": len(seeded), "seeded_folder_paths": seeded}


def collect_archive_outputs_from_state(state: dict[str, Any]) -> list[Path]:
    outputs: list[Path] = []
    seen: set[Path] = set()
    for folder in (state.get("folders") or {}).values():
        if folder.get("status") not in {"completed", "direct_notes_completed"}:
            continue
        detail = folder.get("detail") or {}
        archive_output = detail.get("archive_output")
        if not archive_output:
            export = detail.get("export") or {}
            handoff = export.get("handoff") or {}
            archive_output = handoff.get("archive_output")
        if not archive_output:
            continue
        path = Path(str(archive_output))
        if path in seen:
            continue
        seen.add(path)
        outputs.append(path)
    return outputs


def collect_folder_paths_from_state(state: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for folder_path, folder in (state.get("folders") or {}).items():
        status = folder.get("status")
        if status in {
            "planned",
            "entering",
            "ignored_bad_path",
            "needs_review",
            "excluded_from_run",
            "deferred_current_export",
        }:
            continue
        if folder_path in seen:
            continue
        seen.add(folder_path)
        paths.append(folder_path)
    return paths


def classify_folder(summary: dict[str, Any]) -> dict[str, Any]:
    visible_counts = summary.get("visible_counts") or {}
    note_count = visible_counts.get("note_count")
    folder_count = visible_counts.get("folder_count")
    visible_subfolder_count = int(summary.get("subfolder_count") or 0)
    visible_note_card_count = int(summary.get("note_card_count") or 0)
    has_subfolders = visible_subfolder_count > 0 or (folder_count or 0) > 0
    has_notes = visible_note_card_count > 0 or (note_count or 0) > 0

    if has_subfolders and has_notes:
        strategy = "mixed_tree"
    elif has_subfolders:
        strategy = "nested_tree"
    elif note_count is not None and note_count > SMALL_LEAF_NOTE_LIMIT:
        strategy = "large_leaf_visible_batches"
    elif has_notes:
        strategy = "small_leaf_all_select"
    else:
        strategy = "empty_or_unknown"

    return {
        "folder_path": normalized_folder_path(summary),
        "strategy": strategy,
        "note_count": note_count,
        "folder_count": folder_count,
        "visible_note_card_count": visible_note_card_count,
        "visible_subfolder_count": visible_subfolder_count,
        "has_subfolders": has_subfolders,
        "has_notes": has_notes,
    }


def normalized_folder_path(summary: dict[str, Any]) -> str:
    folder_path = str(summary.get("folder_path") or "").strip()
    if folder_path:
        return folder_path
    if summary.get("is_samsung_notes_visible") and (summary.get("subfolder_count") or 0) > 0:
        return "폴더"
    return folder_path


def record_folder(
    state: dict[str, Any],
    folder_path: str,
    *,
    status: str,
    strategy: str,
    detail: dict[str, Any] | None = None,
) -> None:
    folders = state.setdefault("folders", {})
    previous = folders.get(folder_path, {})
    merged_detail = {
        **(previous.get("detail") or {}),
        **(detail or {}),
    }
    folders[folder_path] = {
        **previous,
        "folder_path": folder_path,
        "status": status,
        "strategy": strategy,
        "updated_at": utc_now(),
        "detail": merged_detail,
    }
    state.setdefault("events", []).append(
        {
            "at": utc_now(),
            "folder_path": folder_path,
            "status": status,
            "strategy": strategy,
        }
    )


def is_partial_mixed_tree_record(record: dict[str, Any] | None) -> bool:
    if not record:
        return False
    if record.get("strategy") != "mixed_tree":
        return False
    detail = record.get("detail") or {}
    classification = detail.get("classification") or {}
    return bool(classification.get("has_subfolders"))


def direct_notes_already_exported(state: dict[str, Any], folder_path: str) -> bool:
    record = (state.get("folders") or {}).get(folder_path) or {}
    detail = record.get("detail") or {}
    return bool(detail.get("archive_output") or (detail.get("export") or {}).get("handoff", {}).get("archive_output"))


def folder_has_accounted_status(state: dict[str, Any], folder_path: str) -> bool:
    status = ((state.get("folders") or {}).get(folder_path) or {}).get("status")
    return status in {"completed", "direct_notes_completed", "empty_or_unknown", "excluded_from_run", "traversed"}


def is_completed(state: dict[str, Any], folder_path: str) -> bool:
    record = (state.get("folders") or {}).get(folder_path)
    if not record:
        return False
    if is_partial_mixed_tree_record(record):
        return False
    return record.get("status") in {"completed", "excluded_from_run", "traversed"}


def child_path(parent_path: str, title: str) -> str:
    if not parent_path or parent_path == "폴더":
        return title
    return f"{parent_path.rstrip('/')}/{title}"


def is_safe_subfolder_title(title: str) -> bool:
    clean = title.strip()
    return bool(clean) and "/" not in clean


def visible_child_titles(summary: dict[str, Any]) -> list[str]:
    titles: list[str] = []
    for subfolder in summary.get("subfolders") or []:
        title = str(subfolder.get("title") or "").strip()
        if not is_safe_subfolder_title(title):
            continue
        titles.append(title)
    return titles


def find_subfolder_by_title(summary: dict[str, Any], title: str) -> dict[str, Any] | None:
    for subfolder in summary.get("subfolders") or []:
        if str(subfolder.get("title") or "").strip() == title:
            return subfolder
    return None


def current_summary(config: RootRunnerConfig, label: str, allowed_path: str | None = None) -> dict[str, Any]:
    xml_path = dump_ui(
        DriverConfig(
            allowed_path=allowed_path or "*",
            destination="Documents",
            out_dir=config.out_dir,
            label=f"{config.run_id}_{label}",
            execute=False,
            select_count=1,
            select_all=False,
            wait_seconds=config.wait_seconds,
            pull_to=None,
            mapping_path=None,
            archive_output=None,
            allow_existing_output=config.allow_existing_output,
            export_format=config.export_format,
            allow_partial_export=config.export_format == "txt",
        ),
        "screen",
    )
    root_allowed = [allowed_path] if allowed_path else []
    summary = summarize(xml_path, root_allowed)
    if not summary["is_samsung_notes_visible"]:
        raise SystemExit(f"Refusing action: Samsung Notes is not visible. Packages: {summary['packages']}")
    return summary


def dump_navigation_xml(config: RootRunnerConfig, label: str) -> Path:
    return dump_ui(
        DriverConfig(
            allowed_path="*",
            destination="Documents",
            out_dir=config.out_dir,
            label=f"{config.run_id}_{label}",
            execute=False,
            select_count=1,
            select_all=False,
            wait_seconds=config.wait_seconds,
            pull_to=None,
            mapping_path=None,
            archive_output=None,
            allow_existing_output=config.allow_existing_output,
            export_format=config.export_format,
        ),
        "screen",
    )


def navigate_to_top_level_folder(
    config: RootRunnerConfig,
    target: str,
    *,
    max_scrolls: int = 12,
    summary_provider: Callable[[RootRunnerConfig, str, str | None], dict[str, Any]] = current_summary,
) -> dict[str, Any]:
    target = target.strip()
    if not is_safe_subfolder_title(target):
        raise SystemExit("Refusing action: --navigate-to-folder supports one safe top-level folder title")
    if max_scrolls < 1:
        raise SystemExit("Refusing action: --max-navigation-scrolls must be at least 1")

    before = summary_provider(config, "navigate_before", None)
    before_path = normalized_folder_path(before)
    if before_path == target:
        return {"status": "already_at_target", "from_path": before_path, "folder_path": target}
    if not config.execute:
        return {"status": "planned", "from_path": before_path, "folder_path": target}

    menu_xml = dump_navigation_xml(config, "navigate_menu")
    menu_target = find_unique_node_target(ui_guard.load_xml(menu_xml), content_desc=NAVIGATION_MENU_DESC)
    ui_guard.tap(*menu_target["center"])
    time.sleep(config.wait_seconds)

    phase_specs = (
        ("toward_top", (500, 600, 500, 1850, 500)),
        ("toward_bottom", (500, 1850, 500, 600, 500)),
    )
    observation_count = 0
    for phase, swipe in phase_specs:
        last_signature: tuple[tuple[str, str], ...] | None = None
        for attempt in range(max_scrolls + 1):
            popup_xml = dump_navigation_xml(config, f"navigate_{phase}_{attempt:02d}")
            root = ui_guard.load_xml(popup_xml)
            row = find_unique_folder_tree_row(root, target)
            observation_count += 1
            if row is not None:
                ui_guard.tap(*row["center"])
                time.sleep(config.wait_seconds)
                after = summary_provider(config, "navigate_after", target)
                after_path = normalized_folder_path(after)
                if after_path != target:
                    raise SystemExit(f"Refusing action: navigation expected {target!r}, found {after_path!r}")
                return {
                    "status": "ok",
                    "from_path": before_path,
                    "folder_path": target,
                    "phase": phase,
                    "observation_count": observation_count,
                }
            signature = folder_tree_signature(root)
            if signature and signature == last_signature:
                break
            last_signature = signature
            if attempt < max_scrolls:
                adb(["shell", "input", "swipe", *(str(value) for value in swipe)], capture=True)
                time.sleep(config.wait_seconds)

    raise SystemExit(f"Refusing action: top-level folder {target!r} was not found in the visible folder tree")


def validate_if_present(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return validate_archive(path)


def run_small_leaf(config: RootRunnerConfig, folder_path: str) -> dict[str, Any]:
    archive_output = config.archive_root / f"{safe_slug(folder_path)}_{config.run_id}"
    if not config.execute:
        return {
            "dry_run": True,
            "planned": {
                "action": "guarded_all_select_export",
                "folder_path": folder_path,
                "export_format": config.export_format,
                "archive_output": str(archive_output),
            },
        }
    result = run_guarded_export(
        DriverConfig(
            allowed_path=folder_path,
            destination="Documents",
            out_dir=config.out_dir,
            label=f"{config.run_id}_{safe_slug(folder_path)}",
            execute=config.execute,
            select_count=1,
            select_all=True,
            wait_seconds=config.wait_seconds,
            pull_to=config.input_root / f"{safe_slug(folder_path)}_{config.run_id}" if config.execute else None,
            mapping_path=None,
            archive_output=archive_output if config.execute else None,
            allow_existing_output=config.allow_existing_output,
            export_format=config.export_format,
            allow_partial_export=config.export_format == "txt",
        )
    )
    summary = summarize_export_result(result)
    validation = validate_if_present(archive_output if config.execute else None)
    return {
        "export": summary,
        "archive_output": str(archive_output) if config.execute else None,
        "validation": validation,
    }


def run_mixed_folder_direct_notes(config: RootRunnerConfig, folder_path: str) -> dict[str, Any]:
    archive_output = config.archive_root / f"{safe_slug(folder_path)}_{config.run_id}"
    if not config.execute:
        return {
            "dry_run": True,
            "planned": {
                "action": "guarded_all_select_then_deselect_subfolders",
                "folder_path": folder_path,
                "export_format": config.export_format,
                "archive_output": str(archive_output),
            },
        }
    result = run_guarded_export(
        DriverConfig(
            allowed_path=folder_path,
            destination="Documents",
            out_dir=config.out_dir,
            label=f"{config.run_id}_{safe_slug(folder_path)}_mixed",
            execute=True,
            select_count=1,
            select_all=True,
            wait_seconds=config.wait_seconds,
            pull_to=config.input_root / f"{safe_slug(folder_path)}_{config.run_id}",
            mapping_path=None,
            archive_output=archive_output,
            allow_existing_output=config.allow_existing_output,
            deselect_visible_subfolders_after_select_all=True,
            export_format=config.export_format,
            allow_partial_export=config.export_format == "txt",
        )
    )
    summary = summarize_export_result(result)
    validation = validate_if_present(archive_output)
    return {
        "export": summary,
        "archive_output": str(archive_output),
        "validation": validation,
    }


def run_large_leaf(config: RootRunnerConfig, folder_path: str) -> dict[str, Any]:
    state_path = config.archive_root / config.run_id / f"{safe_slug(folder_path)}.visible_state.json"
    result = run_visible_batches(
        VisibleBatchRunConfig(
            folder_path=folder_path,
            run_id=f"{config.run_id}_{safe_slug(folder_path)}",
            state_path=state_path,
            input_root=config.input_root,
            archive_root=config.archive_root,
            out_dir=config.out_dir,
            execute=config.execute,
            max_batches=config.max_visible_batches,
            max_empty_scrolls=config.max_empty_scrolls,
            wait_seconds=config.wait_seconds,
            max_count=config.max_count,
            allow_existing_output=config.allow_existing_output,
            nudge_sequence=("large-forward", "medium-forward", "small-forward"),
            max_repeated_screens=2,
            export_format=config.export_format,
            allow_partial_export=config.export_format == "txt",
        )
    )
    return {
        "visible_batches": {
            "status": result.get("status"),
            "run_id": result.get("run_id"),
            "export_format": result.get("export_format"),
            "seen_fingerprint_count": result.get("seen_fingerprint_count"),
            "batch_count": result.get("batch_count"),
            "new_batch_count": len(result.get("new_batches") or []),
            "observation_count": len(result.get("observations") or []),
        },
        "state_path": str(state_path),
    }


def run_current_folder(
    config: RootRunnerConfig,
    *,
    state: dict[str, Any] | None = None,
    summary_provider: Callable[[RootRunnerConfig, str, str | None], dict[str, Any]] = current_summary,
) -> dict[str, Any]:
    state = state if state is not None else load_runner_state(config.state_path, config.run_id)
    set_quiet(config.quiet)
    summary = summary_provider(config, "classify_current", None)
    classification = classify_folder(summary)
    folder_path = classification.get("folder_path")
    if not folder_path:
        raise SystemExit("Refusing action: current Samsung Notes folder path is empty")
    if is_completed(state, folder_path):
        return {"status": "skipped_completed", "folder_path": folder_path, "classification": classification}

    existing_record = (state.get("folders") or {}).get(folder_path) or {}
    existing_strategy = existing_record.get("strategy")
    existing_detail = existing_record.get("detail") or {}
    has_visible_batch_resume = bool(existing_detail.get("state_path") and existing_detail.get("visible_batches"))
    if (
        existing_record.get("status") == "in_progress" and existing_strategy == "large_leaf_visible_batches"
    ) or has_visible_batch_resume:
        strategy = "large_leaf_visible_batches"
        classification = {
            **classification,
            "strategy": strategy,
            "strategy_source": "resumed_visible_batch_state",
        }
    else:
        strategy = classification["strategy"]
    record_folder(state, folder_path, status="planned", strategy=strategy, detail={"classification": classification})
    save_runner_state(config.state_path, state)

    if strategy == "small_leaf_all_select":
        detail = run_small_leaf(config, folder_path)
        export = detail.get("export") or {}
        validation = detail.get("validation") or {}
        if not config.execute:
            status = "planned"
        else:
            completed = export.get("status") == "ok" and validation.get("status") == "ok"
            status = "completed" if completed else "needs_review"
    elif strategy == "large_leaf_visible_batches":
        detail = run_large_leaf(config, folder_path)
        completed = not config.execute
        status = "in_progress" if config.execute else "planned"
    elif strategy == "mixed_tree":
        note_count = classification.get("note_count")
        if note_count is not None and note_count > SMALL_LEAF_NOTE_LIMIT:
            detail = {
                "reason": "large mixed folder direct-note export needs partitioned mixed strategy",
                "subfolders": [item.get("title") for item in summary.get("subfolders") or []],
            }
            status = "needs_review"
        else:
            detail = run_mixed_folder_direct_notes(config, folder_path)
            export = detail.get("export") or {}
            validation = detail.get("validation") or {}
            if not config.execute:
                status = "planned"
            else:
                completed = export.get("status") == "ok" and validation.get("status") == "ok"
                if completed and classification.get("has_subfolders"):
                    status = "direct_notes_completed"
                else:
                    status = "completed" if completed else "needs_review"
    elif strategy == "nested_tree":
        detail = {
            "reason": "tree folder requires recursive root traversal",
            "subfolders": [item.get("title") for item in summary.get("subfolders") or []],
        }
        status = "needs_recursive_runner"
    else:
        detail = {"reason": "no exportable notes detected in current visible folder"}
        status = "empty_or_unknown"

    record_folder(state, folder_path, status=status, strategy=strategy, detail={**detail, "classification": classification})
    save_runner_state(config.state_path, state)
    return {
        "status": status,
        "folder_path": folder_path,
        "strategy": strategy,
        "export_format": config.export_format,
        "classification": classification,
        "detail": detail,
        "state_path": str(config.state_path),
    }


def tap_subfolder(subfolder: dict[str, Any]) -> None:
    from . import ui_guard

    bounds = ui_guard.parse_bounds(str(subfolder.get("bounds") or ""))
    if bounds is None:
        center = subfolder.get("center")
        if not isinstance(center, list) or len(center) != 2:
            raise SystemExit(f"Refusing action: subfolder has no tappable target: {subfolder}")
        ui_guard.tap(int(center[0]), int(center[1]))
        return
    x = bounds.left + max(24, (bounds.right - bounds.left) // 4)
    y = (bounds.top + bounds.bottom) // 2
    ui_guard.tap(x, y)


def tap_subfolder_expand(target: dict[str, Any]) -> None:
    if target.get("ambiguous"):
        raise SystemExit(f"Refusing action: ambiguous subfolder expand target: {target}")
    if not target.get("enabled"):
        raise SystemExit(f"Refusing action: subfolder expand target disabled: {target}")
    center = target.get("center")
    if not isinstance(center, list) or len(center) != 2:
        raise SystemExit(f"Refusing action: subfolder expand has no tappable center: {target}")
    from . import ui_guard

    ui_guard.tap(int(center[0]), int(center[1]))


def back_to_parent() -> None:
    adb(["shell", "input", "keyevent", "KEYCODE_BACK"], capture=True)


def expand_subfolders_if_available(
    config: RootRunnerConfig,
    summary: dict[str, Any],
    *,
    depth: int,
    summary_provider: Callable[[RootRunnerConfig, str, str | None], dict[str, Any]] = current_summary,
) -> dict[str, Any]:
    expand = summary.get("subfolder_expand") or {}
    if not expand.get("available") or not expand.get("is_show_all"):
        return summary
    folder_path = summary.get("folder_path")
    if not config.execute:
        return {
            **summary,
            "hidden_subfolders_not_expanded": True,
        }
    tap_subfolder_expand(expand)
    time.sleep(config.wait_seconds)
    expanded = summary_provider(config, f"recursive_depth_{depth}_expanded", folder_path)
    if expanded.get("folder_path") != folder_path:
        raise SystemExit(f"Refusing action: expected {folder_path!r} after expand, found {expanded.get('folder_path')!r}")
    return expanded


def run_visible_subfolders(
    config: RootRunnerConfig,
    *,
    state: dict[str, Any] | None = None,
    summary_provider: Callable[[RootRunnerConfig, str, str | None], dict[str, Any]] = current_summary,
    current_folder_runner: Callable[[RootRunnerConfig, dict[str, Any] | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    state = state if state is not None else load_runner_state(config.state_path, config.run_id)
    set_quiet(config.quiet)
    parent_summary = summary_provider(config, "visible_subfolders_parent", None)
    parent_summary = expand_subfolders_if_available(config, parent_summary, depth=0, summary_provider=summary_provider)
    parent_path = normalized_folder_path(parent_summary)
    subfolders = list(parent_summary.get("subfolders") or [])
    results: list[dict[str, Any]] = []
    current_folder_runner = current_folder_runner or (lambda runner_config, runner_state: run_current_folder(runner_config, state=runner_state))

    for subfolder in subfolders:
        title = str(subfolder.get("title") or "").strip()
        if not title:
            continue
        expected_child_path = child_path(parent_path, title)
        if is_completed(state, expected_child_path):
            results.append({"folder_path": expected_child_path, "status": "skipped_completed"})
            continue
        if not config.execute:
            record_folder(
                state,
                expected_child_path,
                status="planned",
                strategy="enter_and_classify",
                detail={"parent_path": parent_path, "title": title},
            )
            results.append({"folder_path": expected_child_path, "status": "planned"})
            continue

        record_folder(
            state,
            expected_child_path,
            status="entering",
            strategy="enter_and_classify",
            detail={"parent_path": parent_path, "title": title},
        )
        save_runner_state(config.state_path, state)
        tap_subfolder(subfolder)
        result = current_folder_runner(config, state)
        results.append(result)
        back_to_parent()

    save_runner_state(config.state_path, state)
    return {
        "status": "ok",
        "mode": "visible_subfolders",
        "parent_path": parent_path,
        "subfolder_count": len(subfolders),
        "processed_count": len(results),
        "results": results,
        "state_path": str(config.state_path),
    }


def max_folder_limit_reached(state: dict[str, Any], config: RootRunnerConfig) -> bool:
    if config.max_folders is None:
        return False
    visited = sum(
        1
        for item in (state.get("folders") or {}).values()
        if item.get("status") not in {"planned", "entering", "skipped_completed", "excluded_from_run"}
        and item.get("strategy") != "seeded_completed"
    )
    return visited >= config.max_folders


def run_recursive_current_folder(
    config: RootRunnerConfig,
    *,
    state: dict[str, Any] | None = None,
    depth: int = 0,
    expected_path: str | None = None,
    summary_provider: Callable[[RootRunnerConfig, str, str | None], dict[str, Any]] = current_summary,
) -> dict[str, Any]:
    state = state if state is not None else load_runner_state(config.state_path, config.run_id)
    if depth > config.max_depth:
        summary = summary_provider(config, f"max_depth_{depth}", None)
        folder_path = normalized_folder_path(summary) or "<unknown>"
        classification = classify_folder(summary)
        record_folder(
            state,
            folder_path,
            status="skipped_max_depth",
            strategy=classification["strategy"],
            detail={"depth": depth, "max_depth": config.max_depth, "classification": classification},
        )
        save_runner_state(config.state_path, state)
        return {"status": "skipped_max_depth", "folder_path": folder_path, "depth": depth}
    if max_folder_limit_reached(state, config):
        return {"status": "stopped_max_folders", "depth": depth, "state_path": str(config.state_path)}

    summary = summary_provider(config, f"recursive_depth_{depth}", None)
    summary = expand_subfolders_if_available(config, summary, depth=depth, summary_provider=summary_provider)
    classification = classify_folder(summary)
    folder_path = classification.get("folder_path")
    if not folder_path:
        raise SystemExit("Refusing action: current Samsung Notes folder path is empty")
    if expected_path and folder_path != expected_path:
        raise SystemExit(f"Refusing action: expected child folder {expected_path!r}, found {folder_path!r}")
    if is_completed(state, folder_path):
        return {"status": "skipped_completed", "folder_path": folder_path, "depth": depth}

    strategy = classification["strategy"]
    children: list[dict[str, Any]] = []
    direct_result: dict[str, Any] | None = None
    if depth == 0 and config.skip_current_folder_export and strategy in {"small_leaf_all_select", "large_leaf_visible_batches", "mixed_tree"}:
        record_folder(
            state,
            folder_path,
            status="deferred_current_export",
            strategy=strategy,
            detail={"depth": depth, "classification": classification},
        )
        save_runner_state(config.state_path, state)
    elif strategy == "mixed_tree" and direct_notes_already_exported(state, folder_path):
        record_folder(
            state,
            folder_path,
            status="direct_notes_completed",
            strategy=strategy,
            detail={
                **((state.get("folders") or {}).get(folder_path, {}).get("detail") or {}),
                "depth": depth,
                "classification": classification,
                "skipped_direct_export": "already_exported",
            },
        )
        save_runner_state(config.state_path, state)
    elif strategy in {"small_leaf_all_select", "large_leaf_visible_batches", "mixed_tree", "empty_or_unknown"}:
        direct_result = run_current_folder(config, state=state, summary_provider=lambda _config, _label, _allowed: summary)
        if strategy == "mixed_tree":
            refreshed = summary_provider(config, f"recursive_depth_{depth}_after_direct_export", None)
            refreshed = expand_subfolders_if_available(config, refreshed, depth=depth, summary_provider=summary_provider)
            refreshed_path = normalized_folder_path(refreshed)
            if refreshed_path != folder_path:
                raise SystemExit(
                    f"Refusing action: expected to remain in {folder_path!r} after direct export, found {refreshed_path!r}"
                )
            summary = refreshed
    elif strategy == "nested_tree":
        record_folder(
            state,
            folder_path,
            status="traversing",
            strategy=strategy,
            detail={"depth": depth, "classification": classification},
        )
        save_runner_state(config.state_path, state)

    if strategy in {"mixed_tree", "nested_tree"}:
        if depth >= config.max_depth:
            record_folder(
                state,
                folder_path,
                status="skipped_children_max_depth",
                strategy=strategy,
                detail={"depth": depth, "max_depth": config.max_depth, "classification": classification},
            )
            save_runner_state(config.state_path, state)
        else:
            child_titles = visible_child_titles(summary)
            for title in child_titles:
                expected_child_path = child_path(folder_path, title)
                if is_completed(state, expected_child_path):
                    children.append({"status": "skipped_completed", "folder_path": expected_child_path})
                    continue
                if max_folder_limit_reached(state, config):
                    children.append({"status": "stopped_max_folders", "folder_path": expected_child_path})
                    break
                if not config.execute:
                    record_folder(
                        state,
                        expected_child_path,
                        status="planned",
                        strategy="recursive_child",
                        detail={"parent_path": folder_path, "title": title, "depth": depth + 1},
                    )
                    children.append({"status": "planned", "folder_path": expected_child_path, "depth": depth + 1})
                    continue
                record_folder(
                    state,
                    expected_child_path,
                    status="entering",
                    strategy="recursive_child",
                    detail={"parent_path": folder_path, "title": title, "depth": depth + 1},
                )
                save_runner_state(config.state_path, state)
                if config.execute:
                    fresh_summary = summary_provider(config, f"recursive_depth_{depth}_before_child_{safe_slug(title)}", None)
                    fresh_summary = expand_subfolders_if_available(
                        config,
                        fresh_summary,
                        depth=depth,
                        summary_provider=summary_provider,
                    )
                    fresh_path = normalized_folder_path(fresh_summary)
                    if fresh_path != folder_path:
                        raise SystemExit(
                            f"Refusing action: expected parent folder {folder_path!r} before child {title!r}, found {fresh_path!r}"
                        )
                    subfolder = find_subfolder_by_title(fresh_summary, title)
                    if subfolder is None:
                        record_folder(
                            state,
                            expected_child_path,
                            status="skipped_missing_child_after_refresh",
                            strategy="recursive_child",
                            detail={"parent_path": folder_path, "title": title, "depth": depth + 1},
                        )
                        save_runner_state(config.state_path, state)
                        children.append({"status": "skipped_missing_child_after_refresh", "folder_path": expected_child_path})
                        continue
                tap_subfolder(subfolder)
                time.sleep(config.wait_seconds)
                child_result = run_recursive_current_folder(
                    config,
                    state=state,
                    depth=depth + 1,
                    expected_path=expected_child_path,
                    summary_provider=summary_provider,
                )
                children.append(child_result)
                back_to_parent()

    final_status = direct_result["status"] if direct_result else "traversed"
    if strategy == "nested_tree" and children and all(child.get("status") in {"completed", "skipped_completed", "traversed"} for child in children):
        final_status = "traversed"
        if config.execute:
            record_folder(
                state,
                folder_path,
                status="traversed",
                strategy=strategy,
                detail={"depth": depth, "classification": classification, "child_count": len(children)},
            )
    save_runner_state(config.state_path, state)
    return {
        "status": final_status,
        "folder_path": folder_path,
        "strategy": strategy,
        "depth": depth,
        "direct_result": direct_result,
        "children": children,
        "state_path": str(config.state_path),
    }


def finalize_run_archive(
    config: RootRunnerConfig,
    *,
    state: dict[str, Any] | None = None,
    output: Path | None = None,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    state = state if state is not None else load_runner_state(config.state_path, config.run_id)
    archive_outputs = collect_archive_outputs_from_state(state)
    folder_paths = collect_folder_paths_from_state(state)
    output_dir = output or (config.archive_root / f"{config.run_id}_merged")
    merge_dry_run = (not config.execute) if dry_run is None else dry_run
    if not archive_outputs:
        return {
            "status": "no_archives",
            "archive_output_count": 0,
            "folder_path_count": len(folder_paths),
            "output": str(output_dir),
        }
    merge_result = merge_folder_archive_outputs(
        archive_outputs,
        output_dir,
        dry_run=merge_dry_run,
        allow_existing_output=config.allow_existing_output,
        folder_paths=folder_paths,
    )
    validation = None if merge_dry_run else validate_archive(output_dir)
    return {
        "status": "ok" if merge_dry_run or (validation or {}).get("status") == "ok" else "needs_review",
        "dry_run": merge_dry_run,
        "output": str(output_dir),
        "archive_output_count": len(archive_outputs),
        "folder_path_count": len(folder_paths),
        "planned_copy_count": len(merge_result.get("planned_copies") or []),
        "counts": merge_result.get("manifest", {}).get("counts"),
        "validation": validation,
    }


def audit_run_completion(
    config: RootRunnerConfig,
    *,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = state if state is not None else load_runner_state(config.state_path, config.run_id)
    folders = state.get("folders") or {}
    completion_statuses = {
        "completed",
        "direct_notes_completed",
        "empty_or_unknown",
        "ignored_bad_path",
        "excluded_from_run",
        "traversed",
    }
    if config.skip_current_folder_export:
        completion_statuses.add("deferred_current_export")
    pending = []
    ignored = []
    archive_paths: dict[Path, list[str]] = {}
    missing_archive_records = []

    for folder_path, record in sorted(folders.items()):
        status = record.get("status")
        detail = record.get("detail") or {}
        archive_output = detail.get("archive_output")
        if not archive_output:
            export = detail.get("export") or {}
            archive_output = (export.get("handoff") or {}).get("archive_output")
        if status not in completion_statuses:
            pending.append({"folder_path": folder_path, "status": status, "strategy": record.get("strategy")})
            continue
        if status == "ignored_bad_path":
            ignored.append({"folder_path": folder_path, "detail": detail})
            continue
        if status in {"empty_or_unknown", "excluded_from_run", "deferred_current_export", "traversed"}:
            continue
        if not archive_output:
            missing_archive_records.append({"folder_path": folder_path, "status": status, "strategy": record.get("strategy")})
            continue
        archive_paths.setdefault(Path(str(archive_output)), []).append(folder_path)

    archive_validations = []
    invalid_archives = []
    for archive_path, folder_paths in sorted(archive_paths.items(), key=lambda item: str(item[0])):
        validation = validate_archive(archive_path)
        result = {
            "archive_output": str(archive_path),
            "folder_paths": folder_paths,
            "status": validation.get("status"),
            "counts": validation.get("counts"),
            "error_count": len(validation.get("errors") or []),
            "warning_count": len(validation.get("warnings") or []),
        }
        archive_validations.append(result)
        if validation.get("status") != "ok":
            invalid_archives.append(result)

    status = "complete" if not pending and not missing_archive_records and not invalid_archives else "needs_review"
    return {
        "status": status,
        "mode": "audit_run_completion",
        "run_id": config.run_id,
        "state_path": str(config.state_path),
        "folder_record_count": len(folders),
        "archive_output_count": len(archive_validations),
        "pending_count": len(pending),
        "pending": pending,
        "missing_archive_count": len(missing_archive_records),
        "missing_archives": missing_archive_records,
        "invalid_archive_count": len(invalid_archives),
        "invalid_archives": invalid_archives,
        "ignored_bad_path_count": len(ignored),
        "ignored_bad_paths": ignored,
        "archive_validations": archive_validations,
    }


def verify_current_folder_completion(
    config: RootRunnerConfig,
    *,
    state: dict[str, Any] | None = None,
    summary_provider: Callable[[RootRunnerConfig, str, str | None], dict[str, Any]] = current_summary,
) -> dict[str, Any]:
    state = state if state is not None else load_runner_state(config.state_path, config.run_id)
    summary = summary_provider(config, "verify_current_folder", None)
    classification = classify_folder(summary)
    folder_path = classification.get("folder_path")
    if not folder_path:
        raise SystemExit("Refusing action: current Samsung Notes folder path is empty")

    visible_children = []
    missing_children = []
    for title in visible_child_titles(summary):
        expected_child_path = child_path(folder_path, title)
        record = (state.get("folders") or {}).get(expected_child_path) or {}
        accounted = folder_has_accounted_status(state, expected_child_path)
        child = {
            "folder_path": expected_child_path,
            "title": title,
            "status": record.get("status"),
            "strategy": record.get("strategy"),
            "accounted": accounted,
        }
        visible_children.append(child)
        if not accounted:
            missing_children.append(child)

    has_notes = bool(classification.get("has_notes"))
    direct_record = (state.get("folders") or {}).get(folder_path) or {}
    direct_notes_accounted = (not has_notes) or direct_notes_already_exported(state, folder_path) or is_completed(state, folder_path)
    hidden = summary.get("subfolder_expand") or {}
    hidden_children_may_exist = bool(hidden.get("available") and hidden.get("is_show_all"))

    if missing_children:
        status = "pending_visible_children"
    elif not direct_notes_accounted:
        status = "pending_direct_notes"
    elif hidden_children_may_exist:
        status = "unknown_hidden_children"
    else:
        status = "complete_visible"

    return {
        "status": status,
        "mode": "verify_current_folder",
        "folder_path": folder_path,
        "classification": classification,
        "direct_notes": {
            "has_notes": has_notes,
            "accounted": direct_notes_accounted,
            "status": direct_record.get("status"),
            "strategy": direct_record.get("strategy"),
            "archive_output": (direct_record.get("detail") or {}).get("archive_output"),
        },
        "visible_child_count": len(visible_children),
        "visible_children": visible_children,
        "missing_visible_child_count": len(missing_children),
        "missing_visible_children": missing_children,
        "hidden_children_may_exist": hidden_children_may_exist,
        "state_path": str(config.state_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stateful top-level Samsung Notes export runner.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--input-root", type=Path, default=Path("input_exports"))
    parser.add_argument("--archive-root", type=Path, default=Path("output_archive"))
    parser.add_argument("--out-dir", type=Path, default=Path("ui_dumps"))
    parser.add_argument("--wait-seconds", type=float, default=1.0)
    parser.add_argument("--max-visible-batches", type=int, default=8)
    parser.add_argument("--max-empty-scrolls", type=int, default=8)
    parser.add_argument("--max-subfolder-scrolls", type=int, default=3)
    parser.add_argument("--max-navigation-scrolls", type=int, default=12)
    parser.add_argument("--max-count", type=int)
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--max-folders", type=int)
    parser.add_argument(
        "--skip-current-folder-export",
        action="store_true",
        help="Traverse child folders without exporting direct notes from the starting/current folder.",
    )
    parser.add_argument("--allow-existing-output", action="store_true")
    parser.add_argument(
        "--navigate-to-folder",
        help="Navigate through the visible Samsung Notes folder tree to one exact top-level folder before running.",
    )
    parser.add_argument(
        "--navigate-only",
        action="store_true",
        help="Stop after guarded top-level folder navigation. Requires --navigate-to-folder.",
    )
    parser.add_argument(
        "--process-visible-subfolders",
        action="store_true",
        help="From the current folder screen, enter each visible subfolder and run the folder-level strategy.",
    )
    parser.add_argument(
        "--recursive-current-folder",
        action="store_true",
        help="Recursively process the current folder and its visible child folders with bounded depth/folder limits.",
    )
    parser.add_argument(
        "--verify-current-folder",
        action="store_true",
        help="Fast read-only coverage check for the current visible folder against runner state/seed.",
    )
    parser.add_argument(
        "--audit-run-completion",
        action="store_true",
        help="Read-only local audit of runner state and every completed per-folder archive.",
    )
    parser.add_argument("--finalize-run-archive", action="store_true", help="Merge archive outputs recorded in the runner state and validate the merged archive.")
    parser.add_argument("--merged-output", type=Path, help="Output directory for --finalize-run-archive.")
    parser.add_argument("--merge-dry-run", action="store_true", help="Plan the final merge without copying files.")
    parser.add_argument("--seed-completed", type=Path, help="Seed completed folders from a JSON list before running or finalizing.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--export-format", choices=sorted(EXPORT_FORMATS), default="sdocx")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--summary-only", action="store_true", help="Print compact counts and exceptions instead of full runner details.")
    args = parser.parse_args(argv)

    state_path = args.state or (args.archive_root / args.run_id / "root_export_state.json")
    config = RootRunnerConfig(
        run_id=args.run_id,
        state_path=state_path,
        input_root=args.input_root,
        archive_root=args.archive_root,
        out_dir=args.out_dir,
        execute=args.execute,
        wait_seconds=args.wait_seconds,
        max_visible_batches=args.max_visible_batches,
        max_empty_scrolls=args.max_empty_scrolls,
        max_subfolder_scrolls=args.max_subfolder_scrolls,
        max_count=args.max_count,
        max_depth=args.max_depth,
        max_folders=args.max_folders,
        skip_current_folder_export=args.skip_current_folder_export,
        allow_existing_output=args.allow_existing_output,
        quiet=args.quiet,
        export_format=args.export_format,
    )
    state = load_runner_state(state_path, args.run_id)
    bind_export_format(state, config.export_format)
    if args.navigate_only and not args.navigate_to_folder:
        parser.error("--navigate-only requires --navigate-to-folder")
    navigation_result = None
    if args.navigate_to_folder:
        navigation_result = navigate_to_top_level_folder(
            config,
            args.navigate_to_folder,
            max_scrolls=args.max_navigation_scrolls,
        )
    seed_result = None
    if args.seed_completed:
        entries = load_seed_entries(args.seed_completed)
        seed_result = seed_completed_folders(state, entries, source=str(args.seed_completed))
        save_runner_state(state_path, state)

    if args.navigate_only:
        result = navigation_result or {"status": "not_requested"}
    elif args.finalize_run_archive:
        result = finalize_run_archive(config, state=state, output=args.merged_output, dry_run=args.merge_dry_run or None)
    elif args.audit_run_completion:
        result = audit_run_completion(config, state=state)
    elif args.verify_current_folder:
        result = verify_current_folder_completion(config, state=state)
    elif args.recursive_current_folder:
        result = run_recursive_current_folder(config, state=state)
    elif args.process_visible_subfolders:
        result = run_visible_subfolders(config, state=state)
    else:
        result = run_current_folder(config, state=state)
    if seed_result is not None:
        result = {**result, "seed": seed_result}
    if navigation_result is not None and not args.navigate_only:
        result = {**result, "navigation": navigation_result}
    if args.summary_only:
        result = {
            "status": result.get("status"),
            "mode": result.get("mode"),
            "run_id": args.run_id,
            "folder_path": result.get("folder_path"),
            "counts": {
                "folder_record_count": result.get("folder_record_count"),
                "archive_output_count": result.get("archive_output_count"),
                "visible_child_count": result.get("visible_child_count"),
                "missing_visible_child_count": result.get("missing_visible_child_count"),
                "pending_count": result.get("pending_count"),
                "missing_archive_count": result.get("missing_archive_count"),
                "invalid_archive_count": result.get("invalid_archive_count"),
                "ignored_bad_path_count": result.get("ignored_bad_path_count"),
            },
            "pending": result.get("pending") or result.get("missing_visible_children") or [],
            "missing_archives": result.get("missing_archives") or [],
            "invalid_archives": result.get("invalid_archives") or [],
            "hidden_children_may_exist": result.get("hidden_children_may_exist"),
            "navigation_status": (result.get("navigation") or {}).get("status"),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
