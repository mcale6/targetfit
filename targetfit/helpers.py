"""Small shared helpers."""


def truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, appending '...' if truncated."""
    if text is None:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3] + "..."
