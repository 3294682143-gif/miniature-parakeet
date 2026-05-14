from math_agent.tools.answer_normalizer import (
    extract_answer_by_patterns,
    extract_boxed_answer,
    normalize_answer,
    normalize_latex,
    normalize_number,
)


def test_extract_boxed_answer() -> None:
    assert extract_boxed_answer(r"推导... \\boxed{42}") == "42"


def test_extract_boxed_answer_nested_frac() -> None:
    assert extract_boxed_answer(r"过程... \\boxed{\\dfrac{1}{4}}") == r"\dfrac{1}{4}"


def test_extract_boxed_answer_last_one_from_long_text() -> None:
    txt = r"先有 \\boxed{1}，再讨论，最后 \\boxed{\\frac{a+b}{2}}"
    assert extract_boxed_answer(txt) == r"\frac{a+b}{2}"


def test_extract_final_answer_cn() -> None:
    assert normalize_answer("最终答案： 3/4") == "3/4"


def test_extract_answer_en() -> None:
    assert normalize_answer("Answer: 12") == "12"


def test_extract_answer_patterns_equation_markdown() -> None:
    out = extract_answer_by_patterns("**答案**：$x = 4$")
    assert out in {"x = 4", "x=4"}


def test_normalize_latex_basic() -> None:
    assert normalize_latex(r"\\left( x^2 \\right)") == "( x**2 )"


def test_normalize_number_basic() -> None:
    assert normalize_number("3.0000") == "3"
