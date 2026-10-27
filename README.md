# samsung-notes-exporter (Windows app, via Mac/Parallels)

Archive every note from **Samsung Notes for Windows** to your local disk as
editable `.sdocx` + readable `.pdf`, preserving your notebook/folder
structure -- so you can safely turn off Samsung Notes cloud sync or free up
that storage.

It's **read-only**: it only reads Samsung Notes' own files on disk. It never
modifies, deletes, or uploads anything, doesn't touch Samsung's servers, and
needs no root/jailbreak/Knox bypass -- the Windows app simply doesn't sandbox
its data the way the Android app does. See [How it works](#how-it-works).

This was built for the specific case of Samsung Notes for Windows running
inside a **Parallels Desktop VM on a Mac**, with the export tooling run from
the Mac side. If you're running the Windows app on bare-metal Windows, skip
the Mac-mounting steps and just run everything directly in Windows.

## What you get

```
output/
  manifest.json              every note's id, folder, title, lock status, hashes
  archive/
    Notebook A/
      My note.sdocx           editable, re-importable Samsung Notes file
      My note.pdf              rendered copy (handwriting, drawings, text, tables, images)
    Notebook A/Subfolder/
      Another note.sdocx
      Another note.pdf
```

## Quick start

### On Windows (inside the VM, or on bare-metal Windows)

Only needed if you don't already have a way to get the Mac reading the
Windows filesystem live (see next section) -- otherwise skip this.

```powershell
powershell -ExecutionPolicy Bypass -File collect_samsung_notes.ps1
```

This finds Samsung Notes' local data folder and zips the parts this tool
needs (`wdoc/`, `Storage.sqlite`) to `\\Mac\Home\Downloads` (if that Parallels
share is on) or your Windows Desktop otherwise.

### On your Mac

**1. Let the Mac see the Windows VM's files** (skip if you used the zip
   above, or if you're running Windows directly, not in a VM):

   - Parallels Desktop -> select your VM -> gear icon (**Configure**) ->
     **Options** tab -> **Sharing** -> turn on
     **"Access Windows folders from Mac"**.
   - In Finder: **Go -> Network** (`⇧⌘K`) -> open the VM -> connect (Guest
     is usually fine). It mounts under `/Volumes/`, e.g.
     `/Volumes/[C] Windows 11/...`.

**2. Install Rust + `sdocx-cli`** (renders `.sdocx` -> PDF):

   ```bash
   brew install rust          # or: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   cargo install sdocx-cli
   ```

**3. Run it:**

   ```bash
   python3 snexport.py list                       # dry run, see what's there
   python3 snexport.py export --output ./output    # the real export
   python3 snexport.py verify --output ./output    # confirm nothing's missing/corrupt
   ```

   This gives you the `.sdocx` master + a quick `sdocx-cli` PDF per note. For
   notes made from "Import PDF" or with real annotations, that quick PDF can
   come out blank/wrong (see [Web viewer](#web-viewer-recommended-for-checkingexporting-merged-notes)
   below for the properly merged, correct-color version) -- open the web
   viewer next and export the notes that actually matter from there.

   `snexport.py` auto-searches `/Volumes`, `~/Downloads`, `~/Desktop` for the
   Samsung Notes data folder. If it can't find it, pass it explicitly:
   `--local-state "/Volumes/[C] Windows 11/Users/<you>/AppData/Local/Packages/SAMSUNGELECTRONICSCoLtd.SamsungNotes_<id>/LocalState"`.

## Commands

```
snexport.py list    [--local-state PATH]
snexport.py export  [--local-state PATH] --output DIR [--include-locked] [--skip-pdf] [--force]
snexport.py verify  --output DIR
```

- **`list`** -- prints every active note's folder/title (flags locked ones),
  writes nothing. Good first sanity check.
- **`export`** -- does the real work. Safe to re-run/interrupt: by default it
  **resumes** from `manifest.json` (skips notes already exported). Use
  `--force` to redo everything.
- **`verify`** -- re-hashes every exported `.sdocx` and checks every `.pdf`
  exists and is non-empty. **Run this before deleting or disabling anything
  on the Samsung side.**

Locked notes are skipped by default (their content stays encrypted on disk --
unlock them in Samsung Notes first, or pass `--include-locked` to copy the
still-locked container anyway, for later).

## Web viewer (recommended for checking/exporting merged notes)

A local-only browser UI for browsing your archive, previewing notes with
imported-PDF backgrounds and ink properly merged, toggling light/dark
rendering per note, and exporting whichever copy (or both) you want:

```bash
node server.mjs --output ./output
# open http://localhost:4848
```

Nothing leaves your machine -- it's a plain `node:http` server with no
external dependencies beyond what `vendor/Samsung_Notes` already needs
(`npm install && npm run build` there first, see Setup).

Why this exists: `sdocx-cli` alone doesn't draw imported-PDF page
backgrounds, and its default color handling can turn dark-canvas/white-pen
notes into inverted black-on-white. The viewer uses `lib/noteRenderer.mjs`
(built on `vendor/Samsung_Notes`'s own rendering code) to render each page
correctly, lets you preview both color modes per note, and only writes a
merged PDF to disk when you click export -- nothing is decided for you.

You can also batch this from the CLI instead of the UI:

```bash
node merge_notes.mjs --colors auto   # one PDF per note, mode guessed per note
node merge_notes.mjs --colors light  # force light for every note
node merge_notes.mjs --colors dark   # force dark for every note
node merge_notes.mjs --colors both   # both copies for every note
```

## Inkport: a patched viewer, for interactive browsing/export

[Mhemd139/Samsung_Notes](https://github.com/Mhemd139/Samsung_Notes) (vendored
in `vendor/Samsung_Notes/`) ships **Inkport**, a polished browser-based
`.sdocx` viewer/exporter, plus an **MCP connector** that lets an AI assistant
like Claude read your notes directly. Upstream, Inkport always renders in
light mode (no toggle) -- not fit for dark-canvas/white-pen notes.

**This project patches that in**, directly in the vendored source
(`vendor/Samsung_Notes/src/core/note.ts`, `web/src/library.ts`,
`web/src/exporters.ts`, `web/src/main.ts`, `web/index.html`,
`web/src/styles.css`):
- a Light/Dark toggle per note in the viewer, defaulting to that note's own
  `dark_mode_compatibility` suggestion
- the same true-black-background fix described above, shared with this
  project's own renderer
- "Download PDF" / "Share PDF" / "Export all (ZIP)" all respect the chosen
  mode (ZIP export gets an Auto/Force-light/Force-dark picker, where Auto
  resolves per note)

Run it with:

```bash
cd vendor/Samsung_Notes
npm install && npm run build   # Node side (also needed for snexport.py/the web viewer)
npx vite web --port 5173       # Inkport itself
# open http://localhost:5173
```

Use Inkport when you want to interactively browse/export notes one at a
time with a polished UI. Use `snexport.py` + `server.mjs` (above) for the
"export everything, once, onto disk, verified" bulk-archive workflow --
they're complementary, not competing. The HEIC-photo fix is **not** ported
to Inkport (browsers can't decode HEIC without a new dependency this
project doesn't add) -- that's `snexport.py`/`lib/noteRenderer.mjs`-only
for now.

These patches are plain, self-contained diffs worth upstreaming as a PR to
Mhemd139/Samsung_Notes.

## How it works

Samsung Notes for Windows (Microsoft Store build) stores notes, unencrypted,
under:

```
%LOCALAPPDATA%\Packages\SAMSUNGELECTRONICSCoLtd.SamsungNotes_<id>\LocalState\
  wdoc\<note-uuid>\     one folder per note: .page files, media/, (attach/)
  Storage.sqlite        CategoryTreeDB (folder tree) + NoteDB (note -> folder/title/locked)
```

Zipping a `wdoc/<uuid>` folder's contents, uncompressed, produces the exact
same container format as Samsung Notes' own "Save as file -> Samsung Notes
file" export. **This was verified directly**: a note exported both ways
produced PDFs (via `sdocx-cli`) with an identical SHA-256 hash -- see
`validation/` (gitignored, since it holds real note content; regenerate it
yourself if you want to re-check: export one note via Samsung Notes' own
"Save as file -> Samsung Notes file", then diff against this tool's output
for the same note).

`Storage.sqlite`'s tables give the folder path and title for each note UUID,
so the archive mirrors your actual Samsung Notes folder structure instead of
dumping everything flat by UUID.

### Rendering fixes beyond what the vendored libraries do alone

Three are applied in both `lib/noteRenderer.mjs` (this project's exporter)
**and** `vendor/Samsung_Notes/src/core/note.ts` (so Inkport, the web viewer,
gets them too -- that file is no longer a byte-for-byte upstream snapshot,
see below). One is investigated and documented but deliberately *not*
patched.

- **True black dark mode.** The underlying library's "dark" canvas is `#252525`
  (dark gray), not black. We rewrite just the page-background rect to
  `#000000` after rendering, to match Samsung Notes' actual dark theme.
- **HEIC/other undecodable photos.** Photos pasted from a phone camera are
  often `.heic`, which the underlying renderer can't decode at all -- it
  silently drops them (`UnresolvedImageMedia` in `sdocx-cli`'s diagnostics),
  even though the bytes are fully present in the `.sdocx`. We read each
  affected photo's exact on-page position from the parser's own inspection
  data, decode it ourselves (via macOS's built-in `sips`), and composite it
  in. **`lib/noteRenderer.mjs` only** -- browsers can't decode HEIC without a
  new dependency, so Inkport doesn't get this one. If you're not on macOS
  either, this step is skipped and that spot stays blank; the `.sdocx` is
  unaffected either way.
- **Clipped page content.** Verified on a real note: the renderer's stated
  page height (used for the SVG's viewBox) sometimes undershoots where a
  page's actual ink/objects are placed -- `content_bbox` itself undercounts
  too (seen: reports `y_max=1352` while real objects go to `y_max=1994` on
  the same page) -- so content below the stated height is silently clipped
  out of every rendered page/PDF/image. Confirmed this is genuine content
  loss, not just a tight crop: extending the viewBox (no re-rendering
  needed, the SVG markup for that content is already there, just outside the
  declared bounds) revealed real missing text ("Risk Factors", "HDP Gestosis
  score", etc.). We walk every object's own bbox and widen the viewBox/height
  to cover the true max extent whenever it exceeds the stated page height.
- **Paper-only renders don't lose typed/handwritten content on the same
  page.** All three fixes operate on the already-rendered SVG per page, so
  they compose correctly with the imported-PDF-background compositing
  described above (paper below, photos above that, ink/text above that).

**Investigated, not fixed: opaque highlighter marks over colored ink.**
Confirmed on a real note (verified in both light and dark mode, in `sdocx-cli`,
Inkport, and this project's own renderer alike -- not something we
introduced): a highlighter stroke over non-black ink can render fully
opaque, hiding the text underneath. Traced to `crates/sdocx/src/render.rs`
(`Blend::Darken`/`Blend::Lighten`, chosen by `composition.rs`'s
`render_pass()` classification, which correctly reads each stroke's
`top_layer_pen` flag): the stroke *is* correctly classified and placed in
the dedicated `<g style="mix-blend-mode:darken">` batch -- this isn't a
wiring bug. The real issue is that `darken`/`lighten` blend math only
preserves legibility reliably for near-black (or near-white, in dark mode)
underlying ink; for mid-tone colored ink (confirmed case: teal-green
`#3f8881` under yellow `#ffcb30`), per-channel darken/lighten can land close
enough to the highlighter's own color to visually swallow the text. A real
fix means replicating Samsung's actual (undocumented) highlighter
compositing more accurately, not a small targeted patch -- left for
upstream. The `.sdocx` data itself is unaffected; this is a preview-only
cosmetic issue.

An earlier attempted fix for dark mode (always render "light", then
manually recolor default-ink text/strokes for a dark display) was tried and
**reverted**: it broke highlighter/marker strokes outright, since they use
multiply-blend compositing that assumes a white backdrop -- painting black
behind them makes them vanish entirely (anything × black = black).
`render_svg(index, "dark")` evidently accounts for this; the from-scratch
post-process didn't. Worth knowing if you're tempted to try the same thing.

`vendor/sdocx` remains a plain upstream snapshot (with one additional local
patch, see below); `vendor/Samsung_Notes` now carries the three shipped
fixes above plus the dark/light toggle, mode-aware export, and alternate PDF
viewer described elsewhere in this README. All of it is worth upstreaming
as PRs.

## Credits

- [twangodev/sdocx](https://github.com/twangodev/sdocx) (GPL-3.0) --
  reverse-engineered `.sdocx` parser/renderer; `sdocx-cli` does all the
  PDF rendering here. Vendored in `vendor/sdocx/`.
- [Mhemd139/Samsung_Notes](https://github.com/Mhemd139/Samsung_Notes)
  (GPL-3.0) -- the `Storage.sqlite` index-reading approach (folder tree,
  titles, lock/delete status) follows this project's `windowsApp.ts` /
  `samsungIndex.ts`. Vendored in `vendor/Samsung_Notes/`.
- [Flukinity/samsung-notes-archive-exporter](https://github.com/Flukinity/samsung-notes-archive-exporter)
  (the Android-side equivalent of this project; inspired the folder-preserving
  archive + manifest approach). Vendored in `vendor/samsung-notes-archive-exporter/`.

Both `sdocx` and `Samsung_Notes` are vendored here as plain source snapshots
(no `.git` history) so this project keeps working even if either upstream
repo changes or disappears. This repo is licensed GPL-3.0 to match.

Note: `vendor/sdocx` has one small local patch (`crates/sdocx-cli/src/main.rs`)
adding a `--color-mode auto|light|dark` flag to the CLI, used only to
investigate/confirm the light/dark rendering behavior documented above. The
actual exporter here (`lib/noteRenderer.mjs`) doesn't depend on that patched
binary -- it calls `@twango/sdocx`'s WASM API directly with an explicit color
mode. The patch may be worth upstreaming as a PR to twangodev/sdocx.

Unofficial; not affiliated with or endorsed by Samsung. Samsung Notes is a
trademark of Samsung Electronics.

## Troubleshooting

**"sdocx-cli not found"**
Run `cargo install sdocx-cli`. If `cargo` itself isn't found, install Rust
first (`brew install rust`). If it's installed but still not found, check
`~/.cargo/bin/sdocx-cli` exists -- `snexport.py` checks that path directly as
a fallback, so this should be rare.

**Web viewer: "input exceeds the browser limit of 250 MiB" or a page silently has no PDF background**
A few notes have an imported PDF large enough that `resvg`/PDFium can't
composite it; `lib/noteRenderer.mjs` catches this and falls back to
ink-only for that one page rather than failing the whole note. The `.sdocx`
itself (and the extracted `(imported PDF)` file from `snexport.py export`,
if it made one) still has the real content.

**Web viewer: `node server.mjs` fails to start, or every preview 500s**
Make sure `vendor/Samsung_Notes` is built (`npm install && npm run build`
there) -- `lib/noteRenderer.mjs` loads its compiled `dist/` output and its
`node_modules` (for `@twango/sdocx`, `@resvg/resvg-js`, `jpeg-js`) directly.

**"couldn't auto-find a Samsung Notes LocalState folder"**
The Windows share isn't mounted, or Samsung Notes hasn't been opened/synced
yet in the VM. Check `ls /Volumes/` on the Mac -- if nothing Windows-related
shows up, redo the Finder "Go -> Network" connection step above. Otherwise
pass the full path with `--local-state`.

**Script is slow / seems to hang on an individual note**
Reading many small files over the Parallels SMB share is noticeably slower
than local disk, especially if the VM is also syncing in the background.
Expected for notes with lots of media/handwriting pages -- let it run. In
Activity Monitor, `UN` (uninterruptible, waiting on I/O) for the Python
process is normal; pegged at 100% CPU for a long time on one note might be
worth investigating.

**A note is missing from the output**
Check `manifest.json`: `skipped_locked` (unlock it in Samsung Notes, or rerun
with `--include-locked`) and `skipped_deleted` (it's in the Samsung Notes
recycle bin -- restore it there first) explain most cases. Entries under
`errors` have the actual `sdocx-cli` failure message.

**"UnsupportedPageTemplate" / "UnsupportedImageFeature" warnings during export**
From `sdocx-cli` itself -- some newer Samsung Notes page templates or shape
types aren't fully supported by its renderer yet. The PDF still gets
written; check it visually for that note if you're relying on it. The
`.sdocx` file is unaffected (it's your original data, untouched) -- if
`sdocx-cli` improves later, re-render just the PDFs from the kept `.sdocx`
files.

**"database is locked" or similar on Storage.sqlite**
`snexport.py` copies the database to a temp file before reading it (SQLite
locking doesn't always play nicely over a network share), so this should be
rare. If it still happens, close Samsung Notes in the VM and retry.

**Before you actually turn off Samsung Cloud sync / delete notes**
1. Run `snexport.py verify --output ./output` and confirm it reports clean.
2. Spot-check a handful of `.pdf` files, especially any with handwriting or
   drawings.
3. Check `manifest.json`'s `errors`, `skipped_locked`, and `skipped_deleted`
   are all accounted for (0, or explained).
4. Keep the `.sdocx` files, not just the PDFs -- they're your only editable,
   re-importable copy.
