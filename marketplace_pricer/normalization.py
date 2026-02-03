from __future__ import annotations

import re


_MONEY_RE = re.compile(r"(?P<sign>-)?\$\s*(?P<num>[0-9][0-9,]*(?:\.[0-9]{1,2})?)")


def parse_usd_to_cents(text: str | None) -> int | None:
    if not text:
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    if cleaned.lower() in {"free", "$0", "$0.00"}:
        return 0

    match = _MONEY_RE.search(cleaned)
    if not match:
        return None

    num = match.group("num").replace(",", "")
    try:
        value = float(num)
    except ValueError:
        return None
    cents = int(round(value * 100))
    if match.group("sign"):
        cents *= -1
    return cents


def normalize_whitespace(text: str | None) -> str | None:
    if text is None:
        return None
    return " ".join(text.split()).strip() or None
