"""Tests for the agent harness loop, using a scripted fake model client.

The fake plays the model: it reads the harness's instructions from the
transcript and replies with the JSON tool call a real model should make.
No Ollama needed. Run with: python -m pytest (or python -m unittest).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from slothsort import mover  # noqa: E402
from slothsort.harness import AgentSession, run_agent  # noqa: E402

CATEGORIES_BY_EXT = {".png": "Images", ".pdf": "Documents", ".mp3": "Media"}


class ScriptedClient:
    """A fake model that follows the harness protocol from the transcript."""

    def __init__(self):
        self.calls = 0

    def chat_messages(self, messages):
        self.calls += 1
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        if "CONFIRMED" in last_user:
            return json.dumps({"tool": "apply_plan", "args": {}})
        if "All files are classified" in last_user:
            return json.dumps(
                {"tool": "finish_plan", "args": {"summary": "Tidied. Eventually."}}
            )
        if "NEXT_FILE:" in last_user:
            name = last_user.split("NEXT_FILE:", 1)[1].split("(", 1)[0].strip()
            ext = Path(name).suffix.lower()
            return json.dumps(
                {
                    "tool": "classify_file",
                    "args": {
                        "file": name,
                        "category": CATEGORIES_BY_EXT.get(ext, "Misc"),
                        "new_name": name.lower().replace(" ", "-"),
                        "reason": "scripted fake decision",
                    },
                }
            )
        return json.dumps({"tool": "list_files", "args": {}})


class RogueClient(ScriptedClient):
    """Tries to move files immediately, before any human confirmation."""

    def chat_messages(self, messages):
        if self.calls == 0:
            self.calls += 1
            return json.dumps({"tool": "apply_plan", "args": {}})
        return super().chat_messages(messages)


def _touch(folder: Path, name: str, content: str = "x") -> Path:
    path = folder / name
    path.write_text(content)
    return path


class TestHarnessLoop(unittest.TestCase):
    def test_full_loop_produces_a_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _touch(folder, "My Photo.PNG")
            _touch(folder, "tax return.pdf")
            _touch(folder, "song.mp3")
            plan, session = run_agent(folder, ScriptedClient())
            self.assertEqual(len(plan), 3)
            by_name = {item.source.name: item for item in plan}
            self.assertEqual(by_name["My Photo.PNG"].category, "Images")
            self.assertEqual(by_name["My Photo.PNG"].new_name, "my-photo.png")
            self.assertEqual(by_name["tax return.pdf"].category, "Documents")
            self.assertEqual(session.summary, "Tidied. Eventually.")
            # Nothing moved: planning is a dry run.
            self.assertTrue((folder / "My Photo.PNG").exists())

    def test_model_cannot_apply_in_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _touch(folder, "a.pdf")
            plan, session = run_agent(folder, RogueClient(), allow_apply=False)
            self.assertEqual(len(plan), 1)
            events = [e["event"] for e in session.trace]
            self.assertIn("tool_refused", events)
            self.assertTrue((folder / "a.pdf").exists())
            self.assertFalse((folder / mover.LOG_NAME).exists())

    def test_apply_phase_moves_and_undo_restores(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _touch(folder, "My Photo.PNG", "img")
            session = AgentSession(folder, ScriptedClient(), allow_apply=True)
            session.run()
            moved = session.apply()
            self.assertEqual(moved, 1)
            self.assertTrue((folder / "Images" / "my-photo.png").exists())
            undone = mover.undo_last_run(folder)
            self.assertEqual(len(undone), 1)
            self.assertTrue((folder / "My Photo.PNG").exists())

    def test_trace_is_written_as_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _touch(folder, "a.pdf")
            trace_path = folder / "trace.jsonl"
            _, session = run_agent(folder, ScriptedClient(), trace_path=trace_path)
            lines = trace_path.read_text().strip().splitlines()
            events = [json.loads(line) for line in lines]
            kinds = [e["event"] for e in events]
            self.assertIn("session_start", kinds)
            self.assertIn("tool_call", kinds)
            tools_called = [e["tool"] for e in events if e["event"] == "tool_call"]
            self.assertIn("list_files", tools_called)
            self.assertIn("classify_file", tools_called)
            self.assertIn("plan_complete", kinds)
            self.assertEqual(len(events), len(session.trace))


if __name__ == "__main__":
    unittest.main()
