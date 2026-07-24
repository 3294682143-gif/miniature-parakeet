import time

from math_agent.evaluation.judge import normalized_match, symbolic_match


def test_normalized_match_is_case_insensitive_for_text_answers() -> None:
    assert normalized_match(r"\text{Elliptic}", "elliptic")
    assert normalized_match("Yes", "yes")


def test_symbolic_match_treats_e_as_euler_constant() -> None:
    assert symbolic_match("e^2", "exp(2)")


def test_symbolic_match_supports_implicit_multiplication() -> None:
    assert symbolic_match("2x", "x+x")


def test_symbolic_match_rejects_python_execution_syntax() -> None:
    assert symbolic_match("len([1, 2])", "2") is False
    assert symbolic_match("Symbol.__class__", "Symbol") is False


def test_symbolic_match_has_a_hard_algorithmic_time_limit() -> None:
    expression = "+".join(
        f"sin({index}*x)/cos({index}*x)-tan({index}*x)" for index in range(1, 11)
    )
    started = time.perf_counter()

    symbolic_match(expression, "0")

    assert time.perf_counter() - started < 5.0


def test_deep_latex_fraction_normalization_is_bounded() -> None:
    value = "1"
    for _ in range(6_000):
        value = rf"\frac{{{value}}}{{1}}"
    started = time.perf_counter()

    assert normalized_match(value, value) is False
    assert time.perf_counter() - started < 0.5


def test_conflicting_units_are_not_treated_as_equal() -> None:
    assert normalized_match("1 m", "1 cm") is False
    assert normalized_match("1 kg", "1 g") is False


def test_distinct_large_decimals_do_not_collapse_through_float() -> None:
    assert normalized_match("10000000000000000.1", "10000000000000000.9") is False


def test_dirty_or_conflicting_final_answer_payloads_are_rejected() -> None:
    assert normalized_match("Final answer: 5\nCorrection: 6", "5") is False
    assert normalized_match("Final answer: 5\nFinal answer: 6", "5") is False
    assert normalized_match(r"\boxed{6}\n\boxed{5}", "5") is False
