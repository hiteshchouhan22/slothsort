"""Tests for planning: model-JSON parsing, scanning, prompt building.

No Ollama needed — a fake client returns canned replies.
Run with: python -m pytest  (or: python -m unittest discover -s tests)
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from slothsort.planner import make_plan, parse_plan, scan_folder  # noqa: E402


class FakeClient:
    """Stands in for OllamaClient: returns a fixed reply, records prompts."""

    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list[str] = []

    def chat(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


def _touch(folder: Path, name: str, content: str = "x") -> Path:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


import tempfile  # noqa: E402


class TestPlanParsing(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_parses_plain_json_array(self):
        files = [_touch(self.folder, "IMG_4021.JPG"), _touch(self.folder, "notes.txt")]
        reply = (
            '[{"file": "IMG_4021.JPG", "category": "Images", '
            '"new_name": "img-4021.jpg", "reason": "Photo file"},'
            ' {"file": "notes.txt", "category": "Documents", '
            '"new_name": "notes.txt", "reason": "Text notes"}]'
        )
        plan = parse_plan(files, reply)
        self.assertEqual(len(plan), 2)
        self.assertEqual(plan[0].category, "Images")
        self.assertEqual(plan[0].destination, self.folder / "Images" / "img-4021.jpg")
        self.assertEqual(plan[1].category, "Documents")

    def test_parses_json_wrapped_in_code_fences_and_prose(self):
        files = [_touch(self.folder, "report final v2.pdf")]
        reply = (
            "Here is your plan:\n```json\n"
            '[{"file": "report final v2.pdf", "category": "Documents", '
            '"new_name": "report.pdf", "reason": "Cleaned-up PDF name"}]'
            "\n```\nHope that helps!"
        )
        plan = parse_plan(files, reply)
        self.assertEqual(plan[0].new_name, "report.pdf")
        self.assertEqual(plan[0].category, "Documents")

    def test_unknown_category_falls_back_to_misc(self):
        files = [_touch(self.folder, "thing.xyz")]
        reply = '[{"file": "thing.xyz", "category": "Banana", "new_name": "thing.xyz", "reason": "?"}]'
        plan = parse_plan(files, reply)
        self.assertEqual(plan[0].category, "Misc")

    def test_model_suggested_path_traversal_is_sanitised(self):
        files = [_touch(self.folder, "evil.sh")]
        reply = '[{"file": "evil.sh", "category": "Code", "new_name": "../../evil.sh", "reason": "script"}]'
        plan = parse_plan(files, reply)
        self.assertEqual(plan[0].new_name, "evil.sh")
        self.assertEqual(plan[0].destination.parent, self.folder / "Code")

    def test_files_the_model_forgot_get_misc_default(self):
        files = [_touch(self.folder, "a.txt"), _touch(self.folder, "forgotten.bin")]
        reply = '[{"file": "a.txt", "category": "Documents", "new_name": "a.txt", "reason": "text"}]'
        plan = parse_plan(files, reply)
        by_name = {item.source.name: item for item in plan}
        self.assertEqual(len(plan), 2)
        self.assertEqual(by_name["forgotten.bin"].category, "Misc")

    def test_garbage_reply_raises(self):
        files = [_touch(self.folder, "a.txt")]
        with self.assertRaises(Exception):
            parse_plan(files, "I am a sloth and I refuse to answer.")


class TestScanAndPrompt(unittest.TestCase):
    def test_scan_skips_hidden_dirs_and_own_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _touch(folder, "visible.txt")
            _touch(folder, ".hidden.txt")
            _touch(folder, ".slothsort-undo.json", "[]")
            _touch(folder, "SubFolder/inner.txt")
            found = [p.name for p in scan_folder(folder)]
            self.assertEqual(found, ["visible.txt"])

    def test_make_plan_sends_listing_to_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            _touch(folder, "photo.png")
            client = FakeClient(
                '[{"file": "photo.png", "category": "Images", '
                '"new_name": "photo.png", "reason": "image"}]'
            )
            plan = make_plan(folder, client)
            self.assertEqual(len(client.prompts), 1)
            self.assertIn("photo.png", client.prompts[0])
            self.assertEqual(plan[0].category, "Images")


if __name__ == "__main__":
    unittest.main()
