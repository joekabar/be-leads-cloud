from __future__ import annotations

import pytest

from scraper.db.fields import is_financial_field, validate_field
from scraper.lib.errors import InvalidFieldError


def test_is_financial_revenue() -> None:
    assert is_financial_field("revenue_2023") is True


def test_is_financial_profit() -> None:
    assert is_financial_field("profit_2021") is True


def test_is_financial_employees() -> None:
    assert is_financial_field("employees_2024") is True


def test_is_financial_phone_false() -> None:
    assert is_financial_field("phone") is False


def test_is_financial_short_year_false() -> None:
    assert is_financial_field("revenue_99") is False


def test_is_financial_wrong_prefix_false() -> None:
    assert is_financial_field("xxx_2023") is False


def test_validate_field_static_ok() -> None:
    validate_field("phone")  # must not raise


def test_validate_field_financial_ok() -> None:
    validate_field("revenue_2023")  # must not raise


def test_validate_field_unknown_raises() -> None:
    with pytest.raises(InvalidFieldError):
        validate_field("unknown_field_xyz")
