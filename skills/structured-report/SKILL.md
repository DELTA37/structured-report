---
name: structured-report
description: "Turn a piece of finished (or paused) work into a structured, interactive HTML report: an overview graph of tasks with dependencies, and per task the problem, the goal, the context gathered (with links), what was concluded, what was assumed, the result, a directed flowchart of work stages, what needs the reader's approval and what the reader must do. Use when the user asks for a work report, status report, session summary, handoff, \"what did you do\", \"report on the work\", \"отчёт по работе\", or a flowchart/diagram of how a task was solved."
---

# Structured report

Produce one self-contained HTML file (no network, no build step) that lets a busy reader
1. see in seconds what is waiting on them, then
2. drill into any task and audit *how* the work was done and *why* each claim is believed.

You write **data**, not HTML. `assets/template.html` renders it; `scripts/build.py` validates the
data and embeds it.

## Workflow

1. **Collect the material.** Go back through the work you are reporting on: messages, tool
   results, files read and changed, commands run, links visited, tests, measurements, decisions.
   Report only what actually happened. If you did not see it, it is not context.
2. **Cut it into tasks.** One task = one goal with its own outcome (a bug investigated, a feature
   built, a migration run). 1–12 tasks; merge trivia, split work that has separate outcomes.
   Connect tasks with `links`: `depends` (B needed A's result), `blocks` (A is stopping B now),
   `related` (share context, no order).
3. **Fill every task** following the rules below and `references/schema.md`.
4. **Write the JSON** to a file — default `reports/<YYYY-MM-DD>-<slug>.json` in the current working
   directory unless the user names a place.
5. **Build:** `python3 <skill-dir>/scripts/build.py <file>.json` → writes `<file>.html` next to it.
   Fix every `error:`; read every `warning:` and fix it unless it is genuinely true (e.g. a
   planned task has no stages yet).
6. **Open it locally** (`open file.html` on macOS, `xdg-open` on Linux, `start` on Windows) and give
   the user the path. Do not upload or publish the report anywhere unless asked.
7. In chat, add a 2–4 line summary: the headline result and what is waiting on the reader.

## The rules that make the report trustworthy

The report separates **how you know** each thing. Readers rely on this; never blur it.

- **context** — sources you actually looked at. Each has a `kind` (file, url, doc, log, chat,
  data, commit, issue, code, image), a short `title`, a **real** `url` (web URL, repo URL with
  line anchor, or `file:///abs/path` for local files) and an optional `note` with the specific
  fact you took from it, quoted or exact. Never invent URLs; leave `url` out if there is none.
- **inferences** — conclusions you drew. Each lists `basis`: the context ids it rests on, and a
  `confidence` (high / medium / low). A conclusion without a basis is an assumption.
- **assumptions** — things you took as true without checking. Each says `why` you assumed it,
  how to `verify` it, and the `risk` if it is wrong. Be honest here; hidden assumptions are the
  most expensive part of any handoff.
- **result** — what exists now that did not before, as typed items (`added`, `changed`,
  `removed`, `fixed`, `verified`, `metric` with `value`, `doc`, `decision`), each with a `ref` link
  when there is something to open (PR, commit, file, dashboard). `verified` means you ran a check
  and saw it pass — say which check.
- **stages** — the steps you actually took, in order, 2–8 per task. Each has a `title` (verb
  first), `detail` (what you did), `outcome` (what you learned or produced), optional `status`
  (done / partial / failed / skipped / planned / in_progress / blocked) and `uses` (context ids).
  Dead ends are stages too (`failed` / `skipped`) — they show why the final path was chosen.
  Use `flow` edges when work branched or ran in parallel; omit `flow` for a straight line.
- **approvals** — decisions only the reader can make (merge/ship, spend, scope, anything
  irreversible or customer-facing). State the question, `why` it is theirs, and `options` if
  there are clear choices. Never present something you already did as needing approval.
- **actions** — things the reader must do themselves (access you don't have, a login, a
  physical step, a conversation). Include the exact `command` when there is one.

Write for the reader, not about yourself: short sentences, concrete numbers, names of real files
and systems. Problem = what is wrong and for whom. Task = what "done" means. Keep the overview
`summary` to 2–4 sentences ending with what is waiting on the reader.

## Language

Write the content in the user's language and set `meta.lang` (`en` and `ru` UI labels are built
in; other codes fall back to English labels — add a dictionary to `L10N` in the template to
support more).

## Files

- `assets/template.html` — the viewer (layered graph layout, drawer, print view, SVG icons).
- `scripts/build.py` — validate + embed. `--check` validates only. Standard library only.
- `references/schema.md` — every field, with types and limits.
- `examples/example.json` — a complete example; build it to see the result.
