from __future__ import annotations

import os
import sys
from pathlib import Path


def prefer_repo_source() -> None:
    """Put this checkout's src tree ahead of stale editable installations."""

    source_root = str(Path(__file__).resolve().parent.parent / "src")
    normalized = os.path.normcase(os.path.abspath(source_root))
    sys.path[:] = [
        entry
        for entry in sys.path
        if os.path.normcase(os.path.abspath(entry or os.curdir)) != normalized
    ]
    sys.path.insert(0, source_root)
