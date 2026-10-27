# Decision Log

## Confirmed Decisions

- MVP is a folder-preserving local archive, not Markdown, Obsidian, Trellis, OCR, or AI analysis.
- Use official Samsung Notes visible UI only. Do not use root, Knox bypass, private databases, private cloud APIs, account tokens, or uploads.
- Copy exported files; never delete, move, or modify source notes.
- Keep raw screenshots and UIAutomator XML local-only by default. Normal model observations are screenshot-first with compact candidate metadata.
- Keep `.sdocx` as the source-of-record. TXT is a supplemental derived format and may produce no file for text-empty notes.
- Cap automated selection batches below the observed Samsung Notes large-selection limit and stop closed on unknown or destructive screens.
- Use local hashed visible-card fingerprints for large-folder deduplication without logging note text.
- Use exact UI text and clickable ancestor bounds for top-level folder entry, then verify the breadcrumb.
- Do not commit personal archive outputs, screenshots, UI dumps, reconciliation reports, device seeds, or note contents.
- The repository remains private until the owner independently approves a public release.
