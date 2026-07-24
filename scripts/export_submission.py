from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import stat
import struct
import sys
import tempfile
import unicodedata
import uuid
import zipfile
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from check_project_safety import scan_project, scan_sensitive_files

_REPO_SOURCE = Path(__file__).resolve().parent.parent / "src"
_REPO_SOURCE_KEY = os.path.normcase(os.path.abspath(str(_REPO_SOURCE)))
sys.path[:] = [
    entry
    for entry in sys.path
    if os.path.normcase(os.path.abspath(entry or os.curdir)) != _REPO_SOURCE_KEY
]
sys.path.insert(0, str(_REPO_SOURCE))

import math_agent.schemas as _schema_module  # noqa: E402
from math_agent.io_utils import (  # noqa: E402
    strict_json_loads as _shared_strict_json_loads,
)
from math_agent.schemas import (  # noqa: E402
    SolveResult,
    execution_provenance_fingerprint,
    is_valid_trace_audit_evidence,
)

if not Path(_schema_module.__file__).resolve().is_relative_to(_REPO_SOURCE.resolve()):
    raise ImportError("exporter schema was not loaded from this checkout")

EXCLUDE_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
}

EXCLUDE_FILE_PATTERNS = (
    ".env",
    ".env.",
)
EXPORT_MARKER_NAME = ".evoexternmath-submission.json"
STAGING_SENTINEL_NAME = ".evoexternmath-staging.json"
EXPORT_MARKER_BASE = {
    "format": "evoexternmath-frozen-submission",
    "project": "EvoExternMath-S1++",
    "version": 1,
}
EXPORT_MARKER_KEYS = frozenset(
    {*EXPORT_MARKER_BASE, "files", "out_name", "staging_nonce", "transaction_id"}
)
TRANSACTION_FILE_NAME = ".evoexternmath-export-transaction.json"
MAX_EXPORT_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_EXPORT_ENTRIES = 10_000
MAX_EXPORT_MARKER_BYTES = 2 * 1024 * 1024
MAX_RESULT_BYTES = 64 * 1024 * 1024
MAX_RESULT_LINE_BYTES = 1024 * 1024
MAX_RESULT_ROWS = 100_000
MAX_TRACE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_TRACE_BYTES = 128 * 1024 * 1024
SAFE_OUTPUT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
WINDOWS_RESERVED_OUTPUT_NAMES = {
    "aux",
    "clock$",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
WINDOWS_FORBIDDEN_COMPONENT_CHARS = frozenset('<>:"/\\|?*')
PROTECTED_OUTPUT_ROOTS = {
    ".git",
    ".github",
    "assets",
    "configs",
    "data",
    "demo",
    "docs",
    "evolution",
    "memory",
    "outputs",
    "scripts",
    "skills",
    "src",
    "tests",
}


class ExportSafetyError(ValueError):
    """Raised before mutation when an export path or source is unsafe."""


def _is_excluded_name(name: str) -> bool:
    return name == ".env" or name.startswith(".env.")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_repository_path(repo_root: Path, raw_path: str, label: str) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    if candidate.is_symlink():
        raise ExportSafetyError(f"unsafe {label} path: symbolic links are not allowed")
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ExportSafetyError(f"unsafe {label} path: cannot resolve path") from exc
    if resolved == repo_root or not _is_within(resolved, repo_root):
        raise ExportSafetyError(
            f"unsafe {label} path: path must stay inside the repository"
        )
    return resolved


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _is_safe_output_name(name: str) -> bool:
    base_name = name.casefold().split(".", 1)[0]
    return bool(
        SAFE_OUTPUT_NAME.fullmatch(name)
        and not name.endswith(".")
        and base_name not in WINDOWS_RESERVED_OUTPUT_NAMES
    )


def _portable_relative_path_key(value: str) -> str | None:
    relative = PurePosixPath(value)
    if (
        not value
        or relative.is_absolute()
        or ".." in relative.parts
        or "\\" in value
        or relative.as_posix() != value
    ):
        return None
    normalized_parts: list[str] = []
    for part in relative.parts:
        normalized = unicodedata.normalize("NFC", part)
        stem = normalized.casefold().split(".", 1)[0]
        if (
            not normalized
            or normalized != part
            or normalized.endswith((".", " "))
            or stem in WINDOWS_RESERVED_OUTPUT_NAMES
            or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
            or any(char in WINDOWS_FORBIDDEN_COMPONENT_CHARS for char in normalized)
        ):
            return None
        normalized_parts.append(normalized.casefold())
    return "/".join(normalized_parts)


def _validate_output_dir(
    repo_root: Path,
    out_dir: Path,
    source_paths: list[Path],
    archive_path: Path,
) -> None:
    relative = out_dir.relative_to(repo_root)
    if len(relative.parts) != 1:
        raise ExportSafetyError(
            "unsafe output path: output must be a direct child of the repository"
        )
    if not _is_safe_output_name(relative.name):
        raise ExportSafetyError("unsafe output path: unsupported output name")
    if relative.parts[0].casefold() in PROTECTED_OUTPUT_ROOTS:
        raise ExportSafetyError("unsafe output path: protected repository directory")
    if any(_paths_overlap(out_dir, source) for source in source_paths):
        raise ExportSafetyError("unsafe output path: overlaps an export input")
    if _paths_overlap(out_dir, archive_path):
        raise ExportSafetyError("unsafe output path: overlaps the submission archive")
    if out_dir.is_symlink():
        raise ExportSafetyError("unsafe output path: symbolic links are not allowed")
    if out_dir.exists():
        raise ExportSafetyError(
            "unsafe output path: output already exists and is never overwritten"
        )
    if archive_path.is_symlink() or archive_path.exists():
        raise ExportSafetyError(
            "submission archive already exists and is never overwritten"
        )


def _copyable_tree_files(src: Path) -> list[Path]:
    source_root = src.resolve(strict=True)
    files: list[Path] = []
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        is_junction = getattr(path, "is_junction", lambda: False)()
        if path.is_symlink() or is_junction:
            raise ExportSafetyError(
                "unsafe export source: links and junctions are not allowed"
            )
        if any(part in EXCLUDE_DIR_NAMES for part in rel.parts):
            continue
        if _is_excluded_name(path.name):
            continue
        if path.is_dir():
            continue
        if not path.is_file():
            raise ExportSafetyError("unsafe export source: unsupported file type")
        resolved = path.resolve(strict=True)
        if not _is_within(resolved, source_root):
            raise ExportSafetyError(
                "unsafe export source: path escapes source directory"
            )
        files.append(path)
    return files


def _portable_tree_files(src: Path) -> list[Path]:
    files = _copyable_tree_files(src)
    seen_keys: set[str] = set()
    for path in files:
        relative = path.relative_to(src).as_posix()
        key = _portable_relative_path_key(relative)
        if key is None or key in seen_keys:
            raise ExportSafetyError(
                "unsafe export source: paths must be portable and case-unique"
            )
        seen_keys.add(key)
    return files


def _strict_json_loads(raw: bytes | str) -> object:
    try:
        text = raw.decode("utf-8", errors="strict") if isinstance(raw, bytes) else raw
        return _shared_strict_json_loads(
            text,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ExportSafetyError("submission evidence contains invalid JSON") from exc


def _validate_result_row(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ExportSafetyError("submission result row must be an object")
    required = {
        "question_id",
        "domain",
        "problem_type",
        "problem_parse",
        "solution_plan",
        "visible_solution_steps",
        "tool_trace",
        "final_answer",
        "verification",
        "didactic_hint",
        "confidence",
        "status",
        "error",
        "input_fingerprint",
        "execution_fingerprint",
    }
    if not required.issubset(value):
        raise ExportSafetyError("submission result row is missing required fields")
    question_id = value.get("question_id")
    status_value = value.get("status")
    final_answer = value.get("final_answer")
    verification = value.get("verification")
    problem_parse = value.get("problem_parse")
    confidence = value.get("confidence")
    if (
        not isinstance(question_id, str)
        or not question_id.strip()
        or question_id != question_id.strip()
        or len(question_id) > 128
        or status_value not in {"success", "partial", "fail"}
        or not isinstance(value.get("input_fingerprint"), str)
        or re.fullmatch(r"[0-9a-f]{64}", str(value.get("input_fingerprint"))) is None
        or not isinstance(value.get("execution_fingerprint"), str)
        or re.fullmatch(r"[0-9a-f]{64}", str(value.get("execution_fingerprint")))
        is None
        or not isinstance(value.get("domain"), str)
        or not isinstance(value.get("problem_type"), str)
        or not isinstance(value.get("didactic_hint"), str)
        or not isinstance(problem_parse, dict)
        or not isinstance(problem_parse.get("goal"), str)
        or not isinstance(problem_parse.get("givens"), list)
        or not isinstance(problem_parse.get("symbols"), list)
        or not isinstance(value.get("solution_plan"), list)
        or not isinstance(value.get("visible_solution_steps"), list)
        or not isinstance(value.get("tool_trace"), list)
        or not isinstance(final_answer, dict)
        or final_answer.get("type")
        not in {"number", "expression", "set", "proof", "algorithm", "text"}
        or not isinstance(final_answer.get("value"), str)
        or not isinstance(final_answer.get("boxed"), str)
        or not isinstance(verification, dict)
        or not isinstance(verification.get("passed"), bool)
        or not isinstance(verification.get("method"), str)
        or not isinstance(verification.get("notes"), str)
        or isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0.0 <= float(confidence) <= 1.0
        or (value.get("error") is not None and not isinstance(value.get("error"), str))
    ):
        raise ExportSafetyError("submission result row violates the schema")
    if status_value == "success" and (
        verification.get("passed") is not True
        or not str(final_answer.get("value", "")).strip()
        or value.get("error") is not None
    ):
        raise ExportSafetyError("submission result has an inconsistent success state")
    try:
        canonical = SolveResult.model_validate(value, strict=True).model_dump()
    except Exception as exc:
        raise ExportSafetyError("submission result row violates the schema") from exc
    if canonical != value or set(canonical) != set(value):
        raise ExportSafetyError(
            "submission result row contains non-canonical or unknown fields"
        )
    return canonical


def _load_validated_results(path: Path) -> dict[str, dict[str, object]]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ExportSafetyError("submission results are unreadable") from exc
    if not raw or len(raw) > MAX_RESULT_BYTES:
        raise ExportSafetyError("submission results are empty or too large")
    rows: dict[str, dict[str, object]] = {}
    row_count = 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        row_count += 1
        if row_count > MAX_RESULT_ROWS or len(line) > MAX_RESULT_LINE_BYTES:
            raise ExportSafetyError("submission results exceed the row limits")
        row = _validate_result_row(_strict_json_loads(line))
        question_id = str(row["question_id"])
        if question_id in rows:
            raise ExportSafetyError("submission results contain duplicate question IDs")
        rows[question_id] = row
    if not rows:
        raise ExportSafetyError("submission results contain no valid rows")
    return rows


def _validate_submission_evidence(results_path: Path, traces_dir: Path) -> None:
    results = _load_validated_results(results_path)
    trace_rows: dict[str, dict[str, object]] = {}
    total_bytes = 0
    for path in _portable_tree_files(traces_dir):
        if path.name == ".gitkeep":
            continue
        if path.suffix.casefold() != ".json":
            raise ExportSafetyError("trace directory contains an unsupported file")
        try:
            size = path.stat().st_size
            raw = path.read_bytes()
        except OSError as exc:
            raise ExportSafetyError("submission trace is unreadable") from exc
        total_bytes += size
        if (
            size <= 0
            or size > MAX_TRACE_BYTES
            or total_bytes > MAX_TOTAL_TRACE_BYTES
            or len(raw) != size
        ):
            raise ExportSafetyError("submission traces exceed the safe limits")
        trace = _strict_json_loads(raw)
        if not isinstance(trace, dict):
            raise ExportSafetyError("submission trace root must be an object")
        question_id = trace.get("question_id")
        question = trace.get("question")
        execution_profile = trace.get("execution_profile")
        metadata = trace.get("metadata")
        model_calls = trace.get("model_calls")
        errors = trace.get("errors")
        if (
            not isinstance(question_id, str)
            or not question_id.strip()
            or not isinstance(question, str)
            or not question.strip()
            or question_id in trace_rows
            or not isinstance(model_calls, list)
            or not isinstance(trace.get("tool_calls"), list)
            or not isinstance(errors, list)
            or not isinstance(execution_profile, dict)
            or not isinstance(metadata, dict)
        ):
            raise ExportSafetyError("submission trace violates the audit schema")
        final_result = _validate_result_row(trace.get("final_result"))
        try:
            recomputed_execution_fingerprint = execution_provenance_fingerprint(
                question=question,
                execution_profile=execution_profile,
            )
        except (TypeError, ValueError) as exc:
            raise ExportSafetyError(
                "submission trace has invalid execution provenance"
            ) from exc
        expected_model = execution_profile.get("model")
        final_result_model = SolveResult.model_validate(final_result, strict=True)
        audit_evidence_valid = is_valid_trace_audit_evidence(
            trace,
            final_result_model,
            expected_real_mode=True,
        )
        if (
            final_result.get("question_id") != question_id
            or question_id not in results
            or final_result != results[question_id]
            or execution_profile.get("mock") is not False
            or execution_profile.get("save_trace") is not True
            or execution_profile.get("client_class")
            != "math_agent.clients.interns1_client.InternS1Client"
            or expected_model in {None, "", "unspecified"}
            or not execution_profile.get("endpoint_sha256")
            or not execution_profile.get("trace_dir_sha256")
            or metadata.get("real_execution_requested") is not True
            or recomputed_execution_fingerprint
            != results[question_id].get("execution_fingerprint")
            or trace.get("execution_profile") != execution_profile
            or trace.get("run_mode") != execution_profile.get("run_mode")
            or not audit_evidence_valid
            or final_result.get("status") != results[question_id].get("status")
            or final_result.get("final_answer")
            != results[question_id].get("final_answer")
            or final_result.get("verification")
            != results[question_id].get("verification")
            or final_result.get("error") != results[question_id].get("error")
            or final_result.get("input_fingerprint")
            != results[question_id].get("input_fingerprint")
            or final_result.get("execution_fingerprint")
            != results[question_id].get("execution_fingerprint")
            or trace.get("input_fingerprint")
            != results[question_id].get("input_fingerprint")
            or trace.get("execution_fingerprint")
            != results[question_id].get("execution_fingerprint")
            or sha256(question.strip().encode("utf-8")).hexdigest()
            != results[question_id].get("input_fingerprint")
        ):
            raise ExportSafetyError("submission trace does not match its result row")
        trace_rows[question_id] = trace
    if set(trace_rows) != set(results):
        raise ExportSafetyError("submission results and traces are not one-to-one")


def _staged_files(root: Path) -> list[Path]:
    files: list[Path] = []
    seen_keys: set[str] = set()
    for path in root.rglob("*"):
        is_junction = getattr(path, "is_junction", lambda: False)()
        if path.is_symlink() or is_junction:
            raise ExportSafetyError(
                "unsafe staged export: links and junctions are not allowed"
            )
        if path.is_dir():
            continue
        if not path.is_file() or not _is_within(path.resolve(strict=True), root):
            raise ExportSafetyError(
                "unsafe staged export: expected repository-local regular files"
            )
        relative = path.relative_to(root).as_posix()
        portable_key = _portable_relative_path_key(relative)
        if portable_key is None or portable_key in seen_keys:
            raise ExportSafetyError(
                "unsafe staged export: paths must be portable and case-unique"
            )
        seen_keys.add(portable_key)
        files.append(path)
    return files


def _safe_copy_file(src: Path, dst: Path) -> None:
    if src.is_symlink() or not src.is_file():
        raise ExportSafetyError("unsafe export source: expected a regular file")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def _safe_copy_tree(src: Path, dst: Path) -> None:
    for path in _portable_tree_files(src):
        rel = path.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_manifest(root: Path) -> dict[str, dict[str, int | str]]:
    files = [
        path
        for path in _staged_files(root)
        if path not in {root / EXPORT_MARKER_NAME, root / STAGING_SENTINEL_NAME}
    ]
    if len(files) > MAX_EXPORT_ENTRIES:
        raise ExportSafetyError("export contains too many files")
    manifest: dict[str, dict[str, int | str]] = {}
    total_bytes = 0
    for path in files:
        size = path.stat().st_size
        total_bytes += size
        if total_bytes > MAX_EXPORT_ARCHIVE_BYTES:
            raise ExportSafetyError("export is too large")
        manifest[path.relative_to(root).as_posix()] = {
            "sha256": _hash_file(path),
            "size": size,
        }
    return manifest


def _marker_payload(
    root: Path, transaction_id: str, out_name: str, staging_nonce: str
) -> dict[str, object]:
    return {
        **EXPORT_MARKER_BASE,
        "files": _directory_manifest(root),
        "out_name": out_name,
        "staging_nonce": staging_nonce,
        "transaction_id": transaction_id,
    }


def _read_marker(path: Path) -> dict[str, object] | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        if path.stat().st_size > MAX_EXPORT_MARKER_BYTES:
            return None
        payload = _strict_json_loads(path.read_text(encoding="utf-8", errors="strict"))
    except (ExportSafetyError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _validate_submission_layout(path: Path) -> bool:
    required = {
        EXPORT_MARKER_NAME,
        "docs/README_SUBMISSION.md",
        "result/final_output.jsonl",
        "src_snapshot_note.md",
    }
    optional = {
        "demo/demo_script.md",
        "docs/candidate_summary.md",
        "docs/replay.md",
        "docs/system_overview.md",
        "report/final_report.md",
        "report/final_report.pdf",
    }
    try:
        relative_files = {
            item.relative_to(path).as_posix() for item in _staged_files(path)
        }
    except (ExportSafetyError, OSError, ValueError):
        return False
    if not required.issubset(relative_files):
        return False
    for relative in relative_files:
        if relative in required or relative in optional:
            continue
        if relative.startswith("logs/traces/") or relative.startswith(
            "logs/run_record/"
        ):
            continue
        return False
    return True


def _validate_export_directory(
    path: Path, transaction_id: str, out_name: str, staging_nonce: str
) -> bool:
    marker = _read_marker(path / EXPORT_MARKER_NAME)
    if marker is None or set(marker) != EXPORT_MARKER_KEYS:
        return False
    expected_base = {
        **EXPORT_MARKER_BASE,
        "out_name": out_name,
        "staging_nonce": staging_nonce,
        "transaction_id": transaction_id,
    }
    if any(marker.get(key) != value for key, value in expected_base.items()):
        return False
    files = marker.get("files")
    if not isinstance(files, dict):
        return False
    try:
        return files == _directory_manifest(path) and _validate_submission_layout(path)
    except (ExportSafetyError, OSError):
        return False


def _write_readme_submission(
    target: Path, has_report: bool, has_demo: bool, report_name: str
) -> None:
    content = f"""# EvoExternMath-S1++ Frozen Submission

## 1. Frozen Harness 说明
本提交包面向 EvoExternMath-S1++ Frozen Submission，保持 stable pipeline 冻结基线，不修改核心求解流程与 CLI 行为。

## 2. 运行环境
- Python 3.10+
- 建议：Linux / macOS
- 依赖安装：`pip install -e \".[dev]\"`

## 3. 运行命令
- 单题：`python -m math_agent.cli solve --question \"计算 2+3\" --enable-tools`
- 批量：`python -m math_agent.cli batch --input data/official_questions.jsonl --output outputs/official_results.jsonl --enable-tools`
- 评测：`python scripts/evaluate_results.py --results outputs/official_results.jsonl --report outputs/official_evaluation_report.md`

## 4. JSON 输出格式
批量输出为 JSONL，每行一个 SolveResult，关键字段包括：`question_id`、`final_answer`、`status`、`error`、`verification`。

## 5. Trace 日志说明
trace 位于 `logs/traces/`，用于审计模型调用、工具调用、校验结果与错误记录。

## 6. 复现步骤
1. 准备输入题集（JSONL）。
2. 执行 batch 生成 `official_results.jsonl`。
3. 执行 evaluate 生成报告。
4. 使用 `scripts/export_submission.py` 打包 Frozen Submission。

## 7. 安全说明
- 提交包不包含 API key / `.env` / `.git` / 常见缓存目录。
- 如检测到疑似敏感信息（如 Authorization / Bearer token），导出流程将直接失败。
- 允许 `.env.example` 存在于项目源代码中，但不会被提交打包。

## 8. 提交内容说明
- report 包含状态：{"included" if has_report else "missing"}（期望文件名：`{report_name}`）
- demo 脚本状态：{"included" if has_demo else "missing"}
- `official_results.jsonl` 不应人工逐题修改。
"""
    target.write_text(content, encoding="utf-8")


def _run_safety_scan(repo_root: Path) -> list[tuple[str, str]]:
    findings = scan_project(repo_root)
    blocked: list[tuple[str, str]] = []
    ignored_risks = {
        "forbidden_outputs_artifact",
        "forbidden_official_results_file",
        "forbidden_runtime_artifact",
        "forbidden_outputs_jsonl",
        "forbidden_outputs_traces",
        "forbidden_outputs_run_records",
        "forbidden_submission_archive",
        "forbidden_env_file",
        "forbidden___pycache___artifact",
        "forbidden_.pytest_cache_artifact",
    }
    for rel_path, risk in findings:
        path_name = PurePosixPath(rel_path).name.casefold()
        if risk.startswith("suspected_") and (
            path_name == ".env" or path_name.startswith(".env.")
        ):
            # Local environment files are excluded from every source/staging path.
            # Keep the standalone project scanner strict without preventing an
            # otherwise clean export merely because a local credential exists.
            continue
        if risk in ignored_risks:
            continue
        blocked.append((rel_path, risk))
    return blocked


def _build_zip_archive(
    source_dir: Path,
    temporary_path: Path,
    archive_root_name: str,
    payload: dict[str, object],
) -> None:
    flags = os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary_path, flags)
    try:
        descriptor_stat = os.fstat(descriptor)
        path_stat = os.lstat(temporary_path)
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
            or not _matches_recorded_identity(
                payload, "temporary_archive", temporary_path
            )
        ):
            raise ExportSafetyError("temporary archive identity changed")
        raw_archive = os.fdopen(descriptor, "r+b")
        descriptor = -1
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    with raw_archive:
        raw_archive.seek(0)
        raw_archive.truncate()
        with zipfile.ZipFile(
            raw_archive, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for path in sorted(_staged_files(source_dir)):
                rel = Path(archive_root_name) / path.relative_to(source_dir)
                archive.write(path, arcname=str(rel))
        raw_archive.flush()
        os.fsync(raw_archive.fileno())


def _zip_end_record(handle: BinaryIO) -> tuple[int, int, int, int] | None:
    """Return canonical EOCD metadata, rejecting comments and appended bytes."""
    try:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        tail_start = max(0, size - 65_557)
        handle.seek(tail_start)
        tail = handle.read()
    except OSError:
        return None
    signature = b"PK\x05\x06"
    offset = tail.rfind(signature)
    if offset < 0 or offset + 22 > len(tail):
        return None
    (
        disk_number,
        central_disk,
        disk_entries,
        total_entries,
        central_size,
        central_offset,
        comment_length,
    ) = struct.unpack_from("<HHHHIIH", tail, offset + 4)
    eocd_offset = tail_start + offset
    if (
        disk_number != 0
        or central_disk != 0
        or disk_entries != total_entries
        or total_entries == 0xFFFF
        or central_size == 0xFFFFFFFF
        or central_offset == 0xFFFFFFFF
        or comment_length != 0
        or eocd_offset + 22 != size
        or central_offset + central_size != eocd_offset
    ):
        return None
    return total_entries, central_offset, central_size, eocd_offset


def _zip_member_is_safe_regular_file(info: zipfile.ZipInfo) -> bool:
    """Accept only unencrypted regular files from supported ZIP producers."""
    original_name = info.orig_filename
    if (
        original_name != info.filename
        or "\x00" in original_name
        or "\\" in original_name
        or info.flag_bits & ~0x800
        or info.is_dir()
        or info.extra
        or info.comment
    ):
        return False
    if info.create_system not in {0, 3}:
        return False

    unix_mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(unix_mode)
    if info.create_system == 3 and not stat.S_ISREG(unix_mode):
        return False
    if info.create_system == 0 and file_type not in {0, stat.S_IFREG}:
        return False

    return info.external_attr & 0xFF == 0


def _zip_local_record_end(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo
) -> int | None:
    """Bind a local header to its central entry and return its physical end."""
    handle = archive.fp
    if handle is None or info.header_offset < 0:
        return None
    try:
        handle.seek(info.header_offset)
        header = handle.read(30)
        if len(header) != 30:
            return None
        (
            signature,
            _extract_version,
            local_flags,
            local_compression,
            _modified_time,
            _modified_date,
            local_crc,
            local_compressed_size,
            local_file_size,
            filename_size,
            extra_size,
        ) = struct.unpack("<IHHHHHIIIHH", header)
        if signature != 0x04034B50:
            return None
        if local_flags != info.flag_bits or local_flags & ~0x800:
            return None
        if local_compression != info.compress_type:
            return None
        if (
            local_crc != info.CRC
            or local_compressed_size != info.compress_size
            or local_file_size != info.file_size
        ):
            return None
        encoded_name = info.orig_filename.encode(
            "utf-8" if local_flags & 0x800 else "cp437"
        )
        if (
            filename_size != len(encoded_name)
            or handle.read(filename_size) != encoded_name
        ):
            return None
        if extra_size != 0:
            return None
        return info.header_offset + 30 + filename_size + info.compress_size
    except (OSError, UnicodeError, struct.error):
        return None


def _zip_has_canonical_layout(
    archive: zipfile.ZipFile,
    infos: list[zipfile.ZipInfo],
    end_record: tuple[int, int, int, int],
) -> bool:
    """Reject ZIP prefixes, record gaps, metadata comments, and trailing bytes."""
    declared_entries, central_offset, central_size, eocd_offset = end_record
    handle = archive.fp
    if (
        handle is None
        or archive.comment
        or len(infos) != declared_entries
        or getattr(archive, "start_dir", None) != central_offset
    ):
        return False

    expected_local_offset = 0
    for info in infos:
        if info.header_offset != expected_local_offset or info.comment:
            return False
        record_end = _zip_local_record_end(archive, info)
        if record_end is None:
            return False
        expected_local_offset = record_end
    if expected_local_offset != central_offset:
        return False

    central_end = central_offset + central_size
    cursor = central_offset
    try:
        for info in infos:
            if cursor + 46 > central_end:
                return False
            handle.seek(cursor)
            header = handle.read(46)
            if len(header) != 46:
                return False
            (
                signature,
                version_made_by,
                extract_version,
                flags,
                compression,
                _modified_time,
                _modified_date,
                crc,
                compressed_size,
                file_size,
                filename_size,
                extra_size,
                comment_size,
                disk_start,
                internal_attr,
                external_attr,
                local_offset,
            ) = struct.unpack("<IHHHHHHIIIHHHHHII", header)
            encoded_name = info.orig_filename.encode(
                "utf-8" if flags & 0x800 else "cp437"
            )
            if (
                signature != 0x02014B50
                or flags != info.flag_bits
                or compression != info.compress_type
                or crc != info.CRC
                or compressed_size != info.compress_size
                or file_size != info.file_size
                or filename_size != len(encoded_name)
                or extra_size != 0
                or comment_size != 0
                or disk_start != 0
                or internal_attr != info.internal_attr
                or external_attr != info.external_attr
                or local_offset != info.header_offset
                or version_made_by & 0xFF != info.create_version
                or version_made_by >> 8 != info.create_system
                or extract_version != info.extract_version
                or handle.read(filename_size) != encoded_name
            ):
                return False
            cursor += 46 + filename_size
    except (OSError, UnicodeError, struct.error):
        return False
    return cursor == central_end == eocd_offset


def _validate_export_archive(
    path: Path,
    archive_root_name: str,
    transaction_id: str,
    staging_nonce: str,
) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        if path.stat().st_size > MAX_EXPORT_ARCHIVE_BYTES:
            return False
        with path.open("rb") as raw_archive:
            end_record = _zip_end_record(raw_archive)
            if end_record is None or end_record[0] > MAX_EXPORT_ENTRIES + 1:
                return False
            raw_archive.seek(0)
            with zipfile.ZipFile(raw_archive) as archive:
                infos = archive.infolist()
                if not infos or not _zip_has_canonical_layout(
                    archive, infos, end_record
                ):
                    return False
                if any(
                    not _zip_member_is_safe_regular_file(info)
                    or info.compress_type != zipfile.ZIP_DEFLATED
                    for info in infos
                ):
                    return False
                names = [info.orig_filename for info in infos]
                if len(names) != len(set(names)):
                    return False
                portable_name_keys = [
                    _portable_relative_path_key(name) for name in names
                ]
                if any(key is None for key in portable_name_keys) or len(
                    portable_name_keys
                ) != len(set(portable_name_keys)):
                    return False
                info_by_name = dict(zip(names, infos))
                marker_name = f"{archive_root_name}/{EXPORT_MARKER_NAME}"
                if marker_name not in info_by_name:
                    return False
                marker_info = info_by_name[marker_name]
                if marker_info.file_size > MAX_EXPORT_MARKER_BYTES:
                    return False
                marker = _strict_json_loads(archive.read(marker_info))
                if not isinstance(marker, dict) or set(marker) != EXPORT_MARKER_KEYS:
                    return False
                expected_base = {
                    **EXPORT_MARKER_BASE,
                    "out_name": archive_root_name,
                    "staging_nonce": staging_nonce,
                    "transaction_id": transaction_id,
                }
                if any(
                    marker.get(key) != value for key, value in expected_base.items()
                ):
                    return False
                files = marker.get("files")
                if not isinstance(files, dict):
                    return False
                expected_names = {marker_name}
                total_bytes = marker_info.file_size
                for rel_path, metadata in files.items():
                    if (
                        not isinstance(rel_path, str)
                        or not isinstance(metadata, dict)
                        or set(metadata) != {"sha256", "size"}
                    ):
                        return False
                    relative_member = PurePosixPath(rel_path)
                    if (
                        relative_member.is_absolute()
                        or ".." in relative_member.parts
                        or "\\" in rel_path
                        or relative_member.as_posix() != rel_path
                    ):
                        return False
                    archive_name = f"{archive_root_name}/{rel_path}"
                    expected_names.add(archive_name)
                    if archive_name not in info_by_name:
                        return False
                    info = info_by_name[archive_name]
                    expected_size = metadata.get("size")
                    expected_hash = metadata.get("sha256")
                    if (
                        not isinstance(expected_size, int)
                        or isinstance(expected_size, bool)
                        or not isinstance(expected_hash, str)
                        or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
                        or info.file_size != expected_size
                    ):
                        return False
                    total_bytes += info.file_size
                    if total_bytes > MAX_EXPORT_ARCHIVE_BYTES:
                        return False
                    digest = sha256()
                    with archive.open(info) as member:
                        for chunk in iter(lambda: member.read(1024 * 1024), b""):
                            digest.update(chunk)
                    if digest.hexdigest() != expected_hash:
                        return False
                return set(names) == expected_names
    except Exception:
        return False


def _directory_and_archive_manifests_match(
    directory: Path, archive: Path, archive_root_name: str
) -> bool:
    marker_path = directory / EXPORT_MARKER_NAME
    try:
        marker_bytes = marker_path.read_bytes()
        if len(marker_bytes) > MAX_EXPORT_MARKER_BYTES:
            return False
        with zipfile.ZipFile(archive) as zip_archive:
            archived_marker = zip_archive.read(
                f"{archive_root_name}/{EXPORT_MARKER_NAME}"
            )
        return marker_bytes == archived_marker
    except (KeyError, OSError, zipfile.BadZipFile):
        return False


def _require_recovery_content_safe(path: Path) -> None:
    findings = scan_sensitive_files(_staged_files(path), path)
    if findings:
        raise ExportSafetyError(
            "pending export contains sensitive or unsupported content"
        )


def _clear_readonly_and_retry(function, target, exc_info) -> None:
    os.chmod(target, stat.S_IWRITE)
    function(target)


def _remove_internal_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink():
        path.unlink(missing_ok=True)
        return
    if getattr(path, "is_junction", lambda: False)():
        os.rmdir(path)
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, onerror=_clear_readonly_and_retry)
        return
    path.unlink(missing_ok=True)


def _lock_path(repo_root: Path) -> Path:
    digest = sha256(str(repo_root).encode("utf-8")).hexdigest()[:24]
    return Path(tempfile.gettempdir()) / f"evoexternmath-export-{digest}.lock"


def _acquire_export_lock(repo_root: Path) -> BinaryIO:
    lock_path = _lock_path(repo_root)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(lock_path, flags, 0o600)
        descriptor_stat = os.fstat(descriptor)
        path_stat = os.lstat(lock_path)
        getuid = getattr(os, "getuid", None)
        if (
            not stat.S_ISREG(descriptor_stat.st_mode)
            or descriptor_stat.st_nlink != 1
            or (descriptor_stat.st_dev, descriptor_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
            or (callable(getuid) and descriptor_stat.st_uid != getuid())
        ):
            raise ExportSafetyError("unsafe submission export lock file")
        handle = os.fdopen(descriptor, "r+b")
        descriptor = None
    except Exception as exc:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if isinstance(exc, ExportSafetyError):
            raise
        raise ExportSafetyError("could not create safe export lock") from exc
    if handle.seek(0, os.SEEK_END) == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl = importlib.import_module("fcntl")
            getattr(fcntl, "flock")(
                handle.fileno(),
                getattr(fcntl, "LOCK_EX") | getattr(fcntl, "LOCK_NB"),
            )
    except (OSError, ImportError) as exc:
        handle.close()
        raise ExportSafetyError("another submission export is already running") from exc
    return handle


def _release_export_lock(handle: BinaryIO) -> None:
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl = importlib.import_module("fcntl")
            getattr(fcntl, "flock")(handle.fileno(), getattr(fcntl, "LOCK_UN"))
    finally:
        handle.close()


def _journal_path(repo_root: Path) -> Path:
    return repo_root / TRANSACTION_FILE_NAME


def _write_journal(repo_root: Path, payload: dict[str, object]) -> None:
    journal = _journal_path(repo_root)
    transaction_id = str(payload["transaction_id"])
    temporary = repo_root / f".{TRANSACTION_FILE_NAME}.{transaction_id}.tmp"
    if temporary.exists() or temporary.is_symlink():
        _remove_internal_path(temporary)
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, journal)


def _transaction_paths(
    repo_root: Path, payload: dict[str, object]
) -> tuple[Path, Path, Path, Path, str, str]:
    transaction_id = payload.get("transaction_id")
    out_name = payload.get("out_name")
    staging_nonce = payload.get("staging_nonce")
    if (
        payload.get("version") != 1
        or not isinstance(transaction_id, str)
        or not re.fullmatch(r"[0-9a-f]{32}", transaction_id)
        or not isinstance(staging_nonce, str)
        or not re.fullmatch(r"[0-9a-f]{32}", staging_nonce)
        or not isinstance(out_name, str)
        or Path(out_name).name != out_name
        or not _is_safe_output_name(out_name)
        or out_name.casefold() in PROTECTED_OUTPUT_ROOTS
    ):
        raise ExportSafetyError("invalid pending export transaction journal")
    out_dir = repo_root / out_name
    archive_path = repo_root / f"{out_name}.zip"
    staging_dir = repo_root / f".{out_name}.staging-{transaction_id}"
    temporary_archive = repo_root / f".{out_name}.zip-staging-{transaction_id}"
    canonical_out = out_dir.resolve(strict=False)
    canonical_archive = archive_path.resolve(strict=False)
    if (
        canonical_out.parent != repo_root
        or canonical_out.name != out_name
        or canonical_archive.parent != repo_root
        or canonical_archive.name != f"{out_name}.zip"
    ):
        raise ExportSafetyError("unsafe canonical export transaction path")
    return (
        out_dir,
        archive_path,
        staging_dir,
        temporary_archive,
        out_name,
        transaction_id,
    )


def _update_journal_state(
    repo_root: Path, payload: dict[str, object], state: str
) -> None:
    updated = {**payload, "state": state}
    _write_journal(repo_root, updated)
    payload.clear()
    payload.update(updated)


def _same_file(first: Path, second: Path) -> bool:
    try:
        first_stat = first.stat()
        second_stat = second.stat()
    except OSError:
        return False
    return (first_stat.st_dev, first_stat.st_ino) == (
        second_stat.st_dev,
        second_stat.st_ino,
    )


def _record_identity(payload: dict[str, object], prefix: str, path: Path) -> None:
    path_stat = path.stat()
    payload[f"{prefix}_device"] = path_stat.st_dev
    payload[f"{prefix}_inode"] = path_stat.st_ino


def _matches_recorded_identity(
    payload: dict[str, object], prefix: str, path: Path
) -> bool:
    device = payload.get(f"{prefix}_device")
    inode = payload.get(f"{prefix}_inode")
    if not isinstance(device, int) or not isinstance(inode, int):
        return False
    try:
        path_stat = path.stat()
    except OSError:
        return False
    return (path_stat.st_dev, path_stat.st_ino) == (device, inode)


def _write_staging_sentinel(staging_dir: Path, transaction_id: str, nonce: str) -> None:
    sentinel = staging_dir / STAGING_SENTINEL_NAME
    with sentinel.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {"nonce": nonce, "transaction_id": transaction_id, "version": 1},
            handle,
            sort_keys=True,
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _validate_partial_staging(staging_dir: Path, payload: dict[str, object]) -> bool:
    if not _matches_recorded_identity(payload, "staging", staging_dir):
        return False
    sentinel = _read_marker(staging_dir / STAGING_SENTINEL_NAME)
    return sentinel == {
        "nonce": payload.get("staging_nonce"),
        "transaction_id": payload.get("transaction_id"),
        "version": 1,
    }


def _validate_unrecorded_partial_staging(
    staging_dir: Path, payload: dict[str, object]
) -> bool:
    if (
        staging_dir.is_symlink()
        or getattr(staging_dir, "is_junction", lambda: False)()
        or not staging_dir.is_dir()
    ):
        return False
    try:
        entries = list(staging_dir.iterdir())
    except OSError:
        return False
    if not entries:
        return True
    if entries != [staging_dir / STAGING_SENTINEL_NAME]:
        return False
    return _read_marker(entries[0]) == {
        "nonce": payload.get("staging_nonce"),
        "transaction_id": payload.get("transaction_id"),
        "version": 1,
    }


def _validate_unrecorded_empty_file(path: Path) -> bool:
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        return False
    try:
        path_stat = path.stat()
    except OSError:
        return False
    return stat.S_ISREG(path_stat.st_mode) and path_stat.st_size == 0


def _publish_archive_no_clobber(temporary_archive: Path, archive_path: Path) -> None:
    if os.name == "nt":
        os.rename(temporary_archive, archive_path)
        return
    os.link(temporary_archive, archive_path)
    temporary_archive.unlink()


def _published_pair_is_safe(
    out_dir: Path,
    archive_path: Path,
    transaction_id: str,
    staging_nonce: str,
) -> bool:
    if not _validate_export_directory(
        out_dir, transaction_id, out_dir.name, staging_nonce
    ) or not _validate_export_archive(
        archive_path, out_dir.name, transaction_id, staging_nonce
    ):
        return False
    try:
        _require_recovery_content_safe(out_dir)
    except ExportSafetyError:
        return False
    return _directory_and_archive_manifests_match(out_dir, archive_path, out_dir.name)


def _commit_new_export(
    repo_root: Path,
    payload: dict[str, object],
    out_dir: Path,
    archive_path: Path,
    staging_dir: Path,
    temporary_archive: Path,
) -> None:
    transaction_id = str(payload["transaction_id"])
    staging_nonce = str(payload["staging_nonce"])
    if not _matches_recorded_identity(payload, "staging", staging_dir):
        raise ExportSafetyError("staging directory identity changed")
    if not _matches_recorded_identity(payload, "temporary_archive", temporary_archive):
        raise ExportSafetyError("temporary archive identity changed")
    if out_dir.exists() or out_dir.is_symlink():
        raise ExportSafetyError("output appeared during export; refusing to overwrite")
    if archive_path.exists() or archive_path.is_symlink():
        raise ExportSafetyError("archive appeared during export; refusing to overwrite")
    if out_dir.parent.resolve() != repo_root:
        raise ExportSafetyError("output parent changed during export")
    if not _validate_export_directory(
        staging_dir, transaction_id, out_dir.name, staging_nonce
    ):
        raise ExportSafetyError("staging directory failed manifest validation")
    _require_recovery_content_safe(staging_dir)
    if not _validate_export_archive(
        temporary_archive, out_dir.name, transaction_id, staging_nonce
    ):
        raise ExportSafetyError("temporary archive failed validation")
    if not _directory_and_archive_manifests_match(
        staging_dir, temporary_archive, out_dir.name
    ):
        raise ExportSafetyError("staging directory and archive manifests differ")

    try:
        os.rename(staging_dir, out_dir)
        if not _validate_export_directory(
            out_dir, transaction_id, out_dir.name, staging_nonce
        ):
            raise ExportSafetyError("installed output failed manifest validation")
        _update_journal_state(repo_root, payload, "directory_installed")

        _publish_archive_no_clobber(temporary_archive, archive_path)
        if not _matches_recorded_identity(
            payload, "temporary_archive", archive_path
        ) or not _validate_export_archive(
            archive_path, out_dir.name, transaction_id, staging_nonce
        ):
            raise ExportSafetyError("installed archive failed validation")
        if not _published_pair_is_safe(
            out_dir, archive_path, transaction_id, staging_nonce
        ):
            raise ExportSafetyError("published export pair failed final validation")
        _update_journal_state(repo_root, payload, "committed")
        if not _published_pair_is_safe(
            out_dir, archive_path, transaction_id, staging_nonce
        ):
            raise ExportSafetyError("published export pair changed during commit")
    except BaseException:
        try:
            if _matches_recorded_identity(payload, "temporary_archive", archive_path):
                if (
                    not temporary_archive.exists()
                    and not temporary_archive.is_symlink()
                ):
                    os.rename(archive_path, temporary_archive)
                elif _same_file(temporary_archive, archive_path):
                    _remove_internal_path(archive_path)
        except BaseException:
            pass
        try:
            if (
                _validate_export_directory(
                    out_dir, transaction_id, out_dir.name, staging_nonce
                )
                and not staging_dir.exists()
                and not staging_dir.is_symlink()
            ):
                os.rename(out_dir, staging_dir)
        except BaseException:
            pass
        try:
            _update_journal_state(repo_root, payload, "prepared")
        except BaseException:
            pass
        raise

    _remove_internal_path(temporary_archive)
    _remove_internal_path(_journal_path(repo_root))


def _read_pending_journal(repo_root: Path) -> dict[str, object] | None:
    journal = _journal_path(repo_root)
    if not journal.exists():
        return None
    if journal.is_symlink() or not journal.is_file():
        raise ExportSafetyError("invalid pending export transaction journal")
    try:
        if journal.stat().st_size > 16_384:
            raise ExportSafetyError("pending export transaction journal is too large")
        payload = _strict_json_loads(
            journal.read_text(encoding="utf-8", errors="strict")
        )
    except (ExportSafetyError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExportSafetyError("invalid pending export transaction journal") from exc
    allowed_keys = {
        "out_name",
        "staging_device",
        "staging_inode",
        "staging_nonce",
        "state",
        "temporary_archive_device",
        "temporary_archive_inode",
        "transaction_id",
        "version",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) - allowed_keys
        or payload.get("version") != 1
        or payload.get("state")
        not in {
            "building",
            "prepared",
            "directory_installed",
            "committed",
        }
    ):
        raise ExportSafetyError("invalid pending export transaction journal")
    staging_identity_keys = {"staging_device", "staging_inode"}
    archive_identity_keys = {
        "temporary_archive_device",
        "temporary_archive_inode",
    }
    staging_identity_present = staging_identity_keys.issubset(payload)
    archive_identity_present = archive_identity_keys.issubset(payload)
    if (
        bool(staging_identity_keys & set(payload)) != staging_identity_present
        or bool(archive_identity_keys & set(payload)) != archive_identity_present
        or (archive_identity_present and not staging_identity_present)
        or (
            payload.get("state") in {"prepared", "directory_installed", "committed"}
            and not (staging_identity_present and archive_identity_present)
        )
        or any(
            not isinstance(payload[key], int) or isinstance(payload[key], bool)
            for key in staging_identity_keys | archive_identity_keys
            if key in payload
        )
    ):
        raise ExportSafetyError("invalid pending export transaction journal")
    _transaction_paths(repo_root, payload)
    return payload


def _discard_owned_unpublished_transaction(
    repo_root: Path, payload: dict[str, object]
) -> bool:
    (
        out_dir,
        archive_path,
        staging_dir,
        temporary_archive,
        out_name,
        transaction_id,
    ) = _transaction_paths(repo_root, payload)
    staging_nonce = str(payload["staging_nonce"])
    if _validate_export_archive(archive_path, out_name, transaction_id, staging_nonce):
        return False
    if archive_path.exists() or archive_path.is_symlink():
        if not _matches_recorded_identity(payload, "temporary_archive", archive_path):
            return False
        _remove_internal_path(archive_path)
    if _validate_export_directory(out_dir, transaction_id, out_name, staging_nonce):
        if staging_dir.exists() or staging_dir.is_symlink():
            return False
        os.rename(out_dir, staging_dir)
    elif out_dir.exists() or out_dir.is_symlink():
        return False
    if staging_dir.exists() or staging_dir.is_symlink():
        if not (
            _validate_export_directory(
                staging_dir, transaction_id, out_name, staging_nonce
            )
            or _validate_partial_staging(staging_dir, payload)
            or _validate_unrecorded_partial_staging(staging_dir, payload)
        ):
            return False
        _remove_internal_path(staging_dir)
    if temporary_archive.exists() or temporary_archive.is_symlink():
        if not (
            _validate_export_archive(
                temporary_archive, out_name, transaction_id, staging_nonce
            )
            or _matches_recorded_identity(
                payload, "temporary_archive", temporary_archive
            )
            or _validate_unrecorded_empty_file(temporary_archive)
        ):
            return False
        _remove_internal_path(temporary_archive)
    _remove_internal_path(_journal_path(repo_root))
    return True


def _recover_pending_transaction(repo_root: Path) -> str | None:
    payload = _read_pending_journal(repo_root)
    if payload is None:
        return None
    (
        out_dir,
        archive_path,
        staging_dir,
        temporary_archive,
        out_name,
        transaction_id,
    ) = _transaction_paths(repo_root, payload)
    staging_nonce = str(payload["staging_nonce"])

    out_valid = _validate_export_directory(
        out_dir, transaction_id, out_name, staging_nonce
    )
    archive_valid = _validate_export_archive(
        archive_path, out_name, transaction_id, staging_nonce
    )
    staging_valid = _validate_export_directory(
        staging_dir, transaction_id, out_name, staging_nonce
    )
    temporary_valid = _validate_export_archive(
        temporary_archive, out_name, transaction_id, staging_nonce
    )

    if out_valid and archive_valid:
        _require_recovery_content_safe(out_dir)
        if not _directory_and_archive_manifests_match(out_dir, archive_path, out_name):
            raise ExportSafetyError("pending export artifacts have different manifests")
        if staging_dir.exists() or staging_dir.is_symlink():
            if (
                not staging_valid
                and not _validate_partial_staging(staging_dir, payload)
                and not _validate_unrecorded_partial_staging(staging_dir, payload)
            ):
                raise ExportSafetyError(
                    "pending staging identity changed; refusing cleanup"
                )
            _remove_internal_path(staging_dir)
        if temporary_archive.exists() or temporary_archive.is_symlink():
            if (
                not temporary_valid
                and not _matches_recorded_identity(
                    payload, "temporary_archive", temporary_archive
                )
                and not _validate_unrecorded_empty_file(temporary_archive)
            ):
                raise ExportSafetyError(
                    "pending archive temp identity changed; refusing cleanup"
                )
            _remove_internal_path(temporary_archive)
        _remove_internal_path(_journal_path(repo_root))
        return out_name

    if out_valid and temporary_valid:
        _require_recovery_content_safe(out_dir)
        if not _directory_and_archive_manifests_match(
            out_dir, temporary_archive, out_name
        ):
            raise ExportSafetyError("pending export artifacts have different manifests")
        if archive_path.exists() or archive_path.is_symlink():
            if not _matches_recorded_identity(
                payload, "temporary_archive", archive_path
            ):
                raise ExportSafetyError(
                    "pending archive identity changed; refusing recovery"
                )
            _remove_internal_path(archive_path)
        _update_journal_state(repo_root, payload, "directory_installed")
        try:
            _publish_archive_no_clobber(temporary_archive, archive_path)
        except OSError:
            if _discard_owned_unpublished_transaction(repo_root, payload):
                return None
            raise
        if not _matches_recorded_identity(
            payload, "temporary_archive", archive_path
        ) or not _validate_export_archive(
            archive_path, out_name, transaction_id, staging_nonce
        ):
            if _matches_recorded_identity(payload, "temporary_archive", archive_path):
                _remove_internal_path(archive_path)
            raise ExportSafetyError("could not recover pending submission archive")
        _update_journal_state(repo_root, payload, "committed")
        _remove_internal_path(temporary_archive)
        _remove_internal_path(_journal_path(repo_root))
        return out_name

    if (
        staging_valid
        and temporary_valid
        and not out_dir.exists()
        and not archive_path.exists()
    ):
        _require_recovery_content_safe(staging_dir)
        if not _directory_and_archive_manifests_match(
            staging_dir, temporary_archive, out_name
        ):
            raise ExportSafetyError("pending export artifacts have different manifests")
        _update_journal_state(repo_root, payload, "prepared")
        try:
            _commit_new_export(
                repo_root,
                payload,
                out_dir,
                archive_path,
                staging_dir,
                temporary_archive,
            )
        except OSError:
            if _discard_owned_unpublished_transaction(repo_root, payload):
                return None
            raise
        return out_name

    if not out_dir.exists() and not archive_path.exists():
        if staging_dir.exists() or staging_dir.is_symlink():
            if (
                not staging_valid
                and not _validate_partial_staging(staging_dir, payload)
                and not _validate_unrecorded_partial_staging(staging_dir, payload)
            ):
                raise ExportSafetyError(
                    "pending staging identity changed; refusing cleanup"
                )
            _remove_internal_path(staging_dir)
        if temporary_archive.exists() or temporary_archive.is_symlink():
            if (
                not temporary_valid
                and not _matches_recorded_identity(
                    payload, "temporary_archive", temporary_archive
                )
                and not _validate_unrecorded_empty_file(temporary_archive)
            ):
                raise ExportSafetyError(
                    "pending archive temp identity changed; refusing cleanup"
                )
            _remove_internal_path(temporary_archive)
        _remove_internal_path(_journal_path(repo_root))
        return None

    raise ExportSafetyError(
        "pending export transaction needs manual recovery; no files were overwritten"
    )


def _print_warning(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


def _populate_staging_directory(
    staging_dir: Path,
    repo_root: Path,
    results: Path,
    traces: Path,
    report: Path,
    run_record: Path,
    *,
    out_name: str,
    report_argument: str,
    run_record_argument: str,
    staging_nonce: str,
    transaction_id: str,
) -> None:
    (staging_dir / "result").mkdir(parents=True, exist_ok=True)
    (staging_dir / "logs" / "traces").mkdir(parents=True, exist_ok=True)
    (staging_dir / "logs" / "run_record").mkdir(parents=True, exist_ok=True)
    (staging_dir / "report").mkdir(parents=True, exist_ok=True)
    (staging_dir / "demo").mkdir(parents=True, exist_ok=True)
    (staging_dir / "docs").mkdir(parents=True, exist_ok=True)

    _safe_copy_file(results, staging_dir / "result" / "final_output.jsonl")
    _safe_copy_tree(traces, staging_dir / "logs" / "traces")
    _validate_submission_evidence(
        staging_dir / "result" / "final_output.jsonl",
        staging_dir / "logs" / "traces",
    )

    if run_record.is_dir():
        _safe_copy_tree(run_record, staging_dir / "logs" / "run_record")
    else:
        _print_warning(f"run-record not found, skipped: {run_record_argument}")

    report_included = False
    if report.is_file():
        report_name = (
            "final_report.pdf" if report.suffix.lower() == ".pdf" else "final_report.md"
        )
        _safe_copy_file(report, staging_dir / "report" / report_name)
        report_included = True
    else:
        report_name = "final_report.md"
        _print_warning(f"report not found, skipped: {report_argument}")

    demo_script_src = repo_root / "demo" / "demo_script.md"
    demo_included = demo_script_src.is_file()
    if demo_included:
        _safe_copy_file(demo_script_src, staging_dir / "demo" / "demo_script.md")

    for doc_name in ("system_overview.md", "replay.md"):
        source = repo_root / doc_name
        if source.is_file():
            _safe_copy_file(source, staging_dir / "docs" / doc_name)

    candidate_summary = repo_root / "candidate_summary.md"
    if candidate_summary.is_file():
        _safe_copy_file(
            candidate_summary, staging_dir / "docs" / "candidate_summary.md"
        )

    _write_readme_submission(
        staging_dir / "docs" / "README_SUBMISSION.md",
        report_included,
        demo_included,
        report_name,
    )

    snapshot_note = {
        "project": "EvoExternMath-S1++",
        "frozen_submission": True,
        "excluded": [
            ".env",
            ".env.*",
            ".git",
            "__pycache__",
            ".pytest_cache",
            "outputs/debug*",
            "outputs/mock*",
            "outputs/local*",
        ],
    }
    (staging_dir / "src_snapshot_note.md").write_text(
        "# Source Snapshot Note\n\n```json\n"
        + json.dumps(snapshot_note, ensure_ascii=False, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )
    sentinel = staging_dir / STAGING_SENTINEL_NAME
    if _read_marker(sentinel) != {
        "nonce": staging_nonce,
        "transaction_id": transaction_id,
        "version": 1,
    }:
        raise ExportSafetyError("staging ownership sentinel changed during export")
    marker_path = staging_dir / EXPORT_MARKER_NAME
    temporary_marker = staging_dir / f".{EXPORT_MARKER_NAME}.{transaction_id}.tmp"
    marker_payload = _marker_payload(
        staging_dir, transaction_id, out_name, staging_nonce
    )
    with temporary_marker.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(marker_payload, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary_marker, marker_path)
    sentinel.unlink()
    if not _validate_export_directory(
        staging_dir, transaction_id, out_name, staging_nonce
    ):
        raise ExportSafetyError("staging manifest failed validation")


def _run_export(args: argparse.Namespace, repo_root: Path) -> int:
    try:
        results = _resolve_repository_path(repo_root, args.results, "results")
        traces = _resolve_repository_path(repo_root, args.traces, "traces")
        report = _resolve_repository_path(repo_root, args.report, "report")
        run_record = _resolve_repository_path(repo_root, args.run_record, "run-record")
        out_dir = _resolve_repository_path(repo_root, args.out, "output")
        archive_path = repo_root / f"{out_dir.name}.zip"
    except (ExportSafetyError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not results.is_file():
        print(f"ERROR: results file not found: {args.results}", file=sys.stderr)
        return 2
    if not traces.is_dir():
        print(f"ERROR: traces directory not found: {args.traces}", file=sys.stderr)
        return 2

    try:
        source_paths = [results, traces, report, run_record]
        _validate_output_dir(repo_root, out_dir, source_paths, archive_path)
        export_source_files = [results, *_portable_tree_files(traces)]
        if run_record.is_dir():
            export_source_files.extend(_portable_tree_files(run_record))
        if report.is_file():
            export_source_files.append(report)

        optional_sources = [
            repo_root / "demo" / "demo_script.md",
            repo_root / "system_overview.md",
            repo_root / "replay.md",
            repo_root / "candidate_summary.md",
        ]
        for source in optional_sources:
            if not source.exists():
                continue
            if (
                source.is_symlink()
                or not source.is_file()
                or not _is_within(source.resolve(strict=True), repo_root)
            ):
                raise ExportSafetyError(
                    "unsafe export source: optional source is not a regular repository file"
                )
            export_source_files.append(source)
    except (ExportSafetyError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    findings = _run_safety_scan(repo_root)
    if findings:
        print("ERROR: high-risk sensitive content detected:", file=sys.stderr)
        for rel_path, risk in findings:
            print(f"- {risk}: {rel_path}", file=sys.stderr)
        return 3

    export_findings = scan_sensitive_files(export_source_files, repo_root)
    if export_findings:
        print("ERROR: export source contains sensitive content:", file=sys.stderr)
        for rel_path, risk in export_findings:
            print(f"- {risk}: {rel_path}", file=sys.stderr)
        return 3

    try:
        _validate_submission_evidence(results, traces)
    except (ExportSafetyError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    transaction_id = uuid.uuid4().hex
    payload: dict[str, object] = {
        "out_name": out_dir.name,
        "staging_nonce": uuid.uuid4().hex,
        "state": "building",
        "transaction_id": transaction_id,
        "version": 1,
    }
    (
        expected_out,
        expected_archive,
        staging_dir,
        temporary_archive,
        _,
        _,
    ) = _transaction_paths(repo_root, payload)
    if expected_out != out_dir or expected_archive != archive_path:
        print("ERROR: unsafe transaction path derivation", file=sys.stderr)
        return 2

    try:
        if _journal_path(repo_root).exists():
            raise ExportSafetyError("pending export transaction was not recovered")
        _write_journal(repo_root, payload)
        staging_identity: tuple[int, int] | None = None
        try:
            staging_dir.mkdir(mode=0o700)
            staging_stat = staging_dir.stat()
            staging_identity = (staging_stat.st_dev, staging_stat.st_ino)
            _write_staging_sentinel(
                staging_dir,
                transaction_id,
                str(payload["staging_nonce"]),
            )
            payload["staging_device"], payload["staging_inode"] = staging_identity
            _write_journal(repo_root, payload)
        except BaseException:
            if staging_identity is not None:
                try:
                    current_stat = staging_dir.stat()
                    if (current_stat.st_dev, current_stat.st_ino) == staging_identity:
                        _remove_internal_path(staging_dir)
                except OSError:
                    pass
            raise
        _populate_staging_directory(
            staging_dir,
            repo_root,
            results,
            traces,
            report,
            run_record,
            out_name=out_dir.name,
            report_argument=args.report,
            run_record_argument=args.run_record,
            staging_nonce=str(payload["staging_nonce"]),
            transaction_id=transaction_id,
        )
        staged_findings = scan_sensitive_files(_staged_files(staging_dir), staging_dir)
        if staged_findings:
            print("ERROR: staged export contains sensitive content:", file=sys.stderr)
            for rel_path, risk in staged_findings:
                print(f"- {risk}: {rel_path}", file=sys.stderr)
            _recover_pending_transaction(repo_root)
            return 3
        if not _validate_export_directory(
            staging_dir,
            transaction_id,
            out_dir.name,
            str(payload["staging_nonce"]),
        ):
            raise ExportSafetyError("staging directory failed manifest validation")
        temporary_identity: tuple[int, int] | None = None
        try:
            with temporary_archive.open("xb") as archive_placeholder:
                archive_stat = os.fstat(archive_placeholder.fileno())
                temporary_identity = (archive_stat.st_dev, archive_stat.st_ino)
                archive_placeholder.flush()
                os.fsync(archive_placeholder.fileno())
            payload["temporary_archive_device"], payload["temporary_archive_inode"] = (
                temporary_identity
            )
            _write_journal(repo_root, payload)
        except BaseException:
            if temporary_identity is not None:
                try:
                    current_stat = temporary_archive.stat()
                    if (current_stat.st_dev, current_stat.st_ino) == temporary_identity:
                        temporary_archive.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        _build_zip_archive(staging_dir, temporary_archive, out_dir.name, payload)
        if not _validate_export_archive(
            temporary_archive,
            out_dir.name,
            transaction_id,
            str(payload["staging_nonce"]),
        ):
            raise ExportSafetyError("temporary archive failed validation")
        _update_journal_state(repo_root, payload, "prepared")
        _commit_new_export(
            repo_root,
            payload,
            out_dir,
            archive_path,
            staging_dir,
            temporary_archive,
        )
        if not _published_pair_is_safe(
            out_dir,
            archive_path,
            transaction_id,
            str(payload["staging_nonce"]),
        ):
            raise ExportSafetyError("published export changed before completion")
    except (ExportSafetyError, OSError, UnicodeError, ValueError, zipfile.BadZipFile):
        try:
            if not _discard_owned_unpublished_transaction(repo_root, payload):
                _recover_pending_transaction(repo_root)
        except (ExportSafetyError, OSError):
            pass
        if _published_pair_is_safe(
            out_dir,
            archive_path,
            transaction_id,
            str(payload["staging_nonce"]),
        ) and not (
            temporary_archive.exists()
            or temporary_archive.is_symlink()
            or _journal_path(repo_root).exists()
            or _journal_path(repo_root).is_symlink()
        ):
            print(
                f"OK: submission package recovered at {out_dir} and {archive_path.name}"
            )
            return 0
        print("ERROR: failed to build a safe submission transaction", file=sys.stderr)
        return 2
    print(f"OK: submission package created at {out_dir} and {archive_path.name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export EvoExternMath-S1++ frozen submission package"
    )
    parser.add_argument(
        "--results", required=True, help="Path to official results jsonl"
    )
    parser.add_argument("--traces", required=True, help="Path to traces directory")
    parser.add_argument("--report", required=True, help="Path to evaluation report")
    parser.add_argument(
        "--run-record", required=True, help="Path to run record directory"
    )
    parser.add_argument("--out", default="submission", help="Output directory")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo_root = Path.cwd().resolve()
    try:
        lock_handle = _acquire_export_lock(repo_root)
    except (ExportSafetyError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    try:
        recovered_out = _recover_pending_transaction(repo_root)
        if recovered_out is not None:
            requested_out = Path(args.out)
            if not requested_out.is_absolute():
                requested_out = repo_root / requested_out
            if requested_out.resolve(strict=False) == repo_root / recovered_out:
                print(
                    "OK: recovered pending submission package at "
                    f"{repo_root / recovered_out} and {recovered_out}.zip"
                )
                return 0
        return _run_export(args, repo_root)
    except (ExportSafetyError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        _release_export_lock(lock_handle)


if __name__ == "__main__":
    raise SystemExit(main())
