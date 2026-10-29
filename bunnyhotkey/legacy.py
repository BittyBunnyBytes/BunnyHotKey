"""AutoHotkey v1 frontend: v1 source -> BHK's v2 dialect plus the __v1_* runtime library (lib/v1.py).

The v1 script is read with v1 line rules (literal command text, v1 continuation
sections), then translated line by line.  All of the script's global code -
auto-execute section, hotkey bodies and labels - stays in one global label
stream, exactly like v1: a hotkey becomes ``key::__v1_gosub("label")`` and its
body a label, so Gosub, Goto, fall-through and label-based timers/menus/Gui
events behave as they do in v1.  Commands become calls to __v1_<Command>
functions; v1-only expression syntax is rewritten by `Expr`.
"""
import re

from .errors import AhkSyntaxError
from .lexer import LogicalLine, classify_hot_line

ESC = "`"

# ---------------------------------------------------------------- command table
# Argument kinds: o = output variable (passed as a VarRef; also used for in/out
# variables), i = input variable name, t = text (%var% derefs / "% expr"),
# n = number (an expression unless it contains %var% derefs).  The last
# parameter absorbs any further commas, as in v1.
COMMANDS = {
    'autotrim': 't', 'blockinput': 't', 'click': 't', 'clipwait': 'nn',
    'control': 'ttttttt', 'controlclick': 'ttttnttt', 'controlfocus': 'ttttt',
    'controlget': 'ottttttt', 'controlgetfocus': 'otttt', 'controlgetpos': 'oooottttt',
    'controlgettext': 'ottttt', 'controlmove': 'tnnnntttt', 'controlsend': 'tttttt',
    'controlsendraw': 'tttttt', 'controlsettext': 'tttttt', 'coordmode': 'tt', 'critical': 't',
    'detecthiddentext': 't', 'detecthiddenwindows': 't', 'drive': 'ttt', 'driveget': 'ott',
    'drivespacefree': 'ot', 'edit': '', 'envadd': 'ont', 'envdiv': 'on', 'envget': 'ot',
    'envmult': 'on', 'envset': 'tt', 'envsub': 'ont', 'envupdate': '', 'exitapp': 'n',
    'fileappend': 'ttt', 'filecopy': 'ttn', 'filecopydir': 'ttn', 'filecreatedir': 't',
    'filecreateshortcut': 'tttttttnn', 'filedelete': 't', 'fileencoding': 't',
    'filegetattrib': 'ot', 'filegetshortcut': 'tooooooo', 'filegetsize': 'ott',
    'filegettime': 'ott', 'filegetversion': 'ot', 'fileinstall': 'ttn', 'filemove': 'ttn',
    'filemovedir': 'ttt', 'fileread': 'ot', 'filereadline': 'otn', 'filerecycle': 't',
    'filerecycleempty': 't', 'fileremovedir': 'tn', 'fileselectfile': 'otttt',
    'fileselectfolder': 'ottt', 'filesetattrib': 'ttnn', 'filesettime': 'tttnn',
    'formattime': 'ott', 'getkeystate': 'ott', 'groupactivate': 'tt', 'groupadd': 'tttttt',
    'groupclose': 'tt', 'groupdeactivate': 'tt', 'gui': 'tttt', 'guicontrol': 'ttt',
    'guicontrolget': 'ottt', 'hotkey': 'ttt', 'imagesearch': 'oonnnnt', 'inidelete': 'ttt',
    'iniread': 'otttt', 'iniwrite': 'tttt', 'input': 'ottt', 'inputbox': 'otttnnnntnt',
    'keyhistory': '', 'keywait': 'tt', 'listhotkeys': '', 'listlines': 't', 'listvars': '',
    'menu': 'tttttt', 'mouseclick': 'tnnnntt', 'mouseclickdrag': 'tnnnnnt',
    'mousegetpos': 'oooon', 'mousemove': 'nnnt', 'msgbox': 'tttn', 'onexit': 'tt',
    'outputdebug': 't', 'pause': 'tn', 'pixelgetcolor': 'onnt', 'pixelsearch': 'oonnnnnnt',
    'postmessage': 'nnnttttt', 'process': 'ttt', 'progress': 'ttttt', 'random': 'onn',
    'regdelete': 'ttt', 'regread': 'otttt', 'regwrite': 'ttttt', 'reload': '', 'run': 'ttto',
    'runas': 'ttt', 'runwait': 'ttto', 'send': 't', 'sendevent': 't', 'sendinput': 't',
    'sendlevel': 'n', 'sendmessage': 'nnntttttn', 'sendmode': 't', 'sendplay': 't',
    'sendraw': 't', 'setbatchlines': 't', 'setcapslockstate': 't', 'setcontroldelay': 'n',
    'setdefaultmousespeed': 'n', 'setenv': 'ot', 'setformat': 'tt', 'setkeydelay': 'nnt',
    'setmousedelay': 'nt', 'setnumlockstate': 't', 'setregview': 't', 'setscrolllockstate': 't',
    'setstorecapslockmode': 't', 'settimer': 'ttn', 'settitlematchmode': 't', 'setwindelay': 'n',
    'setworkingdir': 't', 'shutdown': 'n', 'sleep': 'n', 'sort': 'ot', 'soundbeep': 'nn',
    'soundget': 'ottt', 'soundgetwavevolume': 'on', 'soundplay': 'tt', 'soundset': 'tttt',
    'soundsetwavevolume': 'tn', 'splashimage': 'tttttt', 'splashtextoff': '',
    'splashtexton': 'nntt', 'splitpath': 'iooooo', 'statusbargettext': 'ontttt',
    'statusbarwait': 'tnnttntt', 'stringcasesense': 't', 'stringgetpos': 'oittn',
    'stringleft': 'oin', 'stringlen': 'oi', 'stringlower': 'oit', 'stringmid': 'oinnt',
    'stringreplace': 'oittt', 'stringright': 'oin', 'stringsplit': 'oitt', 'stringtrimleft': 'oin',
    'stringtrimright': 'oin', 'stringupper': 'oit', 'suspend': 't', 'sysget': 'ott',
    'thread': 'tnn', 'tooltip': 'tnnn', 'transform': 'ottt', 'traytip': 'ttnn',
    'urldownloadtofile': 'tt', 'winactivate': 'tttt', 'winactivatebottom': 'tttt',
    'winclose': 'ttntt', 'winget': 'ottttt', 'wingetactivestats': 'ooooo',
    'wingetactivetitle': 'o', 'wingetclass': 'otttt', 'wingetpos': 'oooottttt',
    'wingettext': 'otttt', 'wingettitle': 'otttt', 'winhide': 'tttt', 'winkill': 'ttntt',
    'winmaximize': 'tttt', 'winmenuselectitem': 'ttttttttttt', 'winminimize': 'tttt',
    'winminimizeall': '', 'winminimizeallundo': '', 'winmove': 'ttnnnntt', 'winrestore': 'tttt',
    'winset': 'tttttt', 'winsettitle': 'ttttt', 'winshow': 'tttt', 'winwait': 'ttntt',
    'winwaitactive': 'ttntt', 'winwaitclose': 'ttntt', 'winwaitnotactive': 'ttntt',
    # Control flow and legacy If commands handled by the translator itself.
    'gosub': 't', 'goto': 't', 'ifequal': 'it', 'ifnotequal': 'it', 'ifless': 'it',
    'iflessorequal': 'it', 'ifgreater': 'it', 'ifgreaterorequal': 'it', 'ifinstring': 'it',
    'ifnotinstring': 'it', 'ifexist': 't', 'ifnotexist': 't', 'ifwinactive': 'tttt',
    'ifwinnotactive': 'tttt', 'ifwinexist': 'tttt', 'ifwinnotexist': 'tttt', 'ifmsgbox': 't',
}

# Built-in functions whose v1 behaviour differs: v1 name -> (v2 name, ByRef positions).
FUNCS = {
    'instr': ('__v1_InStr', ()), 'substr': ('__v1_SubStr', ()), 'strreplace': ('__v1_StrReplace', (3,)),
    'regexmatch': ('__v1_RegExMatch', (2,)), 'regexreplace': ('__v1_RegExReplace', (3,)),
    'strsplit': ('__v1_StrSplit', ()), 'func': ('__v1_Func', ()), 'isfunc': ('__v1_IsFunc', ()),
    'object': ('__v1_Object', ()), 'array': ('__v1_Array', ()), 'varsetcapacity': ('__v1_VarSetCapacity', (0,)),
    'numget': ('__v1_NumGet', (0,)), 'numput': ('__v1_NumPut', (1,)), 'strget': ('__v1_StrGet', (0,)),
    'strput': ('__v1_StrPut', (1,)), 'dllcall': ('__v1_DllCall', 'dll'), 'exception': ('__v1_Exception', ()),
    'comobjcreate': ('__v1_ComObjCreate', ()), 'comobjerror': ('__v1_ComObjError', ()),
    'comobjparameter': ('__v1_ComObject', ()), 'comobject': ('__v1_ComObject', ()),
    'comobjmissing': ('__v1_ComObjMissing', ()), 'comobjenwrap': ('ComObjFromPtr', ()),
    'comobjunwrap': ('ComObjValue', ()), 'asc': ('Ord', ()), 'onmessage': ('__v1_OnMessage', ()),
    'registercallback': ('__v1_RegisterCallback', ()), 'isbyref': ('__v1_IsByRef', (0,)),
    'getkeystate': ('__v1_GetKeyState', ()), 'isobject': ('__v1_IsObject', ()),
    'objinsert': ('__v1_ObjInsert', ()), 'objinsertat': ('__v1_ObjInsertAt', ()), 'objpush': ('__v1_ObjPush', ()),
    'objpop': ('__v1_ObjPop', ()), 'objremove': ('__v1_ObjRemove', ()), 'objremoveat': ('__v1_ObjRemoveAt', ()),
    'objdelete': ('__v1_ObjDelete', ()), 'objminindex': ('__v1_ObjMinIndex', ()),
    'objmaxindex': ('__v1_ObjMaxIndex', ()), 'objlength': ('__v1_ObjLength', ()), 'objcount': ('__v1_ObjCount', ()),
    'objhaskey': ('__v1_ObjHasKey', ()), 'objclone': ('__v1_ObjClone', ()), 'objnewenum': ('__v1_ObjNewEnum', ()),
    'objrawset': ('__v1_ObjRawSet', ()), 'objrawget': ('__v1_ObjRawGet', ()), 'objgetcapacity': ('__v1_ObjGetCapacity', ()),
    'objsetcapacity': ('__v1_ObjSetCapacity', ()), 'objgetaddress': ('__v1_ObjGetAddress', ()),
    'objbindmethod': ('__v1_ObjBindMethod', ()), 'onexit': ('__v1_OnExitFunc', ()),
    'onclipboardchange': ('__v1_OnClipboardChange', ()), 'hotstring': ('__v1_Hotstring', ()),
    'trim': ('__v1_Trim', ()), 'ltrim': ('__v1_LTrim', ()), 'rtrim': ('__v1_RTrim', ()),
    'round': ('__v1_Round', ()), 'mod': ('__v1_Mod', ()), 'ln': ('__v1_Ln', ()), 'log': ('__v1_Log', ()),
    'sqrt': ('__v1_Sqrt', ()), 'abs': ('__v1_Abs', ()), 'floor': ('__v1_Floor', ()), 'ceil': ('__v1_Ceil', ()),
    'exp': ('__v1_Exp', ()), 'sin': ('__v1_Sin', ()), 'cos': ('__v1_Cos', ()), 'tan': ('__v1_Tan', ()),
    'asin': ('__v1_ASin', ()), 'acos': ('__v1_ACos', ()), 'atan': ('__v1_ATan', ()), 'chr': ('__v1_Chr', ()),
    'strlen': ('__v1_StrLen', ()), 'fileexist': ('__v1_FileExist', ()), 'winexist': ('__v1_WinExist', ()),
    'winactive': ('__v1_WinActive', ()), 'format': ('__v1_Format', ()), 'max': ('__v1_Max', ()),
    'min': ('__v1_Min', ()), 'fileopen': ('__v1_FileOpen', ()), 'islabel': ('__v1_IsLabel', ()),
    'loadpicture': ('__v1_LoadPicture', (2,)), 'menugethandle': ('__v1_MenuGetHandle', ()),
    'menugetname': ('__v1_MenuGetName', ()), 'lv_add': ('__v1_LV_Add', ()), 'lv_insert': ('__v1_LV_Insert', ()),
    'lv_modify': ('__v1_LV_Modify', ()), 'lv_delete': ('__v1_LV_Delete', ()), 'lv_getcount': ('__v1_LV_GetCount', ()),
    'lv_getnext': ('__v1_LV_GetNext', ()), 'lv_gettext': ('__v1_LV_GetText', (0,)),
    'lv_modifycol': ('__v1_LV_ModifyCol', ()), 'lv_insertcol': ('__v1_LV_InsertCol', ()),
    'lv_deletecol': ('__v1_LV_DeleteCol', ()), 'lv_setimagelist': ('__v1_LV_SetImageList', ()),
    'tv_add': ('__v1_TV_Add', ()), 'tv_modify': ('__v1_TV_Modify', ()), 'tv_delete': ('__v1_TV_Delete', ()),
    'tv_getselection': ('__v1_TV_GetSelection', ()), 'tv_getcount': ('__v1_TV_GetCount', ()),
    'tv_getparent': ('__v1_TV_GetParent', ()), 'tv_getchild': ('__v1_TV_GetChild', ()),
    'tv_getprev': ('__v1_TV_GetPrev', ()), 'tv_getnext': ('__v1_TV_GetNext', ()),
    'tv_gettext': ('__v1_TV_GetText', (0,)), 'tv_get': ('__v1_TV_Get', ()), 'tv_setimagelist': ('__v1_TV_SetImageList', ()),
    'sb_settext': ('__v1_SB_SetText', ()), 'sb_setparts': ('__v1_SB_SetParts', ()), 'sb_seticon': ('__v1_SB_SetIcon', ()),
    'il_create': ('IL_Create', ()), 'il_add': ('IL_Add', ()), 'il_destroy': ('IL_Destroy', ()),
    'getkeyname': ('GetKeyName', ()), 'getkeyvk': ('GetKeyVK', ()), 'getkeysc': ('GetKeySC', ()),
    'comobjactive': ('__v1_ComObjActive', ()), 'comobjget': ('ComObjGet', ()), 'comobjconnect': ('ComObjConnect', ()),
    'comobjtype': ('ComObjType', ()), 'comobjvalue': ('ComObjValue', ()), 'comobjflags': ('ComObjFlags', ()),
    'comobjquery': ('ComObjQuery', ()), 'comobjarray': ('ComObjArray', ()),
}

# v1 variable names that are spelled differently in v2.
VARS = {
    'clipboard': 'A_Clipboard', 'clipboardall': 'ClipboardAll()', 'comspec': 'A_ComSpec',
    'programfiles': 'A_ProgramFiles', 'a_loopfilelongpath': 'A_LoopFileFullPath',
    'a_isunicode': '1',
}

V2_RESERVED = {"and", "or", "not", "is", "in", "contains", "as", "if", "else", "loop", "while", "for", "until",
               "try", "catch", "finally", "return", "break", "continue", "goto", "throw", "global", "local",
               "static", "class", "switch", "case", "default", "super", "unset", "this", "isset"}

TIME_UNITS = {'seconds', 'second', 's', 'minutes', 'minute', 'm', 'hours', 'hour', 'h', 'days', 'day', 'd'}

LEGACY_IF_OPS = ('<>', '!=', '>=', '<=', '=', '>', '<')

NAME = r'[\w#@$\u0080-￿]'


# ================================================================ line reader

def _strip_comment(s):
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == ESC:
            i += 2
            continue
        if c == ';' and (i == 0 or s[i - 1] in ' \t'):
            return s[:i].rstrip(' \t')
        i += 1
    return s


_CONT_START = re.compile(r'(,|\.(?!\w*\s*:=)|&&|\|\||and\b|or\b|\?|:(?!:)|\+(?!\+)|-(?!-)|\*|/|<|>|=|~|&|\||\^)', re.I)


def logical_lines(text, filename, ltrim_default=False):
    """v1 GetLine/LoadIncludedFile: comments, continuation sections and lines."""
    if text.startswith('﻿'):
        text = text[1:]
    raw = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    out = []
    i = 0
    n = len(raw)
    in_comment = False

    def code_line(j):
        """(text, next index) of the next non-comment line starting at j, or (None, n)."""
        nonlocal in_comment
        while j < n:
            s = raw[j].strip(' \t')
            j += 1
            if in_comment:
                if s.startswith('*/') or s.endswith('*/'):
                    in_comment = False
                    s = s[2:].strip() if s.startswith('*/') else ''
                    s = _strip_comment(s)
                    if s:
                        return s, j
                continue
            if s.startswith('/*'):
                if not (s.endswith('*/') and len(s) >= 4):
                    in_comment = True
                continue
            if s.startswith(';'):
                continue
            s = _strip_comment(s)
            if s:
                return s, j
        return None, n

    def section(buf, j):
        """Fold continuation sections that start at line j into buf."""
        while True:
            save = (j, in_comment)
            nxt, k = code_line_peek(j)
            if nxt is None or not nxt.startswith('(') or ')' in nxt[1:] or nxt.startswith('(:'):
                return buf, j
            opts = nxt[1:].split()
            join, ltrim, rtrim, comments, lit_pct, lit_comma, lit_esc = '\n', ltrim_default, True, False, False, False, False
            for opt in opts:
                lo = opt.lower()
                if lo.startswith('join'):
                    join = opt[4:].replace('`s', ' ').replace('`n', '\n').replace('`t', '\t').replace('`r', '\r')
                elif lo.startswith('ltrim'):
                    ltrim = lo != 'ltrim0'
                elif lo.startswith('rtrim'):
                    rtrim = lo != 'rtrim0'
                elif lo in ('c', 'com', 'comment', 'comments'):
                    comments = True
                elif opt == '%':
                    lit_pct = True
                elif opt == ',':
                    lit_comma = True
                elif opt == ESC:
                    lit_esc = True
            j = k
            content = []
            while True:
                if j >= n:
                    raise AhkSyntaxError('Missing ")"', filename, j)
                line = raw[j]
                j += 1
                st = line.lstrip(' \t')
                if st.startswith(')'):
                    tail = _strip_comment(st[1:].rstrip(' \t'))
                    break
                if comments:
                    if st.startswith(';'):
                        continue
                    line = _strip_comment(line)
                if ltrim:
                    line = line.lstrip(' \t')
                if rtrim:
                    line = line.rstrip(' \t')
                if lit_esc:
                    line = line.replace(ESC, ESC + ESC)
                if lit_pct:
                    line = line.replace('%', ESC + '%')
                if lit_comma:
                    line = line.replace(',', ESC + ',')
                content.append(line)
            buf = buf + join.join(content) + tail

    def code_line_peek(j):
        nonlocal in_comment
        save = in_comment
        r = code_line(j)
        in_comment = save
        return r

    while True:
        s, i2 = code_line(i)
        if s is None:
            break
        ln = i2
        i = i2
        buf, i = section(s, i)
        if not _special(buf):
            while True:
                nxt, k = code_line_peek(i)
                if nxt is None or _special(nxt) or nxt.startswith(('++', '--')) or not _CONT_START.match(nxt):
                    break
                if nxt.startswith(('{', '}')):
                    break
                code_line(i)   # consume (keeps /* */ state)
                i = k
                sep = '' if nxt.startswith(',') else ' '
                buf, i = section(buf + sep + nxt, i)
        out.append(LogicalLine(buf, ln, filename))
    return out


def _special(text):
    return text.startswith('#') or classify_hot_line(text) is not None or re.match(r'(?:[^\s,`]|`.)+:$', text) is not None


# ================================================================ detection

_CMD_RE = '|'.join(sorted((c for c in COMMANDS if c not in ('goto',)), key=len, reverse=True))
_V1_HINTS = re.compile(
    r'^(#(NoEnv|IfWin\w*|If\b|Persistent|MaxHotkeysPerInterval|CommentFlag|EscapeChar|AllowSameLineComments|MaxMem|'
    r'Delimiter|DerefChar|IfTimeout|KeyHistory|LTrim)'
    r'|(' + _CMD_RE + r')\s*,'
    r'|(' + _CMD_RE + r')\s+[^"\'(&\s][^"]*%\w+%'
    r'|(' + _CMD_RE + r')\s+(?![\w.]+\s*$)(?!.*\w(\.\w|\())[^"\'(&\d\s\-%][^"]*$'
    r'|' + NAME + r'+\s*=[^=>]'
    # `if x = 1`, `if x is Integer` and `catch TargetError` are valid v2 too, so only v1-only forms count.
    r'|if\s+[\w#@$]+\s*(<>|(not\s+)?(between|in|contains)\s|=\s*[^"\'\s(][^"\']*%\w+%'
    r'|is\s+(not\s+)?(digit|xdigit|alpha|upper|lower|alnum|space|time)\s*$)'
    r'|\w+\(.*\bByRef\s'
    r'|.*\bnew\s+\w+\()', re.I)
_V2_HINTS = re.compile(r'(=>|\bcatch\s+\w*\s*as\s|#HotIf\b|^\w+\s*\(\s*&|^(MsgBox|Send\w*|Sleep|ToolTip|Run)\()', re.I)


def detect_text(text, requested='auto'):
    required = None
    for line in text.splitlines():
        m = re.match(r'\s*#Requires\s+AutoHotkey\s+[<>=]*v?([12])', line, re.I)
        if m:
            required = m[1]
            break
    if requested != 'auto':
        if required and required != requested:
            raise AhkSyntaxError('Script version conflicts with --ahk-version.', '', 1)
        return requested
    if required:
        return required
    v1 = v2 = 0
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(';'):
            continue
        if _V1_HINTS.match(s):
            v1 += 1
        if _V2_HINTS.search(s):
            v2 += 1
        hot = classify_hot_line(s)
        if hot and hot[0] == 'hotkey' and hot[2].rstrip().endswith('{'):
            v2 += 1
    return '1' if v1 > v2 else '2'


# ================================================================ expressions

_TOKEN = re.compile(r'''
    (?P<ws>[ \t\n]+)
  | (?P<str>"(?:[^"]|"")*")
  | (?P<num>0[xX][0-9a-fA-F]+|(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)
  | (?P<name>(?:[\w#@$\u0080-￿]|%[^%\s]+%)+)
  | (?P<op>>>>=|<<=|>>=|//=|\*\*|//|\.=|:=|\+=|-=|\*=|/=|\|=|&=|\^=|<>|!=|==|<=|>=|&&|\|\||\+\+|--|<<|>>|~=|[-+*/!~&|^<>=?:.,()\[\]{}%])
''', re.X)


class Tok:
    __slots__ = ('k', 'v')

    def __init__(self, k, v):
        self.k, self.v = k, v

    def __repr__(self):
        return f'{self.k}:{self.v!r}'


def tokenize(s):
    toks = []
    i = 0
    while i < len(s):
        m = _TOKEN.match(s, i)
        if not m:
            toks.append(Tok('op', s[i]))
            i += 1
            continue
        k = m.lastgroup
        toks.append(Tok(k, m.group()))
        i = m.end()
    return toks


def _operand_end(t):
    return t is not None and (t.k in ('str', 'num', 'name') or t.v in (')', ']', '}', '++', '--')) and \
        not (t.k == 'name' and t.v.lower() in ('and', 'or', 'not', 'new', 'return'))


class Expr:
    """Rewrites a v1 expression as BHK v2 source."""

    def __init__(self, tr):
        self.tr = tr

    def __call__(self, s):
        toks = [t for t in tokenize(s)]
        return self.render(toks, 0, len(toks)).strip()

    def match(self, toks, i, end):
        """Index of the bracket closing toks[i]."""
        pairs = {'(': ')', '[': ']', '{': '}'}
        depth = 0
        for j in range(i, end):
            v = toks[j].v if toks[j].k == 'op' else None
            if v in pairs:
                depth += 1
            elif v in (')', ']', '}'):
                depth -= 1
                if depth == 0:
                    return j
        raise AhkSyntaxError('Missing closing bracket.', self.tr.file, self.tr.line, ''.join(t.v for t in toks))

    def split(self, toks, i, end):
        """Top-level comma-separated (start, end) ranges."""
        parts = []
        depth = 0
        start = i
        for j in range(i, end):
            t = toks[j]
            if t.k == 'op':
                if t.v in '([{':
                    depth += 1
                elif t.v in ')]}':
                    depth -= 1
                elif t.v == ',' and depth == 0:
                    parts.append((start, j))
                    start = j + 1
        parts.append((start, end))
        return parts

    def prev(self, toks, i):
        j = i - 1
        while j >= 0 and toks[j].k == 'ws':
            j -= 1
        return toks[j] if j >= 0 else None

    def nxt(self, toks, i, end):
        j = i + 1
        while j < end and toks[j].k == 'ws':
            j += 1
        return j

    def name(self, v, member=False):
        if member:
            return re.sub(r'[#@$]', lambda m: {'#': '_H_', '@': '_At_', '$': '_D_'}[m[0]], v)
        if '%' in v:
            parts = re.split(r'%([^%]+)%', v)
            out = []
            for k, p in enumerate(parts):
                if k % 2:
                    out.append('%' + self(p) + '%')
                elif p:
                    out.append(self.name(p, True))
            return ''.join(out)
        low = v.lower()
        if low in VARS:
            return VARS[low]
        if low.isdigit():
            return f'__v1_arg({low})'
        return self.name(v, True)

    def render(self, toks, i, end):
        out = []
        while i < end:
            t = toks[i]
            k, v = t.k, t.v
            if k == 'ws':
                out.append(' ' if '\n' in v else v)
                i += 1
                continue
            if k == 'str':
                body = v[1:-1].replace('""', ESC + '"').replace('\n', '`n')
                out.append('"' + body + '"')
                i += 1
                continue
            if k == 'num':
                p = self.prev(toks, i)
                if ('.' in v or 'e' in v.lower()) and not v.lower().startswith('0x') and not (p and p.v == '.'):
                    out.append('"' + v + '"')   # v1 keeps a literal float's text
                else:
                    out.append(v)
                i += 1
                continue
            if k == 'name':
                p = self.prev(toks, i)
                low = v.lower()
                j = self.nxt(toks, i, end)
                after = toks[j] if j < end else None
                member = p is not None and p.k == 'op' and p.v == '.' and not (i > 0 and toks[i - 1].k == 'ws')
                if low == 'new' and after is not None and after.k == 'name':
                    # new Class.Sub(args) -> Class.Sub(args)
                    j2 = j
                    cls = []
                    while j2 < end and (toks[j2].k == 'name' or toks[j2].v == '.'):
                        cls.append(toks[j2].v)
                        j2 += 1
                    clsname = ''.join(self.name(c, True) if c != '.' and '%' not in c else (c if c == '.' else self.name(c)) for c in cls)
                    if j2 < end and toks[j2].v == '(':
                        close = self.match(toks, j2, end)
                        out.append(clsname + '(' + self.args(toks, j2 + 1, close, ()) + ')')
                        i = close + 1
                    else:
                        out.append(clsname + '()')
                        i = j2
                    continue
                if member:
                    if self.tr.in_class and low == 'base' and False:
                        pass
                    out.append(self.name(v, True))
                    i += 1
                    continue
                if low == 'base' and self.tr.in_method and after is not None and after.v == '.':
                    out.append('super')
                    i += 1
                    continue
                if after is not None and after.v == '(' and j == i + 1 and low not in ('and', 'or', 'not', 'return'):
                    close = self.match(toks, j, end)
                    if v.startswith('%') and v.endswith('%') and v.count('%') == 2:
                        fn = '__v1_fn(' + self(v[1:-1]) + ')'
                        byref = ()
                    elif '%' in v:
                        fn = '__v1_fn(' + self.tr.literal(v.replace('%', '%')) + ')'
                        byref = ()
                    else:
                        fn, byref = self.tr.func_target(v)
                    out.append(fn + '(' + self.args(toks, j + 1, close, byref) + ')')
                    i = close + 1
                    continue
                out.append(self.name(v))
                i += 1
                continue
            # operators
            if v == '<>':
                out.append('!=')
                i += 1
                continue
            if v == '.' and i + 1 < end and toks[i + 1].v == '(':
                out.append('.Call')
                i += 1
                continue
            if v in ('++', '--') and _operand_end(self.prev(toks, i)) and self.prev(toks, i).v not in ('++', '--'):
                while out and out[-1].strip() == '':
                    out.pop()
                out.append(v)
                i += 1
                continue
            if v == ':=':
                j = self.nxt(toks, i, end)
                out.append(v)
                if j >= end or toks[j].v == ',':
                    out.append(' ""')
                i += 1
                continue
            if v == '{':
                close = self.match(toks, i, end)
                out.append(self.objlit(toks, i + 1, close))
                i = close + 1
                continue
            if v == '[' and not _operand_end(self.prev(toks, i)):
                close = self.match(toks, i, end)
                out.append('__v1_Array(' + self.args(toks, i + 1, close, ()) + ')')
                i = close + 1
                continue
            if v in ('(', '['):
                close = self.match(toks, i, end)
                out.append(v + self.render(toks, i + 1, close) + toks[close].v)
                i = close + 1
                continue
            if v == '&' and not _operand_end(self.prev(toks, i)):
                j = self.nxt(toks, i, end)
                if j < end and toks[j].k == 'name':
                    out.append('__v1_addr(&' + self.name(toks[j].v) + ')')
                    i = j + 1
                    continue
            if v == '*' and not _operand_end(self.prev(toks, i)):
                j = self.nxt(toks, i, end)
                if j < end and toks[j].k in ('name', 'num'):
                    out.append('__v1_deref(' + self.name(toks[j].v) + ')')
                    i = j + 1
                    continue
            if v == '%':
                # %expr% double deref whose inner part has spaces or operators
                j = i + 1
                while j < end and toks[j].v != '%':
                    j += 1
                inner = ''.join(x.v for x in toks[i + 1:j])
                out.append('%' + self(inner) + '%')
                i = j + 1
                continue
            out.append(v)
            i += 1
        return ''.join(out)

    def args(self, toks, i, end, byref):
        if all(t.k == 'ws' for t in toks[i:end]):
            return ''
        parts = self.split(toks, i, end)
        out = []
        for n, (a, b) in enumerate(parts):
            text = self.render(toks, a, b).strip()
            if (byref == 'dll' and n >= 2 and n % 2 == 0) or (byref != 'dll' and n in byref):
                if re.fullmatch(r'(?:[\w\u0080-￿]|%[^%]+%)+', text) and not text[0].isdigit() and \
                        text.lower() not in ('true', 'false') and not text.lower().startswith('a_'):
                    text = '&' + text
            out.append(text)
        return ', '.join(out)

    def objlit(self, toks, i, end):
        if all(t.k == 'ws' for t in toks[i:end]):
            return '__v1_Object()'
        items = []
        for a, b in self.split(toks, i, end):
            depth = 0
            colon = None
            for j in range(a, b):
                tv = toks[j].v if toks[j].k == 'op' else ''
                if tv in ('(', '[', '{'):
                    depth += 1
                elif tv in (')', ']', '}'):
                    depth -= 1
                elif tv == ':' and depth == 0:
                    colon = j
                    break
            if colon is None:
                raise AhkSyntaxError('Invalid object literal.', self.tr.file, self.tr.line)
            key = ''.join(t.v for t in toks[a:colon]).strip()
            if re.fullmatch(NAME + '+', key) and not key.isdigit():
                key = '"' + key + '"'
            else:
                key = self.render(toks, a, colon).strip()
            items.append(key + ', ' + self.render(toks, colon + 1, b).strip())
        return '__v1_Object(' + ', '.join(items) + ')'


# ================================================================ translator

class Translator:
    def __init__(self, lines):
        self.lines = lines
        self.out = []
        self.expr = Expr(self)
        self.file = ''
        self.line = 0
        self.funcs = {}          # lower name -> byref positions
        self.labels = {}         # lower v1 label name -> v2 label name
        self.hot_count = 0
        self.seen_hot = False
        self.stack = []          # block kinds: 'func', 'class', 'prop', 'block', 'getset'
        self.pending = None      # kind of the next '{'
        self.superglobals = []
        self.flags = {'noenv': False, 'persistent': False}
        self.prologue = []
        self.in_class = False
        self.in_method = False
        self.delim = ','

    # ------------------------------------------------------------ helpers
    def emit(self, text):
        if text is not None and text != '':
            self.out.append(LogicalLine(text, self.line, self.file))

    def err(self, msg, extra=''):
        raise AhkSyntaxError(msg, self.file, self.line, extra)

    def func_target(self, name):
        low = name.lower()
        if low in self.funcs:
            return self.expr.name(name, True), self.funcs[low]
        if low in FUNCS:
            return FUNCS[low]
        return self.expr.name(name, True), ()

    def literal(self, text, trim=True):
        """v1 command text (with %var% derefs and escapes) -> v2 expression."""
        if trim:
            text = text.strip(' \t')
        if text.startswith('% ') or text == '%':
            return self.expr(text[1:]) or '""'
        parts = []
        buf = []
        i = 0
        n = len(text)
        while i < n:
            c = text[i]
            if c == ESC and i + 1 < n:
                d = text[i + 1]
                buf.append({'n': '`n', 't': '`t', 'r': '`r', 'b': '`b', 'v': '`v', 'a': '`a', 'f': '`f',
                            '`': '``', '"': '`"'}.get(d, d))
                i += 2
                continue
            if c == '%':
                j = text.find('%', i + 1)
                if j > i + 1 and re.fullmatch(NAME + '+', text[i + 1:j]):
                    if buf:
                        parts.append('"' + ''.join(buf) + '"')
                        buf = []
                    parts.append(self.expr.name(text[i + 1:j]))
                    i = j + 1
                    continue
            if c == '"':
                buf.append('`"')
            elif c == '\n':
                buf.append('`n')
            elif c == '\r':
                buf.append('`r')
            else:
                buf.append(c)
            i += 1
        if buf:
            parts.append('"' + ''.join(buf) + '"')
        if not parts:
            return '""'
        if len(parts) == 1 and not parts[0].startswith('"'):
            return '(' + parts[0] + ' "")' if False else parts[0]
        return ' '.join(parts) if len(parts) > 1 else parts[0]

    def split_args(self, text, kinds=None, maxn=None):
        """Split v1 command parameters on unescaped commas (the last absorbs the rest)."""
        args = []
        buf = []
        depth = 0
        quote = False
        i = 0
        n = len(text)
        expr_arg = None
        while i < n:
            c = text[i]
            if not buf or all(ch in ' \t' for ch in buf):
                idx = len(args)
                kind = kinds[idx] if kinds and idx < len(kinds) else 't'
                stripped = text[i:].lstrip(' \t')
                expr_arg = stripped.startswith('% ') or (kind == 'n' and '%' not in self._arg_preview(text, i))
            if c == ESC and i + 1 < n:
                buf.append(c + text[i + 1])
                i += 2
                continue
            if expr_arg:
                if c == '"':
                    quote = not quote
                elif not quote:
                    if c in '([{':
                        depth += 1
                    elif c in ')]}':
                        depth -= 1
            if c == self.delim and depth <= 0 and not quote and (maxn is None or len(args) < maxn - 1):
                args.append(''.join(buf))
                buf = []
                depth = 0
                quote = False
                i += 1
                continue
            buf.append(c)
            i += 1
        args.append(''.join(buf))
        return args

    @staticmethod
    def _arg_preview(text, i):
        j = text.find(',', i)
        return text[i:j if j >= 0 else len(text)]

    def outvar(self, text):
        text = text.strip()
        if text.startswith('&') and not text.startswith('&&'):
            text = text[1:].strip()
        if not text:
            return ''
        if text.startswith('% '):
            return '&' + self.expr(text[2:])
        if not re.fullmatch(r'(?:' + NAME + r'|%[^%]+%)+', text):
            self.err('Invalid output variable name.', text)
        return '&' + self.expr.name(text)

    def invar(self, text):
        text = text.strip()
        if not text:
            return '""'
        if text.startswith('% '):
            return self.expr(text[2:])
        return self.expr.name(text)

    def number(self, text):
        text = text.strip()
        if text == '':
            return ''
        if text.startswith('% '):
            return self.expr(text[2:])
        if '%' in text:
            return self.literal(text)
        return self.expr(text)

    def conv_args(self, kinds, args):
        out = []
        for idx, a in enumerate(args):
            kind = kinds[idx] if idx < len(kinds) else 't'
            if a.strip() == '' and kind != 'x':
                out.append('')
            elif kind == 'o':
                out.append(self.outvar(a))
            elif kind == 'i':
                out.append(self.invar(a))
            elif kind == 'n':
                out.append(self.number(a))
            else:
                out.append(self.literal(a))
        while out and out[-1] == '':
            out.pop()
        return out

    def label_name(self, name):
        low = name.lower()
        if low in self.labels:
            return self.labels[low]
        if re.fullmatch(r'[A-Za-z_][\w]*', name) and low not in V2_RESERVED and not low.startswith('__v1'):
            v2 = name
        else:
            v2 = '__L_' + low.encode().hex()
        self.labels[low] = v2
        return v2

    # ------------------------------------------------------------ passes
    def scan(self):
        depth = 0
        for idx, ll in enumerate(self.lines):
            t = ll.text
            m = re.match(r'(' + NAME + r'+)\((.*)\)\s*(\{)?$', t)
            if m and depth == 0 and (m[3] or (idx + 1 < len(self.lines) and self.lines[idx + 1].text.startswith('{'))):
                if m[1].lower() not in ('if', 'while', 'for', 'loop', 'switch', 'catch', 'return'):
                    byref = tuple(i for i, p in enumerate(self.params_split(m[2])) if re.match(r'\s*byref\s', p, re.I))
                    self.funcs[m[1].lower()] = byref
            if re.match(r'global\s+\S', t, re.I) and depth == 0:
                for item in self.expr.split(tokenize(t[7:]), 0, len(tokenize(t[7:]))):
                    pass
                for part in self.split_args(t[7:], 'n' * 99):
                    nm = re.match(r'\s*(' + NAME + r'+)', part)
                    if nm:
                        self.superglobals.append(nm[1])
            if t.startswith('{') or t.endswith('{'):
                depth += t.count('{') if t.strip('{ ') == '' else 1
            if t.startswith('}'):
                depth -= len(t) - len(t.lstrip('}').lstrip()) and t.count('}', 0, len(t) - len(t.lstrip('} '))) or 1
                depth = max(depth, 0)
            hot = classify_hot_line(t)
            if not hot and re.fullmatch(r'(?:[^\s,`]|`.)+:', t) and t[:-1].lower() != 'default':
                self.label_name(t[:-1].replace('`', ''))

    @staticmethod
    def params_split(text):
        parts, depth, buf, q = [], 0, [], False
        for c in text:
            if c == '"':
                q = not q
            if not q:
                if c in '([{':
                    depth += 1
                elif c in ')]}':
                    depth -= 1
                elif c == ',' and depth == 0:
                    parts.append(''.join(buf))
                    buf = []
                    continue
            buf.append(c)
        if ''.join(buf).strip():
            parts.append(''.join(buf))
        return parts

    def run(self):
        self.scan()
        for idx, ll in enumerate(self.lines):
            self.file, self.line = ll.file, ll.line
            self.next_text = self.lines[idx + 1].text if idx + 1 < len(self.lines) else ''
            self.do_line(ll.text)
        if self.stack:
            pass
        head = []
        if self.lines:
            self.file, self.line = self.lines[0].file, self.lines[0].line
        for p in self.prologue:
            head.append(LogicalLine(p, self.line, self.file))
        return head + self.out

    # ------------------------------------------------------------ lines
    @property
    def top(self):
        return 'func' not in self.stack and 'class' not in self.stack and 'getset' not in self.stack

    def open_block(self, kind=None):
        k = kind or self.pending or 'block'
        self.pending = None
        self.stack.append(k)
        self._ctx()

    def close_block(self):
        if self.stack:
            if self.stack.pop() == 'hotblock':
                self.emit('return')
        self._ctx()

    def _ctx(self):
        self.in_class = bool(self.stack) and self.stack[-1] == 'class'
        self.in_method = 'class' in self.stack and ('func' in self.stack or 'getset' in self.stack)

    def do_line(self, t):
        # leading closing braces: "} else {" etc.
        while t.startswith('}') and not (t.startswith('}::') and not self.stack):
            self.emit('}')
            self.close_block()
            t = t[1:].lstrip()
            if not t:
                return
        if t == '{':
            self.emit('{')
            self.open_block()
            return
        hot = classify_hot_line(t.replace('`;', ';', 1) if t.startswith('`;') else t)
        if hot and not self.stack:
            return self.hot(hot, t)
        if t.startswith('#'):
            return self.directive(t)
        if self.in_class:
            return self.class_member(t)
        m = re.fullmatch(r'((?:[^\s,`]|`.)+):', t)
        if m and m[1].lower() != 'default' and not t.lower().startswith('case'):
            self.emit(self.label_name(m[1].replace('`', '')) + ':')
            return
        self.statement(t, top=True)

    def directive(self, t):
        m = re.match(r'#(\w+)\s*,?\s*(.*)$', t, re.S)
        if not m:
            return self.emit(t)
        name, arg = m[1].lower(), m[2].strip()
        if name.startswith('ifwin'):
            mm = re.match(r'ifwin(not)?(active|exist)$', name)
            if not arg:
                return self.emit('#HotIf')
            fn = 'WinActive' if mm[2] == 'active' else 'WinExist'
            args = ', '.join(x for x in self.conv_args('tttt', self.split_args(arg, 'tttt', 4)))
            return self.emit('#HotIf ' + ('!' if mm[1] else '') + fn + '(' + args + ')')
        if name == 'if':
            return self.emit('#HotIf ' + self.expr(arg) if arg else '#HotIf')
        if name == 'delimiter':
            self.delim = arg[:1] or ','
            return
        if name == 'iftimeout':
            return self.emit('#HotIfTimeout ' + arg)
        if name == 'noenv':
            self.flags['noenv'] = True
            return
        if name == 'persistent':
            self.prologue.append('Persistent()')
            return
        if name == 'maxhotkeysperinterval':
            self.prologue.append('A_MaxHotkeysPerInterval := ' + (arg or '70'))
            return
        if name == 'hotkeyinterval':
            self.prologue.append('A_HotkeyInterval := ' + (arg or '2000'))
            return
        if name == 'hotkeymodifiertimeout':
            self.prologue.append('A_HotkeyModifierTimeout := ' + (arg or '50'))
            return
        if name in ('installkeybdhook', 'installmousehook'):
            self.prologue.append(('InstallKeybdHook' if 'keybd' in name else 'InstallMouseHook') + '()')
            return
        if name == 'keyhistory':
            self.prologue.append('KeyHistory(' + (arg or '40') + ')')
            return
        if name == 'menumaskkey':
            self.prologue.append('A_MenuMaskKey := "' + arg + '"')
            return
        if name == 'singleinstance':
            return self.emit('#SingleInstance ' + (arg or 'Force'))
        if name in ('requires', 'commentflag', 'escapechar', 'derefchar', 'delimiter', 'allowsamelinecomments',
                    'maxmem', 'ltrim', 'warn', 'notrayicon_', 'include', 'includeagain'):
            if name == 'warn':
                return
            return
        if name == 'hotstring':
            if arg.lower().startswith('nomouse'):
                return self.emit('#Hotstring NoMouse')
            if arg.lower().startswith('endchars'):
                return self.emit('#Hotstring EndChars ' + arg[8:].strip())
            return self.emit('#Hotstring ' + arg)
        return self.emit('#' + m[1] + (' ' + arg if arg else ''))

    def hot(self, hot, t):
        from .parser import _is_remap
        if not self.seen_hot:
            self.emit('return')
            self.seen_hot = True
        if hot[0] == 'hotkey':
            keys, rest = hot[1], hot[2]
            if t.startswith('`;'):
                t = t[1:]
            if rest and _is_remap(rest):
                return self.emit(t)
            head = keys
            label_key = keys
        else:
            opts, trig, rest = hot[1], hot[2], hot[3]
            if rest and 'x' not in opts.lower():
                return self.emit(t)
            head = ':' + opts.replace('X', '').replace('x', '') + ':' + trig
            label_key = ':' + opts + ':' + trig
        self.hot_count += 1
        lbl = f'__hk{self.hot_count}'
        self.labels.setdefault(label_key.lower(), lbl)
        self.emit(head + '::__v1_gosub("' + lbl + '")')
        self.emit(lbl + ':')
        if rest == '{':
            self.emit('{')
            self.open_block('hotblock')
        elif rest:
            self.statement(rest)
            self.emit('return')

    # ------------------------------------------------------------ classes
    def class_member(self, t):
        m = re.match(r'class\s+(' + NAME + r'+)(?:\s+extends\s+([\w.]+))?\s*(\{)?$', t, re.I)
        if m:
            return self.class_head(m)
        m = re.match(r'(' + NAME + r'+)\((.*)\)\s*(\{)?$', t)
        if m and (m[3] or self.next_text.startswith('{')):
            return self.func_head(m, method=True)
        m = re.match(r'(' + NAME + r'+)(\[[^\]]*\])?\s*(\{)?$', t)
        if m:
            params = m[2] or ''
            params = '' if params.replace(' ', '') == '[]' else params
            self.emit(m[1] + params + (' {' if m[3] else ''))
            if m[3]:
                self.open_block('getset')
            else:
                self.pending = 'getset'
            return
        m = re.match(r'(static\s+)?(' + NAME + r'+)\s*(:=|=)\s*(.*)$', t, re.I | re.S)
        if m:
            val = self.expr(m[4]) if m[3] == ':=' else self.literal(m[4])
            return self.emit((m[1] or '') + self.expr.name(m[2], True) + ' := ' + val)
        self.statement(t)

    def class_head(self, m):
        ext = m[2]
        self.emit('class ' + m[1] + (' extends ' + ext if ext else ' extends __v1_Base') + (' {' if m[3] else ''))
        if m[3]:
            self.open_block('class')
        else:
            self.pending = 'class'

    def func_head(self, m, method=False):
        params = []
        for p in self.params_split(m[2]):
            p = p.strip()
            byref = False
            if re.match(r'byref\s', p, re.I):
                byref = True
                p = p[5:].strip()
            pm = re.match(r'(' + NAME + r'+)(\*)?\s*(?:(:=|=)\s*(.*))?$', p, re.S)
            if not pm:
                self.err('Invalid parameter.', p)
            s = ('&' if byref else '') + self.expr.name(pm[1], True) + (pm[2] or '')
            if pm[3]:
                s += ' := ' + self.expr(pm[4])
            elif method and m[1].lower() in ('__get', '__call') and pm[2]:
                s = s[:-1]     # v2 passes the params as an Array
            params.append(s)
        low = m[1].lower()
        if method and low == '__get':
            params = params[:1] + (['__v1_params'] if len(params) < 2 else params[1:2])
        if method and low == '__set':
            if len(params) == 2:
                params = [params[0], '__v1_params', params[1]]
        self.emit(self.expr.name(m[1], True) + '(' + ', '.join(params) + ')' + (' {' if m[3] else ''))
        if m[3]:
            self.open_block('func')
            self.func_prologue()
        else:
            self.pending = 'func'

    def func_prologue(self):
        if self.superglobals:
            self.emit('global ' + ', '.join(self.superglobals))

    # ------------------------------------------------------------ statements
    def statement(self, t, top=False):
        t = t.strip()
        if not t:
            return
        if self.pending == 'func' and t == '{':
            return
        low = t.lower()
        word = re.match(r'(' + NAME + r'+)', t)
        w = word[1].lower() if word else ''
        after = t[len(word[1]):] if word else t
        rest_sep = re.match(r'\s*' + re.escape(self.delim) + r'?\s*', after)
        rest = after[rest_sep.end():] if rest_sep else after

        # function definitions
        if top and self.top or 'class' in self.stack and not self.in_method:
            m = re.match(r'(' + NAME + r'+)\((.*)\)\s*(\{)?$', t)
            if m and w not in ('if', 'while', 'for', 'loop', 'switch', 'catch', 'return') and \
                    (m[3] or self.next_text.startswith('{')) and not self.stack:
                return self.func_head(m)
        if w == 'class' and re.match(r'class\s', t, re.I) and not self.stack:
            m = re.match(r'class\s+(' + NAME + r'+)(?:\s+extends\s+([\w.]+))?\s*(\{)?$', t, re.I)
            if m:
                return self.class_head(m)
        if self.stack and self.stack[-1] == 'getset' and w in ('get', 'set') and re.fullmatch(r'(get|set)\s*\{?', t, re.I):
            self.emit(w + (' {' if t.endswith('{') else ''))
            if t.endswith('{'):
                self.open_block('func')
            else:
                self.pending = 'func'
            return

        # assignment / expression forms take precedence over command names
        if re.match(r'(?:' + NAME + r'|%[^%]+%|[.\[\]])*\s*(:=|\+=|-=|\*=|/=|//=|\.=|\|=|&=|\^=|>>=|<<=|\+\+|--)', t) \
                and not re.match(r'(' + NAME + r'+)\s*,', t):
            m = re.match(r'(' + NAME + r'+|%[^%]+%)\s*(\+=|-=)\s*(.*)$', t, re.S)
            if m:
                parts = self.split_args(m[3], 'nt', 2)
                if len(parts) == 2 and parts[1].strip().lower() in TIME_UNITS | {''}:
                    fn = '__v1_EnvAdd' if m[2] == '+=' else '__v1_EnvSub'
                    return self.emit(fn + '(' + self.outvar(m[1]) + ', ' + self.number(parts[0]) +
                                     (', ' + self.literal(parts[1]) if parts[1].strip() else ', "s"') + ')')
            return self.emit(self.expr(t))
        if t.startswith(('++', '--', '(')):
            return self.emit(self.expr(t))
        m = re.match(r'((?:' + NAME + r'|%[^%]+%)+)\s*=(?!=)(.*)$', t, re.S)
        if m and w not in COMMANDS and w not in ('if', 'while', 'return', 'loop', 'until'):
            return self.emit(self.expr.name(m[1]) + ' := ' + self.literal(m[2]))
        if m and w in COMMANDS and not re.match(NAME + r'+\s*,', t):
            return self.emit(self.expr.name(m[1]) + ' := ' + self.literal(m[2]))

        # control flow
        if w == 'if':
            return self.if_stmt(t[2:])
        if w == 'else':
            r = t[4:].strip()
            if r.startswith(','):
                r = r[1:].strip()
            if r == '{':
                self.emit('else {')
                return self.open_block()
            if not r:
                return self.emit('else')
            self.emit('else')
            return self.statement(r)
        if w == 'loop':
            return self.loop_stmt(t)
        if w == 'while':
            body, brace = self.otb(t[5:].strip().lstrip(',').strip())
            self.emit('while ' + self.paren(self.expr(body)) + brace)
            if brace:
                self.open_block()
            return
        if w == 'until':
            return self.emit('until ' + self.paren(self.expr(rest)))
        if w == 'for' and re.match(r'for\s', t, re.I):
            body, brace = self.otb(t[3:].strip())
            m = re.match(r'(.*?)\s+in\s+(.*)$', body, re.I | re.S)
            if not m:
                self.err('Invalid For loop.', t)
            self.emit('for ' + ', '.join(self.expr.name(v.strip(), True) for v in m[1].split(',')) + ' in ' +
                      self.expr(m[2]) + brace)
            if brace:
                self.open_block()
            return
        if w == 'try':
            r = t[3:].strip()
            if r == '{':
                self.emit('try {')
                return self.open_block()
            self.emit('try')
            return self.statement(r) if r else None
        if w == 'catch':
            r = t[5:].strip()
            brace = ''
            if r.endswith('{'):
                r, brace = r[:-1].strip(), ' {'
            m = re.match(r'(' + NAME + r'+)?\s*(.*)$', r, re.S)
            var = m[1]
            tail = m[2]
            self.emit('catch __v1_Any' + (' as ' + self.expr.name(var, True) if var else '') + brace)
            if brace:
                self.open_block()
            elif tail:
                self.statement(tail)
            return
        if w == 'finally':
            r = t[7:].strip()
            if r == '{':
                self.emit('finally {')
                return self.open_block()
            self.emit('finally')
            return self.statement(r) if r else None
        if w == 'switch' and re.match(r'switch\b', t, re.I):
            body, brace = self.otb(t[6:].strip().lstrip(',').strip(), attached=True)
            self.emit('switch ' + (self.expr(body) if body else '') + brace)
            if brace:
                self.open_block()
            return
        if w == 'case' and re.match(r'case\s', t, re.I):
            m = re.match(r'case\s+(.*?):(?!=)\s*(.*)$', t, re.I | re.S)
            if m:
                vals = ', '.join(self.expr(v) for v in self.params_split(m[1]))
                self.emit('case ' + vals + ':')
                if m[2]:
                    self.statement(m[2])
                return
        if re.match(r'default\s*:', t, re.I):
            self.emit('default:')
            r = t[t.index(':') + 1:].strip()
            if r:
                self.statement(r)
            return
        if w == 'return':
            r = rest.strip()
            if re.fullmatch(r'%(' + NAME + r'+)%', r):
                r = r[1:-1]
            return self.emit('return' + (' ' + self.expr(r) if r else ''))
        if w in ('break', 'continue'):
            return self.emit(w + (' ' + self.label_name(rest.strip()) if rest.strip() and not rest.strip().isdigit()
                                  else (' ' + rest.strip() if rest.strip() else '')))
        if w == 'exit':
            return self.emit('Exit(' + self.number(rest) + ')')
        if w == 'throw':
            return self.emit('throw' + (' ' + self.expr(rest) if rest.strip() else ' __v1_Exception("An exception was thrown.")'))
        if w in ('global', 'local', 'static') and (len(t) == len(w) or t[len(w)] in ' \t'):
            return self.decl(w, t[len(w):].strip())
        if w == 'gosub':
            return self.emit('__v1_gosub(' + self.literal(rest) + ')')
        if w == 'goto':
            r = rest.strip()
            if re.fullmatch(r'[^\s,%`]+', r) and r.lower() in self.labels:
                return self.emit('Goto ' + self.labels[r.lower()])
            return self.emit('__v1_goto(' + self.literal(r) + ')')
        if w.startswith('if') and w in COMMANDS:
            return self.if_command(w, rest)

        # commands
        if w in COMMANDS and (len(t) == len(word[1]) or t[len(word[1])] in ' \t,' + self.delim):
            return self.command(w, rest)

        if re.match(NAME + r'+\s*,', t):
            self.err('This line does not contain a recognized action.', t)
        # anything else is an expression (function call, method call, ...)
        if t.endswith('{') and not t.endswith('{}') and self.expr_is_block_head(t):
            return
        return self.emit(self.expr(t))

    def expr_is_block_head(self, t):
        return False

    def decl(self, kind, text):
        if not text:
            return self.emit(kind)
        items = []
        for part in self.params_split(text):
            p = part.strip()
            m = re.match(r'(' + NAME + r'+)\s*(?:(:=|=)\s*(.*))?$', p, re.S)
            if not m:
                items.append(self.expr(p))
                continue
            s = self.expr.name(m[1], True)
            if m[2]:
                s += ' := ' + (self.expr(m[3]) if m[2] == ':=' else self.literal(m[3]))
            items.append(s)
        self.emit(kind + ' ' + ', '.join(items))

    @staticmethod
    def otb(text, attached=False):
        text = text.rstrip()
        if text.endswith('{') and (len(text) == 1 or text[-2] in ' \t)' or (attached and text[-2] not in ',{')):
            return text[:-1].rstrip(), ' {'
        return text, ''

    @staticmethod
    def paren(text):
        return '(' + text + ')'

    def if_stmt(self, t):
        t = t.strip()
        if t.startswith(','):
            t = t[1:].strip()
        # expression if
        if t.startswith('('):
            try:
                toks = tokenize(t)
                close = self.expr.match(toks, 0, len(toks))
                consumed = len(''.join(x.v for x in toks[:close + 1]))
            except AhkSyntaxError:
                consumed = len(t)
            tail = t[consumed:].strip()
            if not tail or tail == '{' or re.match(r'(and|or|&&|\|\||[-+*/.<>=!?~&|^]|\.)', tail, re.I):
                body, brace = self.otb(t)
                self.emit('if ' + self.paren(self.expr(body)) + brace)
                if brace:
                    self.open_block()
                return
            self.emit('if ' + self.paren(self.expr(t[:consumed])))
            return self.statement(tail)
        lm = re.match(r'(not\s+|!\s*)((?:' + NAME + r'|%[^%]+%)+)\s*(<>|!=|>=|<=|=|>|<)(?![=])(.*)$', t, re.I | re.S)
        if lm and not t.startswith('!('):
            return self.emit(f'if !__v1_cmp({self.invar(lm[2])}, "{lm[3]}", {self.literal(lm[4])})')
        m = re.match(r'((?:' + NAME + r'|%[^%]+%)+)\s+(not\s+)?(between|in|contains|is)\s+(not\s+)?(.*)$', t, re.I | re.S)
        if m and (m[4] is None or m[3].lower() == 'is'):
            var = self.invar(m[1])
            neg = '!' if m[2] or m[4] else ''
            op = m[3].lower()
            val = m[5]
            brace = ''
            if re.search(r'\s\{$', val):
                val, brace = val[:-1].rstrip(), ' {'
            if brace:
                self.pending_brace = True
            if op == 'between':
                bm = re.match(r'(.*?)\s+and\s+(.*)$', val, re.I | re.S)
                if not bm:
                    self.err('"between" requires "and".')
                self.emit(f'if {neg}__v1_between({var}, {self.literal(bm[1])}, {self.literal(bm[2])})' + brace)
            elif op == 'is':
                self.emit(f'if {neg}__v1_is({var}, {self.literal(val)})' + brace)
            else:
                self.emit(f'if {neg}__v1_{op}({var}, {self.literal(val)})' + brace)
            if brace:
                self.open_block()
            return
        m = re.match(r'((?:' + NAME + r'|%[^%]+%)+)\s*(<>|!=|>=|<=|=|>|<)(?![=])(.*)$', t, re.S)
        if m:
            return self.emit(f'if __v1_cmp({self.invar(m[1])}, "{m[2]}", {self.literal(m[3])})')
        body, brace = self.otb(t)
        self.emit('if ' + self.paren(self.expr(body)) + brace)
        if brace:
            self.open_block()

    def if_command(self, w, rest):
        ops = {'ifequal': '=', 'ifnotequal': '<>', 'ifless': '<', 'iflessorequal': '<=', 'ifgreater': '>',
               'ifgreaterorequal': '>='}
        if w in ops:
            a = self.split_args(rest, 'itt', 3)
            self.emit(f'if __v1_cmp({self.invar(a[0])}, "{ops[w]}", {self.literal(a[1] if len(a) > 1 else "")})')
            return self.same_line(a, 2)
        if w in ('ifinstring', 'ifnotinstring'):
            a = self.split_args(rest, 'itt', 3)
            neg = '!' if 'not' in w else ''
            self.emit(f'if {neg}__v1_contains({self.invar(a[0])}, {self.literal(a[1] if len(a) > 1 else "")}, 1)')
            return self.same_line(a, 2)
        if w in ('ifexist', 'ifnotexist'):
            neg = '!' if 'not' in w else ''
            a = self.split_args(rest, 'tt', 2)
            if len(a) > 1 and not self.is_command(a[1]):
                a = [rest]
            self.emit(f'if {neg}__v1_FileExist({self.literal(a[0])})')
            return self.same_line(a, 1)
        if w == 'ifmsgbox':
            a = self.split_args(rest, 'tt', 2)
            self.emit(f'if (__v1_msgresult() = {self.literal(a[0])})')
            return self.same_line(a, 1)
        m = re.match(r'ifwin(not)?(active|exist)$', w)
        args = ', '.join(self.conv_args('tttt', self.split_args(rest, 'tttt', 4)))
        fn = '__v1_WinActive' if m[2] == 'active' else '__v1_WinExist'
        return self.emit(f'if {"!" if m[1] else ""}{fn}({args})')

    def is_command(self, text):
        m = re.match(r'\s*(' + NAME + r'+)', text)
        return bool(m) and (m[1].lower() in COMMANDS or m[1].lower() in ('break', 'continue', 'return', 'exit', 'goto',
                                                                         'gosub', 'else'))

    def same_line(self, args, n):
        """v1 allows a command on the same line after the parameters of IfEqual & co."""
        if len(args) > n and args[n].strip():
            self.statement(args[n].strip())

    def loop_stmt(self, t):
        body, brace = self.otb(t[4:].strip())
        if body.startswith(','):
            body = body[1:].strip()
        if not body:
            self.emit('Loop' + brace)
        else:
            parts = self.split_args(body, 'tttt', 4)
            kind = parts[0].strip().lower()
            if kind in ('parse', 'read', 'files', 'reg') and len(parts) > 1:
                if kind == 'parse':
                    args = [self.invar(parts[1])] + [self.literal(p, trim=False) if p.strip() else '""'
                                                     for p in parts[2:]]
                    # delimiters keep spaces only when written as `s or literally
                    args = [args[0]] + [a for a in args[1:]]
                    if len(parts) > 2:
                        args[1] = self.literal(parts[2], trim=True) if parts[2].strip() else '""'
                else:
                    args = [self.literal(p) for p in parts[1:]]
                while args and args[-1] == '""':
                    args.pop()
                self.emit('Loop ' + kind.capitalize() + ', ' + ', '.join(args) + brace)
            else:
                first = parts[0].strip()
                if len(parts) == 1 and (first.startswith('% ') or re.fullmatch(r'%' + NAME + r'+%|[\d\s+*/()-]+|0x[\da-f]+', first, re.I)):
                    self.emit('Loop ' + self.number(first) + brace)
                elif re.match(r'(HKEY_|HKLM|HKCU|HKCR|HKU|HKCC)', first, re.I):
                    root = first
                    key = parts[1].strip() if len(parts) > 1 else ''
                    inc = parts[2].strip() if len(parts) > 2 else '0'
                    rec = parts[3].strip() if len(parts) > 3 else '0'
                    mode = {'0': 'V', '1': 'KV', '2': 'K'}.get(inc or '0', 'V') + ('R' if rec == '1' else '')
                    self.emit('Loop Reg, ' + self.literal(root + ('\\' + key if key else '')) + ', "' + mode + '"' + brace)
                else:
                    inc = parts[1].strip() if len(parts) > 1 else '0'
                    rec = parts[2].strip() if len(parts) > 2 else '0'
                    mode = {'0': 'F', '1': 'FD', '2': 'D'}.get(inc or '0', 'F') + ('R' if rec == '1' else '')
                    self.emit('Loop Files, ' + self.literal(parts[0]) + ', "' + mode + '"' + brace)
        if brace:
            self.open_block()

    def command(self, w, rest):
        kinds = COMMANDS[w]
        if w == 'msgbox':
            args = self.split_args(rest, 'tttt', 4)
            first = args[0].strip()
            if len(args) == 4 and not re.fullmatch(r'\s*(\d+(\.\d*)?|%' + NAME + r'+%|% .*)\s*', args[3]):
                args = args[:2] + [args[2] + ',' + args[3]]
            if len(args) >= 3 and (re.fullmatch(r'\d+|0x[\da-f]+', first, re.I) or first.startswith('% ')
                                   or re.fullmatch(r'%' + NAME + r'+%', first) or first == ''):
                conv = self.conv_args('ntt' + 'n', args)
                return self.emit('__v1_MsgBox(' + ', '.join(conv) + ')')
            return self.emit('__v1_MsgBox(, , ' + (self.literal(rest) if rest.strip() else '"Press OK to continue."') + ')'
                             if rest.strip() else '__v1_MsgBox()')
        if w in ('send', 'sendinput', 'sendevent', 'sendplay', 'sendraw', 'click', 'controlsend', 'controlsendraw',
                 'traytip', 'tooltip', 'fileappend', 'sendmode'):
            pass
        args = self.split_args(rest, kinds, max(len(kinds), 1)) if rest.strip() else []
        if len(args) > len(kinds) and kinds:
            args = args[:len(kinds)]
        conv = self.conv_args(kinds, args)
        name = '__v1_' + w
        self.emit(name + '(' + ', '.join(conv) + ')')


def translate(lines):
    tr = Translator(lines)
    out = tr.run()
    return out, tr


# ---------------------------------------------------------------- compatibility with the old API
def detect(lines, requested='auto'):
    return detect_text('\n'.join(ll.text for ll in lines), requested)
