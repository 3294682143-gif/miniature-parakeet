from __future__ import annotations

import json
import os
import subprocess
import sys


def test_smoke_interns1_defaults_to_mock() -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "scripts/smoke_interns1.py"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["mode"] == "mock"
    assert payload["preview"]


def test_smoke_interns1_real_requires_allow_real() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/smoke_interns1.py", "--real"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error_type"] == "real_requires_allow_real"
