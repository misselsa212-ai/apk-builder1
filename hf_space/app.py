"""Compatibility entrypoint for the HuggingFace Space UI."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).parents[1] / "app.py"), run_name="__main__")
