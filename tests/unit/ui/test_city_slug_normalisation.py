"""The city slug must be normalised to lower case at the entry point.

run_log holds BOTH 'oostende' (31 runs) and 'Oostende' (11 runs) for the same city,
because build_batch_config only stripped the value. Everything downstream that matches
on city_slug does so case-sensitively:

- batch.py's Phase C2 scope query (``WHERE city_slug = $1``) misses runs recorded under
  the other casing, so those companies never get search validation.
- The goudengids skip_recent dedup keys on the same column, so a differently-cased run
  looks like a different city and gets re-scraped — at concurrency 1 against a WAF that
  is the most expensive mistake the pipeline can make.

get_postal_codes already lowercases, which is why city resolution kept working and hid
the split.
"""

from __future__ import annotations

import pytest

from scraper.ui.run_config import build_batch_config


def _cfg(city: str) -> object:
    return build_batch_config(city=city, sectors=["elektriciens"])


class TestCityIsLowercased:
    def test_capitalised_city_is_normalised(self) -> None:
        assert _cfg("Oostende").city == "oostende"

    def test_already_lowercase_is_unchanged(self) -> None:
        assert _cfg("oostende").city == "oostende"

    def test_surrounding_whitespace_still_stripped(self) -> None:
        assert _cfg("  Oostende  ").city == "oostende"

    def test_mixed_case_is_normalised(self) -> None:
        assert _cfg("SiNt-NiKlAaS").city == "sint-niklaas"

    def test_blank_city_still_rejected(self) -> None:
        with pytest.raises(ValueError, match="city is required"):
            _cfg("   ")
