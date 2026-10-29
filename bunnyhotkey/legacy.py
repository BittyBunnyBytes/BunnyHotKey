"""A deliberately bounded AutoHotkey v1 command/hotkey compatibility frontend."""
import re

from .errors import AhkSyntaxError
from .lexer import LogicalLine, classify_hot_line

# Commands whose positional arguments retain their v2 meaning. Numeric positions
# accept v1 expressions; other positions use legacy literal/percent expansion.
COMMANDS = {
    'send': (), 'sendinput': (), 'sendevent': (), 'sendplay': (),
    'sendraw': (), 'sendmode': (), 'setworkingdir': (), 'keywait': (),
    'sleep': (0,), 'setmousedelay': (0,), 'setkeydelay': (0, 1),
    'setwindelay': (0,), 'setcontroldelay': (0,), 'setdefaultmousespeed': (0,),
    'coordmode': (), 'mousemove': (0, 1, 2), 'mouseclick': (1, 2, 3, 4),
    'click': (), 'winactivate': (), 'winwait': (2,), 'winwaitactive': (2,),
    'winclose': (2,), 'settitlematchmode': (), 'fileappend': (),
    'exitapp': (0,), 'reload': (), 'pause': (), 'suspend': (),
    'tooltip': (1, 2, 3),
}


def split_args(text):
    return re.split(r'(?<!`),', text)


def literal(text):
    text = text.strip()
    if text.startswith('% '):
        return text[2:].strip()
    parts = re.split(r'(?<!`)%([A-Za-z_]\w*)%', text)
    result = []
    for i, part in enumerate(parts):
        if i % 2:
            result.append(part)
        elif part:
            result.append('"' + part.replace('"', '`"').replace('`%', '%') + '"')
    return ' . '.join(result) or '""'


def detect(lines, requested='auto'):
    required = None
    for ll in lines:
        m = re.match(r'#Requires\s+AutoHotkey\s+v?([12])(?:\D|$)', ll.text, re.I)
        if m:
            version = m[1]
            if required and required != version:
                raise AhkSyntaxError('Conflicting AutoHotkey versions.', ll.file, ll.line, ll.text)
            required = version
    if requested != 'auto':
        if required and required != requested:
            raise AhkSyntaxError('Script version conflicts with --ahk-version.', lines[0].file, 1)
        return requested
    if required:
        return required
    for index, ll in enumerate(lines):
        t = ll.text
        if re.match(r'#(?:NoEnv|IfWinActive|IfWinExist|IfWinNotActive|IfWinNotExist|If)\b', t, re.I):
            return '1'
        if re.match(r'(?:' + '|'.join(COMMANDS) + r'|MouseGetPos)\s*,', t, re.I):
            return '1'
        hot = classify_hot_line(t)
        if hot and hot[0] == 'hotkey' and not hot[2]:
            if index + 1 < len(lines) and lines[index + 1].text != '{':
                return '1'
    return '2'


def statement(t, ll):
    m = re.match(r'#IfWin(Not)?(Active|Exist)\b\s*,?\s*(.*)', t, re.I)
    if m:
        args = m[3].strip()
        if not args:
            return '#HotIf'
        fn = 'WinActive' if m[2].lower() == 'active' else 'WinExist'
        return '#HotIf ' + ('!' if m[1] else '') + fn + '(' + ', '.join(map(literal, split_args(args))) + ')'
    if re.match(r'#If\b', t, re.I):
        return re.sub(r'^#If\b', '#HotIf', t, flags=re.I)
    if re.match(r'#Requires\b', t, re.I):
        return ''  # version was checked by detect; retain runtime's actual version
    m = re.match(r'([A-Za-z_]\w*)\s*=(?!=)\s*(.*)$', t)
    if m:
        return m[1] + ' := ' + literal(m[2])
    m = re.match(r'([A-Za-z_]\w*)(?:\s*,\s*|\s+|$)(.*)', t)
    if not m:
        return t
    name, args = m[1], m[2]
    key = name.lower()
    if key == 'mousegetpos':
        vals = split_args(args)
        if any(v.strip() and not re.fullmatch(r'[A-Za-z_]\w*', v.strip()) for v in vals[:4]):
            raise AhkSyntaxError('Invalid v1 output variable.', ll.file, ll.line, t)
        return 'MouseGetPos(' + ', '.join('&' + v.strip() if v.strip() and i < 4 else v.strip() for i, v in enumerate(vals)) + ')'
    if key not in COMMANDS:
        if re.match(r'\w+\s*,', t):
            raise AhkSyntaxError('Unsupported v1 command.', ll.file, ll.line, t)
        return t
    vals = split_args(args) if args else []
    converted = [((v.strip()[2:] if v.strip().startswith('% ') else v.strip())
                  if i in COMMANDS[key] and '%' not in v else literal(v)) if v.strip() else ''
                 for i, v in enumerate(vals)]
    target = 'SendText' if key == 'sendraw' else name
    return target + '(' + ', '.join(converted) + ')'


def translate(lines):
    from .parser import _is_remap
    out = []
    body = False
    depth = 0
    seen_hotkey = False
    def emit(text, ll):
        if text:
            out.append(LogicalLine(text, ll.line, ll.file))
    for index, ll in enumerate(lines):
        t = ll.text
        hot = classify_hot_line(t)
        if hot and hot[0] == 'hotkey':
            if not seen_hotkey:
                emit('return', ll)  # v1 auto-execute stops at the first hotkey
                seen_hotkey = True
            if body:
                emit('}', ll)
                body = False
            keys, rest = hot[1:]
            if rest and _is_remap(rest):
                emit(t, ll)
                continue
            emit(keys + '::', ll)
            # Stacked labels share the following body.
            if not rest and index + 1 < len(lines) and classify_hot_line(lines[index + 1].text):
                continue
            emit('{', ll)
            emit('global', ll)
            if rest:
                emit(statement(rest, ll), ll)
                emit('}', ll)
            else:
                body = True
                depth = 0
            continue
        if body and depth == 0 and t.lower() == 'return':
            emit('return', ll)
            emit('}', ll)
            body = False
            continue
        emit(statement(t, ll), ll)
        if body:
            depth += (t == '{') - (t == '}')
    if body:
        emit('}', lines[-1])
    return out
