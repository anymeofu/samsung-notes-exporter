from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


NOTES_PACKAGE = "com.samsung.android.app.notes"
MYFILES_PACKAGE = "com.sec.android.app.myfiles"
FOLDERPATH_TEXT_ID = f"{NOTES_PACKAGE}:id/folderpath_text"
NOTE_CARD_ID = f"{NOTES_PACKAGE}:id/root_cardview"
SUBFOLDER_ITEM_PREFIX = f"{NOTES_PACKAGE}:id/sub_folder_list_item"
SUBFOLDER_EXPAND_ID = f"{NOTES_PACKAGE}:id/expand_bar_layout"
SUBFOLDER_SELECTION_CHECKBOX_ID = f"{NOTES_PACKAGE}:id/inflate_checkbox"
SELECT_ALL_CONTAINER_ID = f"{NOTES_PACKAGE}:id/checkbox_withtext"
CHECK_INFO_ID = f"{NOTES_PACKAGE}:id/check_info"
DANGEROUS_IDS = {
    f"{NOTES_PACKAGE}:id/action_delete",
    f"{NOTES_PACKAGE}:id/action_move",
    f"{NOTES_PACKAGE}:id/action_lock",
}
SAFE_TAP_IDS = {
    f"{NOTES_PACKAGE}:id/bottom_overflow",
    f"{NOTES_PACKAGE}:id/action_done",
}
SAFE_MENU_TEXTS = {"파일로 저장", "삼성 노트 파일", "텍스트 파일"}
SAFE_MYFILES_TEXTS = {"Documents", "Download"}
SAFE_MYFILES_IDS = {f"{MYFILES_PACKAGE}:id/menu_done"}
FILENAME_DIALOG_TITLE_ID = f"{NOTES_PACKAGE}:id/alertTitle"
FILENAME_INPUT_ID = f"{NOTES_PACKAGE}:id/text_input_dialog"
ANDROID_SAVE_BUTTON_ID = "android:id/button1"
UNSAFE_FILENAME_CHARS = set('/\\\x00')


@dataclass(frozen=True)
class Bounds:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def center(self) -> tuple[int, int]:
        return ((self.left + self.right) // 2, (self.top + self.bottom) // 2)


def parse_bounds(value: str) -> Bounds | None:
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", value or "")
    if not match:
        return None
    return Bounds(*(int(part) for part in match.groups()))


def clean_button_text(value: str) -> str:
    text = value.strip()
    text = re.sub(r",\s*버튼$", "", text)
    return text.strip()


def is_safe_export_filename(filename: str) -> bool:
    stripped = filename.strip()
    if not stripped or stripped in {".", ".."}:
        return False
    if any(char in UNSAFE_FILENAME_CHARS for char in stripped):
        return False
    if any(ord(char) < 32 for char in stripped):
        return False
    return True


def iter_nodes(root: ET.Element):
    yield from root.iter("node")


def load_xml(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


def extract_folder_path(root: ET.Element) -> str:
    parts: list[str] = []
    for node in iter_nodes(root):
        if node.attrib.get("resource-id") != FOLDERPATH_TEXT_ID:
            continue
        text = node.attrib.get("text") or node.attrib.get("content-desc") or ""
        cleaned = clean_button_text(text)
        if cleaned:
            parts.append(cleaned)
    return "/".join(parts)


def extract_note_cards(root: ET.Element) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for node in iter_nodes(root):
        if node.attrib.get("resource-id") != NOTE_CARD_ID:
            continue
        bounds = parse_bounds(node.attrib.get("bounds", ""))
        if not bounds:
            continue
        content_desc = node.attrib.get("content-desc", "")
        fingerprint = hashlib.sha256(content_desc.encode("utf-8")).hexdigest() if content_desc else None
        cards.append(
            {
                "bounds": node.attrib.get("bounds"),
                "center": list(bounds.center),
                "selected": node.attrib.get("selected") == "true",
                "checked": node.attrib.get("checked") == "true",
                "clickable": node.attrib.get("clickable") == "true",
                "long_clickable": node.attrib.get("long-clickable") == "true",
                "fingerprint": fingerprint,
            }
        )
    return cards


def extract_selection_info(root: ET.Element) -> dict[str, Any]:
    selected_count: int | None = None
    text = ""
    for node in iter_nodes(root):
        if node.attrib.get("resource-id") != CHECK_INFO_ID:
            continue
        text = node.attrib.get("text", "")
        match = re.search(r"(\d+)\s*개\s*선택됨", text)
        if match:
            selected_count = int(match.group(1))
        elif re.fullmatch(r"\s*\d+\s*", text):
            selected_count = int(text.strip())
        break
    return {"text": text, "selected_count": selected_count}


def extract_visible_folder_note_counts(root: ET.Element) -> dict[str, int | None]:
    folder_count: int | None = None
    note_count: int | None = None
    for node in iter_nodes(root):
        value = " ".join(
            part for part in (node.attrib.get("text", ""), node.attrib.get("content-desc", "")) if part
        )
        if not value:
            continue
        folder_match = re.search(r"폴더\s*(\d+)\s*개", value)
        note_match = re.search(r"노트\s*(\d+)\s*개", value)
        if folder_match:
            folder_count = int(folder_match.group(1))
        if note_match:
            note_count = int(note_match.group(1))
        if folder_count is not None and note_count is not None:
            break
    return {"folder_count": folder_count, "note_count": note_count}


def extract_subfolders(root: ET.Element) -> list[dict[str, Any]]:
    subfolders: list[dict[str, Any]] = []
    for node in iter_nodes(root):
        resource_id = node.attrib.get("resource-id", "")
        if not re.fullmatch(rf"{re.escape(SUBFOLDER_ITEM_PREFIX)}\d+", resource_id):
            continue
        bounds = parse_bounds(node.attrib.get("bounds", ""))
        if not bounds:
            continue
        title = ""
        for child in node.iter("node"):
            if child.attrib.get("resource-id") != f"{NOTES_PACKAGE}:id/title":
                continue
            candidate = child.attrib.get("text", "").strip()
            if candidate:
                title = candidate
                break
        if not title:
            continue
        subfolders.append(
            {
                "title": title,
                "resource_id": resource_id,
                "content_desc": node.attrib.get("content-desc", ""),
                "bounds": node.attrib.get("bounds"),
                "center": list(bounds.center),
                "clickable": node.attrib.get("clickable") == "true",
                "enabled": node.attrib.get("enabled") == "true",
            }
        )
    subfolders.sort(key=lambda item: (item["center"][1], item["center"][0], item["title"]))
    return subfolders


def extract_selected_subfolder_checkboxes(root: ET.Element) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for node in iter_nodes(root):
        resource_id = node.attrib.get("resource-id", "")
        if not re.fullmatch(rf"{re.escape(SUBFOLDER_ITEM_PREFIX)}\d+", resource_id):
            continue
        title = ""
        checkbox_target: dict[str, Any] | None = None
        for child in node.iter("node"):
            if child.attrib.get("resource-id") == f"{NOTES_PACKAGE}:id/title":
                candidate = child.attrib.get("text", "").strip()
                if candidate:
                    title = candidate
            if child.attrib.get("resource-id") != SUBFOLDER_SELECTION_CHECKBOX_ID:
                continue
            if child.attrib.get("checked") != "true":
                continue
            bounds = parse_bounds(child.attrib.get("bounds", ""))
            if not bounds:
                continue
            checkbox_target = {
                "title": title,
                "resource_id": resource_id,
                "checkbox_resource_id": SUBFOLDER_SELECTION_CHECKBOX_ID,
                "bounds": child.attrib.get("bounds"),
                "center": list(bounds.center),
                "enabled": child.attrib.get("enabled") == "true",
            }
        if checkbox_target:
            checkbox_target["title"] = title
            selected.append(checkbox_target)
    selected.sort(key=lambda item: (item["center"][1], item["center"][0], item["title"]))
    return selected


def extract_subfolder_expand(root: ET.Element) -> dict[str, Any]:
    matches = find_nodes_by_resource_id(root, SUBFOLDER_EXPAND_ID)
    if not matches:
        return {"available": False}
    if len(matches) > 1:
        return {"available": True, "ambiguous": True, "count": len(matches)}
    target = matches[0]
    target["available"] = True
    target["ambiguous"] = False
    label = f"{target.get('text') or ''} {target.get('content_desc') or ''}".strip()
    target["label"] = label
    target["is_show_all"] = "모두 보기" in label
    target["is_collapse"] = "접기" in label
    return target


def find_nodes_by_resource_id(root: ET.Element, resource_id: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for node in iter_nodes(root):
        if node.attrib.get("resource-id") != resource_id:
            continue
        bounds = parse_bounds(node.attrib.get("bounds", ""))
        if not bounds:
            continue
        matches.append(
            {
                "resource_id": resource_id,
                "class": node.attrib.get("class"),
                "text": node.attrib.get("text"),
                "content_desc": node.attrib.get("content-desc"),
                "bounds": node.attrib.get("bounds"),
                "center": list(bounds.center),
                "clickable": node.attrib.get("clickable") == "true",
                "enabled": node.attrib.get("enabled") == "true",
            }
        )
    return matches


def find_nodes_by_text(root: ET.Element, text: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for node in iter_nodes(root):
        if node.attrib.get("text") != text:
            continue
        bounds = parse_bounds(node.attrib.get("bounds", ""))
        if not bounds:
            continue
        matches.append(
            {
                "text": text,
                "resource_id": node.attrib.get("resource-id"),
                "class": node.attrib.get("class"),
                "content_desc": node.attrib.get("content-desc"),
                "bounds": node.attrib.get("bounds"),
                "center": list(bounds.center),
                "clickable": node.attrib.get("clickable") == "true",
                "enabled": node.attrib.get("enabled") == "true",
            }
        )
    return matches


def filename_dialog_details(root: ET.Element) -> dict[str, Any]:
    title_matches = find_nodes_by_resource_id(root, FILENAME_DIALOG_TITLE_ID)
    input_matches = find_nodes_by_resource_id(root, FILENAME_INPUT_ID)
    save_matches = find_nodes_by_resource_id(root, ANDROID_SAVE_BUTTON_ID)
    return {
        "title_matches": title_matches,
        "input_matches": input_matches,
        "save_matches": save_matches,
    }


def resource_ids(root: ET.Element) -> set[str]:
    return {node.attrib.get("resource-id", "") for node in iter_nodes(root) if node.attrib.get("resource-id")}


def packages(root: ET.Element) -> set[str]:
    return {node.attrib.get("package", "") for node in iter_nodes(root) if node.attrib.get("package")}


def is_allowed_path(folder_path: str, allowed_paths: list[str]) -> bool:
    for allowed_path in allowed_paths:
        allowed_root = allowed_path.rstrip("/")
        if allowed_root == "폴더" and folder_path == "":
            return True
        if folder_path == allowed_root or folder_path.startswith(allowed_root + "/"):
            return True
    return False


def assert_allowed_path(folder_path: str, allowed_paths: list[str]) -> None:
    if not is_allowed_path(folder_path, allowed_paths):
        allowed = ", ".join(allowed_paths)
        raise SystemExit(f"Refusing action: folder_path={folder_path!r} not in allowed paths: {allowed}")


def adb_path() -> str:
    candidates = [
        "adb",
        str(Path.home() / "Library/Android/sdk/platform-tools/adb"),
        "/opt/homebrew/bin/adb",
        "/usr/local/bin/adb",
    ]
    for candidate in candidates:
        try:
            subprocess.run([candidate, "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except (OSError, subprocess.CalledProcessError):
            continue
        return candidate
    raise SystemExit("adb not found")


def long_press(x: int, y: int, duration_ms: int) -> None:
    subprocess.run([adb_path(), "shell", "input", "swipe", str(x), str(y), str(x), str(y), str(duration_ms)], check=True)


def tap(x: int, y: int) -> None:
    subprocess.run([adb_path(), "shell", "input", "tap", str(x), str(y)], check=True)


def summarize_xml_root(root: ET.Element, allowed_paths: list[str] | None = None) -> dict[str, Any]:
    allowed_paths = allowed_paths or []
    folder_path = extract_folder_path(root)
    ids = resource_ids(root)
    visible_packages = packages(root)
    note_cards = extract_note_cards(root)
    selection_info = extract_selection_info(root)
    visible_counts = extract_visible_folder_note_counts(root)
    subfolders = extract_subfolders(root)
    selected_subfolder_checkboxes = extract_selected_subfolder_checkboxes(root)
    subfolder_expand = extract_subfolder_expand(root)
    return {
        "packages": sorted(visible_packages),
        "is_samsung_notes_visible": NOTES_PACKAGE in visible_packages,
        "folder_path": folder_path,
        "allowed": is_allowed_path(folder_path, allowed_paths) if allowed_paths else None,
        "allowed_paths": allowed_paths,
        "note_card_count": len(note_cards),
        "note_cards": note_cards,
        "subfolder_count": len(subfolders),
        "subfolders": subfolders,
        "selected_subfolder_checkboxes": selected_subfolder_checkboxes,
        "selected_subfolder_count": len(selected_subfolder_checkboxes),
        "subfolder_expand": subfolder_expand,
        "selection_info": selection_info,
        "visible_counts": visible_counts,
        "bottom_overflow_available": f"{NOTES_PACKAGE}:id/bottom_overflow" in ids,
        "dangerous_actions_present": sorted(ids & DANGEROUS_IDS),
    }


def summarize(xml_path: Path, allowed_paths: list[str]) -> dict[str, Any]:
    summary = summarize_xml_root(load_xml(xml_path), allowed_paths)
    summary["xml"] = str(xml_path)
    return summary


def selected_subfolder_checkbox_tap_plan(summary: dict[str, Any], *, max_count: int = 50) -> list[dict[str, Any]]:
    targets = list(summary.get("selected_subfolder_checkboxes") or [])
    if not targets:
        raise SystemExit("Refusing action: no selected subfolder checkboxes found")
    if len(targets) > max_count:
        raise SystemExit(f"Refusing action: selected subfolder checkbox count {len(targets)} exceeds max {max_count}")
    for target in targets:
        if not target.get("enabled"):
            raise SystemExit(f"Refusing action: selected subfolder checkbox target disabled: {target}")
    return targets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guarded Samsung Notes UI helpers for test folders.")
    parser.add_argument("--xml", required=True, type=Path)
    parser.add_argument("--allowed-path", action="append", required=True)
    parser.add_argument("--json", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("summarize")

    tap_first = subparsers.add_parser("long-press-first-note")
    tap_first.add_argument("--execute", action="store_true", help="Actually send the long press through adb.")
    tap_first.add_argument("--duration-ms", type=int, default=900)

    tap_resource = subparsers.add_parser("tap-resource")
    tap_resource.add_argument("--resource-id", required=True)
    tap_resource.add_argument("--execute", action="store_true", help="Actually send the tap through adb.")

    tap_text = subparsers.add_parser("tap-menu-text")
    tap_text.add_argument("--text", required=True)
    tap_text.add_argument("--execute", action="store_true", help="Actually send the tap through adb.")

    tap_myfiles_text = subparsers.add_parser("tap-myfiles-text")
    tap_myfiles_text.add_argument("--text", required=True)
    tap_myfiles_text.add_argument("--execute", action="store_true", help="Actually send the tap through adb.")

    tap_myfiles_resource = subparsers.add_parser("tap-myfiles-resource")
    tap_myfiles_resource.add_argument("--resource-id", required=True)
    tap_myfiles_resource.add_argument("--execute", action="store_true", help="Actually send the tap through adb.")

    save_dialog = subparsers.add_parser("tap-filename-save")
    save_dialog.add_argument("--expected-prefix", default="Notes_")
    save_dialog.add_argument("--allow-any-safe-filename", action="store_true")
    save_dialog.add_argument("--execute", action="store_true", help="Actually send the tap through adb.")

    deselect_subfolders = subparsers.add_parser("tap-selected-subfolder-checkboxes")
    deselect_subfolders.add_argument("--execute", action="store_true", help="Actually tap selected subfolder checkbox centers through adb.")
    deselect_subfolders.add_argument("--max-count", type=int, default=50)
    deselect_subfolders.add_argument("--tap-delay-seconds", type=float, default=0.1)

    args = parser.parse_args(argv)
    summary = summarize(args.xml, args.allowed_path)
    if args.command == "summarize":
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    if args.command == "long-press-first-note":
        if not summary["is_samsung_notes_visible"]:
            raise SystemExit(f"Refusing action: Samsung Notes is not visible. Packages: {summary['packages']}")
        assert_allowed_path(summary["folder_path"], args.allowed_path)
        if summary["dangerous_actions_present"]:
            raise SystemExit(f"Refusing action: dangerous selection actions already present: {summary['dangerous_actions_present']}")
        if not summary["note_cards"]:
            raise SystemExit("Refusing action: no note cards found")
        x, y = summary["note_cards"][0]["center"]
        result = {
            "action": "long_press_first_note",
            "folder_path": summary["folder_path"],
            "target": {"x": x, "y": y, "duration_ms": args.duration_ms},
            "executed": bool(args.execute),
        }
        if args.execute:
            long_press(x, y, args.duration_ms)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "tap-resource":
        if not summary["is_samsung_notes_visible"]:
            raise SystemExit(f"Refusing action: Samsung Notes is not visible. Packages: {summary['packages']}")
        assert_allowed_path(summary["folder_path"], args.allowed_path)
        if args.resource_id in DANGEROUS_IDS or args.resource_id not in SAFE_TAP_IDS:
            raise SystemExit(f"Refusing action: resource-id is not in safe tap allow-list: {args.resource_id}")
        root = load_xml(args.xml)
        matches = find_nodes_by_resource_id(root, args.resource_id)
        if len(matches) != 1:
            raise SystemExit(f"Refusing action: expected exactly one {args.resource_id}, found {len(matches)}")
        target = matches[0]
        if not target["enabled"]:
            raise SystemExit(f"Refusing action: target is disabled: {target}")
        x, y = target["center"]
        result = {
            "action": "tap_resource",
            "folder_path": summary["folder_path"],
            "target": target,
            "executed": bool(args.execute),
        }
        if args.execute:
            tap(x, y)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "tap-selected-subfolder-checkboxes":
        if not summary["is_samsung_notes_visible"]:
            raise SystemExit(f"Refusing action: Samsung Notes is not visible. Packages: {summary['packages']}")
        assert_allowed_path(summary["folder_path"], args.allowed_path)
        targets = selected_subfolder_checkbox_tap_plan(summary, max_count=args.max_count)
        result = {
            "action": "tap_selected_subfolder_checkboxes",
            "folder_path": summary["folder_path"],
            "target_count": len(targets),
            "targets": targets,
            "executed": bool(args.execute),
        }
        if args.execute:
            for target in targets:
                x, y = target["center"]
                tap(x, y)
                if args.tap_delay_seconds > 0:
                    time.sleep(args.tap_delay_seconds)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "tap-menu-text":
        if not summary["is_samsung_notes_visible"]:
            raise SystemExit(f"Refusing action: Samsung Notes is not visible. Packages: {summary['packages']}")
        if args.text not in SAFE_MENU_TEXTS:
            raise SystemExit(f"Refusing action: menu text is not in safe allow-list: {args.text}")
        root = load_xml(args.xml)
        matches = find_nodes_by_text(root, args.text)
        if len(matches) != 1:
            raise SystemExit(f"Refusing action: expected exactly one menu item {args.text!r}, found {len(matches)}")
        target = matches[0]
        if not target["enabled"]:
            raise SystemExit(f"Refusing action: target is disabled: {target}")
        x, y = target["center"]
        result = {
            "action": "tap_menu_text",
            "target": target,
            "executed": bool(args.execute),
        }
        if args.execute:
            tap(x, y)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "tap-myfiles-text":
        if MYFILES_PACKAGE not in summary["packages"]:
            raise SystemExit(f"Refusing action: My Files is not visible. Packages: {summary['packages']}")
        if args.text not in SAFE_MYFILES_TEXTS:
            raise SystemExit(f"Refusing action: My Files text is not in safe allow-list: {args.text}")
        root = load_xml(args.xml)
        matches = find_nodes_by_text(root, args.text)
        if len(matches) != 1:
            raise SystemExit(f"Refusing action: expected exactly one My Files item {args.text!r}, found {len(matches)}")
        target = matches[0]
        if not target["enabled"]:
            raise SystemExit(f"Refusing action: target is disabled: {target}")
        x, y = target["center"]
        result = {
            "action": "tap_myfiles_text",
            "target": target,
            "executed": bool(args.execute),
        }
        if args.execute:
            tap(x, y)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "tap-myfiles-resource":
        if MYFILES_PACKAGE not in summary["packages"]:
            raise SystemExit(f"Refusing action: My Files is not visible. Packages: {summary['packages']}")
        if args.resource_id not in SAFE_MYFILES_IDS:
            raise SystemExit(f"Refusing action: My Files resource-id is not in safe allow-list: {args.resource_id}")
        root = load_xml(args.xml)
        matches = find_nodes_by_resource_id(root, args.resource_id)
        if len(matches) != 1:
            raise SystemExit(f"Refusing action: expected exactly one {args.resource_id}, found {len(matches)}")
        target = matches[0]
        if not target["enabled"]:
            raise SystemExit(f"Refusing action: target is disabled: {target}")
        x, y = target["center"]
        result = {
            "action": "tap_myfiles_resource",
            "target": target,
            "executed": bool(args.execute),
        }
        if args.execute:
            tap(x, y)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "tap-filename-save":
        if not summary["is_samsung_notes_visible"]:
            raise SystemExit(f"Refusing action: Samsung Notes is not visible. Packages: {summary['packages']}")
        root = load_xml(args.xml)
        details = filename_dialog_details(root)
        title_matches = details["title_matches"]
        input_matches = details["input_matches"]
        save_matches = details["save_matches"]
        if len(title_matches) != 1 or title_matches[0].get("text") != "파일 이름":
            raise SystemExit("Refusing action: filename dialog title was not found")
        if len(input_matches) != 1:
            raise SystemExit(f"Refusing action: expected one filename input, found {len(input_matches)}")
        filename = input_matches[0].get("text") or ""
        if args.allow_any_safe_filename:
            if not is_safe_export_filename(filename):
                raise SystemExit(f"Refusing action: filename {filename!r} is not a safe export filename")
        elif not filename.startswith(args.expected_prefix):
            raise SystemExit(f"Refusing action: filename {filename!r} does not start with {args.expected_prefix!r}")
        if len(save_matches) != 1 or save_matches[0].get("text") != "저장":
            raise SystemExit(f"Refusing action: expected one 저장 button, found {len(save_matches)}")
        target = save_matches[0]
        if not target["enabled"]:
            raise SystemExit(f"Refusing action: target is disabled: {target}")
        x, y = target["center"]
        result = {
            "action": "tap_filename_save",
            "filename": filename,
            "target": target,
            "executed": bool(args.execute),
        }
        if args.execute:
            tap(x, y)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
