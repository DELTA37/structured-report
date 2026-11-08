# structured-report

An agent skill that turns finished work into a **structured, interactive HTML report** — a map of
tasks you can click into, where every claim says how it is known.

![Overview: tasks laid out as a graph, with a queue of what waits on the reader](docs/overview.png)

**Work map** — the only thing on the first page, sized to the window: each task is a card with
its status, a short brief, and what waits on the reader; arrows for dependencies, dashed lines for
related work.

**Task report** (click a task) — in a fixed order:

| Section | What it holds |
|---|---|
| Problem | what is wrong, for whom |
| Task | what done means |
| Context gathered | the sources actually looked at, with links |
| What I concluded | conclusions, each citing the context it rests on, with confidence |
| What I assumed | unverified assumptions, with how to check them and the risk if wrong |
| Result | typed outcomes: added, changed, fixed, verified, measured, decided — with links |
| How the work went | a directed flowchart of the stages, each a block with what was done and what came out |
| Needs your approval | decisions only the reader can make |
| For you to do | steps only the reader can take, with copyable commands |

**Structure vs. content.** The template owns the structure — section names (always English),
order, statuses and icons — and the agent supplies only content (any language) through
`{{placeholders}}`. Facts, conclusions and assumptions are drawn with different rules (solid, double, dashed) so a
reader can tell at a glance what was checked and what was guessed.

<img src="docs/task.png" alt="Task report drawer with context, conclusions, assumptions, result and the stage flowchart" width="720">

The output is a single offline HTML file: no CDN, no fonts to download, no tracking. Inline SVG
icons, keyboard navigation, deep links (`#task=<id>`), and a print view that prints every task.

## Install

With the [skills CLI](https://skills.sh):

```bash
npx skills add DELTA37/structured-report
```

Or copy the skill folder into your agent's skills directory, e.g. for Claude Code:

```bash
git clone https://github.com/DELTA37/structured-report
cp -r structured-report/skills/structured-report ~/.claude/skills/
```

## Use

Ask your agent for a report on the work — *"write a structured report of what you did today"*,
*"отчёт по работе"*. The agent fills a JSON file and runs:

```bash
python3 skills/structured-report/scripts/build.py report.json   # → report.html
```

Try it on the bundled example:

```bash
python3 skills/structured-report/scripts/build.py skills/structured-report/examples/example.json
open skills/structured-report/examples/example.html
```

The data format is documented in [`references/schema.md`](skills/structured-report/references/schema.md).
Content can be in any language; structure labels stay English. See `examples/example.ru.json`.

Requires Python 3.8+ (standard library only) and any modern browser.

## License

MIT
