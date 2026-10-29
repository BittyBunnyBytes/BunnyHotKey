#!/usr/bin/env python3
"""Run-test conformance suites: tests/conformance/<suite>.ahk, one feature per section.

The first line of a suite is ``;; suite: v1|v2 [display] [desktop]``:
``display`` - needs an X display (Gui, windows); ``serial`` - sections share
a global resource (clipboard, registry) and run one at a time; ``desktop`` -
uses the real X11 backend (synthetic keyboard/mouse input, hotkeys), serially;
``tray`` - keeps the tray icon (other suites run with --no-tray).  A section starts with ``;; test: <feature>``, holds standalone code
and ends with ``;; expect:`` lines giving its console output (``;; expect:``
alone = an empty line).  Each section runs as its own script after a prelude
that defines ``out(s)`` (a line to stdout).  Expected values come from the
AutoHotkey documentation and source semantics, not from BHK.

    python3 tools/conformance.py [suite ...] [-v]
"""
import concurrent.futures
import glob
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(ROOT, "tests", "conformance")
PRELUDE = {
    "1": "#NoEnv\nout(s) {\n    FileAppend, %s%`n, *\n}\n",
    "2": "out(s) => FileAppend(s \"`n\", \"*\")\n",
}


def suites():
    return sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(CONF, "*.ahk")))


def load(suite):
    path = os.path.join(CONF, suite + ".ahk")
    lines = open(path, encoding="utf-8").read().split("\n")
    head = re.match(r";; suite:\s*(.*)", lines[0])
    words = head[1].split() if head else ["v2"]
    meta = {"version": words[0].lstrip("v"), "display": "display" in words or "desktop" in words,
            "desktop": "desktop" in words, "serial": "serial" in words or "desktop" in words,
            "tray": "tray" in words}
    tests, cur = [], None
    meta["prelude"] = ""            # code between the header and the first section runs before every section
    for line in lines[1:]:
        m = re.match(r";; test: (.*)", line)
        if m:
            cur = {"name": m[1].strip(), "code": [], "expect": []}
            tests.append(cur)
            continue
        if cur is None:
            if not line.startswith(";"):
                meta["prelude"] += line + "\n"
            continue
        m = re.match(r";; expect:(?: (.*))?$", line)
        if m:
            cur["expect"].append(m[1] or "")
        else:
            cur["code"].append(line + "\n")
    return meta, tests


def run_one(meta, t, tmp):
    tmp = tempfile.mkdtemp(dir=tmp)         # each section gets its own working directory
    fd, path = tempfile.mkstemp(suffix=".ahk", dir=tmp)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(PRELUDE[meta["version"]] + meta["prelude"] + "".join(t["code"]) + "\nExitApp\n")
    cmd = [sys.executable, "-m", "bunnyhotkey", "--console", "--ahk-version=" + meta["version"]]
    if not meta["tray"]:
        cmd.append("--no-tray")
    if not meta["desktop"]:
        cmd.append("--backend=null")
    env = dict(os.environ, PYTHONPATH=ROOT, BHK_ROOT=ROOT)
    try:
        p = subprocess.run(cmd + [path], cwd=tmp, capture_output=True, text=True, timeout=60, env=env)
        out = p.stdout.rstrip("\n")
        got = out.split("\n") if out or t["expect"] == [""] else []
        err = p.stderr.strip()
    except subprocess.TimeoutExpired:
        got, err = [], "timeout"
    return got == t["expect"], got, err


def run(suite, verbose=False, details=False):
    """(passed, total) - or with details=True a list of (test, ok)."""
    meta, tests = load(suite)
    if meta["display"] and not os.environ.get("DISPLAY"):
        return ([] if details else (0, len(tests)))
    with tempfile.TemporaryDirectory() as tmp:
        workers = 1 if meta["serial"] else 8
        with concurrent.futures.ThreadPoolExecutor(workers) as pool:
            results = list(pool.map(lambda t: run_one(meta, t, tmp), tests))
    passed = 0
    for t, (ok, got, err) in zip(tests, results):
        passed += ok
        if verbose and not ok:
            print(f"FAIL [{suite}] {t['name']}\n  want {t['expect']}\n  got  {got}" + (f"\n  err  {err[:400]}" if err else ""))
    if details:
        return [(t, ok) for t, (ok, _, _) in zip(tests, results)]
    return passed, len(tests)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    total = [0, 0]
    for s in args or suites():
        p, n = run(s, verbose="-v" in sys.argv)
        total[0] += p
        total[1] += n
        print(f"{s}: {p}/{n} ({round(100 * p / n) if n else 0}%)", flush=True)
    sys.exit(0 if total[0] == total[1] else 1)
