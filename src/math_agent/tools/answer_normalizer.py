from __future__ import annotations

import re


_BOXED_RE = re.compile(r"\\boxed\{([^{}]+)\}")


def extract_boxed_answer(text: str) -> str | None:
    if not text:
        return None
    matches = _BOXED_RE.findall(text)
    if matches:
        return matches[-1].strip()
    return None


def strip_units(text: str) -> str:
    value = text.strip()
    value = re.sub(r"\s*(cm|mm|m|km|kg|g|mg|s|sec|°c|celsius|dollars|usd|%)+\b", "", value, flags=re.I)
    return value.strip()


def normalize_latex(text: str) -> str:
    value = text.strip()
    value = value.replace("\\left", "").replace("\\right", "")
    value = value.replace("^", "**")
    value = value.replace('\\', '')
    return value.strip()


def normalize_number(text: str) -> str:
    value = text.strip().replace(",", "")
    if re.fullmatch(r"[-+]?\d+\.0+", value):
        return str(int(float(value)))
    if re.fullmatch(r"[-+]?\d*\.\d+", value):
        normalized = str(float(value)).rstrip("0").rstrip(".")
        return normalized if normalized else "0"
    return value


def normalize_answer(text: str) -> str:
    boxed = extract_boxed_answer(text)
    if boxed is not None:
        candidate = boxed
    else:
        patterns = [
            r"最终答案\s*[：:]\s*(.+)$",
            r"答案\s*[：:]\s*(.+)$",
            r"answer\s*[:：]\s*(.+)$",
            r"final_answer\.value\s*[=:：]\s*(.+)$",
        ]
        candidate = text
        for pattern in patterns:
            matched = re.search(pattern, text, flags=re.I | re.M)
            if matched:
                candidate = matched.group(1).strip()
                break

    candidate = strip_units(candidate)
    candidate = normalize_latex(candidate)
    candidate = normalize_number(candidate)
    return candidate.strip()
