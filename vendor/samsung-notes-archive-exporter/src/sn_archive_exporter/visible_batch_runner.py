from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
from .scroll_nudges import NUDGES, get_nudge, validate_nudge_sequence
from .edge_gap_probe import expand_globs, fingerprints_from_xmls, summarize_gap
from .recovery_policy import decide_recovery_action
from .visible_batch_plan import plan_visible_batch
from .visible_batch_state import load_state, mark_seen, save_state


@dataclass(frozen=True)
class VisibleBatchRunConfig:
    folder_path: str
    run_id: str
    state_path: Path
    input_root: Path
    archive_root: Path
    out_dir: Path
    execute: bool
    max_batches: int
    max_empty_scrolls: int
    wait_seconds: float
    export_format: str = "sdocx"
    max_count: int | None = None
    allow_existing_output: bool = False
    nudge_sequence: tuple[str, ...] = ("small-forward",)
    target_globs: tuple[str, ...] = ()
    max_repeated_screens: int = 2
    allow_partial_export: bool = False


def swipe_notes_down(nudge_name: str = "small-forward") -> dict[str, Any]:
    nudge = get_nudge(nudge_name)
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


def visible_signature(summary: dict[str, Any]) -> str:
    fingerprints = sorted(card["fingerprint"] for card in summary["note_cards"] if card.get("fingerprint"))
    return hashlib.sha256("\n".join(fingerprints).encode("utf-8")).hexdigest()


def dump_and_plan(config: VisibleBatchRunConfig, state: dict[str, Any], step: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    xml_path = dump_ui(
        DriverConfig(
            allowed_path=config.folder_path,
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
            allow_existing_output=config.allow_existing_output,
            export_format=config.export_format,
        ),
        "screen",
    )
    summary = ui_guard.summarize(xml_path, [config.folder_path])
    if not summary["is_samsung_notes_visible"]:
        raise SystemExit(f"Refusing action: Samsung Notes is not visible. Packages: {summary['packages']}")
    ui_guard.assert_allowed_path(summary["folder_path"], [config.folder_path])
    plan = plan_visible_batch(
        summary,
        seen_fingerprints=frozenset(state.get("seen_fingerprints") or []),
        max_count=config.max_count,
    )
    plan["xml"] = str(xml_path)
    return xml_path, plan, summary


def run_visible_batches(config: VisibleBatchRunConfig) -> dict[str, Any]:
    if config.max_batches < 1:
        raise SystemExit("Refusing action: --max-batches must be at least 1")
    if config.max_empty_scrolls < 0:
        raise SystemExit("Refusing action: --max-empty-scrolls must be non-negative")
    if config.max_count is not None and config.max_count < 1:
        raise SystemExit("Refusing action: --max-count must be positive")
    validate_nudge_sequence(config.nudge_sequence)
    if config.max_repeated_screens < 1:
        raise SystemExit("Refusing action: --max-repeated-screens must be at least 1")

    state = load_state(config.state_path, run_id=config.run_id, folder_path=config.folder_path)
    state_export_format = state.get("export_format")
    if state_export_format not in {None, config.export_format}:
        raise SystemExit(
            f"Refusing action: state export_format={state_export_format!r} does not match {config.export_format!r}"
        )
    state["export_format"] = config.export_format
    target_universe: set[str] = set()
    if config.target_globs:
        target_universe = fingerprints_from_xmls(expand_globs(config.target_globs), config.folder_path)
    batches: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    empty_scrolls = 0
    repeated_screen_count = 0
    previous_signature: str | None = None

    while len(batches) < config.max_batches:
        _, plan, summary = dump_and_plan(config, state, f"batch_loop_{len(batches) + 1:03d}_scroll_{empty_scrolls:02d}")
        signature = visible_signature(summary)
        if signature == previous_signature:
            repeated_screen_count += 1
        else:
            repeated_screen_count = 0
        previous_signature = signature
        observation = {
            "xml": plan["xml"],
            "visible_note_count": plan["visible_note_count"],
            "safe_unseen_note_count": plan["safe_unseen_note_count"],
            "recommended_select_count": plan["recommended_select_count"],
            "skipped_seen_count": plan["skipped_seen_count"],
            "skipped_unsafe_count": plan["skipped_unsafe_count"],
            "visible_signature": signature[:16],
            "repeated_screen_count": repeated_screen_count,
        }
        if target_universe:
            target_missing = target_universe - set(state.get("seen_fingerprints") or [])
            gap = summarize_gap(summary, target_missing=target_missing, exported_seen=set(state.get("seen_fingerprints") or []))
            gap["target_universe_count"] = len(target_universe)
            gap["target_missing_count"] = len(target_missing)
            observation["gap"] = gap
        decision = decide_recovery_action(
            observation,
            empty_scrolls=empty_scrolls,
            max_empty_scrolls=config.max_empty_scrolls,
            repeated_screen_count=repeated_screen_count,
            max_repeated_screens=config.max_repeated_screens,
        )
        observation["decision"] = decision
        observations.append(observation)
        select_count = int(plan["recommended_select_count"])
        if decision["action"] == "stop":
            break
        if decision["action"] == "nudge":
            nudge_name = config.nudge_sequence[empty_scrolls % len(config.nudge_sequence)]
            observation["nudge_name"] = nudge_name
            if not config.execute:
                break
            observation["nudge"] = swipe_notes_down(nudge_name)
            empty_scrolls += 1
            time.sleep(config.wait_seconds)
            continue
        if select_count < 1:
            raise SystemExit(f"Refusing action: policy chose export but select_count={select_count}")

        batch_number = len(state.get("batches") or []) + 1
        batch_id = f"batch{batch_number:03d}_{select_count}notes"
        pull_to = config.input_root / config.run_id / batch_id
        archive_output = config.archive_root / config.run_id / batch_id
        if not config.execute:
            batches.append({"batch_id": batch_id, "dry_run": True, "plan": plan})
            break

        result = run_guarded_export(
            DriverConfig(
                allowed_path=config.folder_path,
                destination="Documents",
                out_dir=config.out_dir,
                label=f"{config.run_id}_{batch_id}",
                execute=True,
                select_count=select_count,
                select_all=False,
                wait_seconds=config.wait_seconds,
                pull_to=pull_to,
                mapping_path=None,
                archive_output=archive_output,
                allow_existing_output=config.allow_existing_output,
                skip_note_fingerprints=frozenset(state.get("seen_fingerprints") or []),
                export_format=config.export_format,
                allow_partial_export=config.allow_partial_export,
            )
        )
        summary = summarize_export_result(result)
        mark_seen(
            state,
            list(plan["selected_fingerprints"]),
            batch_id=batch_id,
            note=f"exported via {summary.get('handoff', {}).get('archive_output')}",
        )
        save_state(config.state_path, state)
        batches.append({"batch_id": batch_id, "plan": plan, "result": summary})
        empty_scrolls = 0
        repeated_screen_count = 0
        previous_signature = None

    return {
        "status": "ok",
        "run_id": config.run_id,
        "folder_path": config.folder_path,
        "execute": config.execute,
        "export_format": config.export_format,
        "state_path": str(config.state_path),
        "seen_fingerprint_count": len(state.get("seen_fingerprints") or []),
        "batch_count": len(state.get("batches") or []),
        "target_universe_count": len(target_universe) if target_universe else None,
        "target_missing_count": len(target_universe - set(state.get("seen_fingerprints") or [])) if target_universe else None,
        "new_batches": batches,
        "observations": observations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run partitioned visible-note Samsung Notes exports.")
    parser.add_argument("--folder-path", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--input-root", type=Path, default=Path("input_exports"))
    parser.add_argument("--archive-root", type=Path, default=Path("output_archive"))
    parser.add_argument("--out-dir", type=Path, default=Path("ui_dumps"))
    parser.add_argument("--max-batches", type=int, default=1)
    parser.add_argument("--max-empty-scrolls", type=int, default=2)
    parser.add_argument("--max-repeated-screens", type=int, default=2)
    parser.add_argument("--max-count", type=int)
    parser.add_argument(
        "--target-glob",
        action="append",
        default=[],
        help="Optional captured XML glob defining the expected note fingerprint universe for edge-gap recovery.",
    )
    parser.add_argument("--wait-seconds", type=float, default=1.0)
    parser.add_argument(
        "--nudge",
        action="append",
        default=[],
        help=f"Scroll nudge to use when no safe unseen notes are visible. Choices: {', '.join(sorted(NUDGES))}. Can be repeated.",
    )
    parser.add_argument("--allow-existing-output", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--export-format", choices=sorted(EXPORT_FORMATS), default="sdocx")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    set_quiet(args.quiet)
    state_path = args.state or (args.archive_root / args.run_id / "state.json")
    result = run_visible_batches(
        VisibleBatchRunConfig(
            folder_path=args.folder_path,
            run_id=args.run_id,
            state_path=state_path,
            input_root=args.input_root,
            archive_root=args.archive_root,
            out_dir=args.out_dir,
            execute=args.execute,
            max_batches=args.max_batches,
            max_empty_scrolls=args.max_empty_scrolls,
            max_count=args.max_count,
            wait_seconds=args.wait_seconds,
            allow_existing_output=args.allow_existing_output,
            nudge_sequence=tuple(args.nudge or ["small-forward"]),
            target_globs=tuple(args.target_glob),
            max_repeated_screens=args.max_repeated_screens,
            export_format=args.export_format,
        )
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
