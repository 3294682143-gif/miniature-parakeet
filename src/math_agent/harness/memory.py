from __future__ import annotations

import importlib
import json
import os
import re
import stat
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from math_agent.io_utils import NonFiniteJSONError, strict_json_loads
from math_agent.security import (
    contains_non_finite_number,
    is_sensitive_key,
    path_has_link_component,
    redact_sensitive_data,
    redact_sensitive_text,
)

_MEMORY_THREAD_LOCKS: dict[str, threading.RLock] = {}
_MEMORY_THREAD_LOCKS_GUARD = threading.Lock()
MAX_MEMORY_FILE_BYTES = 8 * 1024 * 1024


class MemoryHub:
    def __init__(self, root: str = "memory") -> None:
        self.root = Path(root)

    def load_error_taxonomy(self) -> dict[str, Any]:
        return self._safe_load_json("error_taxonomy.json", default={})

    def load_regression_cases(self) -> dict[str, Any]:
        return self._safe_load_yaml("regression_cases.yaml", default={"cases": []})

    def load_route_stats(self) -> dict[str, Any]:
        return self._safe_load_json(
            "route_stats.json",
            default={
                "total": 0,
                "by_domain": {},
                "by_problem_type": {},
                "by_status": {},
            },
        )

    def load_skill_success_stats(self) -> dict[str, Any]:
        return self._safe_load_json(
            "skill_success_stats.json", default={"total": 0, "skills": {}}
        )

    def load_verifier_failures(self) -> dict[str, Any]:
        return self._safe_load_json(
            "verifier_failures.json", default={"total": 0, "items": []}
        )

    def load_answer_cluster_stats(self) -> dict[str, Any]:
        return self._safe_load_json(
            "answer_cluster_stats.json", default={"total": 0, "clusters": []}
        )

    def summarize_memory(self) -> dict[str, Any]:
        route = self.load_route_stats()
        skills = self.load_skill_success_stats()
        verifier = self.load_verifier_failures()
        clusters = self.load_answer_cluster_stats()
        regressions = self.load_regression_cases()
        return {
            "route_total": int(route.get("total", 0) or 0),
            "skill_total": int(skills.get("total", 0) or 0),
            "verifier_failures_total": int(verifier.get("total", 0) or 0),
            "answer_clusters_total": int(clusters.get("total", 0) or 0),
            "regression_cases_total": len(regressions.get("cases", []) or []),
        }

    def record_route_result(self, domain: str, problem_type: str, status: str) -> None:
        with self._write_lock():
            data = self.load_route_stats()
            dom = self._normalize_value(domain, fallback="unknown")
            ptype = self._normalize_value(problem_type, fallback="unknown")
            st = self._normalize_value(status, fallback="unknown")
            data["total"] = int(data.get("total", 0) or 0) + 1
            self._inc(data.setdefault("by_domain", {}), dom)
            self._inc(data.setdefault("by_problem_type", {}), ptype)
            self._inc(data.setdefault("by_status", {}), st)
            self._safe_write_json("route_stats.json", data)

    def record_skill_result(self, skill_name: str, status: str) -> None:
        with self._write_lock():
            data = self.load_skill_success_stats()
            skill = self._normalize_value(skill_name, fallback="unknown")
            st = self._normalize_value(status, fallback="unknown")
            skills = data.setdefault("skills", {})
            item = skills.setdefault(skill, {"total": 0, "by_status": {}})
            item["total"] = int(item.get("total", 0) or 0) + 1
            self._inc(item.setdefault("by_status", {}), st)
            data["total"] = int(data.get("total", 0) or 0) + 1
            self._safe_write_json("skill_success_stats.json", data)

    def record_verifier_failure(
        self, question_id: str, reason: str, route_info: dict[str, Any] | None = None
    ) -> None:
        with self._write_lock():
            data = self.load_verifier_failures()
            entry = {
                "question_id": self._normalize_value(question_id, fallback="unknown"),
                "reason": self._sanitize_text(reason, limit=300),
                "route_info": self._sanitize_payload(route_info or {}),
                "created_at": datetime.now(UTC).isoformat(),
            }
            data["total"] = int(data.get("total", 0) or 0) + 1
            items = data.setdefault("items", [])
            items.append(entry)
            self._safe_write_json("verifier_failures.json", data)

    def record_answer_cluster(
        self,
        question_id: str,
        normalized_answer: str,
        cluster_size: int,
        selected: bool,
    ) -> None:
        with self._write_lock():
            data = self.load_answer_cluster_stats()
            cluster = {
                "question_id": self._normalize_value(question_id, fallback="unknown"),
                "normalized_answer": self._sanitize_text(normalized_answer, limit=160),
                "cluster_size": max(0, int(cluster_size)),
                "selected": bool(selected),
            }
            data["total"] = int(data.get("total", 0) or 0) + 1
            data.setdefault("clusters", []).append(cluster)
            self._safe_write_json("answer_cluster_stats.json", data)

    def add_regression_case(
        self, case: dict[str, Any], allow_full_question: bool = False
    ) -> None:
        with self._write_lock():
            data = self.load_regression_cases()
            clean = self._sanitize_payload(case)
            question = str(clean.get("question", "") or "")
            if question and (not allow_full_question) and len(question) > 200:
                clean["question"] = f"{question[:200]}...[truncated]"
                clean["question_truncated"] = True
            data.setdefault("cases", []).append(clean)
            self._safe_write_yaml("regression_cases.yaml", data)

    def _safe_load_json(self, filename: str, default: dict[str, Any]) -> dict[str, Any]:
        text, status = self._read_bounded_text(filename)
        if status == "missing":
            return dict(default)
        if text is None:
            result = dict(default)
            result["warning"] = f"{status}:{filename}"
            return result
        try:
            loaded = strict_json_loads(text)
        except NonFiniteJSONError:
            result = dict(default)
            result["warning"] = f"invalid_json_number:{filename}"
            return result
        except (json.JSONDecodeError, RecursionError, ValueError):
            result = dict(default)
            result["warning"] = f"invalid_json:{filename}"
            return result
        if contains_non_finite_number(loaded):
            result = dict(default)
            result["warning"] = f"invalid_json_number:{filename}"
            return result
        loaded = redact_sensitive_data(loaded)
        if isinstance(loaded, dict):
            return loaded
        result = dict(default)
        result["warning"] = f"invalid_json_root:{filename}"
        return result

    def _safe_load_yaml(self, filename: str, default: dict[str, Any]) -> dict[str, Any]:
        text, status = self._read_bounded_text(filename)
        if status == "missing":
            return dict(default)
        if text is None:
            result = dict(default)
            result["warning"] = f"{status}:{filename}"
            return result
        try:
            loaded = yaml.safe_load(text)
        except (yaml.YAMLError, RecursionError):
            result = dict(default)
            result["warning"] = f"invalid_yaml:{filename}"
            return result
        if contains_non_finite_number(loaded):
            result = dict(default)
            result["warning"] = f"invalid_yaml_number:{filename}"
            return result
        loaded = redact_sensitive_data(loaded)
        if isinstance(loaded, dict):
            return loaded
        result = dict(default)
        result["warning"] = f"invalid_yaml_root:{filename}"
        return result

    def _read_bounded_text(self, filename: str) -> tuple[str | None, str]:
        path = self.root / filename
        if path_has_link_component(self.root):
            return None, "unsafe_memory_root"
        try:
            path_stat = os.lstat(path)
        except FileNotFoundError:
            return None, "missing"
        except OSError:
            return None, "memory_read_error"
        if (
            not stat.S_ISREG(path_stat.st_mode)
            or path_stat.st_nlink != 1
            or path_stat.st_size > MAX_MEMORY_FILE_BYTES
        ):
            return None, "unsafe_memory_file"

        descriptor: int | None = None
        try:
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            descriptor_stat = os.fstat(descriptor)
            current_path_stat = os.lstat(path)
            expected_identity = (descriptor_stat.st_dev, descriptor_stat.st_ino)
            if (
                path_has_link_component(self.root)
                or not stat.S_ISREG(descriptor_stat.st_mode)
                or descriptor_stat.st_nlink != 1
                or expected_identity
                != (current_path_stat.st_dev, current_path_stat.st_ino)
                or descriptor_stat.st_size > MAX_MEMORY_FILE_BYTES
            ):
                return None, "unsafe_memory_file"

            payload = bytearray()
            while len(payload) <= MAX_MEMORY_FILE_BYTES:
                chunk = os.read(
                    descriptor,
                    min(64 * 1024, MAX_MEMORY_FILE_BYTES + 1 - len(payload)),
                )
                if not chunk:
                    break
                payload.extend(chunk)
            post_descriptor_stat = os.fstat(descriptor)
            post_path_stat = os.lstat(path)
            if path_has_link_component(self.root):
                return None, "unsafe_memory_root"
            if (
                len(payload) > MAX_MEMORY_FILE_BYTES
                or post_descriptor_stat.st_size > MAX_MEMORY_FILE_BYTES
            ):
                return None, "memory_file_too_large"
            if (
                expected_identity
                != (post_descriptor_stat.st_dev, post_descriptor_stat.st_ino)
                or expected_identity != (post_path_stat.st_dev, post_path_stat.st_ino)
                or post_descriptor_stat.st_nlink != 1
                or post_descriptor_stat.st_size != len(payload)
                or post_path_stat.st_size != len(payload)
            ):
                return None, "memory_file_changed"
            try:
                return bytes(payload).decode("utf-8", errors="strict"), "ok"
            except UnicodeError:
                return None, "invalid_memory_encoding"
        except OSError:
            return None, "memory_read_error"
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    @contextmanager
    def _write_lock(self) -> Iterator[None]:
        self._ensure_safe_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self._ensure_safe_root()
        lock_key = str(self.root.absolute())
        with _MEMORY_THREAD_LOCKS_GUARD:
            thread_lock = _MEMORY_THREAD_LOCKS.setdefault(lock_key, threading.RLock())
        with thread_lock:
            self._ensure_safe_root()
            lock_path = self.root / ".memoryhub.lock"
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor: int | None = None
            try:
                descriptor = os.open(lock_path, flags, 0o600)
                descriptor_stat = os.fstat(descriptor)
                path_stat = os.lstat(lock_path)
                getuid = getattr(os, "getuid", None)
                if (
                    path_has_link_component(self.root)
                    or not stat.S_ISREG(descriptor_stat.st_mode)
                    or descriptor_stat.st_nlink != 1
                    or (descriptor_stat.st_dev, descriptor_stat.st_ino)
                    != (path_stat.st_dev, path_stat.st_ino)
                    or (callable(getuid) and descriptor_stat.st_uid != getuid())
                ):
                    raise OSError("unsafe MemoryHub lock")
                handle = os.fdopen(descriptor, "r+b")
                descriptor = None
            finally:
                if descriptor is not None:
                    os.close(descriptor)
            with handle:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                    os.fsync(handle.fileno())
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), int(getattr(msvcrt, "LK_LOCK")), 1)
                else:
                    fcntl = importlib.import_module("fcntl")
                    getattr(fcntl, "flock")(handle.fileno(), getattr(fcntl, "LOCK_EX"))
                try:
                    yield
                finally:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(
                            handle.fileno(), int(getattr(msvcrt, "LK_UNLCK")), 1
                        )
                    else:
                        fcntl = importlib.import_module("fcntl")
                        getattr(fcntl, "flock")(
                            handle.fileno(), getattr(fcntl, "LOCK_UN")
                        )

    def _atomic_write_text(self, filename: str, content: str) -> None:
        self._ensure_safe_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self._ensure_safe_root()
        path = self.root / filename
        temporary = self.root / f".{filename}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            self._ensure_safe_root()
            os.replace(temporary, path)
        finally:
            if not path_has_link_component(self.root):
                temporary.unlink(missing_ok=True)

    def _safe_write_json(self, filename: str, payload: dict[str, Any]) -> None:
        if contains_non_finite_number(payload):
            raise ValueError("MemoryHub JSON payload contains a non-finite number")
        sanitized = self._sanitize_payload(payload)
        safe_payload = sanitized if isinstance(sanitized, dict) else {}
        self._atomic_write_text(
            filename,
            json.dumps(safe_payload, ensure_ascii=False, indent=2, allow_nan=False)
            + "\n",
        )

    def _safe_write_yaml(self, filename: str, payload: dict[str, Any]) -> None:
        if contains_non_finite_number(payload):
            raise ValueError("MemoryHub YAML payload contains a non-finite number")
        sanitized = self._sanitize_payload(payload)
        safe_payload = sanitized if isinstance(sanitized, dict) else {}
        self._atomic_write_text(
            filename,
            yaml.safe_dump(safe_payload, allow_unicode=True, sort_keys=False),
        )

    @staticmethod
    def _inc(counter: dict[str, int], key: str) -> None:
        counter[key] = int(counter.get(key, 0) or 0) + 1

    @staticmethod
    def _normalize_value(value: Any, fallback: str) -> str:
        text = redact_sensitive_text(str(value or "").strip())
        return text or fallback

    def _sanitize_payload(self, payload: Any) -> Any:
        if contains_non_finite_number(payload):
            raise ValueError("MemoryHub payload contains a non-finite number")
        return self._drop_sensitive_keys(redact_sensitive_data(payload))

    def _ensure_safe_root(self) -> None:
        if path_has_link_component(self.root):
            raise OSError("unsafe MemoryHub root")

    def _drop_sensitive_keys(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            cleaned: dict[str, Any] = {}
            for key, value in payload.items():
                skey = str(key)
                if self._is_sensitive_key(skey):
                    continue
                cleaned[skey] = self._drop_sensitive_keys(value)
            return cleaned
        if isinstance(payload, (list, tuple)):
            return [self._drop_sensitive_keys(v) for v in payload]
        if isinstance(payload, str):
            return self._sanitize_text(payload)
        return payload

    @staticmethod
    def _is_sensitive_key(key: str) -> bool:
        return is_sensitive_key(key)

    @staticmethod
    def _sanitize_text(text: str, limit: int = 500) -> str:
        value = redact_sensitive_text(text.strip())
        value = re.sub(r"(?i)authorization\s*:\s*\S+", "[redacted]", value)
        value = re.sub(r"(?i)bearer\s+[A-Za-z0-9\-_.]+", "[redacted]", value)
        value = re.sub(r"(?i)api[_-]?key\s*[:=]\s*\S+", "[redacted]", value)
        value = re.sub(r"(?i)\.env", "[redacted-env]", value)
        if len(value) > limit:
            return f"{value[:limit]}...[truncated]"
        return value
