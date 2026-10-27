from __future__ import annotations

import argparse
import glob
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sn_archive_exporter.guarded_export_driver import DriverConfig, adb, dump_ui, note_card_is_selectable, set_quiet
from sn_archive_exporter.scroll_nudges import NUDGES, get_nudge, validate_nudge_sequence
from sn_archive_exporter.ui_guard import assert_allowed_path, load_xml, summarize_xml_root
from sn_archive_exporter.visible_batch_state import load_state


@dataclass(frozen=True)
class EdgeGapProbeConfig:
    folder_path: str
    run_id: str
    state_path: Path
    target_globs: tuple[str, ...]
    out_dir: Path
    current_xml: Path | None
    execute: bool
    max_steps: int
    wait_seconds: float
    nudge_sequence: tuple[str, ...]
    quiet: bool = False


def expand_globs(patterns: tuple[str, ...]) -> list[Path]:
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


def fingerprints_from_xmls(xml_paths: list[Path], folder_path: str) -> set[str]:
    fingerprints: set[str] = set()
    for xml_path in xml_paths:
        summary = summarize_xml_root(load_xml(xml_path), [folder_path])
        if summary["folder_path"]:
            assert_allowed_path(summary["folder_path"], [folder_path])
        for card in summary["note_cards"]:
            fingerprint = card.get("fingerprint")
            if fingerprint:
                fingerprints.add(fingerprint)
    return fingerprints


def observe_current(config: EdgeGapProbeConfig, step: int, *, after: str | None = None) -> tuple[Path, dict[str, Any]]:
    if config.current_xml is not None and step == 0:
        summary = summarize_xml_root(load_xml(config.current_xml), [config.folder_path])
        if not summary["is_samsung_notes_visible"]:
            raise SystemExit(f"Refusing action: Samsung Notes is not visible. Packages: {summary['packages']}")
        assert_allowed_path(summary["folder_path"], [config.folder_path])
        return config.current_xml, summary

    label = f"{config.run_id}_edge_gap_step_{step:03d}"
    if after:
        label += f"_{after}"
    xml_path = dump_ui(
        DriverConfig(
            allowed_path=config.folder_path,
            destination="Documents",
            out_dir=config.out_dir,
            label=label,
            execute=False,
            select_count=1,
            select_all=False,
            wait_seconds=config.wait_seconds,
            pull_to=None,
            mapping_path=None,
            archive_output=None,
            allow_existing_output=True,
        ),
        "screen",
    )
    summary = summarize_xml_root(load_xml(xml_path), [config.folder_path])
    if not summary["is_samsung_notes_visible"]:
        raise SystemExit(f"Refusing action: Samsung Notes is not visible. Packages: {summary['packages']}")
    assert_allowed_path(summary["folder_path"], [config.folder_path])
    return xml_path, summary


def apply_nudge(name: str) -> dict[str, Any]:
    nudge = get_nudge(name)
    adb(
        [
            "shell",
            "input",
            "swipe",
            str(nudge.start_x),
            str(nudge.start_y),
            str(nudge.end_x),
            str(nudge.end_y),
            str(nudge.duration_ms),
        ],
        capture=True,
    )
    return {
        "name": nudge.name,
        "start": [nudge.start_x, nudge.start_y],
        "end": [nudge.end_x, nudge.end_y],
        "duration_ms": nudge.duration_ms,
    }


def summarize_gap(
    summary: dict[str, Any],
    *,
    target_missing: set[str],
    exported_seen: set[str],
) -> dict[str, Any]:
    visible = {card["fingerprint"] for card in summary["note_cards"] if card.get("fingerprint")}
    stable = {
        card["fingerprint"]
        for card in summary["note_cards"]
        if card.get("fingerprint") and note_card_is_selectable(card, frozenset(exported_seen))
    }
    visible_missing = visible & target_missing
    stable_missing = stable & target_missing
    edge_missing = visible_missing - stable_missing
    return {
        "folder_path": summary["folder_path"],
        "visible_note_count": summary["note_card_count"],
        "visible_unique_count": len(visible),
        "stable_tappable_unique_count": len(stable),
        "visible_missing_count": len(visible_missing),
        "stable_missing_count": len(stable_missing),
        "edge_only_missing_count": len(edge_missing),
        "skipped_seen_visible_count": len(visible & exported_seen),
        "bottom_overflow_available": summary["bottom_overflow_available"],
        "dangerous_actions_present": summary["dangerous_actions_present"],
    }


def run_edge_gap_probe(config: EdgeGapProbeConfig) -> dict[str, Any]:
    if config.max_steps < 1:
        raise SystemExit("Refusing action: --max-steps must be at least 1")
    if config.current_xml is not None and config.execute:
        raise SystemExit("Refusing action: --current-xml is an offline read-only mode and cannot be combined with --execute")
    validate_nudge_sequence(config.nudge_sequence)

    state = load_state(config.state_path, run_id=config.run_id, folder_path=config.folder_path)
    exported_seen = set(state.get("seen_fingerprints") or [])
    target_xmls = expand_globs(config.target_globs)
    target_universe = fingerprints_from_xmls(target_xmls, config.folder_path)
    target_missing = target_universe - exported_seen

    steps: list[dict[str, Any]] = []
    repeated_screen_count = 0
    previous_visible: set[str] | None = None
    best_stable_missing_count = 0
    for step_index in range(config.max_steps):
        xml_path, summary = observe_current(config, step_index, after="before_nudge")
        current = summarize_gap(summary, target_missing=target_missing, exported_seen=exported_seen)
        visible_now = {card["fingerprint"] for card in summary["note_cards"] if card.get("fingerprint")}
        if previous_visible == visible_now:
            repeated_screen_count += 1
        else:
            repeated_screen_count = 0
        previous_visible = visible_now
        best_stable_missing_count = max(best_stable_missing_count, current["stable_missing_count"])
        entry: dict[str, Any] = {
            "step": step_index,
            "xml": str(xml_path),
            "observation": current,
        }
        if current["stable_missing_count"] > 0:
            entry["stop_reason"] = "stable_missing_notes_available"
            steps.append(entry)
            break
        if repeated_screen_count >= 2:
            entry["stop_reason"] = "screen_repeated"
            steps.append(entry)
            break
        nudge_name = config.nudge_sequence[step_index % len(config.nudge_sequence)]
        entry["planned_nudge"] = nudge_name
        if config.execute:
            entry["executed_nudge"] = apply_nudge(nudge_name)
            time.sleep(config.wait_seconds)
        steps.append(entry)
        if not config.execute:
            break

    return {
        "probe_mode": "read_only_scroll_and_dump",
        "execute": config.execute,
        "folder_path": config.folder_path,
        "run_id": config.run_id,
        "state_path": str(config.state_path),
        "target_xml_count": len(target_xmls),
        "target_universe_count": len(target_universe),
        "exported_seen_count": len(exported_seen),
        "target_missing_count": len(target_missing),
        "best_stable_missing_count": best_stable_missing_count,
        "nudge_sequence": list(config.nudge_sequence),
        "steps": steps,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only edge-gap probe for Samsung Notes visible-batch runs.")
    parser.add_argument("--folder-path", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--target-glob", action="append", required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("ui_dumps"))
    parser.add_argument("--current-xml", type=Path, help="Analyze this already captured screen instead of dumping via ADB.")
    parser.add_argument("--max-steps", type=int, default=6)
    parser.add_argument("--wait-seconds", type=float, default=0.7)
    parser.add_argument(
        "--nudge",
        action="append",
        default=[],
        help=f"Scroll nudge to try. Choices: {', '.join(sorted(NUDGES))}. Can be repeated.",
    )
    parser.add_argument("--execute", action="store_true", help="Actually perform read-only scroll nudges.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    set_quiet(args.quiet)
    nudge_sequence = tuple(args.nudge or ["small-back", "small-forward"])
    result = run_edge_gap_probe(
        EdgeGapProbeConfig(
            folder_path=args.folder_path,
            run_id=args.run_id,
            state_path=args.state,
            target_globs=tuple(args.target_glob),
            out_dir=args.out_dir,
            current_xml=args.current_xml,
            execute=args.execute,
            max_steps=args.max_steps,
            wait_seconds=args.wait_seconds,
            nudge_sequence=nudge_sequence,
            quiet=args.quiet,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
