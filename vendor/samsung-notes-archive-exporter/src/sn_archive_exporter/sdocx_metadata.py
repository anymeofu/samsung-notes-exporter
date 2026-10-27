from __future__ import annotations

import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


FILENAME_DATE_RE = re.compile(r"(?:^|_)(\d{6})_(\d{6})(?= \(\d+\)|\.[^.]+$|$)")


def iso_from_zip_datetime(value: tuple[int, int, int, int, int, int]) -> str:
    return datetime(*value).isoformat(sep=" ")


def parse_notes_filename_datetime(path: Path) -> str | None:
    matches = list(FILENAME_DATE_RE.finditer(path.name))
    if not matches:
        return None
    match = matches[-1]
    return datetime.strptime(f"20{match.group(1)}{match.group(2)}", "%Y%m%d%H%M%S").isoformat(sep=" ")


def extract_sdocx_metadata(path: Path) -> dict[str, Any]:
    if path.suffix.lower() != ".sdocx":
        return {}
    metadata: dict[str, Any] = {
        "filename_datetime": parse_notes_filename_datetime(path),
        "zip_note_datetime": None,
        "zip_page_datetimes": [],
        "zip_distinct_datetimes": [],
        "inferred_display_datetime": None,
        "warnings": [],
    }
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile:
        metadata["warnings"].append("sdocx_not_zip")
        return metadata

    note_entry = next((item for item in entries if item.filename == "note.note"), None)
    page_entries = [item for item in entries if item.filename.endswith(".page")]
    if note_entry is not None:
        metadata["zip_note_datetime"] = iso_from_zip_datetime(note_entry.date_time)
    metadata["zip_page_datetimes"] = sorted({iso_from_zip_datetime(item.date_time) for item in page_entries})
    metadata["zip_distinct_datetimes"] = sorted({iso_from_zip_datetime(item.date_time) for item in entries})
    metadata["inferred_display_datetime"] = (
        metadata["filename_datetime"]
        or metadata["zip_note_datetime"]
        or (metadata["zip_page_datetimes"][0] if metadata["zip_page_datetimes"] else None)
    )
    return metadata
