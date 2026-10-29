#!/usr/bin/env python3
"""The AutoHotkey v1 script corpus: 327 public v1 scripts that pass tools/v1_corpus_audit.py's safety filter
(no process launching, file writes, registry, network, clipboard, native memory, window control, dynamic
code or input outside hotkeys).  The scripts themselves aren't in this repository (their licences vary);
tests/v1corpus/manifest.json lists each one's GitHub source.

    python3 tools/v1_corpus.py fetch [DIR]     download the scripts into DIR/scripts and re-audit them
    python3 tools/v1_corpus.py measure [DIR]   load + compile each one (bhk --validate, nothing runs), record
                                               the result in docs/parity.json and docs/V1_CORPUS.md

DIR defaults to $BHK_V1_CORPUS or ~/Programs/bhk-v1-safe-corpus.
"""
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "tests", "v1corpus", "manifest.json")


def corpus_dir(arg=None):
    return arg or os.environ.get("BHK_V1_CORPUS") or os.path.expanduser("~/Programs/bhk-v1-safe-corpus")


def fetch(d):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from v1_corpus_audit import audit
    os.makedirs(os.path.join(d, "scripts"), exist_ok=True)
    ok = skipped = 0
    for item in json.load(open(MANIFEST)):
        repo, path = (s.strip() for s in item["source"].split(" : ", 1))
        url = repo.replace("https://github.com/", "https://raw.githubusercontent.com/") + "/HEAD/" + \
            urllib.parse.quote(path)
        dest = os.path.join(d, "scripts", item["file"])
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = r.read()
        except (OSError, ValueError) as e:
            print(f"skip {item['file']}: {e}")
            skipped += 1
            continue
        with open(dest, "wb") as fh:
            fh.write(data)
        if audit(dest)[0] != "SAFE":        # the upstream file changed: keep only what passes the filter
            os.remove(dest)
            print(f"skip {item['file']}: no longer passes the safety audit")
            skipped += 1
            continue
        ok += 1
    print(f"{ok} scripts in {d}/scripts, {skipped} skipped")


def measure(d, write=True):
    """(loaded, total, failures) for the corpus in d; None if it isn't there."""
    sd = os.path.join(d, "scripts")
    if not os.path.isdir(sd):
        return None
    items = [x for x in json.load(open(MANIFEST)) if os.path.exists(os.path.join(sd, x["file"]))]
    env = dict(os.environ, PYTHONPATH=ROOT)

    def check(x):
        p = subprocess.run([sys.executable, "-m", "bunnyhotkey", "--validate", "--console",
                            os.path.join(sd, x["file"])], capture_output=True, text=True, timeout=60, env=env)
        err = (p.stderr or p.stdout).strip()
        m = re.search(r"\((\d+)\) : ==> (.*)", err)
        return x, p.returncode == 0 and not p.stdout.strip(), (f"line {m[1]}: {m[2]}" if m else err[:120])

    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        results = list(pool.map(check, items))
    fails = [(x, e) for x, ok, e in results if not ok]
    loaded, total = len(results) - len(fails), len(results)
    if write:
        p = os.path.join(ROOT, "docs", "parity.json")
        data = json.load(open(p, encoding="utf-8"))
        data["v1corpus"] = {"loaded": loaded, "total": total}
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        repos = sorted({x["source"].split(" : ")[0] for x in items})
        lines = ["# AutoHotkey v1 script corpus", "",
                 f"**{loaded} of {total}** public AutoHotkey v1 scripts load and compile in BHK's v1 frontend "
                 "(`bhk --validate`: continuation sections, translation, parsing, compilation; the scripts "
                 "aren't run).", "",
                 "The corpus holds the v1 scripts from these repositories that pass a conservative safety "
                 "filter (`tools/v1_corpus_audit.py`: no process launching, file writes, registry, network, "
                 "clipboard, native memory, window control, dynamic code, `#Include` or input outside "
                 "hotkeys), so it is mostly libraries, functions, classes and hotkey scripts:", ""]
        lines += [f"- {r}" for r in repos]
        lines += ["", "Rebuild and measure with `python3 tools/v1_corpus.py fetch` and "
                  "`python3 tools/v1_corpus.py measure`; the scripts aren't stored here because their "
                  "licences vary (`tests/v1corpus/manifest.json` lists each source).", "",
                  "## Scripts that don't load", "",
                  "| Script | Error |", "|---|---|"]
        lines += [f"| {x['source'].split(' : ')[0].rsplit('/', 1)[-1]}: `{x['source'].split(' : ')[1]}` | "
                  f"{e.replace('|', '/')} |" for x, e in sorted(fails, key=lambda f: f[0]["file"])]
        with open(os.path.join(ROOT, "docs", "V1_CORPUS.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return loaded, total, fails


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "measure"
    d = corpus_dir(sys.argv[2] if len(sys.argv) > 2 else None)
    if cmd == "fetch":
        fetch(d)
    else:
        r = measure(d)
        if r is None:
            sys.exit(f"no corpus in {d} (run: python3 tools/v1_corpus.py fetch)")
        print(f"{r[0]} of {r[1]} load")
        for x, e in r[2]:
            print(f"FAIL {x['file']}: {e}")
