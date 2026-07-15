from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_ASSERTION_TOKEN = re.compile(
    r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b"
    r"|(?<![\w.])[+-]?(?:\d+(?:[.,]\d+)?|\.\d+)\s?(?:%|ms|s|Hz|fps|px)?",
    re.IGNORECASE,
)
_NUMBER_AND_UNIT = re.compile(
    r"(?P<number>[+-]?(?:\d+(?:[.,]\d+)?|\.\d+))(?P<unit>%|ms|s|hz|fps|px)?$",
    re.IGNORECASE,
)


def _normalize_token(value: str) -> str:
    compact = re.sub(r"\s+", "", value).casefold()
    match = _NUMBER_AND_UNIT.fullmatch(compact)
    if not match:
        return compact
    try:
        number = Decimal(match.group("number").replace(",", ""))
    except InvalidOperation:
        return compact
    normalized = format(number.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    if normalized == "-0":
        normalized = "0"
    return normalized + (match.group("unit") or "").casefold()


def assertion_tokens(value: str) -> set[str]:
    """Return normalized numeric, unit-bearing, and DOI assertions."""

    return {_normalize_token(match.group(0)) for match in _ASSERTION_TOKEN.finditer(value)}


def unsupported_assertion_tokens(value: str, support_texts: list[str]) -> list[str]:
    """Find concrete assertions absent from supplied approved evidence text.

    A unit-bearing assertion requires the same unit. A unitless chart value may be
    supported by the same number with a unit in evidence; labels still carry and
    therefore validate their units independently.
    """

    requested = assertion_tokens(value)
    support = set().union(*(assertion_tokens(item) for item in support_texts))
    support_numbers = {
        match.group("number")
        for item in support
        if (match := _NUMBER_AND_UNIT.fullmatch(item)) is not None
    }
    unsupported: list[str] = []
    for token in sorted(requested):
        match = _NUMBER_AND_UNIT.fullmatch(token)
        if token in support:
            continue
        if (
            match is not None
            and not match.group("unit")
            and match.group("number") in support_numbers
        ):
            continue
        unsupported.append(token)
    return unsupported
