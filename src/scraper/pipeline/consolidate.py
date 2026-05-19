"""Placeholder-KBO → real-KBO consolidation pass using rapidfuzz name matching."""

from __future__ import annotations

import asyncio
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import structlog
from rapidfuzz import fuzz
from rapidfuzz import process as _rfprocess

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
    reals: list[_KboInfo],
    threshold: float,
    *,
    postal_index: dict[str, list[_KboInfo]] | None = None,
    city_index: dict[str, list[_KboInfo]] | None = None,
    real_name_norms: list[str] | None = None,
) -> ConsolidationMatch | None:
    """Three-pass matching: name+postal, name+city, name_only.

    When postal_index / city_index are supplied (built once before the main loop),
    Pass 1 and 2 are O(1) bucket lookups rather than O(N) list scans.
    When real_name_norms is supplied, Pass 3 uses rapidfuzz.process.extractOne
    (C inner loop, GIL released) instead of a Python for-loop (~10-50x faster).
    """
    best_score = 0.0
    best_candidate: _KboInfo | None = None
    best_matched_on: Literal["name+postal", "name+city", "name_only"] = "name_only"

    # Pass 1: same postal code
    if postal_index is not None:
        postal_candidates = (
            postal_index.get(placeholder.postal_code, []) if placeholder.postal_code else []
        )
    else:
        postal_candidates = [
            c for c in reals if c.postal_code == placeholder.postal_code and c.postal_code
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
    if city_index is not None:
        city_candidates = city_index.get(placeholder.city, []) if placeholder.city else []
    else:
        city_candidates = [
            c for c in reals if c.city and placeholder.city and c.city == placeholder.city
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
    if real_name_norms is not None:
        result = _rfprocess.extractOne(
            placeholder.name_norm,
            real_name_norms,
            scorer=fuzz.token_set_ratio,
            score_cutoff=90.0,
        )
        if result is not None:
            _matched_norm, score, idx = result
            return ConsolidationMatch(
                placeholder_kbo=placeholder.kbo,
                real_kbo=reals[idx].kbo,
                score=float(score),
                matched_on="name_only",
            )
    else:
        for c in reals:
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


def _run_matching(
    placeholders: list[_KboInfo],
    reals: list[_KboInfo],
    postal_index: dict[str, list[_KboInfo]],
    city_index: dict[str, list[_KboInfo]],
    real_name_norms: list[str],
    threshold: float,
) -> list[ConsolidationMatch]:
    """CPU-bound matching loop, suitable for asyncio.to_thread."""
    matches: list[ConsolidationMatch] = []
    for p in placeholders:
        if not p.name_norm:
            continue
        m = _best_match(
            p,
            reals,
            threshold,
            postal_index=postal_index,
            city_index=city_index,
            real_name_norms=real_name_norms,
        )
        if m:
            matches.append(m)
            logger.debug(
                "consolidation_match",
                placeholder=p.kbo,
                real=m.real_kbo,
                score=m.score,
                matched_on=m.matched_on,
            )
    return matches


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

    # Pre-build lookup indexes once — O(1) bucket access per placeholder instead of O(N) scans.
    postal_index: dict[str, list[_KboInfo]] = {}
    city_index: dict[str, list[_KboInfo]] = {}
    for r in reals:
        if r.postal_code:
            postal_index.setdefault(r.postal_code, []).append(r)
        if r.city:
            city_index.setdefault(r.city, []).append(r)
    real_name_norms = [r.name_norm for r in reals]

    # Run CPU-bound matching in a thread so the event loop stays responsive.
    matches = await asyncio.to_thread(
        _run_matching,
        placeholders,
        reals,
        postal_index,
        city_index,
        real_name_norms,
        name_match_threshold,
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
