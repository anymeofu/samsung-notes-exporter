# Stabilization Roadmap

This roadmap turns the project from exploratory UI discovery into a controlled migration tool. Work should close these milestones in order unless a safety issue forces a change.

## Operating Rule

Every new task must answer one of these questions:

1. Does it preserve note/folder metadata more accurately?
2. Does it make UI traversal safer and more predictable?
3. Does it improve the local archive pipeline without touching source notes?
4. Does it reduce risk before a real migration run?

If not, defer it.

## Milestone 1: Metadata Fidelity

Goal: preserve the information Samsung Notes exposes through official exports and visible UI.

Status: complete for the current MVP and device; semantic date refinements are optional.

Done:

- `.sdocx` filename datetime is extracted as `filename_datetime`.
- `.sdocx` zip timestamp for `note.note` is extracted as `zip_note_datetime`.
- `.sdocx` page timestamps are extracted as `zip_page_datetimes`.
- Archive notes now include `display_datetime` from source-specific metadata.

Optional follow-up:

- Create controlled test notes with known visible dates and compare UI date labels against exported `.sdocx` metadata.
- Decide how to represent unknown date semantics without overclaiming created/modified dates.
- Add manifest fields for UI-observed note title/date when captured separately from export metadata.

Exit criteria:

- For untitled/date-named notes, archive manifest preserves the date-like display signal.
- Date fields are clearly labeled by source and confidence.
- No note body inspection is required for metadata preservation.

## Milestone 2: Traversal Reliability

Goal: navigate folders without confusing folders, note cards, composer screens, or system pickers.

Status: complete for the tested current-device scope; one harmless dummy UI edge case remains documented.

Done:

- Screenshot-first observation is the default.
- Raw UI dumps are local-only unless escalated.
- `모두 보기` expansion is detected.
- Fully visible subfolder tiles are extracted; clipped untitled tiles are skipped.
- Non-folder screens after a folder tap are skipped and recovery is attempted.
- `--skip-export` allows traversal testing without creating more exported files.
- Mixed folder screens are recognized: direct note cards can appear below subfolder grids, and the walker records note-card pages when they become visible.

Known issue:

- In the harmless `Codex` folder, `폴더 15` opens a composer/non-list screen and is skipped.

Optional follow-up:

- Investigate whether `폴더 15` is a malformed test folder, a note card misclassified as a folder, or a Samsung Notes UI edge case.
- Add stricter visual/candidate checks before tapping lower-right folder tiles.
- Add a traversal report section for skipped folders and recovery attempts.
- Run a controlled current-folder direct-note export from `Codex` to prove mixed folders preserve the parent folder path.

Exit criteria:

- A harmless test tree can be traversed end to end with no unhandled aborts.
- Skipped candidates are explicitly recorded with reason and screenshot metadata path.
- The walker returns to the allowed root after failures.

## Milestone 3: Export And Archive Pipeline

Goal: produce a folder-preserving local archive from official `.sdocx` exports.

Status: complete for the current device and export scope.

Done:

- Guarded Save as file flow exports `.sdocx` through Samsung Notes and My Files.
- All-select exports off-screen notes in the current folder in the observed Samsung Notes version.
- Exported files are pulled copy-only.
- Per-folder archive output is generated.
- `run_summary.json` records run-level totals and compact tree.
- `merge-folder-archives` combines per-folder archive outputs.
- Existing output directories are refused by default during execute runs.
- A fresh guarded export from harmless `Codex/Export` selected all 8 dummy notes, exported `.sdocx`, pulled 8 files copy-only, and built a local archive with hashes and `display_datetime` values.
- A harmless `Codex` folder-walk execute produced `run_summary.json`, exported/pulled 12 `.sdocx` files from 3 note-containing folders, recorded 2 over-depth skips, and merged into a 12-note archive without manual repair.
- Global select-all targeting now rejects date section checkboxes and only accepts the top toolbar `전체`/`모두 선택` control.
- Mixed folders now avoid global select-all once subfolders have been observed anywhere in that folder, even if the current viewport shows only notes.
- UI labels such as `폴더 2개, 노트 13개` are parsed as visible folder/note counts for future selection verification.
- Probe confirmed selected subfolders expose `checked=true` and child `inflate_checkbox` bounds; folder tile center taps are unsafe for deselection.
- Guarded export has an experimental visible-folder deselection step after select-all.
- Guarded export has `--selection-probe-only` to stop after selection verification and before export menus.
- A probe showed that the floating breadcrumb bar can occlude upper checkbox bounds, so deselection must use overlay-aware safe regions and recompute after every tap.
- Guarded export has ADB/dump timeouts so stuck `uiautomator dump` calls fail closed.
- The first overlay-aware probe reduced selected folders in `Codex`, but clean note-only selection is not proven yet.
- Mixed-folder selection now has a final verifier requiring zero selected folders, positive selected count, matching UI note count when available, and visible export overflow.
- `Codex` mixed-folder probe-only has two clean final-verifier successes with `selected_count=2` and no export.
- `Codex` dummy mixed-folder full export has one clean success: 2 `.sdocx` files exported, pulled, and archived under `output_archive/codex_mixed_full_export_20260707_2118`.
- Archive validation CLI exists and validated the mixed-folder archive.
- Folder walker default depth is 5, supports `--max-folders`, and completed a limited depth-5 skip-export run in `Codex`.

Optional follow-up:

- Decide whether over-depth skipped folders should become a resume/deeper-pass queue.
- Add a compact archive validation CLI for manifest counts, hashes, folder paths, and date metadata.
- Re-run a deeper harmless pass only after the queue/resume behavior is explicit.
- Validate selection behavior on folders with older date section headers such as month and year groups.
- Run a limited depth-5 dummy walk with export enabled and `--mixed-folder-select-all`.
- Design a safe off-screen note strategy for mixed folders before migrating real folders with many direct notes.
- Extend guarded deselection across off-screen selected folders before enabling the strategy broadly.

Exit criteria:

- One controlled folder walk can produce a merged archive without manual repair. (Met on harmless `Codex` depth-1 run.)
- Source exports remain untouched.
- Re-running with the same output path is blocked unless explicitly allowed.

## Milestone 4: Real Migration Readiness

Goal: prepare for limited real-folder migration without accidental data loss or noisy context exposure.

Status: complete for the current device; broader device support remains optional.

Prerequisites:

- Milestones 1 through 3 exit criteria are met on harmless test folders.
- User approves a small real-folder pilot scope.
- Pilot scope has a clear allowed root folder path.

Pilot plan:

1. Dry-run traversal with `--summary-only --observe-screens --skip-export`.
2. Review skipped candidates and folder counts.
3. Execute export for one approved small folder only.
4. Build and merge archive.
5. Verify manifest counts and metadata.

Exit criteria:

- The user can inspect the archive structure locally.
- Folder path, exported files, hashes, and date-like metadata are present.
- No source note deletion, movement, modification, upload, or private DB access occurred.

## Backlog

- Compare `.pdf`, `.docx`, `.txt` preservation after `.sdocx` pipeline stabilizes.
- Add UI-observed note date capture if Samsung Notes exposes date labels in list cards.
- Add archive validation CLI.
- Add resume support only after output collision and run-summary behavior are fully stable.
- Gradually wire `workflow_state.py` into the folder walker so each step emits compact state deltas instead of ad hoc verbose result snapshots.
