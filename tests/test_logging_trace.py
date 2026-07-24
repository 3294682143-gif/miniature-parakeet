# safety: allow-secret-fixtures
import json
import os
import subprocess
from pathlib import Path

import pytest

from math_agent.logging_utils import (
    atomic_text_write,
    safe_json_dump,
    safe_text_write,
    sanitize_trace,
    write_trace,
    write_trusted_structured_artifact,
)
from math_agent.pipeline import MathAgentPipeline
from math_agent.schemas import SolveResult
from math_agent.security import (
    REDACTED,
    path_has_link_component,
    redact_sensitive_data,
    redact_sensitive_text,
)


def test_solve_default_generates_trace(tmp_path: Path):
    pipeline = MathAgentPipeline(mock=True, trace_dir=tmp_path)
    result = pipeline.solve("1+1=?", "q1")
    assert isinstance(result, SolveResult)
    trace_file = tmp_path / "q1.json"
    assert trace_file.exists()
    data = json.loads(trace_file.read_text(encoding="utf-8"))
    assert data["question_id"] == "q1"
    assert data["question"] == "1+1=?"
    assert isinstance(data["final_result"], dict)
    assert data["run_mode"] == "full"


def test_no_trace_disable(tmp_path: Path):
    pipeline = MathAgentPipeline(mock=True, save_trace=False, trace_dir=tmp_path)
    pipeline.solve("1+1=?", "q2")
    assert not (tmp_path / "q2.json").exists()


def test_trace_redacts_sensitive_values(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "math_agent.pipeline.planner.Planner.plan",
        lambda self, q, route: {"note": "ok"},
    )
    pipeline = MathAgentPipeline(mock=True, trace_dir=tmp_path)
    pipeline.solve("1+1=?", "q3")
    content = (tmp_path / "q3.json").read_text(encoding="utf-8")
    assert "INTERNS1_API_KEY" not in content
    assert "Bearer" not in content
    assert "Authorization" not in content


def test_batch_like_multiple_questions_generate_multiple_traces(tmp_path: Path):
    pipeline = MathAgentPipeline(mock=True, trace_dir=tmp_path)
    pipeline.solve("1+1=?", "a")
    pipeline.solve("2+2=?", "b")
    assert (tmp_path / "a.json").exists()
    assert (tmp_path / "b.json").exists()


def test_failure_still_generates_trace(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "math_agent.pipeline.planner.Planner.plan",
        lambda q: (_ for _ in ()).throw(RuntimeError("fail")),
    )
    pipeline = MathAgentPipeline(mock=True, trace_dir=tmp_path)
    result = pipeline.solve("1+1=?", "qf")
    assert result.status == "fail"
    data = json.loads((tmp_path / "qf.json").read_text(encoding="utf-8"))
    assert data["final_result"]["status"] == "fail"


def test_trace_write_failure_does_not_break_result(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "math_agent.pipeline.write_trace",
        lambda *a, **k: (_ for _ in ()).throw(OSError("disk")),
    )
    pipeline = MathAgentPipeline(mock=True, trace_dir=tmp_path)
    result = pipeline.solve("1+1=?", "qw")
    assert result.status == "fail"
    assert result.verification.passed is False
    assert result.error and result.error.startswith("trace_write_failed:")


def test_bare_credentials_are_redacted_recursively() -> None:
    secrets = [
        "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "AKIAABCDEFGHIJKLMNOP",
        "eyJ" + "header12345.eyJpayload12345.signature12345",
        "SOURCE_TOKEN_VALUE_123456",
        "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "glpat-ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "hf_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "sk_" + "live_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "npm_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "SG.ABCDEFGHIJKLMNOPQRST.UVWXYZABCDEFGHIJKLMNOP",
        "postgresql://dbuser:DB_PASSWORD_123456@db.example/app",
        "https://reviewer:SUPER_SECRET_PASSWORD@example.invalid/api",
    ]
    payload = {
        "question": f"debug {secrets[0]}",
        "nested": [
            secrets[1],
            {"message": secrets[2], "auth_token": secrets[4]},
            secrets[3],
            *secrets[5:],
        ],
    }

    rendered = json.dumps(sanitize_trace(payload), ensure_ascii=False)

    for secret in secrets:
        assert secret not in rendered
    assert "[REDACTED]" in rendered


def test_sensitive_dict_keys_and_additional_token_formats_are_redacted() -> None:
    secrets = [
        "xapp-1-ABCDEFGHIJKLMNOP-1234567890-abcdefghijklmnopqrstuv",
        "whsec_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "dop_v1_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789AB",
    ]
    payload = {
        secrets[0]: "safe",
        "nested": secrets[1:],
        "token_count": 3,
        "secretary": "public-role",
    }

    rendered = json.dumps(sanitize_trace(payload), ensure_ascii=False)

    for secret in secrets:
        assert secret not in rendered
    assert '"token_count": 3' in rendered
    assert '"secretary": "public-role"' in rendered


def test_unknown_high_entropy_bare_token_is_redacted() -> None:
    token = "".join(("Q7mN2pR9", "vK4xT8cL", "3sW6yH1d", "F5zJ0bUa"))

    rendered = redact_sensitive_text(f"worker output: {token}")

    assert token not in rendered
    assert REDACTED in rendered


def test_bare_hex_token_and_untrusted_named_hash_are_redacted() -> None:
    fingerprint = "0123456789abcdef" * 4

    assert redact_sensitive_text(fingerprint) == REDACTED
    assert redact_sensitive_data({"sha256": fingerprint}) == {"sha256": REDACTED}


def test_trace_writer_preserves_trusted_program_provenance_hash(
    tmp_path: Path,
) -> None:
    fingerprint = "0123456789abcdef" * 4
    output = write_trace(
        {
            "question_id": "q1",
            "input_fingerprint": fingerprint,
            "message": f"unlabeled value {fingerprint}",
        },
        tmp_path,
        "q1",
    )
    persisted = json.loads(output.read_text(encoding="utf-8"))

    assert persisted["input_fingerprint"] == fingerprint
    assert persisted["message"] == f"unlabeled value {REDACTED}"


def test_trace_writer_preserves_only_exact_trusted_hash_paths(tmp_path: Path) -> None:
    fingerprint = "0123456789abcdef" * 4
    output = write_trace(
        {
            "question_id": "q1",
            "input_fingerprint": fingerprint,
            "execution_fingerprint": fingerprint,
            "execution_profile": {
                "endpoint_sha256": fingerprint,
                "prompt_config_sha256": fingerprint,
                "trace_dir_sha256": fingerprint,
                "metadata": {"sha256": fingerprint},
            },
            "final_result": {
                "input_fingerprint": fingerprint,
                "execution_fingerprint": fingerprint,
                "metadata": {"input_fingerprint": fingerprint},
            },
            "metadata": {"input_fingerprint": fingerprint},
            "sha256": fingerprint,
        },
        tmp_path,
        "q1",
    )
    persisted = json.loads(output.read_text(encoding="utf-8"))

    assert persisted["input_fingerprint"] == fingerprint
    assert persisted["execution_fingerprint"] == fingerprint
    assert persisted["execution_profile"]["endpoint_sha256"] == fingerprint
    assert persisted["execution_profile"]["prompt_config_sha256"] == fingerprint
    assert persisted["execution_profile"]["trace_dir_sha256"] == fingerprint
    assert persisted["final_result"]["input_fingerprint"] == fingerprint
    assert persisted["final_result"]["execution_fingerprint"] == fingerprint
    assert persisted["execution_profile"]["metadata"]["sha256"] == REDACTED
    assert persisted["final_result"]["metadata"]["input_fingerprint"] == REDACTED
    assert persisted["metadata"]["input_fingerprint"] == REDACTED
    assert persisted["sha256"] == REDACTED


def test_generic_json_writer_does_not_assert_trust_in_provenance_fields(
    tmp_path: Path,
) -> None:
    fingerprint = "0123456789abcdef" * 4
    output = tmp_path / "generic.json"

    assert safe_json_dump({"input_fingerprint": fingerprint}, output)

    assert json.loads(output.read_text(encoding="utf-8")) == {
        "input_fingerprint": REDACTED
    }


def test_text_writer_does_not_trust_json_hash_field_names(tmp_path: Path) -> None:
    fingerprint = "0123456789abcdef" * 4
    output = tmp_path / "summary.json"

    safe_text_write(
        json.dumps(
            {
                "input_manifest_sha256": fingerprint,
                "sha256": fingerprint,
                "message": fingerprint,
            }
        ),
        output,
    )
    persisted = json.loads(output.read_text(encoding="utf-8"))

    assert persisted["input_manifest_sha256"] == REDACTED
    assert persisted["sha256"] == REDACTED
    assert persisted["message"] == REDACTED


def test_text_writer_requires_the_complete_known_artifact_structure(
    tmp_path: Path,
) -> None:
    fingerprint = "0123456789abcdef" * 4
    output = tmp_path / "run_record.json"

    safe_text_write(
        json.dumps({"input_manifest_sha256": fingerprint, "sha256": fingerprint}),
        output,
    )

    assert json.loads(output.read_text(encoding="utf-8")) == {
        "input_manifest_sha256": REDACTED,
        "sha256": REDACTED,
    }


def test_generic_text_writer_does_not_infer_trust_from_artifact_filename(
    tmp_path: Path,
) -> None:
    fingerprint = "0123456789abcdef" * 4
    output = tmp_path / "run_record.json"
    run_record = {
        "run_id": "run-1",
        "created_at": "2026-07-11T00:00:00Z",
        "command": "dry-run",
        "elapsed_ms": 0,
        "errors": [],
        "trace_dir": None,
        "input_manifest_sha256": fingerprint,
        "result_count": 0,
        "invalid_count": 0,
    }

    safe_text_write(json.dumps(run_record), output)

    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["input_manifest_sha256"] == REDACTED


def test_explicit_trusted_artifact_writer_preserves_manifest_hash(
    tmp_path: Path,
) -> None:
    fingerprint = "0123456789abcdef" * 4
    output = tmp_path / "run_record.json"
    run_record = {
        "run_id": "run-1",
        "created_at": "2026-07-11T00:00:00Z",
        "command": "dry-run",
        "elapsed_ms": 0,
        "errors": [],
        "trace_dir": None,
        "input_manifest_sha256": fingerprint,
        "result_count": 0,
        "invalid_count": 0,
    }

    write_trusted_structured_artifact(run_record, output)

    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["input_manifest_sha256"] == fingerprint


def test_lowercase_high_entropy_bare_token_is_redacted() -> None:
    token = "".join(("q7m2p9v4", "x8c3s6y1", "d5z0b8n2", "k4t7w9f3", "h6j1r5u0"))

    assert redact_sensitive_text(token) == REDACTED


def test_uppercase_high_entropy_bare_token_is_redacted() -> None:
    opaque_candidate = "".join(("QWERTYUIOPASDFGHJKL", "ZXCVBNMMNBVCXZLKJHGFDS"))

    assert redact_sensitive_text(opaque_candidate) == REDACTED


def test_base52_high_entropy_bare_token_is_redacted() -> None:
    opaque_candidate = "".join(
        ("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    )

    assert redact_sensitive_text(opaque_candidate) == REDACTED


def test_low_entropy_mixed_identifier_is_not_mistaken_for_a_token() -> None:
    identifier = "Ab1" * 12

    assert redact_sensitive_text(identifier) == identifier


def test_python_class_path_is_not_mistaken_for_a_bare_token() -> None:
    class_path = "math_agent.clients.interns1_client.InternS1Client"

    assert redact_sensitive_text(class_path) == class_path


def test_short_and_extended_credential_assignments_are_redacted() -> None:
    secrets = ["x", "y", "MOCK_AWS_VALUE", "MOCK_CLIENT_VALUE"]
    payload = {
        "message": (
            "api_key=x password=y "
            "AWS_SECRET_ACCESS_KEY=MOCK_AWS_VALUE "
            "CLIENT_SECRET_VALUE=MOCK_CLIENT_VALUE"
        ),
        "AWS_SECRET_ACCESS_KEY": secrets[2],
        "client-secret-value": secrets[3],
        "token_count": 3,
    }

    rendered = json.dumps(sanitize_trace(payload), ensure_ascii=False)

    for assignment in (
        "api_key=x",
        "password=y",
        "AWS_SECRET_ACCESS_KEY=MOCK_AWS_VALUE",
        "CLIENT_SECRET_VALUE=MOCK_CLIENT_VALUE",
    ):
        assert assignment not in rendered
    assert secrets[2] not in rendered
    assert secrets[3] not in rendered
    assert '"token_count": 3' in rendered


def test_redactor_makes_nonstandard_values_safe_and_jsonable() -> None:
    secret = "sk-MOCK_NONSTANDARD_SECRET_1234567890"

    class OpaqueValue:
        def __str__(self) -> str:
            return f"AWS_SECRET_ACCESS_KEY={secret}"

    cleaned = redact_sensitive_data(
        {
            "set_value": {secret, "safe"},
            "frozen_value": frozenset({secret}),
            "bytes_value": secret.encode(),
            "custom_value": OpaqueValue(),
        }
    )
    rendered = json.dumps(cleaned, ensure_ascii=False)

    assert secret not in rendered
    assert cleaned["bytes_value"] == REDACTED
    assert cleaned["custom_value"] == REDACTED


def test_path_link_detection_includes_ancestor_junctions_or_symlinks(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "linked-parent"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("directory links are unavailable on this host")
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip("directory junctions are unavailable on this host")

    try:
        assert path_has_link_component(link / "nested" / "artifact.json") is True
        assert path_has_link_component(target / "artifact.json") is False
    finally:
        if link.is_symlink():
            link.unlink()
        elif getattr(link, "is_junction", lambda: False)():
            os.rmdir(link)


def test_atomic_trace_write_does_not_follow_existing_hardlink(tmp_path: Path) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("preserve", encoding="utf-8")
    trace_path = tmp_path / "trace.json"
    try:
        os.link(victim, trace_path)
    except OSError:
        pytest.skip("hard links are unavailable on this host")

    assert safe_json_dump({"question_id": "q1"}, trace_path) is True

    assert victim.read_text(encoding="utf-8") == "preserve"
    assert json.loads(trace_path.read_text(encoding="utf-8"))["question_id"] == "q1"


def test_protocol_writer_preserves_validated_text_without_redaction(
    tmp_path: Path,
) -> None:
    value = "sk-MOCK_PROTOCOL_VALUE_1234567890"
    output = tmp_path / "result.jsonl"

    atomic_text_write(value + "\n", output)

    assert output.read_text(encoding="utf-8") == value + "\n"


def test_text_writers_enforce_final_utf8_byte_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("math_agent.logging_utils.MAX_SAFE_TEXT_BYTES", 12)

    with pytest.raises(ValueError, match="size limit"):
        atomic_text_write("数学数学数学", tmp_path / "exact.txt")
    with pytest.raises(ValueError, match="size limit"):
        safe_text_write("api_key=x", tmp_path / "redacted.txt")


def test_trace_question_id_cannot_escape_trace_directory(tmp_path: Path) -> None:
    trace_dir = tmp_path / "traces"

    trace_path = write_trace(
        {"question_id": "../escaped", "question": "safe"},
        trace_dir,
        "../escaped",
    )

    assert trace_path.parent.resolve() == trace_dir.resolve()
    assert trace_path.is_file()
    assert not (tmp_path / "escaped.json").exists()


def test_trace_names_are_case_portable_before_any_file_exists(tmp_path: Path) -> None:
    upper = write_trace({"question_id": "Q1"}, tmp_path, "Q1")
    lower = write_trace({"question_id": "q1"}, tmp_path, "q1")

    assert upper.name.startswith("~trace-")
    assert lower.name == "q1.json"
    assert upper.name.casefold() != lower.name.casefold()
    assert json.loads(upper.read_text(encoding="utf-8"))["question_id"] == "Q1"
    assert json.loads(lower.read_text(encoding="utf-8"))["question_id"] == "q1"


def test_new_trace_paths_do_not_scan_the_entire_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        os,
        "scandir",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("directory scan is forbidden")
        ),
    )

    first = write_trace({"question_id": "q1"}, tmp_path, "q1")
    second = write_trace({"question_id": "q2"}, tmp_path, "q2")

    assert first.is_file() and second.is_file()


def test_trace_and_text_writes_reject_linked_parent_directory(tmp_path: Path) -> None:
    target = tmp_path / "outside"
    target.mkdir()
    link = tmp_path / "linked"
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
        with pytest.raises(OSError, match="link or junction"):
            write_trace({"question_id": "q"}, link, "q")
        with pytest.raises(OSError, match="link or junction"):
            safe_text_write("content", link / "child" / "report.txt")
        assert not any(target.iterdir())
    finally:
        if link.is_symlink():
            link.unlink()
        elif getattr(link, "is_junction", lambda: False)():
            os.rmdir(link)


@pytest.mark.parametrize(
    "secret",
    [
        "sk-QUESTION_ID_SECRET_VALUE_123456",
        "xapp-1-ABCDEFGHIJKLMNOP-1234567890-abcdefghijklmnopqrstuv",
        "whsec_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        "dop_v1_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789AB",
    ],
)
def test_secret_shaped_question_id_is_not_used_as_filename(
    tmp_path: Path, secret: str
) -> None:
    trace_path = write_trace(
        {"question_id": secret, "question": "safe"}, tmp_path, secret
    )

    assert secret not in trace_path.name
    assert trace_path.is_file()
    assert secret not in trace_path.read_text(encoding="utf-8")


def test_pipeline_redacts_secret_from_question_and_error(
    tmp_path: Path, monkeypatch
) -> None:
    secret = "sk-PIPELINE_SECRET_VALUE_123456"

    def fail_with_secret(*args, **kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr("math_agent.pipeline.planner.Planner.plan", fail_with_secret)
    pipeline = MathAgentPipeline(mock=True, trace_dir=tmp_path)

    pipeline.solve(f"question contains {secret}", "secret-case")
    content = (tmp_path / "secret-case.json").read_text(encoding="utf-8")

    assert secret not in content
    assert "[REDACTED]" in content
