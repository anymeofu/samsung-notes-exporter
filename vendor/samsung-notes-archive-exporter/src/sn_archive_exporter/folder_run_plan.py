from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _export_summary(node: dict[str, Any]) -> dict[str, Any] | None:
    export = node.get("export") or {}
    if not export:
        return None
    handoff = export.get("handoff") or {}
    return {
        "folder_path": node.get("folder_path"),
        "selected_count": export.get("selected_count"),
        "exported_file_count": export.get("exported_file_count"),
        "pulled_file_count": handoff.get("pulled_file_count"),
        "archive_output": handoff.get("archive_output"),
    }


def collect_tree_plan(tree: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    visited: list[dict[str, Any]] = []
    exported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    dry_run_children: list[dict[str, Any]] = []

    def visit(node: dict[str, Any]) -> None:
        folder_path = node.get("folder_path")
        if node.get("skipped"):
            skipped.append(
                {
                    "folder_path": folder_path,
                    "reason": node.get("skipped"),
                    "error": node.get("error"),
                }
            )
            return
        if node.get("dry_run"):
            dry_run_children.append({"folder_path": folder_path})
            return

        visited.append(
            {
                "folder_path": folder_path,
                "depth": node.get("depth"),
                "visible_note_cards": node.get("visible_note_cards"),
                "visible_subfolder_count": node.get("visible_subfolder_count"),
            }
        )
        export = _export_summary(node)
        if export:
            exported.append(export)
        for child in node.get("children") or []:
            if isinstance(child, dict):
                visit(child)

    if tree:
        visit(tree)

    return {
        "visited": visited,
        "exported": exported,
        "skipped": skipped,
        "dry_run_children": dry_run_children,
    }


def dedupe_by_folder_path(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        folder_path = str(item.get("folder_path") or "")
        key = folder_path or json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def build_folder_run_plan(run_summary_paths: list[Path]) -> dict[str, Any]:
    combined = {
        "visited": [],
        "exported": [],
        "skipped": [],
        "dry_run_children": [],
    }
    for run_summary_path in run_summary_paths:
        run_summary = load_json(run_summary_path)
        tree_plan = collect_tree_plan(run_summary.get("tree") or {})
        for key in combined:
            combined[key].extend(tree_plan[key])

    visited = dedupe_by_folder_path(combined["visited"])
    exported = dedupe_by_folder_path(combined["exported"])
    skipped = dedupe_by_folder_path(combined["skipped"])
    dry_run_children = dedupe_by_folder_path(combined["dry_run_children"])

    exported_paths = {item.get("folder_path") for item in exported}
    visited_paths = {item.get("folder_path") for item in visited}
    unresolved_skipped = [
        item for item in skipped if item.get("folder_path") not in visited_paths
    ]
    unresolved_dry_run_children = [
        item for item in dry_run_children if item.get("folder_path") not in visited_paths
    ]
    visited_without_export = [
        item
        for item in visited
        if item.get("folder_path") not in exported_paths
    ]
    pending = [
        {"folder_path": item.get("folder_path"), "reason": item.get("reason")}
        for item in unresolved_skipped
    ]
    pending.extend(
        {"folder_path": item.get("folder_path"), "reason": "dry_run_child"}
        for item in unresolved_dry_run_children
    )
    unresolved_paths = {
        item.get("folder_path") for item in unresolved_skipped
    } | {
        item.get("folder_path") for item in unresolved_dry_run_children
    }

    return {
        "schema": "sn_archive_exporter.folder_run_plan.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_summary_paths": [str(path) for path in run_summary_paths],
        "counts": {
            "visited": len(visited),
            "exported": len(exported),
            "visited_without_export": len(visited_without_export),
            "skipped": len(skipped),
            "resolved_skipped": len(skipped) - len(unresolved_skipped),
            "dry_run_children": len(dry_run_children),
            "resolved_dry_run_children": len(dry_run_children) - len(unresolved_dry_run_children),
            "pending": len(pending),
        },
        "visited": visited,
        "exported": exported,
        "visited_without_export": visited_without_export,
        "skipped": skipped,
        "dry_run_children": dry_run_children,
        "pending": dedupe_by_folder_path(pending),
        "completed_folder_paths": sorted(
            str(path)
            for path in set(exported_paths) | set(visited_paths)
            if path
        ),
        "incomplete_folder_paths": sorted(
            str(path)
            for path in set(unresolved_paths)
            if path
        ),
    }


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def build_next_run_specs(
    plan: dict[str, Any],
    *,
    run_id_prefix: str,
    max_depth: int,
    max_folders: int | None,
    max_subfolder_scrolls: int,
    mixed_folder_select_all: bool,
    wait_seconds: float,
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for index, pending in enumerate(plan.get("pending") or [], start=1):
        folder_path = str(pending.get("folder_path") or "")
        if not folder_path:
            continue
        run_id = f"{run_id_prefix}_{index:03d}"
        args = [
            "PYTHONPATH=src",
            "python3",
            "-m",
            "sn_archive_exporter.folder_walk_driver",
            "--root-path",
            shell_quote(folder_path),
            "--run-id",
            shell_quote(run_id),
            "--max-depth",
            str(max_depth),
            "--max-subfolder-scrolls",
            str(max_subfolder_scrolls),
        ]
        if max_folders is not None:
            args.extend(["--max-folders", str(max_folders)])
        if mixed_folder_select_all:
            args.append("--mixed-folder-select-all")
        args.extend(
            [
                "--execute",
                "--summary-only",
                "--quiet",
                "--wait-seconds",
                str(wait_seconds),
            ]
        )
        specs.append(
            {
                "folder_path": folder_path,
                "reason": pending.get("reason"),
                "run_id": run_id,
                "command": " ".join(args),
            }
        )
    return specs


def summarize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "schema": plan["schema"],
        "run_summary_count": len(plan.get("run_summary_paths") or []),
        "counts": plan["counts"],
        "incomplete_folder_paths": plan["incomplete_folder_paths"],
    }
    if "next_runs" in plan:
        summary["next_run_count"] = len(plan["next_runs"])
        summary["next_runs"] = plan["next_runs"]
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize completed and pending folders from folder-walk run summaries.")
    parser.add_argument("--run-summary", required=True, action="append", type=Path)
    parser.add_argument("--output", type=Path, help="Write the full plan JSON to this path.")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--next-run-prefix", help="Add suggested folder_walk_driver commands for pending folder paths.")
    parser.add_argument("--next-max-depth", type=int, default=5)
    parser.add_argument("--next-max-folders", type=int)
    parser.add_argument("--next-max-subfolder-scrolls", type=int, default=3)
    parser.add_argument("--next-mixed-folder-select-all", action="store_true")
    parser.add_argument("--next-wait-seconds", type=float, default=0.5)
    args = parser.parse_args(argv)

    plan = build_folder_run_plan(args.run_summary)
    if args.next_run_prefix:
        plan["next_runs"] = build_next_run_specs(
            plan,
            run_id_prefix=args.next_run_prefix,
            max_depth=args.next_max_depth,
            max_folders=args.next_max_folders,
            max_subfolder_scrolls=args.next_max_subfolder_scrolls,
            mixed_folder_select_all=args.next_mixed_folder_select_all,
            wait_seconds=args.next_wait_seconds,
        )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = summarize_plan(plan) if args.summary_only else plan
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
