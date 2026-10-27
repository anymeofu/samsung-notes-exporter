from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class WorkflowPhase(str, Enum):
    OBSERVE_SCREEN = "observe_screen"
    CLASSIFY_SCREEN = "classify_screen"
    SELECT_NOTES = "select_notes"
    EXPORT_CURRENT_FOLDER_NOTES = "export_current_folder_notes"
    OPEN_EXPORT_MENU = "open_export_menu"
    CHOOSE_EXPORT_FORMAT = "choose_export_format"
    CHOOSE_DESTINATION = "choose_destination"
    VERIFY_EXPORT = "verify_export"
    PULL_EXPORTS = "pull_exports"
    BUILD_ARCHIVE = "build_archive"
    ENTER_SUBFOLDER = "enter_subfolder"
    RECOVER_FROM_NON_FOLDER = "recover_from_non_folder"
    RETURN_TO_PARENT = "return_to_parent"
    WRITE_RUN_SUMMARY = "write_run_summary"
    MERGE_ARCHIVE = "merge_archive"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class ArtifactRef:
    kind: str
    path: Path
    note: str | None = None

    def compact(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": self.kind,
            "path": str(self.path),
        }
        if self.note:
            payload["note"] = self.note
        return payload


@dataclass(frozen=True)
class SkippedCandidate:
    folder_path: str
    reason: str
    screen_fingerprint: str | None = None
    artifact: ArtifactRef | None = None

    def compact(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "folder_path": self.folder_path,
            "reason": self.reason,
        }
        if self.screen_fingerprint:
            payload["screen_fingerprint"] = self.screen_fingerprint
        if self.artifact:
            payload["artifact"] = self.artifact.compact()
        return payload


@dataclass(frozen=True)
class WorkflowRunState:
    run_id: str
    root_path: str
    phase: WorkflowPhase
    current_folder_path: str | None = None
    screen_fingerprint: str | None = None
    last_action: str | None = None
    next_action: str | None = None
    visited_folders: tuple[str, ...] = ()
    exported_folders: tuple[str, ...] = ()
    skipped_candidates: tuple[SkippedCandidate, ...] = ()
    artifacts: tuple[ArtifactRef, ...] = ()
    counts: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def transition(
        self,
        phase: WorkflowPhase,
        *,
        current_folder_path: str | None = None,
        screen_fingerprint: str | None = None,
        last_action: str | None = None,
        next_action: str | None = None,
        counts: dict[str, int] | None = None,
        artifacts: list[ArtifactRef] | tuple[ArtifactRef, ...] = (),
        skipped_candidates: list[SkippedCandidate] | tuple[SkippedCandidate, ...] = (),
        visited_folder: str | None = None,
        exported_folder: str | None = None,
        error: str | None = None,
    ) -> WorkflowRunState:
        visited = self.visited_folders
        if visited_folder and visited_folder not in visited:
            visited = (*visited, visited_folder)

        exported = self.exported_folders
        if exported_folder and exported_folder not in exported:
            exported = (*exported, exported_folder)

        merged_counts = dict(self.counts)
        if counts:
            merged_counts.update(counts)

        return WorkflowRunState(
            run_id=self.run_id,
            root_path=self.root_path,
            phase=phase,
            current_folder_path=current_folder_path if current_folder_path is not None else self.current_folder_path,
            screen_fingerprint=screen_fingerprint if screen_fingerprint is not None else self.screen_fingerprint,
            last_action=last_action if last_action is not None else self.last_action,
            next_action=next_action,
            visited_folders=visited,
            exported_folders=exported,
            skipped_candidates=(*self.skipped_candidates, *tuple(skipped_candidates)),
            artifacts=(*self.artifacts, *tuple(artifacts)),
            counts=merged_counts,
            error=error,
        )

    def compact(self, *, artifact_limit: int = 8, skipped_limit: int = 8) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "root_path": self.root_path,
            "phase": self.phase.value,
            "current_folder_path": self.current_folder_path,
            "last_action": self.last_action,
            "next_action": self.next_action,
            "counts": dict(sorted(self.counts.items())),
            "visited_folder_count": len(self.visited_folders),
            "exported_folder_count": len(self.exported_folders),
            "skipped_count": len(self.skipped_candidates),
            "updated_at": self.updated_at,
        }
        if self.screen_fingerprint:
            payload["screen_fingerprint"] = self.screen_fingerprint
        if self.artifacts:
            payload["artifacts"] = [artifact.compact() for artifact in self.artifacts[-artifact_limit:]]
        if self.skipped_candidates:
            payload["skipped_candidates"] = [
                candidate.compact() for candidate in self.skipped_candidates[-skipped_limit:]
            ]
        if self.error:
            payload["error"] = self.error
        return payload


def initial_workflow_state(run_id: str, root_path: str) -> WorkflowRunState:
    return WorkflowRunState(
        run_id=run_id,
        root_path=root_path,
        phase=WorkflowPhase.OBSERVE_SCREEN,
        current_folder_path=root_path,
        next_action="observe_screen",
    )
