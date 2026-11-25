# AI use: generated with ChatGPT (OpenAI, 2026); moved here and commented
# with Claude (Anthropic, Claude Opus 5.5, 2026). See README.md, "AI use".
"""Small helpers used in several files."""

import math


def number(value):
    """Turn an API value into a float, or None if it is missing or invalid.

    None means "no data", which is different from 0.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def metric_text(value, unit="", decimals=1):
    """Format a value for display, e.g. 5.2 → "5.2 km"; missing → "Unavailable"."""
    value = number(value)
    return "Unavailable" if value is None else f"{value:.{decimals}f}{unit}"
