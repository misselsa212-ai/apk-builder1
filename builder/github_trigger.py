"""Load the repository GitHub Actions client from its compatibility location."""

import importlib.util
from pathlib import Path

_source = Path(__file__).parents[1] / "github_trigger.py"
_spec = importlib.util.spec_from_file_location("_apk_builder_github_trigger", _source)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Unable to load {_source}")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

for _name in dir(_module):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_module, _name)