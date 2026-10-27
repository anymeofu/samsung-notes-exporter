from __future__ import annotations

import argparse
import glob
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

from sn_archive_exporter.ui_guard import (
    CHECK_INFO_ID,
    NOTE_CARD_ID,
    NOTES_PACKAGE,
    SUBFOLDER_SELECTION_CHECKBOX_ID,
    extract_note_cards,
    extract_selection_info,
    extract_subfolders,
    iter_nodes,
    load_xml,
    parse_bounds,
    summarize_xml_root,
)
from sn_archive_exporter.guarded_export_driver import note_card_is_selectable

CHECKBOX_ALL_ID = f"{NOTES_PACKAGE}:id/checkbox_all"
SUB_HEADER_TITLE_ID = f"{NOTES_PACKAGE}:id/sub_header_title"
SECTION_CHECKBOX_ID = SUBFOLDER_SELECTION_CHECKBOX_ID


def _node_bounds(node: ET.Element) -> tuple[int, int, int, int] | None:
    bounds = parse_bounds(node.attrib.get("bounds", ""))
    if not bounds:
        return None
    return (bounds.left, bounds.top, bounds.right, bounds.bottom)


def _bounds_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def checked_checkbox_breakdown(root: ET.Element) -> dict[str, int]:
    checked = [
        node
        for node in iter_nodes(root)
        if node.attrib.get("class") == "android.widget.CheckBox" and node.attrib.get("checked") == "true"
    ]
    card_bounds = [
        bounds
        for node in iter_nodes(root)
        if node.attrib.get("resource-id") == NOTE_CARD_ID
        for bounds in [_node_bounds(node)]
        if bounds
    ]
    header_bounds = [
        bounds
        for node in iter_nodes(root)
        if node.attrib.get("resource-id") == SUB_HEADER_TITLE_ID
        for bounds in [_node_bounds(node)]
        if bounds
    ]

    counts: Counter[str] = Counter()
    for node in checked:
        resource_id = node.attrib.get("resource-id", "")
        bounds = _node_bounds(node)
        if resource_id == CHECKBOX_ALL_ID:
            counts["select_all_checkbox"] += 1
        elif resource_id == SECTION_CHECKBOX_ID and bounds and any(_bounds_overlap(bounds, header) for header in header_bounds):
            counts["section_header_checkboxes"] += 1
        elif resource_id == SECTION_CHECKBOX_ID and bounds and any(_bounds_overlap(bounds, card) for card in card_bounds):
            counts["note_card_checkboxes"] += 1
        elif resource_id == SECTION_CHECKBOX_ID:
            counts["other_inflate_checkboxes"] += 1
        else:
            counts["other_checked_checkboxes"] += 1
    counts["total_checked_checkboxes"] = len(checked)
    return dict(sorted(counts.items()))


def compact_selection_probe(xml_path: Path, allowed_paths: list[str]) -> dict[str, Any]:
    root = load_xml(xml_path)
    summary = summarize_xml_root(root, allowed_paths)
    note_cards = extract_note_cards(root)
    selected_cards = [card for card in note_cards if card.get("checked") or card.get("selected")]
    return {
        "xml": str(xml_path),
        "folder_path": summary["folder_path"],
        "allowed": summary["allowed"],
        "selection_info": extract_selection_info(root),
        "visible_note_cards": len(note_cards),
        "visible_checked_note_cards": len(selected_cards),
        "visible_subfolders": len(extract_subfolders(root)),
        "visible_selected_subfolders": summary["selected_subfolder_count"],
        "visible_section_headers": len(
            [node for node in iter_nodes(root) if node.attrib.get("resource-id") == SUB_HEADER_TITLE_ID]
        ),
        "checked_checkbox_breakdown": checked_checkbox_breakdown(root),
        "bottom_overflow_available": summary["bottom_overflow_available"],
        "dangerous_actions_present": summary["dangerous_actions_present"],
        "export_menu_available": summary["bottom_overflow_available"] and not summary["dangerous_actions_present"],
    }


def compact_viewport_probe(xml_paths: list[Path], allowed_paths: list[str], *, include_per_xml: bool = False) -> dict[str, Any]:
    unique_fingerprints: set[str] = set()
    stable_tappable_fingerprints: set[str] = set()
    checked_fingerprints: set[str] = set()
    total_note_instances = 0
    total_section_headers = 0
    selected_count_sum = 0
    selected_count_xmls = 0
    max_selection_count = 0
    folder_paths: Counter[str] = Counter()
    xml_summaries: list[dict[str, Any]] = []
    for xml_path in xml_paths:
        root = load_xml(xml_path)
        summary = summarize_xml_root(root, allowed_paths)
        cards = extract_note_cards(root)
        fingerprints = {card["fingerprint"] for card in cards if card.get("fingerprint")}
        stable_tappable_fingerprints.update(
            card["fingerprint"]
            for card in cards
            if card.get("fingerprint") and note_card_is_selectable(card, frozenset())
        )
        checked_fingerprints.update(card["fingerprint"] for card in cards if card.get("fingerprint") and card.get("checked"))
        unique_fingerprints.update(fingerprints)
        total_note_instances += len(cards)
        section_count = len([node for node in iter_nodes(root) if node.attrib.get("resource-id") == SUB_HEADER_TITLE_ID])
        total_section_headers += section_count
        selection_count = summary["selection_info"]["selected_count"]
        if selection_count is not None:
            selected_count_xmls += 1
            selected_count_sum += selection_count
            max_selection_count = max(max_selection_count, selection_count)
        if summary["folder_path"]:
            folder_paths[summary["folder_path"]] += 1
        if include_per_xml:
            xml_summaries.append(
                {
                    "xml": str(xml_path),
                    "folder_path": summary["folder_path"],
                    "note_card_count": len(cards),
                    "unique_note_fingerprint_count": len(fingerprints),
                    "section_header_count": section_count,
                    "selection_count": selection_count,
                    "bottom_overflow_available": summary["bottom_overflow_available"],
                }
            )

    result = {
        "xml_count": len(xml_paths),
        "folder_path_counts": dict(folder_paths),
        "total_visible_note_instances": total_note_instances,
        "unique_note_fingerprints_in_viewports": len(unique_fingerprints),
        "_unique_fingerprints": sorted(unique_fingerprints),
        "stable_tappable_unique_fingerprints": len(stable_tappable_fingerprints),
        "_stable_tappable_fingerprints": sorted(stable_tappable_fingerprints),
        "checked_unique_fingerprints": len(checked_fingerprints),
        "_checked_fingerprints": sorted(checked_fingerprints),
        "duplicate_visible_note_instances": max(0, total_note_instances - len(unique_fingerprints)),
        "total_visible_section_headers": total_section_headers,
        "selection_count_xmls": selected_count_xmls,
        "selected_count_sum": selected_count_sum,
        "max_selection_count": max_selection_count,
    }
    if include_per_xml:
        result["per_xml"] = xml_summaries
    return result


def state_probe(path: Path | None, *, include_fingerprints: bool = False) -> dict[str, Any] | None:
    if not path:
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    batches = state.get("batches") or []
    result = {
        "state": str(path),
        "run_id": state.get("run_id"),
        "folder_path": state.get("folder_path"),
        "seen_fingerprint_count": len(state.get("seen_fingerprints") or []),
        "batch_count": len(batches),
        "first_batch": batches[0]["batch_id"] if batches else None,
        "last_batch": batches[-1]["batch_id"] if batches else None,
    }
    if include_fingerprints:
        result["_seen_fingerprints"] = sorted(state.get("seen_fingerprints") or [])
    return result


def compare_selection_state_viewports(
    selection: dict[str, Any] | None, state: dict[str, Any] | None, viewports: dict[str, Any]
) -> dict[str, Any]:
    selected_count = (selection or {}).get("selection_info", {}).get("selected_count")
    visible = set(viewports.get("_unique_fingerprints") or [])
    stable = set(viewports.get("_stable_tappable_fingerprints") or [])
    checked = set(viewports.get("_checked_fingerprints") or [])
    seen = set((state or {}).get("_seen_fingerprints") or [])
    result: dict[str, Any] = {
        "select_all_count": selected_count,
        "exported_seen_count": (state or {}).get("seen_fingerprint_count"),
        "viewport_unique_count": viewports.get("unique_note_fingerprints_in_viewports"),
        "stable_tappable_unique_count": viewports.get("stable_tappable_unique_fingerprints"),
        "checked_unique_count": viewports.get("checked_unique_fingerprints"),
        "batch_selected_count_sum": viewports.get("selected_count_sum"),
    }
    if selected_count is not None and visible:
        result["select_all_equals_viewport_unique_count"] = selected_count == len(visible)
    if visible and seen:
        result["visible_but_not_exported_count"] = len(visible - seen)
        result["exported_but_not_visible_count"] = len(seen - visible)
    if stable and seen:
        result["stable_tappable_but_not_exported_count"] = len(stable - seen)
        result["exported_but_not_stable_tappable_count"] = len(seen - stable)
    if checked and seen:
        result["checked_but_not_exported_count"] = len(checked - seen)
        result["exported_but_not_checked_count"] = len(seen - checked)
    if selected_count is not None and state:
        result["select_all_minus_exported_seen_count"] = selected_count - int(state["seen_fingerprint_count"])
    return result


def build_hypotheses(
    selection: dict[str, Any] | None, state: dict[str, Any] | None, viewports: dict[str, Any], comparison: dict[str, Any]
) -> list[str]:
    hypotheses: list[str] = []
    selected_count = (selection or {}).get("selection_info", {}).get("selected_count")
    seen_count = (state or {}).get("seen_fingerprint_count")
    viewport_unique = viewports.get("unique_note_fingerprints_in_viewports")
    if comparison.get("select_all_equals_viewport_unique_count") and comparison.get("visible_but_not_exported_count"):
        if comparison.get("stable_tappable_but_not_exported_count") == 0:
            hypotheses.append(
                "select-all count matches all observed unique note cards, but exported count matches only cards that ever entered the stable tap zone; the remaining gap is unsafe edge cards caused by scroll stride/viewport alignment."
            )
        else:
            hypotheses.append(
                "select-all count matches the unique note fingerprints observed across batch screens; the gap is caused by traversal/export selection strategy skipping stable visible notes."
            )
    strong_edge_alignment = (
        comparison.get("select_all_equals_viewport_unique_count")
        and comparison.get("stable_tappable_but_not_exported_count") == 0
        and comparison.get("visible_but_not_exported_count")
    )
    if selected_count is not None and seen_count is not None and not strong_edge_alignment:
        delta = selected_count - seen_count
        if delta == 0:
            hypotheses.append("selected_count matches exported unique fingerprint count.")
        elif delta > 0:
            hypotheses.append(
                f"selected_count exceeds exported unique fingerprints by {delta}; likely missing traversal coverage or Samsung count includes non-exportable/duplicate grouped items."
            )
        else:
            hypotheses.append(
                f"exported unique fingerprints exceed selected_count by {-delta}; selected_count may have been captured on a filtered/partial screen."
            )
    if selection and not selection.get("bottom_overflow_available"):
        hypotheses.append("select-all state hides export overflow; Samsung Notes treats this selection as unsupported for file export.")
    breakdown = (selection or {}).get("checked_checkbox_breakdown", {})
    if breakdown.get("section_header_checkboxes"):
        hypotheses.append("visible select-all also checks section headers; selection count must not be assumed to equal visible note cards.")
    if viewport_unique and seen_count and viewport_unique < seen_count:
        hypotheses.append("provided viewport XMLs are incomplete for the whole run; use state/archive counts as the stronger exported-note evidence.")
    selected_sum = viewports.get("selected_count_sum")
    if selected_sum and seen_count and selected_sum != seen_count:
        hypotheses.append(
            f"batch selection-count sum is {selected_sum}, while state has {seen_count}; include earlier/offline batch XMLs or use state batches as source of truth."
        )
    return hypotheses


def expand_globs(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        matches = [Path(match) for match in glob.glob(pattern)]
        if not matches and Path(pattern).exists():
            matches = [Path(pattern)]
        for path in sorted(matches):
            if path not in seen:
                paths.append(path)
                seen.add(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Samsung Notes 407-vs-exported-count probe.")
    parser.add_argument("--selection-xml", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--viewport-glob", action="append", default=[])
    parser.add_argument("--allowed-path", action="append", default=[])
    parser.add_argument("--include-per-xml", action="store_true")
    args = parser.parse_args(argv)

    selection = compact_selection_probe(args.selection_xml, args.allowed_path) if args.selection_xml else None
    viewport_paths = expand_globs(args.viewport_glob)
    viewports = compact_viewport_probe(viewport_paths, args.allowed_path, include_per_xml=args.include_per_xml)
    state = state_probe(args.state, include_fingerprints=True)
    comparison = compare_selection_state_viewports(selection, state, viewports)
    viewports.pop("_unique_fingerprints", None)
    viewports.pop("_stable_tappable_fingerprints", None)
    viewports.pop("_checked_fingerprints", None)
    if state:
        state.pop("_seen_fingerprints", None)
    result = {
        "probe_mode": "read_only_local_xml_and_state",
        "privacy": "raw XML and note text are not printed",
        "selection": selection,
        "state": state,
        "viewports": viewports,
        "comparison": comparison,
        "hypotheses": build_hypotheses(selection, state, viewports, comparison),
        "next_read_only_checks": [
            "capture the normal non-selection folder count label for the same folder",
            "capture one fresh select-all screen after scrolling to top and verify whether the 407 count is stable",
            "compare Samsung's visible note count label with exported unique fingerprints before running more exports",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
