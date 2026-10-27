#!/usr/bin/env python3
"""
Run this on the Mac side after unzipping samsung_notes_export.zip.

We don't yet know the exact internal format of the `wdoc` folder (it holds
Samsung Notes' notebook/folder structure), so this script just reports what's
actually there -- file types, sizes, and a peek at the first bytes of each
file -- so we can figure out how to map notes to notebooks.

Usage:
    python3 inspect_wdoc.py /path/to/extracted/samsung_notes_export
"""
import sys
import os
import json

MAGIC_SIGNATURES = {
    b"PK\x03\x04": "zip (could be a renamed .sdocx-like container)",
    b"SQLite format 3\x00": "sqlite database",
    b"{": "possibly JSON (text)",
    b"<": "possibly XML/HTML (text)",
}


def sniff(path, head=64):
    with open(path, "rb") as f:
        data = f.read(head)
    for sig, label in MAGIC_SIGNATURES.items():
        if data.startswith(sig):
            return label, data
    return "unknown binary", data


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    root = sys.argv[1]
    wdoc = os.path.join(root, "wdoc")
    sdoc = os.path.join(root, "sdoc")

    report = {"wdoc": [], "sdoc_sample": []}

    if os.path.isdir(wdoc):
        for name in sorted(os.listdir(wdoc)):
            path = os.path.join(wdoc, name)
            if not os.path.isfile(path):
                continue
            size = os.path.getsize(path)
            label, head = sniff(path)
            entry = {
                "name": name,
                "size": size,
                "guess": label,
                "head_hex": head[:32].hex(),
            }
            if label.startswith("possibly"):
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        entry["head_text"] = f.read(500)
                except Exception:
                    pass
            report["wdoc"].append(entry)
    else:
        report["wdoc_error"] = f"no wdoc folder found at {wdoc}"

    if os.path.isdir(sdoc):
        names = sorted(os.listdir(sdoc))
        report["sdoc_count"] = len(names)
        for name in names[:3]:
            path = os.path.join(sdoc, name)
            if os.path.isfile(path):
                label, head = sniff(path)
                report["sdoc_sample"].append(
                    {"name": name, "size": os.path.getsize(path), "guess": label}
                )
    else:
        report["sdoc_error"] = f"no sdoc folder found at {sdoc}"

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
