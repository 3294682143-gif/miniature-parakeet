import json

from math_agent.pipeline import MathAgentPipeline


class ProofClient:
    model = "intern-s1"

    def __init__(self):
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return json.dumps({
                "problem_parse": {
                    "goal": "证明任意偶数的平方仍然是偶数",
                    "givens": ["n是偶数"],
                    "symbols": ["n", "k"],
                },
                "solution_plan": ["设n=2k", "平方并整理", "得出偶数结论"],
                "potential_tools": [],
                "risk_points": [],
            }, ensure_ascii=False)
        if self.calls == 2:
            return "设n=2k，则n^2=4k^2=2(2k^2)，故n^2为偶数。\n最终结论：已证明：任意偶数的平方仍然是偶数。\n证毕"
        return json.dumps({"method": "logic_review", "passed": True, "notes": "ok"}, ensure_ascii=False)


def test_proof_final_answer_formatting_and_plan_dict_parsing(tmp_path):
    pipeline = MathAgentPipeline(client=ProofClient(), mock=False, trace_dir=tmp_path)
    result = pipeline.solve("证明任意偶数的平方仍然是偶数", "real_proof_001")

    assert result.final_answer.type == "proof"
    assert ("已证明" in result.final_answer.value) or ("命题已完成证明" in result.final_answer.value)
    assert result.final_answer.boxed == ""
    assert "\n" not in result.final_answer.boxed
    assert "设n=2k" in result.visible_solution_steps[0]

    assert result.solution_plan == ["设n=2k", "平方并整理", "得出偶数结论"]
    assert result.problem_parse.goal == "证明任意偶数的平方仍然是偶数"
    assert "{'problem_parse'" not in " ".join(result.solution_plan)
