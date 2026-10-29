#!/usr/bin/env python3
"""How much of the Win32 API that real scripts call through DllCall BHK emulates.

    python3 tools/dllcall_coverage.py CORPUS_DIR [-v]

CORPUS_DIR is a checkout made by tests/validate_corpus.sh (the 337-script v2 corpus).  Every
DllCall("dll\\Function") / DllCall("Function") with a literal name is counted once per script that uses
it ("uses"); calls into Linux .so files and by address aren't Win32 and aren't counted.  The result goes
into docs/parity.json ("dllcall") for the chart.
"""
import collections
import importlib
import json
import os
import pkgutil
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def emulated():
    from bunnyhotkey.loader import Program
    Program("*", [], {"backend": "null"})
    import bunnyhotkey.lib as lib
    for m in pkgutil.iter_modules(lib.__path__):
        if "helper" not in m.name:
            try:
                importlib.import_module("bunnyhotkey.lib." + m.name)
            except Exception:
                pass
    from bunnyhotkey.lib import dllcall
    return set(dllcall.EMU)


def scan(root):
    uses = collections.defaultdict(set)
    rx = re.compile(r"DllCall\(\s*[\"']([^\"']+)[\"']", re.I)
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d != ".git"]
        for f in fns:
            if not f.lower().endswith(".ahk"):
                continue
            path = os.path.join(dp, f)
            text = open(path, encoding="utf-8", errors="replace").read()
            for m in rx.finditer(text):
                lib, _, name = m.group(1).replace("/", "\\").rpartition("\\")
                if ".so" in lib.lower() or not re.fullmatch(r"[A-Za-z_]\w*", name):
                    continue
                uses[name.lower()].add(path)
    return uses


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        sys.exit(__doc__)
    emu = emulated()
    uses = scan(args[0])
    ok = lambda n: n in emu or n.rstrip("w").rstrip("a") in emu    # noqa: E731
    total = sum(len(v) for v in uses.values())
    covered = sum(len(v) for k, v in uses.items() if ok(k))
    print(f"{covered} of {total} DllCall uses ({round(100 * covered / total)}%), "
          f"{sum(ok(k) for k in uses)} of {len(uses)} distinct functions")
    if "-v" in sys.argv:
        for k in sorted(uses, key=lambda k: -len(uses[k]))[:60]:
            if not ok(k):
                print(f"  missing {k}: {len(uses[k])} scripts")
    p = os.path.join(ROOT, "docs", "parity.json")
    data = json.load(open(p, encoding="utf-8"))
    data["dllcall"] = {"covered": covered, "total": total}
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
