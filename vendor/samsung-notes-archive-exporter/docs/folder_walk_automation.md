# Folder Walk Automation

Goal: export each visited Samsung Notes folder with its own `folder_path`, then recurse into visible subfolders.

The walker is guarded by a required root breadcrumb. It refuses to act outside that root.

Dry-run the current folder:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter.folder_walk_driver \
  --root-path "Codex/Export" \
  --run-id codex_folder_walk_dryrun \
  --max-depth 5 \
  --summary-only \
  --observe-screens
```

Execute from the current folder:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter.folder_walk_driver \
  --root-path "Codex/Export" \
  --run-id codex_folder_walk_001 \
  --max-depth 5 \
  --execute
```

## Behavior

- Reads the current breadcrumb from `folderpath_text`.
- Exports notes in the current folder with guarded `--select-all`.
- Pulls newly exported `.sdocx` files copy-only into `input_exports/<run-id>/<folder-slug>/`.
- Builds a per-folder local archive under `output_archive/<run-id>/<folder-slug>/`.
- Writes a compact run summary to `output_archive/<run-id>/run_summary.json` by default.
- Reads visible subfolders from `sub_folder_list_item*`.
- If the current folder shows `모두 보기`, expands hidden subfolders before walking.
- Enters each visible subfolder, repeats the process, then uses Android back navigation and validates the parent breadcrumb.
- `--summary-only` prints compact counts instead of the full walked tree. This is preferred during repeated phone-side experiments.
- `--observe-screens` saves local screenshot-first observation artifacts for each guarded screen without printing raw XML or full compact metadata.
- Use `--run-summary-path <path>` to override the default summary location, or `--no-run-summary` to disable it.
- During `--execute`, per-folder pull/archive output directories must be new by default. Pick a fresh `--run-id`; use `--allow-existing-output` only for an intentional resume/debug run.
- Use `--skip-export` for traversal/recovery testing without creating more exported note files.
- Use `--max-folders N` for long recursive tests; extra child folders are recorded as `skipped: max_folder_limit`.
- Use `--mixed-folder-select-all` only after dummy-folder probe success. It enables guarded all-select plus selected-folder deselection for mixed folders.
- If a tapped folder candidate opens a non-list screen, the walker records `skipped: non_folder_screen_after_tap`, attempts to return to the parent, and continues.

## Current Limits

- Subfolder traversal currently sees only visible subfolders.
- If a folder still has more subfolders than one expanded visible screen, guarded subfolder scrolling can continue discovery.
- Notes are safer: observed `전체` can select off-screen notes in the current folder.
- Intermediate folders are exported too; do not treat only leaf folders as note-containing folders.
- Mixed folders are expected: a folder can contain both direct notes and subfolders. The walker exports direct notes for the current folder when note cards become visible during traversal, then continues subfolder traversal.

## Observed Test

2026-07-01 harmless test:

- Start folder: `Codex`.
- Visible subfolders: `Export`.
- Parent folder direct notes: 0.
- Walker entered `Codex/Export`.
- Child export selected 8 notes via all-select.
- Handoff pulled 8 `.sdocx` files copy-only.
- Archive output: `output_archive/codex_parent_walk_001/Codex__Export`.
- Archive counts: folders 2, notes 8, files 8.
- Back navigation returned to `Codex` and breadcrumb validation passed.

2026-07-01 hidden subfolder expansion test:

- Start folder: `Codex`.
- Before `모두 보기`: 12 subfolders visible.
- Expand control: `com.samsung.android.app.notes:id/expand_bar_layout`.
- After `모두 보기`: 21 subfolders visible.
- Dry-run planned all 21 child folder paths.
- Important guard: after expansion, the same control changes to `접기`; the walker does not tap it again.
- `--summary-only` dry-run output confirmed 21 root child folders without printing the full tree.
- `--observe-screens` dry-run confirmed per-step metadata is saved under `observations/` while stdout remains compact.

2026-07-01 mixed direct-note observation:

- Start folder: `Codex`.
- User added direct notes alongside subfolders.
- Top screen showed only subfolders.
- After scrolling, direct note cards became visible below the subfolder grid.
- Dry-run detected 2 direct note cards in `Codex` and recorded one direct-note page in the compact summary.
- Implementation note: current-folder note export cannot rely only on the first visible page.
- Default safety rule: do not use `전체` / all-select while subfolders are visible.
- Opt-in mixed-folder strategy: `--mixed-folder-select-all` can use all-select followed by selected-folder deselection and final verifier gates.
- Controlled export confirmed 2 direct notes were archived under `archive/Codex/`.

2026-07-07 mixed-folder all-select verifier:

- `Codex` mixed-folder probe-only succeeded twice with `selected_count=2` and no export.
- `Codex` mixed-folder full export succeeded once with 2 `.sdocx` files archived.
- Walker integration remains opt-in with `--mixed-folder-select-all`.

2026-07-07 limited depth-5 traversal:

- Command shape: `--max-depth 5 --max-folders 8 --skip-export --execute --summary-only`.
- Result: visited 8 folders, skipped 14 by `max_folder_limit`, exported 0 files.
- The phone returned to `Codex` after the run.

2026-07-07 bounded depth-5 export:

- Command shape: `--max-depth 5 --max-folders 8 --mixed-folder-select-all --execute --summary-only --quiet`.
- Result: visited 7 folders, max depth seen 2, skipped 0.
- Exported and pulled 13 `.sdocx` files from 4 note-containing folders:
  - `Codex`: 2 files
  - `Codex/Export`: 8 files
  - `Codex/폴더 13`: 2 files
  - `Codex/폴더 13/폴더 2`: 1 file
- All per-folder archives passed `archive_validator`.
- Merged archive: `output_archive/reduced_codex_depth5_export_retry2_20260707_merged`.
- Merged counts: 4 folder paths, 13 notes, 13 files, 13 `display_datetime` values.
- Run plan summary for the same run reports visited 7, exported 4, pending 0:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter.folder_run_plan \
  --run-summary output_archive/reduced_codex_depth5_export_retry2_20260707/run_summary.json \
  --summary-only
```

Add `--next-run-prefix <prefix>` to include suggested `folder_walk_driver` commands for pending skipped/dry-run folders:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter.folder_run_plan \
  --run-summary output_archive/<run-id>/run_summary.json \
  --next-run-prefix resume_<date> \
  --next-mixed-folder-select-all \
  --summary-only
```

2026-07-08 partition probe:

- Command shape: `--max-depth 5 --max-folders 3 --skip-export --execute --summary-only`.
- Result: visited 3 folders, exported 0 files, skipped 2 by `max_folder_limit`, returned to `Codex`.
- Run summary: `output_archive/codex_partition_probe_skip_20260708/run_summary.json`.
- `folder_run_plan --next-run-prefix codex_partition_resume_20260708` generated two resume candidates:
  - `Codex/폴더 10`
  - `Codex/폴더 13`
- This confirms the partition/resume planning loop works without exporting notes.
- Both resume candidates were then executed with `--skip-export`.
- Combined run-plan result across the initial probe and both resume runs: visited 7 folders, skipped 2, resolved skipped 2, pending 0.

- Edge cases covered:
  - intermediate folders can contain notes and subfolders at the same time
  - leaf folders with one note can show the filename dialog even when the driver used select-all mode
  - date-section checkboxes such as `이번 달` must not be confused with the global `전체` control
