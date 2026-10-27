# samsung-notes-exporter

Archive every note from **Samsung Notes for Windows** to your local disk as
editable `.sdocx` + readable `.pdf`, preserving your notebook/folder
structure — so you can safely turn off Samsung Notes cloud sync or free up
that storage.

**Read-only and safe.** It only reads Samsung Notes' own files on disk. It
never modifies, deletes, or uploads anything, doesn't touch Samsung's
servers, and needs no root/jailbreak/Knox bypass — the Windows app simply
doesn't sandbox its data the way the Android app does. Details: [How the
data format works](#how-the-data-format-works).

Built for Samsung Notes for Windows running inside a **Parallels Desktop VM
on a Mac**, with the tooling run from the Mac side. Running Windows on bare
metal instead? Skip the Mac-mounting steps and run everything directly in
Windows.

Unofficial; not affiliated with or endorsed by Samsung. Samsung Notes is a
trademark of Samsung Electronics.

## Contents

- [Quick start](#quick-start)
- [What you get](#what-you-get)
- [The three tools](#the-three-tools) — which one to reach for
- [Command reference](#command-reference)
- [How the data format works](#how-the-data-format-works)
- [Rendering fixes & findings](#rendering-fixes--findings) — the technical deep dive
- [Credits](#credits)
- [Troubleshooting](#troubleshooting)

## Quick start

### 1. On Windows (inside the VM, or on bare-metal Windows)

Only needed if the Mac can't already see the Windows filesystem live (step 2
covers that) — otherwise skip straight to step 2.

```powershell
powershell -ExecutionPolicy Bypass -File collect_samsung_notes.ps1
```

This finds Samsung Notes' local data folder and zips the parts this tool
needs (`wdoc/`, `Storage.sqlite`) to `\\Mac\Home\Downloads` (if that
Parallels share is on) or your Windows Desktop otherwise.

### 2. On your Mac

**a. Let the Mac see the Windows VM's files** (skip if you used the zip
above, or if you're running Windows directly, not in a VM):

- Parallels Desktop → select your VM → gear icon (**Configure**) →
  **Options** tab → **Sharing** → turn on **"Access Windows folders from
  Mac"**.
- In Finder: **Go → Network** (`⇧⌘K`) → open the VM → connect (Guest is
  usually fine). It mounts under `/Volumes/`, e.g.
  `/Volumes/[C] Windows 11/...`.

**b. Install Rust + `sdocx-cli`** (renders `.sdocx` → PDF):

```bash
brew install rust          # or: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
cargo install sdocx-cli
```

**c. Export your `.sdocx` masters** (fast — this is the part that matters
most, your notes are safe once this is done):

```bash
python3 snexport.py list                                     # dry run, see what's there
python3 snexport.py export --output ./output --skip-pdf       # the real export, sdocx only
python3 snexport.py verify --output ./output                  # confirm nothing's missing/corrupt
```

`--skip-pdf` is deliberate: the quick per-note PDF `sdocx-cli` can render on
its own is frequently wrong (blank pages for notes made from "Import PDF",
opaque highlighter marks, clipped content — see [Rendering fixes &
findings](#rendering-fixes--findings)). Get the safe `.sdocx` masters first,
fast; render correct PDFs afterward with the web viewer, only for the notes
you actually want a PDF of.

`snexport.py` auto-searches `/Volumes`, `~/Downloads`, `~/Desktop` for the
Samsung Notes data folder. If it can't find it, pass it explicitly:
`--local-state "/Volumes/[C] Windows 11/Users/<you>/AppData/Local/Packages/SAMSUNGELECTRONICSCoLtd.SamsungNotes_<id>/LocalState"`.

### 3. Get correct PDFs, for the notes you care about

```bash
cd vendor/Samsung_Notes && npm install && npm run build && cd ../..
node server.mjs --output ./output
# open http://localhost:4848
```

Browse your notebook tree, preview each note with imported-PDF backgrounds,
highlighter marks and dark mode all rendering correctly, and export a PDF
only once you're happy with it. See [The three tools](#the-three-tools) for
what else is available (bulk re-render, the Inkport viewer).

## What you get

```
output/
  manifest.json              every note's id, folder, title, lock status, hashes
  archive/
    Notebook A/
      My note.sdocx            editable, re-importable Samsung Notes file (the master copy)
      My note (merged).pdf     correctly rendered PDF, made once you export it from the web viewer
    Notebook A/Subfolder/
      Another note.sdocx
```

The `.sdocx` is what actually matters — it's a byte-exact copy of Samsung's
own format (verified, see [How the data format
works](#how-the-data-format-works)), so nothing is ever lost regardless of
any rendering bug described below. PDFs are a rendered *view* of that data,
made on demand.

## The three tools

| Tool | What it's for | Run it with |
|---|---|---|
| **`snexport.py`** | Bulk-export every note's `.sdocx` master to disk, once, verified. The safety net. | `python3 snexport.py export --output ./output --skip-pdf` |
| **Web viewer** (`server.mjs`) | Browse your archive, preview notes rendered *correctly* (paper + ink + highlighter + dark mode all fixed), export a PDF only for notes you choose. Built specifically for this project. | `node server.mjs --output ./output` → `localhost:4848` |
| **Inkport** (`vendor/Samsung_Notes/web`) | A more polished third-party viewer, patched here with the same fixes (dark mode, clipping, highlighters) plus an alternate native-PDF-view mode. Drag-and-drop `.sdocx` files/folders in directly. | `cd vendor/Samsung_Notes && npx vite web --port 5173` → `localhost:5173` |

They're complementary, not competing:

- Only need the data saved safely, don't care about pretty PDFs yet? →
  `snexport.py --skip-pdf`.
- Want to check/export a handful of specific notes? → either viewer, your
  choice of UI.
- Want every note correctly rendered to PDF, in bulk? → `merge_notes.mjs`
  (below), or the web viewer's logic reused as a script.

### Web viewer, in more depth

```bash
node server.mjs --output ./output
# open http://localhost:4848
```

A local-only browser UI for browsing your archive, previewing notes with
imported-PDF backgrounds and ink properly merged, toggling light/dark
rendering per note, and exporting whichever copy (or both) you want. Nothing
leaves your machine — it's a plain `node:http` server with no external
dependencies beyond what `vendor/Samsung_Notes` already needs
(`npm install && npm run build` there first).

Why it exists: `sdocx-cli` alone doesn't draw imported-PDF page backgrounds,
and its default color handling can turn dark-canvas/white-pen notes into
inverted black-on-white. The viewer uses `lib/noteRenderer.mjs` (built on
`vendor/Samsung_Notes`'s own rendering code) to render each page correctly,
lets you preview both color modes per note, and only writes a merged PDF to
disk when you click export — nothing is decided for you.

You can also batch this from the CLI instead of the UI:

```bash
node merge_notes.mjs --colors auto   # one PDF per note, mode guessed per note
node merge_notes.mjs --colors light  # force light for every note
node merge_notes.mjs --colors dark   # force dark for every note
node merge_notes.mjs --colors both   # both copies for every note
```

### Inkport, in more depth

[Mhemd139/Samsung_Notes](https://github.com/Mhemd139/Samsung_Notes) (vendored
in `vendor/Samsung_Notes/`) ships **Inkport**, a polished browser-based
`.sdocx` viewer/exporter, plus an **MCP connector** that lets an AI assistant
like Claude read your notes directly. Upstream, Inkport always renders in
light mode (no toggle) — not fit for dark-canvas/white-pen notes, and it has
the same clipping/highlighter issues found and fixed here.

**This project patches that in**, directly in the vendored source
(`vendor/Samsung_Notes/src/core/note.ts`, `web/src/library.ts`,
`web/src/exporters.ts`, `web/src/main.ts`, `web/index.html`,
`web/src/styles.css`):

- a Light/Dark toggle per note in the viewer, defaulting to that note's own
  `dark_mode_compatibility` suggestion
- the same true-black-background, clipping, and highlighter-opacity fixes
  described in [Rendering fixes & findings](#rendering-fixes--findings),
  shared with this project's own renderer
- "Download PDF" / "Share PDF" / "Export all (ZIP)" all respect the chosen
  mode (ZIP export gets an Auto/Force-light/Force-dark picker, where Auto
  resolves per note)
- an alternate "PDF view" toggle per note (Cards vs. PDF view) that reuses
  the browser's own native PDF.js viewer — continuous scroll, zoom, page
  thumbnails — instead of Inkport's per-page card list

Run it with:

```bash
cd vendor/Samsung_Notes
npm install && npm run build   # Node side (also needed for snexport.py/the web viewer)
npx vite web --port 5173       # Inkport itself
# open http://localhost:5173
```

One thing *not* ported to Inkport: the HEIC-photo fix. Browsers can't decode
HEIC without a new dependency, so that one stays
`snexport.py`/`lib/noteRenderer.mjs`-only (see below).

These patches are plain, self-contained diffs — worth upstreaming as a PR to
Mhemd139/Samsung_Notes.

## Command reference

```
snexport.py list    [--local-state PATH]
snexport.py export  [--local-state PATH] --output DIR [--include-locked] [--skip-pdf] [--force]
snexport.py verify  --output DIR
```

- **`list`** — prints every active note's folder/title (flags locked ones),
  writes nothing. Good first sanity check.
- **`export`** — does the real work. Safe to re-run/interrupt: by default it
  **resumes** from `manifest.json` (skips notes already exported). Use
  `--force` to redo everything. Use `--skip-pdf` to skip `sdocx-cli`'s
  quick (often-wrong) per-note PDF — recommended, see [Quick
  start](#quick-start).
- **`verify`** — re-hashes every exported `.sdocx` and checks every `.pdf`
  exists and is non-empty. **Run this before deleting or disabling anything
  on the Samsung side.**

Locked notes are skipped by default (their content stays encrypted on disk —
unlock them in Samsung Notes first, or pass `--include-locked` to copy the
still-locked container anyway, for later).

## How the data format works

Samsung Notes for Windows (Microsoft Store build) stores notes, unencrypted,
under:

```
%LOCALAPPDATA%\Packages\SAMSUNGELECTRONICSCoLtd.SamsungNotes_<id>\LocalState\
  wdoc\<note-uuid>\     one folder per note: .page files, media/, (attach/)
  Storage.sqlite        CategoryTreeDB (folder tree) + NoteDB (note -> folder/title/locked)
```

Zipping a `wdoc/<uuid>` folder's contents, uncompressed, produces the exact
same container format as Samsung Notes' own "Save as file → Samsung Notes
file" export. **This was verified directly**: a note exported both ways
produced PDFs (via `sdocx-cli`) with an identical SHA-256 hash — see
`validation/` (gitignored, since it holds real note content; regenerate it
yourself if you want to re-check: export one note via Samsung Notes' own
"Save as file → Samsung Notes file", then diff against this tool's output
for the same note).

`Storage.sqlite`'s tables give the folder path and title for each note UUID,
so the archive mirrors your actual Samsung Notes folder structure instead of
dumping everything flat by UUID.

## Rendering fixes & findings

The technical deep dive — what's wrong with the upstream renderer, how each
issue was tracked down, and exactly what was changed. Skip this if you just
want to use the tool; come back if something looks off and you want to know
why, or if you're thinking about patching the renderer yourself.

Three fixes are applied in both `lib/noteRenderer.mjs` (this project's
exporter) **and** `vendor/Samsung_Notes/src/core/note.ts` (so Inkport gets
them too — that file is no longer a byte-for-byte upstream snapshot, see
[Credits](#credits)). One issue is investigated and documented but
deliberately *not* patched.

### Fixed: true black dark mode

The underlying library's "dark" canvas is `#252525` (dark gray), not black.
We rewrite just the page-background rect to `#000000` after rendering, to
match Samsung Notes' actual dark theme.

### Fixed: HEIC/other undecodable photos

Photos pasted from a phone camera are often `.heic`, which the underlying
renderer can't decode at all — it silently drops them (`UnresolvedImageMedia`
in `sdocx-cli`'s diagnostics), even though the bytes are fully present in
the `.sdocx`. We read each affected photo's exact on-page position from the
parser's own inspection data, decode it ourselves (via macOS's built-in
`sips`), and composite it in.

**`lib/noteRenderer.mjs` only** — browsers can't decode HEIC without a new
dependency, so Inkport doesn't get this one. If you're not on macOS either,
this step is skipped and that spot stays blank; the `.sdocx` is unaffected
either way.

### Fixed: clipped page content

Verified on a real note: the renderer's stated page height *and width*
(used for the SVG's viewBox) sometimes undershoot where a page's actual
ink/objects are placed. `content_bbox` itself undercounts too — a real
example: it reported `y_max=1352` while objects on that same page actually
went to `y_max=1994`. Content past the stated bounds is silently clipped out
of every rendered page/PDF/image.

This was confirmed as genuine content loss, not just a tight crop: widening
the SVG's viewBox (no re-rendering needed — the markup for that content was
already there, just outside the declared bounds) revealed real missing
text, including an entire "Risk Factors" section ("HDP Gestosis score",
"HTN disorder of pregnancy", etc.) that simply didn't appear anywhere,
not on that page or the next. The fix: walk every object's own bounding
box, on both axes, and widen the viewBox/width/height to cover the true max
extent whenever it exceeds what the renderer declared.

**A second, subtler bug this uncovered:** widening a page's viewBox can push
its aspect ratio over the threshold that triggers print-sheet splitting
(`sheetBands` / `cropToInk` in `core/svg.ts` and `web/src/library.ts`,
Inkport's own logic for notes too tall for one sheet). `cropToInk` used the
same unreliable `content_bbox.y_max` as its crop boundary — so a page we'd
just widened could get silently re-cropped right back down, even smaller
than before. Fixed by making `cropToInk` use the same reliable true-extent
value instead of trusting `content_bbox`.

**A third bug, found from a real screenshot:** the first version of this fix
only widened the outer `<svg>` tag's `width`/`height`/`viewBox`, not the
background `<rect>` element's own `width`/`height` attributes. The
newly-revealed strip then had no background paint at all — transparent in
raw SVG, which showed as a stray white block in Inkport's card view (plain
`<img src="blob:...">`, no canvas fill behind it, unlike the PDF-export path,
which happens to paint a full canvas background first and so masked the
same gap in earlier testing). Fixed by widening the background rect (and the
page-boundary `<clipPath>`'s own rect) to match, via an order-independent
attribute replace — the actual attribute order in the generated SVG is
`height` before `width`, the opposite of what you'd naturally assume, so a
naive regex silently matches nothing.

### Fixed: opaque highlighter marks over colored ink

Confirmed on a real note, in both light and dark mode, in `sdocx-cli`,
Inkport, and this project's own renderer alike — not something introduced
here: a highlighter stroke over non-black ink can render fully opaque,
hiding the text underneath entirely.

Traced to `crates/sdocx/src/render.rs` (`Blend::Darken` in light mode,
`Blend::Lighten` in dark mode, chosen in `composition.rs`'s `render_pass()`
classification). The classification itself is correct — it reads each
stroke's `top_layer_pen` flag properly and places highlighter strokes in
their own dedicated `<g style="mix-blend-mode:darken">` batch, drawn after
ordinary ink, exactly as designed. This isn't a wiring bug.

The real issue is the blend math itself: `darken`/`lighten` only reliably
preserves legibility for near-black (light mode) or near-white (dark mode)
underlying ink. For mid-tone colored ink — the confirmed case was
teal-green `#3f8881` text under a yellow `#ffcb30` highlighter — per-channel
darken/lighten can land close enough to the highlighter's own color to
visually swallow the text.

**The fix actually shipped:** replace the highlighter batch's
`mix-blend-mode:darken`/`lighten` with plain `opacity: 0.5`. This was chosen
after testing alternatives — plain alpha blending guarantees legibility
regardless of underlying hue, which the original blend-mode math can't.
Verified against both a known-good case (black text, where the fix makes
highlighter marks a touch paler but still fully legible — a small visual
trade-off) and the known-broken case (teal text, now fully legible, where it
was previously unreadable).

A real fix that preserves Samsung's exact highlighter look for every case
would mean replicating Samsung's actual (undocumented) compositing more
precisely — left for upstream; this project's fix prioritizes guaranteed
legibility over pixel-perfect visual fidelity. The `.sdocx` data itself is
unaffected either way; this was always a preview-only cosmetic issue.

### A fix that was tried and reverted

Worth knowing if you're tempted to try the same thing: an earlier attempt at
the dark-mode fix always rendered in `"light"` mode, then manually
recolored default-ink text/strokes for a dark display. That broke
highlighter/marker strokes outright — they use multiply-blend compositing
that assumes a white backdrop, so painting black behind them makes them
vanish entirely (anything × black = black). `render_svg(index, "dark")`
evidently accounts for this already; the from-scratch post-process didn't.
Reverted in favor of using the parser's native dark-mode rendering directly,
with only the background-rect color swapped afterward.

### Where these fixes live

All four fixes (three applied, one documented) operate on the already-
rendered SVG per page, so they compose correctly with each other and with
the imported-PDF-background compositing described in [How the data format
works](#how-the-data-format-works) — paper below, photos above that,
ink/text above that.

`vendor/sdocx` remains a plain upstream snapshot, with one small additional
local patch (see [Credits](#credits)). `vendor/Samsung_Notes` carries the
shipped fixes above, plus the dark/light toggle, mode-aware export, and
alternate PDF viewer described in [Inkport, in more
depth](#inkport-in-more-depth). All of it is worth upstreaming as PRs.

## Credits

- [twangodev/sdocx](https://github.com/twangodev/sdocx) (GPL-3.0) —
  reverse-engineered `.sdocx` parser/renderer; `sdocx-cli` does all the PDF
  rendering here. Vendored in `vendor/sdocx/`.
- [Mhemd139/Samsung_Notes](https://github.com/Mhemd139/Samsung_Notes)
  (GPL-3.0) — the `Storage.sqlite` index-reading approach (folder tree,
  titles, lock/delete status) follows this project's `windowsApp.ts` /
  `samsungIndex.ts`. Vendored in `vendor/Samsung_Notes/`.
- [Flukinity/samsung-notes-archive-exporter](https://github.com/Flukinity/samsung-notes-archive-exporter)
  — the Android-side equivalent of this project; inspired the
  folder-preserving archive + manifest approach. Vendored in
  `vendor/samsung-notes-archive-exporter/`.

Both `sdocx` and `Samsung_Notes` are vendored here as plain source snapshots
(no `.git` history) so this project keeps working even if either upstream
repo changes or disappears. This repo is licensed GPL-3.0 to match.

`vendor/sdocx` has one small local patch
(`crates/sdocx-cli/src/main.rs`) adding a `--color-mode auto|light|dark`
flag to the CLI, used only to investigate/confirm the light/dark rendering
behavior documented above. The actual exporter here
(`lib/noteRenderer.mjs`) doesn't depend on that patched binary — it calls
`@twango/sdocx`'s WASM API directly with an explicit color mode. The patch
may be worth upstreaming as a PR to twangodev/sdocx.

## Troubleshooting

### Setup

**"sdocx-cli not found"**
Run `cargo install sdocx-cli`. If `cargo` itself isn't found, install Rust
first (`brew install rust`). If it's installed but still not found, check
`~/.cargo/bin/sdocx-cli` exists — `snexport.py` checks that path directly as
a fallback, so this should be rare.

**"couldn't auto-find a Samsung Notes LocalState folder"**
The Windows share isn't mounted, or Samsung Notes hasn't been opened/synced
yet in the VM. Check `ls /Volumes/` on the Mac — if nothing Windows-related
shows up, redo the Finder "Go → Network" connection step above. Otherwise
pass the full path with `--local-state`.

**Web viewer: `node server.mjs` fails to start, or every preview 500s**
Make sure `vendor/Samsung_Notes` is built (`npm install && npm run build`
there) — `lib/noteRenderer.mjs` loads its compiled `dist/` output and its
`node_modules` (for `@twango/sdocx`, `@resvg/resvg-js`, `jpeg-js`) directly.

### While exporting

**Script is slow / seems to hang on an individual note**
Reading many small files over the Parallels SMB share is noticeably slower
than local disk, especially if the VM is also syncing in the background.
Expected for notes with lots of media/handwriting pages — let it run. In
Activity Monitor, `UN` (uninterruptible, waiting on I/O) for the Python
process is normal; pegged at 100% CPU for a long time on one note might be
worth investigating.

**"database is locked" or similar on Storage.sqlite**
`snexport.py` copies the database to a temp file before reading it (SQLite
locking doesn't always play nicely over a network share), so this should be
rare. If it still happens, close Samsung Notes in the VM and retry.

**A note is missing from the output**
Check `manifest.json`: `skipped_locked` (unlock it in Samsung Notes, or
rerun with `--include-locked`) and `skipped_deleted` (it's in the Samsung
Notes recycle bin — restore it there first) explain most cases. Entries
under `errors` have the actual `sdocx-cli` failure message.

**Web viewer: "input exceeds the browser limit of 250 MiB" or a page
silently has no PDF background**
A few notes have an imported PDF large enough that `resvg`/PDFium can't
composite it; `lib/noteRenderer.mjs` catches this and falls back to
ink-only for that one page rather than failing the whole note. The `.sdocx`
itself still has the real content.

**"UnsupportedPageTemplate" / "UnsupportedImageFeature" warnings during
export**
From `sdocx-cli` itself — some newer Samsung Notes page templates or shape
types aren't fully supported by its renderer yet. The PDF still gets
written; check it visually for that note if you're relying on it. The
`.sdocx` file is unaffected (it's your original data, untouched) — if
`sdocx-cli` improves later, re-render just the PDFs from the kept `.sdocx`
files.

### Before you actually turn off Samsung Cloud sync / delete notes

1. Run `snexport.py verify --output ./output` and confirm it reports clean.
2. Spot-check a handful of PDFs from the web viewer, especially any with
   handwriting, drawings, highlighter marks, or notes made from "Import
   PDF" — these are exactly the cases the rendering fixes above target.
3. Check `manifest.json`'s `errors`, `skipped_locked`, and `skipped_deleted`
   are all accounted for (0, or explained).
4. Keep the `.sdocx` files, not just the PDFs — they're your only editable,
   re-importable copy, and the actual source of truth regardless of any
   rendering issue.
