from math_agent.agents.verifier import Verifier


class DummyClient:
    def __init__(self, reply: str = '{"method":"self_review","passed":true,"notes":"ok"}') -> None:
        self.reply = reply

    def chat(self, _messages):
        return self.reply


def test_mock_passed_true() -> None:
    verifier = Verifier(client=DummyClient(), mock=True)
    result = verifier.verify("q", "draft", "answer")
    assert result.passed is True


def test_numeric_check() -> None:
    verifier = Verifier(client=DummyClient(), mock=False)
    result = verifier.verify("q", "最终答案：0.3333333", "1/3")
    assert result.method == "numeric_check"
    assert result.passed is True


def test_symbolic_check() -> None:
    verifier = Verifier(client=DummyClient(), mock=False)
    result = verifier.verify("q", "x+x", "2*x")
    assert result.method == "symbolic_check"
    assert result.passed is True


def test_fallback_no_crash() -> None:
    verifier = Verifier(client=DummyClient("not json"), mock=False)
    result = verifier.verify("q", "nonsense", "other")
    assert result.method == "self_review"
    assert result.passed is False
