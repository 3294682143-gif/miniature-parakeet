from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

STRONG_SCAN_DIRS = {"src", "scripts", "configs", "submission"}
SKIP_TEXT_DIRS = {".git", ".venv", "venv", "node_modules", "outputs", "trace", "run_records", "__pycache__", ".pytest_cache"}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".yaml", ".yml", ".json", ".jsonl", ".toml", ".ini", ".cfg", ".sh"}

API_KEY_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bINTERNS1_API_KEY\s*=\s*[\"']?[A-Za-z0-9._-]{12,}[\"']?"),
]
AUTH_PATTERNS = [
    re.compile(r"\bAuthorization\s*:\s*\S+", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{10,}\b", re.IGNORECASE),
]


def _is_probably_doc(path: Path) -> bool:
    return any(part in {"README", "docs"} for part in path.parts) or path.suffix.lower() == ".md"


def _iter_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_TEXT_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            yield path


def scan_project(root: Path) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []

    for path in root.rglob(".env"):
        if path.is_file() and path.name != ".env.example":
            findings.append((str(path.relative_to(root)), "forbidden_env_file"))

    forbidden_paths = [
        ("official_results.jsonl", "forbidden_official_results_file"),
        ("submission.zip", "forbidden_submission_archive"),
    ]
    for rel, risk in forbidden_paths:
        p = root / rel
        if p.exists():
            findings.append((rel, risk))

    for pattern, risk in [
        ("outputs/*.jsonl", "forbidden_outputs_jsonl"),
        ("outputs/traces/**", "forbidden_outputs_traces"),
        ("outputs/run_records/**", "forbidden_outputs_run_records"),
        ("trace/**", "forbidden_trace_dir"),
        ("run_records/**", "forbidden_run_records_dir"),
    ]:
        for p in root.glob(pattern):
            if p.exists():
                findings.append((str(p.relative_to(root)), risk))

    for cache in ["__pycache__", ".pytest_cache"]:
        for p in root.rglob(cache):
            findings.append((str(p.relative_to(root)), f"forbidden_{cache}_artifact"))

    git_path = root / ".git"
    if git_path.is_file():
        findings.append((".git", "git_packaging_risk"))

    for path in _iter_text_files(root):
        rel = path.relative_to(root)
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        in_strong_dir = rel.parts and rel.parts[0] in STRONG_SCAN_DIRS
        is_doc = _is_probably_doc(rel)

        if in_strong_dir or not is_doc:
            for pat in API_KEY_PATTERNS:
                if pat.search(text):
                    findings.append((str(rel), "suspected_api_key"))
                    break
            for pat in AUTH_PATTERNS:
                if pat.search(text):
                    findings.append((str(rel), "suspected_auth_token"))
                    break

    # de-duplicate
    return sorted(set(findings))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check project for risky files or secret leakage.")
    parser.add_argument("--root", default=".", help="Project root directory to scan")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    findings = scan_project(root)

    if findings:
        print("FAIL")
        for rel_path, risk in findings:
            print(f"- {risk}: {rel_path}")
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
