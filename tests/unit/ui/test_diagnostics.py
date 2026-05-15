"""Unit tests for the diagnostics panel helpers."""

from __future__ import annotations

from scraper.ui.components.diagnostics import compute_coverage_matrix


class TestComputeCoverageMatrix:
    def test_empty_rows_yields_zero_for_every_field(self) -> None:
        cov = compute_coverage_matrix([])
        assert all(v == 0.0 for v in cov.values())
        assert "phone" in cov
        assert "website" in cov

    def test_full_row_yields_100_pct(self) -> None:
        row = {
            "phone": "+3232361306",
            "website": "https://x.be",
            "address": "Some St, 2060 Antwerpen",
            "founding_date": "1989-12-28",
            "function_holders": "Boonen Peter",
            "revenue_latest": 1_500_000.0,
            "email": "info@x.be",
        }
        cov = compute_coverage_matrix([row])
        for field, frac in cov.items():
            assert frac == 1.0, f"{field} should be 100% covered, got {frac}"

    def test_missing_string_field_counts_as_missing(self) -> None:
        rows = [
            {"phone": "+32x", "website": "https://x.be", "email": ""},
            {"phone": "", "website": "https://y.be", "email": "y@y.be"},
        ]
        cov = compute_coverage_matrix(rows)
        assert cov["phone"] == 0.5, "1 of 2 rows has a phone"
        assert cov["website"] == 1.0, "both rows have a website"
        assert cov["email"] == 0.5, "1 of 2 rows has an email"

    def test_none_counts_as_missing_for_numeric_fields(self) -> None:
        rows = [
            {"revenue_latest": None},
            {"revenue_latest": 1000.0},
            {"revenue_latest": 0},  # zero is a real value, counts as present
        ]
        cov = compute_coverage_matrix(rows)
        assert cov["revenue_latest"] == pytest_approx(2 / 3)


def pytest_approx(value: float, tol: float = 1e-9) -> float:
    """Tiny stand-in for pytest.approx to keep this test file dependency-light."""

    class _Approx:
        def __eq__(self, other: object) -> bool:
            return isinstance(other, (int, float)) and abs(float(other) - value) < tol

        def __repr__(self) -> str:
            return f"~{value}"

    return _Approx()  # type: ignore[return-value]
