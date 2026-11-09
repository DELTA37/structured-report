---
name: structured-report
description: "Turn work into a structured, interactive HTML report and keep it in step with the session: a work map of tasks, and for every task — and every stage inside it, recursively — the problem, the goal, the context gathered (with links), conclusions, assumptions, what was not checked, the result, a workflow canvas of stages, what needs the reader's decision and what the reader must do. The reader can answer the agent's questions inside the report and send them back to continue the session; a prompts rail shows which user prompt each block appeared or changed at; full-text search. Use when the user asks for a work report, status report, session summary, handoff, \"what did you do\", \"report on the work\", \"отчёт по работе\", a tracked/living report of the session, or a flowchart of how a task was solved."
---

# Structured report

One self-contained HTML file (no network) that lets a busy reader
1. see the whole work as a map of tasks, with what is waiting on them inside each task,
2. open any task — and any stage inside it — and audit *how* it was done and *why* each claim
   is believed,
3. answer the agent's questions right there, and see which of their prompts produced what.

## Structure vs. content

- **Structure** belongs to the template (`assets/template.html`): layout, section names (Problem,
  Task, Context, Conclusions, Assumptions, Result, Not checked, Workflow, Needs approval, Your
  actions), their order, statuses, every icon and every UI label. Fixed, always English. Icons mark
  structure only, never what the content is about.
- **Content** is yours: the JSON, in the user's language. `scripts/build.py` validates it and fills
  the template's placeholders. You never write HTML and never invent sections.

## Workflow

1. **Collect the material**: messages, tool results, files, commands, links, tests, measurements,
   decisions. Report only what actually happened.
2. **Cut it into tasks** (1–12): one task = one goal with its own outcome. Connect them with
   `links`: `depends`, `blocks`, `related`.
3. **Fill every task** following the rules below and `references/schema.md`.
4. **Write the JSON** — default `reports/<YYYY-MM-DD>-<slug>.json` in the working directory.
5. **Build:** `python3 <skill>/scripts/build.py <file>.json` → `<file>.html`. Fix every `error:`;
   read every `warning:` and fix it unless it is genuinely true.
6. **Open it locally** (`open` / `xdg-open` / `start`) and give the path. Never upload it.
7. In chat: 2–4 lines — the headline result and what waits on the reader.

## Living report: track the session, take answers back

When the user wants the report kept up to date through the session (or asks for a tracked /
living report), bind the session once:

```bash
python3 <skill>/scripts/track.py start reports/<file>.json      # creates <file>.journal.json
```

From then on the `UserPromptSubmit` hook (install once: `track.py install-hook`, which also adds
the Stop hook) logs every user
prompt to the journal and reminds you of the prompt number. **After each prompt that changes the
work, update the JSON and rebuild** — `build.py` fingerprints every block (each node × section)
and stamps new or changed blocks with the current prompt. Never write stamps yourself. The report
shows a Prompts rail; picking a prompt highlights what appeared (green) or changed (blue) there.

**Questions for the reader.** Put decisions in `approvals`. Each is a question with `options` —
**exclusive** by default (one answer) or `"multi": true` (any that apply) — your `recommend` (a
list for multi), `why` and `due`. The reader always has "your own answer" as an extra option; a
question without options is answered in free text. In the report the open questions of a
**Needs approval** section form a **series**, one question at a time: an exclusive option answers
and moves on, a multi-choice or own answer is confirmed with Next, the series ends on a review of
all answers, and **Submit answers** sends them to you — there is no other way to send, and
`actions` (steps the reader takes) have no inputs. The answers go to a local answer service (`127.0.0.1:47319`, started and
kept up to date by the build) even when the report is opened as a plain file, and are stored in
the journal as the next prompt. While the report has open questions, keep a waiter running as a
**background** command:

```bash
python3 <skill>/scripts/track.py wait reports/<file>.json
```

When the reader sends, `wait` prints the answers and exits — that output comes back to you:
**treat it exactly as the user's prompt** and continue; start `wait` again if questions remain.
If no waiter is running, the Stop hook hands queued answers over before your turn ends, and the
UserPromptSubmit hook attaches them to the user's next message — answers are never lost. Answered
questions show as answered after the next build. `--static` builds a report without the answer
channel (for sharing outside this machine): questions are shown read-only, with no inputs.

**Link under the input.** `scripts/statusline.py` prints one status-line row for the session's
report — its title as a clickable link that opens the HTML in the browser, and how many questions
still wait. Use it as the status line or append its output to an existing one; it prints nothing
for sessions without a report.

Every block of the report has a **copy as Markdown** button (the whole report, a task card, a
report, a section, a single item, a step, a prompt) — point the reader to it when they want to
paste something elsewhere.

## The rules that make the report trustworthy

Separate **how you know** each thing; never blur it.

- **context** — sources you actually looked at: `id` (C1…), short `title`, a **real** `url`, and a
  `note` with the exact fact taken. Never invent URLs. Prefer repo / web URLs: `file://` links do
  not open on the reader's machine (build warns; a missing local file is an error).
- **inferences** — conclusions, each with `basis` (context ids) and `confidence`. No basis → it is
  an assumption.
- **assumptions** — taken as true without checking: `why`, how to `verify`, `risk` if wrong.
- **unchecked** — what you did **not** check or do, with `why` not. Readers rely on this more than
  on anything else; say it plainly. A finished task without `unchecked` gets a warning (`[]` means
  "checked everything" — only if true).
- **result** — what exists now, as typed items. Every `verified` item needs `how`: the command,
  test or link that proves it — the build fails without it.
- **stages** — the steps you actually took, 2–8 per level. **A stage is the same kind of node as a
  task**: `id` + `title` required, any task field allowed, its own `stages` + `flow`, to any depth.
  On the card it shows `detail` (what you did), `outcome` (what came out), `status`, `when`,
  `uses`. Clicking a stage opens its report in the same structure, so give real content to stages
  that were real work. Dead ends are stages too (`failed` / `skipped`).
- **next steps are planned stages** — anything still to do is a stage with `status: "planned"`,
  a `detail` (what will be done) and `when` (the condition or time: "after your approval",
  "Monday"). An unfinished task with no planned or in-progress stage gets a warning.
- **approvals** — decisions only the reader can make: the question, `why` it is theirs,
  `options` (exclusive, or `multi: true`), your `recommend` (one of the options; a list for multi),
  `due`. Several related questions in one node become a series — order them as the reader should
  answer them. Never ask approval for something already done.
- **actions** — things only the reader can do, with the exact `command` and `due` when relevant.
- **secrets** — the report gets forwarded. The build fails on anything that looks like a key,
  token, private key, JWT, password assignment or credentials in a URL (gitleaks is used too when
  installed). Remove it from the content; never "mask" it by hand. Secrets in logged prompts are
  masked automatically.

## Write structure, not prose

Every text field renders structure, so give it structure:

- `- item` → bullets; `1. item` → numbered (real sequences only); two or more `Key: value` lines →
  an aligned table; a JSON array of strings → bullets.
- `**bold**` the one or two things per line the reader must not miss; `==text==` highlights;
  `` `code` `` for identifiers, paths, commands.
- No paragraph longer than two sentences; no subtitles or intro lines.
- Point at code as `path:line` (`src/runtime/ops/send.ts:421`, ranges `:40-58`, several `:235,293`;
  another repo — `turnkey-extensions src/…:421`). It becomes a chip that opens those lines inside the
  report, so cite the exact lines a context item or result rests on, not just the file.

Field guidance: `brief` — 1–3 `Key: value` lines for the map card. `problem` — key/value facts.
`goal` — bullets of what done means. `result.summary` — key/value or bullets.

## Language

Content in the user's language, `meta.lang` set to its code. Structure labels stay English.

## Files

- `assets/template.html` — the structure: markup with placeholders, styles, icons, and a script
  for layout, navigation, search, the prompts rail and answering.
- `scripts/build.py` — validates the content (checks above, secrets), stamps the journal, renders
  the template. `--check` validates only; `--template` uses another template.
- `scripts/track.py` — `start`, `wait`, `hook`, `stop-hook`, `daemon`, `status`, `install-hook`
  (see its docstring).
- `scripts/statusline.py` — the report link for the Claude Code status line.
- `references/schema.md` — every field.
- `examples/` — English and Russian examples; the Russian one carries a 5-prompt journal.
