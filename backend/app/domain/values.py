"""Typed fact values: parsing from source text, canonical formatting, and number/date detection.

Numbers, dates and money are never typed by the model into the report: they are parsed once from
evidence, stored typed, and formatted deterministically here. The verifier uses ``numbers_and_dates``
to check that any figure appearing in AI-drafted text matches a figure in the facts it cites.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any


class ValueType(StrEnum):
    TEXT = "text"
    MONEY = "money"
    DATE = "date"
    PERCENT = "percent"
    INTEGER = "integer"
    BOOLEAN = "boolean"


class ValueParseError(ValueError):
    pass


_MONTHS = {
    m: i
    for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"],
        start=1,
    )
}
_MONTH_ABBR = {m[:3]: i for m, i in _MONTHS.items()}

_DATE_LONG = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\s+(\d{4})\b")
_DATE_SLASH = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MONEY = re.compile(r"£\s?(\d[\d,]*(?:\.\d+)?)")
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s?%")
_NUMBER = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(?![\w])")


def _to_decimal(raw: str) -> Decimal:
    try:
        return Decimal(raw.replace(",", "").replace("£", "").strip())
    except InvalidOperation as exc:
        raise ValueParseError(f"not a number: {raw!r}") from exc


def _month(name: str) -> int | None:
    name = name.lower()
    return _MONTHS.get(name) or _MONTH_ABBR.get(name[:3])


def parse_date(raw: str) -> date:
    raw = raw.strip()
    if m := _DATE_ISO.search(raw):
        return date(int(m[1]), int(m[2]), int(m[3]))
    if m := _DATE_SLASH.search(raw):  # UK convention: day/month/year
        return date(int(m[3]), int(m[2]), int(m[1]))
    if (m := _DATE_LONG.search(raw)) and (month := _month(m[2])):
        return date(int(m[3]), month, int(m[1]))
    raise ValueParseError(f"not a recognised date: {raw!r}")


def parse_value(raw: Any, value_type: ValueType) -> Any:
    """Parse a raw extracted string into a typed value. Raises ValueParseError on failure."""
    if raw is None:
        raise ValueParseError("missing value")
    if value_type is ValueType.TEXT:
        text = str(raw).strip()
        if not text:
            raise ValueParseError("empty text")
        return text
    if value_type is ValueType.MONEY:
        if isinstance(raw, (int, Decimal)):
            return Decimal(raw)
        return _to_decimal(str(raw))
    if value_type is ValueType.PERCENT:
        if isinstance(raw, (int, Decimal)):
            return Decimal(raw)
        return _to_decimal(str(raw).replace("%", ""))
    if value_type is ValueType.INTEGER:
        if isinstance(raw, int):
            return raw
        d = _to_decimal(str(raw))
        if d != d.to_integral_value():
            raise ValueParseError(f"not an integer: {raw!r}")
        return int(d)
    if value_type is ValueType.DATE:
        if isinstance(raw, date):
            return raw
        if isinstance(raw, datetime):
            return raw.date()
        return parse_date(str(raw))
    if value_type is ValueType.BOOLEAN:
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in {"yes", "y", "true", "1"}:
            return True
        if s in {"no", "n", "false", "0", "none"}:
            return False
        raise ValueParseError(f"not a yes/no value: {raw!r}")
    raise ValueParseError(f"unsupported type {value_type}")


def format_value(value: Any, value_type: ValueType) -> str:
    """House formatting for client-facing output (UK conventions)."""
    if value_type is ValueType.MONEY:
        return f"£{Decimal(value):,.2f}"
    if value_type is ValueType.PERCENT:
        return f"{Decimal(value).normalize():f}%"
    if value_type is ValueType.DATE:
        d = value if isinstance(value, date) else parse_date(str(value))
        return f"{d.day} {d.strftime('%B')} {d.year}"
    if value_type is ValueType.BOOLEAN:
        return "Yes" if value else "No"
    return str(value)


def to_json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def from_json_value(value: Any, value_type: ValueType) -> Any:
    return parse_value(value, value_type)


def numbers_and_dates(text: str) -> tuple[set[Decimal], set[date]]:
    """Find every date and number in a piece of text.

    Dates are extracted first and removed so their day/year components are not double-counted
    as free-standing numbers.
    """
    dates: set[date] = set()
    remaining = text
    for pattern in (_DATE_ISO, _DATE_SLASH, _DATE_LONG):
        for m in list(pattern.finditer(remaining)):
            try:
                dates.add(parse_date(m[0]))
            except (ValueParseError, ValueError):
                continue
            remaining = remaining.replace(m[0], " ")
    numbers: set[Decimal] = set()
    for pattern in (_MONEY, _PERCENT):
        for m in list(pattern.finditer(remaining)):
            numbers.add(_to_decimal(m[1]))
            remaining = remaining.replace(m[0], " ")
    for m in _NUMBER.finditer(remaining):
        numbers.add(_to_decimal(m[1]))
    return {n.normalize() for n in numbers}, dates
