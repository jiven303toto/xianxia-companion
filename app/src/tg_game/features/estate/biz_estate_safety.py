import re


URL_PATTERN = re.compile(r"(?:https?|tg)://[^\s<>'\"）)]+", re.IGNORECASE)


def _safe_text(value: object, max_length: int = 80) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    text = URL_PATTERN.sub("[url]", text)
    if len(text) > max_length:
        return f"{text[: max_length - 1]}..."
    return text
