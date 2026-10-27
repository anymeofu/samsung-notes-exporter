# Batch Export Test Runbook

Purpose: test a small multi-note export without deleting, moving, uploading, or inspecting note contents.

## Preconditions

- Use harmless notes only.
- Keep Samsung Notes source notes untouched.
- Use the preferred local route:

```text
selection mode
→ More
→ Save as file
→ Samsung Notes file
→ Samsung My Files destination picker
→ public local folder
```

## Recommended Test

1. Open a folder with two or three harmless notes.
2. Enter selection mode.
3. Select two or three notes.
4. Choose More → Save as file → Samsung Notes file.
5. Save into a public local folder such as `Documents` or `Download/SamsungNotesExportTest`.
6. Do not choose messaging, email, Drive, Quick Share, or any upload/send target.
7. Run:

```bash
./scripts/adb_find_sdocx_exports.sh
```

8. Identify newly created `.sdocx` paths by timestamp.
9. Pull exact paths copy-only:

```bash
BATCH_NAME=batch_001 ./scripts/adb_pull_sdocx_exports.sh \
  /sdcard/Documents/Notes_260101_120000.sdocx \
  /sdcard/Documents/Notes_260101_120015.sdocx
```

10. Create a mapping JSON in `input_exports/batch_001/mapping.json`.
11. Build a dry-run archive:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter build \
  --input input_exports/batch_001 \
  --mapping input_exports/batch_001/mapping.json \
  --output output_archive/batch_001 \
  --dry-run
```

12. Build the archive after reviewing the dry-run:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter build \
  --input input_exports/batch_001 \
  --mapping input_exports/batch_001/mapping.json \
  --output output_archive/batch_001
```

## What To Record

- Number of notes selected.
- Number of `.sdocx` files produced.
- Whether Samsung Notes creates one file per note or a bundled export.
- Filename pattern.
- Whether duplicate filenames are created, overwritten, or auto-suffixed.
- Folder path used for the mapping.

## Stop Conditions

- Any UI asks to upload, send, sync, share externally, or grant broad new permissions.
- The destination is not a local My Files picker.
- The selected notes are not harmless.
