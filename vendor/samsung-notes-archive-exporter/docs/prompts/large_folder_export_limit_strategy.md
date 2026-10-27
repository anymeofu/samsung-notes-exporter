# Prompt: Large Folder Export Limit Strategy

Use this prompt when a Samsung Notes folder contains more notes than the app can safely export in one selection.

```text
I need a safe strategy for exporting a large Samsung Notes folder where selecting 100+ notes disables or hides some export functions.

Context:
- I own the notes and device.
- I want local folder-preserving export.
- I do not want root, database access, cloud API reverse engineering, deletion, move, modification, or upload.
- The existing project has guarded visible-batch export logic and a 99-note automated selection cap.

Folder details:
- Folder path:
- Approximate note count:
- Samsung Notes version:
- Android version:
- Observed selection limit/error:
- Are there date section headers such as "이번 주", "6월", or years?:

Please design or adapt a batch export plan that:
1. Keeps each export under the safe selection limit.
2. Avoids tapping note cards hidden under top overlays or bottom toolbars.
3. Tracks exported notes with local hashed UI fingerprints without logging note text.
4. Handles overlapping scroll viewports.
5. Uses read-only coverage scans before recovery exports.
6. Produces a final merged archive and validation report.
7. Fails closed on ambiguous screens or destructive actions.

Before changing code, inspect the existing visible batch runner, tests, and validator. Add tests for any new strategy.
```
