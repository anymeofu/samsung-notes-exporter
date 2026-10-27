# Finalization Plan

This document tracks the path from the current private migration prototype to a reliable personal archive and, later, a public-safe release.

## Priority 1: Finish Extraction — Complete

Success criteria:

- The root screen fast verification reports `complete_visible`.
- The runner state has no `planned`, `entering`, or `needs_review` folders.
- The final merged archive validates `ok`.
- The final merged archive preserves direct notes in mixed folders.
- Dot-named folders such as `TestMaterials/.` remain in manifest paths and are only sanitized for filesystem paths.
- No source notes or phone-side files are deleted, moved, modified, or uploaded.

Current best archive:

```text
output_archive/root_seeded_execute_20260710_merged_latest
```

Current verified counts:

```text
folders: 56
notes: 884
files: 884
display_datetime: 884/884
sdocx metadata: 884/884
```

Personal TXT reconciliation is also complete:

```text
personal source notes: 871
TXT files: 868
confirmed text-empty SDOCX-only notes: 3
unexplained omissions: 0
```

## Priority 2: Final Archive Handoff — Complete

- Create a final named archive directory after the last verification pass.
- Run `archive_validator --summary-only` and keep the full validator output locally.
- Write `docs/final_migration_report.md` with:
  - device/app context
  - export mode
  - final archive path
  - folder/note/file counts
  - empty folders
  - warnings
  - known limitations
  - reproduction commands

Completed in `docs/final_migration_report.md`.

## Priority 3: Optional Format Conversion

Do not mix conversion into the core exporter.

Create a separate ignored workspace for conversion experiments, for example:

```text
conversion_workspace/
```

Recommended conversion approach:

- Start from the finalized local archive.
- Treat `.sdocx` as source-of-record.
- Produce `.txt` or other derived files without modifying the archive.
- Do not push converted personal note text.

If `.sdocx` parsing is insufficient for a user's notes, update the UI automation to choose another official Save as file format such as text, PDF, Word, or image instead of Samsung Notes file. This is a separate export-mode feature, not an MVP requirement.

The current TXT experiment confirms that official TXT export is useful for text-first users, but it is not a lossless replacement for `.sdocx`: text-empty notes may produce no TXT file at all. Keep the source archive authoritative.

## Priority 4: Full Automation Test — Complete For Current Device

Before any public release:

- Reset to a harmless dummy Samsung Notes tree.
- Run the exporter end-to-end without step-by-step manual steering.
- Confirm it can:
  - detect root folders
  - export direct notes in mixed folders
  - handle dot-named folders
  - preserve folder paths
  - stop safely on unknown screens
  - resume from state
  - produce a validated merged archive

Completed against the harmless `Codex` tree, including same-state resume and guarded entry from `Codex/Export`.

## Priority 5: Public Release Readiness — Private Release Complete

Before pushing or making the repository public:

- Run `git ls-files` checks to confirm no generated private data is tracked:
  - `input_exports/`
  - `output_archive/`
  - `ui_dumps/`
  - `observations/`
  - `.sdocx`
  - raw XML/PNG screenshots
- Review docs for private note titles or user-specific sensitive paths.
- Keep the repository private until this review is complete.
- Update README with:
  - cloud backup warning
  - version/device variability warning
  - Galaxy S26 Plus/macOS/ADB context
  - automation risk and permission scope
  - prompt-pack location for adapting the project to other devices

The repository has passed the generated-data scan and remains private. Making it public is an optional user decision, not a migration prerequisite.

## Priority 6: Prompt Pack — Complete

Prepare prompts under `docs/prompts/` for users who want an assistant to inspect, adapt, or rebuild this tool for their own device.

Planned prompts:

- `review_and_adapt_to_my_device.md`
- `connection_troubleshooting.md`
- `large_folder_export_limit_strategy.md`
- `rebuild_for_different_device.md`

These prompts should not be pasted into README in full. README should link to them.

## Remaining Optional Work

- Investigate the unusual harmless dummy folder behavior and improve skipped-candidate diagnostics.
- Compare PDF, Word, and image exports for users who need visual/layout preservation.
- Add UI-observed date fields if a future use case needs semantics beyond export metadata.
- Decide whether to make the private repository public after an independent review.
