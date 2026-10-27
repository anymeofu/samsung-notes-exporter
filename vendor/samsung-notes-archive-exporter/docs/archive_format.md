# Archive Format

## Goals

- Preserve Samsung Notes folder and subfolder structure as local directories.
- Preserve original-ish official export files such as `.sdocx`, `.pdf`, `.docx`, or `.txt`.
- Keep enough metadata for later conversion without making conversion part of the MVP.
- Avoid destructive operations on source exports.

## Directory Layout

```text
output_archive/
  manifest.json
  folders.json
  notes_index.json
  archive/
    Folder A/
      note_001.sdocx
      note_001.pdf
    Folder A/Subfolder B/
      note_002.sdocx
```

## manifest.json

`manifest.json` is the top-level archive record.

```json
{
  "source": "Samsung Notes",
  "archive_version": "0.1",
  "export_mode": "ui_automation",
  "created_at": "2026-06-29T00:00:00Z",
  "device": {
    "manufacturer": null,
    "model": null,
    "android_version": null,
    "samsung_notes_version": null
  },
  "counts": {
    "folders": 0,
    "notes": 0,
    "files": 0
  },
  "notes": []
}
```

## folders.json

`folders.json` records the folder tree independently from files.

```json
{
  "folders": [
    {
      "id": "folder-000001",
      "path": "Folder A",
      "depth": 0,
      "parent_id": null,
      "source": "ui_observed",
      "warnings": []
    },
    {
      "id": "folder-000002",
      "path": "Folder A/Subfolder B",
      "depth": 1,
      "parent_id": "folder-000001",
      "source": "ui_observed",
      "warnings": []
    }
  ]
}
```

## notes_index.json

`notes_index.json` is optimized for later lookup and conversion.

```json
{
  "notes": [
    {
      "id": "note-000001",
      "title": "Some Note",
      "folder_id": "folder-000002",
      "folder_path": "Folder A/Subfolder B",
      "exported_files": [
        {
          "path": "archive/Folder A/Subfolder B/note_000001.sdocx",
          "format": "sdocx",
          "sha256": "unknown",
          "size_bytes": null,
          "source_path": null,
          "sdocx_metadata": {
            "filename_datetime": "2026-05-05 01:56:48",
            "zip_note_datetime": "2026-05-05 01:56:48",
            "zip_page_datetimes": ["2026-05-05 00:50:22"],
            "zip_distinct_datetimes": ["2026-05-05 00:50:22", "2026-05-05 01:56:48"],
            "inferred_display_datetime": "2026-05-05 01:56:48",
            "warnings": []
          }
        }
      ],
      "display_datetime": "2026-05-05 01:56:48",
      "conversion_status": "not_converted",
      "warnings": []
    }
  ]
}
```

## Filename and Path Rules

Folder and note titles may contain characters that are invalid or awkward on local filesystems. The archive builder should:

- Normalize path separators by replacing `/` and `:` with safe substitutes.
- Trim leading and trailing whitespace.
- Avoid reserved names such as `.` and `..`.
- Preserve the original title separately in manifest metadata.
- Use generated IDs when names collide.
- Never overwrite an existing archive file without an explicit collision suffix or user approval.

Suggested collision suffix:

```text
Some Note.sdocx
Some Note (2).sdocx
Some Note (3).sdocx
```

For stable machine identifiers, prefer deterministic IDs from normalized `folder_path`, note title, export batch, and file hash once available.

## Export Format Notes

Observed for `.sdocx`:

- Samsung Notes `.sdocx` exports are zip files in tested samples.
- Filename pattern `Notes_YYMMDD_HHMMSS.sdocx` matches the zip timestamp of `note.note` in tested samples.
- Real exports may also use note-title-based filenames such as `<title>_YYMMDD_HHMMSS.sdocx`; these are accepted when the generated filename is filesystem-safe and are preserved in the archive path.
- Page files may have an earlier zip timestamp than `note.note`; this is a candidate for page/note creation or last page update time, but it is not yet labeled by Samsung documentation.
- The archive records these as source-specific metadata fields rather than claiming they are definitely created/modified dates.

Initial expectation, pending broader format testing:

- `.sdocx`: likely best candidate for original Samsung Notes preservation.
- `.pdf`: useful visual snapshot, may preserve handwriting and layout.
- `.docx`: useful for text and images, may alter layout.
- `.txt`: useful fallback for body text only.

These are hypotheses until tested with harmless sample notes.

## Non-goals

- Markdown conversion.
- Obsidian vault generation.
- Trellis import.
- OCR.
- AI summarization.
- Semantic classification.

## MVP Builder Status

Implemented command shape:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter build \
  --input input_exports/manual_test_001 \
  --mapping input_exports/manual_test_001/mapping.json \
  --output output_archive/manual_test_001 \
  --dry-run
```

The builder:

- Copies source exports into `archive/<folder_path>/`.
- Preserves Samsung Notes export filenames in the archive path, subject only to filesystem sanitization and collision suffixes.
- Leaves source export files untouched.
- Supports dry-run.
- Generates `manifest.json`, `folders.json`, and `notes_index.json`.
- Records SHA-256 and file size.
- Sanitizes folder path parts for local filesystems.
- Handles existing target filename collisions with numbered suffixes.

Current limitation: mapping JSON is manual/user-provided. UI traversal is not yet generating mappings automatically.

See `samples/batch_mapping_example.json` for a synthetic multi-note mapping example.

## Folder Walk Merge

Guarded folder walking may create one archive per visited note-containing folder under `output_archive/<run-id>/<folder-slug>/`. Merge those per-folder archives into one final archive with:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter merge-folder-archives \
  --run-summary output_archive/<run-id>/run_summary.json \
  --output output_archive/<run-id>/merged_archive \
  --summary-only
```

Use `--dry-run` to inspect planned copies. Existing merge output directories are refused by default; pass `--allow-existing-output` only for intentional debug/resume use.

For partitioned or resumed folder walks, repeat `--run-summary` once per successful partial run:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter merge-folder-archives \
  --run-summary output_archive/<run-id-a>/run_summary.json \
  --run-summary output_archive/<run-id-b>/run_summary.json \
  --output output_archive/<merged-run-id> \
  --summary-only
```

Duplicate per-folder archive outputs are deduplicated during merge, so retry plans can include overlapping successful run summaries without duplicating copied files.

When a `run_summary.json` is available, merge output preserves visited folder paths in `folders.json` even if a visited folder has no exported notes. Files are still copied only for exported notes.

Verified locally:

- Single-note `.sdocx` archive build.
- Multi-note single-folder archive build.
- Multi-note archive build split across two folder paths from one pulled batch.
- Real two-folder `.sdocx` archive build using user-provided Samsung Notes paths.
- Synthetic per-folder archive merge using `run_summary.json`.
- Synthetic multi-run archive merge using repeated `--run-summary`.
- Real dummy merge preserving visited empty folders in `folders.json`.
