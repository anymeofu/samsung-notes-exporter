from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_archive(archive_dir: Path) -> dict[str, Any]:
    manifest_path = archive_dir / "manifest.json"
    folders_path = archive_dir / "folders.json"
    notes_index_path = archive_dir / "notes_index.json"
    errors: list[str] = []
    warnings: list[str] = []

    for required in (manifest_path, folders_path, notes_index_path):
        if not required.exists():
            errors.append(f"missing required file: {required.relative_to(archive_dir)}")
    if errors:
        return {"status": "error", "archive_dir": str(archive_dir), "errors": errors, "warnings": warnings}

    manifest = load_json(manifest_path)
    folders = load_json(folders_path)
    notes_index = load_json(notes_index_path)

    notes = manifest.get("notes") or []
    folder_entries = folders.get("folders") or []
    note_index_entries = notes_index.get("notes") or []
    file_count = 0
    folder_paths = {folder.get("path") for folder in folder_entries}
    note_ids = set()
    note_folder_paths: set[str] = set()
    notes_with_display_datetime = 0
    files_with_sdocx_metadata = 0

    counts = manifest.get("counts") or {}
    if counts.get("folders") != len(folder_entries):
        errors.append(f"folder count mismatch: manifest={counts.get('folders')} actual={len(folder_entries)}")
    if counts.get("notes") != len(notes):
        errors.append(f"note count mismatch: manifest={counts.get('notes')} actual={len(notes)}")
    if len(note_index_entries) != len(notes):
        errors.append(f"notes_index count mismatch: index={len(note_index_entries)} manifest={len(notes)}")

    for note in notes:
        note_id = note.get("id")
        if not note_id:
            errors.append("note missing id")
        elif note_id in note_ids:
            errors.append(f"duplicate note id: {note_id}")
        else:
            note_ids.add(note_id)
        folder_path = note.get("folder_path")
        if folder_path not in folder_paths:
            errors.append(f"note {note_id or '<missing>'} references missing folder_path: {folder_path!r}")
        elif isinstance(folder_path, str):
            note_folder_paths.add(folder_path)
        if note.get("display_datetime"):
            notes_with_display_datetime += 1
        exported_files = note.get("exported_files") or []
        if not exported_files:
            warnings.append(f"note {note_id or '<missing>'} has no exported files")
        for exported in exported_files:
            file_count += 1
            relative = exported.get("path")
            if not relative:
                errors.append(f"note {note_id or '<missing>'} has exported file without path")
                continue
            source_name = Path(str(exported.get("source_path") or exported.get("path") or "")).name
            archived_name = Path(str(relative)).name
            if source_name and source_name != archived_name and not archived_name.startswith(f"{Path(source_name).stem} "):
                warnings.append(
                    f"archived filename differs from source for note {note_id or '<missing>'}: "
                    f"source={source_name!r} archived={archived_name!r}"
                )
            if exported.get("sdocx_metadata"):
                files_with_sdocx_metadata += 1
            path = archive_dir / relative
            if not path.exists():
                errors.append(f"missing exported file: {relative}")
                continue
            expected_hash = exported.get("sha256")
            actual_hash = sha256_file(path)
            if expected_hash != actual_hash:
                errors.append(f"sha256 mismatch for {relative}: manifest={expected_hash} actual={actual_hash}")
            expected_size = exported.get("size_bytes")
            if expected_size is not None and expected_size != path.stat().st_size:
                errors.append(f"size mismatch for {relative}: manifest={expected_size} actual={path.stat().st_size}")

    if counts.get("files") != file_count:
        errors.append(f"file count mismatch: manifest={counts.get('files')} actual={file_count}")
    empty_folder_paths = sorted(str(path) for path in folder_paths - note_folder_paths if path)

    return {
        "status": "error" if errors else "ok",
        "archive_dir": str(archive_dir),
        "counts": {
            "folders": len(folder_entries),
            "notes": len(notes),
            "files": file_count,
        },
        "quality": {
            "notes_with_display_datetime": notes_with_display_datetime,
            "notes_missing_display_datetime": len(notes) - notes_with_display_datetime,
            "files_with_sdocx_metadata": files_with_sdocx_metadata,
            "empty_folder_count": len(empty_folder_paths),
            "empty_folder_paths": empty_folder_paths,
        },
        "errors": errors,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a Samsung Notes local archive.")
    parser.add_argument("archive_dir", type=Path)
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args(argv)

    result = validate_archive(args.archive_dir)
    if args.summary_only:
        result = {
            "status": result["status"],
            "archive_dir": result["archive_dir"],
            "counts": result.get("counts"),
            "quality": result.get("quality"),
            "error_count": len(result.get("errors") or []),
            "warning_count": len(result.get("warnings") or []),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
