# Mixed Folder Selection Strategy

Samsung Notes folders may contain both subfolders and direct notes. In these mixed folders, global select-all can select folders as well as notes. That is not safe as a default export action.

## Preferred Future Strategy

For mixed folders with many direct notes, the preferred strategy is:

1. Enter selection mode from a direct note card.
2. Tap the top toolbar `전체` / `모두 선택` control.
3. Deselect every selected folder tile.
4. Verify that only notes remain selected.
5. Continue to `파일로 저장` only after verification.

This should reduce missed notes compared with visible-note batching, especially when notes are split across date sections such as `이번 주`, `6월`, or `2025년`.

## Required Guards

Do not enable this strategy until all of these are observable in the UI:

- The folder/note count label can be read, for example `폴더 2개, 노트 13개`.
- Selected folder tiles can be identified and tapped without confusing them with notes or date section headers.
- Every folder page can be traversed so off-screen selected folders are also deselected.
- After deselection, selected count equals the visible UI note count when that count is available.
- The export path is available only after folders are deselected. If `파일로 저장` is missing, cancel selection and mark the folder for manual review.

## Probe Findings

- After global select-all in the `Codex` dummy mixed folder, selected subfolder item nodes expose `checked="true"`.
- Each selected folder contains a child checkbox with resource-id `com.samsung.android.app.notes:id/inflate_checkbox`.
- The child checkbox bounds are small and explicit, for example `[312,309][367,364]`.
- Tapping folder tile centers is not safe: during one probe, selection mode exited and a remaining tap opened `Codex/폴더 16`.
- Folder deselection should tap the selected `inflate_checkbox` child center and verify selection mode still remains active after each batch.
- A follow-up probe showed that upper selected-folder checkbox bounds can sit behind Samsung Notes' floating breadcrumb bar. Tapping a checkbox behind that overlay can navigate to the folder overview instead of deselecting the folder.
- The guarded driver now treats upper-edge checkbox bounds as unstable and taps one recomputed checkbox per dump instead of replaying a stale list of targets.
- An overlay-aware scroll probe reduced selected folders while keeping `folder_path=Codex`, but `uiautomator dump` can hang during long selection sessions. The guarded driver now applies a dump timeout so this fails closed instead of waiting indefinitely.
- When folders are selected, the bottom overflow export entry may be unavailable; this can be used as an additional guard signal.
- `ui_guard tap-selected-subfolder-checkboxes` now exists as a guarded primitive for deselecting visible selected folder checkboxes from a saved UI dump.
- `guarded_export_driver --deselect-visible-subfolders-after-select-all` wires the primitive into the guarded flow for visible selected folders. It is still experimental and does not yet handle off-screen selected folders.
- `guarded_export_driver --selection-probe-only` can execute selection preparation and verification, then stop before any export menu is opened. Use this in `Codex` dummy folders before enabling a full export run.

## Current Safe Default

Until the deselection flow is proven, mixed folders use explicit visible note-card selection only. This is slower and may need pagination, but it avoids selecting folders.

For experiments in the dummy `Codex` tree, use probe-only mode first:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter.guarded_export_driver \
  --allowed-path Codex \
  --select-all \
  --deselect-visible-subfolders-after-select-all \
  --selection-probe-only \
  --execute \
  --summary-only \
  --quiet \
  --wait-seconds 0.5 \
  --deselect-scroll-attempts 4
```

After a probe-only run, either review the current phone screen or press Back to leave selection mode. Do not continue to export from a mixed folder until off-screen selected folders are handled or proven absent.

## Open Questions

- Does Samsung Notes expose selected folder state as `checked=true` on subfolder nodes?
- Does global select-all select off-screen folders in every version/language?
- Can the app show a trustworthy total note count for all mixed folders?
- After deselecting folders, does the selected count always reflect notes only?
- Are date section checkboxes distinct from global select-all and folder tiles across month/year sections?
