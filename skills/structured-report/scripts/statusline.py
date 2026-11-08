#!/usr/bin/env python3
"""statusline.py — one status-line row for Claude Code: the report this session tracks, as a
clickable link (OSC 8) that opens the HTML in the browser, plus how many questions still wait.

Use it alone as the status line:
    "statusLine": {"type": "command", "command": "python3 <skill>/scripts/statusline.py"}
or append its output to your own status line (it reads the same JSON from stdin and prints
nothing when the session tracks no report). Standard library only.
"""
import json
import os
import sys
import urllib.parse

SESSIONS = os.path.expanduser("~/.claude/structured-report/sessions.json")


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def waiting(data, answers):
    n = 0

    def walk(node, key):
        nonlocal n
        n += sum(1 for i, _ in enumerate(node.get("approvals") or []) if f"{key}#a{i}" not in answers)
        for s in node.get("stages") or []:
            walk(s, f"{key}/{s.get('id')}")
    for t in data.get("tasks") or []:
        walk(t, t.get("id"))
    return n


def line(event):
    b = load(SESSIONS, {}).get(event.get("session_id") or "")
    if not b:
        return ""
    data_path = b["report"]
    html_path = os.path.splitext(data_path)[0] + ".html"
    if not os.path.exists(html_path):
        return ""
    data = load(data_path, {})
    journal = load(os.path.splitext(data_path)[0] + ".journal.json", {})
    title = (data.get("meta") or {}).get("title") or os.path.basename(html_path)
    if len(title) > 60:
        title = title[:59] + "…"
    url = "file://" + urllib.parse.quote(os.path.abspath(html_path))
    link = f"\x1b]8;;{url}\x1b\\\x1b[4m{title}\x1b[24m ↗\x1b]8;;\x1b\\"
    q = waiting(data, journal.get("answers") or {})
    tail = f" \x1b[2m·\x1b[0m \x1b[33m{q} question{'s' if q != 1 else ''} waiting\x1b[0m" if q else ""
    return f"\x1b[2m📋 Report:\x1b[0m {link}{tail}"


if __name__ == "__main__":
    try:
        sys.stdout.write(line(json.load(sys.stdin)))
    except Exception:
        pass
