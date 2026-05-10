from math_agent.tools.answer_normalizer import (
    extract_boxed_answer,
    normalize_answer,
    normalize_latex,
    normalize_number,
)


def test_extract_boxed_answer() -> None:
    assert extract_boxed_answer(r"推导... \\boxed{42}") == "42"


def test_extract_final_answer_cn() -> None:
    assert normalize_answer("最终答案： 3/4") == "3/4"


def test_extract_answer_en() -> None:
    assert normalize_answer("Answer: 12") == "12"


def test_normalize_latex_basic() -> None:
    assert normalize_latex(r"\\left( x^2 \\right)") == "( x**2 )"


def test_normalize_number_basic() -> None:
    assert normalize_number("3.0000") == "3"
