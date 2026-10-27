# Feasibility Report

## Result

The realistic local MVP route is:

```text
Samsung Notes visible UI
→ Save as file
→ Samsung Notes file
→ Samsung My Files local destination
→ copy-only ADB pull
→ folder-preserving archive
```

This route was proven on the current device and supports folder paths, nested folders, large-folder visible batches, resume state, and manifest validation.

## Limits

- UI labels, resource IDs, coordinates, and export behavior vary by device, language, resolution, and Samsung Notes version.
- Large selections can hide export controls, so the runner partitions selections and uses local hashed fingerprints.
- TXT is not lossless and can omit text-empty notes; SDOCX remains authoritative.
- Deep breadcrumb behavior and unusual test-folder screens may require fresh probes.

## Recommendation

Use the guarded runner with a harmless test tree first. For another environment, run the adaptation prompt in `docs/prompts/` and rebuild screen schemas from fresh observations instead of copying coordinates blindly.
