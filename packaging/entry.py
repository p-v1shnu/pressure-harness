"""Entry point for the packaged executable.

Separate from the console script so PyInstaller has one obvious module to start
from, and so the frozen build and `pip install` cannot drift apart.
"""

import multiprocessing
import sys

from pharness.cli import main

if __name__ == "__main__":
    # Without this, a frozen build that starts a subprocess of itself re-runs
    # the whole program instead. Cheap to add, confusing to debug.
    multiprocessing.freeze_support()
    sys.exit(main())
