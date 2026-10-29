"""Static safety audit of an AHK v1 corpus. Conservative allowlist-by-exclusion:
a script is SAFE only if, after stripping comments, it has none of the risky tokens below,
no #Include, is not v2, and does not simulate input outside hotkey bodies.
Usage: python3 -I audit_v1.py CORPUS_DIR OUT_JSON
"""
import hashlib, json, os, re, sys

RISKY = {
    "process": r"Run|RunWait|RunAs|Shutdown|Process|ComObjCreate|ComObjGet|ComObjActive|ComObject|ComObjConnect|ComCall",
    "memory/native": r"DllCall|RegisterCallback|CallbackCreate|NumPut|NumGet|StrPut|VarSetCapacity|Buffer|LoadLibrary|ObjFromPtr",
    "file write/delete": r"FileDelete|FileRecycle|FileRecycleEmpty|FileMove|FileMoveDir|FileCopy|FileCopyDir|FileRemoveDir|"
                         r"FileCreateDir|DirCreate|DirDelete|DirMove|DirCopy|FileAppend|FileOpen|FileSetAttrib|FileSetTime|"
                         r"FileCreateShortcut|FileInstall|IniWrite|IniDelete|FileRead|FileReadLine|IniRead|Loop\s*,\s*(Files|Read|Parse\s*,\s*%?A_LoopReadLine)",
    "registry": r"RegWrite|RegDelete|RegRead|Loop\s*,\s*Reg",
    "network": r"URLDownloadToFile|Download|WinHttp|XMLHTTP|MSXML2|InetGet|ServerXMLHTTP",
    "clipboard": r"Clipboard|ClipboardAll|ClipWait|OnClipboardChange",
    "system": r"SoundSet|SoundSetWaveVolume|SoundBeep|SoundPlay|BlockInput|PostMessage|SendMessage|WinKill|WinClose|WinHide|"
              r"WinSet|WinMove|WinMinimizeAll|Control|ControlSend|ControlClick|Drive|DriveEject|SetCapsLockState|"
              r"SetNumLockState|SetScrollLockState|EnvSet|EnvUpdate|SysGet|Hotkey|OnMessage|Reload|Critical|"
              r"PixelSearch|ImageSearch|Gdip_|Shell\.|WScript|PowerShell|cmd\.exe|\.exe\b|\.bat\b|\.vbs\b|\.ps1\b",
    "dynamic code": r"Func\s*\(|%\w+%\s*\(|\.Call\s*\(|ObjBindMethod|BoundFunc|Exec\s*\(|Eval\s*\(",
}
RISKY_RE = {k: re.compile(r"(?<![\w.$#])(" + v + r")(?![\w])", re.I) for k, v in RISKY.items()}
INPUT_RE = re.compile(r"^\s*(Send\w*|Click|MouseMove|MouseClick\w*|MouseClickDrag|SendRaw|SendInput|SendPlay|SendEvent)\b", re.I | re.M)
HOTKEY_RE = re.compile(r"^\s*[^\s;,].*?::", re.M)
V1_HINT = re.compile(r"^\s*(#NoEnv|#SingleInstance\s*,?\s*Force|SendMode\s*,?\s*Input|SetWorkingDir\s*,?\s*%A_ScriptDir%|"
                     r"\w+\s*,\s*\S|\w+\s*=\s*[^=]|#IfWin\w+|return\s*$)", re.I | re.M)


def strip_comments(src):
    src = re.sub(r"(?ms)^\s*/\*.*?^\s*\*/", "", src)
    return re.sub(r"(?m)(^|\s);.*$", "", src)


def audit(path):
    raw = open(path, "rb").read()
    try:
        txt = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "not utf-8", None
    if "\0" in txt or len(txt) > 200_000:
        return "binary/huge", None
    code = strip_comments(txt)
    if re.search(r"#Requires\s+AutoHotkey\s+v?2", code, re.I):
        return "v2", None
    if re.search(r"(?im)^\s*#Include", code):
        return "#Include", None
    for name, rx in RISKY_RE.items():
        m = rx.search(code)
        if m:
            return name + ": " + m.group(1), None
    hk = HOTKEY_RE.search(code)
    auto = code[:hk.start()] if hk else code
    if INPUT_RE.search(auto):
        return "input outside hotkeys", None
    if re.search(r"(?im)^\s*SetTimer", code) and INPUT_RE.search(code):
        return "timer + input", None
    if not V1_HINT.search(code) and not hk:
        return "no v1 markers", None
    if not code.strip():
        return "empty", None
    return "SAFE", hashlib.sha256(code.encode()).hexdigest()


def main():
    root, out = sys.argv[1], sys.argv[2]
    safe, reasons, seen = [], {}, set()
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d != ".git"]
        for f in fns:
            if not f.lower().endswith(".ahk"):
                continue
            p = os.path.join(dp, f)
            verdict, h = audit(p)
            key = verdict.split(":")[0]
            if verdict == "SAFE" and h in seen:
                key = "duplicate"
            reasons[key] = reasons.get(key, 0) + 1
            if key == "SAFE":
                seen.add(h)
                safe.append(os.path.relpath(p, root))
    json.dump({"safe": sorted(safe), "reasons": reasons}, open(out, "w"), indent=1)
    for k, v in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"{v:6} {k}")


if __name__ == "__main__":
    main()
