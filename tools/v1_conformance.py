#!/usr/bin/env python3
"""AutoHotkey v1 conformance checks: tests/v1conf/<suite>.ahk, one feature per section.

A section starts with ``;; test: <feature>``, holds standalone v1 code and ends
with ``;; expect:`` lines giving its console output, one line each (``;; expect:``
alone = an empty line).  Every section runs as its own script with the
prelude ``out(s)`` (FileAppend to stdout).  Expected values come from the
AutoHotkey v1.1 documentation and source semantics, not from BHK.

    python3 tools/v1_conformance.py [suite ...] [-v]
"""
import concurrent.futures
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(ROOT, "tests", "v1conf")
PRELUDE = "#NoEnv\nout(s) {\n    FileAppend, %s%`n, *\n}\n"
SUITES = ("language", "gui")


def sections(suite):
    path = os.path.join(CONF, suite + ".ahk")
    tests, cur = [], None
    for line in open(path, encoding="utf-8"):
        m = re.match(r";; test: (.*)", line)
        if m:
            cur = {"name": m[1].strip(), "code": [], "expect": []}
            tests.append(cur)
            continue
        if cur is None:
            continue
        m = re.match(r";; expect:(?: (.*))?$", line.rstrip("\n"))
        if m:
            cur["expect"].append(m[1] or "")
        else:
            cur["code"].append(line)
    return tests


def run_one(suite, t, tmp):
    fd, path = tempfile.mkstemp(suffix=".ahk", dir=tmp)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(PRELUDE + "".join(t["code"]) + "\nExitApp\n")
    env = dict(os.environ, PYTHONPATH=ROOT)
    try:
        p = subprocess.run([sys.executable, "-m", "bunnyhotkey", "--console", "--ahk-version=1",
                            "--backend=null", "--no-tray", path], cwd=tmp, capture_output=True, text=True, timeout=30, env=env)
        got = p.stdout.rstrip("\n").split("\n") if p.stdout.strip("\n") or t["expect"] == [""] else []
        err = p.stderr.strip()
    except subprocess.TimeoutExpired:
        got, err = [], "timeout"
    return got == t["expect"], got, err


def run(suite, verbose=False):
    tests = sections(suite)
    with tempfile.TemporaryDirectory() as tmp:
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            results = list(pool.map(lambda t: run_one(suite, t, tmp), tests))
    passed = 0
    for t, (ok, got, err) in zip(tests, results):
        passed += ok
        if verbose and not ok:
            print(f"FAIL [{suite}] {t['name']}\n  want {t['expect']}\n  got  {got}" + (f"\n  err  {err[:300]}" if err else ""))
    return passed, len(tests)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    for s in args or SUITES:
        p, n = run(s, verbose="-v" in sys.argv)
        print(f"{s}: {p}/{n} ({round(100 * p / n) if n else 0}%)")
