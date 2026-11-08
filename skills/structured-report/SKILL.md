---
name: structured-report
description: "Turn a piece of finished (or paused) work into a structured, interactive HTML report: an overview graph of tasks with dependencies, and per task the problem, the goal, the context gathered (with links), what was concluded, what was assumed, the result, a directed flowchart of work stages, what needs the reader's approval and what the reader must do. Use when the user asks for a work report, status report, session summary, handoff, \"what did you do\", \"report on the work\", \"отчёт по работе\", or a flowchart/diagram of how a task was solved."
---

# Structured report

Produce one self-contained HTML file (no network, no build step) that lets a busy reader
1. see the whole work as a map of tasks, with what is waiting on them inside each task, then
2. drill into any task and audit *how* the work was done and *why* each claim is believed.

## Structure vs. content

The report keeps two things apart, and so must you:

- **Structure** belongs to the template (`assets/template.html`): the page layout, section names
  (Problem, Task, Context, Conclusions, Assumptions, Result, Workflow, Needs approval, Your
  actions), their order, statuses, and every icon. It is fixed and always in English. Icons mark
  structure only — a section, a status, an approval or action — never what the content is about.
- **Content** is yours: the JSON data, written in the user's language. `scripts/build.py`
  validates it and fills the template's placeholders (`{{title}}`, `{{problem|rich}}`,
  `{{#tasks}}…{{/tasks}}`). You never write HTML and never invent new sections; if something does
  not fit a section, it does not belong in the report.

The first page is only the **work map**: every task is a card with its status, title, a short
`brief`, and the approvals/actions waiting on the reader. It fits the screen without scrolling.
Clicking a card opens that task's full report.

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

- **context** — sources you actually looked at. Each has an `id` (C1, C2…), a short `title`, a **real** `url` (web URL, repo URL with
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
- **stages** — the steps you actually took, in order, 2–8 per level. **A stage is the same kind of
  node as a task**: `id` and `title` are required, and it may carry any task field — `problem`,
  `goal`, `context`, `inferences`, `assumptions`, `result`, `approvals`, `actions` and its own
  `stages` + `flow`, to any depth. On the card it shows `detail` (what you did), `outcome` (what
  came out), `status` and `uses` (context ids from its own or any enclosing level). Clicking a
  stage opens its report in the same structure, so give a stage real content when it was real
  work (an investigation, a migration batch), and keep trivial steps to `detail` + `outcome`.
  In a stage's report `detail` stands in for Task and `outcome` for Result when those are absent;
  empty sections are hidden. Dead ends are stages too (`failed` / `skipped`). Use `flow` edges
  when work branched or ran in parallel; omit it for a straight line.
- **approvals** — decisions only the reader can make (merge/ship, spend, scope, anything
  irreversible or customer-facing). State the question, `why` it is theirs, and `options` if
  there are clear choices. Never present something you already did as needing approval.
- **actions** — things the reader must do themselves (access you don't have, a login, a
  physical step, a conversation). Include the exact `command` when there is one.

## Write structure, not prose

Unstructured text is unreadable here. Every text field is rendered with structure, so give it
structure:

- `- item` lines → bullet list; `1. item` → numbered list (only for real sequences).
- `Key: value` lines (two or more in a row) → an aligned key/value table. Use it for facts:
  `Since: release 2.14`, `Latency: **820 ms → 1.7 s**`, `Affected: **212** customers`.
- A text field may also be a JSON array of strings → bullet list.
- `**bold**` the number, name or term the reader must not miss — one or two per line, not more.
  `==text==` highlights; `` `code` `` for identifiers, paths, commands.
- No paragraphs longer than two sentences. No subtitles, captions or intro lines: a section is
  its title plus the structured content.

Field guidance: `brief` — 1–3 `Key: value` lines for the map card (the state of the task in a
glance; it must fit a 300 px card). `problem` — key/value facts (where, since when, how much, who is affected). `goal` —
bullets of what done means. `result.summary` — key/value or bullets. Write for the reader, not
about yourself: concrete numbers, real file and system names.

## Language

Write the content in the user's language and set `meta.lang` to its code (`ru`, `en`, …). Labels
of the structure stay English — they are part of the template, not the content.

## Files

- `assets/template.html` — the structure: markup with placeholders, styles, icons, and a small
  script for graph layout and navigation only.
- `scripts/build.py` — validates the content and renders the template (Mustache subset, see its
  docstring). `--check` validates only; `--template` uses another template. Standard library only.
- `references/schema.md` — every field, with types and limits.
- `examples/example.json`, `examples/example.ru.json` — complete examples (English and Russian
  content in the same English structure).
