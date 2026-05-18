import json
import subprocess
import sys

from math_agent.harness.budget_scheduler import (
    BudgetDecision,
    allocate_budget,
    budget_decision_to_dict,
    clamp_candidate_count,
    explain_budget_decision,
    infer_domain,
    load_budget_config,
)


def test_load_budget_config_ok():
    cfg = load_budget_config("configs/budgets.yaml")
    assert cfg["easy"]["max_candidates"] == 1
    assert cfg["hard"]["max_model_calls"] == 7


def test_load_budget_config_missing_fallback(tmp_path):
    cfg = load_budget_config(str(tmp_path / "missing.yaml"))
    assert cfg["standard"]["max_candidates"] == 2


def test_load_budget_config_bad_yaml_fallback(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("easy: [", encoding="utf-8")
    cfg = load_budget_config(str(bad))
    assert cfg["easy"]["timeout_seconds"] == 30


def test_clamp_budget_levels():
    cfg = load_budget_config()
    assert clamp_candidate_count(99, "easy", "unknown", cfg) == 1
    assert clamp_candidate_count(99, "standard", "unknown", cfg) == 2
    assert clamp_candidate_count(99, "hard", "unknown", cfg) == 2


def test_clamp_domain_limits():
    cfg = load_budget_config()
    assert clamp_candidate_count(9, "hard", "proof", cfg) == 2
    assert clamp_candidate_count(9, "hard", "topology", cfg) == 2
    assert clamp_candidate_count(9, "hard", "calculation", cfg) == 1
    assert clamp_candidate_count(9, "hard", "equation", cfg) == 1


def test_invalid_budget_fallback_standard():
    d = allocate_budget(requested_budget="invalid")
    assert d.budget_name == "standard"
    assert any("fallback to standard" in w for w in d.warnings)


def test_invalid_candidate_fallback_to_one():
    d = allocate_budget(requested_candidate_count=0)
    assert d.max_candidates == 1


def test_voting_flags():
    d1 = allocate_budget(request_voting=False, requested_candidate_count=5, requested_budget="hard")
    assert not d1.enable_voting
    d2 = allocate_budget(request_voting=True, requested_candidate_count=1, requested_budget="easy")
    assert not d2.enable_voting


def test_mode_overrides():
    d = allocate_budget(mode="tool-first")
    assert d.tool_first is True
    d_fast = allocate_budget(mode="fast", requested_budget="hard", requested_candidate_count=5)
    assert d_fast.budget_name == "easy"
    assert d_fast.max_candidates <= 1


def test_infer_domain_proof_like():
    domain = infer_domain(question="Prove that identity element is unique")
    assert domain in {"proof", "proof-like"}


def test_explain_and_json_dumpable():
    d = allocate_budget()
    text = explain_budget_decision(d)
    assert isinstance(text, str) and text
    dumped = json.dumps(budget_decision_to_dict(d), ensure_ascii=False)
    assert "budget_name" in dumped
    manual = BudgetDecision(**budget_decision_to_dict(d))
    assert json.dumps(budget_decision_to_dict(manual))


def test_cli_behaviour_unchanged_and_mock(tmp_path):
    cmd = [sys.executable, "-m", "math_agent.cli", "solve", "--question", "1+1=?"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(proc.stdout.strip())
    assert data["status"] in {"success", "partial", "fail"}

    in_file = tmp_path / "in.jsonl"
    out_file = tmp_path / "out.jsonl"
    in_file.write_text('{"question_id":"q1","question":"1+1=?"}\\n', encoding="utf-8")
    cmd2 = [sys.executable, "-m", "math_agent.cli", "batch", "--input", str(in_file), "--output", str(out_file)]
    subprocess.run(cmd2, capture_output=True, text=True, check=True)
