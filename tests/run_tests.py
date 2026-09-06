#!/usr/bin/env python3
"""Run the whole SkillSafeWerkstatt test suite with the standard library only.

    python3 tests/run_tests.py            # everything
    python3 tests/run_tests.py sync       # only modules whose name contains "sync"
    python3 tests/run_tests.py -q         # quieter output

Exit code 0 means every test passed.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


def build_suite(selectors: list[str]) -> unittest.TestSuite:
    sys.path.insert(0, str(HERE))
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for module_path in sorted(HERE.glob("test_*.py")):
        name = module_path.stem
        if selectors and not any(selector in name for selector in selectors):
            continue
        suite.addTests(loader.loadTestsFromName(name))
    return suite


def main(argv: list[str]) -> int:
    verbosity = 1 if "-q" in argv else 2
    selectors = [item for item in argv if not item.startswith("-")]
    suite = build_suite(selectors)
    if suite.countTestCases() == 0:
        print(f"no tests matched {selectors}", file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
