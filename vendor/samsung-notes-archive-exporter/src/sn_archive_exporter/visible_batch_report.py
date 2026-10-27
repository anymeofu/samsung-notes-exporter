from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Any

from .archive_validator import validate_archive
from .selection_count_probe import compact_viewport_probe, state_probe


def expand_paths(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        matches = [Path(match) for match in glob.glob(pattern)]
        if not matches and Path(pattern).exists():
            matches = [Path(pattern)]
        for path in sorted(matches):
            if path in seen:
                continue
            seen.add(path)
            paths.append(path)
    return paths


def summarize_archive_outputs(paths: list[Path]) -> dict[str, Any]:
    notes = 0
    files = 0
    folders: set[str] = set()
    notes_missing_display_datetime = 0
    files_with_sdocx_metadata = 0
    missing_manifests: list[str] = []
    source_manifests: list[str] = []

    for archive_output in paths:
        manifest_path = archive_output / "manifest.json"
        if not manifest_path.exists():
            missing_manifests.append(str(manifest_path))
            continue
        source_manifests.append(str(manifest_path))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for note in manifest.get("notes") or []:
            notes += 1
            folder_path = note.get("folder_path")
            if isinstance(folder_path, str):
                folders.add(folder_path)
            if not note.get("display_datetime"):
                notes_missing_display_datetime += 1
            for exported in note.get("exported_files") or []:
                files += 1
                if exported.get("sdocx_metadata"):
                    files_with_sdocx_metadata += 1

    return {
        "archive_output_count": len(paths),
        "source_manifest_count": len(source_manifests),
        "missing_manifest_count": len(missing_manifests),
        "missing_manifests": missing_manifests,
        "counts": {
            "folders_with_notes": len(folders),
            "notes": notes,
            "files": files,
        },
        "quality": {
            "notes_missing_display_datetime": notes_missing_display_datetime,
            "files_with_sdocx_metadata": files_with_sdocx_metadata,
        },
    }


def summarize_merged_archive(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    result = validate_archive(path)
    return {
        "archive_dir": result["archive_dir"],
        "status": result["status"],
        "counts": result.get("counts"),
        "quality": result.get("quality"),
        "error_count": len(result.get("errors") or []),
        "warning_count": len(result.get("warnings") or []),
    }


def mismatch_summary(
    *,
    state: dict[str, Any] | None,
    viewports: dict[str, Any] | None,
    archive_outputs: dict[str, Any] | None,
    merged_archive: dict[str, Any] | None,
) -> dict[str, Any]:
    state_seen = (state or {}).get("seen_fingerprint_count")
    viewport_unique = (viewports or {}).get("unique_note_fingerprints_in_viewports")
    archive_notes = ((archive_outputs or {}).get("counts") or {}).get("notes")
    merged_notes = ((merged_archive or {}).get("counts") or {}).get("notes")

    values = {
        "state_seen": state_seen,
        "viewport_unique": viewport_unique,
        "archive_output_notes": archive_notes,
        "merged_archive_notes": merged_notes,
    }
    comparable = {key: value for key, value in values.items() if isinstance(value, int)}
    expected = max(comparable.values()) if comparable else None
    mismatches = {
        key: value
        for key, value in comparable.items()
        if expected is not None and value != expected
    }
    return {
        "expected_count": expected,
        "values": values,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }


def build_report(
    *,
    folder_path: str,
    state_path: Path | None,
    viewport_patterns: list[str],
    archive_patterns: list[str],
    merged_archive_path: Path | None,
) -> dict[str, Any]:
    state = state_probe(state_path) if state_path else None
    viewport_paths = expand_paths(viewport_patterns)
    viewports = (
        compact_viewport_probe(viewport_paths, [folder_path], include_per_xml=False)
        if viewport_paths
        else None
    )
    if viewports:
        viewports.pop("_unique_fingerprints", None)
        viewports.pop("_stable_tappable_fingerprints", None)
        viewports.pop("_checked_fingerprints", None)

    archive_paths = expand_paths(archive_patterns)
    archive_outputs = summarize_archive_outputs(archive_paths) if archive_paths else None
    merged_archive = summarize_merged_archive(merged_archive_path)
    mismatches = mismatch_summary(
        state=state,
        viewports=viewports,
        archive_outputs=archive_outputs,
        merged_archive=merged_archive,
    )
    return {
        "report_mode": "visible_batch_run_report",
        "privacy": "raw XML and note text are not printed",
        "folder_path": folder_path,
        "state": state,
        "viewports": viewports,
        "archive_outputs": archive_outputs,
        "merged_archive": merged_archive,
        "comparison": mismatches,
        "status": "ok" if mismatches["mismatch_count"] == 0 and (merged_archive or {}).get("status", "ok") == "ok" else "check",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize a visible-batch export run without printing raw note text.")
    parser.add_argument("--folder-path", required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--viewport-glob", action="append", default=[])
    parser.add_argument("--archive-output", action="append", default=[])
    parser.add_argument("--archive-glob", action="append", default=[])
    parser.add_argument("--merged-archive", type=Path)
    args = parser.parse_args(argv)

    archive_patterns = list(args.archive_output) + list(args.archive_glob)
    report = build_report(
        folder_path=args.folder_path,
        state_path=args.state,
        viewport_patterns=args.viewport_glob,
        archive_patterns=archive_patterns,
        merged_archive_path=args.merged_archive,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
