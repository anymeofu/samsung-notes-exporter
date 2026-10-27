# Threat Model

## Scope

This project handles the user's personal Samsung Notes and local migration archive. It must preserve data while avoiding unsafe access patterns, accidental modification, and unnecessary exposure of private content.

## Assets

- Personal note files and note contents.
- Folder and subfolder names.
- Note titles, timestamps, tags, and attachments.
- Device metadata such as model, Android version, package names, and app versions.
- Local archive manifests and hashes.

## Allowed Operations

- Read-only ADB device and package inspection after user approval.
- Listing public storage paths that may contain already-exported note files.
- Dumping visible UI hierarchy from the current screen after user approval.
- Copying user-provided export files into a local archive during a later MVP phase.
- Generating local manifests and hashes.

## Prohibited Operations

- Rooting the device or advising Knox bypass.
- Copying or reading Samsung Notes private app databases.
- Reverse engineering Samsung Cloud private APIs.
- Inspecting account tokens or credentials.
- Uploading note data or manifests to external services.
- Deleting, moving, or modifying original notes or export files.
- Logging personal note contents.
- Treating Markdown conversion as an MVP goal.

## Main Risks

### Accidental data modification

Risk: Automation could tap destructive UI controls or alter notes.

Mitigation: Start with manual navigation, UI dumps, and read-only commands. Document risky buttons before any tap automation.

### Private content leakage

Risk: UI dumps or path listings may include note titles or folder names.

Mitigation: Keep outputs local. Summarize public facts in docs. Do not commit real personal dumps unless the user explicitly approves.

### False confidence in automation

Risk: UI labels and resource IDs may vary by Samsung Notes version, language, theme, device size, or Android version.

Mitigation: Record Known, Unknown, and Risk separately in `docs/samsung_notes_ui_map.md`.

### Loss of folder context

Risk: Official export files may not preserve original folder path.

Mitigation: Capture `folder_path` during UI traversal and write it to manifest entries before or during export handling.

### Filename collisions

Risk: Multiple notes can share titles or export filenames.

Mitigation: Archive builder must use collision-safe filenames and stable generated IDs.

## Data Handling Rules

- Store only summaries of device probe output in `docs/device_probe.md`.
- Store UI dump XML outside committed docs unless scrubbed or sample-only.
- Put only harmless test samples in `samples/`.
- Prefer generated IDs and hashes over content snippets.
