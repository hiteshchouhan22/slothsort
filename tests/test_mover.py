"""Tests for moving: collisions, dry-run behaviour, apply + undo round-trip.

Run with: python -m pytest  (or: python -m unittest discover -s tests)
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from slothsort import mover  # noqa: E402
from slothsort.planner import PlanItem  # noqa: E402


def _touch(folder: Path, name: str, content: str) -> Path:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _snapshot(folder: Path) -> dict[str, str]:
    """Map of relative path -> content for every file under folder."""
    return {
        str(p.relative_to(folder)): p.read_text()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.name != mover.LOG_NAME
    }


class TestCollisions(unittest.TestCase):
    def test_existing_destination_gets_numeric_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _touch(folder, "Documents/report.pdf", "old")
            dest = folder / "Documents" / "report.pdf"
            self.assertEqual(
                mover.resolve_collision(dest), folder / "Documents" / "report-1.pdf"
            )

    def test_two_files_same_target_in_one_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            a = _touch(folder, "a report.pdf", "A")
            b = _touch(folder, "report.pdf", "B")
            plan = [
                PlanItem(a, "Documents", "report.pdf", ""),
                PlanItem(b, "Documents", "report.pdf", ""),
            ]
            moves = mover.plan_moves(plan)
            dests = sorted(m.destination.name for m in moves)
            self.assertEqual(dests, ["report-1.pdf", "report.pdf"])


class TestApplyUndo(unittest.TestCase):
    def test_planning_alone_moves_nothing(self):
        """Dry-run: building the plan and resolving moves touches no files."""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            src = _touch(folder, "messy notes.txt", "hello")
            before = _snapshot(folder)
            plan = [PlanItem(src, "Documents", "notes.txt", "tidier name")]
            mover.plan_moves(plan)  # what the CLI does before --apply
            self.assertEqual(_snapshot(folder), before)
            self.assertFalse((folder / mover.LOG_NAME).exists())

    def test_apply_then_undo_restores_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            a = _touch(folder, "IMG_1.JPG", "jpeg-bytes")
            b = _touch(folder, "my song.mp3", "mp3-bytes")
            _touch(folder, "Images/existing.jpg", "already here")
            c = _touch(folder, "photo.jpg", "will collide")
            before = _snapshot(folder)

            plan = [
                PlanItem(a, "Images", "photo-1.jpg", ""),
                PlanItem(b, "Media", "my-song.mp3", ""),
                PlanItem(c, "Images", "existing.jpg", ""),  # collides on purpose
            ]
            done = mover.apply_plan(folder, plan)
            self.assertEqual(len(done), 3)
            self.assertTrue((folder / mover.LOG_NAME).exists())
            self.assertFalse(a.exists())
            self.assertTrue((folder / "Media" / "my-song.mp3").exists())
            # Collision: pre-existing file untouched, newcomer suffixed.
            self.assertEqual((folder / "Images" / "existing.jpg").read_text(), "already here")
            self.assertTrue((folder / "Images" / "existing-1.jpg").exists())

            undone = mover.undo_last_run(folder)
            self.assertEqual(len(undone), 3)
            self.assertEqual(_snapshot(folder), before)

    def test_undo_with_no_history_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(mover.undo_last_run(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
