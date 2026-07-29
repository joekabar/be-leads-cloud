"""Consolidation must be incremental, not a full re-match on every run.

Before this, every run re-matched all 11,065 placeholders (~40 min, single-threaded)
and re-emitted the observations of every match again — two consecutive runs both logged
"matches=2797, observations_re_emitted=43466", inserting the same ~43k rows twice into
an append-only table.
"""

from __future__ import annotations

from datetime import date

from scraper.pipeline.consolidate import select_placeholders_to_process


def _state(kbo: str, real: str | None, snapshot: date | None) -> dict[str, object]:
    return {"placeholder_kbo": kbo, "real_kbo": real, "snapshot_date": snapshot}


_SNAP = date(2026, 5, 14)
_NEWER = date(2026, 6, 15)


class TestSelectPlaceholdersToProcess:
    def test_unseen_placeholder_is_processed(self) -> None:
        assert select_placeholders_to_process(["9001"], [], _SNAP) == ["9001"]

    def test_matched_placeholder_is_never_reprocessed(self) -> None:
        """Its observations are already re-emitted; redoing it duplicates them."""
        state = [_state("9001", "0123456789", _SNAP)]
        assert select_placeholders_to_process(["9001"], state, _SNAP) == []

    def test_matched_placeholder_skipped_even_on_newer_snapshot(self) -> None:
        state = [_state("9001", "0123456789", _SNAP)]
        assert select_placeholders_to_process(["9001"], state, _NEWER) == []

    def test_unmatched_placeholder_not_retried_on_same_snapshot(self) -> None:
        """Nothing changed, so the expensive name-only pass would find nothing new."""
        state = [_state("9001", None, _SNAP)]
        assert select_placeholders_to_process(["9001"], state, _SNAP) == []

    def test_unmatched_placeholder_retried_on_newer_snapshot(self) -> None:
        """New real KBOs were staged, so a previous non-match may now match."""
        state = [_state("9001", None, _SNAP)]
        assert select_placeholders_to_process(["9001"], state, _NEWER) == ["9001"]

    def test_unmatched_with_null_snapshot_is_retried(self) -> None:
        state = [_state("9001", None, None)]
        assert select_placeholders_to_process(["9001"], state, _SNAP) == ["9001"]

    def test_mixed_population(self) -> None:
        state = [
            _state("9001", "0123456789", _SNAP),  # matched -> skip
            _state("9002", None, _SNAP),  # unmatched, same snapshot -> skip
            _state("9003", None, date(2026, 1, 1)),  # unmatched, older -> retry
        ]
        result = select_placeholders_to_process(["9001", "9002", "9003", "9004"], state, _SNAP)
        assert result == ["9003", "9004"]

    def test_force_reprocesses_everything(self) -> None:
        state = [_state("9001", "0123456789", _SNAP), _state("9002", None, _SNAP)]
        result = select_placeholders_to_process(["9001", "9002"], state, _SNAP, force=True)
        assert result == ["9001", "9002"]

    def test_order_is_preserved(self) -> None:
        assert select_placeholders_to_process(["9003", "9001", "9002"], [], _SNAP) == [
            "9003",
            "9001",
            "9002",
        ]

    def test_steady_state_is_empty(self) -> None:
        """The whole point: a re-run with no new placeholders does no matching work."""
        kbos = [f"900{i}" for i in range(5)]
        state = [_state(k, None, _SNAP) for k in kbos]
        assert select_placeholders_to_process(kbos, state, _SNAP) == []
