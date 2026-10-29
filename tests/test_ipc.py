"""Window messages between two Bunny Hot Key processes: the receiver's hidden "AutoHotkey" main window is found
with DetectHiddenWindows, gets WM_COPYDATA through OnMessage (the reply comes back to SendMessage), and exits on
WM_COMMAND 65307 (ID_TRAY_EXIT), as AutoHotkey scripts do.  Needs an X display; skipped without one."""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RUN = [sys.executable, "-m", "bunnyhotkey", "--console", "--backend=null", "--no-tray"]


def main():
    if not os.environ.get("DISPLAY"):
        print("skipped: no DISPLAY")
        return 0
    recv = subprocess.Popen(RUN + [os.path.join(HERE, "ipc", "receiver.ahk")], cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    time.sleep(1.5)
    send = subprocess.run(RUN + [os.path.join(HERE, "ipc", "sender.ahk")], cwd=ROOT, capture_output=True, text=True,
                          timeout=30)
    try:
        out, _ = recv.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        recv.kill()
        print("FAIL: receiver did not exit on WM_COMMAND 65307")
        return 1
    want_send = "found: 1 class=AutoHotkey\nreply: 1234\n"
    want_recv = "gui pid matches: 1\nreceiver got: hello from sender (dwData=42)\n"
    if send.stdout != want_send or out != want_recv:
        print("FAIL\nsender:", repr(send.stdout + send.stderr), "\nreceiver:", repr(out))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
