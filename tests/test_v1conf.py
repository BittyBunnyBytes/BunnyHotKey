"""AutoHotkey v1 conformance checks (tests/v1conf, run by tools/v1_conformance.py) must all pass."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import v1_conformance


class V1Conformance(unittest.TestCase):
    def test_suites(self):
        for suite in v1_conformance.SUITES:
            with self.subTest(suite=suite):
                passed, total = v1_conformance.run(suite, verbose=True)
                self.assertEqual(passed, total)


if __name__ == '__main__':
    unittest.main()
