# Project Plan

This is the execution map for the Samsung Notes archive exporter. It is designed to keep the project moving in small, reversible steps with clear safety gates.

## North Star

Build a local migration tool that preserves the user's Samsung Notes folder and subfolder structure as a local archive of official export files, with structured manifests for later conversion.

The MVP succeeds when:

- A harmless sample export batch can be copied into `output_archive/archive/<folder_path>/`.
- `manifest.json`, `folders.json`, and `notes_index.json` are generated.
- Source export files are never deleted or modified.
- Folder paths are preserved from observed or user-provided folder metadata.
- Every uncertain device/UI assumption is documented.

## Current Operating Mode

Status as of 2026-07-01: the project has moved from exploratory UI discovery into stabilization.

The active milestone checklist is `docs/stabilization_roadmap.md`. Use it as the source of truth for what should be done next.

Do not continue by adding one-off automation tricks unless they fit this order:

1. Preserve archive metadata correctly, especially date-like Samsung Notes identifiers.
2. Stabilize screenshot-first folder traversal and recovery behavior on harmless folders.
3. Prove end-to-end export on controlled test folders.
4. Only then scale to real personal folder trees.

Current priority questions:

- Which Samsung Notes date signals are preserved in `.sdocx` exports?
- Can folder traversal reliably distinguish folders from note cards/composer-opening candidates?
- Can one folder-walk run produce a complete `run_summary.json` and merged archive without manual repair?
- What remaining fields must the archive manifest preserve before any real migration run?

## Execution Rules

- Work phase by phase.
- Do not skip safety gates.
- Treat each ADB/device action as requiring explicit user approval.
- Prefer observation before automation.
- Prefer copy over move.
- Keep real personal dumps and exports out of git.
- Record decisions in `docs/decision_log.md`.
- Record current state in `docs/project_status.md`.

## Phase 0: Repository Foundation

Status: complete.

Deliverables:

- Repository scaffold.
- Safety-focused `README.md`.
- Project agent rules in `AGENTS.md`.
- Threat model.
- Archive format draft.
- Read-only ADB helper scripts.

Exit criteria:

- Scripts pass shell syntax checks.
- GitHub private repo exists.
- Initial scaffold is pushed.

Current gap:

- Commit and push status should be kept current after plan updates.

## Phase 1: Read-only Device Probe

Status: complete.

Purpose:

Confirm device and Samsung Notes package facts without reading note content.

Inputs:

- User-owned Galaxy S26 Plus, exact model to be confirmed by ADB.
- USB debugging enabled.
- User approval to run `./scripts/adb_probe.sh`.

Commands:

```bash
./scripts/adb_probe.sh
```

Deliverables:

- Summarized facts in `docs/device_probe.md`.
- No full `dumpsys` dump committed.
- No personal note contents logged.

Exit criteria:

- Manufacturer, model, Android version recorded.
- Samsung Notes package/version recorded if visible.
- `run-as` and private directory permission result summarized.

Safety gate:

- Stop if output appears to contain personal note content.

## Phase 2: Public Storage Trace Search

Status: complete.

Purpose:

Find already-exported or public-storage Samsung Notes-related files without opening contents.

Commands:

```bash
./scripts/adb_find_public_notes.sh
```

Deliverables:

- Summary in `docs/device_probe.md`.
- Optional local-only raw path list if the user asks for it.

Exit criteria:

- Known whether public `.sdocx`, `.sdoc`, `.pdf`, `.docx`, or related files exist.
- No files copied, moved, deleted, or opened.

Safety gate:

- Do not commit raw personal file paths unless explicitly approved.

## Phase 3: UI Observation

Status: substantially complete for MVP.

Purpose:

Determine whether Samsung Notes folder and export UI can be observed reliably through UIAutomator dumps.

Workflow:

1. User manually opens Samsung Notes.
2. User navigates to a target screen.
3. Run `./scripts/dump_ui.sh <label>` after approval.
4. Summarize Known / Unknown / Risk in `docs/samsung_notes_ui_map.md`.

Target screens:

- Main screen.
- Folder list screen.
- Subfolder screen.
- Note list inside a folder.
- Selection mode.
- Share/export menu.

Deliverables:

- UI map with observed text, content descriptions, and resource IDs.
- Risk notes for destructive or ambiguous controls.

Exit criteria:

- We know whether folder names and note titles appear in UI hierarchy.
- We know whether export controls are identifiable without coordinates.

Safety gate:

- No tap automation until UI risks are documented.

## Phase 4: Folder Tree Capture Strategy

Status: drafted with observed UI signals.

Purpose:

Design how to preserve the Samsung Notes folder tree even if export files do not contain folder metadata.

Deliverables:

- Updated `docs/folder_tree_capture.md`.
- Folder ID and path rules.
- Duplicate handling rules.
- Back navigation and breadcrumb strategy.
- Filesystem escaping rules.

Exit criteria:

- A manual folder tree can be represented as `folders.json`.
- Each note can be assigned a `folder_path` before archive building.

Safety gate:

- Do not assume UI traversal is reliable until dumps prove it.

## Phase 5: Manual Export Flow Test

Status: partially complete.

Purpose:

Evaluate official Samsung Notes export formats using harmless sample notes.

Workflow:

1. User creates a small test folder and sample notes.
2. User manually exports available formats.
3. User places only harmless samples in `samples/` or another approved local path.
4. Agent inspects file structure and metadata only as approved.

Formats to compare:

- `.sdocx`
- `.pdf`
- `.docx`
- `.txt`

Deliverables:

- Updated `docs/export_flow_notes.md`.
- Recommendation for archival primary format.

Exit criteria:

- We know which format preserves title, body, handwriting, images, dates, tags, and folder info best.

Safety gate:

- Do not inspect personal note contents.

## Phase 6: Archive Builder MVP

Status: MVP implemented.

Purpose:

Build a local copy-only archive builder for already-exported files.

Expected command shape:

```bash
python -m sn_archive_exporter build \
  --input input_exports/batch_001 \
  --mapping folder_mapping.json \
  --output output_archive \
  --dry-run
```

MVP capabilities:

- Copy files into `archive/<folder_path>/`.
- Generate `manifest.json`.
- Generate `folders.json`.
- Generate `notes_index.json`.
- Record SHA-256 and file size.
- Handle filename collisions safely.
- Default to dry-run or copy-only behavior.

Non-MVP capabilities:

- Markdown conversion.
- OCR.
- AI analysis.
- Direct Samsung Notes automation.

Exit criteria:

- Works on harmless sample exports.
- Tests cover path sanitization, collision handling, dry-run behavior, and manifest generation.
- No source files are modified.

Safety gate:

- Refuse destructive modes unless explicitly designed and approved later.

## Phase 7: Automation Feasibility Report

Status: draft complete.

Purpose:

Decide whether ADB/UIAutomator export automation is realistic and safe.

Deliverable:

- `docs/feasibility_report.md`

Required answers:

- Can ADB alone automate export?
- Are UI elements stable enough?
- Where would coordinate taps be required?
- Can folder structure be read from UI?
- Is there a subfolder depth limit?
- Does export preserve folder info?
- Can traversal record folder info if export does not?
- Is an Accessibility app needed?
- Is Windows Samsung Notes automation better?
- What is the most realistic MVP path?

Exit criteria:

- Clear go/no-go recommendation for automation.
- Preferred next implementation path.

## Phase Gates

Do not move to a later phase if the earlier phase has unresolved safety blockers.

Allowed overlap:

- Phase 4 can draft while Phase 3 observations are ongoing.
- Phase 6 can start with user-provided synthetic mappings before UI automation exists.
- Phase 7 should wait until at least one UI observation and one manual export test exist.

## Immediate Next 3 Actions

1. Keep this plan and status docs committed and pushed.
2. Ask user approval for Phase 1 read-only ADB probe.
3. After probe, summarize only safe facts and update `docs/device_probe.md`.
