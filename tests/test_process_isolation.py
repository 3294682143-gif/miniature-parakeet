from __future__ import annotations

import threading

import pytest

import math_agent.clients.interns1_client as client_module
import math_agent.process_isolation as isolation
from math_agent.tools.python_sandbox import run_python_code
from math_agent.tools.sympy_tools import simplify_expression


def test_isolated_process_budget_rejects_excess_parallel_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(isolation, "_PROCESS_SLOTS", threading.BoundedSemaphore(1))
    monkeypatch.setattr(isolation, "PROCESS_SLOT_WAIT_SECONDS", 0.01)

    with isolation.isolated_process_slot():
        with pytest.raises(isolation.ProcessCapacityError):
            with isolation.isolated_process_slot():
                raise AssertionError("capacity rejection must happen first")


def test_isolated_process_budget_releases_the_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(isolation, "_PROCESS_SLOTS", threading.BoundedSemaphore(1))

    with isolation.isolated_process_slot():
        pass
    with isolation.isolated_process_slot():
        pass


def test_all_worker_entry_points_share_the_same_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(isolation, "_PROCESS_SLOTS", threading.BoundedSemaphore(1))
    monkeypatch.setattr(isolation, "PROCESS_SLOT_WAIT_SECONDS", 0.01)

    with isolation.isolated_process_slot():
        sympy_result = simplify_expression("1+1")
        python_result = run_python_code("print(1 + 1)")
        http_result = client_module._run_isolated_http(
            {
                "url": "https://example.com/chat/completions",
                "api_key": "",
                "payload": {},
                "timeout": 1,
            },
            1,
        )

    assert sympy_result.startswith("ERROR:")
    assert python_result["status"] == "error"
    assert "capacity" in python_result["result_summary"].casefold()
    assert http_result == {"ok": False, "error": "capacity"}
