#!/usr/bin/env python3
"""
snexport -- Samsung Notes (Windows app) local archiver.

Reads Samsung Notes for Windows' own on-disk files read-only (no UI
automation, no account access, nothing uploaded anywhere) and archives every
note as:
  - <title>.sdocx  -- the editable Samsung Notes container, re-importable
                       into Samsung Notes / openable in sdocx.twango.dev
  - <title>.pdf    -- a rendered, human-readable copy

...into a folder tree that mirrors your Samsung Notes notebooks/folders.

Run `python3 snexport.py --help` or see README.md for full instructions.
"""
import argparse
import hashlib
import io
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def find_sdocx_cli() -> str:
    exe = shutil.which("sdocx-cli")
    if exe:
        return exe
    # cargo installs here by default; it may not be on PATH in every shell.
    fallback = Path.home() / ".cargo" / "bin" / "sdocx-cli"
    if fallback.exists():
        return str(fallback)
    print(
        "ERROR: sdocx-cli not found.\n"
        "Install it with:\n"
        "    cargo install sdocx-cli\n"
        "(needs Rust: https://rustup.rs -- or `brew install rust` on macOS)\n"
        "See README.md Troubleshooting if this still fails.",
        file=sys.stderr,
    )
    sys.exit(1)


def candidate_local_state_dirs():
    """Search likely mount points for a SamsungNotes LocalState folder
    (Parallels 'Share Windows folders with Mac', a manual SMB mount, or a
    folder you extracted collect_samsung_notes.ps1's zip into)."""
    roots = [Path("/Volumes")] + [Path.home() / d for d in ("Downloads", "Desktop")]
    found = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            children = list(root.iterdir())
        except PermissionError:
            continue
        for child in children:
            # Parallels "Share Windows folders with Mac" mounts as e.g.
            # /Volumes/[C] Windows 11
            packages_glob = list(child.glob("Users/*/AppData/Local/Packages/SAMSUNGELECTRONICSCoLtd.SamsungNotes_*/LocalState"))
            found.extend(packages_glob)
            # a manually extracted collect_samsung_notes.ps1 zip
            if (child / "wdoc").is_dir() and (child / "Storage.sqlite").exists():
                found.append(child)
    return found


def resolve_local_state(arg_path: str | None) -> Path:
    if arg_path:
        p = Path(arg_path).expanduser()
        if not p.is_dir():
            print(f"ERROR: {p} is not a directory.", file=sys.stderr)
            sys.exit(1)
        return p

    candidates = candidate_local_state_dirs()
    if not candidates:
        print(
            "ERROR: couldn't auto-find a Samsung Notes LocalState folder.\n"
            "Pass it explicitly with --local-state, e.g.:\n"
            '  --local-state "/Volumes/[C] Windows 11/Users/<you>/AppData/Local/'
            'Packages/SAMSUNGELECTRONICSCoLtd.SamsungNotes_<id>/LocalState"\n'
            "See README.md Troubleshooting.",
            file=sys.stderr,
        )
        sys.exit(1)
    if len(candidates) > 1:
        print("Found multiple candidates, pick one with --local-state:")
        for c in candidates:
            print(f"  {c}")
        sys.exit(1)
    print(f"Found Samsung Notes data at: {candidates[0]}")
    return candidates[0]


# ---------------------------------------------------------------------------
# Index (folders / titles / locked / deleted)
# ---------------------------------------------------------------------------

def read_index(storage_sqlite: Path):
    """Returns {note_uuid: {folder, title, locked, deleted}}."""
    with tempfile.TemporaryDirectory() as tmp:
        local_copy = Path(tmp) / "Storage.sqlite"
        shutil.copy2(storage_sqlite, local_copy)
        conn = sqlite3.connect(f"file:{local_copy}?mode=ro", uri=True)
        try:
            cur = conn.cursor()
            cur.execute("SELECT UUID, ParentUUID, DisplayName FROM CategoryTreeDB")
            folder_rows = cur.fetchall()
            by_id = {uuid: (parent, name) for uuid, parent, name in folder_rows}
            parent_ids = {parent for _, parent, _ in folder_rows if parent}
            containers = {
                uuid for uuid, parent, _ in folder_rows if not parent and uuid in parent_ids
            }

            def folder_path(uuid, seen=None):
                seen = seen or set()
                if not uuid or uuid not in by_id or uuid in containers or uuid in seen:
                    return ""
                seen.add(uuid)
                parent, name = by_id[uuid]
                name = (name or "").strip() or "Unnamed folder"
                parent_path = folder_path(parent, seen) if parent else ""
                return f"{parent_path}/{name}" if parent_path else name

            cur.execute("SELECT UUID, CategoryUUID, DeletedStatus, IsLocked, Title FROM NoteDB")
            index = {}
            for uuid, category_uuid, deleted, locked, title in cur.fetchall():
                index[uuid] = {
                    "folder": folder_path(category_uuid or ""),
                    "deleted": bool(deleted),
                    "locked": bool(locked),
                    "title": title or "",
                }
            return index
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Note -> .sdocx
# ---------------------------------------------------------------------------

def zip_note_folder(note_dir: Path) -> bytes:
    """Zips a wdoc/<uuid> folder's contents, uncompressed -- this is byte-
    identical in structure to what Samsung Notes' own 'Save as file ->
    Samsung Notes file' produces for the files it actually uses (verified by
    SHA-256-matching the rendered PDF of a real export against this)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for path in sorted(note_dir.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=str(path.relative_to(note_dir)))
    return buf.getvalue()


def extract_embedded_pdfs(sdocx_bytes: bytes):
    """Samsung Notes' "Import PDF" feature keeps the original PDF verbatim in
    media/, used as a page background. sdocx-cli doesn't render that
    background yet (pages come out blank except for any hand-drawn ink on
    top), so pull the original PDF(s) out directly -- that's the faithful
    visual copy for these notes, not the renderer's output."""
    pdfs = []
    with zipfile.ZipFile(io.BytesIO(sdocx_bytes)) as zf:
        for name in zf.namelist():
            if name.lower().startswith("media/") and name.lower().endswith(".pdf"):
                pdfs.append((name, zf.read(name)))
    return pdfs


def sanitize(name: str) -> str:
    name = name.strip() or "Untitled"
    name = re.sub(r'[\/:*?"<>|\x00-\x1f]', "_", name)
    return name[:150]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def cmd_export(args):
    sdocx_cli = find_sdocx_cli()
    local_state = resolve_local_state(args.local_state)
    wdoc_dir = local_state / "wdoc"
    storage_sqlite = local_state / "Storage.sqlite"
    output_root = Path(args.output).expanduser()
    archive_dir = output_root / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    if not wdoc_dir.is_dir():
        print(f"ERROR: no wdoc folder found at {wdoc_dir}", file=sys.stderr)
        sys.exit(1)

    print("Reading note index from Storage.sqlite ...")
    try:
        index = read_index(storage_sqlite)
    except Exception as e:
        print(f"WARNING: couldn't read Storage.sqlite ({e}); folder names/titles will be missing.")
        index = {}

    manifest_path = output_root / "manifest.json"
    manifest = {"notes": [], "skipped_locked": [], "skipped_deleted": [], "errors": []}
    if manifest_path.exists() and not args.force:
        try:
            manifest = json.loads(manifest_path.read_text())
        except Exception:
            pass
    done_ids = {n["id"] for n in manifest["notes"]} if not args.force else set()

    used_names = {}
    note_dirs = sorted(p for p in wdoc_dir.iterdir() if p.is_dir())
    print(f"Found {len(note_dirs)} note folder(s) in {wdoc_dir}")
    if done_ids:
        print(f"Resuming: {len(done_ids)} already exported (use --force to redo everything).")

    for note_dir in note_dirs:
        uuid = note_dir.name
        if uuid in done_ids:
            continue
        meta = index.get(uuid, {"folder": "", "deleted": False, "locked": False, "title": ""})

        if meta["deleted"]:
            manifest["skipped_deleted"].append(uuid)
            continue
        if meta["locked"] and not args.include_locked:
            manifest["skipped_locked"].append(uuid)
            continue

        folder_path = meta["folder"]
        target_dir = archive_dir / folder_path if folder_path else archive_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        base_name = sanitize(meta["title"] or uuid)
        key = str(target_dir)
        used_names.setdefault(key, set())
        final_name = base_name
        if final_name in used_names[key]:
            final_name = f"{base_name} ({uuid[:8]})"
        used_names[key].add(final_name)

        entry = {"id": uuid, "title": meta["title"], "folder": folder_path, "locked": meta["locked"]}

        try:
            sdocx_bytes = zip_note_folder(note_dir)
        except Exception as e:
            entry["stderr"] = f"failed to zip note folder: {e}"
            manifest["errors"].append(entry)
            print(f"  FAIL {uuid}: couldn't zip note folder ({e})")
            continue

        sdocx_path = target_dir / f"{final_name}.sdocx"
        sdocx_path.write_bytes(sdocx_bytes)
        entry["sdocx_file"] = str(sdocx_path.relative_to(output_root))
        entry["sdocx_sha256"] = sha256_bytes(sdocx_bytes)

        embedded_pdfs = extract_embedded_pdfs(sdocx_bytes)
        if embedded_pdfs:
            entry["source_pdfs"] = []
            suffix = "" if len(embedded_pdfs) == 1 else None
            for i, (_, data) in enumerate(embedded_pdfs, start=1):
                label = "(imported PDF)" if suffix == "" else f"(imported PDF {i})"
                src_path = target_dir / f"{final_name} {label}.pdf"
                src_path.write_bytes(data)
                entry["source_pdfs"].append(str(src_path.relative_to(output_root)))
            print(f"       + extracted {len(embedded_pdfs)} original imported PDF(s)")

        if not args.skip_pdf:
            pdf_path = target_dir / f"{final_name}.pdf"
            cmd = [sdocx_cli, str(sdocx_path), "-o", str(pdf_path)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0 and pdf_path.exists():
                entry["pdf_file"] = str(pdf_path.relative_to(output_root))
                entry["pdf_sha256"] = sha256_bytes(pdf_path.read_bytes())
            else:
                # The .sdocx (your real, editable data) is already safely
                # written above -- a PDF render failure (e.g. sdocx-cli's
                # ~512MB single-entry limit on a huge imported PDF, or a
                # malformed embedded image) shouldn't make this look like a
                # lost note. Record it as sdocx-only, not a hard failure.
                entry["pdf_error"] = result.stderr.strip()[-2000:]
                manifest["pdf_only_errors"] = manifest.get("pdf_only_errors", [])
                manifest["pdf_only_errors"].append(entry["id"])
                print(f"  OK (sdocx only, PDF render failed) {folder_path or '(root)'}/{final_name}: {entry['pdf_error'][:150]}")

        manifest["notes"].append(entry)
        if "pdf_file" in entry:
            print(f"  OK   {folder_path or '(root)'}/{final_name}")

        # Save progress as we go, so a Ctrl+C or crash doesn't lose work.
        manifest_path.write_text(json.dumps(manifest, indent=2))

    manifest_path.write_text(json.dumps(manifest, indent=2))

    print()
    print(f"Exported {len(manifest['notes'])} / {len(note_dirs)} notes successfully.")
    pdf_only = manifest.get("pdf_only_errors", [])
    if pdf_only:
        print(f"{len(pdf_only)} of those are .sdocx only -- PDF rendering failed (huge embedded PDF, or a corrupt/unsupported image). Your original note data is still safe; see manifest.json 'pdf_only_errors'.")
    if manifest["skipped_locked"]:
        print(f"Skipped {len(manifest['skipped_locked'])} locked note(s) (rerun with --include-locked to try anyway).")
    if manifest["skipped_deleted"]:
        print(f"Skipped {len(manifest['skipped_deleted'])} note(s) in the recycle bin.")
    if manifest["errors"]:
        print(f"{len(manifest['errors'])} FAILED COMPLETELY (no .sdocx either) -- see manifest.json, or rerun 'snexport verify'.")
    print(f"Archive: {archive_dir}")
    print(f"Manifest: {manifest_path}")


# ---------------------------------------------------------------------------
# list (dry run)
# ---------------------------------------------------------------------------

def cmd_list(args):
    local_state = resolve_local_state(args.local_state)
    wdoc_dir = local_state / "wdoc"
    storage_sqlite = local_state / "Storage.sqlite"
    try:
        index = read_index(storage_sqlite)
    except Exception as e:
        print(f"WARNING: couldn't read Storage.sqlite ({e})")
        index = {}

    note_dirs = sorted(p for p in wdoc_dir.iterdir() if p.is_dir())
    active = locked = deleted = 0
    for note_dir in note_dirs:
        meta = index.get(note_dir.name, {"folder": "", "deleted": False, "locked": False, "title": ""})
        if meta["deleted"]:
            deleted += 1
            continue
        if meta["locked"]:
            locked += 1
        active += 1
        folder = meta["folder"] or "(root)"
        title = meta["title"] or f"(untitled {note_dir.name[:8]})"
        tag = " [LOCKED]" if meta["locked"] else ""
        print(f"{folder}/{title}{tag}")

    print()
    print(f"{active} active note(s) ({locked} locked), {deleted} in recycle bin.")


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def cmd_verify(args):
    output_root = Path(args.output).expanduser()
    manifest_path = output_root / "manifest.json"
    if not manifest_path.exists():
        print(f"ERROR: no manifest.json in {output_root} -- run 'snexport export' first.", file=sys.stderr)
        sys.exit(1)
    manifest = json.loads(manifest_path.read_text())

    problems = []
    for entry in manifest["notes"]:
        sdocx_file = output_root / entry["sdocx_file"]
        if not sdocx_file.exists():
            problems.append(f"MISSING {entry['sdocx_file']}")
            continue
        actual_hash = sha256_bytes(sdocx_file.read_bytes())
        if actual_hash != entry["sdocx_sha256"]:
            problems.append(f"HASH MISMATCH {entry['sdocx_file']}")
        if not zipfile.is_zipfile(sdocx_file):
            problems.append(f"NOT A VALID ZIP {entry['sdocx_file']}")

        if "pdf_file" in entry:
            pdf_file = output_root / entry["pdf_file"]
            if not pdf_file.exists():
                problems.append(f"MISSING {entry['pdf_file']}")
            elif pdf_file.stat().st_size == 0:
                problems.append(f"EMPTY {entry['pdf_file']}")

        for src in entry.get("source_pdfs", []):
            src_path = output_root / src
            if not src_path.exists():
                problems.append(f"MISSING {src}")
            elif src_path.stat().st_size == 0:
                problems.append(f"EMPTY {src}")

    print(f"Checked {len(manifest['notes'])} exported note(s).")
    pdf_only = manifest.get("pdf_only_errors", [])
    if pdf_only:
        print(f"{len(pdf_only)} note(s) are .sdocx only (PDF rendering failed) -- data is safe, just not visually previewable yet. See manifest.json 'pdf_only_errors'.")
    if manifest["errors"]:
        print(f"{len(manifest['errors'])} note(s) failed during export completely -- no .sdocx either (see manifest.json 'errors').")
    if problems:
        print(f"{len(problems)} PROBLEM(S) FOUND:")
        for p in problems:
            print(f"  {p}")
        print()
        print("Do not delete your Samsung Cloud / on-device notes until this is clean.")
        sys.exit(1)
    else:
        print("All exported files present and hash-verified. Looks safe.")
        if manifest["errors"] or manifest["skipped_locked"]:
            print(
                "NOTE: some notes were skipped or failed (see manifest.json) -- "
                "those are NOT covered by this check."
            )


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        prog="snexport",
        description="Archive Samsung Notes (Windows app) to editable .sdocx + .pdf, "
        "preserving folder structure. Read-only; never modifies your notes.",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    common_ls = argparse.ArgumentParser(add_help=False)
    common_ls.add_argument(
        "--local-state",
        help="Path to the SamsungNotes package's LocalState folder. "
        "Auto-detected if omitted (see README).",
    )

    p_export = sub.add_parser("export", parents=[common_ls], help="Export all notes to .sdocx + .pdf")
    p_export.add_argument("--output", required=True, help="output archive folder")
    p_export.add_argument("--include-locked", action="store_true", help="also attempt locked notes (content stays encrypted)")
    p_export.add_argument("--skip-pdf", action="store_true", help="only write .sdocx, skip PDF rendering (faster)")
    p_export.add_argument("--force", action="store_true", help="re-export everything, ignoring previous progress")
    p_export.set_defaults(func=cmd_export)

    p_list = sub.add_parser("list", parents=[common_ls], help="List notes without exporting anything (dry run)")
    p_list.set_defaults(func=cmd_list)

    p_verify = sub.add_parser("verify", help="Verify a previous export's files are intact")
    p_verify.add_argument("--output", required=True, help="the archive folder to verify")
    p_verify.set_defaults(func=cmd_verify)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
