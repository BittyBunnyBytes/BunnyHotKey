"""Headless backend: tracks logical state only."""
from __future__ import annotations

import time


class NullBackend:
    name = "null"
    can_suppress = False

    def __init__(self, rt):
        self.rt = rt
        self.down = set()
        self.pos = (0, 0)
        self.toggles = {"capslock": False, "numlock": True, "scrolllock": False}
        self.log = []          # injected events, used by the test-suite

    def start(self):
        pass

    def stop(self):
        pass

    def refresh(self):
        pass

    def key(self, code, down):
        self.log.append(("key", code, down))
        (self.down.add if down else self.down.discard)(code)

    def tap(self, code):
        self.key(code, True)
        self.key(code, False)

    def text(self, s):
        self.log.append(("text", s))

    def button(self, name, down):
        self.log.append(("button", name, down))

    def wheel(self, name, n):
        self.log.append(("wheel", name, n))

    def move(self, x, y):
        self.pos = (x, y)

    def mouse_pos(self):
        return self.pos

    def window_under_mouse(self):
        return 0

    def key_state(self, code, physical=False):
        return code in self.down

    def logical_modifiers(self):
        return [c for c in self.down if c in (29, 97, 42, 54, 56, 100, 125, 126)]

    def toggle_state(self, name):
        return self.toggles.get(name.lower(), False)

    def flush(self):
        pass

    def idle_ms(self):
        return int((time.monotonic() - self.rt.start_time) * 1000)
