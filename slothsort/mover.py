"""Applying and undoing a plan — the careful, boring part.

Design rules:
- Never overwrite an existing file. Collisions get a numeric suffix
  (``name-1.ext``, ``name-2.ext``, ...).
- Every applied run is appended to an undo log (JSON) in the tidied folder,
  so `slothsort undo` can put everything back.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .planner import PlanItem

LOG_NAME = ".slothsort-undo.json"


@dataclass
class Move:
    source: Path
    destination: Path


def resolve_collision(destination: Path, reserved: set[Path] | None = None) -> Path:
    """Return *destination*, or a ``-N`` suffixed variant that is free.

    A destination counts as taken if it exists on disk or is already reserved
    by another move in the same run.
    """
    reserved = reserved or set()
    if not destination.exists() and destination not in reserved:
        return destination
    stem, suffix, parent = destination.stem, destination.suffix, destination.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}-{counter}{suffix}"
        if not candidate.exists() and candidate not in reserved:
            return candidate
        counter += 1


def plan_moves(plan: list[PlanItem]) -> list[Move]:
    """Resolve final destinations (with collision suffixes) without moving."""
    moves: list[Move] = []
    reserved: set[Path] = set()
    for item in plan:
        dest = resolve_collision(item.destination, reserved)
        reserved.add(dest)
        moves.append(Move(item.source, dest))
    return moves


def _read_log(folder: Path) -> list[dict]:
    log_path = folder / LOG_NAME
    if not log_path.exists():
        return []
    try:
        data = json.loads(log_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _write_log(folder: Path, runs: list[dict]) -> None:
    (folder / LOG_NAME).write_text(json.dumps(runs, indent=2), encoding="utf-8")


def apply_plan(folder: Path, plan: list[PlanItem]) -> list[Move]:
    """Move files per *plan* and record the run in the undo log."""
    moves = plan_moves(plan)
    done: list[Move] = []
    for move in moves:
        if move.source == move.destination:
            continue
        move.destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(move.source), str(move.destination))
        done.append(move)
    if done:
        runs = _read_log(folder)
        runs.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "moves": [
                    {"from": str(m.source), "to": str(m.destination)} for m in done
                ],
            }
        )
        _write_log(folder, runs)
    return done


def undo_last_run(folder: Path) -> list[Move]:
    """Reverse the most recent applied run in *folder*.

    Returns the moves that were undone (destination -> original location).
    Files that have since vanished are skipped, never guessed at.
    """
    runs = _read_log(folder)
    if not runs:
        return []
    last = runs.pop()
    undone: list[Move] = []
    reserved: set[Path] = set()
    for record in reversed(last.get("moves", [])):
        current = Path(record["to"])
        original = Path(record["from"])
        if not current.exists():
            continue
        target = resolve_collision(original, reserved)
        reserved.add(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(current), str(target))
        undone.append(Move(current, target))
    _write_log(folder, runs)
    return undone
