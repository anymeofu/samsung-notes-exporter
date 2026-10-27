from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .archive_builder import build_archive
from . import ui_guard
from . import visual_observer
from .selection_limits import MAX_EXPORT_SELECTION_COUNT
from .visible_batch_state import load_state
from .workflow_state import ArtifactRef, WorkflowPhase, WorkflowRunState, initial_workflow_state


REMOTE_XML = "/sdcard/window_dump.xml"
QUIET = False
ADB_TIMEOUT_SECONDS = 30.0
DUMP_TIMEOUT_SECONDS = 20.0
EXPORT_FORMATS = {
    "sdocx": {
        "menu_text": "삼성 노트 파일",
        "extension": ".sdocx",
        "action": "tap_samsung_notes_file",
    },
    "txt": {
        "menu_text": "텍스트 파일",
        "extension": ".txt",
        "action": "tap_text_file",
    },
}


@dataclass(frozen=True)
class DriverConfig:
    allowed_path: str
    destination: str
    out_dir: Path
    label: str
    execute: bool
    select_count: int
    select_all: bool
    wait_seconds: float
    pull_to: Path | None
    mapping_path: Path | None
    archive_output: Path | None
    observation_dir: Path | None = None
    observation_level: int = 0
    observation_max_candidates: int = 35
    allow_existing_output: bool = False
    deselect_visible_subfolders_after_select_all: bool = False
    selection_probe_only: bool = False
    deselect_scroll_attempts: int = 4
    deselect_max_taps: int = 80
    skip_note_fingerprints: frozenset[str] = frozenset()
    export_format: str = "sdocx"
    allow_partial_export: bool = False


def adb(
    args: list[str],
    *,
    capture: bool = False,
    timeout_seconds: float = ADB_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    command_parts = [ui_guard.adb_path(), *args]
    kwargs: dict[str, Any] = {
        "check": True,
        "text": True,
        "timeout": timeout_seconds,
    }
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    try:
        return subprocess.run(command_parts, **kwargs)
    except subprocess.TimeoutExpired as exc:
        command = " ".join(command_parts)
        raise SystemExit(f"Refusing action: adb command timed out after {timeout_seconds:.1f}s: {command}") from exc
    except subprocess.CalledProcessError as exc:
        command = " ".join(command_parts)
        output = ""
        for stream in (exc.stderr, exc.stdout):
            if isinstance(stream, str) and stream.strip():
                output = stream.strip()
                break
        detail = f": {output}" if output else ""
        raise SystemExit(f"Refusing action: adb command failed with exit {exc.returncode}: {command}{detail}") from exc


def set_quiet(value: bool) -> None:
    global QUIET
    QUIET = value


def log(message: str) -> None:
    if not QUIET:
        print(message, file=sys.stderr, flush=True)


def safe_label(value: str) -> str:
    allowed = []
    for char in value:
        if char.isalnum() or char in "._-":
            allowed.append(char)
        else:
            allowed.append("_")
    return "".join(allowed).strip("_") or "guarded_export"


def dump_ui(config: DriverConfig, step: str) -> Path:
    config.out_dir.mkdir(parents=True, exist_ok=True)
    local_xml = config.out_dir / f"{safe_label(config.label)}_{step}.xml"
    log(f"[{step}] dumping current UI")
    adb(["shell", "uiautomator", "dump", REMOTE_XML], capture=True, timeout_seconds=DUMP_TIMEOUT_SECONDS)
    adb(["pull", REMOTE_XML, str(local_xml)], capture=True)
    if config.observation_dir is not None:
        observation = visual_observer.build_observation_from_xml(
            label=f"{safe_label(config.label)}_{step}",
            out_dir=config.observation_dir,
            xml_path=local_xml,
            level=config.observation_level,
            max_candidates=config.observation_max_candidates,
            last_action=step,
            task_state=f"allowed_path={config.allowed_path}",
        )
        log(f"[{step}] observation metadata: {observation['metadata']}")
    return local_xml


def load_summary(xml_path: Path, allowed_path: str) -> dict[str, Any]:
    return ui_guard.summarize(xml_path, [allowed_path])


def require_notes_folder(summary: dict[str, Any], allowed_path: str) -> None:
    if not summary["is_samsung_notes_visible"]:
        raise SystemExit(f"Refusing action: Samsung Notes is not visible. Packages: {summary['packages']}")
    ui_guard.assert_allowed_path(summary["folder_path"], [allowed_path])


def tap_single_resource(xml_path: Path, resource_id: str) -> dict[str, Any]:
    root = ui_guard.load_xml(xml_path)
    matches = ui_guard.find_nodes_by_resource_id(root, resource_id)
    if len(matches) != 1:
        raise SystemExit(f"Refusing action: expected exactly one {resource_id}, found {len(matches)}")
    target = matches[0]
    if not target["enabled"]:
        raise SystemExit(f"Refusing action: target is disabled: {target}")
    x, y = target["center"]
    ui_guard.tap(x, y)
    return target


def find_single_resource(xml_path: Path, resource_id: str) -> dict[str, Any]:
    root = ui_guard.load_xml(xml_path)
    matches = ui_guard.find_nodes_by_resource_id(root, resource_id)
    if len(matches) != 1:
        raise SystemExit(f"Refusing action: expected exactly one {resource_id}, found {len(matches)}")
    target = matches[0]
    if not target["enabled"]:
        raise SystemExit(f"Refusing action: target is disabled: {target}")
    return target


def tap_single_text(xml_path: Path, text: str) -> dict[str, Any]:
    root = ui_guard.load_xml(xml_path)
    matches = ui_guard.find_nodes_by_text(root, text)
    if len(matches) != 1:
        raise SystemExit(f"Refusing action: expected exactly one text item {text!r}, found {len(matches)}")
    target = matches[0]
    if not target["enabled"]:
        raise SystemExit(f"Refusing action: target is disabled: {target}")
    x, y = target["center"]
    ui_guard.tap(x, y)
    return target


def find_select_all_target(xml_path: Path) -> dict[str, Any]:
    root = ui_guard.load_xml(xml_path)
    candidates = []
    match_count = 0
    for node in ui_guard.iter_nodes(root):
        if node.attrib.get("resource-id") != ui_guard.SELECT_ALL_CONTAINER_ID:
            continue
        match_count += 1
        bounds = ui_guard.parse_bounds(node.attrib.get("bounds", ""))
        if bounds is None:
            continue
        label_parts = []
        for child in node.iter("node"):
            label_parts.extend(
                part.strip()
                for part in (child.attrib.get("text", ""), child.attrib.get("content-desc", ""))
                if part.strip()
            )
        label = " ".join(label_parts)
        if bounds.top > 950:
            continue
        if "전체" not in label and "모두 선택" not in label:
            continue
        candidates.append(
            {
                "resource_id": ui_guard.SELECT_ALL_CONTAINER_ID,
                "class": node.attrib.get("class"),
                "text": node.attrib.get("text"),
                "content_desc": node.attrib.get("content-desc"),
                "label": label,
                "bounds": node.attrib.get("bounds"),
                "center": list(bounds.center),
                "clickable": node.attrib.get("clickable") == "true",
                "enabled": node.attrib.get("enabled") == "true",
            }
        )
    if len(candidates) != 1:
        raise SystemExit(
            "Refusing action: expected exactly one top toolbar select-all target, "
            f"found {len(candidates)} from {match_count} checkbox_withtext node(s)"
        )
    target = candidates[0]
    if not target["enabled"]:
        raise SystemExit(f"Refusing action: select-all target is disabled: {target}")
    return target


def find_single_text(xml_path: Path, text: str) -> dict[str, Any]:
    root = ui_guard.load_xml(xml_path)
    matches = ui_guard.find_nodes_by_text(root, text)
    if len(matches) != 1:
        raise SystemExit(f"Refusing action: expected exactly one text item {text!r}, found {len(matches)}")
    target = matches[0]
    if not target["enabled"]:
        raise SystemExit(f"Refusing action: target is disabled: {target}")
    return target


def detect_filename_dialog(xml_path: Path) -> tuple[str, dict[str, Any]]:
    root = ui_guard.load_xml(xml_path)
    details = ui_guard.filename_dialog_details(root)
    title_matches = details["title_matches"]
    input_matches = details["input_matches"]
    save_matches = details["save_matches"]
    if len(title_matches) != 1 or title_matches[0].get("text") != "파일 이름":
        raise SystemExit("Refusing action: filename dialog title was not found")
    if len(input_matches) != 1:
        raise SystemExit(f"Refusing action: expected one filename input, found {len(input_matches)}")
    filename = input_matches[0].get("text") or ""
    if not ui_guard.is_safe_export_filename(filename):
        raise SystemExit(f"Refusing action: filename {filename!r} is not a safe export filename")
    if len(save_matches) != 1 or save_matches[0].get("text") != "저장":
        raise SystemExit(f"Refusing action: expected one 저장 button, found {len(save_matches)}")
    target = save_matches[0]
    if not target["enabled"]:
        raise SystemExit(f"Refusing action: target is disabled: {target}")
    return filename, target


def require_export_format(export_format: str) -> dict[str, str]:
    spec = EXPORT_FORMATS.get(export_format)
    if spec is None:
        raise SystemExit(f"Refusing action: unsupported export format: {export_format}")
    return spec


def verify_public_file(destination: str, filename: str, *, extension: str = ".sdocx") -> str:
    path = f"/sdcard/{destination}/{filename}{extension}"
    result = adb(["shell", f"ls -l {shlex.quote(path)}"], capture=True)
    return result.stdout.strip()


def list_public_exports(destination: str, extension: str) -> dict[str, str]:
    if extension not in {spec["extension"] for spec in EXPORT_FORMATS.values()}:
        raise SystemExit(f"Refusing action: unsupported export extension: {extension}")
    root = f"/sdcard/{destination}"
    result = adb(
        [
            "shell",
            f"if [ -d {shlex.quote(root)} ]; then "
            f"find {shlex.quote(root)} -maxdepth 1 -type f -iname '*{extension}' -exec ls -l {{}} \\; 2>/dev/null; fi",
        ],
        capture=True,
    )
    files: dict[str, str] = {}
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        marker = f" {root}/"
        if marker not in line:
            continue
        path = line.split(marker, 1)[1]
        files[f"{root}/{path}"] = line
    return files


def list_public_sdocx(destination: str) -> dict[str, str]:
    return list_public_exports(destination, ".sdocx")


def wait_for_new_public_exports(
    destination: str,
    before_files: dict[str, str],
    expected_min: int,
    *,
    extension: str,
    timeout_seconds: float = 90.0,
    poll_seconds: float = 2.0,
) -> tuple[list[str], dict[str, str]]:
    deadline = time.monotonic() + timeout_seconds
    after_files: dict[str, str] = {}
    exported_files: list[str] = []
    last_reported_count = -1
    while True:
        after_files = list_public_exports(destination, extension)
        exported_files = sorted(path for path in after_files if path not in before_files)
        if len(exported_files) != last_reported_count:
            log(f"[verify] detected {len(exported_files)}/{expected_min} new {extension} files in {destination}")
            last_reported_count = len(exported_files)
        if len(exported_files) >= expected_min:
            return exported_files, after_files
        if time.monotonic() >= deadline:
            log(f"[verify] timed out with {len(exported_files)}/{expected_min} new {extension} files in {destination}")
            return exported_files, after_files
        time.sleep(poll_seconds)


def wait_for_new_public_sdocx(
    destination: str,
    before_files: dict[str, str],
    expected_min: int,
    *,
    timeout_seconds: float = 90.0,
    poll_seconds: float = 2.0,
) -> tuple[list[str], dict[str, str]]:
    return wait_for_new_public_exports(
        destination,
        before_files,
        expected_min,
        extension=".sdocx",
        timeout_seconds=timeout_seconds,
        poll_seconds=poll_seconds,
    )


def validate_export_file_count(*, expected: int, actual: int, extension: str, allow_partial: bool) -> dict[str, Any] | None:
    if actual >= expected:
        return None
    if not allow_partial or actual == 0:
        raise SystemExit(
            f"Refusing success: expected at least {expected} new {extension} files, found {actual}"
        )
    return {
        "status": "partial",
        "expected_file_count": expected,
        "exported_file_count": actual,
        "missing_file_count": expected - actual,
        "reason": "selected_notes_without_generated_export_files",
    }


def pull_exported_files(remote_paths: list[str], output_dir: Path, *, extension: str = ".sdocx") -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pulled: list[Path] = []
    for remote_path in remote_paths:
        if not remote_path.lower().endswith(extension):
            raise SystemExit(f"Refusing action: exported path does not end with {extension}: {remote_path}")
        log(f"[pull] copy-only pull {remote_path}")
        adb(["pull", remote_path, str(output_dir) + "/"], capture=True)
        pulled.append(output_dir / Path(remote_path).name)
    return pulled


def ensure_output_targets_available(
    pull_to: Path | None,
    archive_output: Path | None,
    *,
    allow_existing_output: bool,
) -> None:
    if allow_existing_output:
        return
    existing = [path for path in (pull_to, archive_output) if path is not None and path.exists()]
    if existing:
        paths = ", ".join(str(path) for path in existing)
        raise SystemExit(
            "Refusing action: output target already exists. "
            f"Choose a new run id/output path or pass --allow-existing-output. Existing: {paths}"
        )


def write_archive_mapping(
    pulled_files: list[Path],
    mapping_path: Path,
    folder_path: str,
) -> dict[str, Any]:
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    notes = []
    for index, pulled_file in enumerate(pulled_files, start=1):
        notes.append(
            {
                "id": f"exported-note-{index:06d}",
                "title": pulled_file.stem,
                "source": pulled_file.name,
                "folder_path": folder_path,
            }
        )
    mapping = {"notes": notes}
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return mapping


def run_step(
    config: DriverConfig,
    step: str,
    action: Callable[[Path], dict[str, Any]],
    *,
    pause_after: bool = True,
) -> dict[str, Any]:
    xml_path = dump_ui(config, step)
    result: dict[str, Any] = {"step": step, "xml": str(xml_path), "executed": config.execute}
    log(f"[{step}] validating and running guarded action")
    action_result = action(xml_path)
    result.update(action_result)
    log(f"[{step}] ok: {result.get('action')}")
    if pause_after and config.execute:
        time.sleep(config.wait_seconds)
    return result


def record_export_workflow(
    state: WorkflowRunState | None,
    workflow_events: list[dict[str, Any]],
    config: DriverConfig,
    phase: WorkflowPhase,
    *,
    last_action: str | None = None,
    next_action: str | None = None,
    counts: dict[str, int] | None = None,
    artifacts: list[ArtifactRef] | tuple[ArtifactRef, ...] = (),
    error: str | None = None,
) -> WorkflowRunState:
    if state is None:
        state = initial_workflow_state(config.label, config.allowed_path)
    state = state.transition(
        phase,
        current_folder_path=config.allowed_path,
        last_action=last_action,
        next_action=next_action,
        counts=counts,
        artifacts=artifacts,
        error=error,
    )
    event = state.compact(artifact_limit=3, skipped_limit=3)
    event["sequence"] = len(workflow_events) + 1
    workflow_events.append(event)
    return state


def workflow_counts_for_export_event(event: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key in (
        "visible_note_count",
        "already_selected",
        "additional_selected",
        "checked_count",
        "selected_count",
    ):
        value = event.get(key)
        if isinstance(value, int):
            counts[key] = value
    requested = event.get("requested_select_count")
    if isinstance(requested, int):
        counts["requested_select_count"] = requested
    if event.get("select_all") is True or requested == "all":
        counts["select_all"] = 1
    return counts


def workflow_phase_for_export_action(action: str) -> WorkflowPhase:
    if action in {
        "long_press_first_note",
        "tap_select_all",
        "deselect_visible_subfolder_checkboxes",
        "select_additional_visible_notes",
        "confirm_selected_note_count",
    }:
        return WorkflowPhase.SELECT_NOTES
    if action in {"tap_overflow", "tap_save_as_file"}:
        return WorkflowPhase.OPEN_EXPORT_MENU
    if action in {"tap_samsung_notes_file", "tap_text_file", "tap_export_format"}:
        return WorkflowPhase.CHOOSE_EXPORT_FORMAT
    if action in {"tap_destination", "tap_myfiles_done", "tap_filename_save"}:
        return WorkflowPhase.CHOOSE_DESTINATION
    return WorkflowPhase.EXPORT_CURRENT_FOLDER_NOTES


def workflow_next_action_for_export_action(action: str) -> str | None:
    next_actions = {
        "long_press_first_note": "select_remaining_or_all",
        "tap_select_all": "confirm_selection",
        "deselect_visible_subfolder_checkboxes": "confirm_selection",
        "select_additional_visible_notes": "confirm_selection",
        "confirm_selected_note_count": "open_selection_overflow",
        "tap_overflow": "tap_save_as_file",
        "tap_save_as_file": "choose_export_format",
        "tap_samsung_notes_file": "choose_myfiles_destination",
        "tap_text_file": "choose_myfiles_destination",
        "tap_export_format": "choose_myfiles_destination",
        "tap_destination": "tap_myfiles_done",
        "tap_myfiles_done": "verify_export_or_filename_dialog",
        "tap_filename_save": "verify_export",
    }
    return next_actions.get(action)


def selected_count_for_select_all(summary: dict[str, Any], checked_count: int) -> int:
    selected_count = summary["selection_info"]["selected_count"]
    note_card_count = summary["note_card_count"]
    if selected_count is None:
        if checked_count < note_card_count:
            raise SystemExit(f"Refusing action: selected count was not visible: {summary['selection_info']}")
        selected_count = checked_count
    if selected_count < note_card_count:
        raise SystemExit(
            f"Refusing action: select-all chose {selected_count}, "
            f"but {note_card_count} note cards are visible"
        )
    if checked_count < note_card_count:
        raise SystemExit(
            f"Refusing action: only {checked_count} visible notes are checked "
            f"out of {note_card_count}"
        )
    return selected_count


def require_export_overflow_available(summary: dict[str, Any], selected_count: int | None) -> None:
    if summary.get("bottom_overflow_available"):
        return
    dangerous = ", ".join(summary.get("dangerous_actions_present") or [])
    detail = f"selected_count={selected_count}"
    if dangerous:
        detail = f"{detail}; visible_actions={dangerous}"
    raise SystemExit(
        "Refusing action: Samsung Notes is not exposing export overflow for this selection "
        f"({detail}). Use a smaller batch/partitioned export plan."
    )


def require_export_selection_limit(selected_count: int | None) -> None:
    if selected_count is None or selected_count <= MAX_EXPORT_SELECTION_COUNT:
        return
    raise SystemExit(
        f"Refusing action: selected_count={selected_count} exceeds the safe Samsung Notes export "
        f"batch limit of {MAX_EXPORT_SELECTION_COUNT}. Use partitioned visible batches."
    )


def selected_count_for_select_all_after_subfolder_deselect(summary: dict[str, Any], checked_count: int) -> int:
    return verify_note_only_selection_after_subfolder_deselect(summary, checked_count)["selected_count"]


def can_skip_select_all_after_first(
    summary: dict[str, Any],
    *,
    deselect_subfolders_after_select_all: bool,
) -> bool:
    if deselect_subfolders_after_select_all:
        return False
    checked_count = sum(1 for card in summary.get("note_cards", []) if card.get("checked"))
    note_card_count = int(summary.get("note_card_count") or 0)
    selected_count = summary.get("selection_info", {}).get("selected_count")
    return checked_count > 0 and checked_count == note_card_count and selected_count == checked_count


def verify_note_only_selection_after_subfolder_deselect(
    summary: dict[str, Any],
    checked_count: int,
) -> dict[str, Any]:
    if summary.get("selected_subfolder_count"):
        raise SystemExit(
            "Refusing action: selected subfolders remain after deselection: "
            f"{summary['selected_subfolder_count']}"
        )
    selected_count = summary["selection_info"]["selected_count"]
    if selected_count is None:
        selected_count = checked_count
    if selected_count < checked_count:
        raise SystemExit(
            f"Refusing action: selected count {selected_count} is less than checked note cards {checked_count}"
        )
    note_count = (summary.get("visible_counts") or {}).get("note_count")
    if note_count is not None and selected_count != note_count:
        raise SystemExit(
            f"Refusing action: selected count {selected_count} does not match UI note count {note_count}"
        )
    require_export_overflow_available(summary, selected_count)
    if selected_count < 1:
        raise SystemExit("Refusing action: no notes remain selected after subfolder deselection")
    return {
        "selected_count": selected_count,
        "checked_count": checked_count,
        "ui_note_count": note_count,
        "bottom_overflow_available": True,
    }


def is_stably_visible_checkbox_target(target: dict[str, Any]) -> bool:
    bounds = ui_guard.parse_bounds(str(target.get("bounds") or ""))
    if bounds is None:
        return False
    # Samsung Notes selection mode can float the breadcrumb bar over the upper
    # grid. Checkbox bounds behind that bar are stale hit targets, not safe taps.
    return bounds.top >= 485 and bounds.bottom <= 2214


def is_stably_tappable_note_card(target: dict[str, Any]) -> bool:
    bounds = ui_guard.parse_bounds(str(target.get("bounds") or ""))
    if bounds is None:
        return False
    _, center_y = bounds.center
    # In selection mode Samsung Notes overlays a bottom toolbar. A partially
    # visible note can still be reported as clickable, but tapping its center
    # can hit Move/Lock/Delete instead of the note card.
    return bounds.top >= 485 and center_y < 2067


def note_card_is_selectable(target: dict[str, Any], skip_fingerprints: set[str] | frozenset[str]) -> bool:
    fingerprint = target.get("fingerprint")
    if fingerprint and fingerprint in skip_fingerprints:
        return False
    return is_stably_tappable_note_card(target)


def selected_subfolder_checkbox_targets(summary: dict[str, Any]) -> list[dict[str, Any]]:
    targets = list(summary.get("selected_subfolder_checkboxes") or [])
    for target in targets:
        if not target.get("enabled"):
            raise SystemExit(f"Refusing action: selected subfolder checkbox target disabled: {target}")
    return targets


def stable_checkbox_targets(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [target for target in targets if is_stably_visible_checkbox_target(target)]


def unstable_checkbox_targets(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [target for target in targets if not is_stably_visible_checkbox_target(target)]


def checkbox_target_signature(targets: list[dict[str, Any]]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(target.get("title") or ""), str(target.get("bounds") or "")) for target in targets))


def is_selection_context(summary: dict[str, Any]) -> bool:
    if summary.get("selected_subfolder_count", 0) > 0:
        return True
    if summary.get("selection_info", {}).get("text"):
        return True
    return any(card.get("checked") for card in summary.get("note_cards", []))


def require_selection_context(summary: dict[str, Any], allowed_path: str) -> None:
    if not summary["is_samsung_notes_visible"]:
        raise SystemExit("Refusing action: Samsung Notes disappeared during folder deselection")
    folder_path = summary.get("folder_path") or ""
    if folder_path and not ui_guard.is_allowed_path(folder_path, [allowed_path]):
        raise SystemExit(f"Refusing action: folder path changed during folder deselection: {folder_path!r}")
    if not is_selection_context(summary):
        raise SystemExit("Refusing action: selection context was lost during folder deselection")


def scroll_selection_page_down() -> None:
    adb(["shell", "input", "swipe", "540", "720", "540", "1700", "550"], capture=True)


def record_event_workflow(
    state: WorkflowRunState | None,
    workflow_events: list[dict[str, Any]],
    config: DriverConfig,
    event: dict[str, Any],
) -> WorkflowRunState:
    action = str(event.get("action") or event.get("step") or "unknown_export_action")
    artifacts = []
    if event.get("xml"):
        artifacts.append(ArtifactRef("ui_dump", Path(event["xml"]), note=str(event.get("step") or action)))
    return record_export_workflow(
        state,
        workflow_events,
        config,
        workflow_phase_for_export_action(action),
        last_action=action,
        next_action=workflow_next_action_for_export_action(action),
        counts=workflow_counts_for_export_event(event),
        artifacts=artifacts,
    )


def run_guarded_export(config: DriverConfig) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    workflow_events: list[dict[str, Any]] = []
    workflow_state: WorkflowRunState | None = initial_workflow_state(config.label, config.allowed_path)
    format_spec = require_export_format(config.export_format)
    export_extension = format_spec["extension"]
    if config.select_count < 1:
        raise SystemExit("Refusing action: --select-count must be at least 1")
    if not config.select_all and config.select_count > MAX_EXPORT_SELECTION_COUNT:
        raise SystemExit(
            f"Refusing action: --select-count must be <= {MAX_EXPORT_SELECTION_COUNT} "
            "because Samsung Notes disables some actions at 100+ selected files"
        )
    if config.select_all and config.select_count != 1:
        raise SystemExit("Refusing action: use either --select-all or --select-count, not both")
    if config.deselect_visible_subfolders_after_select_all and not config.select_all:
        raise SystemExit("Refusing action: --deselect-visible-subfolders-after-select-all requires --select-all")
    if config.selection_probe_only and not config.execute:
        raise SystemExit("Refusing action: --selection-probe-only is only meaningful with --execute")
    if config.deselect_scroll_attempts < 0:
        raise SystemExit("Refusing action: --deselect-scroll-attempts must be non-negative")
    if config.deselect_max_taps < 1:
        raise SystemExit("Refusing action: --deselect-max-taps must be at least 1")
    if config.execute:
        ensure_output_targets_available(
            config.pull_to,
            config.archive_output,
            allow_existing_output=config.allow_existing_output,
        )
    before_files = list_public_exports(config.destination, export_extension) if config.execute else {}

    def select_first(xml_path: Path) -> dict[str, Any]:
        summary = load_summary(xml_path, config.allowed_path)
        require_notes_folder(summary, config.allowed_path)
        if summary["dangerous_actions_present"]:
            raise SystemExit(f"Refusing action: dangerous selection actions already present: {summary['dangerous_actions_present']}")
        if not summary["note_cards"]:
            raise SystemExit("Refusing action: no note cards found")
        if (
            config.select_all
            and summary["subfolder_count"] > 0
            and not config.deselect_visible_subfolders_after_select_all
        ):
            raise SystemExit(
                "Refusing action: --select-all is unsafe while subfolders are visible. "
                "Use --select-count for visible direct notes in a mixed folder."
            )
        if not config.select_all and config.select_count > summary["note_card_count"]:
            raise SystemExit(
                f"Refusing action: requested {config.select_count} notes, "
                f"but only {summary['note_card_count']} visible note cards were found"
            )
        selectable_cards = [
            card for card in summary["note_cards"] if note_card_is_selectable(card, config.skip_note_fingerprints)
        ]
        if not selectable_cards:
            raise SystemExit("Refusing action: no safely tappable unskipped note cards found")
        if not config.select_all and config.select_count > len(selectable_cards):
            raise SystemExit(
                f"Refusing action: requested {config.select_count} notes, "
                f"but only {len(selectable_cards)} unskipped note cards are safely tappable"
            )
        target_card = selectable_cards[0]
        x, y = target_card["center"]
        if config.execute:
            ui_guard.long_press(x, y, 900)
        return {
            "action": "long_press_first_note",
            "folder_path": summary["folder_path"],
            "target": {"x": x, "y": y},
            "requested_select_count": "all" if config.select_all else config.select_count,
            "visible_note_count": summary["note_card_count"],
            "safe_unskipped_note_count": len(selectable_cards),
        }

    def tap_select_all(xml_path: Path) -> dict[str, Any]:
        summary = load_summary(xml_path, config.allowed_path)
        require_notes_folder(summary, config.allowed_path)
        checked_cards = [card for card in summary["note_cards"] if card.get("checked")]
        if len(checked_cards) != 1:
            raise SystemExit(f"Refusing action: expected exactly one selected note before select-all, found {len(checked_cards)}")
        target = find_select_all_target(xml_path)
        if config.execute:
            x, y = target["center"]
            ui_guard.tap(x, y)
        return {
            "action": "tap_select_all",
            "already_selected": len(checked_cards),
            "target": target,
        }

    def deselect_visible_subfolders(xml_path: Path) -> dict[str, Any]:
        summary = load_summary(xml_path, config.allowed_path)
        require_notes_folder(summary, config.allowed_path)
        initial_targets = selected_subfolder_checkbox_targets(summary)
        skipped_targets = unstable_checkbox_targets(initial_targets)
        tapped_targets: list[dict[str, Any]] = []
        scroll_count = 0
        repeated_signature_count = 0
        previous_signature: tuple[tuple[str, str], ...] | None = None
        if config.execute:
            current_xml = xml_path
            while len(tapped_targets) < config.deselect_max_taps:
                current_summary = load_summary(current_xml, config.allowed_path)
                require_selection_context(current_summary, config.allowed_path)
                current_targets = selected_subfolder_checkbox_targets(current_summary)
                current_signature = checkbox_target_signature(current_targets)
                if current_signature == previous_signature:
                    repeated_signature_count += 1
                else:
                    repeated_signature_count = 0
                previous_signature = current_signature
                safe_targets = stable_checkbox_targets(current_targets)
                if safe_targets:
                    target = safe_targets[0]
                    x, y = target["center"]
                    ui_guard.tap(x, y)
                    tapped_targets.append(target)
                    time.sleep(0.2)
                    current_xml = dump_ui(config, f"01b_deselect_visible_subfolders_after_tap_{len(tapped_targets):02d}")
                    continue
                if not current_targets:
                    break
                if scroll_count >= config.deselect_scroll_attempts:
                    break
                if repeated_signature_count >= 1 and scroll_count > 0:
                    break
                scroll_selection_page_down()
                scroll_count += 1
                time.sleep(0.3)
                current_xml = dump_ui(config, f"01b_deselect_visible_subfolders_after_scroll_{scroll_count:02d}")
            final_summary = load_summary(current_xml, config.allowed_path)
            require_selection_context(final_summary, config.allowed_path)
            remaining_targets = selected_subfolder_checkbox_targets(final_summary)
        else:
            tapped_targets = stable_checkbox_targets(initial_targets)
            remaining_targets = skipped_targets
        return {
            "action": "deselect_visible_subfolder_checkboxes",
            "target_count": len(tapped_targets),
            "scroll_count": scroll_count,
            "skipped_unstable_target_count": len(skipped_targets),
            "remaining_visible_selected_subfolder_count": len(remaining_targets),
            "targets": tapped_targets,
        }

    def select_remaining(xml_path: Path) -> dict[str, Any]:
        summary = load_summary(xml_path, config.allowed_path)
        require_notes_folder(summary, config.allowed_path)
        checked_cards = [card for card in summary["note_cards"] if card.get("checked")]
        unchecked_cards = [card for card in summary["note_cards"] if not card.get("checked")]
        tappable_unchecked_cards = [
            card for card in unchecked_cards if note_card_is_selectable(card, config.skip_note_fingerprints)
        ]
        if len(checked_cards) != 1:
            raise SystemExit(f"Refusing action: expected exactly one selected note after long-press, found {len(checked_cards)}")
        remaining = config.select_count - len(checked_cards)
        if remaining < 0:
            raise SystemExit(f"Refusing action: too many notes already selected: {len(checked_cards)}")
        if remaining > len(tappable_unchecked_cards):
            raise SystemExit(
                f"Refusing action: need {remaining} additional notes, "
                f"but only {len(tappable_unchecked_cards)} unchecked cards are safely tappable"
            )
        targets = tappable_unchecked_cards[:remaining]
        if config.execute:
            for target in targets:
                x, y = target["center"]
                ui_guard.tap(x, y)
                time.sleep(0.25)
        return {
            "action": "select_additional_visible_notes",
            "already_selected": len(checked_cards),
            "additional_selected": len(targets),
            "requested_select_count": config.select_count,
            "targets": [{"x": card["center"][0], "y": card["center"][1]} for card in targets],
        }

    selected_total_holder: dict[str, int] = {}

    def confirm_selection(xml_path: Path) -> dict[str, Any]:
        summary = load_summary(xml_path, config.allowed_path)
        require_notes_folder(summary, config.allowed_path)
        checked_count = sum(1 for card in summary["note_cards"] if card.get("checked"))
        selected_count = summary["selection_info"]["selected_count"]
        if config.select_all:
            if config.deselect_visible_subfolders_after_select_all:
                selection_verification = verify_note_only_selection_after_subfolder_deselect(summary, checked_count)
                selected_count = selection_verification["selected_count"]
            else:
                selected_count = selected_count_for_select_all(summary, checked_count)
                selection_verification = {}
            require_export_selection_limit(selected_count)
            require_export_overflow_available(summary, selected_count)
            selected_total_holder["selected_count"] = selected_count
            return {
                "action": "confirm_selected_note_count",
                "checked_count": checked_count,
                "selected_count": selected_count,
                "select_all": True,
                "selection_verification": selection_verification,
            }
        if checked_count != config.select_count:
            raise SystemExit(f"Refusing action: expected {config.select_count} checked notes, found {checked_count}")
        require_export_selection_limit(config.select_count)
        require_export_overflow_available(summary, config.select_count)
        selected_total_holder["selected_count"] = config.select_count
        return {
            "action": "confirm_selected_note_count",
            "checked_count": checked_count,
            "selected_count": selected_count,
            "select_all": False,
        }

    def tap_overflow(xml_path: Path) -> dict[str, Any]:
        summary = load_summary(xml_path, config.allowed_path)
        require_notes_folder(summary, config.allowed_path)
        resource_id = f"{ui_guard.NOTES_PACKAGE}:id/bottom_overflow"
        if resource_id not in ui_guard.SAFE_TAP_IDS:
            raise SystemExit(f"Refusing action: resource-id is not safe: {resource_id}")
        target = tap_single_resource(xml_path, resource_id) if config.execute else find_single_resource(xml_path, resource_id)
        return {"action": "tap_overflow", "target": target}

    def tap_save_as(xml_path: Path) -> dict[str, Any]:
        text = "파일로 저장"
        if text not in ui_guard.SAFE_MENU_TEXTS:
            raise SystemExit(f"Refusing action: menu text is not safe: {text}")
        target = tap_single_text(xml_path, text) if config.execute else find_single_text(xml_path, text)
        return {"action": "tap_save_as_file", "target": target}

    def tap_export_format(xml_path: Path) -> dict[str, Any]:
        text = format_spec["menu_text"]
        if text not in ui_guard.SAFE_MENU_TEXTS:
            raise SystemExit(f"Refusing action: menu text is not safe: {text}")
        target = tap_single_text(xml_path, text) if config.execute else find_single_text(xml_path, text)
        return {
            "action": format_spec["action"],
            "export_format": config.export_format,
            "extension": export_extension,
            "target": target,
        }

    def tap_destination(xml_path: Path) -> dict[str, Any]:
        summary = load_summary(xml_path, config.allowed_path)
        if ui_guard.MYFILES_PACKAGE not in summary["packages"]:
            raise SystemExit(f"Refusing action: My Files is not visible. Packages: {summary['packages']}")
        if config.destination not in ui_guard.SAFE_MYFILES_TEXTS:
            raise SystemExit(f"Refusing action: destination is not safe: {config.destination}")
        target = tap_single_text(xml_path, config.destination) if config.execute else find_single_text(xml_path, config.destination)
        return {"action": "tap_destination", "destination": config.destination, "target": target}

    def tap_done(xml_path: Path) -> dict[str, Any]:
        summary = load_summary(xml_path, config.allowed_path)
        if ui_guard.MYFILES_PACKAGE not in summary["packages"]:
            raise SystemExit(f"Refusing action: My Files is not visible. Packages: {summary['packages']}")
        resource_id = f"{ui_guard.MYFILES_PACKAGE}:id/menu_done"
        if resource_id not in ui_guard.SAFE_MYFILES_IDS:
            raise SystemExit(f"Refusing action: My Files resource-id is not safe: {resource_id}")
        target = tap_single_resource(xml_path, resource_id) if config.execute else find_single_resource(xml_path, resource_id)
        return {"action": "tap_myfiles_done", "target": target}

    filename_holder: dict[str, str] = {}

    def tap_filename_save(xml_path: Path) -> dict[str, Any]:
        summary = load_summary(xml_path, config.allowed_path)
        if not summary["is_samsung_notes_visible"]:
            raise SystemExit(f"Refusing action: Samsung Notes is not visible. Packages: {summary['packages']}")
        filename, target = detect_filename_dialog(xml_path)
        filename_holder["filename"] = filename
        if config.execute:
            x, y = target["center"]
            ui_guard.tap(x, y)
        return {"action": "tap_filename_save", "filename": filename, "target": target}

    event = run_step(config, "00_select_first", select_first)
    events.append(event)
    workflow_state = record_event_workflow(workflow_state, workflow_events, config, event)
    if not config.execute:
        planned_actions = [
            "long_press_first_note",
            "tap_select_all" if config.select_all else "select_additional_visible_notes",
            *(
                ["deselect_visible_subfolder_checkboxes"]
                if config.deselect_visible_subfolders_after_select_all
                else []
            ),
            "confirm_selected_note_count",
            "tap_overflow",
            "tap_save_as_file",
            format_spec["action"],
            "tap_destination",
            "tap_myfiles_done",
        ]
        if not config.select_all and config.select_count == 1:
            planned_actions.append("tap_filename_save")
        workflow_state = record_export_workflow(
            workflow_state,
            workflow_events,
            config,
            WorkflowPhase.DONE,
            last_action="dry_run_plan",
            next_action="review_planned_actions",
            counts={"planned_action_count": len(planned_actions)},
        )
        return {
            "allowed_path": config.allowed_path,
            "destination": config.destination,
            "export_format": config.export_format,
            "execute": config.execute,
            "select_count": "all" if config.select_all else config.select_count,
            "events": events,
            "workflow": workflow_state.compact(),
            "workflow_recent_events": workflow_events[-20:],
            "planned_actions": planned_actions,
            "verification": None,
        }

    if config.select_all:
        precheck_xml = dump_ui(config, "01_select_all_precheck")
        precheck_summary = load_summary(precheck_xml, config.allowed_path)
        require_notes_folder(precheck_summary, config.allowed_path)
        if can_skip_select_all_after_first(
            precheck_summary,
            deselect_subfolders_after_select_all=config.deselect_visible_subfolders_after_select_all,
        ):
            checked_count = sum(1 for card in precheck_summary["note_cards"] if card.get("checked"))
            event = {
                "step": "01_select_all_precheck",
                "xml": str(precheck_xml),
                "executed": config.execute,
                "action": "skip_select_all_already_selected",
                "checked_count": checked_count,
                "selected_count": precheck_summary["selection_info"]["selected_count"],
                "visible_note_count": precheck_summary["note_card_count"],
                "select_all": True,
            }
        else:
            event = run_step(config, "01_select_all", tap_select_all)
        events.append(event)
        workflow_state = record_event_workflow(workflow_state, workflow_events, config, event)
        if config.deselect_visible_subfolders_after_select_all:
            event = run_step(config, "01b_deselect_visible_subfolders", deselect_visible_subfolders)
            events.append(event)
            workflow_state = record_event_workflow(workflow_state, workflow_events, config, event)
    else:
        event = run_step(config, "01_select_remaining", select_remaining)
        events.append(event)
        workflow_state = record_event_workflow(workflow_state, workflow_events, config, event)
    for step, action in (
        ("02_confirm_selection", confirm_selection),
    ):
        event = run_step(config, step, action)
        events.append(event)
        workflow_state = record_event_workflow(workflow_state, workflow_events, config, event)

    if config.selection_probe_only:
        workflow_state = record_export_workflow(
            workflow_state,
            workflow_events,
            config,
            WorkflowPhase.DONE,
            last_action="selection_probe_only",
            next_action="review_selection_state_or_cancel",
            counts={
                "event_count": len(events),
                "selected_count": selected_total_holder.get("selected_count", 0),
            },
        )
        return {
            "allowed_path": config.allowed_path,
            "destination": config.destination,
            "export_format": config.export_format,
            "execute": config.execute,
            "select_count": "all" if config.select_all else config.select_count,
            "selection_probe_only": True,
            "events": events,
            "workflow": workflow_state.compact(),
            "workflow_recent_events": workflow_events[-20:],
            "exported_files": [],
            "verification": None,
            "handoff": None,
        }

    for step, action in (
        ("03_overflow", tap_overflow),
        ("04_save_as", tap_save_as),
        ("05_export_format", tap_export_format),
        ("06_destination", tap_destination),
        ("07_done", tap_done),
    ):
        event = run_step(config, step, action)
        events.append(event)
        workflow_state = record_event_workflow(workflow_state, workflow_events, config, event)

    exported_files: list[str] = []
    expects_filename_dialog = selected_total_holder.get("selected_count") == 1
    if expects_filename_dialog:
        event = run_step(config, "08_filename_save", tap_filename_save)
        events.append(event)
        workflow_state = record_event_workflow(workflow_state, workflow_events, config, event)

    verification = None
    partial_export = None
    handoff: dict[str, Any] | None = None
    if config.execute:
        time.sleep(config.wait_seconds)
        if expects_filename_dialog:
            log(f"[verify] checking exported public {export_extension}")
            verification = verify_public_file(
                config.destination,
                filename_holder["filename"],
                extension=export_extension,
            )
            exported_files = [f"/sdcard/{config.destination}/{filename_holder['filename']}{export_extension}"]
        else:
            log(f"[verify] checking newly exported public {export_extension} files")
            expected_min = selected_total_holder.get("selected_count", 1 if config.select_all else config.select_count)
            exported_files, after_files = wait_for_new_public_exports(
                config.destination,
                before_files,
                expected_min,
                extension=export_extension,
            )
            partial_export = validate_export_file_count(
                expected=expected_min,
                actual=len(exported_files),
                extension=export_extension,
                allow_partial=config.allow_partial_export,
            )
            verification = "\n".join(after_files[path] for path in exported_files)
        log("[verify] ok")
        workflow_state = record_export_workflow(
            workflow_state,
            workflow_events,
            config,
            WorkflowPhase.VERIFY_EXPORT,
            last_action="verify_public_sdocx",
            next_action="pull_exports" if config.pull_to is not None else "review_result",
            counts={"exported_file_count": len(exported_files)},
        )

        if config.pull_to is not None:
            pulled_files = pull_exported_files(exported_files, config.pull_to, extension=export_extension)
            mapping_path = config.mapping_path or (config.pull_to / "mapping.json")
            mapping = write_archive_mapping(pulled_files, mapping_path, config.allowed_path)
            handoff = {
                "pull_to": str(config.pull_to),
                "mapping_path": str(mapping_path),
                "pulled_files": [str(path) for path in pulled_files],
                "mapping": mapping,
            }
            workflow_state = record_export_workflow(
                workflow_state,
                workflow_events,
                config,
                WorkflowPhase.PULL_EXPORTS,
                last_action="pull_exported_files",
                next_action="build_archive" if config.archive_output is not None else "review_result",
                counts={"pulled_file_count": len(pulled_files)},
                artifacts=[ArtifactRef("mapping", mapping_path)],
            )
            if config.archive_output is not None:
                log("[archive] building local archive from pulled exports")
                archive_result = build_archive(config.pull_to, mapping_path, config.archive_output, dry_run=False)
                handoff["archive_output"] = str(config.archive_output)
                handoff["archive_counts"] = archive_result["manifest"]["counts"]
                log("[archive] ok")
                workflow_state = record_export_workflow(
                    workflow_state,
                    workflow_events,
                    config,
                    WorkflowPhase.BUILD_ARCHIVE,
                    last_action="build_archive",
                    next_action="review_result",
                    counts={
                        "archive_notes": archive_result["manifest"]["counts"]["notes"],
                        "archive_files": archive_result["manifest"]["counts"]["files"],
                    },
                    artifacts=[ArtifactRef("archive_output", config.archive_output)],
                )

    workflow_state = record_export_workflow(
        workflow_state,
        workflow_events,
        config,
        WorkflowPhase.DONE,
        last_action="run_guarded_export",
        next_action="review_result",
        counts={"event_count": len(events), "exported_file_count": len(exported_files)},
    )

    return {
        "allowed_path": config.allowed_path,
        "destination": config.destination,
        "export_format": config.export_format,
        "execute": config.execute,
        "select_count": "all" if config.select_all else config.select_count,
        "events": events,
        "workflow": workflow_state.compact(),
        "workflow_recent_events": workflow_events[-20:],
        "exported_files": exported_files,
        "verification": verification,
        "partial_export": partial_export,
        "handoff": handoff,
    }


def summarize_export_result(result: dict[str, Any]) -> dict[str, Any]:
    events = result.get("events", [])
    selected_count = None
    planned_actions = result.get("planned_actions", [])
    for event in events:
        if event.get("action") == "confirm_selected_note_count":
            selected_count = event.get("selected_count") or event.get("checked_count")
            break

    exported_files = result.get("exported_files") or []
    handoff = result.get("handoff") or {}
    workflow = result.get("workflow") or {}
    partial_export = result.get("partial_export")
    summary: dict[str, Any] = {
        "status": "partial" if partial_export else "ok",
        "allowed_path": result.get("allowed_path"),
        "destination": result.get("destination"),
        "export_format": result.get("export_format"),
        "execute": result.get("execute"),
        "selection_probe_only": result.get("selection_probe_only", False),
        "select_count": result.get("select_count"),
        "selected_count": selected_count,
        "event_count": len(events),
        "planned_action_count": len(planned_actions),
        "exported_file_count": len(exported_files),
    }
    if partial_export:
        summary["partial_export"] = partial_export
    if workflow:
        summary["workflow_phase"] = workflow.get("phase")
        summary["workflow_event_count"] = len(result.get("workflow_recent_events") or [])
    if planned_actions:
        summary["planned_actions"] = planned_actions
    if exported_files:
        summary["exported_file_names"] = [Path(path).name for path in exported_files]
    if handoff:
        summary["handoff"] = {
            "pull_to": handoff.get("pull_to"),
            "pulled_file_count": len(handoff.get("pulled_files") or []),
            "mapping_path": handoff.get("mapping_path"),
            "archive_output": handoff.get("archive_output"),
            "archive_counts": handoff.get("archive_counts"),
        }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guarded one-note Samsung Notes export driver.")
    parser.add_argument("--allowed-path", required=True, help="Exact Samsung Notes breadcrumb path allowed for note selection.")
    parser.add_argument("--destination", default="Documents", choices=sorted(ui_guard.SAFE_MYFILES_TEXTS))
    parser.add_argument("--export-format", default="sdocx", choices=sorted(EXPORT_FORMATS))
    parser.add_argument("--allow-partial-export", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=Path("ui_dumps"))
    parser.add_argument("--label", default="guarded_export")
    parser.add_argument("--select-count", type=int, default=1, help="Number of visible notes to select and export.")
    parser.add_argument("--select-all", action="store_true", help="Use Samsung Notes' top-left all-select checkbox after entering selection mode.")
    parser.add_argument(
        "--deselect-visible-subfolders-after-select-all",
        action="store_true",
        help="Experimental: after select-all, deselect visible selected subfolder checkboxes before export.",
    )
    parser.add_argument(
        "--selection-probe-only",
        action="store_true",
        help="Execute selection preparation and verification only, then stop before opening export menus.",
    )
    parser.add_argument("--wait-seconds", type=float, default=1.0)
    parser.add_argument(
        "--deselect-scroll-attempts",
        type=int,
        default=4,
        help="Maximum selection-list scrolls while trying to expose selected folder checkboxes safely.",
    )
    parser.add_argument(
        "--deselect-max-taps",
        type=int,
        default=80,
        help="Maximum selected-folder checkbox taps during deselection.",
    )
    parser.add_argument("--pull-to", type=Path, help="Copy-only pull newly exported files into this local directory.")
    parser.add_argument("--mapping-path", type=Path, help="Write Archive Builder mapping JSON here. Defaults to <pull-to>/mapping.json.")
    parser.add_argument("--archive-output", type=Path, help="Build a local archive from pulled files and the generated mapping.")
    parser.add_argument("--execute", action="store_true", help="Actually send guarded input events through adb.")
    parser.add_argument("--summary-only", action="store_true", help="Print a compact result summary instead of full event details.")
    parser.add_argument("--quiet", action="store_true", help="Suppress step-by-step stderr progress logs.")
    parser.add_argument("--observe-screens", action="store_true", help="Save screenshot-first local observation logs for each guarded step.")
    parser.add_argument("--observation-dir", type=Path, default=Path("observations"))
    parser.add_argument("--observation-level", type=int, choices=[0, 1, 2], default=0)
    parser.add_argument("--observation-max-candidates", type=int, default=35)
    parser.add_argument("--allow-existing-output", action="store_true", help="Allow writing into existing pull/archive output directories.")
    parser.add_argument(
        "--skip-note-fingerprint",
        action="append",
        default=[],
        help="Do not select a visible note card with this local SHA-256 content-desc fingerprint.",
    )
    parser.add_argument("--skip-note-state", type=Path, help="Read skip-note fingerprints from a visible-batch state JSON.")
    parser.add_argument("--run-id", help="Run id expected inside --skip-note-state.")
    args = parser.parse_args(argv)
    if args.mapping_path and not args.pull_to:
        raise SystemExit("Refusing action: --mapping-path requires --pull-to")
    if args.archive_output and not args.pull_to:
        raise SystemExit("Refusing action: --archive-output requires --pull-to")
    if args.skip_note_state and not args.run_id:
        raise SystemExit("Refusing action: --skip-note-state requires --run-id")

    skip_note_fingerprints = set(args.skip_note_fingerprint)
    if args.skip_note_state:
        state = load_state(args.skip_note_state, run_id=args.run_id, folder_path=args.allowed_path)
        skip_note_fingerprints.update(state.get("seen_fingerprints") or [])

    config = DriverConfig(
        allowed_path=args.allowed_path,
        destination=args.destination,
        out_dir=args.out_dir,
        label=args.label,
        execute=args.execute,
        select_count=args.select_count,
        select_all=args.select_all,
        wait_seconds=args.wait_seconds,
        pull_to=args.pull_to,
        mapping_path=args.mapping_path,
        archive_output=args.archive_output,
        observation_dir=args.observation_dir if args.observe_screens else None,
        observation_level=args.observation_level,
        observation_max_candidates=args.observation_max_candidates,
        allow_existing_output=args.allow_existing_output,
        deselect_visible_subfolders_after_select_all=args.deselect_visible_subfolders_after_select_all,
        selection_probe_only=args.selection_probe_only,
        deselect_scroll_attempts=args.deselect_scroll_attempts,
        deselect_max_taps=args.deselect_max_taps,
        skip_note_fingerprints=frozenset(skip_note_fingerprints),
        export_format=args.export_format,
        allow_partial_export=args.allow_partial_export,
    )
    set_quiet(args.quiet)
    result = run_guarded_export(config)
    if args.summary_only:
        result = summarize_export_result(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
