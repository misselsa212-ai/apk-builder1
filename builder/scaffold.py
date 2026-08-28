"""Compatibility entrypoint for the Android project scaffold."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).parents[1] / "scaffold.py"), run_name="__main__")