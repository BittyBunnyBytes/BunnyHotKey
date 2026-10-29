"""v1 compatibility regressions, with input confined to the null backend."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bunnyhotkey.loader import Program
from bunnyhotkey.backends import get_backend
from bunnyhotkey.errors import AhkSyntaxError, ReturnEx
from bunnyhotkey.objects import BuiltinFunc

class LegacyTests(unittest.TestCase):
    def load(self, path, version='auto'):
        p = Program(str(path), [], {'backend': 'null', 'gui_errors': False, 'ahk_version': version})
        auto, hot = p.loader.load(str(path))
        p.register_hot(hot)
        self.addCleanup(p.shutdown)
        return p, auto, hot

    def invoke(self, p, hot, key):
        fn = next(fn for kind, node, fn in hot if kind == 'hot' and key in getattr(node, 'keys', []))
        try:
            p.rt.call(fn, [key])
        except ReturnEx:
            pass

    def script(self, text):
        d = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, d, True)
        path = Path(d) / 'hotkeys.ahk'
        path.write_text(text)
        return self.load(path)

    def test_hotkey_toggle_is_shared(self):
        p, _, hot = self.script('#NoEnv\ntoggle := 0\n$MButton::\ntoggle := !toggle\n'
                                'if toggle\n    Send, {MButton down}\nelse\n    Send, {MButton up}\nreturn\n')
        b = get_backend(p.rt)
        self.assertEqual(p.rt.script_version, '1')
        self.assertTrue(p.rt.is_persistent())
        self.invoke(p, hot, '$MButton')
        self.assertEqual(p.rt.globals['toggle'].value, 1)
        self.invoke(p, hot, '$MButton')
        self.assertEqual(p.rt.globals['toggle'].value, 0)
        self.assertEqual([e for e in b.log if e[0] == 'button'],
                         [('button', 'MButton', True), ('button', 'MButton', False)])

    def test_mouse_output_parameters(self):
        p, auto, hot = self.script('#NoEnv\nCoordMode, Mouse, Screen\nXButton1::\nMouseGetPos, mx, my\nreturn\n')
        try:
            auto(None)          # the auto-execute section sets CoordMode for later threads
        except ReturnEx:
            pass
        p.rt.defaults = p.rt.thread.settings
        b = get_backend(p.rt)
        b.pos = (12, 34)
        self.invoke(p, hot, 'XButton1')
        self.assertEqual(p.rt.globals['mx'].value, 12)
        self.assertEqual(p.rt.globals['my'].value, 34)

    def test_window_conditions(self):
        p, _, hot = self.script('#NoEnv\n#IfWinActive, Some Window\nF1::Send, a\n#IfWinActive\n')
        directives = [n for kind, n, fn in hot if kind == 'directive' and n.name.lower() == 'hotif']
        self.assertEqual(directives[0].args, 'WinActive("Some Window")')
        self.assertEqual(len(p.rt.hotmgr.criteria), 1)

    def test_version_and_interpolation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.ahk'
            path.write_text('#Requires AutoHotkey v1.1\nname = Bunny\nresult = Hello %name%\n')
            p, auto, _ = self.load(path)
            auto(None)
            self.assertEqual(p.rt.globals['result'].value, 'Hello Bunny')
            with self.assertRaises(AhkSyntaxError):
                self.load(path, '2')
            path.write_text('#Requires AutoHotkey v2.0\nresult := 42\n')
            p, auto, _ = self.load(path)
            auto(None)
            self.assertEqual(p.rt.script_version, '2')
            path.write_text('#Requires AutoHotkey v1\nUnsupportedCommand, arg\n')
            with self.assertRaises(AhkSyntaxError):
                self.load(path)

    def test_detection_ignores_forms_valid_in_v2(self):
        from bunnyhotkey.legacy import detect_text
        v2 = ('class B {\n  static E(b) {\n    if b is String\n      return 1\n    if b = 0\n      return 2\n'
              '    try x() \n    catch TargetError\n      return 3\n  }\n}\nMsgBox npEl.DumpAll()\n'
              'MouseMove found.x, found.y\n')
        self.assertEqual(detect_text(v2), '2')
        self.assertEqual(detect_text('if x <> 5\n  MsgBox no\nname = Bunny\n'), '1')

    def test_falls_back_to_the_other_version(self):
        with tempfile.TemporaryDirectory() as d:
            lib = Path(d, 'lib.ahk')
            lib.write_text('Get(&a?) {\n  return IsSet(a)\n}\n')
            main = Path(d, 'main.ahk')
            # Scored as v1 on its own, but the included library only loads as v2.
            main.write_text('#Include lib.ahk\nSetTimer Tick, -3000\nTick() {\n}\n')
            p = Program(str(main), [], {'backend': 'null', 'gui_errors': False, 'ahk_version': 'auto',
                                        'validate': True})
            self.addCleanup(lambda: p.shutdown())
            self.assertEqual(p.run(), 0)
            self.assertEqual(p.rt.script_version, '2')

if __name__ == '__main__':
    unittest.main()
