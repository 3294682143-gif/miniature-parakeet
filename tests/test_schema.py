from math_agent.schemas import MathResult


def test_math_result_schema():
    obj = MathResult(
        question_id='q1',
        question='1+1=?',
        answer='2',
        explanation='ok',
        success=True,
        metadata={'mode': 'mock'},
    )
    data = obj.model_dump()
    assert data['answer'] == '2'
    assert data['success'] is True
