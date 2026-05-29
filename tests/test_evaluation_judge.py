from math_agent.evaluation.judge import normalized_match, symbolic_match


def test_normalized_match_is_case_insensitive_for_text_answers() -> None:
    assert normalized_match(r"\text{Elliptic}", "elliptic")
    assert normalized_match("Yes", "yes")


def test_symbolic_match_treats_e_as_euler_constant() -> None:
    assert symbolic_match("e^2", "exp(2)")
