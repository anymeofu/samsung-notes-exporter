from __future__ import annotations

import unittest
from pathlib import Path

from sn_archive_exporter.workflow_state import (
    ArtifactRef,
    SkippedCandidate,
    WorkflowPhase,
    initial_workflow_state,
)


class WorkflowStateTests(unittest.TestCase):
    def test_initial_state_is_compact_and_observation_first(self) -> None:
        state = initial_workflow_state("run_001", "Codex")

        compact = state.compact()

        self.assertEqual(compact["run_id"], "run_001")
        self.assertEqual(compact["phase"], "observe_screen")
        self.assertEqual(compact["current_folder_path"], "Codex")
        self.assertEqual(compact["next_action"], "observe_screen")
        self.assertEqual(compact["visited_folder_count"], 0)

    def test_transition_updates_counts_and_deduplicates_folder_progress(self) -> None:
        state = initial_workflow_state("run_001", "Codex")

        next_state = state.transition(
            WorkflowPhase.EXPORT_CURRENT_FOLDER_NOTES,
            current_folder_path="Codex",
            last_action="classify_screen",
            next_action="select_notes",
            counts={"visible_note_cards": 2, "visible_subfolders": 21},
            visited_folder="Codex",
            exported_folder="Codex",
        ).transition(
            WorkflowPhase.RETURN_TO_PARENT,
            visited_folder="Codex",
            exported_folder="Codex",
        )

        compact = next_state.compact()

        self.assertEqual(compact["phase"], "return_to_parent")
        self.assertEqual(compact["visited_folder_count"], 1)
        self.assertEqual(compact["exported_folder_count"], 1)
        self.assertEqual(compact["counts"]["visible_note_cards"], 2)
        self.assertEqual(compact["counts"]["visible_subfolders"], 21)

    def test_compact_limits_artifacts_and_skipped_candidates(self) -> None:
        state = initial_workflow_state("run_001", "Codex")
        artifacts = [ArtifactRef("observation_metadata", Path(f"observations/{index}.json")) for index in range(10)]
        skipped = [
            SkippedCandidate(
                folder_path=f"Codex/Folder {index}",
                reason="non_folder_screen_after_tap",
                artifact=artifacts[index],
            )
            for index in range(10)
        ]

        next_state = state.transition(
            WorkflowPhase.RECOVER_FROM_NON_FOLDER,
            artifacts=artifacts,
            skipped_candidates=skipped,
        )
        compact = next_state.compact(artifact_limit=3, skipped_limit=2)

        self.assertEqual([item["path"] for item in compact["artifacts"]], [
            "observations/7.json",
            "observations/8.json",
            "observations/9.json",
        ])
        self.assertEqual([item["folder_path"] for item in compact["skipped_candidates"]], [
            "Codex/Folder 8",
            "Codex/Folder 9",
        ])
        self.assertEqual(compact["skipped_count"], 10)


if __name__ == "__main__":
    unittest.main()
