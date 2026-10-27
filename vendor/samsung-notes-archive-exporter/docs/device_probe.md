# Device Probe

Device facts collected from read-only ADB probe.

Probe attempt on 2026-06-29:

- `adb` was not available on PATH.
- Android SDK `adb` was found under the user's Android SDK platform-tools directory.
- ADB daemon could start after elevated local permission.
- No authorized Android device was detected by `adb devices`.
- No device properties or Samsung Notes package facts were collected.

Probe result on 2026-06-30:

- ADB device status: authorized.
- ADB serial shown by `adb devices`: recorded locally, not needed for archive logic.
- Manufacturer: `samsung`.
- Model: `SM-S947N`.
- Android release: `16`.
- Samsung Notes package: `com.samsung.android.app.notes`.
- Samsung Notes version name: `4.4.41.9`.
- Samsung Notes version code: `444109000`.
- Samsung Notes target SDK: `36`.
- Samsung Notes last update time: `2026-06-03 04:57:30`.
- Samsung Notes private app directory probe: `/data/data/com.samsung.android.app.notes` returned `Permission denied`.
- `run-as com.samsung.android.app.notes`: failed with `package not debuggable`.
- Note-related packages observed: Samsung Notes, Samsung Voice Recorder, Android notes role package, and a third-party FitNotes package.
- No note contents were opened, copied, or inspected.

Public-storage trace search attempt on 2026-06-30:

- Initial `adb_find_public_notes.sh` run reached the authorized device.
- Search did not complete because the Android shell `find` expression was malformed by multiline quoting.
- No file contents were opened, copied, moved, or deleted.

Public-storage trace search result on 2026-06-30:

- Search completed after fixing the Android shell `find` expression.
- Native Samsung Notes export candidates found: 3 `.sdocx` files.
- `.sdocx` candidates were under a public download subfolder used by a messaging app.
- No `.sdoc` or `.spd` candidates were observed in the displayed results.
- Many `.pdf` and `.docx` files were found under public `Download` and `Documents` paths, but these are noisy broad-extension matches and should not be treated as Samsung Notes exports unless corroborated by export flow or filenames.
- `/sdcard/Android/media` and `/sdcard/Samsung` produced no displayed candidates.
- No file contents were opened, copied, moved, or deleted.

Post Save as file check on 2026-06-30:

- A new `.sdocx` export was observed under public `Documents`.
- The file used a generated Samsung Notes filename pattern like `Notes_<YYMMDD>_<HHMMSS>.sdocx`.
- Read-only `ls -l` confirmed the saved file exists and has nonzero size.
- No file contents were opened, copied, moved, or deleted during this check.

Narrow `.sdocx` export search on 2026-06-30:

- Added and ran `scripts/adb_find_sdocx_exports.sh`.
- Public `.sdocx` candidates found: 4 total.
- Existing `.sdocx` candidates under public `Download` messaging-app subfolder: 3.
- Newly saved `.sdocx` candidate under public `Documents`: 1.
- The search lists paths and basic file metadata only; it does not open, copy, move, delete, or inspect contents.

User-reported target device:

- Galaxy S26 Plus
- Exact ADB model string is `SM-S947N`.

When approved, summarize only non-content facts here:

- ADB authorization status.
- Manufacturer.
- Model.
- Android version.
- Samsung Notes package name.
- Samsung Notes version name and version code if visible.
- Whether `run-as com.samsung.android.app.notes` succeeds or fails.
- Whether `/data/data/com.samsung.android.app.notes` permission probing is denied or visible.
- Public-storage filename search summary.

Do not paste full `dumpsys` output or personal note paths unless the user explicitly approves.
