"""Draws assets/parity.svg - BHK's parity with AutoHotkey v2 per area (numbers from docs/PARITY.md)."""
import os
from xml.sax.saxutils import escape

AREAS = [  # (area, percent, note)
    ("Language syntax & semantics (v2.0)", 99, "all v2.0 constructs; regression suite"),
    ("Real-world v2 scripts that load", 99, "243 of 246 from 7 repos"),
    ("Strings / RegEx / Math / Dates", 100, "45 of 45 functions"),
    ("Keyboard & mouse functions", 99, "Send, Click, Hotkey(), InputHook..."),
    ("Process / Run / System", 96, "Run, Process*, Env*, Sound*, Reg*"),
    ("Files / Dirs / INI", 95, "Drive* metadata partial"),
    ("Window functions (Win*)", 95, "EWMH; WinGetText/regions partial"),
    ("Tray icon & menu", 95, "XFCE live; Cinnamon via XApp monitor"),
    ("Hotkeys & hotstrings (X11)", 90, "bare modifiers not suppressible"),
    ("All built-in functions", 88, "271 full, 63 partial, 11 missing"),
    ("Gui", 65, "15 of 23 control types"),
    ("Win32 controls (Control*, Edit*)", 61, "no Win32 controls on Linux"),
    ("COM / ActiveX", 0, "Windows-only"),
    ("Wayland input", 0, "dropped for now"),
]


def color(p):
    return "#2da44e" if p >= 90 else "#d4a72c" if p >= 60 else "#cf222e"


def main():
    row, top, label_w, bar_w = 30, 74, 300, 330
    h = top + row * len(AREAS) + 54
    w = label_w + bar_w + 290
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
           'font-family="Segoe UI, Helvetica, Arial, sans-serif">',
           f'<rect width="{w}" height="{h}" rx="12" fill="#ffffff" stroke="#d0d7de"/>',
           '<text x="20" y="34" font-size="20" font-weight="700" fill="#1f2328">Bunny Hot Key - parity with AutoHotkey v2</text>',
           '<text x="20" y="56" font-size="12.5" fill="#59636e">Share of AutoHotkey v2.0.31 behaviour reproduced. '
           'Full = 1, partial = 0.5. Details: docs/PARITY.md</text>']
    for i, (area, pct, note) in enumerate(AREAS):
        y = top + i * row
        out.append(f'<text x="20" y="{y + 15}" font-size="13" fill="#1f2328">{escape(area)}</text>')
        out.append(f'<rect x="{label_w}" y="{y + 3}" width="{bar_w}" height="16" rx="4" fill="#eef1f4"/>')
        if pct:
            out.append(f'<rect x="{label_w}" y="{y + 3}" width="{bar_w * pct / 100:.1f}" height="16" rx="4" fill="{color(pct)}"/>')
        out.append(f'<text x="{label_w + bar_w + 10}" y="{y + 15}" font-size="13" font-weight="700" fill="{color(pct)}">{pct}%</text>')
        out.append(f'<text x="{label_w + bar_w + 55}" y="{y + 15}" font-size="11.5" fill="#59636e">{escape(note)}</text>')
    ly = h - 26
    for j, (txt, c) in enumerate((("90%+ complete", "#2da44e"), ("partial: 60-89%", "#d4a72c"), ("missing / left to do", "#cf222e"))):
        x = 20 + j * 190
        out.append(f'<rect x="{x}" y="{ly - 11}" width="12" height="12" rx="3" fill="{c}"/>')
        out.append(f'<text x="{x + 18}" y="{ly}" font-size="12" fill="#1f2328">{txt}</text>')
    out.append("</svg>")
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "parity.svg")
    with open(path, "w") as fh:
        fh.write("\n".join(out))
    print(path)


if __name__ == "__main__":
    main()
