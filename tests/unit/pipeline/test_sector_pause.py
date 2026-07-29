"""Phase B needs an explicit pause between sectors.

The per-sector refresh_companies_current() call was ~130 s of wasted database work, but
it was also the only thing pacing Phase B: it sat between one sector's last request and
the next sector's first. Removing it without replacement would make requests arrive
faster and trip the Imperva WAF sooner, not later.

Observed live on 2026-07-29: goudengids served results for 8 sectors over ~30 minutes,
then blocked every subsequent sector on page 1. The pause is therefore a real rate
control, not a cosmetic delay, and it must be configurable so a blocked run can be
resumed more slowly.
"""

from __future__ import annotations

from scraper.pipeline.batch import BatchConfig


class TestSectorPauseConfig:
    def test_default_pause_replaces_the_matview_pacing(self) -> None:
        cfg = BatchConfig(city="oostende", sectors=["dakdekkers"])
        assert cfg.goudengids_sector_pause_s > 0

    def test_pause_is_configurable(self) -> None:
        cfg = BatchConfig(city="oostende", sectors=["dakdekkers"], goudengids_sector_pause_s=300)
        assert cfg.goudengids_sector_pause_s == 300

    def test_pause_can_be_disabled_for_tests(self) -> None:
        cfg = BatchConfig(city="oostende", sectors=["dakdekkers"], goudengids_sector_pause_s=0)
        assert cfg.goudengids_sector_pause_s == 0
