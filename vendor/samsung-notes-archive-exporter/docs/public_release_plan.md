# Public Release Plan

## Positioning

Present this as an early alpha for a narrow, tested environment:

> A guarded, folder-preserving Samsung Notes exporter using visible UI and ADB. No root, private database access, private cloud API, or upload route.

Do not claim universal device support, lossless TXT conversion, unattended safety, or official Samsung affiliation.

## Recommended Sequence

1. Publish a tagged alpha release after the license and security files are present.
2. Start with a focused Samsung Notes community and ask for feedback from users with harmless test folders.
3. Share to broader Samsung communities only after device/version differences and failure reports are understood.
4. Mention Obsidian communities only when discussing migration workflows; this tool's primary output is an archive, not an Obsidian importer.
5. Contact DataHoarder moderators before posting software there and disclose the license and safety model.

## Suggested Post

Title:

```text
[Open source alpha] Folder-preserving Samsung Notes exporter using visible UI and ADB
```

Body:

```text
I built an early open-source tool to export Samsung Notes into a local archive that preserves folder paths.

It uses Samsung Notes' visible Save as file flow and ADB. It does not root the phone, access the private Notes database, reverse-engineer Samsung Cloud, upload notes, or delete/move source notes.

The current alpha was tested on one Galaxy/Android/Samsung Notes/macOS setup. It uses guarded screenshots/UI nodes, dry-runs, bounded batches, local state, hashes, and archive validation. Other devices may need fresh UI probes and adjustments.

Please review the code and run it first on a harmless test folder. Back up Samsung Notes before any real export. Feedback about device/version differences is more useful than unverified success reports.
```

## Do Not Include

- Personal archive links or screenshots.
- Raw UI XML, note titles, folder names, device serials, or account details.
- Claims that the tool is safe for unattended use on every Samsung device.
- A request for users to grant broad permissions without explaining why.
- AI-generated promotional text presented as personal experience.
