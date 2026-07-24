from __future__ import annotations

import re

MAX_NORMALIZE_INPUT_CHARS = 8_192
MAX_EXTRACTION_INPUT_CHARS = 64 * 1024
MAX_BOXED_ANSWERS = 32
MAX_FRACTION_REPLACEMENT_PASSES = 128

_ANSWER_PATTERNS = [
    r"final\s*answer\s*[:：]\s*(.+)$",
    r"answer\s*[:：]\s*(.+)$",
    r"result\s*[:：]\s*(.+)$",
    r"最终答案\s*[：:]\s*(.+)$",
    r"最终结论\s*[：:]\s*(.+)$",
    r"答案\s*[：:]\s*(.+)$",
    r"\*\*答案\*\*\s*[：:]\s*(.+)$",
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


def extract_boxed_answers(text: str) -> list[str]:
    if not text or len(text) > MAX_EXTRACTION_INPUT_CHARS:
        return []
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
                    if len(matches) >= MAX_BOXED_ANSWERS:
                        break
                start = end_pos + 1
                continue
        start = pos + len(needle)
    return matches


def extract_boxed_answer(text: str) -> str | None:
    matches = extract_boxed_answers(text)
    if matches:
        return matches[-1]
    return None


def extract_answer_by_patterns(text: str) -> str | None:
    if not text or len(text) > MAX_EXTRACTION_INPUT_CHARS:
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
    if len(candidate) > 160 or "```" in candidate or "###" in candidate:
        return ""
    return candidate


def _replace_latex_fractions(value: str) -> str:
    text = value
    for command in ("dfrac", "frac"):
        pattern = re.compile(rf"\\{command}\s*\{{([^{{}}]+)\}}\s*\{{([^{{}}]+)\}}")
        for _ in range(MAX_FRACTION_REPLACEMENT_PASSES):
            updated = pattern.sub(
                lambda m: f"{m.group(1).strip()}/{m.group(2).strip()}",
                text,
            )
            if updated == text:
                break
            text = updated
        else:
            return ""
    return text


def _compact_math_spacing(value: str) -> str:
    text = re.sub(r"\s*([=+\-*/,\[\]\(\)])\s*", r"\1", value.strip())
    text = re.sub(r"\s+", " ", text)
    if re.search(r"[=+\-*/\[\]\(\)\d]", text):
        text = text.replace(" ", "")
    return text


def _insert_implicit_multiplication(value: str) -> str:
    text = value
    text = re.sub(r"(?<=\d)(?=pi\b)", "*", text, flags=re.I)
    text = re.sub(r"(?<=\d)(?=[a-zA-Z])", "*", text)
    text = re.sub(r"\)(?=\d|[a-zA-Z])", ")*", text)
    text = re.sub(r"(?<=\d)\(", "*(", text)
    text = re.sub(r"\)\(", ")*(", text)
    text = text.replace("**", "__POW__")
    text = re.sub(r"\*+", "*", text)
    return text.replace("__POW__", "**")


def strip_units(text: str) -> str:
    value = text.strip()
    return re.sub(
        r"(?<=\d)\s*(cm|mm|m|km|kg|g|mg|s|sec|celsius|dollars|usd|%)\b$",
        "",
        value,
        flags=re.I,
    ).strip()


def normalize_latex(text: str) -> str:
    value = text.strip()
    value = value.strip("$")
    value = value.replace("\\left", "").replace("\\right", "")
    value = re.sub(r"\\(?:text|mathrm)\s*\{([^{}]+)\}", r"\1", value)
    value = _replace_latex_fractions(value)
    value = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r"sqrt(\1)", value)
    value = re.sub(r"sqrt\s*\{([^{}]+)\}", r"sqrt(\1)", value)
    value = value.replace("\\cdot", "*").replace("\\times", "*")
    value = value.replace("\\pi", "pi").replace("π", "pi")
    value = value.replace("^", "**")
    value = value.replace("\\", "")
    return value.strip()


def normalize_number(text: str) -> str:
    value = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text.strip())
    value = re.sub(
        r"(?<![\d.])([-+]?\d+)\.0+(?=($|[+\-*/\)]))",
        lambda m: m.group(1),
        value,
    )
    value = re.sub(r"(?<!\d)1\*pi\b", "pi", value)
    decimal_match = re.fullmatch(r"(?P<sign>[-+]?)(?P<int>\d*)\.(?P<frac>\d+)", value)
    if decimal_match:
        integer = decimal_match.group("int").lstrip("0") or "0"
        fraction = decimal_match.group("frac").rstrip("0")
        sign = decimal_match.group("sign")
        if integer == "0" and not fraction:
            sign = ""
        return f"{sign}{integer}" + (f".{fraction}" if fraction else "")
    return value


def normalize_answer(text: str) -> str:
    if not isinstance(text, str) or len(text) > MAX_NORMALIZE_INPUT_CHARS:
        return ""
    boxed = extract_boxed_answer(text)
    if boxed is not None:
        candidate = boxed
    else:
        candidate = text
        extracted = extract_answer_by_patterns(text)
        if extracted is not None:
            candidate = extracted

    candidate = normalize_latex(candidate)
    candidate = _compact_math_spacing(candidate)
    candidate = _insert_implicit_multiplication(candidate)
    candidate = normalize_number(candidate)
    return candidate.strip()
