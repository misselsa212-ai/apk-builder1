"""Compatibility entrypoint for APK rebranding."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).parents[1] / "rebrand_apk.py"), run_name="__main__")
