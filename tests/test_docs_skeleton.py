from pathlib import Path


def _read(path: str) -> str:
    p = Path(path)
    assert p.exists(), f"missing file: {path}"
    return p.read_text(encoding="utf-8")


def test_final_report_exists_and_required_content() -> None:
    text = _read("docs/final_report.md")
    assert "EvoExternMath-S1++" in text
    assert "Frozen Harness" in text
    assert ("不人工" in text) or ("official_results.jsonl" in text)
    assert "待填实验结果" in text


def test_architecture_exists_and_mermaid() -> None:
    text = _read("docs/architecture.md")
    assert "Mermaid" in text or "mermaid" in text
    assert "Input" in text and "SolveResult JSON" in text


def test_externalization_design_exists_and_key_terms() -> None:
    text = _read("docs/externalization_design.md")
    assert "Memory" in text
    assert "Skills" in text or "Skill" in text
    assert "Protocol" in text


def test_replay_doc_exists_and_cli_usage() -> None:
    text = _read("docs/replay.md")
    assert "replay_trace.py" in text


def test_submission_checklist_exists_and_required_terms() -> None:
    text = _read("docs/submission_checklist.md")
    assert ".env" in text
    assert "API key" in text
    assert "trace_count" in text
    assert "pytest -q" in text


def test_no_fabricated_official_112_completion_claim() -> None:
    docs = [
        "docs/final_report.md",
        "docs/architecture.md",
        "docs/externalization_design.md",
        "docs/replay.md",
        "docs/submission_checklist.md",
    ]
    banned = ["官方 112 题已完成", "official 112 completed"]
    for doc in docs:
        text = _read(doc)
        for phrase in banned:
            assert phrase not in text, f"found banned phrase '{phrase}' in {doc}"
