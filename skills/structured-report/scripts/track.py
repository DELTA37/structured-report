#!/usr/bin/env python3
"""track.py — keep a report in step with a Claude Code session, and take answers back from it.

    track.py start <report.json> [--session ID]   bind this session to the report (creates the journal)
    track.py hook                                  UserPromptSubmit hook: log the prompt to the bound report
    track.py serve <report.json> [--port N]        serve the built report; the first "Send to agent"
                                                   stores the answers, prints them and exits
    track.py status [--session ID]                 which report this session tracks, current prompt
    track.py install-hook [--settings PATH]        add the UserPromptSubmit hook to Claude Code settings

The journal (<report>.journal.json, next to the report JSON) holds the prompts, the answers given
in the report, and — written by build.py — when each block appeared or changed. Standard library only.

Flow: the agent runs `start` once, then updates the report JSON and rebuilds whenever a prompt
changes the work. With open questions it runs `serve` as a background command; when the reader
presses "Send to agent", serve prints the answers and exits — the harness hands that output back
to the agent, which continues as if the reader had typed it.
"""
import argparse
import datetime
import http.server
import json
import os
import secrets
import sys
import threading
import webbrowser

HOME = os.path.expanduser("~/.claude/structured-report")
SESSIONS = os.path.join(HOME, "sessions.json")
HERE = os.path.dirname(os.path.abspath(__file__))


def journal_path(data_path):
    return os.path.splitext(os.path.abspath(data_path))[0] + ".journal.json"


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def add_prompt(jpath, text, kind="prompt"):
    j = load(jpath, {})
    j.setdefault("prompts", []); j.setdefault("blocks", {}); j.setdefault("answers", {})
    n = len(j["prompts"]) + 1
    entry = {"id": f"p{n}", "n": n, "at": now(), "kind": kind, "text": text}
    j["prompts"].append(entry)
    save(jpath, j)
    return j, entry


# ── commands ────────────────────────────────────────────────────────────────

def cmd_start(a):
    data = os.path.abspath(a.report)
    jp = journal_path(data)
    if not os.path.exists(jp):
        save(jp, {"prompts": [], "blocks": {}, "answers": {}})
    sid = a.session or os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID")
    if not sid:
        sys.exit("no session id: pass --session or run inside Claude Code")
    m = load(SESSIONS, {})
    m[sid] = {"report": data, "since": now()}
    save(SESSIONS, m)
    print(f"tracking {data}\njournal  {jp}\nsession  {sid}")


def cmd_hook(a):
    """UserPromptSubmit: never fail, never slow the prompt down."""
    try:
        ev = json.load(sys.stdin)
        sid, text = ev.get("session_id"), ev.get("prompt") or ""
        b = load(SESSIONS, {}).get(sid)
        if not b or not os.path.exists(b["report"]):
            return
        if text.strip().startswith("/") and len(text.split()) == 1:
            return                                    # bare slash commands are not work prompts
        _, e = add_prompt(journal_path(b["report"]), text)
        print(f"[structured-report] This session tracks {b['report']} — this is prompt #{e['n']}. "
              f"If this prompt changes the work, update the report JSON and rebuild it "
              f"(build.py stamps changed blocks with #{e['n']}).")
    except Exception:
        pass


def cmd_status(a):
    sid = a.session or os.environ.get("CLAUDE_CODE_SESSION_ID")
    b = load(SESSIONS, {}).get(sid)
    if not b:
        print("this session tracks no report"); return
    j = load(journal_path(b["report"]), {})
    p = (j.get("prompts") or [{}])[-1]
    print(f"report  {b['report']}\nprompts {len(j.get('prompts', []))} (current #{p.get('n', '—')})")


def format_answers(title, items, message):
    lines = [f"Answers from the report «{title}»:"]
    for it in items:
        where = f"{it['num']} " if it.get("num") else ""
        if it["type"] == "approval":
            val = it.get("choice") or "—"
        else:
            val = "done" if it.get("done") else "not done"
        c = f" — {it['comment']}" if it.get("comment") else ""
        lines.append(f"- [{where}{it['title']}] {it['question']}: {val}{c}")
    if message:
        lines.append(f"Message: {message}")
    return "\n".join(lines)


def cmd_serve(a):
    data = os.path.abspath(a.report)
    html_path = os.path.splitext(data)[0] + ".html"
    jp = journal_path(data)
    if not os.path.exists(html_path):
        sys.exit(f"build the report first: {html_path} not found")
    token = secrets.token_urlsafe(16)
    done = threading.Event()
    result = {}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.split("?")[0] not in ("/", "/index.html"):
                self.send_error(404); return
            with open(html_path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != "/__answers" or self.headers.get("X-Report-Token") != token:
                self.send_error(403); return
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            except ValueError:
                self.send_error(400); return
            items, message = body.get("items") or [], (body.get("message") or "").strip()
            if not items and not message:
                self.send_error(400); return
            title = load(data, {}).get("meta", {}).get("title", "report")
            text = format_answers(title, items, message)
            j, entry = add_prompt(jp, text, kind="answer")
            for it in items:
                j["answers"][it["akey"]] = {k: it.get(k) for k in ("choice", "done", "comment")} | {"prompt": entry["id"]}
            save(jp, j)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "prompt": entry["n"]}).encode())
            result["text"] = text
            done.set()

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), H)
    url = f"http://127.0.0.1:{srv.server_address[1]}/?t={token}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"report served at {url} — waiting for answers", file=sys.stderr, flush=True)
    if not a.no_open:
        webbrowser.open(url)
    done.wait()
    srv.shutdown()
    print("The reader answered in the report (treat this as their prompt):\n")
    print(result["text"])


def cmd_install_hook(a):
    path = os.path.expanduser(a.settings)
    s = load(path, {})
    cmd = f'python3 "{os.path.join(HERE, "track.py")}" hook'
    hooks = s.setdefault("hooks", {}).setdefault("UserPromptSubmit", [])
    if any(cmd == h.get("command") for g in hooks for h in g.get("hooks", [])):
        print("hook already installed"); return
    hooks.append({"hooks": [{"type": "command", "command": cmd, "timeout": 5}]})
    if os.path.exists(path):
        os.replace(path, path + ".bak-structured-report")
    save(path, s)
    print(f"installed UserPromptSubmit hook in {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start"); p.add_argument("report"); p.add_argument("--session")
    sub.add_parser("hook")
    p = sub.add_parser("status"); p.add_argument("--session")
    p = sub.add_parser("serve"); p.add_argument("report"); p.add_argument("--port", type=int, default=0); p.add_argument("--no-open", action="store_true")
    p = sub.add_parser("install-hook"); p.add_argument("--settings", default="~/.claude/settings.json")
    a = ap.parse_args()
    {"start": cmd_start, "hook": cmd_hook, "status": cmd_status, "serve": cmd_serve, "install-hook": cmd_install_hook}[a.cmd](a)


if __name__ == "__main__":
    main()
