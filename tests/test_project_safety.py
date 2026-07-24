# safety: allow-secret-fixtures
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _load_safety_module():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "check_project_safety.py"
    )
    spec = importlib.util.spec_from_file_location("check_project_safety", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


safety_module = _load_safety_module()
scan_project = safety_module.scan_project
scan_sensitive_files = safety_module.scan_sensitive_files


def test_scan_clean_repo_passes(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "README.md").write_text("project", encoding="utf-8")
    findings = scan_project(tmp_path)
    assert findings == []


def test_project_scan_applies_strict_patterns_to_source_directories(tmp_path: Path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "leak.py").write_text(
        "aws = 'AKIAABCDEFGHIJKLMNOP'\n"
        "key = '-----BEGIN " + "PRIVATE KEY-----'\n"
        "password = 'tiny'\n",
        encoding="utf-8",
    )

    risks = {risk for _, risk in scan_project(tmp_path)}

    assert "suspected_aws_key" in risks
    assert "suspected_private_key" in risks
    assert "suspected_credential_value" in risks


@pytest.mark.parametrize(
    "suffix",
    [
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".html",
        ".css",
        ".rst",
        ".vue",
        ".arbitrary-text",
    ],
)
def test_project_scan_covers_common_text_source_suffixes(
    tmp_path: Path, suffix: str
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    fixture_value = "sk-" + "A" * 24
    (source / f"sample{suffix}").write_text(
        f'const API_KEY = "{fixture_value}";\n', encoding="utf-8"
    )

    findings = scan_project(tmp_path)

    assert any(
        path == f"src/sample{suffix}" and risk == "suspected_api_key"
        for path, risk in findings
    )


def test_env_example_not_flagged(tmp_path: Path):
    (tmp_path / ".env.example").write_text(
        "INTERNS1_API_KEY=placeholder", encoding="utf-8"
    )
    findings = scan_project(tmp_path)
    assert findings == []


def test_unquoted_config_and_shell_credentials_are_flagged(tmp_path: Path) -> None:
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "prod.yaml").write_text(
        "OPENAI_API_KEY: realvalue123456789\n", encoding="utf-8"
    )
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "deploy.sh").write_text(
        "SERVICE_TOKEN=realvalue123456789\n", encoding="utf-8"
    )
    (tmp_path / "Makefile").write_text(
        "SERVICE_PASSWORD=realvalue123456789\n", encoding="utf-8"
    )

    findings = scan_project(tmp_path)
    flagged = {path for path, risk in findings if risk == "suspected_credential_value"}

    assert {"configs/prod.yaml", "scripts/deploy.sh", "Makefile"} <= flagged


def test_bom_and_powershell_credentials_are_flagged(tmp_path: Path) -> None:
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "prod.yaml").write_text(
        "\ufeffOPENAI_API_KEY: realvalue123456789\n", encoding="utf-8"
    )
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "deploy.ps1").write_text(
        "$env:SERVICE_TOKEN = 'realvalue123456789'\n", encoding="utf-8"
    )

    flagged = {
        path
        for path, risk in scan_project(tmp_path)
        if risk == "suspected_credential_value"
    }

    assert {"configs/prod.yaml", "scripts/deploy.ps1"} <= flagged


def test_sensitive_key_files_and_log_csv_secrets_are_detected(tmp_path: Path) -> None:
    (tmp_path / "server.pem").write_text(
        "-----BEGIN " + "PRIVATE KEY-----\nnot-a-real-key\n",
        encoding="utf-8",
    )
    (tmp_path / ".npmrc").write_text(
        "registry=https://example.test\n", encoding="utf-8"
    )
    (tmp_path / "debug.log").write_text(
        "Bearer " + "RANDOMLOOKINGTOKEN123456789\n", encoding="utf-8"
    )
    (tmp_path / "data.csv").write_text(
        "key," + "AKIA" + "ABCDEFGHIJKLMNOP" + "\n", encoding="utf-8"
    )

    risks = {risk for _, risk in scan_project(tmp_path)}

    assert "forbidden_credential_file" in risks
    assert "suspected_auth_token" in risks
    assert "suspected_aws_key" in risks


@pytest.mark.parametrize(
    "suffix", [".jks", ".keystore", ".ppk", ".pkcs12", ".p12", ".pfx"]
)
def test_binary_credential_containers_are_explicitly_forbidden(
    tmp_path: Path, suffix: str
) -> None:
    (tmp_path / f"forced{suffix}").write_bytes(b"binary-placeholder")

    findings = scan_project(tmp_path)

    assert (f"forced{suffix}", "forbidden_credential_file") in findings


def test_high_confidence_secret_is_detected_inside_binary_content(
    tmp_path: Path,
) -> None:
    binary = tmp_path / "opaque.bin"
    binary.write_bytes(
        b"\x00\x89BINARY\xff" + b"-----BEGIN " + b"PRIVATE KEY-----" + b"\x00"
    )

    findings = scan_project(tmp_path)

    assert ("opaque.bin", "suspected_private_key") in findings


def test_empty_git_metadata_directory_is_not_treated_as_a_repository(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()

    assert scan_project(tmp_path) == []


def test_git_history_never_executes_repository_git_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    metadata = root / ".git"
    metadata.mkdir()
    (metadata / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    repository_git = root / ("git.exe" if os.name == "nt" else "git")
    repository_git.write_text("harmless repository probe\n", encoding="utf-8")
    trusted_bin = tmp_path / "trusted-bin"
    trusted_bin.mkdir()
    trusted_git = trusted_bin / ("git.exe" if os.name == "nt" else "git")
    trusted_git.write_text("harmless trusted fixture\n", encoding="utf-8")
    execution_marker = tmp_path / "repository-git-executed.txt"

    monkeypatch.chdir(root)
    monkeypatch.setenv("PATH", os.pathsep.join((str(root), str(trusted_bin))))
    which_commands: list[str] = []

    def fake_which(
        command: str, mode: int = os.F_OK | os.X_OK, path: str | None = None
    ) -> str | None:
        del mode, path
        which_commands.append(command)
        candidate = Path(command)
        if not candidate.is_absolute():
            return str(repository_git)
        if candidate.parent == root:
            return str(repository_git)
        if candidate.parent == trusted_bin:
            return str(trusted_git)
        return None

    run_calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        run_calls.append((command, kwargs))
        executable = Path(command[0])
        if not executable.is_absolute() or executable.resolve() == repository_git:
            execution_marker.write_text("executed\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="")

    monkeypatch.setattr(safety_module.shutil, "which", fake_which)
    monkeypatch.setattr(safety_module.subprocess, "run", fake_run)

    history, failure = safety_module._bounded_git_history(root)

    assert history is None
    assert failure == "git_history_scan_unavailable"
    assert not execution_marker.exists()
    assert which_commands and all(
        Path(command).is_absolute() for command in which_commands
    )
    assert run_calls
    command, kwargs = run_calls[0]
    assert Path(command[0]).resolve() == trusted_git.resolve()
    assert Path(kwargs["cwd"]).resolve() == trusted_git.parent.resolve()
    assert kwargs["env"]["NoDefaultCurrentDirectoryInExePath"] == "1"


def test_git_history_fails_closed_when_only_repository_git_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    metadata = root / ".git"
    metadata.mkdir()
    (metadata / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    repository_git = root / ("git.exe" if os.name == "nt" else "git")
    repository_git.write_text("harmless repository probe\n", encoding="utf-8")

    monkeypatch.chdir(root)
    monkeypatch.setenv("PATH", str(root))

    def fake_which(
        command: str, mode: int = os.F_OK | os.X_OK, path: str | None = None
    ) -> str | None:
        del mode, path
        candidate = Path(command)
        if not candidate.is_absolute() or candidate.parent == root:
            return str(repository_git)
        return None

    def unexpected_run(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("repository-local Git reached subprocess.run")

    monkeypatch.setattr(safety_module.shutil, "which", fake_which)
    monkeypatch.setattr(safety_module.subprocess, "run", unexpected_run)

    history, failure = safety_module._bounded_git_history(root)

    assert history is None
    assert failure == "git_history_scan_unavailable"


def test_bounded_git_command_uses_absolute_executable_and_hardened_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    trusted_bin = tmp_path / "trusted-bin"
    trusted_bin.mkdir()
    trusted_git = trusted_bin / ("git.exe" if os.name == "nt" else "git")
    trusted_git.write_text("harmless trusted fixture\n", encoding="utf-8")
    popen_calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_popen(command: list[str], **kwargs: object) -> None:
        popen_calls.append((command, kwargs))
        raise OSError("stop after capturing the invocation")

    monkeypatch.setattr(safety_module.subprocess, "Popen", fake_popen)

    output, failure = safety_module._bounded_git_command(
        root,
        ["status", "--porcelain"],
        git_executable=trusted_git.resolve(),
        max_bytes=1024,
        timeout_seconds=1,
    )

    assert output is None
    assert failure == "git_history_scan_unavailable"
    assert popen_calls
    command, kwargs = popen_calls[0]
    assert Path(command[0]).resolve() == trusted_git.resolve()
    assert Path(command[0]).is_absolute()
    assert Path(kwargs["cwd"]).resolve() == trusted_git.parent.resolve()
    assert kwargs["env"]["NoDefaultCurrentDirectoryInExePath"] == "1"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is unavailable")
def test_deleted_secret_is_still_detected_in_git_history(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Safety Fixture"],
        cwd=tmp_path,
        check=True,
    )
    retired = tmp_path / "retired.txt"
    retired.write_text("ghp_" + "R" * 24, encoding="utf-8")
    subprocess.run(["git", "add", "retired.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "add fixture"], cwd=tmp_path, check=True)
    retired.unlink()
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "remove fixture"], cwd=tmp_path, check=True)

    findings = scan_project(tmp_path)

    assert ("[git-history]", "suspected_github_token") in findings


@pytest.mark.skipif(shutil.which("git") is None, reason="git is unavailable")
def test_secret_in_git_commit_message_is_detected(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Safety Fixture"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "README.md").write_text("clean\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "commit",
            "-qm",
            "diff --git a/x b/tests/x\nSERVICE_TOKEN=REALVALUE123456",
        ],
        cwd=tmp_path,
        check=True,
    )

    findings = scan_project(tmp_path)

    assert ("[git-history]", "suspected_credential_value") in findings


@pytest.mark.skipif(shutil.which("git") is None, reason="git is unavailable")
def test_secret_in_annotated_git_tag_message_is_detected(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Safety Fixture"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "README.md").write_text("clean\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "clean commit"], cwd=tmp_path, check=True)
    message_token = "ghp_" + "T" * 24
    subprocess.run(
        ["git", "tag", "-a", "audit-note", "-m", f"retire {message_token}"],
        cwd=tmp_path,
        check=True,
    )

    findings = scan_project(tmp_path)

    assert ("[git-history]", "suspected_github_token") in findings


@pytest.mark.skipif(shutil.which("git") is None, reason="git is unavailable")
def test_secret_in_deleted_binary_git_blob_is_detected(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Safety Fixture"],
        cwd=tmp_path,
        check=True,
    )
    retired = tmp_path / "retired.bin"
    retired.write_bytes(
        b"\x00\x89BINARY\xff" + b"-----BEGIN " + b"PRIVATE KEY-----" + b"\x00"
    )
    subprocess.run(["git", "add", "retired.bin"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "add binary fixture"],
        cwd=tmp_path,
        check=True,
    )
    retired.unlink()
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "remove binary fixture"],
        cwd=tmp_path,
        check=True,
    )

    findings = scan_project(tmp_path)

    assert ("[git-history]", "suspected_private_key") in findings


@pytest.mark.skipif(shutil.which("git") is None, reason="git is unavailable")
def test_secret_in_attribute_forced_binary_git_blob_is_detected(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Safety Fixture"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / ".gitattributes").write_text("*.txt binary\n", encoding="utf-8")
    retired = tmp_path / "retired.txt"
    retired.write_text("ghp_" + "B" * 24 + "\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", ".gitattributes", "retired.txt"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "add forced binary fixture"],
        cwd=tmp_path,
        check=True,
    )
    retired.unlink()
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "remove forced binary fixture"],
        cwd=tmp_path,
        check=True,
    )

    findings = scan_project(tmp_path)

    assert ("[git-history]", "suspected_github_token") in findings


@pytest.mark.skipif(shutil.which("git") is None, reason="git is unavailable")
def test_real_credential_assignment_in_deleted_test_file_is_detected(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Safety Fixture"],
        cwd=tmp_path,
        check=True,
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    retired = tests_dir / "retired.py"
    retired.write_text("SERVICE_TOKEN=REALVALUE123456\n", encoding="utf-8")
    subprocess.run(["git", "add", "tests/retired.py"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "add retired test"],
        cwd=tmp_path,
        check=True,
    )
    retired.unlink()
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "remove retired test"],
        cwd=tmp_path,
        check=True,
    )

    findings = scan_project(tmp_path)

    assert ("[git-history]", "suspected_credential_value") in findings


@pytest.mark.skipif(shutil.which("git") is None, reason="git is unavailable")
def test_exact_marked_fixture_stays_allowed_in_git_history(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Safety Fixture"],
        cwd=tmp_path,
        check=True,
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    fixture_token = "ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
    (tests_dir / "marked_fixture.py").write_text(
        "# safety: allow-secret-fixtures\n" f"token = '{fixture_token}'\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "tests/marked_fixture.py"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "add explicit safety fixture"],
        cwd=tmp_path,
        check=True,
    )

    assert scan_project(tmp_path) == []


def test_git_diff_assignment_detector_ignores_python_forwarding_and_types() -> None:
    patch = (
        "+        api_key: str | None = None,\n"
        "+        self.api_key = api_key or os.getenv('INTERNS1_API_KEY')\n"
        '+        raise ValueError("missing_api_key: API key is required")\n'
    )

    assert not safety_module._has_unredacted_git_diff_credential_assignment(patch)


def test_config_placeholders_remain_allowed(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(
        "INTERNS1_API_KEY=placeholder\nSERVICE_TOKEN=${SERVICE_TOKEN}\n",
        encoding="utf-8",
    )
    assert scan_project(tmp_path) == []


def test_commented_credential_in_config_is_not_treated_as_a_placeholder(
    tmp_path: Path,
) -> None:
    configs = tmp_path / "configs"
    configs.mkdir()
    fixture_value = "sk-" + "C" * 24
    (configs / "prod.yaml").write_text(
        f"# retired credential: {fixture_value}\nservice: demo\n", encoding="utf-8"
    )

    findings = scan_project(tmp_path)

    assert any(
        path == "configs/prod.yaml" and risk == "suspected_api_key"
        for path, risk in findings
    )


def test_commented_and_bare_unquoted_credential_assignments_are_flagged(
    tmp_path: Path,
) -> None:
    configs = tmp_path / "configs"
    source = tmp_path / "src"
    configs.mkdir()
    source.mkdir()
    (configs / "prod.yaml").write_text(
        "# OPENAI_API_KEY: realvalue123456789\n", encoding="utf-8"
    )
    (source / "settings.py").write_text(
        "OPENAI_API_KEY = realvalue123456789\n", encoding="utf-8"
    )

    flagged = {
        path
        for path, risk in scan_project(tmp_path)
        if risk == "suspected_credential_value"
    }

    assert {"configs/prod.yaml", "src/settings.py"} <= flagged


@pytest.mark.parametrize("embedded_word", ["TEST", "MOCK", "EXAMPLE", "REALVALUE"])
def test_fixture_marker_cannot_scrub_real_tokens_containing_fixture_words(
    tmp_path: Path, embedded_word: str
) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    sk_value = "sk-" + f"ABCD{embedded_word}EFGHIJKLMNOPQRSTUVWXYZ"
    ghp_value = "ghp_" + f"ABCD{embedded_word}EFGHIJKLMNOPQRSTUVWXYZ"
    (tests_dir / "token_fixture.py").write_text(
        "# safety: allow-secret-fixtures\n"
        f"first = '{sk_value}'\n"
        f"second = '{ghp_value}'\n",
        encoding="utf-8",
    )

    risks = {risk for _, risk in scan_project(tmp_path)}

    assert "suspected_api_key" in risks
    assert "suspected_github_token" in risks


@pytest.mark.parametrize("key", ["password", "secret"])
def test_fixture_marker_never_scrubs_credential_keys(tmp_path: Path, key: str) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    value = "QwErTyUiOpAsDfGhJkL"
    (tests_dir / "credential_fixture.py").write_text(
        "# safety: allow-secret-fixtures\n" f"data = {{'{key}': '{value}'}}\n",
        encoding="utf-8",
    )

    assert any(
        risk == "suspected_credential_value" for _, risk in scan_project(tmp_path)
    )


@pytest.mark.parametrize(
    ("relative_path", "content"),
    [
        ("configs/prod.yaml", "# OPENAI_API_KEY: CorrectHorseBatteryStaple\n"),
        ("scripts/deploy.sh", "SERVICE_PASSWORD=CorrectHorseBatteryStaple\n"),
        ("src/settings.py", "SERVICE_TOKEN = CorrectHorseBatteryStaple\n"),
        ("configs/short.yaml", "SERVICE_PASSWORD=hunter2\n"),
        ("scripts/short.sh", "SERVICE_TOKEN=abc123\n"),
        ("src/short.py", "SERVICE_PASSWORD = AbcDef\n"),
    ],
)
def test_unredacted_credentials_are_flagged_regardless_of_character_mix_or_length(
    tmp_path: Path, relative_path: str, content: str
) -> None:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")

    assert any(
        finding_path == relative_path and risk == "suspected_credential_value"
        for finding_path, risk in scan_project(tmp_path)
    )


@pytest.mark.parametrize(
    "content",
    [
        '{"SERVICE_PASSWORD":"CorrectHorseBatteryStaple"}',
        "SERVICE_TOKEN=abcdefghijklmnopqrstuvwxyz",
        '{"SERVICE_PASSWORD":"hunter2"}',
        "SERVICE_TOKEN=abc123",
        '{"SERVICE_PASSWORD":"$!@#"}',
    ],
)
def test_export_scan_blocks_unredacted_credentials(
    tmp_path: Path, content: str
) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_text(content, encoding="utf-8")

    assert any(
        risk == "suspected_credential_value"
        for _, risk in scan_sensitive_files([artifact], tmp_path)
    )


def test_env_file_flagged(tmp_path: Path):
    (tmp_path / ".env").write_text("INTERNS1_API_KEY=abc", encoding="utf-8")
    findings = scan_project(tmp_path)
    assert any(risk == "forbidden_env_file" for _, risk in findings)


def test_bearer_token_flagged(tmp_path: Path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    auth_fixture = "Bearer super" + "SecretToken12345"  # safety: allow-mock-token
    (scripts_dir / "x.py").write_text(f"TOKEN = '{auth_fixture}'\n", encoding="utf-8")
    findings = scan_project(tmp_path)
    assert any(
        path == "scripts/x.py" and risk == "suspected_auth_token"
        for path, risk in findings
    )


def test_outputs_jsonl_flagged(tmp_path: Path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "results.jsonl").write_text("{}\n", encoding="utf-8")
    findings = scan_project(tmp_path)
    assert any(risk == "forbidden_outputs_artifact" for _, risk in findings)


@pytest.mark.parametrize(
    "relative_path", ["outputs/.gitkeep", "outputs/traces/.gitkeep"]
)
def test_allowed_output_placeholders_must_be_empty_regular_files(
    tmp_path: Path, relative_path: str
) -> None:
    placeholder = tmp_path / relative_path
    placeholder.parent.mkdir(parents=True)
    placeholder.write_bytes(b"")

    assert scan_project(tmp_path) == []

    placeholder.write_text("nonempty", encoding="utf-8")
    assert (relative_path, "nonempty_output_placeholder") in scan_project(tmp_path)

    placeholder.write_bytes(b"\xff")
    findings = scan_project(tmp_path)
    assert (relative_path, "nonempty_output_placeholder") in findings
    assert (relative_path, "unreadable_output_placeholder") in findings


@pytest.mark.parametrize(
    "relative_path", ["outputs/.gitkeep", "outputs/traces/.gitkeep"]
)
def test_allowed_output_placeholders_are_still_secret_scanned(
    tmp_path: Path, relative_path: str
) -> None:
    placeholder = tmp_path / relative_path
    placeholder.parent.mkdir(parents=True)
    placeholder.write_text("sk-" + "R" * 24, encoding="utf-8")

    findings = scan_project(tmp_path)

    assert (relative_path, "nonempty_output_placeholder") in findings
    assert (relative_path, "suspected_api_key") in findings


@pytest.mark.parametrize(
    "relative_path", ["outputs/.gitkeep", "outputs/traces/.gitkeep"]
)
def test_allowed_output_placeholders_cannot_be_directories(
    tmp_path: Path, relative_path: str
) -> None:
    placeholder = tmp_path / relative_path
    placeholder.mkdir(parents=True)

    assert (relative_path, "output_placeholder_not_regular") in scan_project(tmp_path)


def test_allowed_output_directory_link_is_still_flagged(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    link = outputs / "traces"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("directory links are unavailable")
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip("directory junctions are unavailable")
    try:
        findings = scan_project(tmp_path)
        assert any(
            path == "outputs/traces" and risk == "linked_project_entry"
            for path, risk in findings
        )
    finally:
        if link.is_symlink():
            link.unlink()
        elif getattr(link, "is_junction", lambda: False)():
            os.rmdir(link)


def test_project_scan_closes_recursive_artifact_and_env_aliases(tmp_path: Path):
    nested_output = tmp_path / "outputs" / "custom" / "results.jsonl"
    nested_output.parent.mkdir(parents=True)
    nested_output.write_text("{}\n", encoding="utf-8")
    nested_official = tmp_path / "data" / "OFFICIAL_RESULTS.JSONL"
    nested_official.parent.mkdir()
    nested_official.write_text("{}\n", encoding="utf-8")
    nested_archive = tmp_path / "artifacts" / "SUBMISSION.ZIP"
    nested_archive.parent.mkdir()
    nested_archive.write_bytes(b"zip")
    (tmp_path / ".env.local").write_text("password='tiny'\n", encoding="utf-8")

    risks = {risk for _, risk in scan_project(tmp_path)}

    assert "forbidden_outputs_artifact" in risks
    assert "forbidden_official_results_file" in risks
    assert "forbidden_submission_archive" in risks
    assert "forbidden_env_file" in risks


def test_nested_runtime_artifact_directories_are_forbidden(tmp_path: Path) -> None:
    for relative in (
        "nested/outputs/results.jsonl",
        "nested/trace/raw.log",
        "nested/traces/raw.log",
        "nested/run_records/record.json",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    risks = {risk for _, risk in scan_project(tmp_path)}

    assert "forbidden_outputs_artifact" in risks
    assert "forbidden_runtime_artifact" in risks


def test_root_dry_run_artifacts_are_forbidden(tmp_path: Path) -> None:
    for name in safety_module.ROOT_RUNTIME_ARTIFACT_NAMES:
        (tmp_path / name).write_text("{}\n", encoding="utf-8")

    flagged = {
        path
        for path, risk in scan_project(tmp_path)
        if risk == "forbidden_runtime_artifact"
    }

    assert safety_module.ROOT_RUNTIME_ARTIFACT_NAMES <= flagged


def test_fixture_marker_cannot_suppress_a_real_looking_secret(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "bad.py").write_text(
        "# safety: allow-secret-fixtures\n" "token = '" + "ghp_" + "A" * 24 + "'\n",
        encoding="utf-8",
    )

    assert any(risk == "suspected_github_token" for _, risk in scan_project(tmp_path))


def test_project_scan_is_bounded_strict_and_redacts_finding_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_file = tmp_path / "user_agent.py"
    root_file.write_text("key = 'AKIAABCDEFGHIJKLMNOP'\n", encoding="utf-8")
    bad = tmp_path / "src" / "bad.py"
    bad.parent.mkdir()
    bad.write_bytes(b"\xff\xfe\x00")
    secret_dir = tmp_path / "sk-FILENAME_SECRET_VALUE_123456"
    secret_dir.mkdir()
    (secret_dir / ".env.local").write_text("x", encoding="utf-8")
    large = tmp_path / "src" / "large.py"
    large.write_text("x" * 65, encoding="utf-8")
    monkeypatch.setattr(safety_module, "MAX_PROJECT_TEXT_FILE_BYTES", 64)

    findings = scan_project(tmp_path)
    risks = {risk for _, risk in findings}
    rendered = "\n".join(f"{risk}:{path}" for path, risk in findings)

    assert "suspected_aws_key" in risks
    assert "unreadable_project_text" in risks
    assert "project_text_file_too_large" in risks
    assert "FILENAME_SECRET_VALUE" not in rendered
    assert "[redacted-path]" in rendered


def test_pycache_flagged(tmp_path: Path):
    pycache = tmp_path / "src" / "__pycache__"
    pycache.mkdir(parents=True)
    findings = scan_project(tmp_path)
    assert any("__pycache__" in risk for _, risk in findings)


def test_no_secret_echo_in_findings(tmp_path: Path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    auth_fixture = "Bearer NEVER_PRINT_THIS_SECRET_12345"  # safety: allow-mock-token
    (scripts_dir / "leak.py").write_text(auth_fixture, encoding="utf-8")
    findings = scan_project(tmp_path)
    rendered = "\n".join(f"{risk}:{path}" for path, risk in findings)
    assert "NEVER_PRINT_THIS_SECRET_12345" not in rendered


def test_sensitive_project_file_and_directory_names_are_flagged_and_redacted(
    tmp_path: Path,
) -> None:
    fixture_name = "sk-" + "D" * 24
    file_root = tmp_path / "file-case"
    directory_root = tmp_path / "directory-case"
    file_root.mkdir()
    directory_root.mkdir()
    secret_dir = directory_root / ("ghp_" + "E" * 24)
    secret_dir.mkdir()
    (file_root / f"{fixture_name}.txt").write_text("benign", encoding="utf-8")
    (secret_dir / "benign.txt").write_text("benign", encoding="utf-8")

    file_findings = scan_project(file_root)
    directory_findings = scan_project(directory_root)
    findings = [*file_findings, *directory_findings]
    rendered = "\n".join(f"{risk}:{path}" for path, risk in findings)

    assert any(risk == "sensitive_project_filename" for _, risk in file_findings)
    assert any(risk == "sensitive_project_filename" for _, risk in directory_findings)
    assert fixture_name not in rendered
    assert "ghp_" + "E" * 24 not in rendered
    assert "[redacted-path]" in rendered


def test_strict_scan_does_not_accept_generic_mock_words_as_allowline(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "trace.log"
    artifact.write_text(
        "test example mock Authorization: Bearer REAL_TOKEN_VALUE_123456",
        encoding="utf-8",
    )

    findings = scan_sensitive_files([artifact], tmp_path)

    assert any(risk == "suspected_auth_token" for _, risk in findings)


def test_strict_scan_detects_common_secret_formats(tmp_path: Path) -> None:
    artifacts = {
        "github.log": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "github-fine.log": "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "gitlab.log": "glpat-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "huggingface.log": "hf_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "stripe.log": "sk_" + "live_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "slack-app.log": "xapp-1-ABCDEFGHIJKLMNOP-1234567890-abcdefghijklmnopqrstuv",
        "stripe-webhook.log": "whsec_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "digitalocean.log": "dop_v1_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789AB",
        "npm.log": "npm_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "sendgrid.log": "SG.ABCDEFGHIJKLMNOPQRST.UVWXYZABCDEFGHIJKLMNOP",
        "aws.txt": "AKIAABCDEFGHIJKLMNOP",
        "private.md": "-----BEGIN " + "PRIVATE KEY-----",
        "credential.json": '{"client_secret":"CREDENTIAL_VALUE_123456"}',
        "authorization.json": '{"Authorization":"Token ABCDEFGHIJKLMNOP"}',
        "database.txt": "postgresql://dbuser:DB_PASSWORD_123456@db.example/app",
        "generic-uri.txt": "https://" + "alice:p@ssword@" + "example.test/path",
    }
    paths = []
    for name, content in artifacts.items():
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        paths.append(path)

    findings = scan_sensitive_files(paths, tmp_path)
    risks = {risk for _, risk in findings}

    assert "suspected_github_token" in risks
    assert "suspected_aws_key" in risks
    assert "suspected_private_key" in risks
    assert "suspected_credential_value" in risks
    assert "suspected_github_fine_grained_token" in risks
    assert "suspected_gitlab_token" in risks
    assert "suspected_huggingface_token" in risks
    assert "suspected_stripe_key" in risks
    assert "suspected_slack_app_token" in risks
    assert "suspected_stripe_webhook_secret" in risks
    assert "suspected_digitalocean_token" in risks
    assert "suspected_npm_token" in risks
    assert "suspected_sendgrid_key" in risks
    assert "suspected_database_url" in risks
    assert "suspected_uri_userinfo" in risks


def test_strict_scan_accepts_explicitly_redacted_credentials(tmp_path: Path) -> None:
    artifact = tmp_path / "trace.json"
    artifact.write_text(
        '{"Authorization":"[REDACTED]","api_key":"[REDACTED]",'
        '"message":"Bearer [REDACTED] Authorization: [REDACTED]"}',
        encoding="utf-8",
    )

    assert scan_sensitive_files([artifact], tmp_path) == []
