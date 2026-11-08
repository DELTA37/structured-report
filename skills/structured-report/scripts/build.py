#!/usr/bin/env python3
"""Build a self-contained structured-report HTML from a JSON data file.

    python3 build.py report.json                 # -> report.html next to the JSON
    python3 build.py report.json -o out.html
    python3 build.py report.json --check         # validate only

The template (../assets/template.html) renders everything client-side from the
embedded JSON, so the output is one offline file with no external requests.
Exit code 1 on validation errors (warnings do not fail the build).
Standard library only.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "assets", "template.html")

TASK_STATUS = {"done", "in_progress", "blocked", "needs_review", "planned", "failed", "partial"}
STAGE_STATUS = {"done", "failed", "skipped", "partial", "in_progress", "planned", "blocked"}
CONTEXT_KINDS = {"file", "url", "doc", "log", "chat", "data", "commit", "issue", "code", "image"}
RESULT_KINDS = {"added", "changed", "removed", "fixed", "verified", "metric", "doc", "decision"}
LINK_KINDS = {"depends", "related", "blocks"}
LEVELS = {"high", "medium", "low"}


def validate(d):
    errors, warnings = [], []
    err, warn = errors.append, warnings.append
    if not isinstance(d, dict):
        return ["top level must be an object"], []
    meta = d.get("meta") or {}
    if not meta.get("title"):
        err("meta.title is required")
    if meta.get("lang") and meta["lang"][:2] not in ("en", "ru"):
        warn(f"meta.lang={meta['lang']!r}: only en/ru labels are built in, falling back to en")
    tasks = d.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        err("tasks must be a non-empty list")
        return errors, warnings
    ids = set()
    for n, t in enumerate(tasks):
        where = f"tasks[{n}]"
        tid = t.get("id")
        if not tid:
            err(f"{where}.id is required")
        elif tid in ids:
            err(f"{where}.id {tid!r} is duplicated")
        ids.add(tid)
        where = f"task {tid or n}"
        for k in ("title", "problem", "goal"):
            if not t.get(k):
                err(f"{where}: {k} is required")
        if t.get("status") and t["status"] not in TASK_STATUS:
            err(f"{where}: status {t['status']!r} not in {sorted(TASK_STATUS)}")
        ctx_ids = set()
        for c in t.get("context") or []:
            if not c.get("id") or not c.get("title"):
                err(f"{where}: every context item needs id and title")
            if c.get("id") in ctx_ids:
                err(f"{where}: context id {c.get('id')!r} duplicated")
            ctx_ids.add(c.get("id"))
            if c.get("kind") and c["kind"] not in CONTEXT_KINDS:
                warn(f"{where}: context kind {c['kind']!r} has no icon (known: {sorted(CONTEXT_KINDS)})")
            if not c.get("url") and c.get("kind") in ("url", "file", "doc", "issue", "commit"):
                warn(f"{where}: context {c.get('id')!r} ({c['kind']}) has no url — readers cannot open it")
        if not ctx_ids:
            warn(f"{where}: no context gathered")
        for i in t.get("inferences") or []:
            if not i.get("text"):
                err(f"{where}: inference without text")
            for b in i.get("basis") or []:
                if b not in ctx_ids:
                    err(f"{where}: inference basis {b!r} is not a context id")
            if not i.get("basis"):
                warn(f"{where}: inference {i.get('text', '')[:40]!r} has no basis — is it an assumption?")
            if i.get("confidence") and i["confidence"] not in LEVELS:
                err(f"{where}: confidence must be one of {sorted(LEVELS)}")
        for a in t.get("assumptions") or []:
            if not a.get("text"):
                err(f"{where}: assumption without text")
            if not a.get("verify"):
                warn(f"{where}: assumption {a.get('text', '')[:40]!r} has no 'verify'")
            if a.get("risk") and a["risk"] not in LEVELS:
                err(f"{where}: risk must be one of {sorted(LEVELS)}")
        res = t.get("result") or {}
        if not res.get("summary") and not res.get("items"):
            warn(f"{where}: empty result")
        for r in res.get("items") or []:
            if r.get("kind") and r["kind"] not in RESULT_KINDS:
                warn(f"{where}: result kind {r['kind']!r} not in {sorted(RESULT_KINDS)}")
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
            warn(f"{where}: no stages — the flowchart will be empty")
        for a in t.get("approvals") or []:
            if not a.get("text"):
                err(f"{where}: approval without text")
        for a in t.get("actions") or []:
            if not a.get("text"):
                err(f"{where}: action without text")
    for l in d.get("links") or []:
        if l.get("from") not in ids or l.get("to") not in ids:
            err(f"link {l} references unknown task")
        if l.get("kind", "related") not in LINK_KINDS:
            err(f"link kind {l.get('kind')!r} not in {sorted(LINK_KINDS)}")
    return errors, warnings


def build(data, template_path=TEMPLATE):
    with open(template_path, encoding="utf-8") as f:
        tpl = f.read()
    payload = json.dumps(data, ensure_ascii=False, indent=1)
    # never let data close the <script> element
    payload = payload.replace("</", "<\\/").replace("<!--", "<\\!--")
    if "__REPORT_DATA__" not in tpl:
        raise SystemExit("template has no __REPORT_DATA__ placeholder")
    return tpl.replace("__REPORT_DATA__", payload)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", help="report JSON")
    ap.add_argument("-o", "--out", help="output HTML (default: <data>.html)")
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
    out = a.out or os.path.splitext(a.data)[0] + ".html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(build(data))
    print(os.path.abspath(out))


if __name__ == "__main__":
    main()
