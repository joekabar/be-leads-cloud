"""Run an async job in a daemon thread and deliver its result via a queue.

Streamlit reruns top-to-bottom on every interaction, so long-running async work
(staging a ZIP, a full batch run) must live off the script thread. This is the
shared version of the pattern first used inline in ``pages/kbo_data.py``: start
the job, stash the returned queue in ``st.session_state``, and poll it with
:func:`poll_job` at the top of each rerun.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


def start_async_job(
    coro_factory: Callable[[], Coroutine[Any, Any, Any]],
) -> queue.Queue[dict[str, Any]]:
    """Run ``coro_factory()`` in a daemon thread; return a result queue.

    The queue receives exactly one message when the job finishes:
    ``{"status": "success", "result": <value>}`` or
    ``{"status": "error", "error": <str>}``.
    """
    q: queue.Queue[dict[str, Any]] = queue.Queue()

    def _target() -> None:
        try:
            result: Any = asyncio.run(coro_factory())
            q.put({"status": "success", "result": result})
        except Exception as exc:
            q.put({"status": "error", "error": str(exc)})

    threading.Thread(target=_target, daemon=True).start()
    return q


def poll_job(q: queue.Queue[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Return the finished-job message if ready, else ``None`` (non-blocking)."""
    if q is None:
        return None
    try:
        return q.get_nowait()
    except queue.Empty:
        return None
