from __future__ import annotations

import re

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
    if not text:
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
    if ". " in candidate:
        candidate = candidate.split(". ", 1)[0].strip()
    candidate = re.sub(r"^\$+\s*(.*?)\s*\$+$", r"\1", candidate)
    candidate = candidate.strip("` ").strip()
    candidate = re.sub(r"\s+", " ", candidate)
    if len(candidate) > 160 or "```" in candidate or "###" in candidate:
        return ""
    return candidate


def _replace_latex_fractions(value: str) -> str:
    text = value
    for command in ("dfrac", "frac"):
        prefix = f"\\{command}"
        # Use balanced brace matching to handle nested fractions
        while True:
            pos = text.find(prefix)
            if pos < 0:
                break
            # Find the opening brace after the command
            brace_start = pos + len(prefix)
            while brace_start < len(text) and text[brace_start].isspace():
                brace_start += 1
            if brace_start >= len(text) or text[brace_start] != "{":
                # Skip this occurrence — maybe a false positive
                text = text[:pos] + text[pos + 1:]  # remove one backslash to avoid infinite loop
                continue
            # Find matching closing brace for numerator
            num_result = _extract_braced_content(text, brace_start)
            if num_result is None:
                break
            numerator, num_end = num_result
            # Find the opening brace for denominator
            denom_start = num_end + 1
            while denom_start < len(text) and text[denom_start].isspace():
                denom_start += 1
            if denom_start >= len(text) or text[denom_start] != "{":
                break
            # Find matching closing brace for denominator
            denom_result = _extract_braced_content(text, denom_start)
            if denom_result is None:
                break
            denominator, denom_end = denom_result
            # Replace the fraction with inline form
            replacement = f"{numerator.strip()}/{denominator.strip()}"
            text = text[:pos] + replacement + text[denom_end + 1:]
    return text


def _compact_math_spacing(value: str) -> str:
    text = re.sub(r"\s*([=+\-*/,\[\]\(\)])\s*", r"\1", value.strip())
    text = re.sub(r"\s+", " ", text)
    word_count = len(text.split())
    if word_count <= 3 and re.search(r"[=+\-*/\[\]\(\)\d]", text):
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
    value = re.sub(r"\*\*\{\s*([^{}]+?)\s*\}", r"**(\1)", value)
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
    candidate = _compact_math_spacing(candidate)
    candidate = _insert_implicit_multiplication(candidate)
    candidate = normalize_number(candidate)
    return candidate.strip()
