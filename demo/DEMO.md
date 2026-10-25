# SlothSort — live demo transcript (real run, real model)

Everything below actually happened. No mocked model, no staged output.

- **Date:** 2026-10-25 (~08:19–08:21 UTC)
- **Machine:** a small cloud sandbox, 2 CPUs, no GPU, ~8 GB RAM
- **Server:** Ollama 0.40.11, `ollama serve` on `localhost:11434`
- **Model:** **`gemma3:1b`** (806 MB, Google's open-weight Gemma 3, pulled from
  the Ollama registry) — SlothSort's default model
- **Sample input:** `python demo/make_mess.py demo/messy` — 12 files
  (11 visible + 1 hidden, which must never be touched)

## 1. Dry run — the agent plans, nothing moves

```
$ python -m slothsort demo/messy   # dry run, model: gemma3:1b (default)
Agent summary: "File classification complete."

Tidy plan for demo/messy (11 files):

  FILE                                     ->  DESTINATION  (why)
  ---------------------------------------  --  -----------
  backup-2025-12-31.zip                    ->  Archives/backup-2025-12-31.zip  (Archive file)
  budget 2026 copy.xlsx                    ->  Documents/budget 2026 copy.xlsx  (Spreadsheet)
  IMG_4021.JPG                             ->  Images/IMG_4021.JPG  (Image)
  installer_v2.1.dmg                       ->  Installers/installer_v2.1.dmg  (Installer)
  invoice_final_FINAL_v3.pdf               ->  Documents/invoice_final_FINAL_v3.pdf  (PDF)
  lofi beats to sort files to.mp3          ->  Misc/lofi beats to sort files to.mp3  (Harness fallback: model did not classify this file.)
  notes from call.txt                      ->  Misc/notes from call.txt  (Text)
  random download (1).bin                  ->  Misc/random download (1).bin  (Binary File)
  Resume (2).docx                          ->  Documents/Resume (2).docx  (Document)
  Screenshot 2026-10-24 at 9.41.03 PM.png  ->  Media/Screenshot 2026-10-24 at 9.41.03 PM.png  (Image)
  todo_old.py                              ->  Misc/todo_old.py  (Script)

Session trace: demo/messy/.slothsort-trace.jsonl (every model decision + tool call)
Dry run — nothing was moved. Re-run with --apply to let the sloth work.

real    1m23.918s
```

Session trace for this run: 57 events — 14 tool calls (`list_files` ×1,
`classify_file` ×12, `finish_plan` ×1), 13 model replies, and **1 honest
harness fallback**: Gemma failed to classify the `.mp3` within the retry
budget, so the harness filed it under `Misc` itself and logged the fallback
in the trace (visible in the plan above).

## 2. Apply — human confirms, the agent moves the files

A fresh agent session (models are stateless; the plan is rebuilt). This run
Gemma classified all 11 files itself, including the `.mp3` → `Media`.

```
$ echo y | python -m slothsort demo/messy --apply   # model: gemma3:1b
Agent summary: "File classification complete."

Tidy plan for demo/messy (11 files):
  ... (same table as the dry run, except:)
  lofi beats to sort files to.mp3          ->  Media/lofi beats to sort files to.mp3  (Audio)

Session trace: demo/messy/.slothsort-trace.jsonl (every model decision + tool call)
Move 11 files in demo/messy? [y/N] Done: moved 11 files. Undo anytime with: slothsort undo demo/messy

$ find demo/messy | sort
demo/messy
demo/messy/.hidden-shame.txt          <- hidden file: untouched, as designed
demo/messy/.slothsort-trace.jsonl
demo/messy/.slothsort-undo.json
demo/messy/Archives/backup-2025-12-31.zip
demo/messy/Documents/Resume (2).docx
demo/messy/Documents/budget 2026 copy.xlsx
demo/messy/Documents/invoice_final_FINAL_v3.pdf
demo/messy/Images/IMG_4021.JPG
demo/messy/Installers/installer_v2.1.dmg
demo/messy/Media/Screenshot 2026-10-24 at 9.41.03 PM.png
demo/messy/Media/lofi beats to sort files to.mp3
demo/messy/Misc/notes from call.txt
demo/messy/Misc/random download (1).bin
demo/messy/Misc/todo_old.py
```

The apply session's full trace (59 events, including the model's own
`apply_plan` tool call after confirmation) is saved next to this file as
[`trace-apply.jsonl`](trace-apply.jsonl).

## 3. Undo — the mess comes back, exactly as it was

```
$ python -m slothsort undo demo/messy
  demo/messy/Misc/todo_old.py  ->  demo/messy/todo_old.py
  demo/messy/Media/Screenshot 2026-10-24 at 9.41.03 PM.png  ->  demo/messy/Screenshot 2026-10-24 at 9.41.03 PM.png
  demo/messy/Documents/Resume (2).docx  ->  demo/messy/Resume (2).docx
  demo/messy/Misc/random download (1).bin  ->  demo/messy/random download (1).bin
  demo/messy/Misc/notes from call.txt  ->  demo/messy/notes from call.txt
  demo/messy/Media/lofi beats to sort files to.mp3  ->  demo/messy/lofi beats to sort files to.mp3
  demo/messy/Documents/invoice_final_FINAL_v3.pdf  ->  demo/messy/invoice_final_FINAL_v3.pdf
  demo/messy/Installers/installer_v2.1.dmg  ->  demo/messy/installer_v2.1.dmg
  demo/messy/Images/IMG_4021.JPG  ->  demo/messy/IMG_4021.JPG
  demo/messy/Documents/budget 2026 copy.xlsx  ->  demo/messy/budget 2026 copy.xlsx
  demo/messy/Archives/backup-2025-12-31.zip  ->  demo/messy/backup-2025-12-31.zip
Undid 11 moves. The mess is back, exactly as it was.
```

## Honest notes (what a 1B model is really like)

- **Categories were sensible, renames were timid.** Gemma mostly kept the
  original filenames instead of cleaning them (`invoice_final_FINAL_v3.pdf`
  survived). The harness validates and bounds the model's decisions; it does
  not pretend they are better than they are.
- **Two judgement calls were imperfect**: the spreadsheet went to `Documents`
  (reason: "Spreadsheet" — it knew, it just picked the folder loosely) and
  the screenshot PNG went to `Media` instead of `Images`.
- **One fallback in run 1, none in run 2.** Small-model variance is real;
  the trace is how you see it instead of guessing.
- **Speed:** ~84 seconds to plan 11 files on 2 CPU cores. Slow and steady
  indeed. On any real laptop this is several times faster.

## Reproduce it yourself

Locally:

```bash
ollama pull gemma3:1b && ollama serve
python demo/make_mess.py
python -m slothsort demo/messy
```

Or on GitHub: this repo ships `.github/workflows/demo.yml` — trigger it from
the Actions tab and it installs Ollama, pulls `gemma3:1b`, runs plan + apply
+ undo and the test suite, and uploads the transcript and trace as artifacts.
