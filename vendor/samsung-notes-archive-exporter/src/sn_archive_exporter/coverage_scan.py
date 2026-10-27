from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sn_archive_exporter.edge_gap_probe import apply_nudge, expand_globs, fingerprints_from_xmls, summarize_gap
from sn_archive_exporter.guarded_export_driver import DriverConfig, dump_ui, set_quiet
from sn_archive_exporter.scroll_nudges import NUDGES, validate_nudge_sequence
from sn_archive_exporter.ui_guard import assert_allowed_path, load_xml, summarize_xml_root
from sn_archive_exporter.visible_batch_runner import visible_signature
from sn_archive_exporter.visible_batch_state import load_state


@dataclass(frozen=True)
class CoverageScanConfig:
    folder_path: str
    run_id: str
    state_path: Path
    target_globs: tuple[str, ...]
    out_dir: Path
    execute: bool
    max_steps: int
    max_repeated_screens: int
    wait_seconds: float
    nudge_sequence: tuple[str, ...]
    stop_on_stable_missing: bool = False


def dump_summary(config: CoverageScanConfig, step: int) -> tuple[Path, dict[str, Any]]:
    xml_path = dump_ui(
        DriverConfig(
            allowed_path=config.folder_path,
            destination="Documents",
            out_dir=config.out_dir,
            label=f"{config.run_id}_coverage_scan_step_{step:03d}",
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


def run_coverage_scan(config: CoverageScanConfig) -> dict[str, Any]:
    if config.max_steps < 1:
        raise SystemExit("Refusing action: --max-steps must be at least 1")
    if config.max_repeated_screens < 1:
        raise SystemExit("Refusing action: --max-repeated-screens must be at least 1")
    validate_nudge_sequence(config.nudge_sequence)

    state = load_state(config.state_path, run_id=config.run_id, folder_path=config.folder_path)
    exported_seen = set(state.get("seen_fingerprints") or [])
    target_xmls = expand_globs(config.target_globs)
    target_universe = fingerprints_from_xmls(target_xmls, config.folder_path)
    target_missing = target_universe - exported_seen

    observed: set[str] = set()
    observed_missing: set[str] = set()
    observed_stable_missing: set[str] = set()
    steps: list[dict[str, Any]] = []
    previous_signature: str | None = None
    repeated_screen_count = 0
    stop_reason = "max_steps"

    for step in range(config.max_steps):
        xml_path, summary = dump_summary(config, step)
        signature = visible_signature(summary)
        if signature == previous_signature:
            repeated_screen_count += 1
        else:
            repeated_screen_count = 0
        previous_signature = signature

        visible = {card["fingerprint"] for card in summary["note_cards"] if card.get("fingerprint")}
        gap = summarize_gap(summary, target_missing=target_missing, exported_seen=exported_seen)
        visible_missing = visible & target_missing
        stable_missing_count = int(gap.get("stable_missing_count") or 0)
        observed.update(visible)
        observed_missing.update(visible_missing)
        if stable_missing_count:
            for card in summary["note_cards"]:
                fingerprint = card.get("fingerprint")
                if fingerprint in visible_missing:
                    observed_stable_missing.add(fingerprint)

        entry: dict[str, Any] = {
            "step": step,
            "xml": str(xml_path),
            "visible_signature": signature[:16],
            "repeated_screen_count": repeated_screen_count,
            "visible_unique_count": len(visible),
            "seen_visible_count": len(visible & exported_seen),
            "missing_visible_count": len(visible_missing),
            "stable_missing_count": stable_missing_count,
            "edge_only_missing_count": gap["edge_only_missing_count"],
            "observed_unique_total": len(observed),
            "observed_missing_total": len(observed_missing),
            "observed_stable_missing_total": len(observed_stable_missing),
        }
        if config.stop_on_stable_missing and stable_missing_count:
            entry["stop_reason"] = "stable_missing_found"
            steps.append(entry)
            stop_reason = "stable_missing_found"
            break
        if repeated_screen_count >= config.max_repeated_screens:
            entry["stop_reason"] = "screen_repeated"
            steps.append(entry)
            stop_reason = "screen_repeated"
            break

        nudge_name = config.nudge_sequence[step % len(config.nudge_sequence)]
        entry["planned_nudge"] = nudge_name
        if config.execute:
            entry["executed_nudge"] = apply_nudge(nudge_name)
            time.sleep(config.wait_seconds)
        steps.append(entry)
        if not config.execute:
            stop_reason = "dry_run"
            break

    return {
        "scan_mode": "read_only_coverage_scan",
        "execute": config.execute,
        "folder_path": config.folder_path,
        "run_id": config.run_id,
        "target_xml_count": len(target_xmls),
        "target_universe_count": len(target_universe),
        "exported_seen_count": len(exported_seen),
        "target_missing_count": len(target_missing),
        "observed_unique_total": len(observed),
        "observed_missing_total": len(observed_missing),
        "observed_stable_missing_total": len(observed_stable_missing),
        "stop_reason": stop_reason,
        "nudge_sequence": list(config.nudge_sequence),
        "steps": steps,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Samsung Notes visible coverage scanner.")
    parser.add_argument("--folder-path", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--target-glob", action="append", required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("ui_dumps"))
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--max-repeated-screens", type=int, default=2)
    parser.add_argument("--wait-seconds", type=float, default=0.5)
    parser.add_argument(
        "--nudge",
        action="append",
        default=[],
        help=f"Scroll nudge to use. Choices: {', '.join(sorted(NUDGES))}. Can be repeated.",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--stop-on-stable-missing", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    set_quiet(args.quiet)
    result = run_coverage_scan(
        CoverageScanConfig(
            folder_path=args.folder_path,
            run_id=args.run_id,
            state_path=args.state,
            target_globs=tuple(args.target_glob),
            out_dir=args.out_dir,
            execute=args.execute,
            max_steps=args.max_steps,
            max_repeated_screens=args.max_repeated_screens,
            wait_seconds=args.wait_seconds,
            nudge_sequence=tuple(args.nudge or ["large-forward"]),
            stop_on_stable_missing=args.stop_on_stable_missing,
        )
    )
    if args.summary_only:
        run_result_steps = result.get("steps") or []
        result = {key: value for key, value in result.items() if key != "steps"}
        result["last_step"] = (run_result_steps[-1] if run_result_steps else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
