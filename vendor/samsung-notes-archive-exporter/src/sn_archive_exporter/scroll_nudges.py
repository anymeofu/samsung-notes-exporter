from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Nudge:
    name: str
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    duration_ms: int


NUDGES = {
    "small-forward": Nudge("small-forward", 540, 1500, 540, 1180, 450),
    "medium-forward": Nudge("medium-forward", 540, 1700, 540, 1000, 550),
    "large-forward": Nudge("large-forward", 540, 1850, 540, 650, 750),
    "small-back": Nudge("small-back", 540, 950, 540, 1270, 450),
    "medium-back": Nudge("medium-back", 540, 850, 540, 1550, 550),
    "large-back": Nudge("large-back", 540, 650, 540, 1850, 750),
}


def get_nudge(name: str) -> Nudge:
    try:
        return NUDGES[name]
    except KeyError as exc:
        raise SystemExit(f"Unknown nudge {name!r}; choose one of {sorted(NUDGES)}") from exc


def validate_nudge_sequence(names: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if not names:
        raise SystemExit("Refusing action: at least one nudge is required")
    unknown = [name for name in names if name not in NUDGES]
    if unknown:
        raise SystemExit(f"Unknown nudge(s): {unknown}; choose from {sorted(NUDGES)}")
    return tuple(names)
