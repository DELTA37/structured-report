#!/usr/bin/env python3
"""ide.py — show a session's report inside the JetBrains IDE the session runs in, as a split  Session | Report.

    ide.py open <report.json|report.html> --project DIR [--session ID] [--ide webstorm|pycharm|…]

The IDE is the one this process runs under (`__CFBundleIdentifier`, set for sessions started from the IDE's
agent panel or terminal), or --ide. Nothing happens outside a JetBrains IDE.

How: a request file goes to ~/.claude/structured-report/ide/requests/, then the IDE's own `ideScript`
command runs ide-open.groovy inside the already running IDE (no plugin, no restart). The script opens the
HTML in the IDE's built-in browser in the editor window to the right of the session and reloads it every
time the report is rebuilt. The launcher gets a clean environment: GUI apps must not inherit CLAUDE_* vars.
Standard library only; never raises from `open_in_ide` (best-effort, called from a SessionStart hook).
"""
import argparse
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "ide-open.groovy")
REQS = os.path.expanduser("~/.claude/structured-report/ide/requests")

# bundle id → launcher name inside <App>.app/Contents/MacOS
IDES = {
    "com.jetbrains.WebStorm": "webstorm", "com.jetbrains.pycharm": "pycharm", "com.jetbrains.pycharm.ce": "pycharm",
    "com.jetbrains.intellij": "idea", "com.jetbrains.intellij.ce": "idea", "com.jetbrains.goland": "goland",
    "com.jetbrains.rider": "rider", "com.jetbrains.CLion": "clion", "com.jetbrains.rubymine": "rubymine",
    "com.jetbrains.PhpStorm": "phpstorm", "com.jetbrains.datagrip": "datagrip",
}


def launcher(ide=None):
    """Path of the IDE's command-line launcher, or None when not inside a JetBrains IDE."""
    bid = os.environ.get("__CFBundleIdentifier", "")
    if ide:
        bid = next((b for b, n in IDES.items() if n == ide.lower()), "")
    name = IDES.get(bid)
    if not name:
        return None
    apps = [a.strip() for a in subprocess.run(["mdfind", f"kMDItemCFBundleIdentifier == '{bid}'"],
                                              capture_output=True, text=True, timeout=5).stdout.splitlines()]
    apps += glob.glob("/Applications/*.app") + glob.glob(os.path.expanduser("~/Applications/*.app"))
    for app in apps:
        exe = os.path.join(app, "Contents", "MacOS", name)
        if os.path.exists(exe):
            return exe
    return None


def _prop(v):
    return str(v).replace("\\", "\\\\").replace("\n", " ")


def open_in_ide(report, project, sid=None, ide=None):
    """Ask the running IDE to show `report` next to the session. Returns the launcher used, or None."""
    try:
        exe = launcher(ide)
        if not exe or not project:
            return None
        html = os.path.splitext(os.path.abspath(report))[0] + ".html"
        if not os.path.exists(html):
            return None
        sid = sid or os.path.basename(html).rsplit("-", 1)[-1].split(".")[0]
        os.makedirs(REQS, exist_ok=True)
        req = os.path.join(REQS, f"{sid}.properties")
        with open(req + ".tmp", "w", encoding="utf-8") as f:
            f.write(f"sid={_prop(sid)}\nproject={_prop(os.path.abspath(project))}\n"
                    f"html={_prop(html)}\ntitle=Отчёт · {_prop(sid[:8])}\n")
        os.replace(req + ".tmp", req)
        env = {"HOME": os.path.expanduser("~"), "USER": os.environ.get("USER", ""), "PATH": "/usr/bin:/bin"}
        subprocess.Popen([exe, "ideScript", SCRIPT], env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return exe
    except Exception:
        return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["open"])
    ap.add_argument("report")
    ap.add_argument("--project", default=os.getcwd())
    ap.add_argument("--session")
    ap.add_argument("--ide")
    a = ap.parse_args()
    used = open_in_ide(a.report, a.project, a.session, a.ide)
    print(f"asked {used}" if used else "not inside a JetBrains IDE (or no HTML) — nothing to do")
    sys.exit(0 if used else 1)
