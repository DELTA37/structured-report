#!/usr/bin/env python3
"""autobind.py — every Claude Code session gets its own living structured-report, without anyone
running `track.py start` by hand; inside PyCharm / WebStorm the report is shown beside the session.

    autobind.py install [--repo DIR | --global]   wire the SessionStart hook: into DIR/.claude/settings.local.json
                                                  (default: the current repo) or ~/.claude/settings.json
    autobind.py uninstall [--repo DIR | --global] remove it again
    autobind.py status                            where it is wired
    autobind.py hook                              the SessionStart hook itself (reads the event on stdin)
    autobind.py bind <session-id> <cwd>           bind an already running session

What it does for a session that is not bound yet:
  1. writes a skeleton report  ~/Reports/sessions/<repo>/<date>-<sid8>.json  (one in_progress task),
  2. `track.py start --session <id>` — journal, answer token, daemon,
  3. `build.py` — so the HTML exists and the status line shows the link,
  4. tells the agent (additionalContext) where the report is and that it must keep it current.
A session that is already bound (resume, /clear, compact) only gets the reminder.
Never fails the session: every error is swallowed. Standard library only.
"""
import datetime
import json
import os
import subprocess
import sys

SKILL = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TRACK = os.path.join(SKILL, "scripts", "track.py")
BUILD = os.path.join(SKILL, "scripts", "build.py")
SESSIONS = os.path.expanduser("~/.claude/structured-report/sessions.json")
ROOT = os.path.expanduser("~/Reports/sessions")


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def bound(sid):
    b = load(SESSIONS, {}).get(sid)
    return b["report"] if b and os.path.exists(b.get("report", "")) else None


def skeleton(sid, repo, root=None):
    today = datetime.date.today().isoformat()
    return {
        "meta": {"title": f"{repo} · сессия {sid[:8]} · {today}", "lang": "ru",
                 **({"roots": [root]} if root else {})},
        "tasks": [{
            "id": "session",
            "title": "Работа сессии (заполняется по ходу)",
            "status": "in_progress",
            "brief": f"Репо: {repo}\nСессия: {sid[:8]}",
            "problem": "Задача сессии ещё не сформулирована — агент заполнит после первого запроса.",
            "goal": "- Отчёт отражает каждую задачу сессии, её контекст, выводы, результат и что не проверено.",
            "stages": [
                {"id": "s1", "title": "Первый запрос", "status": "planned",
                 "detail": "Разобрать запрос и разрезать работу на задачи отчёта.",
                 "when": "после первого запроса пользователя"},
                {"id": "s2", "title": "Работа и обновление отчёта", "status": "planned",
                 "detail": "После каждого запроса, меняющего работу, — обновить JSON и пересобрать.",
                 "when": "по ходу сессии"},
            ],
        }],
    }


def bind(sid, cwd):
    """Returns (report_path, created)."""
    have = bound(sid)
    if have:
        return have, False
    repo = os.path.basename(os.path.normpath(cwd or os.getcwd())) or "session"
    day = datetime.date.today().isoformat()
    path = os.path.join(ROOT, repo, f"{day}-{sid[:8]}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(skeleton(sid, repo, os.path.abspath(cwd) if cwd else None), f, ensure_ascii=False, indent=2)
    subprocess.run([sys.executable, TRACK, "start", path, "--session", sid],
                   capture_output=True, timeout=20)
    subprocess.run([sys.executable, BUILD, path], capture_output=True, timeout=30)
    return path, True


def context(path, created):
    html = os.path.splitext(path)[0] + ".html"
    head = "создан и привязан" if created else "привязан"
    return (f"[structured-report] Живой отчёт этой сессии {head}: {path} (HTML: {html}). "
            "Веди его по скиллу structured-report: после каждого запроса, который меняет работу, "
            "обнови JSON (задачи, контекст, выводы, допущения, результат, что не проверено, стадии) "
            f"и пересобери: python3 {BUILD} {path}. Пока это каркас — замени его реальной работой "
            "после первого содержательного запроса. Не открывай HTML сам без просьбы.")


def in_ide(path, cwd, sid):
    """Session runs inside PyCharm / WebStorm → show the report next to it (split Session | Report)."""
    try:
        sys.path.insert(0, os.path.join(SKILL, "scripts"))
        import ide  # noqa: E402
        if ide.open_in_ide(path, cwd, sid):
            return (" Отчёт показан в IDE справа от сессии и перезагружается сам после каждой пересборки "
                    "— открывать HTML через `open` не нужно.")
    except Exception:
        pass
    return ""


def hook():
    try:
        ev = json.load(sys.stdin)
        sid = ev.get("session_id")
        if not sid:
            return
        path, created = bind(sid, ev.get("cwd"))
        ide = in_ide(path, ev.get("cwd"), sid)
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                 "additionalContext": context(path, created) + ide}},
                         ensure_ascii=False))
    except Exception:
        pass


HOOK_CMD = f'python3 "{os.path.realpath(__file__)}" hook'
MARK = "autobind"                                       # matches this script and the old ~/.claude/hooks copy


def settings_path(args):
    if "--global" in args:
        return os.path.expanduser("~/.claude/settings.json")
    repo = args[args.index("--repo") + 1] if "--repo" in args else os.getcwd()
    top = subprocess.run(["git", "-C", repo, "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
    return os.path.join(top or os.path.abspath(repo), ".claude", "settings.local.json")


def wired(entries):
    return [e for e in entries for h in e.get("hooks", []) if "structured-report" in h.get("command", "") and MARK in h.get("command", "")]


def install(args, on=True):
    p = settings_path(args)
    d = load(p, {})
    ss = d.setdefault("hooks", {}).setdefault("SessionStart", [])
    old = wired(ss)
    for e in old:
        ss.remove(e)
    if on:
        ss.append({"hooks": [{"type": "command", "command": HOOK_CMD, "timeout": 60}]})
    if not ss:
        d["hooks"].pop("SessionStart")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f, open(p + ".bak-structured-report", "w", encoding="utf-8") as b:
            b.write(f.read())
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print(("wired: " if on else "removed: ") + p)


def status():
    places = [os.path.expanduser("~/.claude/settings.json")]
    for p in places + [settings_path([])]:
        if wired(load(p, {}).get("hooks", {}).get("SessionStart", [])):
            print("wired:", p)


if __name__ == "__main__":
    a = sys.argv[1:]
    cmd = a[0] if a else "hook"
    if cmd == "bind":
        p, c = bind(a[1], a[2] if len(a) > 2 else None)
        print(("created " if c else "already ") + p)
    elif cmd == "install":
        install(a[1:])
    elif cmd == "uninstall":
        install(a[1:], on=False)
    elif cmd == "status":
        status()
    else:
        hook()
