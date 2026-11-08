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
import datetime
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse

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
    "script": lambda v: json.dumps(v, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--"),
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


# ── secrets: a report is a file people forward — never let a credential into it ──

SECRET_RULES = [
    ("AWS access key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("GitHub token", r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})"),
    ("Slack token", r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    ("OpenAI / Anthropic key", r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"),
    ("Google API key", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ("Stripe key", r"\b(?:sk|rk)_live_[0-9A-Za-z]{20,}"),
    ("Private key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("JWT", r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ("Credentials in URL", r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]{3,}@"),
    ("Password / token assignment", r"(?i)\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)\b\s*[:=]\s*['\"]?(?!<|\$\{|\*{3}|x{4})[^\s'\"]{8,}"),
]
_SECRET_RX = [(n, re.compile(r)) for n, r in SECRET_RULES]


def _strings(obj, path="$"):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _strings(v, f"{path}[{i}]")


def _redact(m):
    return m[:4] + "…" + ("*" * 4)


def scan_secrets(obj):
    """[(json path, rule, redacted match)] — regex rules, plus gitleaks when it is installed."""
    found = []
    strings = list(_strings(obj))
    for path, text in strings:
        for name, rx in _SECRET_RX:
            for m in rx.finditer(text):
                found.append((path, name, _redact(m.group(0))))
    gl = shutil.which("gitleaks")
    if gl and strings:
        blob = "\n".join(t for _, t in strings)
        try:
            r = subprocess.run([gl, "stdin", "--no-banner", "--report-format", "json", "--report-path", "/dev/stdout", "--log-level", "error"],
                               input=blob, capture_output=True, text=True, timeout=30)
            for f in json.loads(r.stdout or "[]"):
                secret = f.get("Secret") or f.get("Match") or ""
                where = next((p for p, t in strings if secret and secret in t), "$")
                if not any(where == p and _redact(secret)[:4] == x[:4] for p, _, x in found):
                    found.append((where, f"gitleaks: {f.get('RuleID')}", _redact(secret)))
        except Exception:
            pass
    return found


def redact_text(text):
    for _, rx in _SECRET_RX:
        text = rx.sub(lambda m: _redact(m.group(0)), text)
    return text


# ── journal: which user prompt each block appeared / changed at ──
#
# <report>.journal.json sits next to the report JSON and is written by scripts/track.py (prompts,
# answers) and by this build (block fingerprints). Content stays clean: no stamps in the report.

SECTIONS = ("card", "problem", "goal", "context", "inferences", "assumptions", "result",
            "unchecked", "workflow", "approvals", "actions")


def journal_path(data_path):
    return os.path.splitext(data_path)[0] + ".journal.json"


def load_journal(path):
    try:
        with open(path, encoding="utf-8") as f:
            j = json.load(f)
    except (OSError, ValueError):
        return None
    j.setdefault("prompts", []); j.setdefault("blocks", {}); j.setdefault("answers", {})
    return j


def _section_payload(n, sec):
    g = n.get
    return {
        "card": [g("title"), g("status"), g("brief"), g("detail"), g("outcome"), g("ref"), g("when")],
        "problem": g("problem"), "goal": [g("goal"), g("detail")], "context": g("context"),
        "inferences": g("inferences"), "assumptions": g("assumptions"),
        "result": [g("result"), g("outcome")], "unchecked": g("unchecked"),
        "workflow": [[(s.get("id"), s.get("title"), s.get("status")) for s in g("stages") or []], g("flow")],
        "approvals": g("approvals"), "actions": g("actions"),
    }[sec]


def stamp_blocks(data, journal):
    """Update journal['blocks'] with fingerprints; new or changed blocks get the current prompt."""
    current = journal["prompts"][-1]["id"] if journal["prompts"] else None
    seen = {}

    def walk(n, key):
        for sec in SECTIONS:
            payload = _section_payload(n, sec)
            if payload in (None, [], [None, None], [[], None]) or (isinstance(payload, list) and not any(payload)):
                continue
            h = hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
            seen[f"{key}#{sec}"] = h
        for s in n.get("stages") or []:
            walk(s, f"{key}/{s['id']}")
    for t in data["tasks"]:
        walk(t, t["id"])
    blocks = journal["blocks"]
    for k, h in seen.items():
        b = blocks.get(k)
        if b is None:
            blocks[k] = {"hash": h, "since": current, "changed": []}
        elif b["hash"] != h:
            b["hash"] = h
            if current and current != b.get("since") and current not in b["changed"]:
                b["changed"].append(current)
    for k in list(blocks):
        if k not in seen:
            del blocks[k]
    return journal


# ── search index: plain text of every block, labelled with its structural section ──

def _plain(v):
    if v is None:
        return ""
    if isinstance(v, list):
        return " · ".join(t for t in (_plain(x) for x in v) if t)
    if isinstance(v, dict):
        return " ".join(_plain(x) for x in v.values() if isinstance(x, (str, list)))
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", str(v))
    return re.sub(r"[`*=]{1,2}", "", t).replace("\n", " · ").strip()


def search_index(reports):
    out = []
    for r in reports:
        trail = " › ".join(f"{x['num'] + ' ' if x.get('num') else ''}{x['title']}" for x in r["trail"] if not x.get("map"))
        base = {"k": r["key"], "n": r["num"], "t": r["title"], "p": trail}
        def add(sec, label, text):
            text = _plain(text)
            if text:
                out.append(dict(base, s=sec, l=label, x=text))
        add("card", "Title", r["title"])
        add("card", "Brief", r.get("brief"))
        add("problem", "Problem", r.get("problem"))
        add("goal", "Task", r.get("goal_text"))
        for c in r["ctx"]:
            add("context", f"Context {c['id']}", [c.get("title"), c.get("note")])
        for i in r["inferences"]:
            add("inferences", "Conclusion", i.get("text"))
        for a in r["assumptions"]:
            add("assumptions", "Assumption", [a.get("text"), a.get("verify")])
        add("result", "Result", [r.get("result_summary")] + [x.get("text") for x in r["result_items"]])
        for u in r["unchecked"]:
            add("unchecked", "Not checked", [u.get("text"), u.get("why")])
        for a in r["approvals"]:
            add("approvals", "Needs approval", [a.get("text")] + list(a.get("options") or []))
        for a in r["actions"]:
            add("actions", "Your action", [a.get("text"), a.get("command")])
    return out


# ── view model: derive what the template needs, without changing the content ──
#
# Tasks and stages are the same kind of node. A task is a top-level node (shown on the map);
# its `stages` are nodes too, with the same fields, to any depth. Every node gets its own report.

STATUSES = TASK_STATUS | STAGE_STATUS | {"skipped"}
NODE_TEXT = ("ref", "brief", "problem", "goal", "detail", "outcome", "flow")


def _report(n, key, num, trail, ctx_up, task_title, reports, waiting_up):
    """Flatten one node (and its subtree) into `reports`; return the stage-card view of it."""
    n = dict(n)
    for k in NODE_TEXT:
        n.setdefault(k, None)
    n["status"] = n.get("status") or ("planned" if num is None else "done")
    n["status_label"] = STATUS_LABEL.get(n["status"], n["status"])
    n["key"], n["num"], n["trail"] = key, num, trail
    n["is_task"] = num is None

    own = [dict(c, inherited=False, url=c.get("url"), note=c.get("note")) for c in n.get("context") or []]
    index = {**ctx_up, **{c["id"]: c for c in own}}
    stages = n.get("stages") or []
    wanted = set(n.get("uses") or [])
    for i in n.get("inferences") or []:
        wanted.update(i.get("basis") or [])
    for s in stages:
        wanted.update(s.get("uses") or [])
    own_ids = {c["id"] for c in own}
    n["ctx"] = own + [dict(ctx_up[i], inherited=True) for i in sorted(wanted - own_ids) if i in ctx_up]

    n["inferences"] = [dict({"basis": None, "confidence": None}, **i) for i in n.get("inferences") or []]
    for i in n["inferences"]:
        i["confidence_dots"] = {"high": 3, "medium": 2, "low": 1}.get(i.get("confidence"), 0)
    n["assumptions"] = [dict({"why": None, "verify": None, "risk": None}, **a) for a in n.get("assumptions") or []]
    n["approvals"] = [dict({"why": None, "options": None, "recommend": None, "due": None}, **a) for a in n.get("approvals") or []]
    n["actions"] = [dict({"why": None, "command": None, "due": None}, **a) for a in n.get("actions") or []]
    answers = (VIEW_CTX.get("journal") or {}).get("answers", {})
    prompt_n = {p["id"]: p["n"] for p in (VIEW_CTX.get("journal") or {}).get("prompts", [])}
    for i, a in enumerate(n["approvals"]):
        a["akey"] = f"{key}#a{i}"
        ans = answers.get(a["akey"])
        a["answered"] = dict(ans, n=prompt_n.get(ans.get("prompt"))) if ans else None
        a["opts"] = [{"text": o, "rec": o == a["recommend"]} for o in a.get("options") or []] or None
    for i, a in enumerate(n["actions"]):
        a["akey"] = f"{key}#d{i}"
        ans = answers.get(a["akey"])
        a["answered"] = dict(ans, n=prompt_n.get(ans.get("prompt"))) if ans else None
    n["unchecked"] = [dict({"why": None}, **u) for u in n.get("unchecked") or []]
    n.setdefault("when", None)
    res = n.get("result") or {}
    n["result_summary"] = res.get("summary") or n["outcome"]
    n["result_items"] = [dict({"kind": None, "value": None, "ref": None, "how": None}, **r) for r in res.get("items") or []]
    n["goal_text"] = n["goal"] or n["detail"]
    n["has_result"] = bool(n["result_summary"] or n["result_items"])

    # what waits on the reader here and anywhere below
    slot = len(reports)
    reports.append(None)          # reserve: reports are listed depth-first, parent before children
    here = [{"approve": True, "text": a["text"], "where": num, "answered": bool(a["answered"])} for a in n["approvals"]] + \
           [{"approve": False, "text": a["text"], "where": num, "answered": bool(a["answered"])} for a in n["actions"]]
    below = []
    me = {"key": key, "num": num, "title": n["title"], "map": False}
    cards = []
    for i, s in enumerate(stages):
        snum = f"{num}.{i + 1}" if num else str(i + 1)
        card = _report(s, f"{key}/{s['id']}", snum, trail + [me], index, task_title, reports, below)
        cards.append(card)
    keys = [c["key"] for c in cards]
    for i, c in enumerate(cards):
        reports_by_key[c["key"]]["prev"] = keys[i - 1] if i else None
        reports_by_key[c["key"]]["next"] = keys[i + 1] if i + 1 < len(keys) else None
    n["children"] = cards
    n["edges"] = n["flow"] or [{"from": stages[i]["id"], "to": stages[i + 1]["id"]} for i in range(len(stages) - 1)]
    n["waiting_all"] = here + below
    n["waiting"] = any(not w["answered"] for w in n["waiting_all"])
    n.setdefault("prev", None)
    n.setdefault("next", None)
    waiting_up.extend(n["waiting_all"])
    reports[slot] = n
    reports_by_key[key] = n
    return {"id": n["id"], "key": key, "num": num, "title": n["title"], "status": n["status"],
            "status_label": n["status_label"], "detail": n["detail"], "outcome": n["outcome"],
            "uses": n.get("uses") or None, "deep": bool(stages), "waiting": n["waiting"], "when": n["when"]}


reports_by_key = {}
VIEW_CTX = {}


def view(d, journal=None):
    v = json.loads(json.dumps(d))
    v.setdefault("meta", {})
    v["meta"].setdefault("lang", "en")
    reports_by_key.clear()
    VIEW_CTX["journal"] = journal
    reports, tasks = [], []
    root = {"key": "", "num": None, "title": None, "map": True}
    for t in v["tasks"]:
        sink = []
        _report(t, t["id"], None, [root], {}, t["title"], reports, sink)
        tasks.append(reports_by_key[t["id"]])
    ids = [t["key"] for t in tasks]
    for i, t in enumerate(tasks):
        t["prev"] = ids[i - 1] if i else None
        t["next"] = ids[i + 1] if i + 1 < len(ids) else None
    v["tasks"] = tasks
    v["reports"] = reports
    # "A depends on B" is drawn B -> A (prerequisite first)
    v["edges"] = [({"from": l["to"], "to": l["from"], "kind": "depends", "label": l.get("label")}
                   if l.get("kind") == "depends" else
                   {"from": l["from"], "to": l["to"], "kind": l.get("kind", "related"), "label": l.get("label")})
                  for l in v.get("links") or []]
    v["has_blocks"] = any(l.get("kind") == "blocks" for l in v.get("links") or [])
    v["index"] = search_index(reports)
    j = journal or {}
    v["prompts"] = [dict(p, text=redact_text(p.get("text", "")), answer=p.get("kind") == "answer") for p in j.get("prompts", [])]
    v["track"] = {"prompts": [{"id": p["id"], "n": p["n"]} for p in j.get("prompts", [])], "blocks": {k: {"since": b.get("since"), "changed": b.get("changed", [])} for k, b in j.get("blocks", {}).items()}}
    return v


# ── validation ──────────────────────────────────────────────────────────────

def _has_next(n):
    return any(s.get("status") in ("planned", "in_progress") or _has_next(s) for s in n.get("stages") or [])


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

    def node(n, where, ctx_up, top):
        if not n.get("id") or not n.get("title"):
            err(f"{where}: id and title are required")
        if "/" in str(n.get("id", "")):
            err(f"{where}: id must not contain '/'")
        if top:
            for k in ("problem", "goal"):
                if not n.get(k):
                    err(f"{where}: {k} is required for a task")
            if not n.get("brief"):
                warn(f"{where}: no brief — the map card falls back to result.summary")
        if n.get("status") and n["status"] not in STATUSES:
            err(f"{where}: status {n['status']!r} not in {sorted(STATUSES)}")
        own = set()
        for c in n.get("context") or []:
            if not c.get("id") or not c.get("title"):
                err(f"{where}: every context item needs id and title")
            if c.get("id") in own:
                err(f"{where}: context id {c.get('id')!r} duplicated")
            own.add(c.get("id"))
        known = ctx_up | own
        if top and not own:
            warn(f"{where}: no context gathered")
        for u in n.get("uses") or []:
            if u not in known:
                err(f"{where}: uses unknown context {u!r}")
        for i in n.get("inferences") or []:
            if not i.get("text"):
                err(f"{where}: inference without text")
            for b in i.get("basis") or []:
                if b not in known:
                    err(f"{where}: inference basis {b!r} is not a context id here or above")
            if not i.get("basis"):
                warn(f"{where}: inference {str(i.get('text', ''))[:40]!r} has no basis — is it an assumption?")
            if i.get("confidence") and i["confidence"] not in LEVELS:
                err(f"{where}: confidence must be one of {sorted(LEVELS)}")
        for a in n.get("assumptions") or []:
            if not a.get("text"):
                err(f"{where}: assumption without text")
            if not a.get("verify"):
                warn(f"{where}: assumption {str(a.get('text', ''))[:40]!r} has no 'verify'")
            if a.get("risk") and a["risk"] not in LEVELS:
                err(f"{where}: risk must be one of {sorted(LEVELS)}")
        res = n.get("result") or {}
        if top and not res.get("summary") and not res.get("items"):
            warn(f"{where}: empty result")
        for r in res.get("items") or []:
            if r.get("kind") and r["kind"] not in RESULT_KINDS:
                err(f"{where}: result kind {r['kind']!r} not in {sorted(RESULT_KINDS)}")
            if r.get("kind") == "verified" and not r.get("how"):
                err(f"{where}: verified result {str(r.get('text', ''))[:40]!r} needs 'how' — the command, test or link that proves it")
        for u in n.get("unchecked") or []:
            if not u.get("text"):
                err(f"{where}: unchecked item without text")
        if top and n.get("status") in ("done", "needs_review", "partial") and "unchecked" not in n:
            warn(f"{where}: say what you did not check — add 'unchecked' (use [] if you checked everything)")
        if n.get("status") == "planned" and not top and not (n.get("detail") or n.get("goal")):
            err(f"{where}: a planned stage needs 'detail' — what will be done")
        for a in n.get("approvals") or []:
            if a.get("recommend") and a.get("options") and a["recommend"] not in a["options"]:
                err(f"{where}: recommend {a['recommend']!r} is not one of the options")
        for k in ("approvals", "actions"):
            for a in n.get(k) or []:
                if not a.get("text"):
                    err(f"{where}: {k[:-1]} without text")
        sids = set()
        for s in n.get("stages") or []:
            if s.get("id") in sids:
                err(f"{where}: stage id {s.get('id')!r} duplicated")
            sids.add(s.get("id"))
            node(s, f"{where} › {s.get('id')}", known, False)
        for f in n.get("flow") or []:
            if f.get("from") not in sids or f.get("to") not in sids:
                err(f"{where}: flow edge {f} references unknown stage")
        if top and not sids:
            warn(f"{where}: no stages — the workflow chart will be empty")
        if top and n.get("status") not in ("done", "failed") and not _has_next(n):
            warn(f"{where}: what happens next? add a stage with status 'planned' (detail + when)")

    ids = set()
    local = []
    for p, text in _strings(d):
        if p.endswith(".url") and text.startswith("file:"):
            fp = urllib.parse.unquote(urllib.parse.urlparse(text).path)
            if not os.path.exists(fp):
                err(f"{p}: local file does not exist: {fp}")
            local.append(p)
    if local:
        warn(f"{len(local)} link(s) point to local files (file://) — readers on other machines cannot open them; prefer repo / web URLs")
    for p, rule, m in scan_secrets(d):
        err(f"{p}: looks like a secret ({rule}: {m}) — remove it from the report")
    for n, t in enumerate(tasks):
        if t.get("id") in ids:
            err(f"tasks[{n}].id {t.get('id')!r} is duplicated")
        ids.add(t.get("id"))
        node(t, f"task {t.get('id') or n}", set(), True)
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
    ap.add_argument("--journal", help="journal JSON (default: <data>.journal.json if it exists)")
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
    jpath = a.journal or journal_path(a.data)
    journal = load_journal(jpath)
    if journal is not None:
        stamp_blocks(data, journal)
        with open(jpath, "w", encoding="utf-8") as f:
            json.dump(journal, f, ensure_ascii=False, indent=1)
        hidden = sum(1 for p in journal["prompts"] if redact_text(p.get("text", "")) != p.get("text", ""))
        if hidden:
            print(f"warning: {hidden} prompt(s) contained something like a secret — masked in the report", file=sys.stderr)
    with open(a.template, encoding="utf-8") as f:
        out_html = render(f.read(), view(data, journal))
    out = a.out or os.path.splitext(a.data)[0] + ".html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(out_html)
    print(os.path.abspath(out))


if __name__ == "__main__":
    main()
