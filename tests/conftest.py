from __future__ import annotations

import os
from pathlib import Path


def _prefer_current_source_for_test_subprocesses() -> None:
    """Ensure subprocess tests exercise this checkout, not a stale editable install."""
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    existing = os.environ.get("PYTHONPATH", "")
    entries = [entry for entry in existing.split(os.pathsep) if entry]
    normalized = {os.path.normcase(os.path.abspath(entry)) for entry in entries}
    if os.path.normcase(os.path.abspath(source_root)) not in normalized:
        entries.insert(0, source_root)
    os.environ["PYTHONPATH"] = os.pathsep.join(entries)


_prefer_current_source_for_test_subprocesses()
