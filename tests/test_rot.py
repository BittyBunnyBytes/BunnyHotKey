"""Cross-process ComObjActive: one script publishes an object with RegisterActiveObject (Lexikos's
ObjRegisterActive), another gets it with ComObjActive and calls its members, including a callback into itself.

Run: python3 tests/test_rot.py
"""
import os
import select
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WANT = """hi bunny
total 12
total 100
cb 42
err MethodError: This value of type "Calc" has no method named "Nope".
missing (0x800401E3) Operation unavailable
"""


def run(name):
    return [sys.executable, "-m", "bunnyhotkey", "--console", "--backend=null", os.path.join(HERE, "rot", name)]


def main():
    server = subprocess.Popen(run("server.ahk"), cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        line, deadline = b"", time.monotonic() + 20
        while not line.endswith(b"\n") and time.monotonic() < deadline:
            if select.select([server.stdout], [], [], 0.5)[0]:
                ch = server.stdout.read1(256) if hasattr(server.stdout, "read1") else server.stdout.read(1)
                if not ch:
                    break
                line += ch
        if line.strip() != b"ready":
            print(f"FAIL server didn't start: {line!r}")
            return 1
        r = subprocess.run(run("client.ahk"), cwd=ROOT, capture_output=True, text=True, timeout=60)
        got = r.stdout + r.stderr
    finally:
        server.terminate()                  # this exact process, never a pattern match
        try:
            server.wait(5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
    if got != WANT:
        print("FAIL rot client output:")
        for g, w in zip(got.splitlines() + [""] * 9, WANT.splitlines()):
            print(("  ok   " if g == w else "  DIFF ") + f"got {g!r} want {w!r}")
        return 1
    print("PASS rot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
