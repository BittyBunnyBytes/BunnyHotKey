"""Regression suite: runs tests/scripts/*.ahk with the null backend and compares stdout to *.expected.

Expected outputs were checked line by line against AutoHotkey v2.0.31's source semantics.
Run: python3 tests/run.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main():
    scripts = sorted(f for f in os.listdir(os.path.join(HERE, "scripts")) if f.endswith(".ahk"))
    failed = 0
    for name in scripts:
        path = os.path.join(HERE, "scripts", name)
        exp_path = path[:-4] + ".expected"
        if not os.path.exists(exp_path):
            continue
        r = subprocess.run([sys.executable, "-m", "bunnyhotkey", "--console", "--backend=null", path],
                           capture_output=True, text=True, cwd=ROOT, timeout=60)
        got = r.stdout + r.stderr
        want = open(exp_path).read()
        if got == want:
            print(f"PASS {name}")
        else:
            failed += 1
            print(f"FAIL {name}")
            for i, (g, w) in enumerate(zip(got.splitlines(), want.splitlines())):
                if g != w:
                    print(f"  line {i + 1}: got {g!r} want {w!r}")
                    break
    py_tests = ["test_input.py", "test_tray.py"]
    for t in py_tests:
        r = subprocess.run([sys.executable, os.path.join(HERE, t)], capture_output=True, text=True, cwd=ROOT)
        print(f"PASS {t}" if r.returncode == 0 else f"FAIL {t}\n" + r.stdout)
        failed += r.returncode != 0
    total = len(scripts) + len(py_tests)
    print(f"{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
