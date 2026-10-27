# Screenshot-First UI Agent Policy

Samsung Notes automation should use screenshots as the primary observation source. UIAutomator XML is local affordance data for hit-testing and text extraction, not the normal model context.

## Normal Observation

Use `scripts/observe_screen.sh <label>` for routine phone-side observation. It saves local artifacts:

- Raw screenshot: `observations/*.png`
- Raw UI dump: `observations/*.xml`
- Compact metadata: `observations/*.metadata.json`
- Annotated screenshot overlay: `observations/*.annotated.svg`
- Screen schema cache: `screen_schemas/cache.json`

The command prints a short summary plus a candidate preview by default. Full compact candidate metadata is saved in `observations/*.metadata.json`. Do not paste raw XML into chat or docs during normal operation.

## Compact Metadata

The normal observation payload may include:

- Candidate id
- Bounds and center
- Role/class short name
- Short visible text or content description
- Clickable/editable/scrollable state
- Useful resource id when it helps safe action selection
- Screen size, package/activity, screen fingerprint
- Last action and task state

It should not include full XML attributes, invisible nodes, repeated booleans, or irrelevant layout containers.

To inspect the full compact candidate list locally, use:

```bash
PRINT_MODE=compact ./scripts/observe_screen.sh <label>
```

## Escalation Ladder

Level 0: screenshot plus annotated boxes and compact candidates.

Level 1: add a compact structural summary: packages, folder path, note/subfolder counts, selection state, visible buttons, editable fields, scrollable regions, and dangerous actions.

Level 2: inspect raw XML locally and send only selected suspicious nodes or subtrees.

Level 3: send full or near-full raw XML only after explicit approval, unless running in an intentional debug session. Use this only for unknown screen types, repeated action failure, screenshot/metadata disagreement, blocking dialogs, system pickers, or potentially destructive ambiguous actions.

After Level 3, extract a reusable schema, cache it by screen fingerprint, and return to compact observation.

## Action Selection

Choose actions from visual evidence first, then compact metadata. Execute by candidate id, bounds, coordinates, text input, swipe, back, or wait. Prefer stable bounds/node actions when available, but coordinate actions are allowed when visual evidence is clearer.

Do not turn this project into a pure accessibility-tree tool. UI dumps remain auxiliary.

## Logging

Always save screenshots, XML dumps, parsed metadata, actions, and results locally for debugging. Keep these paths ignored by git. Share only compact summaries unless escalation is approved.
