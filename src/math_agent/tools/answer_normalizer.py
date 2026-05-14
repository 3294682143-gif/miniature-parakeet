from __future__ import annotations

import re


_ANSWER_PATTERNS = [
    r"最终答案\s*[：:]\s*(.+)$",
    r"最终结论\s*[：:]\s*(.+)$",
    r"答案\s*[：:]\s*(.+)$",
    r"answer\s*[:：]\s*(.+)$",
    r"final_answer\.value\s*[=:：]\s*(.+)$",
    r"解为\s*(.+)$",
    r"解得\s*(.+)$",
    r"所以\s*(.+)$",
]


def _extract_braced_content(text: str, open_idx: int) -> tuple[str, int] | None:
    if open_idx < 0 or open_idx >= len(text) or text[open_idx] != "{":
        return None
    depth = 0
    chars: list[str] = []
    for idx in range(open_idx, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
            if depth > 1:
                chars.append(ch)
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                return "".join(chars), idx
            if depth < 0:
                return None
            chars.append(ch)
            continue
        if depth >= 1:
            chars.append(ch)
    return None


def extract_boxed_answer(text: str) -> str | None:
    if not text:
        return None
    needle = r"\boxed"
    start = 0
    matches: list[str] = []
    while True:
        pos = text.find(needle, start)
        if pos < 0:
            break
        brace_pos = pos + len(needle)
        while brace_pos < len(text) and text[brace_pos].isspace():
            brace_pos += 1
        if brace_pos < len(text) and text[brace_pos] == "{":
            parsed = _extract_braced_content(text, brace_pos)
            if parsed is not None:
                content, end_pos = parsed
                cleaned = content.strip().replace("\\\\", "\\")
                if cleaned:
                    matches.append(cleaned)
                start = end_pos + 1
                continue
        start = pos + len(needle)
    if matches:
        return matches[-1]
    return None


def extract_answer_by_patterns(text: str) -> str | None:
    if not text:
        return None
    cleaned_text = text.replace("**", "")
    for pattern in _ANSWER_PATTERNS:
        matched = re.search(pattern, cleaned_text, flags=re.I | re.M)
        if matched:
            candidate = _clean_extracted_answer(matched.group(1))
            if candidate:
                return candidate
    return None


def _clean_extracted_answer(raw: str) -> str:
    candidate = (raw or "").strip()
    candidate = candidate.replace("**", "").strip()
    if "。" in candidate:
        candidate = candidate.split("。", 1)[0].strip()
    candidate = re.sub(r"^\$+\s*(.*?)\s*\$+$", r"\1", candidate)
    candidate = candidate.strip("` ").strip()
    candidate = re.sub(r"\s+", " ", candidate)
    return candidate


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
        candidate = text
        extracted = extract_answer_by_patterns(text)
        if extracted is not None:
            candidate = extracted

    candidate = strip_units(candidate)
    candidate = normalize_latex(candidate)
    candidate = normalize_number(candidate)
    return candidate.strip()
