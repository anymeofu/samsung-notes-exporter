# Selection Count Probe

This tool explains mismatches between Samsung Notes selection counts and exported visible-batch counts without printing raw UI XML or note text.

Use it only with a harmless test folder. The probe records hashed visible-card fingerprints locally, compares them with the batch state, and distinguishes stable tappable cards from unsafe edge-only cards.

Safety rules:

- Keep raw XML, screenshots, and state files local and ignored.
- Run a read-only coverage probe before recovery export.
- Export only stable tappable cards.
- Stop on repeated screens, unknown screens, or a possible destructive action.
