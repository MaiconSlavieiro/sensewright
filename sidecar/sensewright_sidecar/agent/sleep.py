"""Sleep-cycle transition detection (F07 / P07-P09).

The mod reports a volatile ``is_sleeping`` flag on every autonomy pulse but has
no dedicated sleep event. The sidecar owns the edge detection: it remembers the
previous flag per sim and turns false->true into ``sleep_start`` and true->false
into ``wake``. Those edges are what trigger the dream engine (``sim.dream``),
the post-dream cognition plan (``sim.cognition``), the sleep consolidation
(``sim.sleep``) and the evolution reflection (``evo.reflect``).
"""
from __future__ import annotations

from typing import Optional

SLEEP_START = "sleep_start"
WAKE = "wake"


def sleep_transition(prev: Optional[bool], current: bool) -> Optional[str]:
    """Return ``"sleep_start"``/``"wake"`` on an edge, else ``None``.

    ``prev`` is ``None`` on the first observation of a sim (no edge fires, we
    only learn the initial state).
    """
    if prev is None:
        return None
    if not prev and current:
        return SLEEP_START
    if prev and not current:
        return WAKE
    return None
