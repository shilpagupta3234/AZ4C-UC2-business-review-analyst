"""REQUIRED before you start: checks that your AI activity on this assignment will be recorded, and says what to fix.

    python check_setup.py        (on Windows, if that doesn't work: py check_setup.py)

Run it from this folder before you write any code, and again after fixing anything it reports, until it says
"ALL SET". A submission without a recorded AI activity log may be disqualified.
It changes nothing on your machine and sends nothing about you or your work.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
HERE = PROJECT / ".az4c"
WINDOWS = os.name == "nt"
COMMANDS = (["python3"], ["python"], ["py", "-3"])
HOOK_FILES = (".az4c/log_event.py", ".claude/settings.json", ".cursor/hooks.json", ".github/hooks/az4c-activity.json")

fixes: list[str] = []
notes: list[str] = []


def say(ok: bool | None, text: str, fix: str = "") -> None:
    print(f"  [{'OK ' if ok else 'FIX' if ok is False else '!  '}] {text}")
    if fix:
        (fixes if ok is False else notes).append(fix)


def version_of(cmd: list[str]) -> tuple[int, ...] | None:
    exe = shutil.which(cmd[0])
    if exe is None:
        return None
    try:
        r = subprocess.run([exe, *cmd[1:], "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"],
                           capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        return tuple(int(x) for x in r.stdout.strip().split("."))
    except ValueError:
        return None


def check_python() -> None:
    print("Python")
    found = {" ".join(c): version_of(c) for c in COMMANDS}
    working = {name: v for name, v in found.items() if v}
    for name, v in found.items():
        say(True if v else None, f"{name}: {'.'.join(map(str, v)) if v else 'not available'}")
    if not working:
        how = ("Install Python 3.12 from python.org and, in the installer, tick \"Add python.exe to PATH\". "
               "If it is installed already, run the installer again, choose Modify, and tick "
               "\"Add Python to environment variables\". Then close and reopen your editor."
               if WINDOWS else "Install Python 3.12 (python.org, or your package manager) so that python3 works.")
        say(False, "Your AI tool runs python3, python or py, and none of them works on this machine.", how)
    elif all(v < (3, 8) for v in working.values()):
        say(False, "The Python your AI tool would use is older than 3.8.", "Install Python 3.12 from python.org.")
    else:
        say(True, f"Your AI tool will run {next(iter(working))}.")
    has_312 = any(v[:2] == (3, 12) for v in working.values()) or (WINDOWS and version_of(["py", "-3.12"]))
    if not has_312:
        say(None, "Python 3.12 not found. START_HERE.md asks you to use it: your code is run with 3.12.",
            "Install Python 3.12 from python.org and use it for this project.")


def check_files() -> dict:
    print("Settings files")
    folders = [PROJECT] + ([PROJECT / "code"] if (PROJECT / "code").is_dir() else [])
    for folder in folders:
        missing = [f for f in HOOK_FILES if not (folder / f).is_file()]
        where = "repository folder" if folder == PROJECT else "code/"
        if missing:
            say(False, f"{where}: missing {', '.join(missing)}",
                "Some AI tool settings files are missing. Download your pack again from your assessment link and "
                "copy your work into it.")
        else:
            say(True, f"{where}: all in place")
    try:
        cfg = json.loads((HERE / "candidate.json").read_text(encoding="utf-8"))
        if not all(cfg.get(k) for k in ("candidate", "token", "endpoint")):
            raise ValueError
    except (OSError, ValueError):
        say(False, ".az4c/candidate.json is missing or incomplete",
            "This copy wasn't downloaded from your own assessment link. Download your pack from your link and "
            "work in that copy.")
        return {}
    say(True, "your assessment settings are in place")
    return cfg


def check_connection(cfg: dict) -> None:
    print("Connection")
    host = cfg["endpoint"].split("/")[2] if "//" in cfg["endpoint"] else cfg["endpoint"]
    req = urllib.request.Request(cfg["endpoint"], data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg['token']}"})
    try:
        urllib.request.urlopen(req, timeout=60)
        say(True, f"{host} reached")
    except urllib.error.HTTPError as e:
        if e.code == 400:
            say(True, f"{host} reached, and your settings are accepted")
        elif e.code == 401:
            say(False, f"{host} doesn't accept the settings in this copy",
                "Download your pack again from your own assessment link and work in that copy.")
        else:
            say(None, f"{host} answered {e.code}; run this check again in a few minutes")
    except Exception:
        say(False, f"{host} can't be reached from this machine",
            f"Your network may be blocking https://{host} (a firewall, proxy or VPN). Allow it, or try another "
            "network, then run this check again.")


def flush_waiting(cfg: dict) -> None:
    queue = Path(tempfile.gettempdir()) / f"az4c-activity-{cfg['candidate']}"
    waiting = list(queue.glob("*.json")) if queue.is_dir() else []
    if not waiting:
        return
    subprocess.run([sys.executable, str(HERE / "log_event.py"), "--flush"], timeout=300, stdin=subprocess.DEVNULL)
    left = len(list(queue.glob("*.json")))
    if left:
        say(False, f"{left} of {len(waiting)} recorded steps are still waiting to be sent",
            "Fix the connection above, then run this check again: it sends them.")
    else:
        say(True, f"{len(waiting)} recorded steps that were waiting have now been sent")


def check_folder(cfg: dict) -> Path | None:
    print("Folder")
    if not (PROJECT / ".git").exists():
        above = next((p for p in PROJECT.parents if (p / ".git").exists()), None)
        if above:
            say(None, f"this folder is inside another git repository ({above})",
                f"Push this folder as its own repository, as START_HERE.md says: run git init in {PROJECT}, "
                f"not in {above}.")
    queue = Path(tempfile.gettempdir()) / f"az4c-activity-{cfg['candidate']}"
    folders = [PROJECT] + ([PROJECT / "code"] if (PROJECT / "code").is_dir() else [])
    for folder in folders:
        if (queue / f"snapshot-{hashlib.sha256(str(folder).encode()).hexdigest()[:12]}.state").is_file():
            say(True, f"your AI tool has recorded activity with {folder} open as the project folder")
            return folder
    say(None, "your AI tool hasn't recorded anything from this folder yet")
    return None


def main() -> None:
    print(f"Checking {PROJECT}\n")
    check_python()
    cfg = check_files()
    used = None
    if cfg:
        check_connection(cfg)
        flush_waiting(cfg)
        used = check_folder(cfg)
    print()
    for note in dict.fromkeys(notes):
        print(f"Note: {note}")
    line = "=" * 78
    if fixes:
        print(f"\n{line}\n  NOT READY: your AI activity on this assignment is NOT being recorded.")
        print("  A submission without a recorded AI activity log may be disqualified.")
        print(f"{line}\nFix the following, then run this check again until it says ALL SET:")
        for i, fix in enumerate(dict.fromkeys(fixes), 1):
            print(f"  {i}. {fix}")
        sys.exit(1)
    if used:
        print(f"\n{line}\n  ALL SET: your AI activity on this assignment is being recorded.\n{line}")
        print("Keep working with this folder (or its code folder) open in your editor. Run this check again if you")
        print("change computer or editor.")
        return
    print(f"\n{line}\n  ALL SET: your AI activity on this assignment will be recorded.\n{line}")
    print("Last step: in Claude Code, Cursor or VS Code with GitHub Copilot, open exactly this folder as the project")
    print(f"folder, not a folder above it:\n\n    {PROJECT}\n\n(or its code folder). Allow the project's settings if "
          "your editor asks, send one prompt to your")
    print("AI assistant, then run this check again: it should say your activity is being recorded.")


if __name__ == "__main__":
    main()
