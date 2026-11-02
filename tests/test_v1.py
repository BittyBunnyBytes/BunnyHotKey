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

    def test_open_brace_hotkey_is_not_a_block(self):
        p, _, hot = self.script('#NoEnv\nn := 0\n{::\nn += 1\nreturn\n}::\nn += 10\nreturn\nF1::n := 5\n')
        self.invoke(p, hot, '{')
        self.invoke(p, hot, '}')
        self.assertEqual(p.rt.globals['n'].value, 11)
        self.invoke(p, hot, 'F1')
        self.assertEqual(p.rt.globals['n'].value, 5)

    def test_if_directive_continues_on_the_next_line(self):
        _, _, hot = self.script('#NoEnv\na := 1\n#If (a\n  && a > 0)\nF1::return\n#If\nF2::return\n')
        self.assertEqual({k for kind, node, _ in hot if kind == 'hot' for k in node.keys}, {'F1', 'F2'})

    def test_other_directives_do_not_swallow_the_next_line(self):
        p, auto, _ = self.script('#NoEnv\n#SingleInstance Force\nx := 1\n.5\n')
        self.assertEqual(p.rt.script_version, '1')

    def test_var_class_field(self):
        p, auto, _ = self.script('#NoEnv\nclass A {\n  var x := 7\n  var y\n}\no := new A\nr := o.x\nb := o.y\nh := o.HasKey("y")\n')
        try:
            auto(None)
        except ReturnEx:
            pass
        self.assertEqual(p.rt.globals['r'].value, 7)
        self.assertEqual(p.rt.globals['b'].value, '')
        self.assertTrue(p.rt.globals['h'].value)


class V2HotFunctionTests(unittest.TestCase):
    """A function definition under "key::" (AutoHotkey v2 docs, Named Function Hotkeys)."""

    load = LegacyTests.load
    invoke = LegacyTests.invoke
    script = LegacyTests.script

    def v2(self, text):
        return self.script('#Requires AutoHotkey v2\nout := ""\n' + text)

    def global_after(self, p, hot, key, name='out'):
        self.invoke(p, hot, key)
        return p.rt.globals[name].value

    def test_named_function_gets_the_hotkey_name(self):
        for head in ('Tick(hk) {\n', 'Tick(hk)\n{\n'):
            p, _, hot = self.v2('F1::\n' + head + '  global out\n  out := hk\n}\n')
            self.assertEqual(self.global_after(p, hot, 'F1'), 'F1')

    def test_stacked_hotkeys_share_it_and_it_stays_callable(self):
        p, auto, hot = self.v2('F1::\nF2::\nTick(hk) {\n  global out\n  out .= hk "."\n}\nTick("x")\n')
        try:
            auto(None)
        except ReturnEx:
            pass
        self.invoke(p, hot, 'F1')
        self.invoke(p, hot, 'F2')
        self.assertEqual(p.rt.globals['out'].value, 'x.F1.F2.')

    def test_arrow_function(self):
        p, _, hot = self.v2('F1::\nTick(hk) => Save(hk)\nSave(v) {\n  global out\n  out := v\n}\n')
        self.assertEqual(self.global_after(p, hot, 'F1'), 'F1')

    def test_hotstring_runs_it_instead_of_replacing_with_nothing(self):
        _, _, hot = self.v2('::btw::\nTick(hs) {\n}\n')
        node = next(n for kind, n, _ in hot if kind == 'hot')
        self.assertIsNone(node.replacement)
        self.assertIsNotNone(node.body)

    def test_hotkey_stacked_over_a_hotstring(self):
        _, _, hot = self.v2('F1::\n::btw::\n{\n  global out\n  out := "ran"\n}\n')
        kinds = [n for kind, n, _ in hot if kind == 'hot']
        self.assertEqual(len(kinds), 2)
        self.assertTrue(all(n.body is not None for n in kinds))

    def test_a_call_under_a_hotkey_is_still_an_error(self):
        with self.assertRaises(AhkSyntaxError):
            self.v2('F1::\nTick()\nTick() {\n}\n')

    def test_hotif_expression_spans_lines(self):
        _, _, hot = self.v2('a := 1\n#HotIf (a\n  && a > 0)\nF1::{\n}\n#HotIf\nF2::{\n}\n')
        self.assertEqual({k for kind, n, _ in hot if kind == 'hot' for k in n.keys}, {'F1', 'F2'})

    def test_hotif_does_not_swallow_the_hotkey_after_it(self):
        for key in ('+a', '^a', '*a', '<^a', '~a', '!a', '/', ','):
            _, _, hot = self.v2(f'x := 1\n#HotIf x\n{key}::{{\n}}\n')
            self.assertEqual([k for kind, n, _ in hot if kind == 'hot' for k in n.keys], [key])
        _, _, hot = self.v2('x := 1\n#HotIf x\n::btw::by the way\n')
        self.assertEqual([n.trigger for kind, n, _ in hot if kind == 'hot'], ['btw'])

    def test_keyword_under_a_hotkey_is_still_an_error(self):
        with self.assertRaises(AhkSyntaxError):
            self.v2('F1::\nif (1) {\n}\n')


if __name__ == '__main__':
    unittest.main()
