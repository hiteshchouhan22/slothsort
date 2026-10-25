---
title: "SlothSort: I built a tiny agent harness from scratch, then taught it to tidy my Downloads folder so I never have to"
published: false
tags: devchallenge, hf26challenge, opensource, ai, python
---

*This is a submission for the [Hacktoberfest Open-Source AI Challenge: Week 3](https://dev.to/challenges/hacktoberfest-week3-2026-10-19) — theme: **Slow and Steady**.*

## What I built

Two things, really:

**1. A small agent harness, written from scratch.** About 350 lines of standard-library Python, zero dependencies. It runs a model↔tools loop over a local open-weight model: the model never touches the filesystem — it can only reply with JSON tool calls (`list_files`, `classify_file`, `finish_plan`, `apply_plan`, `undo_last_run`). The harness validates every call, executes it, feeds the result back, retries malformed replies with feedback, and writes a **full session trace (JSONL)** of every model decision, tool call, refusal and fallback. If the model fumbles a step, the harness says so in the trace — nothing is silently faked.

**2. SlothSort, the harness's job: a file tidier that rewards laziness.** Point it at a messy folder. The agent lists the files, classifies each one into a category with a cleaner filename and a one-line reason, and shows you a plan. It is the "Slow and Steady" deal: the sloth does the filing, slowly and carefully; you keep your energy.

```bash
python demo/make_mess.py                 # a folder with 12 sad files
python -m slothsort demo/messy           # dry run: plan only
python -m slothsort demo/messy --apply   # confirmed? then it moves
python -m slothsort undo demo/messy      # regret? fully reversible
```

The brain is **Gemma 3 (`gemma3:1b`)**, Google's open-weight model, served locally by Ollama. The harness is model-agnostic — Gemma is a component, not a landlord (more on that below).

## How it saves effort (the lazy payoff)

- I never sort a Downloads folder by hand again. The agent does the boring classification pass — including renaming `invoice_final_FINAL_v3.pdf` into something a human would choose.
- It is careful precisely because I am lazy: **dry-run by default**, an interactive confirmation before anything moves, **never overwrite** (collisions get a `-1` suffix), and an **undo log** that reverses the last run exactly. A lazy tool you can't trust is just more work.
- It skips hidden files and its own logs. Even its mistakes are auditable through the trace.

## Demo

- Repo: [REPO LINK]
- Live demo (GitHub Actions, one click, real model): the repo ships a `demo.yml` workflow that installs Ollama, pulls `gemma3:1b`, runs the agent against the sample messy folder — plan, apply, undo — and uploads the **full transcript and session trace** as artifacts. No staging, no mocked model.
- A local run transcript and instructions are also in the repo under `demo/` ([REPO LINK]).

## Why open innovation matters here

This project only makes sense with open-weight models:

- **Privacy by architecture.** Filenames are personal — tax returns, ID scans, salary letters. With a local open model, they never leave the machine. A cloud API would make the whole tool a bad idea.
- **Offline and free forever.** No API key, no per-token bill, no rate limits. It runs on a plane.
- **Swappable models.** Because Gemma is open weight and served behind a plain local API, I can swap in `qwen2.5:0.5b` or `llama3.2:1b` with one environment variable and the harness doesn't change a line. Open weights turn "the model" into a replaceable part — which is exactly what made a from-scratch harness worth building: the loop, the tools, the safety gates and the trace are mine; the brain is interchangeable.
- **Small models are enough — if the harness is honest.** A 1B model will not reliably one-shot a 40-file JSON plan. But guided one file at a time, with validation and retries, it does the job. That gap between "demo-ware" and "works on my machine" is where open tooling lets you experiment for free until it clicks.

## Prize categories

I'm entering:

- **Best Use of Gemma** — Gemma 3 (`gemma3:1b`, open weight, via Ollama) is SlothSort's default and demoed model: it makes every classification decision inside the harness's tool loop, and the full session trace of its decisions ships with the demo.

## Stack

Python 3 (standard library only), Ollama, Gemma 3. Tests: 17, using scripted fake model clients — plan parsing, collision handling, dry-run safety, harness apply-gate refusal, and apply+undo round-trips, all green without needing a model installed.

— Hitesh Chouhan
