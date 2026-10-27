# Prompt: Rebuild For A Very Different Device

Use this prompt if your phone, OS, Samsung Notes version, UI language, or computer environment is different enough that adapting this project may be slower than rebuilding the automation around the same safety principles.

```text
I want you to build a local Samsung Notes archive exporter for my own environment, using the lessons from an existing Galaxy S26 Plus/macOS prototype but not blindly copying its UI coordinates or assumptions.

Goal:
Create a folder-preserving local archive of my own Samsung Notes through official visible UI flows.

Non-goals:
- No root.
- No Knox bypass.
- No private Samsung Cloud API reverse engineering.
- No private app database copying.
- No deletion, move, modification, or upload.
- No Markdown conversion as the first milestone.

My environment:
- Phone model:
- Android version:
- Samsung Notes version:
- UI language:
- Computer OS:
- ADB availability:

Build plan:
1. Scaffold a repo with docs, scripts, source, tests, and ignored local artifact directories.
2. Add read-only ADB probes.
3. Add screenshot-first observation that saves raw XML/screenshots locally but sends compact metadata to the assistant.
4. Map Samsung Notes folder, selection, Save as file, format chooser, and My Files picker screens.
5. Build guarded export for a harmless dummy folder first.
6. Add archive builder with manifest/folders/notes index and SHA-256 hashes.
7. Add stateful runner with resume support.
8. Add validation and final reporting.
9. Add public-release safety checks.

Important:
Ask for approval only at new risk boundaries. Once I approve a class of official UI export action for a safe dummy folder, do not ask for the same approval repeatedly unless the screen/risk changes.

Approval and efficiency policy:
- Present the planned permission and risk boundaries as one short checklist before the first device action.
- After I approve that checklist, batch routine read-only observations and already-approved official export actions where the guard can verify the current folder and screen.
- Stop and ask again only for a new risk boundary, an unknown screen, a possible destructive action, or an export path that could upload/share data.
- Keep normal observations screenshot-first with compact candidates. Store raw XML locally and escalate it only when the screen is genuinely ambiguous.
- If the environment differs substantially from the fields above, rebuild the device adapter and screen schemas from fresh probes instead of copying coordinates or assuming labels.

Output expected:
- A clear implementation plan.
- Minimal dependencies.
- Tests for parsing/state/archive logic.
- Commands I can run safely.
- A final checklist before public sharing.
```
