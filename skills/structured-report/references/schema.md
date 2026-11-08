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
    "lang": "en | ru (default en) — UI labels",
    "author": "who did the work",
    "audience": "who it is for",
    "period": {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"},
    "generated": "YYYY-MM-DD HH:MM (default: now)"
  },
  "summary": "2–4 sentences: headline result, then what waits on the reader",

  "tasks": [{
    "id": "string, unique, used in links and URLs (#task=<id>)",
    "title": "string, required",
    "status": "done | in_progress | blocked | needs_review | planned | failed | partial",
    "ref": {"label": "ISSUE-1", "url": "https://…"},          // optional tracker / PR link
    "tags": ["short", "labels"],

    "problem": "required — what is wrong, for whom, how it shows",
    "goal": "required — what done means",

    "context": [{
      "id": "C1 — unique within the task",
      "kind": "file | url | doc | log | chat | data | commit | issue | code | image",
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

    "stages": [{
      "id": "unique within the task",
      "title": "required, verb first",
      "detail": "what was done",
      "outcome": "what it produced or showed",
      "status": "done (default) | partial | failed | skipped | planned | in_progress | blocked",
      "uses": ["C2"]                                           // context ids
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

- Overview: header, summary, counters, the "Waiting on you" queue (all approvals and actions
  across tasks), and the task graph laid out in layers left → right by `depends`/`blocks`.
- Click a task (or a queue item) → drawer with the full report; `#task=<id>` deep-links to it;
  Esc closes; Alt+←/→ moves between tasks.
- Print / Save as PDF prints every task in full, one per page, with stages as a numbered list.
