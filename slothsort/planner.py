"""Planning: turn a folder listing into a tidy-up plan using a local model.

The model client is a tiny protocol: anything with a ``chat(prompt) -> str``
method works. ``OllamaClient`` talks to a real Ollama server over HTTP using
only the standard library; tests inject a fake client instead.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HOST = "http://localhost:11434"
# Gemma 3 (Google's open-weight family) is the default: it is the model the
# agent harness was built and demoed with. Any Ollama model works, though —
# e.g. SLOTH_MODEL=qwen2.5:0.5b for an even smaller footprint.
DEFAULT_MODEL = "gemma3:1b"

CATEGORIES = [
    "Documents",
    "Images",
    "Code",
    "Archives",
    "Media",
    "Spreadsheets",
    "Presentations",
    "Installers",
    "Misc",
]

# Files SlothSort itself writes next to the target folder's undo logs.
# They are never planned, moved, or tidied.
OWN_FILE_PREFIXES = (".slothsort",)

PROMPT_TEMPLATE = """You are SlothSort, a lazy but careful file organiser.
For each file below, decide:
- "category": exactly one of {categories}
- "new_name": a cleaner filename. Keep the original extension. Use lowercase
  words separated by hyphens or underscores. If the name is already clean,
  keep it unchanged.
- "reason": one short line (max 12 words) explaining the choice.

Reply with ONLY a JSON array, one object per file, in the same order:
[{{"file": "<original filename>", "category": "...", "new_name": "...", "reason": "..."}}]

Files:
{listing}
"""


@dataclass
class PlanItem:
    """One proposed move: source file -> category folder / new name."""

    source: Path
    category: str
    new_name: str
    reason: str

    @property
    def destination(self) -> Path:
        return self.source.parent / self.category / self.new_name


class OllamaError(RuntimeError):
    """Raised when Ollama is unreachable or returns something unusable."""


class OllamaClient:
    """Minimal Ollama chat client (stdlib urllib only)."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        model: str = DEFAULT_MODEL,
        timeout: float = 120.0,
    ) -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(self, prompt: str) -> str:
        return self.chat_messages([{"role": "user", "content": prompt}])

    def chat_messages(self, messages: list[dict]) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "stream": False,
                # Ask for JSON back; small models still sometimes wrap it in
                # prose or code fences, which the parsers tolerate.
                "format": "json",
                "options": {"temperature": 0.1},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.host}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise OllamaError(
                f"Could not reach Ollama at {self.host} ({exc}). "
                "Is `ollama serve` running?"
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise OllamaError(f"Ollama returned a non-JSON response: {exc}") from exc
        try:
            return body["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise OllamaError(f"Unexpected Ollama response shape: {body!r}") from exc


def scan_folder(folder: Path) -> list[Path]:
    """List the files SlothSort is willing to plan for, sorted by name.

    Skips directories, hidden files, and SlothSort's own log files.
    """
    files: list[Path] = []
    for entry in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if not entry.is_file():
            continue
        if entry.name.startswith("."):
            continue
        if entry.name.startswith(OWN_FILE_PREFIXES):
            continue
        files.append(entry)
    return files


def build_prompt(files: list[Path]) -> str:
    listing = "\n".join(
        f"{i + 1}. {f.name} ({f.stat().st_size} bytes)" for i, f in enumerate(files)
    )
    return PROMPT_TEMPLATE.format(categories=", ".join(CATEGORIES), listing=listing)


def _extract_json_array(text: str) -> list:
    """Pull the first JSON array out of a model reply, tolerating fences/prose."""
    text = text.strip()
    if text.startswith("```"):
        # Strip a markdown code fence.
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise OllamaError(f"Model did not return a JSON array. Raw reply: {text[:200]!r}")
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise OllamaError(f"Could not parse model JSON: {exc}") from exc
    # Some small models wrap the array in an object, e.g. {"files": [...]}.
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                data = value
                break
    if not isinstance(data, list):
        raise OllamaError(f"Model did not return a JSON array. Raw reply: {text[:200]!r}")
    return data


def sanitise_name(raw: str, original: Path) -> str:
    """Keep a model-suggested name safe: no paths, no traversal, keep extension."""
    name = Path(str(raw).strip()).name  # drops any directory components
    name = name.replace("/", "_").replace("\\", "_").strip()
    if not name or name in {".", ".."}:
        return original.name
    if original.suffix and Path(name).suffix.lower() != original.suffix.lower():
        name = f"{Path(name).stem}{original.suffix}"
    return name


def parse_plan(files: list[Path], raw_reply: str) -> list[PlanItem]:
    """Turn the model's raw reply into PlanItems matched back to real files."""
    entries = _extract_json_array(raw_reply)
    by_name = {f.name: f for f in files}
    plan: list[PlanItem] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        original = by_name.get(str(entry.get("file", "")))
        if original is None or original.name in seen:
            continue
        seen.add(original.name)
        category = str(entry.get("category", "Misc")).strip()
        if category not in CATEGORIES:
            category = "Misc"
        new_name = sanitise_name(str(entry.get("new_name", original.name)), original)
        reason = str(entry.get("reason", "")).strip() or "No reason given."
        plan.append(PlanItem(original, category, new_name, reason))
    # Anything the model forgot still gets a sensible default home.
    for f in files:
        if f.name not in seen:
            plan.append(PlanItem(f, "Misc", f.name, "Model skipped it; filed under Misc."))
    return plan


def make_plan(folder: Path, client) -> list[PlanItem]:
    """Scan *folder* and ask *client* (anything with .chat) for a tidy plan."""
    files = scan_folder(folder)
    if not files:
        return []
    reply = client.chat(build_prompt(files))
    return parse_plan(files, reply)


def env_client() -> OllamaClient:
    """Build a client from SLOTH_OLLAMA_HOST / SLOTH_MODEL env vars, if set."""
    return OllamaClient(
        host=os.environ.get("SLOTH_OLLAMA_HOST", DEFAULT_HOST),
        model=os.environ.get("SLOTH_MODEL", DEFAULT_MODEL),
    )
