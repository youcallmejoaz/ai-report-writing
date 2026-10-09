from datetime import date
from decimal import Decimal

import pytest

from app.domain.values import ValueParseError, ValueType, format_value, numbers_and_dates, parse_value


def test_money_and_percent_round_trip():
    assert parse_value("£125,400.00", ValueType.MONEY) == Decimal("125400.00")
    assert format_value(Decimal("125400"), ValueType.MONEY) == "£125,400.00"
    assert format_value(parse_value("1.15%", ValueType.PERCENT), ValueType.PERCENT) == "1.15%"


@pytest.mark.parametrize("raw", ["31/03/2026", "31 March 2026", "2026-03-31", "31st Mar 2026"])
def test_uk_dates(raw):
    assert parse_value(raw, ValueType.DATE) == date(2026, 3, 31)


def test_bad_values_raise():
    with pytest.raises(ValueParseError):
        parse_value("about a hundred grand", ValueType.MONEY)
    with pytest.raises(ValueParseError):
        parse_value("maybe", ValueType.BOOLEAN)


def test_numbers_and_dates_does_not_double_count_dates():
    numbers, dates = numbers_and_dates("Worth £1,250.50 on 31 March 2026, charge 0.75%, age 63.")
    assert dates == {date(2026, 3, 31)}
    assert numbers == {Decimal("1250.50"), Decimal("0.75"), Decimal("63")}
