from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .archive_builder import ARCHIVE_VERSION, collision_safe_path, folder_records, sha256_file
from .guarded_export_driver import ensure_output_targets_available
from .sdocx_metadata import extract_sdocx_metadata, parse_notes_filename_datetime


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_archive_outputs(tree: dict[str, Any]) -> list[Path]:
    outputs: list[Path] = []

    def visit(node: dict[str, Any]) -> None:
        export = node.get("export") or {}
        handoff = export.get("handoff") or {}
        archive_output = handoff.get("archive_output")
        if archive_output:
            outputs.append(Path(archive_output))
        for child in node.get("children") or []:
            if isinstance(child, dict):
                visit(child)

    visit(tree)
    seen: set[Path] = set()
    unique: list[Path] = []
    for output in outputs:
        if output in seen:
            continue
        seen.add(output)
        unique.append(output)
    return unique


def collect_folder_paths(tree: dict[str, Any]) -> list[str]:
    paths: list[str] = []

    def visit(node: dict[str, Any]) -> None:
        if node.get("dry_run"):
            return
        folder_path = node.get("folder_path")
        if folder_path:
            paths.append(str(folder_path))
        if node.get("skipped"):
            return
        for child in node.get("children") or []:
            if isinstance(child, dict):
                visit(child)

    if tree:
        visit(tree)

    seen: set[str] = set()
    unique: list[str] = []
    for folder_path in paths:
        if folder_path in seen:
            continue
        seen.add(folder_path)
        unique.append(folder_path)
    return unique


def collect_archive_outputs_from_summaries(run_summary_paths: list[Path]) -> list[Path]:
    outputs: list[Path] = []
    seen: set[Path] = set()
    for run_summary_path in run_summary_paths:
        run_summary = load_json(run_summary_path)
        for output in collect_archive_outputs(run_summary.get("tree") or {}):
            if output in seen:
                continue
            seen.add(output)
            outputs.append(output)
    return outputs


def collect_folder_paths_from_summaries(run_summary_paths: list[Path]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for run_summary_path in run_summary_paths:
        run_summary = load_json(run_summary_path)
        for folder_path in collect_folder_paths(run_summary.get("tree") or {}):
            if folder_path in seen:
                continue
            seen.add(folder_path)
            paths.append(folder_path)
    return paths


def merge_folder_archive_outputs(
    archive_outputs: list[Path],
    output_dir: Path,
    *,
    dry_run: bool,
    allow_existing_output: bool = False,
    run_summary_paths: list[Path] | None = None,
    folder_paths: list[str] | None = None,
) -> dict[str, Any]:
    if not dry_run:
        ensure_output_targets_available(None, output_dir, allow_existing_output=allow_existing_output)

    run_summary_paths = run_summary_paths or []
    run_summary_path_strings = [str(path) for path in run_summary_paths]

    notes: list[dict[str, Any]] = []
    planned_copies: list[dict[str, str]] = []
    source_manifests: list[str] = []
    used_note_ids: set[str] = set()

    for archive_output in archive_outputs:
        manifest_path = archive_output / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"missing per-folder manifest: {manifest_path}")
        source_manifest = load_json(manifest_path)
        source_manifests.append(str(manifest_path))
        for source_note in source_manifest.get("notes") or []:
            merged_note = dict(source_note)
            original_id = str(merged_note.get("id") or "")
            note_id = original_id
            if not note_id or note_id in used_note_ids:
                note_id = f"merged-note-{len(used_note_ids) + 1:06d}"
            used_note_ids.add(note_id)
            merged_note["id"] = note_id
            warnings = list(merged_note.get("warnings") or [])
            if original_id and original_id != note_id:
                warnings.append(f"renamed_duplicate_note_id:{original_id}")
            merged_files = []
            for exported_file in source_note.get("exported_files") or []:
                relative_path = Path(str(exported_file["path"]))
                source_file = archive_output / relative_path
                if not source_file.exists():
                    raise FileNotFoundError(f"missing archived file: {source_file}")
                target_path = collision_safe_path(output_dir / relative_path)
                if not dry_run:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source_file, target_path)
                planned_copies.append({"source": str(source_file), "target": str(target_path)})
                merged_export = dict(exported_file)
                merged_export["path"] = target_path.relative_to(output_dir).as_posix()
                merged_export["sha256"] = sha256_file(source_file)
                merged_export["size_bytes"] = source_file.stat().st_size
                merged_export["source_archive"] = str(archive_output)
                if "filename_datetime" not in merged_export:
                    filename_datetime = parse_notes_filename_datetime(source_file)
                    if filename_datetime:
                        merged_export["filename_datetime"] = filename_datetime
                if "sdocx_metadata" not in merged_export:
                    sdocx_metadata = extract_sdocx_metadata(source_file)
                    if sdocx_metadata:
                        merged_export["sdocx_metadata"] = sdocx_metadata
                merged_files.append(merged_export)
            merged_note["exported_files"] = merged_files
            if merged_note.get("display_datetime") is None:
                first_metadata = (merged_files[0].get("sdocx_metadata") if merged_files else None) or {}
                merged_note["display_datetime"] = first_metadata.get("inferred_display_datetime") or (
                    merged_files[0].get("filename_datetime") if merged_files else None
                )
            merged_note["warnings"] = warnings
            notes.append(merged_note)

    merged_folder_paths = list(folder_paths or [])
    merged_folder_paths.extend(str(note.get("folder_path") or "") for note in notes)
    folders = folder_records(merged_folder_paths)
    folder_by_path = {folder["path"]: folder for folder in folders}
    for note in notes:
        folder = folder_by_path.get(str(note.get("folder_path") or ""))
        note["folder_id"] = folder["id"] if folder else None

    manifest = {
        "source": "Samsung Notes",
        "archive_version": ARCHIVE_VERSION,
        "export_mode": "folder_walk_merge",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "run_summary_path": run_summary_path_strings[0] if run_summary_path_strings else None,
        "run_summary_paths": run_summary_path_strings,
        "source_manifests": source_manifests,
        "device": {
            "manufacturer": "samsung",
            "model": "SM-S947N",
            "android_version": "16",
            "samsung_notes_version": "4.4.41.9",
        },
        "counts": {
            "folders": len(folders),
            "notes": len(notes),
            "files": sum(len(note["exported_files"]) for note in notes),
        },
        "notes": notes,
    }
    folders_doc = {"folders": folders}
    notes_index = {"notes": notes}

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output_dir / "folders.json").write_text(json.dumps(folders_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output_dir / "notes_index.json").write_text(json.dumps(notes_index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "dry_run": dry_run,
        "run_summary_path": run_summary_path_strings[0] if run_summary_path_strings else None,
        "run_summary_paths": run_summary_path_strings,
        "archive_outputs": [str(path) for path in archive_outputs],
        "planned_copies": planned_copies,
        "manifest": manifest,
        "folders": folders_doc,
        "notes_index": notes_index,
    }


def merge_folder_archives(
    run_summary_path: Path,
    output_dir: Path,
    *,
    dry_run: bool,
    allow_existing_output: bool = False,
) -> dict[str, Any]:
    return merge_folder_archives_from_summaries(
        [run_summary_path],
        output_dir,
        dry_run=dry_run,
        allow_existing_output=allow_existing_output,
    )


def merge_folder_archives_from_summaries(
    run_summary_paths: list[Path],
    output_dir: Path,
    *,
    dry_run: bool,
    allow_existing_output: bool = False,
) -> dict[str, Any]:
    archive_outputs = collect_archive_outputs_from_summaries(run_summary_paths)
    folder_paths = collect_folder_paths_from_summaries(run_summary_paths)
    return merge_folder_archive_outputs(
        archive_outputs,
        output_dir,
        dry_run=dry_run,
        allow_existing_output=allow_existing_output,
        run_summary_paths=run_summary_paths,
        folder_paths=folder_paths,
    )
