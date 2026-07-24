from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import threading
import time
from collections.abc import Iterable
from pathlib import Path

STRONG_SCAN_DIRS = {"src", "scripts", "configs", "submission"}
SKIP_TEXT_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "outputs",
    "trace",
    "run_records",
    "__pycache__",
    ".pytest_cache",
}
TEXT_SUFFIXES = {
    ".c",
    ".cc",
    ".cjs",
    ".clj",
    ".conf",
    ".config",
    ".cpp",
    ".cs",
    ".css",
    ".cxx",
    ".dart",
    ".ex",
    ".exs",
    ".fs",
    ".fsx",
    ".go",
    ".gql",
    ".gradle",
    ".graphql",
    ".h",
    ".hcl",
    ".hpp",
    ".htm",
    ".html",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".kts",
    ".less",
    ".lock",
    ".lua",
    ".mjs",
    ".php",
    ".pl",
    ".properties",
    ".proto",
    ".py",
    ".ipynb",
    ".r",
    ".rb",
    ".rs",
    ".rst",
    ".sass",
    ".scala",
    ".scss",
    ".sql",
    ".sol",
    ".svelte",
    ".svg",
    ".swift",
    ".tf",
    ".tfvars",
    ".ts",
    ".tsx",
    ".vue",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".json",
    ".jsonl",
    ".toml",
    ".ini",
    ".cfg",
    ".sh",
    ".ps1",
    ".psm1",
    ".bat",
    ".cmd",
    ".xml",
    ".csv",
    ".log",
    ".pem",
    ".key",
}
BINARY_SUFFIXES = {
    ".7z",
    ".avi",
    ".db",
    ".dll",
    ".docx",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".mov",
    ".mp3",
    ".mp4",
    ".otf",
    ".parquet",
    ".pdf",
    ".png",
    ".pptx",
    ".pyc",
    ".pyd",
    ".so",
    ".sqlite",
    ".tar",
    ".ttf",
    ".wav",
    ".webp",
    ".woff",
    ".woff2",
    ".xlsx",
    ".zip",
}
CONFIG_SECRET_SUFFIXES = {
    ".bat",
    ".cfg",
    ".cmd",
    ".ini",
    ".ps1",
    ".psm1",
    ".sh",
    ".toml",
    ".xml",
    ".yaml",
    ".yml",
}
CONFIG_SECRET_NAMES = {
    ".env.example",
    ".envrc",
    ".git-credentials",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials",
    "dockerfile",
    "makefile",
}
FORBIDDEN_CREDENTIAL_SUFFIXES = {
    ".jks",
    ".keystore",
    ".p12",
    ".pfx",
    ".pkcs12",
    ".ppk",
}
FORBIDDEN_CREDENTIAL_NAMES = {
    ".envrc",
    ".git-credentials",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials",
    "id_ed25519",
    "id_rsa",
}

API_KEY_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bINTERNS1_API_KEY[ \t]*=[ \t]*[\"']?[A-Za-z0-9._-]{12,}[\"']?"),
]
AUTH_PATTERNS = [
    re.compile(
        r"\bAuthorization[\"']?\s*:\s*[\"']?\s*"
        r"(?:(?:Basic|Bearer|Token)\s+)?[A-Za-z0-9._~+/-]{8,}",
        re.IGNORECASE,
    ),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{10,}\b", re.IGNORECASE),
]
STRICT_EXPORT_TEXT_SUFFIXES = {
    ".csv",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
}
MAX_EXPORT_FILE_BYTES = 64 * 1024 * 1024
MAX_EXPORT_TOTAL_BYTES = 256 * 1024 * 1024
MAX_PROJECT_ENTRIES = 100_000
MAX_PROJECT_TEXT_FILES = 20_000
MAX_PROJECT_TEXT_FILE_BYTES = 16 * 1024 * 1024
MAX_PROJECT_TOTAL_TEXT_BYTES = 256 * 1024 * 1024
MAX_UNKNOWN_TEXT_PROBE_BYTES = 8 * 1024
MAX_BINARY_SECRET_SCAN_FILE_BYTES = 64 * 1024 * 1024
MAX_BINARY_SECRET_SCAN_TOTAL_BYTES = 256 * 1024 * 1024
MAX_GIT_HISTORY_COMMITS = 2_000
MAX_GIT_HISTORY_BYTES = 64 * 1024 * 1024
MAX_GIT_HISTORY_SECONDS = 30
MAX_TRUSTED_GIT_CACHE_ENTRIES = 32
ALLOWED_OUTPUT_PATHS = {
    "outputs",
    "outputs/.gitkeep",
    "outputs/traces",
    "outputs/traces/.gitkeep",
}
REQUIRED_EMPTY_OUTPUT_PLACEHOLDERS = {
    "outputs/.gitkeep",
    "outputs/traces/.gitkeep",
}
ROOT_RUNTIME_ARTIFACT_NAMES = {
    "config_snapshot.json",
    "dry_run_report.md",
    "dry_run_results.jsonl",
    "dry_run_summary.json",
    "invalid_cases.jsonl",
    "run_record.json",
}
STRICT_SECRET_PATTERNS = (
    (
        "suspected_private_key",
        re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----", re.IGNORECASE),
    ),
    ("suspected_github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("suspected_slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "suspected_slack_app_token",
        re.compile(r"\bxapp-[A-Za-z0-9-]{20,}\b", re.IGNORECASE),
    ),
    ("suspected_aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("suspected_google_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    (
        "suspected_jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    ),
    (
        "suspected_basic_auth",
        re.compile(r"\bBasic\s+[A-Za-z0-9+/]{12,}={0,2}\b", re.IGNORECASE),
    ),
    (
        "suspected_github_fine_grained_token",
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    ),
    ("suspected_gitlab_token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("suspected_huggingface_token", re.compile(r"\bhf_[A-Za-z0-9]{20,}\b")),
    ("suspected_stripe_key", re.compile(r"\bsk_live_[A-Za-z0-9]{16,}\b")),
    (
        "suspected_stripe_webhook_secret",
        re.compile(r"\bwhsec_[A-Za-z0-9]{16,}\b", re.IGNORECASE),
    ),
    (
        "suspected_digitalocean_token",
        re.compile(r"\bdop_v1_[A-Za-z0-9]{40,}\b", re.IGNORECASE),
    ),
    ("suspected_npm_token", re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b")),
    (
        "suspected_sendgrid_key",
        re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b"),
    ),
    (
        "suspected_database_url",
        re.compile(
            r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://"
            r"[^\s:/]+:[^\s@/]+@",
            re.IGNORECASE,
        ),
    ),
    (
        "suspected_uri_userinfo",
        re.compile(
            r"\b[A-Za-z][A-Za-z0-9+.-]{1,31}://" r"[^\s/@:]+:[^\s/@]+@",
            re.IGNORECASE,
        ),
    ),
)
HIGH_CONFIDENCE_BINARY_RISKS = {
    "suspected_api_key",
    "suspected_auth_token",
    "suspected_aws_key",
    "suspected_basic_auth",
    "suspected_database_url",
    "suspected_digitalocean_token",
    "suspected_github_fine_grained_token",
    "suspected_github_token",
    "suspected_gitlab_token",
    "suspected_google_key",
    "suspected_huggingface_token",
    "suspected_jwt",
    "suspected_npm_token",
    "suspected_private_key",
    "suspected_sendgrid_key",
    "suspected_slack_app_token",
    "suspected_slack_token",
    "suspected_stripe_key",
    "suspected_stripe_webhook_secret",
}
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"""
    (?<![A-Z0-9_."'-])
    (?:
        (?P<key_quote>["'])
        (?P<quoted_key>
            [A-Z0-9_-]*API[_-]?KEY|[A-Z0-9_-]*TOKEN|[A-Z0-9_-]*SECRET|
            [A-Z0-9_-]*PASSWORD|PASSPHRASE
        )
        (?P=key_quote)
      |
        (?P<bare_key>
            [A-Z0-9_-]*API[_-]?KEY|[A-Z0-9_-]*TOKEN|[A-Z0-9_-]*SECRET|
            [A-Z0-9_-]*PASSWORD|PASSPHRASE
        )
    )
    [ \t]*[:=][ \t]*["']?
    (?P<value>
        (?:Basic|Bearer|Token)[ \t]+\[TEST_FIXTURE\] |
        [A-Z0-9._/+@=-]+
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
SOURCE_SECRET_LITERAL_ASSIGNMENT_PATTERN = re.compile(
    r"""
    (?<![A-Z0-9_."'-])
    (?:
        (?P<literal_key_quote>["'])
        (?:[A-Z0-9_-]*API[_-]?KEY|[A-Z0-9_-]*TOKEN|[A-Z0-9_-]*SECRET|
           [A-Z0-9_-]*PASSWORD|PASSPHRASE)
        (?P=literal_key_quote)
      |
        (?:[A-Z0-9_-]*API[_-]?KEY|[A-Z0-9_-]*TOKEN|[A-Z0-9_-]*SECRET|
           [A-Z0-9_-]*PASSWORD|PASSPHRASE)
    )
    [ \t]*[:=][ \t]*(?P<quote>["'])(?!\[?REDACTED\]?)(?P<value>[^"'\r\n]+)(?P=quote)
    """,
    re.IGNORECASE | re.VERBOSE,
)
CONFIG_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"""
    ^[\ufeff \t]*(?:[#;][ \t]*)?(?:(?:export|set)[ \t]+)?(?:\$env:)?
    (?:[A-Z0-9_-]*API[_-]?KEY|[A-Z0-9_-]*TOKEN|[A-Z0-9_-]*SECRET|
       [A-Z0-9_-]*PASSWORD|PASSPHRASE)
    [ \t]*[:=][ \t]*(?P<value>
        ["']?(?:Basic|Bearer|Token)[ \t]+\[TEST_FIXTURE\]["']? |
        [^\s#;,]+
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
PLACEHOLDER_CREDENTIAL_VALUE = re.compile(
    r"""
    (?:
        \[REDACTED\] |
        \[TEST_FIXTURE\] |
        (?:Basic|Bearer|Token)\s+\[TEST_FIXTURE\] |
        \$\{?[A-Z_][A-Z0-9_]*\}? |
        \{[A-Z_][A-Z0-9_]*\} |
        \{\{[^{}]+\}\} |
        <[^<>]+> |
        (?:placeholder|changeme|replace[_-]?me|dummy|mock|test|example)
        (?:[_-](?:value|key|token|secret|password))? |
        your[_-][a-z0-9_-]+
    )
    \Z
    """,
    re.IGNORECASE | re.VERBOSE,
)
TEST_FIXTURE_FILE_MARKER = "safety: allow-secret-fixtures"
EXPLICIT_SYNTHETIC_TEST_VALUE = re.compile(
    r"""
    (?<![A-Z0-9._/+@-])
    (?:
        Bearer[ ](?:superSecretToken12345|NEVER_PRINT_THIS_SECRET_12345) |
        https:// user:password@ example\.com/v1 |
        https:// reviewer:SUPER_SECRET_PASSWORD@ example\.invalid/api |
        postgresql:// dbuser:DB_PASSWORD_123456@ db\.example/app |
        sk-(?:
            ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 |
            DEBUGGER_SECRET_VALUE_123456 |
            FILENAME_SECRET_VALUE_123456 |
            MOCK_CLI_QUESTION_ID_1234567890 |
            MOCK_DRY_RUN_EXCEPTION_1234567890 |
            MOCK_DRY_RUN_ID_1234567890 |
            MOCK_MANUAL_DEBUGGER_SECRET_123456 |
            MOCK_MEMORY_CONTAINER_SECRET_1234567890 |
            MOCK_NONSTANDARD_SECRET_1234567890 |
            MOCK_PROTOCOL_VALUE_1234567890 |
            PIPELINE_SECRET_VALUE_123456 |
            QUESTION_ID_SECRET_VALUE_123456 |
            REPORT_SECRET_VALUE_123456 |
            STATUS_SECRET_VALUE_123456 |
            USER_AGENT_SECRET_VALUE_123456 |
            UTF16_SECRET_VALUE_123456
        ) |
        ghp_ ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 |
        github_pat_ ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 |
        glpat- ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 |
        hf_ ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 |
        sk_live_ ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 |
        xapp-1- ABCDEFGHIJKLMNOP-1234567890-abcdefghijklmnopqrstuv |
        whsec_ ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 |
        dop_v1_ ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789AB |
        npm_ ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 |
        SG\. ABCDEFGHIJKLMNOPQRST\.UVWXYZABCDEFGHIJKLMNOP |
        AKIA ABCDEFGHIJKLMNOP |
        ABCDEFGHIJKLMNOP(?:QRSTUVWXYZ123456)? |
        REALVALUE[0-9]{6,} |
        (?:abc|bool|hidden|str|tiny|v|value|x|y) |
        (?:mock|dummy|example|placeholder|test)(?:[-_][A-Z0-9]+)+ |
        [A-Z0-9]+(?:[_-][A-Z0-9]+)*[_-]
        (?:CREDENTIAL|SECRET|TOKEN|KEY|PASSWORD|VALUE)
        (?:[_-][A-Z0-9]+)*
    )
    (?![A-Z0-9._/+@-])
    """,
    re.IGNORECASE | re.VERBOSE,
)
EXACT_SYNTHETIC_TEST_VALUES = re.compile(
    r"(?P<quote>[\"'])(?:abc|hidden|password|secret|super-secret-key|tiny|v|x|y)"
    r"(?P=quote)(?![ \t]*[:=])",
    re.IGNORECASE,
)


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_link_or_junction(path: Path) -> bool:
    try:
        return path.is_symlink() or getattr(path, "is_junction", lambda: False)()
    except OSError:
        return True


def _is_probably_doc(path: Path) -> bool:
    return (
        any(part in {"README", "docs"} for part in path.parts)
        or path.suffix.lower() == ".md"
    )


def _iter_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_TEXT_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            yield path


def _unknown_file_looks_like_utf8_text(path: Path) -> bool:
    if path.suffix.casefold() in BINARY_SUFFIXES:
        return False
    try:
        with path.open("rb") as handle:
            probe = handle.read(MAX_UNKNOWN_TEXT_PROBE_BYTES)
    except OSError:
        return False
    if not probe or b"\x00" in probe:
        return False
    try:
        probe.decode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return True


def _scan_high_confidence_binary_secrets(path: Path) -> set[str]:
    """Scan bounded binary bytes for credential formats with low false positives."""

    try:
        size = path.stat().st_size
        if size > MAX_BINARY_SECRET_SCAN_FILE_BYTES:
            return {"binary_secret_scan_file_too_large"}
        raw = path.read_bytes()
    except OSError:
        return {"unreadable_project_binary"}
    if len(raw) > MAX_BINARY_SECRET_SCAN_FILE_BYTES:
        return {"binary_secret_scan_file_too_large"}
    text = raw.decode("latin-1", errors="strict")
    return _strict_secret_risks(text) & HIGH_CONFIDENCE_BINARY_RISKS


def _git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "NoDefaultCurrentDirectoryInExePath": "1",
        }
    )
    return environment


_TRUSTED_GIT_EXECUTABLE_CACHE: dict[tuple[str, str, str], Path] = {}


def _resolved_existing_path(path: Path) -> Path | None:
    try:
        return path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None


def _is_within_path(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _validated_external_git_candidate(
    candidate: Path,
    *,
    root: Path,
    current_directory: Path,
) -> Path | None:
    if not candidate.is_absolute():
        return None
    resolved = _resolved_existing_path(candidate)
    if resolved is None or not resolved.is_file():
        return None
    if _is_within_path(resolved, root) or _is_within_path(resolved, current_directory):
        return None
    return resolved


def _trusted_git_executable(root: Path) -> Path | None:
    """Resolve Git from explicit PATH entries without searching the repository."""

    resolved_root = _resolved_existing_path(root)
    resolved_cwd = _resolved_existing_path(Path.cwd())
    search_path = os.environ.get("PATH", "")
    if resolved_root is None or resolved_cwd is None or not search_path:
        return None
    cache_key = (str(resolved_root), str(resolved_cwd), search_path)
    cached = _TRUSTED_GIT_EXECUTABLE_CACHE.get(cache_key)
    if cached is not None:
        validated = _validated_external_git_candidate(
            cached,
            root=resolved_root,
            current_directory=resolved_cwd,
        )
        if validated is not None:
            return validated
        _TRUSTED_GIT_EXECUTABLE_CACHE.pop(cache_key, None)

    for raw_entry in search_path.split(os.pathsep):
        entry = raw_entry.strip().strip('"')
        search_directory = Path(entry) if entry else resolved_cwd
        if not search_directory.is_absolute():
            search_directory = resolved_cwd / search_directory
        resolved_directory = _resolved_existing_path(search_directory)
        if resolved_directory is None or not resolved_directory.is_dir():
            continue
        if _is_within_path(resolved_directory, resolved_root) or _is_within_path(
            resolved_directory, resolved_cwd
        ):
            continue
        # Supplying an absolute candidate keeps ``shutil.which`` from adding
        # the Windows current directory to its search path.
        discovered = shutil.which(str(resolved_directory / "git"))
        if discovered is None:
            continue
        validated = _validated_external_git_candidate(
            Path(discovered),
            root=resolved_root,
            current_directory=resolved_cwd,
        )
        if validated is None:
            continue
        if len(_TRUSTED_GIT_EXECUTABLE_CACHE) >= MAX_TRUSTED_GIT_CACHE_ENTRIES:
            _TRUSTED_GIT_EXECUTABLE_CACHE.clear()
        _TRUSTED_GIT_EXECUTABLE_CACHE[cache_key] = validated
        return validated
    return None


def _bounded_git_command(
    root: Path,
    arguments: list[str],
    *,
    git_executable: Path,
    max_bytes: int,
    timeout_seconds: float,
) -> tuple[bytes | None, str | None]:
    resolved_root = _resolved_existing_path(root)
    resolved_cwd = _resolved_existing_path(Path.cwd())
    if resolved_root is None or resolved_cwd is None:
        return None, "git_history_scan_unavailable"
    validated_git = _validated_external_git_candidate(
        git_executable,
        root=resolved_root,
        current_directory=resolved_cwd,
    )
    if validated_git is None:
        return None, "git_history_scan_unavailable"
    command = [
        str(validated_git),
        "--no-pager",
        "-c",
        "diff.external=",
        "-C",
        str(root),
        *arguments,
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen(
            command,
            cwd=validated_git.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_git_environment(),
            creationflags=creationflags,
        )
    except OSError:
        return None, "git_history_scan_unavailable"
    stdout = process.stdout
    if stdout is None:
        process.kill()
        process.wait()
        return None, "git_history_scan_unavailable"

    chunks: list[bytes] = []
    state = {"bytes": 0, "exceeded": False, "error": False}

    def _read_stdout() -> None:
        try:
            while True:
                chunk = stdout.read(64 * 1024)
                if not chunk:
                    break
                state["bytes"] += len(chunk)
                if state["bytes"] > max_bytes:
                    state["exceeded"] = True
                    break
                chunks.append(chunk)
        except OSError:
            state["error"] = True

    reader = threading.Thread(target=_read_stdout, daemon=True)
    reader.start()
    reader.join(max(timeout_seconds, 0.0))
    if reader.is_alive() or state["exceeded"] or state["error"]:
        process.kill()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        stdout.close()
        reader.join(timeout=1)
        if reader.is_alive():
            return None, "git_history_scan_timeout"
        if state["exceeded"]:
            return None, "git_history_byte_limit_exceeded"
        return None, "git_history_scan_timeout"
    try:
        return_code = process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        return None, "git_history_scan_timeout"
    finally:
        stdout.close()
    if return_code != 0:
        return None, "git_history_scan_unavailable"
    return b"".join(chunks), None


def _bounded_git_history(
    root: Path,
) -> tuple[tuple[bytes, bytes] | None, str | None]:
    """Return separate bounded message and patch streams without echoing them."""

    git_executable = _trusted_git_executable(root)
    if git_executable is None:
        return None, "git_history_scan_unavailable"
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        count = subprocess.run(
            [
                str(git_executable),
                "-C",
                str(root),
                "rev-list",
                "--count",
                "--all",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=5,
            check=False,
            cwd=git_executable.parent,
            env=_git_environment(),
            creationflags=creationflags,
        )
        commit_count = int(count.stdout.strip()) if count.returncode == 0 else -1
    except (OSError, subprocess.TimeoutExpired, UnicodeError, ValueError):
        return None, "git_history_scan_unavailable"
    if commit_count < 0:
        return None, "git_history_scan_unavailable"
    if commit_count > MAX_GIT_HISTORY_COMMITS:
        return None, "git_history_commit_limit_exceeded"

    commands = [
        ("messages", ["for-each-ref", "--format=%(contents)%00", "refs/tags"]),
        (
            "messages",
            [
                "log",
                "--all",
                f"--max-count={MAX_GIT_HISTORY_COMMITS}",
                "--format=%B%x00",
            ],
        ),
        (
            "patches",
            [
                "log",
                "--all",
                f"--max-count={MAX_GIT_HISTORY_COMMITS}",
                "--format=",
                "--patch",
                "--text",
                "--no-color",
                "--no-ext-diff",
                "--no-textconv",
            ],
        ),
    ]
    deadline = time.monotonic() + MAX_GIT_HISTORY_SECONDS
    remaining_bytes = MAX_GIT_HISTORY_BYTES
    outputs: dict[str, list[bytes]] = {"messages": [], "patches": []}
    for stream, command in commands:
        output, failure = _bounded_git_command(
            root,
            command,
            git_executable=git_executable,
            max_bytes=remaining_bytes,
            timeout_seconds=deadline - time.monotonic(),
        )
        if failure is not None:
            return None, failure
        assert output is not None
        outputs[stream].append(output)
        remaining_bytes -= len(output)
    return (b"".join(outputs["messages"]), b"".join(outputs["patches"])), None


def scan_git_history(root: Path) -> list[tuple[str, str]]:
    """Scan reachable Git patch history with strict time and byte ceilings."""

    git_entry = root / ".git"
    if not git_entry.exists():
        return []
    # Packaging/export fixtures may contain an empty ``.git`` directory solely
    # to verify exclusion rules.  Such a directory has no reachable history and
    # is not a Git repository.  A real worktree always has either HEAD metadata
    # or a gitfile that redirects to the actual metadata directory; once those
    # markers exist, history-scan failures remain fail-closed below.
    if git_entry.is_dir() and not (git_entry / "HEAD").is_file():
        return []
    history, failure = _bounded_git_history(root)
    if failure is not None:
        return [("[git-history]", failure)]
    assert history is not None
    messages, patch = history
    message_text = messages.decode("utf-8", errors="replace")
    text = patch.decode("utf-8", errors="replace")
    risks = _strict_secret_risks(message_text)
    sections = re.split(r"(?m)(?=^diff --git )", text)
    for section in sections:
        scanned = section
        if _history_section_has_current_fixture_marker(root, section):
            scanned = _scrub_explicit_synthetic_test_values(section)
        section_risks = _strict_secret_risks(scanned)
        if _has_unredacted_git_diff_credential_assignment(scanned):
            section_risks.add("suspected_credential_value")
        risks.update(section_risks)
        if _has_unredacted_source_literal_secret(scanned):
            risks.add("suspected_credential_value")
    return [("[git-history]", risk) for risk in sorted(risks)]


def _bounded_project_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for current, directories, filenames in os.walk(
        root, topdown=True, followlinks=False
    ):
        directories[:] = sorted(directories)
        for name in [*directories, *sorted(filenames)]:
            paths.append(Path(current) / name)
            if len(paths) > MAX_PROJECT_ENTRIES:
                raise OSError("project entry limit exceeded")
        directories[:] = [
            name
            for name in directories
            if name not in {".git", ".venv", "venv", "node_modules"}
        ]
    return paths


def _safe_project_rel(path: Path, root: Path) -> str:
    try:
        raw = path.relative_to(root).as_posix()
    except (OSError, RuntimeError, ValueError):
        raw = "[outside-repository]"
    return _safe_finding_path(raw)


def _scan_output_placeholder(path: Path) -> set[str]:
    """Validate and secret-scan an allowed outputs/.gitkeep placeholder."""

    risks: set[str] = set()
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return {"output_placeholder_not_regular"}
        with path.open("rb") as handle:
            opened_stat = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened_stat.st_mode):
                return {"output_placeholder_not_regular"}
            raw = handle.read(MAX_PROJECT_TEXT_FILE_BYTES + 1)
    except OSError:
        return {"unreadable_output_placeholder"}

    if opened_stat.st_size != 0 or raw:
        risks.add("nonempty_output_placeholder")
    if (
        opened_stat.st_size > MAX_PROJECT_TEXT_FILE_BYTES
        or len(raw) > MAX_PROJECT_TEXT_FILE_BYTES
    ):
        risks.add("output_placeholder_too_large")
        raw = raw[:MAX_PROJECT_TEXT_FILE_BYTES]
    if b"\x00" in raw:
        risks.add("unreadable_output_placeholder")
        return risks
    try:
        text = raw.decode("utf-8", errors="strict").removeprefix("\ufeff")
    except UnicodeError:
        risks.add("unreadable_output_placeholder")
        return risks

    risks.update(_strict_secret_risks(text))
    if _has_unredacted_source_literal_secret(text) or _has_unredacted_config_secret(
        text
    ):
        risks.add("suspected_credential_value")
    return risks


def _strict_secret_risks(text: str) -> set[str]:
    risks: set[str] = set()
    if any(pattern.search(text) for pattern in API_KEY_PATTERNS):
        risks.add("suspected_api_key")
    if any(pattern.search(text) for pattern in AUTH_PATTERNS):
        risks.add("suspected_auth_token")
    if _has_risky_credential_assignment(text):
        risks.add("suspected_credential_value")
    for risk, pattern in STRICT_SECRET_PATTERNS:
        if pattern.search(text):
            risks.add(risk)
    return risks


def _looks_like_unredacted_credential_value(value: str) -> bool:
    candidate = value.strip().strip("\"'")
    return bool(candidate) and PLACEHOLDER_CREDENTIAL_VALUE.fullmatch(candidate) is None


def _credential_assignment_is_risky(match: re.Match[str]) -> bool:
    value = match.group("value")
    if not _looks_like_unredacted_credential_value(value):
        return False
    key = (match.group("quoted_key") or match.group("bare_key")).casefold()
    normalized_key = key.replace("-", "_")
    if normalized_key in {
        "contains_secret",
        "has_secret",
        "is_secret",
    }:
        return False
    candidate = value.strip().strip("\"'").casefold()
    if candidate in {"bool", "bytes", "float", "int", "none", "null", "str"}:
        return False
    tail = match.string[match.end() :].lstrip()
    if tail.startswith("(") and re.fullmatch(
        r"[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+", candidate
    ):
        return False
    if "." in candidate:
        referenced_name = candidate.rsplit(".", 1)[-1].replace("-", "_")
        if referenced_name == normalized_key:
            return False
    return True


def _has_risky_credential_assignment(text: str) -> bool:
    return any(
        _credential_assignment_is_risky(match)
        for match in SECRET_ASSIGNMENT_PATTERN.finditer(text)
    )


def _has_unredacted_config_secret(text: str) -> bool:
    for line in text.splitlines():
        match = CONFIG_SECRET_ASSIGNMENT_PATTERN.search(line)
        if match is None:
            continue
        value = match.group("value").strip().strip("\"'")
        if _looks_like_unredacted_credential_value(value):
            return True
    return False


def _has_unredacted_git_diff_credential_assignment(text: str) -> bool:
    for line in text.splitlines():
        if not line.startswith(("+", "-")) or line.startswith(("+++", "---")):
            continue
        if _has_risky_credential_assignment(line[1:]):
            return True
    return False


def _has_unredacted_source_literal_secret(text: str) -> bool:
    for match in SOURCE_SECRET_LITERAL_ASSIGNMENT_PATTERN.finditer(text):
        value = match.group("value").strip()
        if value and PLACEHOLDER_CREDENTIAL_VALUE.fullmatch(value) is None:
            return True
    return False


def _scrub_explicit_synthetic_test_values(text: str) -> str:
    scrubbed = EXPLICIT_SYNTHETIC_TEST_VALUE.sub("[TEST_FIXTURE]", text)
    return EXACT_SYNTHETIC_TEST_VALUES.sub(
        lambda match: f"{match.group('quote')}placeholder{match.group('quote')}",
        scrubbed,
    )


def _history_section_has_current_fixture_marker(root: Path, section: str) -> bool:
    """Allow exact fixture scrubbing only for a current marked tests file."""

    header = section.splitlines()[0] if section else ""
    match = re.fullmatch(r"diff --git a/(\S+) b/(\S+)", header)
    if match is None or match.group(1) != match.group(2):
        return False
    relative_text = match.group(2)
    relative = Path(relative_text)
    if (
        not relative.parts
        or relative.parts[0].casefold() != "tests"
        or relative.is_absolute()
        or ".." in relative.parts
    ):
        return False
    candidate = root / relative
    try:
        if _is_link_or_junction(candidate) or not candidate.is_file():
            return False
        with candidate.open("r", encoding="utf-8", errors="strict") as handle:
            prefix = handle.read(4_096)
    except (OSError, UnicodeError):
        return False
    return any(
        line.strip().casefold().lstrip("#;").strip() == TEST_FIXTURE_FILE_MARKER
        for line in prefix.splitlines()
    )


def _safe_finding_path(path: str) -> str:
    return "[redacted-path]" if _strict_secret_risks(path) else path


def scan_sensitive_files(paths: Iterable[Path], root: Path) -> list[tuple[str, str]]:
    """Fail-closed secret scan for the exact files selected for export."""

    findings: list[tuple[str, str]] = []
    root = root.resolve()
    candidates = {
        candidate if candidate.is_absolute() else root / candidate
        for candidate in paths
    }
    total_bytes = 0
    for path in sorted(candidates):
        try:
            raw_rel_path = path.resolve(strict=False).relative_to(root).as_posix()
        except (OSError, RuntimeError, ValueError):
            raw_rel_path = "[outside-repository]"
        rel_path = _safe_finding_path(raw_rel_path)
        if _strict_secret_risks(raw_rel_path):
            findings.append((rel_path, "sensitive_export_filename"))
        if _is_link_or_junction(path) or not path.is_file():
            findings.append((rel_path, "unsupported_export_file"))
            continue
        if path.suffix.lower() not in STRICT_EXPORT_TEXT_SUFFIXES:
            findings.append((rel_path, "unsupported_export_file_type"))
            continue
        try:
            file_bytes = path.stat().st_size
            total_bytes += file_bytes
            if file_bytes > MAX_EXPORT_FILE_BYTES:
                findings.append((rel_path, "export_file_too_large"))
                continue
            if total_bytes > MAX_EXPORT_TOTAL_BYTES:
                findings.append((rel_path, "export_total_size_exceeded"))
                continue
            text = path.read_text(encoding="utf-8", errors="strict").removeprefix(
                "\ufeff"
            )
        except (OSError, UnicodeError):
            findings.append((rel_path, "unreadable_export_text"))
            continue
        if "\x00" in text:
            findings.append((rel_path, "unreadable_export_text"))
            continue
        strict_risks = _strict_secret_risks(text)
        if _has_unredacted_source_literal_secret(text):
            strict_risks.add("suspected_credential_value")
        for risk in strict_risks:
            findings.append((rel_path, risk))
    return sorted(set(findings))


def scan_project(root: Path) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    root = root.resolve()
    try:
        project_paths = _bounded_project_paths(root)
    except OSError:
        return [("[project-root]", "project_entry_limit_exceeded")]

    git_path = root / ".git"
    if git_path.is_file():
        findings.append((".git", "git_packaging_risk"))

    text_file_count = 0
    total_text_bytes = 0
    total_binary_bytes = 0
    for path in project_paths:
        safe_rel = _safe_project_rel(path, root)
        try:
            rel = path.relative_to(root)
        except ValueError:
            findings.append((safe_rel, "outside_repository_path"))
            continue
        rel_text = rel.as_posix()
        parts_casefold = tuple(part.casefold() for part in rel.parts)
        name_casefold = path.name.casefold()

        if _strict_secret_risks(rel_text):
            findings.append((safe_rel, "sensitive_project_filename"))

        if _is_link_or_junction(path):
            findings.append((safe_rel, "linked_project_entry"))
            continue
        if (
            path.suffix.casefold() in FORBIDDEN_CREDENTIAL_SUFFIXES
            or name_casefold in FORBIDDEN_CREDENTIAL_NAMES
        ):
            findings.append((safe_rel, "forbidden_credential_file"))
            continue
        if path.suffix.casefold() in {".key", ".pem"}:
            findings.append((safe_rel, "forbidden_credential_file"))

        if name_casefold == ".env" or (
            name_casefold.startswith(".env.") and name_casefold != ".env.example"
        ):
            findings.append((safe_rel, "forbidden_env_file"))
        if name_casefold == "official_results.jsonl":
            findings.append((safe_rel, "forbidden_official_results_file"))
        if name_casefold == "submission.zip":
            findings.append((safe_rel, "forbidden_submission_archive"))
        if len(rel.parts) == 1 and name_casefold in ROOT_RUNTIME_ARTIFACT_NAMES:
            findings.append((safe_rel, "forbidden_runtime_artifact"))
        if "__pycache__" in parts_casefold:
            findings.append((safe_rel, "forbidden___pycache___artifact"))
        if ".pytest_cache" in parts_casefold:
            findings.append((safe_rel, "forbidden_.pytest_cache_artifact"))
        if parts_casefold and parts_casefold[0] == "outputs":
            if rel_text not in ALLOWED_OUTPUT_PATHS and rel_text != "outputs":
                findings.append((safe_rel, "forbidden_outputs_artifact"))
            elif rel_text in REQUIRED_EMPTY_OUTPUT_PLACEHOLDERS:
                for risk in _scan_output_placeholder(path):
                    findings.append((safe_rel, risk))
            continue
        if "outputs" in parts_casefold:
            findings.append((safe_rel, "forbidden_outputs_artifact"))
            continue
        if any(part in {"trace", "traces", "run_records"} for part in parts_casefold):
            findings.append((safe_rel, "forbidden_runtime_artifact"))
            continue
        if not path.is_file() or any(part in SKIP_TEXT_DIRS for part in rel.parts):
            continue
        declared_text = (
            path.suffix.casefold() in TEXT_SUFFIXES
            or name_casefold in CONFIG_SECRET_NAMES
        )
        looks_like_text = declared_text or _unknown_file_looks_like_utf8_text(path)
        if not looks_like_text:
            try:
                binary_size = path.stat().st_size
            except OSError:
                findings.append((safe_rel, "unreadable_project_binary"))
                continue
            total_binary_bytes += binary_size
            if total_binary_bytes > MAX_BINARY_SECRET_SCAN_TOTAL_BYTES:
                findings.append(
                    ("[project-root]", "project_binary_scan_size_limit_exceeded")
                )
                break
            for risk in _scan_high_confidence_binary_secrets(path):
                findings.append((safe_rel, risk))
            continue

        text_file_count += 1
        if text_file_count > MAX_PROJECT_TEXT_FILES:
            findings.append(("[project-root]", "project_text_file_limit_exceeded"))
            break
        try:
            size = path.stat().st_size
        except OSError:
            findings.append((safe_rel, "unreadable_project_text"))
            continue
        total_text_bytes += size
        if size > MAX_PROJECT_TEXT_FILE_BYTES:
            findings.append((safe_rel, "project_text_file_too_large"))
            continue
        if total_text_bytes > MAX_PROJECT_TOTAL_TEXT_BYTES:
            findings.append(("[project-root]", "project_text_size_limit_exceeded"))
            break
        try:
            text = path.read_text(encoding="utf-8", errors="strict").removeprefix(
                "\ufeff"
            )
        except (OSError, UnicodeError):
            findings.append((safe_rel, "unreadable_project_text"))
            continue
        if "\x00" in text:
            findings.append((safe_rel, "unreadable_project_text"))
            continue
        scanned_text = text
        if (
            rel.parts
            and rel.parts[0].casefold() == "tests"
            and TEST_FIXTURE_FILE_MARKER in text.casefold()
        ):
            scanned_text = _scrub_explicit_synthetic_test_values(text)
        strict_risks = _strict_secret_risks(scanned_text)
        if _has_unredacted_source_literal_secret(scanned_text):
            strict_risks.add("suspected_credential_value")
        is_config_secret_file = (
            path.suffix.casefold() in CONFIG_SECRET_SUFFIXES
            or name_casefold in CONFIG_SECRET_NAMES
        )
        has_unredacted_config_secret = (
            is_config_secret_file and _has_unredacted_config_secret(scanned_text)
        )
        if has_unredacted_config_secret:
            strict_risks.add("suspected_credential_value")
        for risk in strict_risks:
            findings.append((safe_rel, risk))

    findings.extend(scan_git_history(root))
    return sorted(set(findings))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check project for risky files or secret leakage."
    )
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
