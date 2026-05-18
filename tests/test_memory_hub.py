from pathlib import Path

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
        reason="Authorization: abc Bearer token",
        route_info={"domain": "proof", "api_key": "secret", "Authorization": "hidden"},
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
