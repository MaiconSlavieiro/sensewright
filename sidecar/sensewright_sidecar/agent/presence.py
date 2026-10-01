"""PresencePolicy: who is "at home" and how much agency they get (v0.4 P3).

The player's household is ``full`` (idle impulses + speech). Everyone else is a
visitor: ``reactive`` by default (they react to salient events and may join an
existing native conversation, but get no idle impulse and do not comment on the
household's home), ``full`` or ``off`` per config.

It also provides the per-Sim context line ("your home" vs "visiting") and a
real-distance ``nearby`` helper so a stranger never receives household names.
"""

from __future__ import annotations

import logging
from typing import Any

from .. import content_i18n

logger = logging.getLogger(__name__)

TIER_FULL = "full"
TIER_REACTIVE = "reactive"
TIER_OFF = "off"

_VISITOR_TIERS = (TIER_REACTIVE, TIER_FULL, TIER_OFF)

_FAMILIAR_TYPES = ("family", "friend", "romantic", "spouse", "partner")


def location_xy(sim: dict[str, Any] | None) -> tuple[float, float] | None:
    """Parse a pulse ``location`` ("x,y") into floats, or None when absent."""
    location = (sim or {}).get("location")
    if not isinstance(location, str):
        return None
    parts = location.split(",")
    if len(parts) != 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except (TypeError, ValueError):
        return None


def distance_between(a: dict[str, Any] | None, b: dict[str, Any] | None) -> float | None:
    """Lot-space distance between two pulse Sims, or None when unknown."""
    pa, pb = location_xy(a), location_xy(b)
    if pa is None or pb is None:
        return None
    return ((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2) ** 0.5


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class PresencePolicy:
    """Visitor tiers, per-Sim context and real-distance proximity."""

    def __init__(self, settings: Any = None) -> None:
        self.visitor = TIER_REACTIVE
        self.familiar_friendship = 20.0
        if settings is not None:
            self.configure(settings)

    def configure(self, settings: Any) -> None:
        try:
            presence = getattr(getattr(settings, "agents", None), "presence", None)
        except Exception:
            presence = None
        if presence is None:
            return
        value = str(getattr(presence, "visitor", TIER_REACTIVE) or "").strip().lower()
        self.visitor = value if value in _VISITOR_TIERS else TIER_REACTIVE
        self.familiar_friendship = float(
            getattr(presence, "familiar_friendship", 20.0) or 0.0
        )

    @staticmethod
    def _household_of(sim: dict[str, Any] | None) -> Any:
        return (sim or {}).get("household_id")

    def is_household(
        self,
        sim: dict[str, Any] | None,
        *,
        player_household_id: Any = None,
        is_player: bool = False,
    ) -> bool:
        """True when ``sim`` belongs to the player's own household."""
        if is_player or (sim or {}).get("is_player"):
            return True
        household = self._household_of(sim)
        if household is None or player_household_id is None:
            return False
        return household == player_household_id

    def tier(
        self,
        sim: dict[str, Any] | None,
        *,
        player_household_id: Any = None,
        is_player: bool = False,
    ) -> str:
        """Return ``full``/``reactive``/``off`` for one pulse Sim."""
        if self.is_household(sim, player_household_id=player_household_id, is_player=is_player):
            return TIER_FULL
        if self.visitor == TIER_OFF:
            return TIER_OFF
        if self.visitor == TIER_FULL:
            return TIER_FULL
        return TIER_REACTIVE

    def allows_idle(
        self,
        sim: dict[str, Any] | None,
        *,
        player_household_id: Any = None,
        is_player: bool = False,
    ) -> bool:
        """Only ``full`` presence Sims get idle impulses."""
        return self.tier(
            sim, player_household_id=player_household_id, is_player=is_player
        ) == TIER_FULL

    def allows_speech(
        self,
        sim: dict[str, Any] | None,
        *,
        player_household_id: Any = None,
        is_player: bool = False,
    ) -> bool:
        """``full`` and ``reactive`` Sims may speak (reactive only with a target)."""
        return self.tier(
            sim, player_household_id=player_household_id, is_player=is_player
        ) != TIER_OFF

    def is_familiar(self, sim: dict[str, Any] | None) -> bool:
        """True for household members and known friends/relatives."""
        relationships = (sim or {}).get("relationships")
        if not isinstance(relationships, list):
            return False
        for rel in relationships:
            if not isinstance(rel, dict):
                continue
            rel_type = str(rel.get("type") or rel.get("track") or "").lower()
            if rel_type in _FAMILIAR_TYPES:
                return True
            for key in ("friendship", "level"):
                value = _as_float(rel.get(key))
                if value is not None and value >= self.familiar_friendship:
                    return True
        return False

    def context_line(
        self,
        sim: dict[str, Any] | None,
        *,
        lang: str,
        player_household_id: Any = None,
        is_player: bool = False,
        household_name: str = "",
    ) -> str:
        """A short "your home" vs "visiting" line for a prompt."""
        sim = sim or {}
        name = str(sim.get("full_name") or sim.get("name") or f"Sim {sim.get('sim_id', 0)}")
        if self.is_household(
            sim, player_household_id=player_household_id, is_player=is_player
        ):
            household = household_name or str(sim.get("household_name") or "")
            if household:
                return content_i18n.t(
                    lang, "presence.context.home", name=name, household=household
                )
            return content_i18n.t(lang, "presence.context.unknown", name=name)
        if sim.get("location"):
            return content_i18n.t(lang, "presence.context.visiting", name=name)
        return content_i18n.t(lang, "presence.context.unknown", name=name)

    @staticmethod
    def nearby(
        sim: dict[str, Any] | None,
        sims: list[dict[str, Any]] | None,
        *,
        radius: float | None = None,
    ) -> list[dict[str, Any]]:
        """Return the Sims within ``radius`` of ``sim`` (unknown distance included)."""
        center = sim or {}
        out: list[dict[str, Any]] = []
        for other in sims or []:
            if other is center:
                continue
            if int(other.get("sim_id") or 0) == int(center.get("sim_id") or 0):
                continue
            distance = distance_between(center, other)
            if radius is not None and distance is not None and distance > radius:
                continue
            out.append(other)
        return out

    def snapshot(self) -> dict[str, Any]:
        return {
            "visitor": self.visitor,
            "familiar_friendship": self.familiar_friendship,
        }
