#!/bin/sh
# Extract AutoHotkey's built-in function names from its C++ source: tools/extract_ahk_builtins.sh <ahk-source>/source
SRC=${1:?usage: $0 <AutoHotkey>/source}
{
  echo "# AutoHotkey built-in names (script.cpp BIF table, lib/functions.h md_func, globaldata.cpp g_act)."
  echo "# Regenerate from an AutoHotkey source checkout with tools/extract_ahk_builtins.sh."
  {
    grep -oE "^\s*(BIF[A-Za-z0-9_]*)\(([A-Za-z0-9_]+)" "$SRC/script.cpp" | sed -E 's/.*\(//'
    grep -oE "md_func[A-Za-z0-9_]*\(([A-Za-z0-9_]+)" "$SRC/lib/functions.h" | sed -E 's/.*\(//'
    sed -n '/g_act\[\] =/,/^};/p' "$SRC/globaldata.cpp" | grep -oE '_T\("[A-Za-z]+"\)' | sed -E 's/_T\("(.*)"\)/\1/'
  } | sort -u | grep -v -x -i -E "if|else|loop|while|for|try|catch|finally|throw|return|break|continue|goto|switch|case|default|global|local|static|until|class|assign|expression|block|exit"
} > "$(dirname "$0")/ahk_builtins.txt"
