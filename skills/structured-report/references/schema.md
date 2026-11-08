# Report data schema

One JSON object. Text fields (`summary`, `problem`, `goal`, notes, `detail`, `why`, …) are
structured text — a string or an array of strings (array → bullet list). Inside a string:

| Write | Renders as |
|---|---|
| `- item` lines | bullet list |
| `1. item` lines | numbered list |
| two or more `Key: value` lines | aligned key/value table (one alone → **Key:** value) |
| blank line | new paragraph |
| `**bold**`, `==highlight==`, `` `code` ``, `[label](https://…)` | inline emphasis / link |

Everything is HTML-escaped.

```jsonc
{
  "meta": {
    "title": "string, required — what the report covers",
    "lang": "language code of the content (html lang attribute); labels stay English"
  },

  "tasks": [{
    "id": "string, unique, used in links and URLs (#task=<id>)",
    "title": "string, required",
    "status": "done | in_progress | blocked | needs_review | planned | failed | partial",
    "ref": {"label": "ISSUE-1", "url": "https://…"},          // optional tracker / PR link
    "brief": "1–3 `Key: value` lines shown on the map card",

    "problem": "required — what is wrong, for whom, how it shows",
    "goal": "required — what done means",

    "context": [{
      "id": "C1 — unique within the task",
      "title": "required",
      "url": "https://… | file:///abs/path | relative/path — only if real",
      "note": "the specific fact taken from this source"
    }],

    "inferences": [{
      "text": "required — the conclusion",
      "basis": ["C1", "C3"],                                   // context ids
      "confidence": "high | medium | low"
    }],

    "assumptions": [{
      "text": "required",
      "why": "why it was assumed instead of checked",
      "verify": "how to check it",
      "risk": "high | medium | low — cost if wrong"
    }],

    "result": {
      "summary": "one or two sentences",
      "items": [{
        "kind": "added | changed | removed | fixed | verified | metric | doc | decision",
        "text": "what",
        "value": "for metric: the number with unit, shown large",
        "ref": {"label": "PR #12", "url": "https://…"}
      }]
    },

    "stages": [{                                               // a stage is a node: same fields as a task
      "id": "unique among its siblings, no '/'",
      "title": "required, verb first",
      "status": "done (default) | partial | failed | skipped | planned | in_progress | blocked | needs_review",
      "detail": "what was done — shown on the card; Task in its report when goal is absent",
      "outcome": "what it produced — shown on the card; Result in its report when result is absent",
      "uses": ["C2"],                                          // context ids from this level or any above
      // optional, exactly as for a task: problem, goal, context, inferences, assumptions,
      // result, approvals, actions, and nested "stages" + "flow" — to any depth
    }],
    "flow": [{"from": "stage id", "to": "stage id", "label": "optional"}],
    // flow omitted → stages are chained in order

    "approvals": [{"text": "required", "why": "…", "options": ["A", "B"]}],
    "actions":   [{"text": "required", "why": "…", "command": "exact command"}]
  }],

  "links": [{
    "from": "task id",
    "to": "task id",
    "kind": "depends | related | blocks",   // depends: `from` needs `to`; blocks: `from` blocks `to`
    "label": "optional, short"
  }]
}
```

## Validation (`build.py`)

Errors (build fails): missing required fields, duplicate ids, unknown statuses or levels,
inference `basis` / stage `uses` / `flow` / `links` pointing at ids that do not exist.

Warnings: task without context or stages, inference without basis, assumption without
`verify`, link-like context without `url`, unknown context or result kind, empty result.

## Viewer behaviour

- Page 1 is the work map only; the page never scrolls — the map is a canvas. It opens showing
  everything when that stays readable (≥ 72 %), otherwise at 72 % from the first tasks. Move by
  dragging, two-finger scroll / wheel or arrow keys; zoom with pinch, Ctrl/⌘+wheel, `+` `−`, or the
  buttons; `0`, the fit button or a double-click on empty space shows everything. A minimap
  (approvals/actions in yellow) appears when the graph does not fit; click or drag it to move.
  Tabbing to a card brings it into view. Layout: left → right by `depends` / `blocks`, dashed
  for `related`. Each card: status icon, title,
  `brief` (falls back to `result.summary`), and the task's approvals and actions.
- Every task and every stage has its own report in the same structure (empty sections hidden).
  Its Workflow is a canvas of its direct stages (drag, pinch / Ctrl+wheel; plain wheel scrolls the
  report; expand button = full page, Esc to leave). Click a stage to open its report — recursively.
  Stages that contain stages look like a stack; stages with something waiting on the reader carry
  a yellow edge. A trail (Work map › task › 3 › 3.2) leads back; ‹ › move between siblings,
  Alt+↑ goes one level up. `#task=<id>/<stage id>/…` deep-links to any level.
- Approvals and actions from nested stages also appear on the task's map card, prefixed with the
  stage number.
- Click a card → drawer with the task report in the template's fixed section order; Esc closes.
- Print / Save as PDF prints every task report, one per page, with stages as a numbered list.

## Template placeholders

See the docstring of `scripts/build.py`. The template receives the JSON plus derived fields:
`tasks` (top-level nodes, for the map) and `reports` (every node, depth first). Each report has
`key` (`task/stage/…`), `num` (`3.2`, none for tasks), `trail`, `prev` / `next` (siblings),
`status_label`, `goal_text`, `result_summary`, `result_items`, `has_result`, `ctx` (own context plus
inherited items it references, flagged `inherited`), `children` (stage cards: `key`, `num`, `deep`,
`waiting`), `edges`, and `waiting_all` (its own and nested approvals/actions with `where`).
Top-level `edges` and `has_blocks` describe the map.
