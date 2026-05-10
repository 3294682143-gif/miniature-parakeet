import ast
from pathlib import Path


def test_no_eval_in_business_code():
    for path in Path('src/math_agent').rglob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != 'eval', f"eval call found in {path}"
