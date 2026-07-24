# safety: allow-secret-fixtures
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from math_agent.harness.memory import MemoryHub


def test_init_does_not_write_files(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    MemoryHub(root=str(root))
    assert not root.exists()


def test_load_error_taxonomy_success() -> None:
    hub = MemoryHub(root="memory")
    taxonomy = hub.load_error_taxonomy()
    assert "bad_json" in taxonomy
    assert taxonomy["bad_json"]["risk_level"] == "high"


def test_load_regression_cases_success() -> None:
    hub = MemoryHub(root="memory")
    cases = hub.load_regression_cases()
    assert isinstance(cases.get("cases"), list)
    assert len(cases["cases"]) >= 1


def test_missing_files_safe_fallback(tmp_path: Path) -> None:
    hub = MemoryHub(root=str(tmp_path / "missing-memory"))
    assert hub.load_route_stats()["total"] == 0
    assert hub.load_regression_cases()["cases"] == []


def test_bad_json_safe_fallback(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    root.mkdir(parents=True)
    (root / "route_stats.json").write_text("{bad", encoding="utf-8")
    hub = MemoryHub(root=str(root))
    stats = hub.load_route_stats()
    assert stats["total"] == 0
    assert "warning" in stats


def test_yaml_alias_dag_is_processed_once_not_exponentially(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    lines = ["a0: &a0 [0,0,0,0,0,0,0,0]"]
    for level in range(1, 9):
        previous = f"a{level - 1}"
        lines.append(
            f"a{level}: &a{level} [" + ",".join(f"*{previous}" for _ in range(8)) + "]"
        )
    lines.append("cases: *a8")
    (root / "regression_cases.yaml").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    started = time.perf_counter()

    loaded = MemoryHub(root=str(root)).load_regression_cases()

    assert isinstance(loaded, dict)
    assert time.perf_counter() - started < 1.0


def test_record_route_result_explicit_write(tmp_path: Path) -> None:
    hub = MemoryHub(root=str(tmp_path / "memory"))
    hub.record_route_result(domain="algebra", problem_type="equation", status="success")
    stats = hub.load_route_stats()
    assert stats["total"] == 1
    assert stats["by_domain"]["algebra"] == 1


def test_record_skill_result_explicit_write(tmp_path: Path) -> None:
    hub = MemoryHub(root=str(tmp_path / "memory"))
    hub.record_skill_result(skill_name="proof", status="success")
    stats = hub.load_skill_success_stats()
    assert stats["total"] == 1
    assert stats["skills"]["proof"]["by_status"]["success"] == 1


def test_record_verifier_failure_filters_sensitive_fields(tmp_path: Path) -> None:
    hub = MemoryHub(root=str(tmp_path / "memory"))
    hub.record_verifier_failure(
        question_id="q1",
        reason="Authorization: abc Bearer token",  # safety: allow-mock-token
        route_info={"domain": "proof", "api_key": "secret", "Authorization": "ok"},
    )
    payload = hub.load_verifier_failures()
    item = payload["items"][0]
    assert "api_key" not in item["route_info"]
    assert "Authorization" not in item["route_info"]
    assert "Bearer" not in item["reason"]


def test_add_regression_case_truncates_long_question(tmp_path: Path) -> None:
    hub = MemoryHub(root=str(tmp_path / "memory"))
    long_question = "Q" * 260
    hub.add_regression_case({"case_id": "x", "question": long_question})
    data = hub.load_regression_cases()
    saved = data["cases"][0]
    assert saved["question"].endswith("...[truncated]")
    assert saved["question_truncated"] is True


def test_summarize_memory() -> None:
    hub = MemoryHub(root="memory")
    summary = hub.summarize_memory()
    assert "route_total" in summary
    assert "regression_cases_total" in summary


def test_concurrent_route_writes_do_not_lose_updates(tmp_path: Path) -> None:
    root = tmp_path / "memory"

    def record(_: int) -> None:
        MemoryHub(root=str(root)).record_route_result(
            domain="algebra", problem_type="equation", status="success"
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(record, range(40)))

    stats = MemoryHub(root=str(root)).load_route_stats()
    assert stats["total"] == 40
    assert stats["by_domain"]["algebra"] == 40


def test_all_memoryhub_write_sinks_redact_credentials(tmp_path: Path) -> None:
    secret = "https://reviewer:SUPER_SECRET_PASSWORD@example.invalid/api"
    root = tmp_path / "memory"
    hub = MemoryHub(root=str(root))

    hub.record_route_result(secret, secret, secret)
    hub.record_skill_result(secret, secret)
    hub.record_verifier_failure(secret, secret, {"domain": secret})
    hub.record_answer_cluster(secret, secret, 1, True)

    rendered = "\n".join(
        path.read_text(encoding="utf-8") for path in root.iterdir() if path.is_file()
    )
    assert secret not in rendered
    assert "[REDACTED]" in rendered


def test_memoryhub_load_rejects_invalid_utf8(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    (root / "route_stats.json").write_bytes(b"\xff\xfe")

    stats = MemoryHub(root=str(root)).load_route_stats()

    assert stats["total"] == 0
    assert stats["warning"].startswith("invalid_memory_encoding:")


def test_memoryhub_load_rejects_hardlinked_file(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    source = tmp_path / "outside.json"
    source.write_text('{"total": 99}', encoding="utf-8")
    try:
        os.link(source, root / "route_stats.json")
    except OSError:
        pytest.skip("hard links are unavailable on this host")

    stats = MemoryHub(root=str(root)).load_route_stats()

    assert stats["total"] == 0
    assert stats["warning"].startswith("unsafe_memory_file:")


def test_memoryhub_load_enforces_actual_size_limit(tmp_path: Path, monkeypatch) -> None:
    import math_agent.harness.memory as memory_module

    root = tmp_path / "memory"
    root.mkdir()
    (root / "route_stats.json").write_text('{"padding":"1234567890"}')
    monkeypatch.setattr(memory_module, "MAX_MEMORY_FILE_BYTES", 8)

    stats = MemoryHub(root=str(root)).load_route_stats()

    assert stats["total"] == 0
    assert stats["warning"].startswith("unsafe_memory_file:")


def test_memoryhub_json_and_yaml_sinks_redact_extended_keys_and_containers(
    tmp_path: Path,
) -> None:
    secret = "sk-MOCK_MEMORY_CONTAINER_SECRET_1234567890"
    root = tmp_path / "memory"
    hub = MemoryHub(root=str(root))

    hub.record_verifier_failure(
        "q1",
        "AWS_SECRET_ACCESS_KEY=MOCK_AWS_VALUE",
        {
            "AWS_SECRET_ACCESS_KEY": "MOCK_AWS_VALUE",
            "client_secret_value": "MOCK_CLIENT_VALUE",
        },
    )
    hub.add_regression_case(
        {
            "case_id": "set-case",
            "notes": {secret},
            "raw": secret.encode(),
        }
    )

    rendered = "\n".join(
        path.read_text(encoding="utf-8") for path in root.iterdir() if path.is_file()
    )
    assert secret not in rendered
    assert "MOCK_AWS_VALUE" not in rendered
    assert "MOCK_CLIENT_VALUE" not in rendered
    assert "[REDACTED]" in rendered


def test_memoryhub_rejects_non_finite_json_and_yaml_numbers(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    (root / "route_stats.json").write_text('{"total": NaN}', encoding="utf-8")
    (root / "regression_cases.yaml").write_text(
        "cases:\n  - score: .inf\n", encoding="utf-8"
    )
    hub = MemoryHub(root=str(root))

    stats = hub.load_route_stats()
    cases = hub.load_regression_cases()

    assert stats["total"] == 0
    assert stats["warning"].startswith("invalid_json_number:")
    assert cases["cases"] == []
    assert cases["warning"].startswith("invalid_yaml_number:")

    with pytest.raises(ValueError, match="non-finite"):
        hub.add_regression_case({"case_id": "bad-number", "score": float("inf")})


def test_memoryhub_rejects_duplicate_json_object_keys(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    root.mkdir()
    (root / "route_stats.json").write_text('{"total":1,"total":999}', encoding="utf-8")

    stats = MemoryHub(root=str(root)).load_route_stats()

    assert stats["total"] == 0
    assert stats["warning"].startswith("invalid_json:")


def test_memoryhub_rejects_unsafe_ancestor_for_reads_and_writes(
    tmp_path: Path, monkeypatch
) -> None:
    import math_agent.harness.memory as memory_module

    root = tmp_path / "memory"
    root.mkdir()
    (root / "route_stats.json").write_text('{"total": 99}', encoding="utf-8")
    monkeypatch.setattr(
        memory_module, "path_has_link_component", lambda _path: True, raising=False
    )
    hub = MemoryHub(root=str(root))

    stats = hub.load_route_stats()
    with pytest.raises(OSError, match="unsafe MemoryHub root"):
        hub.record_route_result("algebra", "equation", "success")

    assert stats["total"] == 0
    assert stats["warning"].startswith("unsafe_memory_root:")
