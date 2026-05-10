from math_agent.pipeline import solve_question
from math_agent.schemas import MathQuestion, SolveResult


def test_pipeline_mock_success():
    result = solve_question(MathQuestion(question_id='q1', question='1+1=?'), mock=True)
    assert isinstance(result, SolveResult)
    assert result.status == 'success'
    assert result.final_answer.value == '2'


def test_pipeline_mock_failure_json_safe():
    result = solve_question(MathQuestion(question_id='q3', question='1/0=?'), mock=True)
    assert result.status == 'fail'
    assert isinstance(result.model_dump_json(), str)
