"""v1 compatibility regressions, with input confined to the null backend."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bunnyhotkey.loader import Program
from bunnyhotkey.backends import get_backend
from bunnyhotkey.errors import AhkSyntaxError, ReturnEx
from bunnyhotkey.objects import BuiltinFunc

ROOT = Path(__file__).parent / 'v1'

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

    def test_user_scripts_start(self):
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        for path in ROOT.glob('*.ahk'):
            with self.subTest(script=path.name):
                p, auto, hot = self.load(path)
                try:
                    auto(None)
                except ReturnEx:
                    pass
                self.assertEqual(p.rt.script_version, '1')
                self.assertTrue(p.rt.is_persistent())

    def test_middle_button_toggle_is_shared(self):
        p, _, hot = self.load(ROOT / 'Toggle Mbutton.ahk')
        b = get_backend(p.rt)
        self.invoke(p, hot, '$Mbutton')
        self.assertEqual(p.rt.globals['toggle'].value, 1)
        self.invoke(p, hot, '$Mbutton')
        self.assertEqual(p.rt.globals['toggle'].value, 0)
        self.assertEqual([e for e in b.log if e[0] == 'button'],
                         [('button', 'MButton', True), ('button', 'MButton', False)])

    def test_mouse_output_parameters(self):
        p, _, hot = self.load(ROOT / 'm3 ro run.ahk')
        b = get_backend(p.rt)
        b.pos = (12, 34)
        self.invoke(p, hot, 'XButton1')
        self.assertEqual(p.rt.globals['mx'].value, 12)
        self.assertEqual(p.rt.globals['my'].value, 34)
        self.assertFalse(b.down)

    def test_loops_can_toggle_off(self):
        for filename, key in [('Forest.ahk', 'P'), ('Autoclicker.ahk', '~x')]:
            p, _, hot = self.load(ROOT / filename)
            b = get_backend(p.rt)
            if filename == 'Autoclicker.ahk':
                self.invoke(p, hot, '~c')
            def sleep(ms):
                p.rt.globals['toggle'].value = 0
            p.rt.builtins['sleep'] = BuiltinFunc('Sleep', sleep, 1, 1)
            # Builtins are captured during compilation: reload after replacing.
            auto, hot = p.loader.load(str(ROOT / filename))
            self.invoke(p, hot, key)
            self.assertEqual(p.rt.globals['toggle'].value, 0)
            self.assertTrue(b.log)

    def test_window_conditions(self):
        p, _, hot = self.load(ROOT / 'Rainworld P1.ahk')
        directives = [n for kind, n, fn in hot if kind == 'directive' and n.name.lower() == 'hotif']
        self.assertEqual(directives[0].args, 'WinActive("Rain World")')
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

if __name__ == '__main__':
    unittest.main()
