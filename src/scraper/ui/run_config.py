"""UI-input → BatchConfig mapping and sector validation.

Kept free of any ``streamlit`` import so it can be unit-tested directly. The
Streamlit batch page (``ui/pages/run_pipeline.py``) collects widget values and
hands them to :func:`build_batch_config`; the resulting :class:`BatchConfig` is
then passed to :func:`scraper.pipeline.batch.run_batch`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from scraper.pipeline.batch import BatchConfig
from scraper.pipeline.orchestrator import _SECTOR_NACE_PREFIXES

if TYPE_CHECKING:
    from pathlib import Path


def resolve_sectors(sectors: list[str], *, all_sectors: bool) -> list[str]:
    """Return the validated sector slug list.

    ``all_sectors`` wins over an explicit list (mirrors ``batch_cli``). Raises
    ``ValueError`` on an unknown slug or when neither input selects anything.
    """
    if all_sectors:
        return list(_SECTOR_NACE_PREFIXES.keys())
    if not sectors:
        raise ValueError("Select at least one sector, or enable 'all sectors'.")
    unknown = [s for s in sectors if s not in _SECTOR_NACE_PREFIXES]
    if unknown:
        valid = ", ".join(sorted(_SECTOR_NACE_PREFIXES))
        raise ValueError(f"Unknown sector slug(s): {unknown}. Valid slugs: {valid}")
    return list(sectors)


def build_batch_config(
    *,
    city: str,
    sectors: list[str],
    all_sectors: bool = False,
    lang: Literal["nl", "fr"] = "nl",
    max_pages: int = 25,
    do_kbo_dump: bool = True,
    do_goudengids: bool = True,
    do_kbopub: bool = True,
    do_nbb: bool = True,
    do_website: bool = True,
    do_search: bool = True,
    export_dir: Path | None = None,
    export_chunk_size: int = 5000,
    goudengids_skip_recent_hours: int = 720,
    ddg_brave_skip_recent_hours: int = 168,
    nbb_subscription_key: str | None = None,
    brave_subscription_key: str | None = None,
) -> BatchConfig:
    """Validate UI inputs and assemble a :class:`BatchConfig`.

    Raises ``ValueError`` for an empty city or an invalid sector selection so the
    page can surface the message without starting a thread.
    """
    if not city.strip():
        raise ValueError("city is required")
    resolved = resolve_sectors(sectors, all_sectors=all_sectors)
    return BatchConfig(
        city=city.strip(),
        sectors=resolved,
        lang=lang,
        max_pages=max_pages,
        nbb_subscription_key=nbb_subscription_key,
        brave_subscription_key=brave_subscription_key,
        do_kbo_dump=do_kbo_dump,
        do_goudengids=do_goudengids,
        do_kbopub=do_kbopub,
        do_nbb=do_nbb,
        do_website=do_website,
        do_search=do_search,
        export_dir=export_dir,
        export_chunk_size=export_chunk_size,
        goudengids_skip_recent_hours=goudengids_skip_recent_hours,
        ddg_brave_skip_recent_hours=ddg_brave_skip_recent_hours,
    )
