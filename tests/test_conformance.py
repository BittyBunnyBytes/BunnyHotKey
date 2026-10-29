"""Run-test conformance suites (tests/conformance, tools/conformance.py).

Each suite must keep at least the pass count recorded in tests/conformance/baseline.json, so a
regression fails here while known gaps (sections that fail today) don't. Suites marked "desktop"
drive the real X11 session and only run with BHK_DESKTOP_TESTS=1.
"""
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import conformance


class Conformance(unittest.TestCase):
    def test_suites(self):
        base = json.loads((ROOT / 'tests' / 'conformance' / 'baseline.json').read_text())
        for suite in conformance.suites():
            meta, _ = conformance.load(suite)
            if meta['desktop'] and os.environ.get('BHK_DESKTOP_TESTS') != '1':
                continue
            with self.subTest(suite=suite):
                passed, total = conformance.run(suite, verbose=True)
                self.assertGreaterEqual(passed, base.get(suite, total))


if __name__ == '__main__':
    unittest.main()
