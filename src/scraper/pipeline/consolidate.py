"""Placeholder-KBO → real-KBO consolidation pass using rapidfuzz name matching."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import structlog
from rapidfuzz import fuzz

from scraper.db.models import Observation
from scraper.db.repositories.observations import ObservationsRepo
from scraper.db.repositories.runs import RunsRepo
from scraper.sources.ddg_brave.classifier import normalize_name

if TYPE_CHECKING:
    import asyncpg

logger = structlog.get_logger()

_LEGAL_FORMS = frozenset(
    {"bv", "nv", "sa", "sprl", "srl", "bvba", "cvba", "scrl", "commv", "cv", "vzw", "asbl"}
)


def _strip_diacritics(s: str) -> str:
    nfkd = unicodedata.normalize("NFD", s)
    return nfkd.encode("ascii", "ignore").decode("ascii")


def _normalize_for_match(name: str) -> str:
    """Lowercase, strip diacritics, strip legal-form suffixes, strip punctuation."""
    if not name:
        return ""
    return normalize_name(name)


@dataclass(frozen=True, slots=True)
class ConsolidationMatch:
    placeholder_kbo: str
    real_kbo: str
    score: float
    matched_on: Literal["name+postal", "name+city", "name_only"]


@dataclass
class _KboInfo:
    kbo: str
    name: str
    name_norm: str
    postal_code: str
    city: str


_SQL_PLACEHOLDER_NAMES = (
    "SELECT kbo_number, value->>'text' AS name FROM companies_current "
    "WHERE field = 'name' AND kbo_number LIKE '9%'"
)
_SQL_PLACEHOLDER_ADDRS = (
    "SELECT kbo_number, value->>'postal_code' AS postal_code, "
    "value->>'city' AS city FROM companies_current "
    "WHERE field = 'address' AND kbo_number LIKE '9%'"
)
_SQL_REAL_NAMES = (
    "SELECT kbo_number, value->>'text' AS name FROM companies_current "
    "WHERE field = 'name' AND kbo_number NOT LIKE '9%'"
)
_SQL_REAL_ADDRS = (
    "SELECT kbo_number, value->>'postal_code' AS postal_code, "
    "value->>'city' AS city FROM companies_current "
    "WHERE field = 'address' AND kbo_number NOT LIKE '9%'"
)


async def _gather_kbo_infos(pool: asyncpg.Pool, is_placeholder: bool) -> list[_KboInfo]:
    """Collect name, postal_code, city for placeholder (9%) or real KBOs."""
    name_rows = await pool.fetch(_SQL_PLACEHOLDER_NAMES if is_placeholder else _SQL_REAL_NAMES)
    addr_rows = await pool.fetch(_SQL_PLACEHOLDER_ADDRS if is_placeholder else _SQL_REAL_ADDRS)

    names: dict[str, str] = {r["kbo_number"]: r["name"] or "" for r in name_rows}
    addrs: dict[str, tuple[str, str]] = {}
    for r in addr_rows:
        addrs[r["kbo_number"]] = (r["postal_code"] or "", r["city"] or "")

    result: list[_KboInfo] = []
    for kbo in names:
        name = names[kbo]
        postal, city = addrs.get(kbo, ("", ""))
        result.append(
            _KboInfo(
                kbo=kbo,
                name=name,
                name_norm=_normalize_for_match(name),
                postal_code=postal.strip(),
                city=city.lower().strip(),
            )
        )
    return result


def _best_match(
    placeholder: _KboInfo,
    candidates: list[_KboInfo],
    threshold: float,
) -> ConsolidationMatch | None:
    """Three-pass matching: name+postal, name+city, name_only."""
    best_score = 0.0
    best_candidate: _KboInfo | None = None
    best_matched_on: Literal["name+postal", "name+city", "name_only"] = "name_only"

    # Pass 1: same postal code
    postal_candidates = [
        c for c in candidates if c.postal_code == placeholder.postal_code and c.postal_code
    ]
    for c in postal_candidates:
        score = fuzz.token_set_ratio(placeholder.name_norm, c.name_norm)
        if score >= threshold and score > best_score:
            best_score = score
            best_candidate = c
            best_matched_on = "name+postal"

    if best_candidate is not None:
        return ConsolidationMatch(
            placeholder_kbo=placeholder.kbo,
            real_kbo=best_candidate.kbo,
            score=best_score,
            matched_on=best_matched_on,
        )

    # Pass 2: same city (case-insensitive)
    city_candidates = [
        c for c in candidates if c.city and placeholder.city and c.city == placeholder.city
    ]
    for c in city_candidates:
        score = fuzz.token_set_ratio(placeholder.name_norm, c.name_norm)
        if score >= threshold and score > best_score:
            best_score = score
            best_candidate = c
            best_matched_on = "name+city"

    if best_candidate is not None:
        return ConsolidationMatch(
            placeholder_kbo=placeholder.kbo,
            real_kbo=best_candidate.kbo,
            score=best_score,
            matched_on=best_matched_on,
        )

    # Pass 3: name only, stricter threshold (90)
    for c in candidates:
        score = fuzz.token_set_ratio(placeholder.name_norm, c.name_norm)
        if score >= 90.0 and score > best_score:
            best_score = score
            best_candidate = c
            best_matched_on = "name_only"

    if best_candidate is not None:
        return ConsolidationMatch(
            placeholder_kbo=placeholder.kbo,
            real_kbo=best_candidate.kbo,
            score=best_score,
            matched_on=best_matched_on,
        )

    return None


async def consolidate(
    pool: asyncpg.Pool,
    *,
    name_match_threshold: float = 80.0,
) -> list[ConsolidationMatch]:
    """Match placeholder KBOs to real KBOs and re-emit observations under the real KBO.

    Placeholder observations are NOT deleted (append-only invariant). New observations
    are inserted under the real KBO with confidence * 0.9 (inference penalty).
    """
    runs_repo = RunsRepo(pool)
    obs_repo = ObservationsRepo(pool)
    run_id = await runs_repo.start_run(source="kbo_dump")  # reuse valid source name
    snapshot_at = datetime.now(tz=UTC)
    log = logger.bind(run_id=str(run_id), source="consolidation")
    log.info("consolidation_started")

    placeholders = await _gather_kbo_infos(pool, is_placeholder=True)
    reals = await _gather_kbo_infos(pool, is_placeholder=False)

    if not placeholders or not reals:
        log.info("consolidation_nothing_to_do", placeholders=len(placeholders), reals=len(reals))
        await runs_repo.finish_run(run_id, jobs_done=0)
        return []

    log.info("consolidation_matching", placeholders=len(placeholders), reals=len(reals))

    matches: list[ConsolidationMatch] = []
    for p in placeholders:
        if not p.name_norm:
            continue
        m = _best_match(p, reals, name_match_threshold)
        if m:
            matches.append(m)
            log.debug(
                "consolidation_match",
                placeholder=p.kbo,
                real=m.real_kbo,
                score=m.score,
                matched_on=m.matched_on,
            )

    # Re-emit placeholder observations under real KBO.
    all_new_obs: list[Observation] = []
    for match in matches:
        rows = await pool.fetch(
            "SELECT kbo_number, field, value, raw_value, source, source_url, "
            "observed_at, confidence FROM observations WHERE kbo_number = $1",
            match.placeholder_kbo,
        )
        for row in rows:
            try:
                new_obs = Observation(
                    kbo_number=match.real_kbo,
                    field=row["field"],
                    value=dict(row["value"]),
                    raw_value=row["raw_value"],
                    source=row["source"],
                    source_url=row["source_url"],
                    observed_at=row["observed_at"] or snapshot_at,
                    confidence=round(float(row["confidence"]) * 0.9, 4),
                    run_id=run_id,
                )
                all_new_obs.append(new_obs)
            except (ValueError, Exception) as exc:
                log.warning(
                    "consolidation_obs_skip",
                    placeholder=match.placeholder_kbo,
                    real=match.real_kbo,
                    error=str(exc),
                )

    if all_new_obs:
        await obs_repo.insert_many(all_new_obs)

    await runs_repo.finish_run(run_id, jobs_done=len(matches))
    log.info(
        "consolidation_done",
        matches=len(matches),
        observations_re_emitted=len(all_new_obs),
    )
    return matches
