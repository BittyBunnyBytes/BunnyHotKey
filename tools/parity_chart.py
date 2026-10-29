"""Recreate the parity visual: python3 tools/parity_chart.py

1. Measures every AutoHotkey built-in (tools/ahk_builtins.txt) against BHK's implementation.
2. Reads docs/parity.json (areas, notes, hand-scored percentages, the "missing" list).
3. Writes assets/parity.svg and refreshes the generated blocks in README.md and docs/PARITY.md
   (between <!-- parity:...:start --> and <!-- parity:...:end --> markers).

To update: edit docs/parity.json (or improve BHK), then rerun this script.
"""
from __future__ import annotations

import inspect
import json
import os
import re
import sys
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

GROUPS = {
    "strings": lambda n: n in {
        "InStr", "SubStr", "StrLen", "StrLower", "StrUpper", "StrTitle", "StrReplace", "StrSplit", "Trim", "LTrim",
        "RTrim", "StrCompare", "Chr", "Ord", "Format", "FormatTime", "RegExMatch", "RegExReplace", "Sort", "Abs", "Ceil",
        "Floor", "Round", "Mod", "Max", "Min", "Sqrt", "Exp", "Log", "Ln", "Sin", "Cos", "Tan", "ASin", "ACos", "ATan",
        "Random", "DateAdd", "DateDiff", "VerCompare", "StrPtr", "StrGet", "StrPut", "NumGet", "NumPut"},
    "input": lambda n: n.startswith((
        "Send", "Click", "Mouse", "GetKey", "KeyWait", "SetCapsLock", "SetNumLock", "SetScrollLock", "BlockInput", "Hotkey",
        "Hotstring", "HotIf", "InputHook", "SetKeyDelay", "SetMouseDelay", "SetDefaultMouseSpeed", "CoordMode",
        "CaretGetPos")),
    "process": lambda n: n.startswith(("Run", "Process", "Env", "Shutdown", "Sound", "SysGet", "Monitor", "Download",
                                       "Reg", "Clip", "OnClipboard")),
    "files": lambda n: n.startswith(("File", "Dir", "Ini", "SplitPath", "Drive")),
    "window": lambda n: n.startswith(("Win", "Group")),
    "controls": lambda n: n.startswith(("Control", "Edit", "ListView", "StatusBar", "MenuSelect", "PostMessage",
                                        "SendMessage")),
    "all": lambda n: True,
}


def classify():
    """{name: 'full' | 'partial' | 'missing'} for every AutoHotkey built-in."""
    from bunnyhotkey.lib import EXPORTS
    from bunnyhotkey.loader import Program
    prog = Program("*", [], {"backend": "null"})
    names = [l.strip() for l in open(os.path.join(ROOT, "tools", "ahk_builtins.txt")) if l.strip() and not l.startswith("#")]
    funcs = {n.lower(): f for n, f, _ in EXPORTS}
    classes = set(prog.rt.globals)
    result = {}
    for n in names:
        k = n.lower()
        f = funcs.get(k)
        if f is None and k not in classes:
            result[n] = "missing"
            continue
        src = inspect.getsource(f) if f else ""
        if k == "dllcall":
            result[n] = "partial"
        elif "Windows-only" in src or "not supported by Bunny" in src or "not available in Bunny" in src:
            result[n] = "missing"
        else:
            body = [l for l in src.splitlines()[1:] if l.strip() and not l.strip().startswith(('"""', "#"))]
            stub = len(body) <= 2 and any(t in src for t in ('return ""', "return 0", "return 1", "AhkArray(None, [])"))
            result[n] = "partial" if stub else "full"
    return result


def measure(spec, cls, data):
    kind, _, group = spec.partition(":")
    if kind == "corpus":
        c = data["corpus"]
        return round(100 * c["loaded"] / c["total"]), dict(c)
    pred = GROUPS[group]
    st = [s for n, s in cls.items() if pred(n)]
    full, part, miss = st.count("full"), st.count("partial"), st.count("missing")
    pct = round(100 * (full + part / 2) / len(st)) if st else 0
    return pct, {"full": full, "partial": part, "missing": miss, "count": len(st)}


def color(p):
    return "#2da44e" if p >= 90 else "#d4a72c" if p >= 60 else "#cf222e"


def render(data, rows):
    row, top, label_w, bar_w = 30, 74, 300, 330
    h = top + row * len(rows) + 54
    w = label_w + bar_w + 290
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
           'font-family="Segoe UI, Helvetica, Arial, sans-serif">',
           f'<rect width="{w}" height="{h}" rx="12" fill="#ffffff" stroke="#d0d7de"/>',
           f'<text x="20" y="34" font-size="20" font-weight="700" fill="#1f2328">{escape(data["title"])}</text>',
           f'<text x="20" y="56" font-size="12.5" fill="#59636e">{escape(data["subtitle"])}</text>']
    for i, (area, pct, note) in enumerate(rows):
        y = top + i * row
        out.append(f'<text x="20" y="{y + 15}" font-size="13" fill="#1f2328">{escape(area)}</text>')
        out.append(f'<rect x="{label_w}" y="{y + 3}" width="{bar_w}" height="16" rx="4" fill="#eef1f4"/>')
        if pct:
            out.append(f'<rect x="{label_w}" y="{y + 3}" width="{bar_w * pct / 100:.1f}" height="16" rx="4" fill="{color(pct)}"/>')
        out.append(f'<text x="{label_w + bar_w + 10}" y="{y + 15}" font-size="13" font-weight="700" fill="{color(pct)}">{pct}%</text>')
        out.append(f'<text x="{label_w + bar_w + 55}" y="{y + 15}" font-size="11.5" fill="#59636e">{escape(note)}</text>')
    ly = h - 26
    for j, (txt, c) in enumerate((("90%+ complete", "#2da44e"), ("partial: 60-89%", "#d4a72c"),
                                  ("missing / left to do", "#cf222e"))):
        x = 20 + j * 190
        out.append(f'<rect x="{x}" y="{ly - 11}" width="12" height="12" rx="3" fill="{c}"/>')
        out.append(f'<text x="{x + 18}" y="{ly}" font-size="12" fill="#1f2328">{txt}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def replace_block(path, name, text):
    p = os.path.join(ROOT, path)
    s = open(p, encoding="utf-8").read()
    start, end = f"<!-- parity:{name}:start -->", f"<!-- parity:{name}:end -->"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pattern.search(s):
        print(f"warning: no {start} marker in {path}")
        return
    s = pattern.sub(lambda m: f"{start}\n{text}\n{end}", s)
    open(p, "w", encoding="utf-8").write(s)


def main():
    data = json.load(open(os.path.join(ROOT, "docs", "parity.json"), encoding="utf-8"))
    cls = classify()
    rows = []
    values = {}
    for a in data["areas"]:
        if "measure" in a:
            pct, vals = measure(a["measure"], cls, data)
        else:
            pct, vals = a["percent"], {}
        values[a["area"]] = pct
        rows.append((a["area"], pct, a.get("note", "").format(**vals)))
    with open(os.path.join(ROOT, "assets", "parity.svg"), "w", encoding="utf-8") as fh:
        fh.write(render(data, rows))
    _, allv = measure("builtins:all", cls, data)
    lang = values.get("Language syntax & semantics (v2.0)", 0)
    api = values.get("All built-in functions", 0)
    summary = (f"**In short:** the AutoHotkey v2 *language* is essentially complete ({lang}%), and\n"
               f"**{api}% of its built-in function API** is reproduced ({allv['full']} full, {allv['partial']} partial, "
               f"{allv['missing']} missing).\n\n**Missing or left to do:**\n"
               + "\n".join(f"- {m}" for m in data["missing"])
               + "\n\nThe full breakdown is in [docs/PARITY.md](docs/PARITY.md).")
    replace_block("README.md", "summary", summary)
    replace_block("docs/PARITY.md", "counts",
                  f"Result: **{allv['full']} full, {allv['partial']} partial, {allv['missing']} missing ({api}%)** "
                  f"of {allv['count']} built-ins.")
    print(f"assets/parity.svg updated: built-ins {allv['full']}/{allv['partial']}/{allv['missing']} of {allv['count']} ({api}%)")


if __name__ == "__main__":
    main()
