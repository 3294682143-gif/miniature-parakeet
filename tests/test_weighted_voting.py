import json
import subprocess
import sys

from math_agent.harness.weighted_voting import (
    build_cluster_summary,
    make_candidate_from_solve_result,
    normalize_candidate_answer,
    select_best_candidate,
)
from math_agent.schemas import CandidateAnswer


def _c(cid: str, ans: str, verifier: float, conf: float, **kwargs) -> CandidateAnswer:
    return CandidateAnswer(
        candidate_id=cid,
        source="mock",
        answer_type=kwargs.get("answer_type", "number"),
        final_answer_value=ans,
        final_answer_boxed=kwargs.get("boxed", f"\\boxed{{{ans}}}" if ans else ""),
        normalized_answer="",
        confidence=conf,
        verifier_score=verifier,
        risk_score=kwargs.get("risk_score", 0.0),
        risk_flags=kwargs.get("risk_flags", []),
    )


def test_cluster_same_answers():
    res = select_best_candidate([_c("a", "2", 0.7, 0.7), _c("b", "2.0", 0.65, 0.6), _c("c", "3", 0.4, 0.4)])
    summary = res.cluster_summary
    sizes = sorted(x["size"] for x in summary)
    assert sizes[-1] >= 2


def test_not_blind_majority_low_verifier():
    res = select_best_candidate([_c("a", "5", 0.1, 0.9), _c("b", "5", 0.1, 0.8), _c("c", "6", 0.9, 0.7)])
    assert res.selected_candidate_id == "c"


def test_minor_high_verifier_wins():
    res = select_best_candidate([_c("a", "8", 0.2, 0.7), _c("b", "8", 0.2, 0.7), _c("c", "9", 0.92, 0.8, risk_score=0.0)])
    assert res.selected_candidate_id == "c"


def test_empty_final_penalized():
    res = select_best_candidate([_c("a", "", 0.9, 0.9), _c("b", "11", 0.5, 0.4)])
    assert res.selected_candidate_id == "b"


def test_boxed_42_fallback_penalized():
    res = select_best_candidate([_c("a", "42", 0.85, 0.8, boxed="\\boxed{42}"), _c("b", "41", 0.75, 0.7)])
    assert res.selected_candidate_id == "b"


def test_dirty_boxed_penalized():
    res = select_best_candidate([_c("a", "17", 0.9, 0.8, boxed="```text\n17\n```"), _c("b", "16", 0.8, 0.75)])
    assert res.selected_candidate_id == "b"


def test_proof_use_verifier_confidence():
    res = select_best_candidate([
        _c("a", "Proof text A", 0.9, 0.9, answer_type="proof"),
        _c("b", "Proof text B", 0.4, 0.6, answer_type="proof"),
    ])
    assert res.selected_candidate_id == "a"


def test_close_gap_need_more_verification():
    res = select_best_candidate([_c("a", "21", 0.81, 0.8), _c("b", "21", 0.8, 0.8)])
    assert res.need_more_verification is True


def test_empty_candidates_safe_fail():
    res = select_best_candidate([])
    assert res.selected_candidate_id is None
    assert "no_valid_candidate" in res.issues


def test_bad_dict_not_crash():
    res = select_best_candidate([{"foo": "bar"}, _c("b", "3", 0.6, 0.6).model_dump()])
    assert res.selected_candidate_id == "b"


def test_result_json_dumps_and_summary_jsonable():
    cands = [normalize_candidate_answer(_c("a", "2", 0.8, 0.8)), normalize_candidate_answer(_c("b", "2", 0.7, 0.7))]
    summary = build_cluster_summary(cands)
    json.dumps(summary, ensure_ascii=False)
    json.dumps(select_best_candidate(cands).model_dump(), ensure_ascii=False)


def test_make_candidate_from_solve_result_reads_boxed():
    result = {
        "question_id": "q1",
        "domain": "algebra",
        "problem_type": "equation",
        "problem_parse": {"goal": "x+1=2", "givens": [], "symbols": ["x"]},
        "solution_plan": ["isolate x"],
        "visible_solution_steps": ["x=1"],
        "tool_trace": [{"tool": "none", "purpose": "n/a", "status": "skipped", "summary": "n/a"}],
        "final_answer": {"type": "number", "value": "1", "boxed": "\\boxed{1}"},
        "verification": {"method": "numeric_check", "passed": True, "notes": "ok"},
        "didactic_hint": "hint",
        "confidence": 0.8,
        "status": "success",
    }
    candidate = make_candidate_from_solve_result(result, candidate_id="cand1", source="mock")
    assert candidate.final_answer_boxed == "\\boxed{1}"


def test_cli_mock_solve_and_batch_still_work(tmp_path):
    p1 = subprocess.run([sys.executable, "-m", "math_agent.cli", "solve", "--question", "1+1=?"], capture_output=True, text=True, check=True)
    assert json.loads(p1.stdout)["status"] in {"success", "partial", "fail"}

    in_file = tmp_path / "in.jsonl"
    in_file.write_text('{"question_id":"q1","question":"1+1=?"}\n{"question_id":"q2","question":"2+2=?"}\n', encoding="utf-8")
    out_file = tmp_path / "out.jsonl"
    subprocess.run([sys.executable, "-m", "math_agent.cli", "batch", "--input", str(in_file), "--output", str(out_file)], capture_output=True, text=True, check=True)
    assert out_file.exists()
