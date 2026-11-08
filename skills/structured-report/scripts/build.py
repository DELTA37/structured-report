#!/usr/bin/env python3
"""Build a structured-report HTML from a JSON data file.

    python3 build.py report.json                 # -> report.html next to the JSON
    python3 build.py report.json -o out.html
    python3 build.py report.json --check         # validate only
    python3 build.py report.json --template my-template.html

Structure lives in the template (../assets/template.html): fixed English section names,
icons and layout, with placeholders. Content lives in the JSON, in any language.
This script validates the content and fills the placeholders. Standard library only.

Placeholder syntax (a small Mustache subset):
    {{name}}            escaped value; dotted paths allowed: {{meta.title}}
    {{name|filter}}     filters: rich (structured text -> HTML), md (inline only),
                        json (for data-* attributes), url (safe link target)
    {{#name}}…{{/name}} list -> repeat for each item; object/true -> render once
    {{^name}}…{{/name}} render when missing / empty / false
    {{#name?}}…{{/name?}} render once if non-empty, without entering the value
    {{.}}               current item;   {{@n}} 1-based index inside a list
    {{! comment }}
"""
import argparse
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "assets", "template.html")

TASK_STATUS = {"done", "in_progress", "blocked", "needs_review", "planned", "failed", "partial"}
STAGE_STATUS = {"done", "failed", "skipped", "partial", "in_progress", "planned", "blocked"}
RESULT_KINDS = {"added", "changed", "removed", "fixed", "verified", "metric", "doc", "decision"}
LINK_KINDS = {"depends", "related", "blocks"}
LEVELS = {"high", "medium", "low"}
STATUS_LABEL = {"done": "Done", "in_progress": "In progress", "blocked": "Blocked", "needs_review": "Needs review",
                "planned": "Planned", "failed": "Failed", "skipped": "Skipped", "partial": "Partly done"}


# ── structured text ─────────────────────────────────────────────────────────

def _safe_url(u):
    u = (u or "").strip()
    return u if re.match(r"^(https?:|mailto:|file:|\.{0,2}/|#)", u, re.I) else None


def md(s):
    """Inline formatting only: `code`, **bold**, ==mark==, [label](url)."""
    h = html.escape(str(s if s is not None else ""), quote=True)
    h = re.sub(r"`([^`]+)`", r"<code>\1</code>", h)
    h = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", h)
    h = re.sub(r"==([^=]+)==", r"<mark>\1</mark>", h)

    def link(m):
        url = _safe_url(html.unescape(m.group(2)))
        return f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{m.group(1)}</a>' if url else m.group(1)
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, h)


def rich(v):
    """Structured text -> HTML: '- ' bullets, '1. ' numbers, 'Key: value' rows, blank-line paragraphs.
    A list renders as bullets."""
    if v is None or v == "":
        return ""
    if isinstance(v, list):
        return "<ul>" + "".join(f"<li>{md(x)}</li>" for x in v) + "</ul>"
    out, buf, mode = [], [], None

    def flush():
        nonlocal buf, mode
        if not buf:
            return
        if mode == "ul":
            out.append("<ul>" + "".join(f"<li>{md(x)}</li>" for x in buf) + "</ul>")
        elif mode == "ol":
            out.append("<ol>" + "".join(f"<li>{md(x)}</li>" for x in buf) + "</ol>")
        elif mode == "kv":
            if len(buf) > 1:
                out.append('<dl class="kv">' + "".join(f"<dt>{md(k)}</dt><dd>{md(x)}</dd>" for k, x in buf) + "</dl>")
            else:
                out.append(f"<p><strong>{md(buf[0][0])}:</strong> {md(buf[0][1])}</p>")
        else:
            out.append("<p>" + "<br>".join(md(x) for x in buf) + "</p>")
        buf, mode = [], None

    for raw in str(v).split("\n"):
        line = raw.strip()
        if not line:
            flush()
            continue
        if (m := re.match(r"^[-•*]\s+(.*)$", line)):
            kind, item = "ul", m.group(1)
        elif (m := re.match(r"^\d+[.)]\s+(.*)$", line)):
            kind, item = "ol", m.group(1)
        elif (m := re.match(r"^([^:`*\[]{2,28}):\s+(.+)$", line)):
            kind, item = "kv", (m.group(1), m.group(2))
        else:
            kind, item = "p", line
        if mode and mode != kind:
            flush()
        mode = kind
        buf.append(item)
    flush()
    return "".join(out)


# ── template engine (Mustache subset) ───────────────────────────────────────

TAG = re.compile(r"\{\{\s*([#^/!])?\s*([^}|]*?)\s*(?:\|\s*(\w+))?\s*\}\}")


def _parse(tpl):
    root, stack, pos = [], [], 0
    cur = root
    for m in TAG.finditer(tpl):
        if m.start() > pos:
            cur.append(("text", tpl[pos:m.start()]))
        pos = m.end()
        sigil, name, flt = m.group(1), m.group(2).strip(), m.group(3)
        if sigil == "!":
            continue
        if sigil in ("#", "^"):
            node = ("sec", name, sigil == "^", [])
            cur.append(node)
            stack.append((cur, name))
            cur = node[3]
        elif sigil == "/":
            if not stack or stack[-1][1] != name:
                raise SystemExit(f"template: unexpected {{{{/{name}}}}}")
            cur, _ = stack.pop()
        else:
            cur.append(("var", name, flt))
    if stack:
        raise SystemExit(f"template: unclosed {{{{#{stack[-1][1]}}}}}")
    if pos < len(tpl):
        cur.append(("text", tpl[pos:]))
    return root


_MISSING = object()


def _lookup(stack, name):
    if name == ".":
        return stack[-1].get(".", stack[-1]) if isinstance(stack[-1], dict) else stack[-1]
    head, *rest = name.split(".")
    for frame in reversed(stack):
        if isinstance(frame, dict) and head in frame:
            v = frame[head]
            for k in rest:
                if isinstance(v, dict) and k in v:
                    v = v[k]
                elif isinstance(v, list) and k.isdigit() and int(k) < len(v):
                    v = v[int(k)]
                else:
                    return None
            return v
    return None


FILTERS = {
    None: lambda v: html.escape(str(v), quote=True),
    "rich": rich,
    "md": md,
    "json": lambda v: html.escape(json.dumps(v, ensure_ascii=False), quote=True),
    "url": lambda v: html.escape(_safe_url(v) or "", quote=True),
}


def _render(nodes, stack):
    out = []
    for n in nodes:
        if n[0] == "text":
            out.append(n[1])
        elif n[0] == "var":
            v = _lookup(stack, n[1])
            if v is None or v == "":
                continue
            if n[2] not in FILTERS:
                raise SystemExit(f"template: unknown filter |{n[2]}")
            out.append(FILTERS[n[2]](v))
        else:
            _, name, inverted, children = n
            probe = name.endswith("?")
            v = _lookup(stack, name.rstrip("?"))
            truthy = bool(v) and v is not False
            if inverted:
                if not truthy:
                    out.append(_render(children, stack))
            elif truthy:
                if probe:
                    out.append(_render(children, stack))
                elif isinstance(v, list):
                    for i, item in enumerate(v):
                        frame = dict(item) if isinstance(item, dict) else {".": item}
                        frame["@n"] = i + 1
                        out.append(_render(children, stack + [frame]))
                elif isinstance(v, dict):
                    out.append(_render(children, stack + [v]))
                else:
                    out.append(_render(children, stack))
    return "".join(out)


def render(tpl, data):
    return _render(_parse(tpl), [data])


# ── view model: derive what the template needs, without changing the content ──

def view(d):
    v = json.loads(json.dumps(d))
    v.setdefault("meta", {})
    v["meta"].setdefault("lang", "en")
    tasks = v["tasks"]
    # Every optional key exists explicitly, so a missing field never resolves to a parent's value.
    OPT = {
        "context": ("url", "note"), "inferences": ("basis", "confidence"),
        "assumptions": ("why", "verify", "risk"), "stages": ("detail", "outcome", "uses"),
        "approvals": ("why", "options"), "actions": ("why", "command"),
    }
    for t in tasks:
        for k in ("ref", "brief", "flow"):
            t.setdefault(k, None)
        for coll, keys in OPT.items():
            t[coll] = t.get(coll) or []
            for it in t[coll]:
                for k in keys:
                    it.setdefault(k, None)
        t.setdefault("result", {})
        t["result"] = t["result"] or {}
        t["result"].setdefault("summary", None)
        t["result"]["items"] = t["result"].get("items") or []
        for it in t["result"]["items"]:
            for k in ("kind", "value", "ref"):
                it.setdefault(k, None)
    for t in tasks:
        t.setdefault("status", "planned")
        t["status_label"] = STATUS_LABEL.get(t["status"], t["status"])
        t["brief"] = t.get("brief") or (t.get("result") or {}).get("summary") or ""
        t["waiting"] = bool(t.get("approvals") or t.get("actions"))
        for s in t.get("stages") or []:
            s.setdefault("status", "done")
            s["status_label"] = STATUS_LABEL.get(s["status"], s["status"])
        st = t.get("stages") or []
        t["flow_edges"] = t.get("flow") or [{"from": st[i]["id"], "to": st[i + 1]["id"]} for i in range(len(st) - 1)]
        for i in t.get("inferences") or []:
            i["confidence_dots"] = {"high": 3, "medium": 2, "low": 1}.get(i.get("confidence"), 0)
    # "A depends on B" is drawn B -> A (prerequisite first)
    v["edges"] = [({"from": l["to"], "to": l["from"], "kind": "depends", "label": l.get("label")}
                   if l.get("kind") == "depends" else
                   {"from": l["from"], "to": l["to"], "kind": l.get("kind", "related"), "label": l.get("label")})
                  for l in v.get("links") or []]
    v["has_blocks"] = any(l.get("kind") == "blocks" for l in v.get("links") or [])
    return v


# ── validation ──────────────────────────────────────────────────────────────

def validate(d):
    errors, warnings = [], []
    err, warn = errors.append, warnings.append
    if not isinstance(d, dict):
        return ["top level must be an object"], []
    if not (d.get("meta") or {}).get("title"):
        err("meta.title is required")
    tasks = d.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        err("tasks must be a non-empty list")
        return errors, warnings
    ids = set()
    for n, t in enumerate(tasks):
        tid = t.get("id")
        if not tid:
            err(f"tasks[{n}].id is required")
        elif tid in ids:
            err(f"tasks[{n}].id {tid!r} is duplicated")
        ids.add(tid)
        where = f"task {tid or n}"
        for k in ("title", "problem", "goal"):
            if not t.get(k):
                err(f"{where}: {k} is required")
        if not t.get("brief"):
            warn(f"{where}: no brief — the map card falls back to result.summary")
        if t.get("status") and t["status"] not in TASK_STATUS:
            err(f"{where}: status {t['status']!r} not in {sorted(TASK_STATUS)}")
        ctx_ids = set()
        for c in t.get("context") or []:
            if not c.get("id") or not c.get("title"):
                err(f"{where}: every context item needs id and title")
            if c.get("id") in ctx_ids:
                err(f"{where}: context id {c.get('id')!r} duplicated")
            ctx_ids.add(c.get("id"))
        if not ctx_ids:
            warn(f"{where}: no context gathered")
        for i in t.get("inferences") or []:
            if not i.get("text"):
                err(f"{where}: inference without text")
            for b in i.get("basis") or []:
                if b not in ctx_ids:
                    err(f"{where}: inference basis {b!r} is not a context id")
            if not i.get("basis"):
                warn(f"{where}: inference {str(i.get('text', ''))[:40]!r} has no basis — is it an assumption?")
            if i.get("confidence") and i["confidence"] not in LEVELS:
                err(f"{where}: confidence must be one of {sorted(LEVELS)}")
        for a in t.get("assumptions") or []:
            if not a.get("text"):
                err(f"{where}: assumption without text")
            if not a.get("verify"):
                warn(f"{where}: assumption {str(a.get('text', ''))[:40]!r} has no 'verify'")
            if a.get("risk") and a["risk"] not in LEVELS:
                err(f"{where}: risk must be one of {sorted(LEVELS)}")
        res = t.get("result") or {}
        if not res.get("summary") and not res.get("items"):
            warn(f"{where}: empty result")
        for r in res.get("items") or []:
            if r.get("kind") and r["kind"] not in RESULT_KINDS:
                err(f"{where}: result kind {r['kind']!r} not in {sorted(RESULT_KINDS)}")
        st_ids = set()
        for s in t.get("stages") or []:
            if not s.get("id") or not s.get("title"):
                err(f"{where}: every stage needs id and title")
            if s.get("id") in st_ids:
                err(f"{where}: stage id {s.get('id')!r} duplicated")
            st_ids.add(s.get("id"))
            if s.get("status") and s["status"] not in STAGE_STATUS:
                err(f"{where}: stage status {s['status']!r} not in {sorted(STAGE_STATUS)}")
            for u in s.get("uses") or []:
                if u not in ctx_ids:
                    err(f"{where}: stage {s.get('id')!r} uses unknown context {u!r}")
        for f in t.get("flow") or []:
            if f.get("from") not in st_ids or f.get("to") not in st_ids:
                err(f"{where}: flow edge {f} references unknown stage")
        if not st_ids:
            warn(f"{where}: no stages — the workflow chart will be empty")
        for k in ("approvals", "actions"):
            for a in t.get(k) or []:
                if not a.get("text"):
                    err(f"{where}: {k[:-1]} without text")
    for l in d.get("links") or []:
        if l.get("from") not in ids or l.get("to") not in ids:
            err(f"link {l} references unknown task")
        if l.get("kind", "related") not in LINK_KINDS:
            err(f"link kind {l.get('kind')!r} not in {sorted(LINK_KINDS)}")
    return errors, warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", help="report JSON")
    ap.add_argument("-o", "--out", help="output HTML (default: <data>.html)")
    ap.add_argument("--template", default=TEMPLATE, help="template HTML (default: bundled)")
    ap.add_argument("--check", action="store_true", help="validate only")
    a = ap.parse_args()
    with open(a.data, encoding="utf-8") as f:
        data = json.load(f)
    errors, warnings = validate(data)
    for w in warnings:
        print("warning:", w, file=sys.stderr)
    for e in errors:
        print("error:", e, file=sys.stderr)
    if errors:
        sys.exit(1)
    if a.check:
        print(f"ok: {len(data['tasks'])} tasks")
        return
    with open(a.template, encoding="utf-8") as f:
        out_html = render(f.read(), view(data))
    out = a.out or os.path.splitext(a.data)[0] + ".html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(out_html)
    print(os.path.abspath(out))


if __name__ == "__main__":
    main()
