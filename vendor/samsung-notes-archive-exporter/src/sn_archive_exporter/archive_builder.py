from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .sdocx_metadata import extract_sdocx_metadata, parse_notes_filename_datetime


ARCHIVE_VERSION = "0.1"
INVALID_PATH_CHARS = re.compile(r'[<>:"\\|?*\x00-\x1f]')


@dataclass(frozen=True)
class ExportMapping:
    source: Path
    folder_path: str
    title: str | None = None
    note_id: str | None = None


def sanitize_path_part(value: str) -> str:
    cleaned = INVALID_PATH_CHARS.sub("_", value.replace("/", "_")).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned in {"", ".", ".."}:
        return "_"
    return cleaned.rstrip(". ")


def sanitize_folder_path(folder_path: str) -> Path:
    parts = [sanitize_path_part(part) for part in folder_path.split("/") if part.strip()]
    if not parts:
        return Path("_unfiled")
    return Path(*parts)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collision_safe_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 2
    while True:
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def load_mapping(mapping_path: Path, input_dir: Path) -> list[ExportMapping]:
    data = json.loads(mapping_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("notes"), list):
        raise ValueError("mapping JSON must contain a top-level notes array")

    mappings: list[ExportMapping] = []
    for index, item in enumerate(data["notes"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"notes[{index}] must be an object")
        if "source" not in item:
            raise ValueError(f"notes[{index}] is missing source")
        if "folder_path" not in item:
            raise ValueError(f"notes[{index}] is missing folder_path")

        source = Path(str(item["source"]))
        if not source.is_absolute():
            source = input_dir / source
        mappings.append(
            ExportMapping(
                source=source,
                folder_path=str(item["folder_path"]),
                title=str(item["title"]) if item.get("title") is not None else None,
                note_id=str(item["id"]) if item.get("id") is not None else None,
            )
        )
    return mappings


def folder_records(folder_paths: list[str]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for folder_path in folder_paths:
        parts = [part for part in folder_path.split("/") if part.strip()]
        current: list[str] = []
        parent_id: str | None = None
        for part in parts or ["_unfiled"]:
            current.append(part)
            path = "/".join(current)
            if path in seen:
                parent_id = seen[path]["id"]
                continue
            folder_id = f"folder-{len(seen) + 1:06d}"
            seen[path] = {
                "id": folder_id,
                "path": path,
                "safe_path": str(sanitize_folder_path(path)),
                "depth": len(current) - 1,
                "parent_id": parent_id,
                "source": "mapping",
                "warnings": [],
            }
            parent_id = folder_id
    return list(seen.values())


def build_archive(
    input_dir: Path,
    mapping_path: Path,
    output_dir: Path,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    mappings = load_mapping(mapping_path, input_dir)
    created_at = datetime.now(timezone.utc).isoformat()
    archive_dir = output_dir / "archive"

    folders = folder_records([mapping.folder_path for mapping in mappings])
    folder_by_path = {folder["path"]: folder for folder in folders}
    notes: list[dict[str, Any]] = []
    planned_copies: list[dict[str, str]] = []

    for index, mapping in enumerate(mappings, start=1):
        if not mapping.source.exists():
            raise FileNotFoundError(mapping.source)
        if not mapping.source.is_file():
            raise ValueError(f"source is not a file: {mapping.source}")

        folder_safe_path = sanitize_folder_path(mapping.folder_path)
        target_dir = archive_dir / folder_safe_path
        target_name = sanitize_path_part(mapping.source.name)
        target_path = collision_safe_path(target_dir / target_name)
        file_hash = sha256_file(mapping.source)
        size_bytes = mapping.source.stat().st_size
        note_id = mapping.note_id or f"note-{index:06d}"
        folder = folder_by_path.get(mapping.folder_path)

        if not dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(mapping.source, target_path)

        exported_file = {
            "path": target_path.relative_to(output_dir).as_posix(),
            "format": mapping.source.suffix.lower().lstrip(".") or "unknown",
            "sha256": file_hash,
            "size_bytes": size_bytes,
            "source_path": str(mapping.source),
        }
        filename_datetime = parse_notes_filename_datetime(mapping.source)
        if filename_datetime:
            exported_file["filename_datetime"] = filename_datetime
        sdocx_metadata = extract_sdocx_metadata(mapping.source)
        if sdocx_metadata:
            exported_file["sdocx_metadata"] = sdocx_metadata
        notes.append(
            {
                "id": note_id,
                "title": mapping.title or mapping.source.stem,
                "display_datetime": (
                    sdocx_metadata.get("inferred_display_datetime") if sdocx_metadata else filename_datetime
                ),
                "folder_id": folder["id"] if folder else None,
                "folder_path": mapping.folder_path,
                "exported_files": [exported_file],
                "conversion_status": "not_converted",
                "warnings": [],
            }
        )
        planned_copies.append({"source": str(mapping.source), "target": str(target_path)})

    manifest = {
        "source": "Samsung Notes",
        "archive_version": ARCHIVE_VERSION,
        "export_mode": "manual_save_as_file",
        "created_at": created_at,
        "dry_run": dry_run,
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
        (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (output_dir / "folders.json").write_text(json.dumps(folders_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (output_dir / "notes_index.json").write_text(json.dumps(notes_index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "dry_run": dry_run,
        "planned_copies": planned_copies,
        "manifest": manifest,
        "folders": folders_doc,
        "notes_index": notes_index,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a folder-preserving Samsung Notes archive.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Build an archive from exported files and a mapping JSON.")
    build.add_argument("--input", required=True, type=Path, help="Directory containing exported files.")
    build.add_argument("--mapping", required=True, type=Path, help="JSON mapping file.")
    build.add_argument("--output", required=True, type=Path, help="Output archive directory.")
    build.add_argument("--dry-run", action="store_true", help="Print planned operations without copying files.")

    merge = subparsers.add_parser("merge-folder-archives", help="Merge per-folder folder-walk archives into one archive.")
    merge.add_argument(
        "--run-summary",
        required=True,
        action="append",
        type=Path,
        help="Folder walk run_summary.json path. Repeat for partitioned/resumed runs.",
    )
    merge.add_argument("--output", required=True, type=Path, help="Merged archive output directory.")
    merge.add_argument("--dry-run", action="store_true", help="Print planned operations without copying files.")
    merge.add_argument("--allow-existing-output", action="store_true", help="Allow writing into an existing output directory.")
    merge.add_argument("--summary-only", action="store_true", help="Print compact merge counts instead of full manifests.")

    direct_merge = subparsers.add_parser(
        "merge-archive-outputs",
        help="Merge explicitly listed archive output directories into one archive.",
    )
    direct_merge.add_argument(
        "--archive-output",
        required=True,
        action="append",
        type=Path,
        help="Archive output directory containing manifest.json. Repeat for visible-batch archives.",
    )
    direct_merge.add_argument(
        "--folder-path",
        action="append",
        default=[],
        help="Visited folder path to preserve even if it has no notes. Repeat as needed.",
    )
    direct_merge.add_argument("--output", required=True, type=Path, help="Merged archive output directory.")
    direct_merge.add_argument("--dry-run", action="store_true", help="Print planned operations without copying files.")
    direct_merge.add_argument(
        "--allow-existing-output",
        action="store_true",
        help="Allow writing into an existing output directory.",
    )
    direct_merge.add_argument("--summary-only", action="store_true", help="Print compact merge counts instead of full manifests.")

    report = subparsers.add_parser("visible-batch-report", help="Compare visible-batch state, viewport, and archive counts.")
    report.add_argument("--folder-path", required=True)
    report.add_argument("--state", type=Path)
    report.add_argument("--viewport-glob", action="append", default=[])
    report.add_argument("--archive-output", action="append", default=[])
    report.add_argument("--archive-glob", action="append", default=[])
    report.add_argument("--merged-archive", type=Path)

    args = parser.parse_args(argv)
    if args.command == "build":
        result = build_archive(args.input, args.mapping, args.output, dry_run=args.dry_run)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "merge-folder-archives":
        from .archive_merger import merge_folder_archives_from_summaries

        result = merge_folder_archives_from_summaries(
            args.run_summary,
            args.output,
            dry_run=args.dry_run,
            allow_existing_output=args.allow_existing_output,
        )
        if args.summary_only:
            result = {
                "dry_run": result["dry_run"],
                "run_summary_path": result["run_summary_path"],
                "run_summary_count": len(result["run_summary_paths"]),
                "archive_output_count": len(result["archive_outputs"]),
                "planned_copy_count": len(result["planned_copies"]),
                "counts": result["manifest"]["counts"],
            }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "merge-archive-outputs":
        from .archive_merger import merge_folder_archive_outputs

        result = merge_folder_archive_outputs(
            args.archive_output,
            args.output,
            dry_run=args.dry_run,
            allow_existing_output=args.allow_existing_output,
            folder_paths=args.folder_path,
        )
        if args.summary_only:
            result = {
                "dry_run": result["dry_run"],
                "archive_output_count": len(result["archive_outputs"]),
                "planned_copy_count": len(result["planned_copies"]),
                "counts": result["manifest"]["counts"],
            }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "visible-batch-report":
        from .visible_batch_report import build_report

        report = build_report(
            folder_path=args.folder_path,
            state_path=args.state,
            viewport_patterns=args.viewport_glob,
            archive_patterns=list(args.archive_output) + list(args.archive_glob),
            merged_archive_path=args.merged_archive,
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["status"] == "ok" else 1
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
