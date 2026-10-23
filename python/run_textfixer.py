"""Entry point for the packaged .exe (PyInstaller) and for `python run_textfixer.py`."""

import sys

from textfixer.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
