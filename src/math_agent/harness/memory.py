from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


class MemoryHub:
    def __init__(self, root: str = "memory") -> None:
        self.root = Path(root)

    def load_error_taxonomy(self) -> dict[str, Any]:
        return self._safe_load_json("error_taxonomy.json", default={})

    def load_regression_cases(self) -> dict[str, Any]:
        return self._safe_load_yaml("regression_cases.yaml", default={"cases": []})

    def load_route_stats(self) -> dict[str, Any]:
        return self._safe_load_json("route_stats.json", default={"total": 0, "by_domain": {}, "by_problem_type": {}, "by_status": {}})

    def load_skill_success_stats(self) -> dict[str, Any]:
        return self._safe_load_json("skill_success_stats.json", default={"total": 0, "skills": {}})

    def load_verifier_failures(self) -> dict[str, Any]:
        return self._safe_load_json("verifier_failures.json", default={"total": 0, "items": []})

    def load_answer_cluster_stats(self) -> dict[str, Any]:
        return self._safe_load_json("answer_cluster_stats.json", default={"total": 0, "clusters": []})

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
        data = self.load_skill_success_stats()
        skill = self._normalize_value(skill_name, fallback="unknown")
        st = self._normalize_value(status, fallback="unknown")
        skills = data.setdefault("skills", {})
        item = skills.setdefault(skill, {"total": 0, "by_status": {}})
        item["total"] = int(item.get("total", 0) or 0) + 1
        self._inc(item.setdefault("by_status", {}), st)
        data["total"] = int(data.get("total", 0) or 0) + 1
        self._safe_write_json("skill_success_stats.json", data)

    def record_verifier_failure(self, question_id: str, reason: str, route_info: dict[str, Any] | None = None) -> None:
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

    def record_answer_cluster(self, question_id: str, normalized_answer: str, cluster_size: int, selected: bool) -> None:
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

    def add_regression_case(self, case: dict[str, Any], allow_full_question: bool = False) -> None:
        data = self.load_regression_cases()
        clean = self._sanitize_payload(case)
        question = str(clean.get("question", "") or "")
        if question and (not allow_full_question) and len(question) > 200:
            clean["question"] = f"{question[:200]}...[truncated]"
            clean["question_truncated"] = True
        data.setdefault("cases", []).append(clean)
        self._safe_write_yaml("regression_cases.yaml", data)

    def _safe_load_json(self, filename: str, default: dict[str, Any]) -> dict[str, Any]:
        path = self.root / filename
        if not path.exists():
            return dict(default)
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            result = dict(default)
            result["warning"] = f"invalid_json:{filename}"
            return result
        if isinstance(loaded, dict):
            return loaded
        result = dict(default)
        result["warning"] = f"invalid_json_root:{filename}"
        return result

    def _safe_load_yaml(self, filename: str, default: dict[str, Any]) -> dict[str, Any]:
        path = self.root / filename
        if not path.exists():
            return dict(default)
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            result = dict(default)
            result["warning"] = f"invalid_yaml:{filename}"
            return result
        if isinstance(loaded, dict):
            return loaded
        result = dict(default)
        result["warning"] = f"invalid_yaml_root:{filename}"
        return result

    def _safe_write_json(self, filename: str, payload: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / filename
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _safe_write_yaml(self, filename: str, payload: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / filename
        path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    @staticmethod
    def _inc(counter: dict[str, int], key: str) -> None:
        counter[key] = int(counter.get(key, 0) or 0) + 1

    @staticmethod
    def _normalize_value(value: Any, fallback: str) -> str:
        text = str(value or "").strip()
        return text or fallback

    def _sanitize_payload(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            cleaned: dict[str, Any] = {}
            for key, value in payload.items():
                skey = str(key)
                if self._is_sensitive_key(skey):
                    continue
                cleaned[skey] = self._sanitize_payload(value)
            return cleaned
        if isinstance(payload, list):
            return [self._sanitize_payload(v) for v in payload]
        if isinstance(payload, str):
            return self._sanitize_text(payload)
        return payload

    @staticmethod
    def _is_sensitive_key(key: str) -> bool:
        lower = key.lower()
        return any(token in lower for token in ("api_key", "authorization", "bearer", ".env", "secret", "token"))

    @staticmethod
    def _sanitize_text(text: str, limit: int = 500) -> str:
        value = text.strip()
        value = re.sub(r"(?i)authorization\s*:\s*\S+", "[redacted]", value)
        value = re.sub(r"(?i)bearer\s+[A-Za-z0-9\-_.]+", "[redacted]", value)
        value = re.sub(r"(?i)api[_-]?key\s*[:=]\s*\S+", "[redacted]", value)
        value = re.sub(r"(?i)\.env", "[redacted-env]", value)
        if len(value) > limit:
            return f"{value[:limit]}...[truncated]"
        return value
