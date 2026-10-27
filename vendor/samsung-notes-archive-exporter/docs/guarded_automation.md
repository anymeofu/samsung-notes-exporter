# Guarded Automation

Goal: automate only inside harmless test folders first.

## Current Guard

`sn_archive_exporter.ui_guard` parses a local UIAutomator XML dump and refuses actions unless the visible breadcrumb exactly matches an allowed folder path.

Example:

```bash
SUMMARY_LINES=0 ./scripts/dump_ui.sh codex_export_test_context
PYTHONPATH=src python3 -m sn_archive_exporter.ui_guard \
  --xml ui_dumps/codex_export_test_context.xml \
  --allowed-path "Codex/Export" \
  summarize
```

Dry-run a long press on the first visible note:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter.ui_guard \
  --xml ui_dumps/codex_export_test_context.xml \
  --allowed-path "Codex/Export" \
  long-press-first-note
```

Execute only after reviewing the dry-run:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter.ui_guard \
  --xml ui_dumps/codex_export_test_context.xml \
  --allowed-path "Codex/Export" \
  long-press-first-note --execute
```

Dry-run a safe resource-id tap, such as selection-mode overflow:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter.ui_guard \
  --xml ui_dumps/codex_selection_after_guard_2.xml \
  --allowed-path "Codex/Export" \
  tap-resource --resource-id com.samsung.android.app.notes:id/bottom_overflow
```

Dry-run a safe Samsung Notes menu text tap:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter.ui_guard \
  --xml ui_dumps/codex_selection_more_after_guard.xml \
  --allowed-path "Codex/Export" \
  tap-menu-text --text "파일로 저장"
```

Dry-run the final Samsung Notes filename confirmation save button:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter.ui_guard \
  --xml ui_dumps/codex_after_done_no_file.xml \
  --allowed-path "Codex/Export" \
  tap-filename-save
```

## Safety Rules

- Guarded automation is allowed only in explicit test folders.
- The Samsung Notes package must be visible in the UI dump.
- If the current breadcrumb does not match, the helper refuses to act.
- If dangerous selection actions are already visible, the helper refuses to long-press.
- Resource-id taps are allow-listed. Delete, move, and lock are never safe tap targets.
- Menu text taps are allow-listed. Currently `파일로 저장` and `삼성 노트 파일` are allowed.
- My Files taps are separately allow-listed. Currently `Documents`, `Download`, and `com.sec.android.app.myfiles:id/menu_done` are allowed.
- The final filename confirmation tap is allowed only when Samsung Notes shows a `파일 이름` dialog, a generated filename with the expected `Notes_` prefix, and exactly one enabled `저장` button.
- Start with one action at a time; do not chain export steps yet.
- Never automate delete, move, lock, or secure-folder actions.

## Observed Guarded Export

On 2026-06-30, a harmless `Codex/Export` test-folder note was exported through guarded one-step automation:

```text
Samsung Notes test folder
→ guarded long-press first visible note
→ guarded bottom overflow tap
→ guarded "파일로 저장" tap
→ guarded "삼성 노트 파일" tap
→ guarded My Files "Documents" tap
→ guarded My Files done tap
→ guarded Samsung Notes filename "저장" tap
```

Result: a new nonzero `.sdocx` appeared in public `/sdcard/Documents`.

Important observation: My Files `Done` is not the final write step. Samsung Notes returns to a filename confirmation dialog before creating the file.

## Guarded Driver

`sn_archive_exporter.guarded_export_driver` performs the same one-note `.sdocx` export flow with a fresh UI dump before every action. It is intended only for harmless test folders until repeated successfully.

Precondition: the phone must already show the allowed Samsung Notes folder's note list. For the current test folder:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter.guarded_export_driver \
  --allowed-path "Codex/Export" \
  --label codex_export_driver_test
```

The command above is a dry-run: it dumps and validates the first visible note-list screen, then prints the planned guarded actions without tapping.

Execute the guarded flow:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter.guarded_export_driver \
  --allowed-path "Codex/Export" \
  --label codex_export_driver_test \
  --execute
```

Export multiple visible notes from the same allowed test folder:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter.guarded_export_driver \
  --allowed-path "Codex/Export" \
  --label codex_export_multiselect_2 \
  --select-count 2 \
  --execute
```

Export, copy-only pull the newly created `.sdocx` files, write an Archive Builder mapping, and build a local archive:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter.guarded_export_driver \
  --allowed-path "Codex/Export" \
  --label codex_export_handoff_2 \
  --select-count 2 \
  --pull-to input_exports/codex_export_handoff_2 \
  --archive-output output_archive/codex_export_handoff_2 \
  --execute
```

Use Samsung Notes' top-left all-select checkbox after entering selection mode:

```bash
PYTHONPATH=src python3 -m sn_archive_exporter.guarded_export_driver \
  --allowed-path "Codex/Export" \
  --label codex_export_select_all \
  --select-all \
  --pull-to input_exports/codex_export_select_all \
  --archive-output output_archive/codex_export_select_all \
  --execute
```

The driver still refuses delete, move, lock, external share targets, non-allow-listed My Files destinations, and unexpected UI states. It verifies the resulting public `.sdocx` with `ls -l` only; it does not open file contents.

Observed multi-note behavior:

- After the first long-press, note cards expose selected state as `checked=true`.
- The driver selects additional visible notes only from unchecked visible `root_cardview` cards.
- The driver confirms the checked note count before opening the export menu.
- Single-note export shows a final Samsung Notes filename dialog.
- Multi-note export skips the filename dialog and writes one `.sdocx` per selected note directly after My Files `Done`.
- Multi-note verification compares the public destination `.sdocx` listing before and after export.
- The selected-mode toolbar exposes a top-left "전체" / all-select checkbox.
- `--select-all` now taps that checkbox after a first-note long-press, then verifies the toolbar selected count before export.
- In the `Codex/Export` test folder, all-select selected 4 visible notes and exported 4 `.sdocx` files.
- In a larger `Codex/Export` test folder, 6 note cards were visible but the toolbar reported 8 selected notes after all-select.
- The larger-folder all-select test exported, pulled, and archived 8 `.sdocx` files, confirming all-select can include off-screen notes in this observed Samsung Notes version.

## Observed Lock-Screen Case

During the first guarded long-press experiment, a follow-up dump captured `com.android.systemui` rather than Samsung Notes, likely because the device had returned to the lock/AOD or notification surface. This is now treated as a hard refusal condition for future guarded actions.
