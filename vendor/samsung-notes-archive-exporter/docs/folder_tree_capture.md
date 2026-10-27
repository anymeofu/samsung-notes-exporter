# Folder Tree Capture

This strategy is not finalized. Initial UI observations show that Samsung Notes exposes folder drawer rows, subfolder grid items, and a folder breadcrumb in UIAutomator dumps.

## Questions To Answer

1. Can Samsung Notes UI expose folder and subfolder lists through UIAutomator?
2. Can each folder's full path be constructed reliably?
3. How should filesystem-unsafe characters be escaped?
4. How should duplicate folder or note names be assigned stable IDs?
5. How should back navigation and breadcrumb state be tracked?
6. If exported files do not preserve folder information, where in traversal should `folder_path` be recorded?

## Draft Output

```json
{
  "folders": [
    {
      "id": "generated-folder-id",
      "path": "Folder A",
      "depth": 0
    },
    {
      "id": "generated-folder-id",
      "path": "Folder A/Subfolder B",
      "depth": 1
    }
  ]
}
```

## Initial Position

Prefer a manual or semi-manual capture first:

- User navigates to a folder screen.
- `scripts/dump_ui.sh` captures visible hierarchy.
- Agent records observed text/resource IDs in `docs/samsung_notes_ui_map.md`.
- Only after multiple dumps confirm stable structure should automation attempt traversal.

## Observed Signals

- Drawer folder list: `drawer_recyclerview`, `drawer_item_container`, `folder_item_layout`.
- Folder-internal breadcrumb: `folderpath_home`, `folderpath_layout`, `folderpath_text`.
- Subfolder grid: `sub_folder_list_item1` through `sub_folder_list_item4`, `sub_folder_icon`, `title`.
- Folder and subfolder accessibility descriptions include a pattern equivalent to `Folder, <name>, <count>`.
- Deeper folder breadcrumbs contain multiple `folderpath_text` nodes in parent-to-child order.
- Note-list items expose `root_cardview`, `thumbnail_container`, `title`, `text_content`, `time`, and `extra`.

## Draft Capture Strategy

1. Start from the navigation drawer and capture visible top-level folder rows.
2. For each folder, enter the folder manually or through a later approved tap strategy.
3. Read breadcrumb segments from all visible `folderpath_text` nodes.
4. Read visible subfolder candidates from `sub_folder_list_item*` nodes.
5. Build `folder_path` from the traversal stack and validate it against breadcrumb segments.
6. Scroll and repeat only after confirming scroll behavior is safe and read-only.

Important tree model: Samsung Notes folders are not assumed to contain notes only at leaf folders. Intermediate folders can contain both notes and child folders. A traversal/export plan must export notes present at every visited folder path before or independently of descending into subfolders.

## Guarded Walker Status

`sn_archive_exporter.folder_walk_driver` now performs a guarded folder walk from the current folder:

- Validates that every visited breadcrumb is under the requested root path.
- Exports notes in each visited folder with guarded all-select.
- Pulls newly exported `.sdocx` files copy-only into ignored local input folders.
- Builds a per-folder archive with the exact breadcrumb path.
- Enters visible subfolders and validates parent breadcrumb after Android back navigation.

Current limitation: only visible subfolders are traversed. Add guarded scrolling before relying on it for folders that have more subfolders than one screen.

## Current Assumptions To Test

- `folderpath_text` appears to expose the parent chain at the tested depth. Very deep nesting and horizontal scrolling remain untested.
- `sub_folder_list_item*` nodes are likely folders; note-card resource IDs differ and include `root_cardview`, `thumbnail_container`, and note text/time fields.
- A folder path may have both direct note children and subfolder children; direct notes should be mapped to that folder path, not pushed down to a leaf path.
- Folder counts in accessibility descriptions should be treated as advisory, not as identity.
- Bounds may help infer grid order but should not be used as the primary folder identity.

## Privacy Handling

- Raw UI XML contains folder names and sometimes note snippets.
- Do not commit raw UI dumps.
- In docs, record resource IDs and structural patterns rather than actual folder names.
