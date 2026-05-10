import json
import subprocess
import sys
from pathlib import Path


def test_cli_solve_outputs_json():
    cmd = [sys.executable, '-m', 'math_agent.cli', 'solve', '--question', '1+1=?']
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(proc.stdout.strip())
    assert data['question'] == '1+1=?'
    assert 'success' in data


def test_cli_batch_processes_sample(tmp_path: Path):
    in_file = Path('data/sample_questions.jsonl')
    out_file = tmp_path / 'results.jsonl'
    cmd = [sys.executable, '-m', 'math_agent.cli', 'batch', '--input', str(in_file), '--output', str(out_file)]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    lines = out_file.read_text(encoding='utf-8').strip().splitlines()
    assert len(lines) >= 1
    for line in lines:
        parsed = json.loads(line)
        assert 'success' in parsed
