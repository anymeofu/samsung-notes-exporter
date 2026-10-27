# Final Migration Report

## Scope

- Device: user-reported Galaxy S26 Plus, ADB model `SM-S947N`
- Android: `16`
- Samsung Notes: `4.4.41.9`
- Computer: macOS
- Export route: Samsung Notes visible UI → Save as file → public local Documents → copy-only ADB pull
- Primary format: `.sdocx`
- Derived format tested separately: `.txt`

## Final Archives

Personal-only SDOCX archive:

```text
output_archive/personal_sdocx_archive_final_20260711
```

Validated counts:

```text
folders: 52
notes: 871
files: 871
display_datetime: 871/871
sdocx metadata: 871/871
errors: 0
```

Supplemental TXT archive:

```text
output_archive/personal_txt_archive_final_20260711
```

TXT reconciliation:

```text
source personal notes: 871
TXT files: 868
confirmed text-empty SDOCX-only notes: 3
unexplained omissions: 0
TXT dates: 868/868
```

The three text-empty notes are accounted for by their preserved SDOCX files. Artificial empty TXT placeholders were not created.

## Folder Preservation

The personal SDOCX archive preserves the folder path in `manifest.json`, `folders.json`, and the local `archive/` tree. Direct notes in parent folders and notes in nested folders are represented separately. Empty observed folders are retained in the folder index.

## Automation Verification

The harmless `Codex` test tree was processed end to end without step-by-step steering:

- 7 folder records
- 13 SDOCX notes/files
- 3 empty folders preserved
- validator errors: 0
- validator warnings: 0
- same-state resume: complete, with no duplicate export
- start from `Codex/Export` → node-based navigation to `Codex`: passed

## Safety Review

- No root, Knox bypass, private database access, or private cloud API was used.
- No Samsung Notes content was uploaded or externally transmitted.
- No source note was deleted, moved, or modified by the exporter.
- Generated archives, screenshots, UI dumps, and reconciliation data are ignored by Git.
- GitHub repository remains private.

## Known Limitations

- Samsung Notes UI labels, resource IDs, coordinate geometry, and export behavior may vary by device, language, screen size, and app version.
- One harmless dummy folder with unusual behavior remains a deferred UI edge case.
- TXT is supplemental and is not a lossless replacement for SDOCX.
- A filename normalization warning remains for one Samsung-generated filename with a leading space.

## Reproduction Checks

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m sn_archive_exporter.archive_validator output_archive/personal_sdocx_archive_final_20260711
PYTHONPATH=src python3 -m sn_archive_exporter.archive_validator output_archive/personal_txt_archive_final_20260711
```
