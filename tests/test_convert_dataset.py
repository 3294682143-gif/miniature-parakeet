import json
import subprocess
import sys
from pathlib import Path


SCRIPT = [sys.executable, "scripts/convert_dataset.py"]


def _run_convert(input_path: Path, output_path: Path):
    return subprocess.run(
        [*SCRIPT, "--input", str(input_path), "--output", str(output_path)],
        capture_output=True,
        text=True,
    )


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").strip().splitlines()] if path.exists() and path.read_text(encoding="utf-8").strip() else []


def test_jsonl_input_conversion(tmp_path: Path):
    in_file = tmp_path / "raw.jsonl"
    out_file = tmp_path / "official.jsonl"
    in_file.write_text(
        '{"id":"a1","question":"Q1"}\n'
        '{"question_id":"b2","problem":"Q2"}\n'
        '{"question_id":"c3","question":"Q3"}\n',
        encoding="utf-8",
    )

    proc = _run_convert(in_file, out_file)
    assert proc.returncode == 0
    rows = _read_jsonl(out_file)
    assert rows == [
        {"question_id": "a1", "question": "Q1"},
        {"question_id": "b2", "question": "Q2"},
        {"question_id": "c3", "question": "Q3"},
    ]


def test_json_input_conversion(tmp_path: Path):
    in_file = tmp_path / "raw.json"
    out_file = tmp_path / "official.jsonl"
    in_file.write_text(
        json.dumps([
            {"id": "x1", "question": "A"},
            {"question_id": "x2", "problem": "B"},
        ], ensure_ascii=False),
        encoding="utf-8",
    )

    proc = _run_convert(in_file, out_file)
    assert proc.returncode == 0
    assert _read_jsonl(out_file) == [
        {"question_id": "x1", "question": "A"},
        {"question_id": "x2", "question": "B"},
    ]


def test_txt_input_conversion(tmp_path: Path):
    in_file = tmp_path / "raw.txt"
    out_file = tmp_path / "official.jsonl"
    in_file.write_text("题目一\n\n题目二\n\n\n题目三", encoding="utf-8")

    proc = _run_convert(in_file, out_file)
    assert proc.returncode == 0
    assert _read_jsonl(out_file) == [
        {"question_id": "official_001", "question": "题目一"},
        {"question_id": "official_002", "question": "题目二"},
        {"question_id": "official_003", "question": "题目三"},
    ]


def test_preserve_question_id_and_id_conversion_and_skip_empty(tmp_path: Path):
    in_file = tmp_path / "raw.jsonl"
    out_file = tmp_path / "official.jsonl"
    in_file.write_text(
        '{"question_id":"keep_me","question":"ok"}\n'
        '{"id":"legacy_id","problem":"use me"}\n'
        '{"question":"auto id"}\n'
        '{"question":"   "}\n'
        '{"problem":""}\n',
        encoding="utf-8",
    )

    proc = _run_convert(in_file, out_file)
    assert proc.returncode == 0
    assert _read_jsonl(out_file) == [
        {"question_id": "keep_me", "question": "ok"},
        {"question_id": "legacy_id", "question": "use me"},
        {"question_id": "official_001", "question": "auto id"},
    ]


def test_invalid_input_no_dirty_output(tmp_path: Path):
    in_file = tmp_path / "broken.jsonl"
    out_file = tmp_path / "official.jsonl"
    in_file.write_text('{"question":"ok"}\n{not valid json}\n', encoding="utf-8")

    proc = _run_convert(in_file, out_file)
    assert proc.returncode != 0
    assert "Error:" in proc.stderr
    if out_file.exists():
        assert out_file.read_text(encoding="utf-8") == ""


def test_output_lines_are_valid_json(tmp_path: Path):
    in_file = tmp_path / "raw.txt"
    out_file = tmp_path / "official.jsonl"
    in_file.write_text("Q1\n\nQ2", encoding="utf-8")

    proc = _run_convert(in_file, out_file)
    assert proc.returncode == 0
    for line in out_file.read_text(encoding="utf-8").splitlines():
        parsed = json.loads(line)
        assert set(parsed.keys()) == {"question_id", "question"}
