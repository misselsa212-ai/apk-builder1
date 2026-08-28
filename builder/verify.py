"""Compatibility entrypoint for APK verification."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).parents[1] / "verify.py"), run_name="__main__")