# Workflow Design

This project uses a small internal workflow/state layer instead of a general-purpose agent framework for the current phase.

## Decision

Do not adopt LangGraph, OpenAI Agents SDK, Microsoft Agent Framework, or similar orchestration frameworks for the MVP stabilization phase.

Use a compact internal state machine for:

- current folder traversal state
- export step progress
- screen fingerprint/schema references
- skipped candidates and recovery outcomes
- local artifact paths
- compact state deltas for stdout/logging

## Rationale

The core work is deterministic Android UI automation through ADB, guarded by local observations. The project does not yet need distributed agents, tool routing, long-running remote orchestration, or model-to-model handoffs.

External graph/agent frameworks would add dependency surface and implementation context before the export path itself is stable. They may also increase token use if every step is represented as framework-level messages instead of a compact local state delta.

The useful idea to borrow is not the framework dependency; it is the discipline of explicit states, transitions, artifacts, and recovery rules.

## State Machine Shape

The automation should describe each step as one of these phases:

- `observe_screen`
- `classify_screen`
- `select_notes`
- `export_current_folder_notes`
- `open_export_menu`
- `choose_export_format`
- `choose_destination`
- `verify_export`
- `pull_exports`
- `build_archive`
- `enter_subfolder`
- `recover_from_non_folder`
- `return_to_parent`
- `write_run_summary`
- `merge_archive`
- `done`
- `failed`

Each transition should produce a compact state delta:

```json
{
  "phase": "enter_subfolder",
  "folder_path": "Codex",
  "next_action": "tap_subfolder",
  "last_action": "observe_screen",
  "counts": {
    "visible_subfolders": 21,
    "visible_note_cards": 2
  },
  "artifacts": [
    {
      "kind": "observation_metadata",
      "path": "observations/run_001_step.metadata.json"
    }
  ]
}
```

The full local logs may contain screenshots, raw UIAutomator XML, parsed candidates, and action history. Normal stdout and model context should contain only compact deltas and artifact paths.

## Token Policy

Normal operation:

- Send or print compact state deltas.
- Refer to cached screen schemas by fingerprint.
- Keep full XML, screenshots, and parsed metadata on disk.
- Avoid reprinting full trees, manifests, and run summaries unless explicitly requested.
- For known-safe dummy roots such as `Codex`, prefer `--summary-only --quiet` after the flow has been proven. The executor still performs guarded UI checks before actions; quiet mode only suppresses step-by-step stderr progress.
- In mixed folders, meaning a folder where subfolders have been observed anywhere in the folder, do not use global select-all for note export even if the current scrolled viewport shows only notes. Select visible note cards directly instead. A future optimization may try select-all plus manual folder deselection, but that needs its own guarded proof because selecting folders is outside the export target.

Escalation:

- If screenshot-first observation is ambiguous, add a compact structural summary.
- If still blocked, inspect raw XML locally and send only relevant nodes.
- Full raw XML is an explicit debug escalation, not routine context.

## Integration Plan

1. Add pure dataclasses and helpers in `workflow_state.py`.
2. Unit test state summaries and deltas without ADB.
3. Gradually replace ad hoc dict result assembly in the folder walker with the state helpers.
4. Add compact workflow events to guarded export steps without printing raw UI dumps.
5. Keep the existing CLI behavior stable while adding more compact `--summary-only` output.
6. Reconsider an external framework only if the project later needs resumable remote jobs, parallel device coordination, or multiple model/tool agents.

## Reconsideration Criteria

Re-evaluate external frameworks only when at least one of these is true:

- Multiple devices or export roots must run concurrently.
- Human approval checkpoints need a durable queue across app restarts.
- Recovery flows become too complex for a small state module.
- A real model planner must choose between multiple tools beyond ADB, archive building, and local parsing.
- Workflow visualization/debugging becomes a primary development bottleneck.
