"""A tiny agent harness, built from scratch, with SlothSort as its job.

The harness runs a model <-> tools loop over a *local* open-weight model
(Gemma via Ollama by default):

- the model never touches the filesystem directly; it can only emit JSON
  tool calls;
- the harness validates and executes each call, feeds the result back, and
  keeps the loop going until the plan is complete;
- every model reply, tool call, refusal and fallback is written to a session
  trace (JSONL), so a run can be audited line by line.

Tools
-----
list_files      List the files in the target folder (harness-scanned, so
                hidden files and SlothSort's own logs never appear).
classify_file   Record the model's filing decision for one file:
                {file, category, new_name, reason}. Categories and names are
                validated/sanitised by the harness, not trusted from the model.
finish_plan     End the planning loop.
apply_plan      Execute the moves. Gated: in dry-run mode the harness refuses
                this call, so the model literally cannot move files until a
                human has seen the plan and confirmed.
undo_last_run   Reverse the last applied run (same undo log as the CLI).

Small models are imperfect instruction followers, so the harness guides the
loop one step at a time ("classify THIS file next"), retries malformed calls
with feedback, and — as a last resort — files a file under Misc itself and
says so in the trace. The trace never hides a fallback.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import mover
from .planner import CATEGORIES, PlanItem, sanitise_name, scan_folder

SYSTEM_PROMPT = """You are the brain of SlothSort, a lazy file-tidying agent.
You cannot touch files yourself. You act ONLY by replying with one JSON tool
call at a time, with no other text, in this exact shape:
{"tool": "<tool name>", "args": { ... }}

Tools:
- list_files: args {} — list the untidied files.
- classify_file: args {"file": "<exact filename>", "category": "<one of: {categories}>", "new_name": "<cleaner filename, keep the extension; lowercase words with hyphens or underscores; keep unchanged if already clean>", "reason": "<short reason, max 12 words>"}
- finish_plan: args {"summary": "<one short line>"} — call when every file is classified.
- apply_plan: args {} — move the files. Only call if the harness says the user confirmed; it will refuse otherwise.

Be decisive, be lazy, be tidy.""".replace(
    "{categories}", ", ".join(CATEGORIES)
)


@dataclass
class TraceEvent:
    event: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": self.event,
            **self.data,
        }


@dataclass
class Tool:
    name: str
    description: str


# The registry: name -> description. Handlers are AgentSession methods named
# `_tool_<name>`, which keeps the registry declarative and easy to extend.
TOOLS: dict[str, Tool] = {
    "list_files": Tool("list_files", "List untidied files in the target folder."),
    "classify_file": Tool("classify_file", "Record a filing decision for one file."),
    "finish_plan": Tool("finish_plan", "End the planning loop."),
    "apply_plan": Tool("apply_plan", "Execute the planned moves (human-gated)."),
    "undo_last_run": Tool("undo_last_run", "Reverse the last applied run."),
}


def _parse_tool_call(raw: str) -> dict | None:
    """Extract a {"tool": ..., "args": {...}} object from a model reply."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    candidates = [text]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "tool" in data:
            args = data.get("args", {})
            data["args"] = args if isinstance(args, dict) else {}
            return data
    return None


class AgentSession:
    """One harness run over one folder."""

    def __init__(
        self,
        folder: Path,
        client,
        allow_apply: bool = False,
        max_retries: int = 3,
    ) -> None:
        self.folder = Path(folder)
        self.client = client
        self.allow_apply = allow_apply
        self.max_retries = max_retries
        self.files: list[Path] = []
        self.classified: dict[str, PlanItem] = {}
        self.plan: list[PlanItem] = []
        self.summary: str = ""
        self.trace: list[dict] = []
        self.messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Tidy the folder {self.folder}. Start by calling list_files. "
                    'Reply with ONLY this JSON: {"tool": "list_files", "args": {}}'
                ),
            },
        ]

    # -- tracing ---------------------------------------------------------
    def _trace(self, event: str, **data) -> None:
        self.trace.append(TraceEvent(event, data).to_dict())

    def write_trace(self, path: Path) -> None:
        path.write_text(
            "\n".join(json.dumps(e) for e in self.trace) + "\n", encoding="utf-8"
        )

    # -- model plumbing ----------------------------------------------------
    def _ask_model(self) -> str:
        chat_messages = getattr(self.client, "chat_messages", None)
        if callable(chat_messages):
            reply = chat_messages(self.messages)
        else:  # fall back to single-prompt clients: flatten the transcript
            transcript = "\n".join(
                f"{m['role'].upper()}: {m['content']}" for m in self.messages
            )
            reply = self.client.chat(transcript)
        self.messages.append({"role": "assistant", "content": reply})
        self._trace("model_reply", reply=reply)
        return reply

    def _feedback(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})
        self._trace("harness_feedback", message=text)

    # -- tools ---------------------------------------------------------------
    def _tool_list_files(self, args: dict) -> dict:
        self.files = scan_folder(self.folder)
        return {"files": [f.name for f in self.files], "count": len(self.files)}

    def _tool_classify_file(self, args: dict) -> dict:
        name = str(args.get("file", ""))
        target = next((f for f in self.files if f.name == name), None)
        if target is None:
            return {"error": f"unknown file: {name!r}. Call list_files and use exact names."}
        category = str(args.get("category", "Misc")).strip()
        if category not in CATEGORIES:
            category = "Misc"
        new_name = sanitise_name(str(args.get("new_name", target.name)), target)
        reason = str(args.get("reason", "")).strip() or "No reason given."
        self.classified[target.name] = PlanItem(target, category, new_name, reason)
        remaining = [f.name for f in self.files if f.name not in self.classified]
        return {"recorded": target.name, "remaining": remaining}

    def _tool_finish_plan(self, args: dict) -> dict:
        self.summary = str(args.get("summary", "")).strip()
        return {"status": "plan complete"}

    def _tool_apply_plan(self, args: dict) -> dict:
        if not self.allow_apply:
            self._trace("tool_refused", tool="apply_plan", reason="dry-run mode")
            return {
                "error": "REFUSED: dry-run mode. A human must see the plan and "
                "confirm before anything moves."
            }
        done = mover.apply_plan(self.folder, self.plan)
        return {"moved": len(done)}

    def _tool_undo_last_run(self, args: dict) -> dict:
        undone = mover.undo_last_run(self.folder)
        return {"undone": len(undone)}

    def _dispatch(self, call: dict) -> dict:
        name = call.get("tool", "")
        handler = getattr(self, f"_tool_{name}", None)
        if name not in TOOLS or handler is None:
            result = {"error": f"unknown tool: {name!r}. Valid tools: {', '.join(TOOLS)}"}
            self._trace("tool_error", tool=name, result=result)
            return result
        self._trace("tool_call", tool=name, args=call.get("args", {}))
        result = handler(call.get("args", {}))
        self._trace("tool_result", tool=name, result=result)
        return result

    # -- the loop --------------------------------------------------------------
    def _step(self, instruction: str, expected_tool: str) -> dict | None:
        """Ask the model for one specific tool call, retrying with feedback."""
        self._feedback(instruction)
        for attempt in range(1, self.max_retries + 1):
            raw = self._ask_model()
            call = _parse_tool_call(raw)
            if call is None:
                self._trace("retry", attempt=attempt, reason="unparseable reply")
                self._feedback(
                    "That was not a valid JSON tool call. Reply with ONLY the "
                    f"JSON for {expected_tool}, nothing else."
                )
                continue
            if call["tool"] != expected_tool:
                # A valid but unexpected call still gets executed (so the model
                # can, e.g., call list_files again) — except apply attempts,
                # which the tool itself gates.
                result = self._dispatch(call)
                if call["tool"] == "apply_plan":
                    return call
                self._feedback(
                    f"Tool result: {json.dumps(result)}\n"
                    f"Now reply with ONLY the JSON for {expected_tool}."
                )
                continue
            return call
        return None

    def run(self) -> list[PlanItem]:
        """Run the planning loop and return the plan (moves nothing)."""
        self._trace("session_start", folder=str(self.folder), allow_apply=self.allow_apply)

        call = self._step("Begin.", "list_files")
        if call is not None and call["tool"] == "list_files":
            self._dispatch(call)
        else:
            # Model couldn't manage step one; scan ourselves, say so in trace.
            self._trace("fallback", step="list_files", reason="model did not call it")
            self._dispatch({"tool": "list_files", "args": {}})

        for target in self.files:
            if target.name in self.classified:
                continue
            instruction = (
                f"TOOL RESULT (list_files/classify_file): progress noted.\n"
                f"Classify this file next.\nNEXT_FILE: {target.name} "
                f"({target.stat().st_size} bytes)\n"
                "Reply with ONLY the classify_file JSON tool call for this file."
            )
            call = self._step(instruction, "classify_file")
            if call is not None and call["tool"] == "classify_file":
                self._dispatch(call)
            if target.name not in self.classified:
                self._trace("fallback", step="classify_file", file=target.name,
                            reason="model failed to classify; harness filed under Misc")
                self._dispatch(
                    {
                        "tool": "classify_file",
                        "args": {
                            "file": target.name,
                            "category": "Misc",
                            "new_name": target.name,
                            "reason": "Harness fallback: model did not classify this file.",
                        },
                    }
                )

        self.plan = [self.classified[f.name] for f in self.files]
        call = self._step(
            "All files are classified. Reply with ONLY the finish_plan JSON "
            'tool call: {"tool": "finish_plan", "args": {"summary": "<one short line>"}}',
            "finish_plan",
        )
        if call is not None and call["tool"] == "finish_plan":
            self._dispatch(call)
        else:
            self._trace("fallback", step="finish_plan", reason="model did not finish cleanly")
        self._trace("plan_complete", files=len(self.plan), summary=self.summary)
        return self.plan

    def apply(self) -> int:
        """Apply phase: ask the model to call apply_plan, then execute.

        Only callable after run() and only meaningful when allow_apply is set
        (i.e. a human confirmed). If the model fumbles the call, the harness
        executes it directly and records that honestly in the trace.
        """
        if not self.allow_apply:
            raise RuntimeError("apply() called without allow_apply — the gate held.")
        call = self._step(
            "The user has SEEN the plan and CONFIRMED. Reply with ONLY: "
            '{"tool": "apply_plan", "args": {}}',
            "apply_plan",
        )
        if call is not None and call["tool"] == "apply_plan":
            result = self._dispatch(call)
            moved = int(result.get("moved", 0))
        else:
            self._trace("fallback", step="apply_plan",
                        reason="model did not call it after confirmation; harness executed")
            done = mover.apply_plan(self.folder, self.plan)
            moved = len(done)
            self._trace("tool_result", tool="apply_plan",
                        result={"moved": moved, "executor": "harness_fallback"})
        self._trace("session_end", moved=moved)
        return moved


def run_agent(
    folder: Path,
    client,
    allow_apply: bool = False,
    trace_path: Path | None = None,
) -> tuple[list[PlanItem], AgentSession]:
    """Convenience wrapper: run a session, optionally persist its trace."""
    session = AgentSession(folder, client, allow_apply=allow_apply)
    plan = session.run()
    if trace_path is not None:
        session.write_trace(trace_path)
    return plan, session
