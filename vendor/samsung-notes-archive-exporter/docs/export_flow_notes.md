# Export Flow Notes

Use harmless test notes only. Do not place personal notes in `samples/`.

## Preferred Flow

```text
selection mode
→ More / overflow
→ Save as file
→ Samsung Notes file
→ Samsung My Files destination picker
→ local public folder
→ Save
```

The flow was observed on the current test device and produces one `.sdocx` per selected note. The exporter copies files locally and records the original folder path in manifests.

## Formats

- SDOCX: primary archival format.
- TXT: supplemental text-first format; text-empty notes may produce no file.
- PDF, Word, PowerPoint, and image: available in the observed UI but not part of the primary MVP.

## Safety

- Do not choose messaging, email, cloud, Quick Share, or other upload/send targets.
- Keep raw UI dumps and generated exports ignored.
- Verify file counts, hashes, folder paths, and date-like metadata after each run.
