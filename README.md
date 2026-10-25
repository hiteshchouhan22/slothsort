# SlothSort 🦥

**A tiny agent harness built from scratch — and the lazy file tidier it runs.**

SlothSort is two things:

1. **A from-scratch agent harness** (`slothsort/harness.py`, ~350 lines of
   stdlib Python, zero dependencies): a model↔tools loop over a *local*
   open-weight model. The model never touches your files. It can only reply
   with JSON tool calls; the harness validates each one, executes it, feeds
   the result back, and writes a **full session trace** of every decision.
2. **Its demo job: tidying a messy folder.** Point it at your `~/Downloads`
   disaster zone. The agent lists the files, classifies each one (category,
   cleaner filename, one-line reason), and presents a plan. Nothing moves
   until you say so.

Built for the DEV Hacktoberfest 2026 Week 3 challenge — theme **"Slow and
Steady"**: software that rewards laziness. The sloth does the filing. You
keep your energy.

## Why an agent harness, not a script?

A one-shot prompt ("here are 40 files, return JSON") works until it doesn't:
small local models drop files, invent filenames, or emit prose instead of
JSON. The harness fixes that structurally:

- **One decision at a time.** The loop asks the model to classify *this*
  file next, then feeds the result back. Even a 1B model can do that
  reliably.
- **Tools, not trust.** The model can only act through a small tool registry
  (`list_files`, `classify_file`, `finish_plan`, `apply_plan`,
  `undo_last_run`). Categories are validated, suggested names are sanitised
  (no path traversal, extension preserved), unknown files are rejected.
- **Retries with feedback, honest fallbacks.** A malformed reply gets a
  correction and another chance. If the model still fumbles, the harness
  files the file under `Misc` itself — and records the fallback in the trace.
  Nothing is silently faked.
- **A human gate the model cannot bypass.** `apply_plan` is refused by the
  harness in dry-run mode. The model *cannot* move your files until you have
  seen the plan and typed `y`.
- **A trace of everything.** Each run writes `.slothsort-trace.jsonl` — every
  model reply, tool call, refusal and fallback, timestamped. Audit it, diff
  it, learn from it.

## The model: Gemma, running on your machine

By default the harness drives **Gemma 3 (`gemma3:1b`)**, Google's open-weight
model family, served locally by [Ollama](https://ollama.com). The harness is
model-agnostic — the loop, tools and trace don't care which model is behind
the API:

```bash
SLOTH_MODEL=qwen2.5:0.5b python -m slothsort ~/Downloads   # smaller/faster
SLOTH_MODEL=llama3.2:1b  python -m slothsort ~/Downloads   # different brain
```

## Why local and open matters

- **Private by architecture.** Your filenames — tax returns, medical scans,
  that `final_FINAL_v9` resume — never leave your machine. There is no cloud
  call to leak them to.
- **Offline.** Works on a plane, in a cabin, during an outage.
- **Free forever.** No API key, no per-token bill, no rate limit.
- **Swappable.** Open weights mean the model is a component, not a landlord.
  When a better small model ships, you pull it and the harness doesn't change.

## Quick start

```bash
# 1. Install Ollama (https://ollama.com), then pull the default model:
ollama pull gemma3:1b
ollama serve            # leave running in another terminal

# 2. Dry run — see the plan, move nothing:
python -m slothsort ~/Downloads

# 3. Like the plan? Apply it (it will ask you to confirm):
python -m slothsort ~/Downloads --apply

# 4. Regret everything? Undo the last run:
python -m slothsort undo ~/Downloads
```

No install needed: the project is pure standard library, Python 3.9+. Run it
straight from the repo root with `python -m slothsort`.

## Safety features (the boring part that matters)

- **Dry-run by default.** A plan is printed as a table; zero files move
  without `--apply` *and* an interactive confirmation.
- **Undo log.** Every applied run is recorded in `.slothsort-undo.json` in
  the folder. `slothsort undo` reverses the last run exactly.
- **Never overwrite.** If a destination exists, the newcomer gets a numeric
  suffix (`report-1.pdf`). Your existing files are never clobbered.
- **Hands off the wrong files.** Hidden files and SlothSort's own logs are
  never planned or moved.
- **Sanitised suggestions.** Model-proposed names can't escape the category
  folder (`../../evil.sh` becomes just `evil.sh`).

## Demo

```bash
python demo/make_mess.py          # creates demo/messy/ with 12 sad files
python -m slothsort demo/messy    # watch the agent plan
python -m slothsort demo/messy --apply
python -m slothsort undo demo/messy
```

A captured real run (model output included, nothing staged) lives in
[`demo/DEMO.md`](demo/DEMO.md), with the raw session trace alongside it.

## How it works

```
slothsort/
  harness.py   the agent loop: tools registry, validation, retries,
               fallbacks, the apply gate, the JSONL session trace
  planner.py   Ollama client (stdlib HTTP), folder scanning, and the
               one-shot planner used by --classic mode
  mover.py     plan application: collision suffixes, undo log, undo
  cli.py       argument parsing, plan table, confirmation prompt
tests/         pytest/unittest suite — scripted fake model clients,
               no Ollama required
```

## Tests

```bash
python -m pytest        # or: python -m unittest discover -s tests
```

17 tests: plan parsing (including fences/prose-wrapped JSON), path-traversal
sanitisation, collision handling, dry-run moves nothing, apply+undo
round-trip, the full harness loop against a scripted fake model, the dry-run
apply refusal, and trace integrity.

## License

MIT
