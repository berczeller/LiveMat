"""Run the test suite inside a headless Blender.

    blender -b --factory-startup --python tests/run_tests.py

Exits with code 1 when any test fails.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(ROOT / "tests"), top_level_dir=str(ROOT)
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


main()
