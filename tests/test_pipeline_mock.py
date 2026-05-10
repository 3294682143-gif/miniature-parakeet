from math_agent.pipeline import solve_question
from math_agent.schemas import MathQuestion


def test_pipeline_mock_success():
    result = solve_question(MathQuestion(question_id='q1', question='1+1=?'), mock=True)
    assert result.success is True
    assert result.answer == '2'


def test_pipeline_mock_failure_json_safe():
    result = solve_question(MathQuestion(question_id='q3', question='1/0=?'), mock=True)
    assert result.success is False
    assert isinstance(result.model_dump_json(), str)
