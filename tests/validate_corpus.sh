#!/bin/sh
# Clone popular AutoHotkey v2 repositories and check that every script loads under BHK
# (bhk --validate parses and compiles; it does not execute the scripts).
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=${1:-$(mktemp -d)}
cd "$WORK"
for r in Descolada/AHK-v2-libraries thqby/ahk2_lib TheArkive/JXON_ahk2 G33kDude/cJson.ahk Descolada/UIA-v2 \
         jNizM/ahk-scripts-v2 Descolada/OCR; do
    d=$(echo "$r" | tr / _)
    [ -d "$d" ] || git -c url."https://github.com/".insteadOf="git@github.com:" clone -q --depth 1 --recurse-submodules --shallow-submodules "https://github.com/$r.git" "$d"
done
ok=0; fail=0
for f in $(find "$WORK" -type f -name '*.ahk' -not -path '*/.git/*' | tr ' ' '?'); do
    f=$(echo "$f" | tr '?' ' ')
    if out=$(cd "$ROOT" && timeout 30 python3 -m bunnyhotkey --validate --console "$f" 2>&1) && [ -z "$out" ]; then
        ok=$((ok + 1))
    else
        fail=$((fail + 1)); echo "FAIL $f: $(echo "$out" | head -1)"
    fi
done
echo "$ok loaded, $fail failed (scripts in $WORK)"
