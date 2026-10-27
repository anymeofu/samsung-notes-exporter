# Samsung Notes Archive Exporter

Local migration tooling for exporting personal Samsung Notes into a folder-preserving archive.

This project starts from a conservative premise: do not root the device, bypass Knox, reverse engineer Samsung Cloud private APIs, copy private app databases, upload data, delete data, or modify notes. The first usable target is a read-only, user-visible workflow that observes Samsung Notes folder structure and prepares a local archive format for official export files such as `.sdocx`, `.pdf`, `.docx`, or `.txt`.

## Current Status

This is an early alpha release. The current-device migration, folder-preserving archive, and harmless end-to-end automation replay are complete. The project is intentionally conservative and version-sensitive; review the code before granting ADB access.

Before using this on important notes, make a normal Samsung/Samsung Cloud/device backup first. This project is designed to avoid deleting, moving, modifying, uploading, or reading private app databases, but UI automation is still powerful and version-sensitive.

Implemented so far:

- Project documentation scaffold and phase-by-phase plan.
- Read-only ADB probe and public-storage filename search scripts.
- UI hierarchy dump helper.
- Archive Builder MVP with manifest, folder index, notes index, hashes, dry-run, and copy-only behavior.
- Guarded Samsung Notes Save as file automation for `.sdocx` and TXT.
- Guarded all-select export for the current folder.
- Guarded folder walker for visible/expanded subfolders, including the observed `모두 보기` expansion control.
- Screenshot-first compact UI observer that saves raw screenshots/XML locally but prints only compact candidate metadata.
- Stateful root export runner with resume/seed support and fast visible completion verification.

Out of scope for this alpha:

- Markdown or Obsidian conversion.
- OCR, AI summarization, semantic classification, or cloud sync.
- Universal support for other Samsung Notes versions or devices.

The primary archive is `.sdocx`, because it is the most original export observed in this project. TXT is a separate derived archive for text-first workflows. Samsung Notes may create no TXT file for a note with no text content; those notes remain accounted for by their preserved `.sdocx` source and are not replaced with artificial empty TXT files.

## Safety Rules

- Work only with the user's personal notes and device.
- Default to dry-run and read-only behavior.
- Do not delete, move, modify, upload, or externally transmit note data.
- Do not read or copy `/data/data/com.samsung.android.app.notes` contents.
- Do not store personal note contents in logs.
- Record what is observed separately from what is uncertain.
- Review `SECURITY.md` before running any real-device command.

## Repository Layout

```text
samsung-notes-archive-exporter/
  README.md
  AGENTS.md
  docs/
    project_status.md
    decision_log.md
    threat_model.md
    device_probe.md
    samsung_notes_ui_map.md
    folder_tree_capture.md
    export_flow_notes.md
    archive_format.md
  scripts/
    adb_probe.sh
    adb_find_public_notes.sh
    dump_ui.sh
  src/
    sn_archive_exporter/
      __init__.py
  tests/
  samples/
    README.md
```

## Prerequisites

- macOS development machine.
- Android platform tools installed, especially `adb`.
- User-owned Android Galaxy device with USB debugging enabled.
- User approval before running any ADB command.

## Install

The archive builder can be installed locally without third-party runtime dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
sn-archive-builder --help
```

The guarded Android automation remains an expert workflow. It requires `adb`, USB debugging, a user-owned device, a harmless test folder for the first run, and explicit review before `--execute`.

The current automation was developed against a Korean Samsung Notes UI on a user-reported Galaxy S26 Plus / ADB model `SM-S947N` from macOS. Other devices, languages, screen sizes, or Samsung Notes versions may need UI-map and coordinate adjustments. See `docs/prompts/` for prompts that help another assistant review or adapt the project to a different environment.

Check whether `adb` is available:

```bash
adb version
```

If Android Studio installed platform tools outside PATH, the scripts also check:

```text
~/Library/Android/sdk/platform-tools/adb
/opt/homebrew/bin/adb
/usr/local/bin/adb
```

## Read-only Scripts

These scripts are intended for observation only. They do not copy note files, modify device data, or access private Samsung Notes databases.

Run only after explicit approval:

```bash
./scripts/adb_probe.sh
```

This prints device and Samsung Notes package information for manual summarization into `docs/device_probe.md`.

```bash
./scripts/adb_find_public_notes.sh
```

This searches public storage paths for filenames that look like already-exported notes. It prints paths only and does not open file contents.

```bash
./scripts/adb_find_sdocx_exports.sh
```

This narrower helper lists public `.sdocx` candidates and basic file metadata only. Prefer it after confirming Samsung Notes can save `.sdocx` locally.

```bash
BATCH_NAME=batch_001 ./scripts/adb_pull_sdocx_exports.sh /sdcard/Documents/Notes_260101_120000.sdocx
```

This copy-only helper pulls exact `.sdocx` paths into ignored `input_exports/<batch>/`.

```bash
./scripts/dump_ui.sh main
```

This legacy helper dumps the currently visible Android UI hierarchy to `ui_dumps/main.xml`. Prefer the screenshot-first observer for normal work:

```bash
./scripts/observe_screen.sh codex_current
```

The observer saves a screenshot, raw XML dump, compact metadata, and an annotated SVG under ignored local directories. It prints compact metadata only; raw XML should be shared only through the escalation policy in `docs/screenshot_first_agent.md`.

For local debugging of the full compact candidate list:

```bash
PRINT_MODE=compact ./scripts/observe_screen.sh codex_current
```

## Expected Archive Output

The archive builder will eventually produce:

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

The MVP archive builder will copy files into a folder-preserving layout, record hashes, and generate manifests. It will not delete source exports or convert content.

## Personal Run Result

The private Galaxy S26 Plus/macOS test run produced:

- `.sdocx` source archive: 884 notes/files, including 13 harmless Codex dummy notes.
- Personal-only `.sdocx` archive: 871 notes/files in `output_archive/personal_sdocx_archive_final_20260711/`.
- Personal official-UI TXT archive: 868 files.
- Three text-empty notes were preserved as `.sdocx` only; unexplained TXT omissions: 0.
- TXT dates were preserved for 868/868 exported files.

Generated archives, note contents, screenshots, UI dumps, and reconciliation reports remain in ignored local directories. They must not be committed or uploaded.

## Archive Builder MVP

Create a mapping JSON that assigns exported files to original folder paths:

```json
{
  "notes": [
    {
      "id": "manual-test-001",
      "title": "Manual Save As File Test",
      "source": "Notes_260416_231358.sdocx",
      "folder_path": "Manual Test/Samsung Notes"
    }
  ]
}
```

A synthetic multi-note example is available at `samples/batch_mapping_example.json`.

Dry-run:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter build \
  --input input_exports/manual_test_001 \
  --mapping input_exports/manual_test_001/mapping.json \
  --output output_archive/manual_test_001 \
  --dry-run
```

Build:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter build \
  --input input_exports/manual_test_001 \
  --mapping input_exports/manual_test_001/mapping.json \
  --output output_archive/manual_test_001
```

Run tests:

```bash
python -m unittest discover -s tests
```

The current feasibility recommendation is documented in `docs/feasibility_report.md`.
For the next multi-note test, follow `docs/batch_export_test.md`.
The extraction-to-release roadmap is documented in `docs/finalization_plan.md`.
For device adaptation, connection recovery, large-folder limits, and rebuild guidance, use the prompts in `docs/prompts/` rather than copying this prototype's coordinates blindly.
For public sharing guidance, use `docs/public_release_plan.md`.

## Guarded Export Helpers

Dry-run the current allowed folder and print only compact counts:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter.guarded_export_driver \
  --allowed-path "Codex/Export" \
  --select-all \
  --summary-only
```

Dry-run folder walking from the current Samsung Notes folder:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter.folder_walk_driver \
  --root-path "Codex" \
  --run-id codex_summary_dryrun \
  --max-depth 1 \
  --summary-only \
  --observe-screens
```

Navigate from the current Samsung Notes folder to one exact top-level safe root, then run recursive export:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter.root_export_runner \
  --run-id my_guarded_run \
  --navigate-to-folder "Codex" \
  --recursive-current-folder \
  --max-depth 5 \
  --export-format sdocx \
  --execute \
  --summary-only
```

Top-level navigation resolves the navigation button and target folder row from local UI nodes, taps parsed bounds, and verifies the resulting breadcrumb. It refuses duplicate titles, nested target paths, missing targets, and path mismatches.

Use `--observe-screens` when you want local screenshot/metadata logs for each guarded step without sending raw XML to the model. Use `--execute` only when the phone is showing the expected folder and the user has approved the guarded UI actions. The drivers copy exported files; they do not delete or move source files.

## Before Running

For a new device, keep the first run read-only and use the adaptation prompts before exporting. Never test first on important notes. The expected initial workflow is:

1. Connect the Galaxy device.
2. Confirm USB debugging authorization on the phone.
3. Run `./scripts/adb_probe.sh`.
4. Summarize package and device facts in `docs/device_probe.md`.
5. Run public-storage filename search only if approved.

Do not attach raw screenshots, UI dumps, note titles, folder names, device serials, or archive files to public issues. See `SECURITY.md` and `CONTRIBUTING.md`.
