from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import struct
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import ui_guard


REMOTE_XML = "/sdcard/window_dump.xml"
REMOTE_PNG = "/sdcard/screen.png"
DEFAULT_SCHEMA_CACHE = Path("screen_schemas/cache.json")


@dataclass(frozen=True)
class ObservationPaths:
    screenshot: Path
    xml: Path
    metadata: Path
    annotated_svg: Path


def adb(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    command_parts = [ui_guard.adb_path(), *args]
    kwargs: dict[str, Any] = {"check": True, "text": True}
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    try:
        return subprocess.run(command_parts, **kwargs)
    except subprocess.CalledProcessError as exc:
        output = ""
        for stream in (exc.stderr, exc.stdout):
            if isinstance(stream, str) and stream.strip():
                output = stream.strip()
                break
        detail = f": {output}" if output else ""
        command = " ".join(command_parts)
        raise SystemExit(f"Refusing observation: adb command failed with exit {exc.returncode}: {command}{detail}") from exc


def safe_label(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_.-]+", "_", value).strip("_")
    return cleaned or "screen"


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not a PNG screenshot: {path}")
    return struct.unpack(">II", header[16:24])


def short_text(value: str | None, limit: int = 40) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def is_useful_resource(resource_id: str) -> bool:
    useful_suffixes = {
        "folderpath_text",
        "root_cardview",
        "sub_folder_list_item",
        "expand_bar_layout",
        "checkbox_withtext",
        "bottom_overflow",
        "action_done",
        "menu_done",
        "alertTitle",
        "text_input_dialog",
    }
    return any(resource_id.endswith(suffix) for suffix in useful_suffixes)


def node_role(class_name: str) -> str:
    if not class_name:
        return "node"
    return class_name.rsplit(".", 1)[-1]


def point_in_bounds(point: list[int] | tuple[int, int], bounds: list[int]) -> bool:
    x, y = point
    left, top, right, bottom = bounds
    return left <= x <= right and top <= y <= bottom


def compact_candidates(root: ET.Element, *, max_candidates: int = 35) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_bounds: set[tuple[str, str, str]] = set()
    grouped_bounds: list[list[int]] = []

    for subfolder in ui_guard.extract_subfolders(root):
        left, top, right, bottom = [int(part) for part in re.findall(r"\d+", subfolder["bounds"])]
        grouped_bounds.append([left, top, right, bottom])
        candidates.append(
            {
                "id": f"c{len(candidates) + 1:03d}",
                "bounds": [left, top, right, bottom],
                "center": subfolder["center"],
                "role": "subfolder",
                "text": short_text(subfolder["title"]),
                "content_desc": short_text(subfolder.get("content_desc")),
                "states": ["clickable"] if subfolder.get("enabled") else [],
                "resource_id": subfolder.get("resource_id"),
            }
        )
        if len(candidates) >= max_candidates:
            return candidates

    for card in ui_guard.extract_note_cards(root):
        left, top, right, bottom = [int(part) for part in re.findall(r"\d+", card["bounds"])]
        grouped_bounds.append([left, top, right, bottom])
        states = ["clickable"]
        if card.get("long_clickable"):
            states.append("long_clickable")
        if card.get("checked"):
            states.append("checked")
        candidates.append(
            {
                "id": f"c{len(candidates) + 1:03d}",
                "bounds": [left, top, right, bottom],
                "center": card["center"],
                "role": "note_card",
                "states": states,
                "resource_id": ui_guard.NOTE_CARD_ID,
            }
        )
        if len(candidates) >= max_candidates:
            return candidates

    for node in ui_guard.iter_nodes(root):
        bounds_value = node.attrib.get("bounds", "")
        bounds = ui_guard.parse_bounds(bounds_value)
        if not bounds:
            continue
        text = short_text(node.attrib.get("text"))
        content_desc = short_text(node.attrib.get("content-desc"))
        resource_id = node.attrib.get("resource-id", "")
        clickable = node.attrib.get("clickable") == "true"
        editable = node.attrib.get("class") == "android.widget.EditText"
        scrollable = node.attrib.get("scrollable") == "true"
        actionable = clickable or editable or scrollable
        labeled = bool(text or content_desc)
        useful = is_useful_resource(resource_id)
        if not (actionable or labeled or useful):
            continue
        center = list(bounds.center)
        if any(point_in_bounds(center, parent) for parent in grouped_bounds):
            continue
        key = (bounds_value, text, content_desc)
        if key in seen_bounds:
            continue
        seen_bounds.add(key)
        candidate: dict[str, Any] = {
            "id": f"c{len(candidates) + 1:03d}",
            "bounds": [bounds.left, bounds.top, bounds.right, bounds.bottom],
            "center": center,
            "role": node_role(node.attrib.get("class", "")),
        }
        if text:
            candidate["text"] = text
        if content_desc and content_desc != text:
            candidate["content_desc"] = content_desc
        states = []
        if clickable:
            states.append("clickable")
        if editable:
            states.append("editable")
        if scrollable:
            states.append("scrollable")
        if states:
            candidate["states"] = states
        if resource_id and (useful or actionable):
            candidate["resource_id"] = resource_id
        candidates.append(candidate)
        if len(candidates) >= max_candidates:
            break
    return candidates


def structural_summary(root: ET.Element) -> dict[str, Any]:
    summary = ui_guard.summarize_xml_root(root)
    buttons = []
    editable = []
    scrollable = []
    for item in compact_candidates(root, max_candidates=120):
        states = set(item.get("states", []))
        if "editable" in states:
            editable.append(item)
        elif "scrollable" in states:
            scrollable.append(item)
        elif "clickable" in states or item.get("text") or item.get("content_desc"):
            buttons.append(item)
    return {
        "packages": summary["packages"],
        "folder_path": summary["folder_path"],
        "note_card_count": summary["note_card_count"],
        "subfolder_count": summary["subfolder_count"],
        "selection": summary["selection_info"],
        "dangerous_actions_present": summary["dangerous_actions_present"],
        "visible_buttons": buttons[:30],
        "editable_fields": editable[:10],
        "scrollable_regions": scrollable[:10],
    }


def fingerprint_observation(
    *,
    package_activity: str,
    screen_size: tuple[int, int],
    root: ET.Element,
    candidates: list[dict[str, Any]],
) -> str:
    parts = [
        package_activity,
        f"{screen_size[0]}x{screen_size[1]}",
        ui_guard.extract_folder_path(root),
        ",".join(sorted(ui_guard.packages(root))),
    ]
    for candidate in candidates[:25]:
        parts.append("|".join(str(candidate.get(key, "")) for key in ("role", "text", "content_desc", "resource_id")))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def current_package_activity() -> str:
    result = adb(["shell", "dumpsys", "window"], capture=True)
    for line in result.stdout.splitlines():
        if "mCurrentFocus=" in line or "mFocusedApp=" in line:
            return line.strip()
    return "unknown"


def capture_observation(label: str, out_dir: Path) -> tuple[ObservationPaths, ET.Element, tuple[int, int], str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = f"{stamp}_{safe_label(label)}"
    paths = ObservationPaths(
        screenshot=out_dir / f"{base}.png",
        xml=out_dir / f"{base}.xml",
        metadata=out_dir / f"{base}.metadata.json",
        annotated_svg=out_dir / f"{base}.annotated.svg",
    )
    adb(["shell", "screencap", "-p", REMOTE_PNG], capture=True)
    adb(["pull", REMOTE_PNG, str(paths.screenshot)], capture=True)
    adb(["shell", "uiautomator", "dump", REMOTE_XML], capture=True)
    adb(["pull", REMOTE_XML, str(paths.xml)], capture=True)
    root = ui_guard.load_xml(paths.xml)
    size = png_size(paths.screenshot)
    return paths, root, size, current_package_activity()


def capture_screenshot(path: Path) -> tuple[int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    adb(["shell", "screencap", "-p", REMOTE_PNG], capture=True)
    adb(["pull", REMOTE_PNG, str(path)], capture=True)
    return png_size(path)


def compose_observation(
    *,
    paths: ObservationPaths,
    root: ET.Element,
    screen_size: tuple[int, int],
    package_activity: str,
    level: int,
    max_candidates: int,
    schema_cache_path: Path,
    last_action: str | None,
    task_state: str | None,
) -> dict[str, Any]:
    candidates = compact_candidates(root, max_candidates=max_candidates)
    fingerprint = fingerprint_observation(
        package_activity=package_activity,
        screen_size=screen_size,
        root=root,
        candidates=candidates,
    )
    write_annotated_svg(paths, screen_size, candidates[:40])
    observation: dict[str, Any] = {
        "mode": "screenshot_first_compact",
        "escalation_level": level,
        "screen_fingerprint": fingerprint,
        "screen_size": list(screen_size),
        "package_activity": package_activity,
        "screenshot": str(paths.screenshot),
        "annotated_screenshot": str(paths.annotated_svg),
        "metadata": str(paths.metadata),
        "local_raw_ui_dump": str(paths.xml),
        "raw_ui_dump_sent_to_model": False,
        "last_action": last_action,
        "task_state": task_state,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    if level >= 1:
        observation["structural_summary"] = structural_summary(root)
    paths.metadata.write_text(json.dumps(observation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_schema_cache(schema_cache_path, fingerprint, observation)
    return observation


def build_observation_from_xml(
    *,
    label: str,
    out_dir: Path,
    xml_path: Path,
    level: int,
    max_candidates: int,
    schema_cache_path: Path = DEFAULT_SCHEMA_CACHE,
    last_action: str | None = None,
    task_state: str | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = safe_label(label)
    paths = ObservationPaths(
        screenshot=out_dir / f"{base}.png",
        xml=xml_path,
        metadata=out_dir / f"{base}.metadata.json",
        annotated_svg=out_dir / f"{base}.annotated.svg",
    )
    screen_size = capture_screenshot(paths.screenshot)
    root = ui_guard.load_xml(xml_path)
    return compose_observation(
        paths=paths,
        root=root,
        screen_size=screen_size,
        package_activity=current_package_activity(),
        level=level,
        max_candidates=max_candidates,
        schema_cache_path=schema_cache_path,
        last_action=last_action,
        task_state=task_state,
    )


def write_annotated_svg(paths: ObservationPaths, screen_size: tuple[int, int], candidates: list[dict[str, Any]]) -> None:
    width, height = screen_size
    image_href = html.escape(paths.screenshot.name)
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'  <image href="{image_href}" width="{width}" height="{height}" />',
    ]
    for candidate in candidates:
        left, top, right, bottom = candidate["bounds"]
        label = html.escape(candidate["id"])
        lines.append(
            f'  <rect x="{left}" y="{top}" width="{right-left}" height="{bottom-top}" '
            'fill="none" stroke="#ff3b30" stroke-width="3" />'
        )
        lines.append(
            f'  <rect x="{left}" y="{max(0, top - 28)}" width="62" height="28" fill="#ff3b30" opacity="0.9" />'
        )
        lines.append(
            f'  <text x="{left + 6}" y="{max(18, top - 8)}" '
            'font-family="monospace" font-size="20" fill="white">'
            f"{label}</text>"
        )
    lines.append("</svg>")
    paths.annotated_svg.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_schema_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def update_schema_cache(path: Path, fingerprint: str, observation: dict[str, Any]) -> None:
    cache = load_schema_cache(path)
    cache.setdefault(fingerprint, {
        "fingerprint": fingerprint,
        "package_activity": observation["package_activity"],
        "visual_description": "Unlabeled observed screen. Fill in after first review.",
        "key_actionable_regions": observation["candidates"][:20],
        "expected_buttons": [],
        "scroll_behavior": "unknown",
        "known_failure_modes": [],
        "safe_next_action_rules": [],
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_observation(
    *,
    label: str,
    out_dir: Path,
    level: int,
    max_candidates: int,
    schema_cache_path: Path,
    last_action: str | None,
    task_state: str | None,
) -> dict[str, Any]:
    paths, root, screen_size, package_activity = capture_observation(label, out_dir)
    return compose_observation(
        paths=paths,
        root=root,
        screen_size=screen_size,
        package_activity=package_activity,
        level=level,
        max_candidates=max_candidates,
        schema_cache_path=schema_cache_path,
        last_action=last_action,
        task_state=task_state,
    )


def terse_candidate(candidate: dict[str, Any]) -> str:
    label = candidate.get("text") or candidate.get("content_desc") or candidate.get("resource_id") or ""
    label = short_text(str(label), 28)
    return f"{candidate['id']} {candidate.get('role')} {label!r} {candidate.get('bounds')}"


def summarize_for_stdout(observation: dict[str, Any], *, candidate_limit: int = 12) -> dict[str, Any]:
    return {
        "mode": observation["mode"],
        "screen_fingerprint": observation["screen_fingerprint"],
        "screen_size": observation["screen_size"],
        "package_activity": observation["package_activity"],
        "screenshot": observation["screenshot"],
        "annotated_screenshot": observation["annotated_screenshot"],
        "metadata": observation["metadata"],
        "raw_ui_dump_sent_to_model": False,
        "candidate_count": observation["candidate_count"],
        "candidate_preview": [
            terse_candidate(candidate)
            for candidate in observation.get("candidates", [])[:candidate_limit]
        ],
        "last_action": observation.get("last_action"),
        "task_state": observation.get("task_state"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Screenshot-first compact Android UI observer.")
    parser.add_argument("--label", default="screen")
    parser.add_argument("--out-dir", type=Path, default=Path("observations"))
    parser.add_argument("--level", type=int, choices=[0, 1, 2], default=0)
    parser.add_argument("--max-candidates", type=int, default=60)
    parser.add_argument("--schema-cache", type=Path, default=DEFAULT_SCHEMA_CACHE)
    parser.add_argument("--last-action")
    parser.add_argument("--task-state")
    parser.add_argument(
        "--print-mode",
        choices=["summary", "compact"],
        default="summary",
        help="summary prints a small preview; compact prints all compact candidates.",
    )
    args = parser.parse_args(argv)
    observation = build_observation(
        label=args.label,
        out_dir=args.out_dir,
        level=args.level,
        max_candidates=args.max_candidates,
        schema_cache_path=args.schema_cache,
        last_action=args.last_action,
        task_state=args.task_state,
    )
    output = observation if args.print_mode == "compact" else summarize_for_stdout(observation)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
