"""Command-line interface for SlothSort.

Usage:
    python -m slothsort [folder]              # agent plans (dry run), prints plan + trace path
    python -m slothsort [folder] --apply      # agent plans, you confirm, files move
    python -m slothsort [folder] --classic    # one-shot planner instead of the agent harness
    python -m slothsort undo [folder]         # put the last run back
    python -m slothsort [folder] --model gemma3:1b --host http://localhost:11434
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import mover
from .harness import AgentSession
from .planner import DEFAULT_HOST, DEFAULT_MODEL, OllamaClient, OllamaError, make_plan

TRACE_NAME = ".slothsort-trace.jsonl"


def _print_plan(folder: Path, plan) -> None:
    if not plan:
        print(f"Nothing to tidy in {folder} — it's already sloth-approved.")
        return
    width = max(len(item.source.name) for item in plan)
    print(f"\nTidy plan for {folder} ({len(plan)} files):\n")
    print(f"  {'FILE':<{width}}  ->  DESTINATION  (why)")
    print(f"  {'-' * width}  --  -----------")
    for item in plan:
        dest = f"{item.category}/{item.new_name}"
        print(f"  {item.source.name:<{width}}  ->  {dest}  ({item.reason})")
    print()


def _confirm(count: int, folder: Path) -> bool:
    answer = input(f"Move {count} files in {folder}? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def cmd_sort(args: argparse.Namespace) -> int:
    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        print(f"error: {folder} is not a folder.", file=sys.stderr)
        return 2

    client = OllamaClient(host=args.host, model=args.model)

    if args.classic:
        try:
            plan = make_plan(folder, client)
        except OllamaError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        _print_plan(folder, plan)
        if not plan:
            return 0
        if not args.apply:
            print("Dry run — nothing was moved. Re-run with --apply to let the sloth work.")
            return 0
        if not _confirm(len(plan), folder):
            print("Okay, staying lazy. Nothing moved.")
            return 0
        done = mover.apply_plan(folder, plan)
        print(f"Done: moved {len(done)} files. Undo anytime with: slothsort undo {folder}")
        return 0

    # Default: the agent harness drives the model through the tools loop.
    session = AgentSession(folder, client, allow_apply=args.apply)
    try:
        plan = session.run()
    except OllamaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    trace_path = Path(args.trace) if args.trace else folder / TRACE_NAME
    session.write_trace(trace_path)
    if session.summary:
        print(f'Agent summary: "{session.summary}"')
    _print_plan(folder, plan)
    print(f"Session trace: {trace_path} (every model decision + tool call)")
    if not plan:
        return 0

    if not args.apply:
        print("Dry run — nothing was moved. Re-run with --apply to let the sloth work.")
        return 0
    if not _confirm(len(plan), folder):
        print("Okay, staying lazy. Nothing moved.")
        session.write_trace(trace_path)
        return 0

    moved = session.apply()
    session.write_trace(trace_path)
    print(f"Done: moved {moved} files. Undo anytime with: slothsort undo {folder}")
    return 0


def cmd_undo(args: argparse.Namespace) -> int:
    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        print(f"error: {folder} is not a folder.", file=sys.stderr)
        return 2
    undone = mover.undo_last_run(folder)
    if not undone:
        print(f"Nothing to undo in {folder}.")
        return 0
    for move in undone:
        print(f"  {move.source}  ->  {move.destination}")
    print(f"Undid {len(undone)} moves. The mess is back, exactly as it was.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slothsort",
        description="SlothSort — a from-scratch agent harness that tidies files "
        "with a local open-weight model. Dry-run by default, undoable always.",
    )
    parser.add_argument(
        "folder",
        nargs="?",
        default=".",
        help="Folder to tidy (default: current directory). "
        "Tip: use 'slothsort undo <folder>' to reverse the last run.",
    )
    parser.add_argument("--apply", action="store_true", help="Actually move files (after a confirmation prompt).")
    parser.add_argument("--classic", action="store_true", help="Use the one-shot planner instead of the agent harness.")
    parser.add_argument("--trace", default=None, help="Where to write the session trace JSONL (default: <folder>/.slothsort-trace.jsonl).")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model name (default: {DEFAULT_MODEL}).")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Ollama host (default: {DEFAULT_HOST}).")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `slothsort undo [folder]` is a subcommand in spirit; keep argparse simple.
    if argv and argv[0] == "undo":
        undo_parser = argparse.ArgumentParser(prog="slothsort undo")
        undo_parser.add_argument("folder", nargs="?", default=".")
        return cmd_undo(undo_parser.parse_args(argv[1:]))
    return cmd_sort(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
