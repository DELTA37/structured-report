#!/usr/bin/env python3
"""track.py — keep a report in step with a Claude Code session, and take the reader's answers
straight back to the agent.

    track.py start <report.json> [--session ID]   bind this session to the report (creates the journal)
    track.py wait  <report.json> [--session ID]   block until the reader answers in the report, print
                                                   the answers, exit. Run it as a BACKGROUND command:
                                                   its exit wakes the agent with the answers as a prompt.
    track.py hook                                  UserPromptSubmit hook: log the prompt; hand over
                                                   answers that are still queued
    track.py stop-hook                             Stop hook: if answers are queued, keep the agent going
    track.py daemon                                the local answer service (127.0.0.1:47319); started
                                                   automatically by build.py / wait
    track.py status [--session ID]
    track.py install-hook [--settings PATH]        add both hooks to Claude Code settings

How answers travel: the built report (even opened as a plain file) posts "Send to agent" to the
local daemon with the report's token. The daemon stores the answers in the journal as the next
prompt (kind "answer", delivered=false). They reach the agent by the first of:
  1. a running `wait` (the agent is idle and waiting) — it exits with the answers → the agent wakes;
  2. the Stop hook (the agent is mid-turn) — it blocks the stop and passes the answers on;
  3. the UserPromptSubmit hook (nobody was waiting) — the answers ride along with the next message.
Standard library only.
"""
import argparse
import datetime
import http.server
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.request

HOME = os.path.expanduser("~/.claude/structured-report")
SESSIONS = os.path.join(HOME, "sessions.json")
REGISTRY = os.path.join(HOME, "reports.json")
LOG = os.path.join(HOME, "daemon.log")
PIDFILE = os.path.join(HOME, "daemon.pid")
VERSION = str(int(os.path.getmtime(os.path.abspath(__file__))))   # restart the daemon when this file changes
HERE = os.path.dirname(os.path.abspath(__file__))
HOST = "127.0.0.1"
PORT = int(os.environ.get("STRUCTURED_REPORT_PORT", "47319"))
ENDPOINT = f"http://{HOST}:{PORT}"


# ── files ───────────────────────────────────────────────────────────────────

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
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def journal(jpath):
    j = load(jpath, {})
    j.setdefault("prompts", []); j.setdefault("blocks", {}); j.setdefault("answers", {})
    return j


def add_prompt(jpath, text, kind="prompt"):
    j = journal(jpath)
    n = len(j["prompts"]) + 1
    entry = {"id": f"p{n}", "n": n, "at": now(), "kind": kind, "text": text}
    if kind == "answer":
        entry["delivered"] = False
    j["prompts"].append(entry)
    save(jpath, j)
    return j, entry


def ensure_token(data_path):
    """Journal + answer token for a report; registers the token with the daemon registry."""
    jp = journal_path(data_path)
    j = journal(jp)
    if not j.get("token"):
        j["token"] = secrets.token_urlsafe(18)
        save(jp, j)
    reg = load(REGISTRY, {})
    if reg.get(j["token"], {}).get("journal") != jp:
        reg[j["token"]] = {"journal": jp, "data": os.path.abspath(data_path)}
        save(REGISTRY, reg)
    return j["token"]


def take_pending(jpath):
    """Mark queued answers delivered and return their text (or None)."""
    j = journal(jpath)
    pending = [p for p in j["prompts"] if p.get("kind") == "answer" and not p.get("delivered")]
    if not pending:
        return None
    for p in pending:
        p["delivered"] = True
    save(jpath, j)
    return "\n\n".join(f"#{p['n']} — {p['text']}" for p in pending)


def bound_report(sid):
    b = load(SESSIONS, {}).get(sid) if sid else None
    return b["report"] if b and os.path.exists(b["report"]) else None


def bind(data, sid):
    m = load(SESSIONS, {})
    m[sid] = {"report": os.path.abspath(data), "since": now()}
    save(SESSIONS, m)


def session_id(a):
    return getattr(a, "session", None) or os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID")


# ── daemon ──────────────────────────────────────────────────────────────────

def daemon_alive():
    try:
        with socket.create_connection((HOST, PORT), timeout=0.3):
            return True
    except OSError:
        return False


def daemon_version():
    try:
        with urllib.request.urlopen(f"{ENDPOINT}/version", timeout=0.5) as r:
            return json.loads(r.read()).get("version")
    except Exception:
        return None


def ensure_daemon():
    if daemon_alive():
        if daemon_version() == VERSION:
            return True
        try:                                   # an older daemon: replace it
            os.kill(int(open(PIDFILE).read().strip()), signal.SIGTERM)
        except (OSError, ValueError):
            pass
        for _ in range(20):
            if not daemon_alive():
                break
            time.sleep(0.1)
    os.makedirs(HOME, exist_ok=True)
    with open(LOG, "a") as log:
        subprocess.Popen([sys.executable, os.path.join(HERE, "track.py"), "daemon"], stdin=subprocess.DEVNULL,
                         stdout=log, stderr=log, start_new_session=True, close_fds=True)
    for _ in range(30):
        if daemon_alive():
            return True
        time.sleep(0.1)
    return False


def waiter_alive(jpath):
    try:
        pid = int(open(jpath + ".waiting").read().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def format_answers(title, items, message):
    lines = [f"Answers from the report «{title}»:"]
    for it in items:
        where = f"{it['num']} " if it.get("num") else ""
        ch = it.get("choice")
        parts = (ch if isinstance(ch, list) else [ch] if ch else [])
        if it.get("other"):
            parts.append(f"own answer: {it['other']}")
        if it.get("comment"):
            parts.append(f"comment: {it['comment']}")
        lines.append(f"- [{where}{it.get('title', '')}] {it.get('question', '')}: {'; '.join(parts) or '—'}")
    if message:
        lines.append(f"Message: {message}")
    return "\n".join(lines)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Report-Token")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def reply(self, code, body):
        self.send_response(code)
        self.cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def report(self):
        return load(REGISTRY, {}).get(self.headers.get("X-Report-Token") or "")

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/version":
            return self.reply(200, {"version": VERSION})
        r = self.report()
        if self.path != "/ping" or not r:
            return self.reply(403, {"ok": False})
        self.reply(200, {"ok": True, "waiting": waiter_alive(r["journal"])})

    def do_POST(self):
        r = self.report()
        if self.path != "/answers" or not r:
            return self.reply(403, {"ok": False})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except ValueError:
            return self.reply(400, {"ok": False})
        items, message = body.get("items") or [], (body.get("message") or "").strip()
        if not items and not message:
            return self.reply(400, {"ok": False})
        title = load(r["data"], {}).get("meta", {}).get("title", "report")
        j, entry = add_prompt(r["journal"], format_answers(title, items, message), kind="answer")
        for it in items:
            if it.get("akey"):
                j["answers"][it["akey"]] = {k: it.get(k) for k in ("choice", "other", "comment")} | {"prompt": entry["id"]}
        save(r["journal"], j)
        self.reply(200, {"ok": True, "prompt": entry["n"], "waiting": waiter_alive(r["journal"])})


def cmd_daemon(a):
    srv = http.server.ThreadingHTTPServer((HOST, PORT), Handler)
    os.makedirs(HOME, exist_ok=True)
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
    print(f"{now()} structured-report daemon on {ENDPOINT}", flush=True)
    srv.serve_forever()


# ── commands ────────────────────────────────────────────────────────────────

def cmd_start(a):
    data = os.path.abspath(a.report)
    ensure_token(data)
    sid = session_id(a)
    if not sid:
        sys.exit("no session id: pass --session or run inside Claude Code")
    bind(data, sid)
    ok = ensure_daemon()
    print(f"tracking {data}\njournal  {journal_path(data)}\nsession  {sid}\nanswers  {ENDPOINT} ({'up' if ok else 'NOT running'})")


def cmd_wait(a):
    data = os.path.abspath(a.report)
    jp = journal_path(data)
    ensure_token(data)
    sid = session_id(a)
    if sid:
        bind(data, sid)
    ensure_daemon()
    pidfile = jp + ".waiting"
    with open(pidfile, "w") as f:
        f.write(str(os.getpid()))

    def bye(*_):
        try:
            os.remove(pidfile)
        except OSError:
            pass
        sys.exit(0)
    signal.signal(signal.SIGTERM, bye)
    print(f"waiting for answers to {data} (send them from the report)", file=sys.stderr, flush=True)
    try:
        while True:
            text = take_pending(jp)
            if text:
                print("The reader answered in the report — treat this as their prompt and continue:\n")
                print(text)
                return
            time.sleep(1)
    finally:
        try:
            os.remove(pidfile)
        except OSError:
            pass


def cmd_hook(a):
    """UserPromptSubmit: never fail, never slow the prompt down."""
    try:
        ev = json.load(sys.stdin)
        sid, text = ev.get("session_id"), ev.get("prompt") or ""
        report = bound_report(sid)
        if not report:
            return
        jp = journal_path(report)
        pending = take_pending(jp)
        out = []
        if pending:
            out.append(f"[structured-report] The reader also answered in the report (not yet seen by you):\n{pending}")
        if not (text.strip().startswith("/") and len(text.split()) == 1):
            _, e = add_prompt(jp, text)
            out.append(f"[structured-report] This session tracks {report} — this is prompt #{e['n']}. "
                       f"If it changes the work, update the report JSON and rebuild (changed blocks get #{e['n']}).")
        print("\n".join(out))
    except Exception:
        pass


def cmd_stop_hook(a):
    """Stop: if the reader answered while the agent was working, don't let the turn end."""
    try:
        ev = json.load(sys.stdin)
        report = bound_report(ev.get("session_id"))
        if not report:
            return
        pending = take_pending(journal_path(report))
        if pending:
            print(json.dumps({"decision": "block",
                              "reason": "The reader answered in the report — treat this as their prompt and continue:\n" + pending}))
    except Exception:
        pass


def cmd_status(a):
    report = bound_report(session_id(a))
    if not report:
        print("this session tracks no report"); return
    j = journal(journal_path(report))
    p = (j["prompts"] or [{}])[-1]
    queued = sum(1 for x in j["prompts"] if x.get("kind") == "answer" and not x.get("delivered"))
    print(f"report  {report}\nprompts {len(j['prompts'])} (current #{p.get('n', '—')}), queued answers {queued}\n"
          f"daemon  {ENDPOINT} {'up' if daemon_alive() else 'down'}; waiter {'running' if waiter_alive(journal_path(report)) else 'not running'}")


def cmd_install_hook(a):
    path = os.path.expanduser(a.settings)
    s = load(path, {})
    changed = False
    for event, sub in (("UserPromptSubmit", "hook"), ("Stop", "stop-hook")):
        cmd = f'python3 "{os.path.join(HERE, "track.py")}" {sub}'
        groups = s.setdefault("hooks", {}).setdefault(event, [])
        if any(cmd == h.get("command") for g in groups for h in g.get("hooks", [])):
            continue
        groups.append({"hooks": [{"type": "command", "command": cmd, "timeout": 5}]})
        changed = True
    if not changed:
        print("hooks already installed"); return
    if os.path.exists(path):
        with open(path, encoding="utf-8") as src, open(path + ".bak-structured-report", "w", encoding="utf-8") as dst:
            dst.write(src.read())
    save(path, s)
    print(f"installed UserPromptSubmit + Stop hooks in {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("start"); p.add_argument("report"); p.add_argument("--session")
    p = sub.add_parser("wait"); p.add_argument("report"); p.add_argument("--session")
    sub.add_parser("hook"); sub.add_parser("stop-hook"); sub.add_parser("daemon")
    p = sub.add_parser("status"); p.add_argument("--session")
    p = sub.add_parser("install-hook"); p.add_argument("--settings", default="~/.claude/settings.json")
    a = ap.parse_args()
    {"start": cmd_start, "wait": cmd_wait, "hook": cmd_hook, "stop-hook": cmd_stop_hook, "daemon": cmd_daemon,
     "status": cmd_status, "install-hook": cmd_install_hook}[a.cmd](a)


if __name__ == "__main__":
    main()
