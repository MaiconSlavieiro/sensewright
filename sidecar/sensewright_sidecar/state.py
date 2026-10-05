"""Central application state for the Sensewright sidecar.

Holds the process-wide singletons (config, SaveVault, LLMScheduler) plus the
in-memory transient state that must never leak across save slots: the IntentBus
queue, short-term chat buffers, conversation sessions, seat manager, control
leases and the player-activity lock. Persistent data lives in the SQLite Shadow
DB (see :mod:`sensewright_sidecar.memory.sqlite_store`).
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .config import get_config
from .llm import get_scheduler
from .observability.logging import get_logger
from .panel_store import PanelStore
from .save_vault import SaveVault

logger = get_logger("state")

#: Sidecar data directory: <sidecar>/data (saves/, locales/, logs/).
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class AppState:
    """Thread-safe holder for cross-request, cross-session state."""

    def __init__(self) -> None:
        self.config = get_config()
        self.data_dir = _DATA_DIR
        self.save_vault = SaveVault(
            self.data_dir,
            rewind_tolerance_ticks=int(self.config.gameplay("rewind_tolerance_ticks", 3000)),
        )
        self.scheduler = get_scheduler()
        self.panel = PanelStore(self.data_dir)
        self._lock = threading.RLock()

        #: Persistent-ish RAM structures (cleared on session-start).
        self.game_pid: Optional[int] = None
        self.active_save_id: Optional[int] = None
        #: Monotonic session token. Incremented on every session reset and on a
        #: real rewind. Async workers capture it and drop results from obsolete
        #: sessions so a job can never write into a newer session's store (2.4).
        self.session_epoch: int = 0
        #: Highest autonomy tick already ingested. Ticks <= this are duplicates
        #: (re-delivered after a rewind or a retried request) and are ignored (2.3).
        self.last_processed_tick: int = 0
        #: True while a god.plan job is scheduled but has not landed yet. Closes
        #: the check-then-act TOCTOU that used to create two active arcs (3.1).
        self.arc_planning: bool = False
        self.current_lang: str = ""
        self.census: Dict[int, Dict[str, Any]] = {}
        self.relationships: Dict[str, Dict[str, Any]] = {}
        #: Zone/venue context reported by the Mod (venue_type, is_residential).
        #: Used to ground social/chat prompts in the setting.
        self.zone_context: Dict[str, Any] = {}
        #: Expansion packs installed in the running game (A10 / EP guards).
        self.installed_packs: set = set()
        #: Well-known compatible mods detected by the Mod scan (2.7 / FC5).
        self.detected_mods: List[str] = []

        # IntentBus: intents produced this tick, returned to the mod on pull.
        self._pending_intents: List[Dict[str, Any]] = []

        # Short-term chat buffers: sim_id -> {"turns": [...], "last_tick": int}
        self.chat_buffers: Dict[int, Dict[str, Any]] = {}

        # Conversation sessions: session_id -> dict
        self.conversations: Dict[str, Dict[str, Any]] = {}

        #: Last "Previously on…" recap produced by ops.recap (P32).
        self.recap: Dict[str, Any] = {}
        #: Non-player sims seen across autonomy pulses (world.npc.backstory, P22).
        self.townie_sightings: Dict[int, int] = {}
        #: Sims for which sim.background.expand already ran (P13).
        self.background_expanded: set = set()
        #: Sims for which a ``sim.profile`` generation was already scheduled this
        #: session (BUG-11). Bounds the chat-triggered fallback to one attempt per
        #: sim per session, so a persistent template (LLM down) cannot re-spawn a
        #: profile job on every chat message.
        self.profile_generation_attempted: set = set()
        #: Per-sim tick of the last relationship review (P29).
        self.last_relationship_review_tick: Dict[int, int] = {}
        #: Panic switch (FC4 / 4.8): when True autonomy dispatch is suspended.
        self.paused: bool = False
        #: Deep-window signal (F16): True while the player is idle/paused, so
        #: long-horizon "deep" work may be exploited (S-M03). Set from
        #: /v1/config/player-activity and surfaced in /v1/status.
        self.deep_window_open: bool = False

        # Seat manager state.
        self.seats: Dict[int, Dict[str, Any]] = {}

        # God Director state.
        self.active_arc: Optional[Dict[str, Any]] = None
        self.catalyst_leases: Dict[int, Dict[str, Any]] = {}
        #: Per-sim tick of the last scheduled idle impulse (4.1 throttle).
        self.last_impulse_tick: Dict[int, int] = {}

        # Sleep-cycle edge detection + per-sim daily cadence (F07 / P07-P09).
        self.sleep_state: Dict[int, bool] = {}
        self.salient_since_sleep: Dict[int, bool] = {}
        self.last_reflect_tick: Dict[int, int] = {}
        self.last_psyche_decay_tick: Dict[int, int] = {}
        #: Last in-game day for which the end-of-day pipeline ran (P23/P10).
        self.last_day_tick: int = 0

        # Speech pacing: sim_id -> wall-clock timestamps of recent lines (F11).
        self.speak_history: Dict[int, List[float]] = {}

        # Player-activity lock: sim_id -> absolute wall-clock expiry.
        self.player_lock_until: Dict[int, float] = {}

        # Rumor epidemiology lives in the neighborhoods table, but the hot set is
        # cached here keyed by save_id.
        self.rumors_cache: Dict[str, List[Dict[str, Any]]] = {}

        #: Cumulative runtime counters exposed by ``/v1/status`` (5.1). Never
        #: cleared across sessions so operators can spot trends.
        self.metrics: Dict[str, int] = {}

    # ── metrics (5.1) ────────────────────────────────────────────────────
    def incr(self, key: str, amount: int = 1) -> None:
        with self._lock:
            self.metrics[key] = self.metrics.get(key, 0) + int(amount)

    def metrics_snapshot(self) -> Dict[str, int]:
        with self._lock:
            return dict(self.metrics)

    # ── store access ─────────────────────────────────────────────────────
    def working_store(self):
        return self.save_vault.working_store()

    # ── session epoch & tick idempotency (2.2-2.4) ───────────────────────
    def bump_epoch(self) -> int:
        """Invalidate every in-flight async callback from the prior session."""
        with self._lock:
            self.session_epoch += 1
            return self.session_epoch

    def accept_tick(self, tick: int) -> bool:
        """Record ``tick`` if it is newer than the last ingested autonomy tick.

        Returns ``False`` for a duplicate/stale tick so the caller can skip the
        heavy ingestion path without dropping already-ready intents.
        """
        with self._lock:
            tick = int(tick)
            if tick <= self.last_processed_tick:
                return False
            self.last_processed_tick = tick
            return True

    def set_processed_tick(self, tick: int) -> None:
        with self._lock:
            self.last_processed_tick = int(tick)

    def guard_callback(self, name: str, callback: Callable[[Any], None]) -> Callable[[Any], None]:
        """Wrap a background callback so it is dropped when its epoch is stale.

        The epoch is captured at scheduling time; if a session reset or rewind
        happened before the job completed, the callback must not touch the new
        session's store (2.4).
        """
        epoch = self.session_epoch

        def _guarded(result: Any) -> None:
            if epoch != self.session_epoch:
                self.incr("stale_epoch_dropped")
                logger.info("stale_epoch_dropped callback=%s epoch=%s current=%s",
                            name, epoch, self.session_epoch)
                return
            callback(result)

        return _guarded

    # ── god single-flight (3.1) ──────────────────────────────────────────
    def try_begin_arc_plan(self) -> bool:
        """Atomically claim the single in-flight god.plan slot."""
        with self._lock:
            if self.arc_planning:
                return False
            self.arc_planning = True
            return True

    def end_arc_plan(self) -> None:
        with self._lock:
            self.arc_planning = False

    # ── census (thread-safe accessors) ───────────────────────────────────
    def update_census(self, sims: Dict[int, Dict[str, Any]]) -> None:
        """Replace census entries for the given sim ids (thread-safe)."""
        with self._lock:
            for sim_id, sim in sims.items():
                self.census[int(sim_id)] = sim

    def merge_census_delta(self, delta: List[Dict[str, Any]]) -> None:
        """Merge volatile delta fields into the census (thread-safe)."""
        with self._lock:
            for sim in delta:
                if not isinstance(sim, dict):
                    continue
                sim_id = int(sim.get("sim_id", 0))
                if not sim_id:
                    continue
                entry = self.census.setdefault(sim_id, {"sim_id": sim_id})
                for key, value in sim.items():
                    if value is not None:
                        entry[key] = value

    def get_census(self, sim_id: int) -> Dict[str, Any]:
        with self._lock:
            return dict(self.census.get(int(sim_id), {}))

    def census_items(self) -> List[tuple]:
        with self._lock:
            return [(sid, dict(sim)) for sid, sim in self.census.items()]

    def set_seats(self, seats: Dict[int, Dict[str, Any]]) -> None:
        with self._lock:
            self.seats = seats

    def get_seats(self) -> Dict[int, Dict[str, Any]]:
        with self._lock:
            return dict(self.seats)

    # ── IntentBus ────────────────────────────────────────────────────────
    def enqueue_intents(self, intents: List[Dict[str, Any]]) -> None:
        with self._lock:
            self._pending_intents.extend(intents)
            self.metrics["intents_emitted"] = self.metrics.get("intents_emitted", 0) + len(intents)

    def drain_intents(self) -> List[Dict[str, Any]]:
        with self._lock:
            intents = self._pending_intents
            self._pending_intents = []
            self.metrics["intents_drained"] = self.metrics.get("intents_drained", 0) + len(intents)
            return intents

    # ── chat buffers ─────────────────────────────────────────────────────
    def chat_turns(self, sim_id: int) -> List[Dict[str, str]]:
        return self.chat_buffers.get(int(sim_id), {}).get("turns", [])

    def append_chat_turn(self, sim_id: int, role: str, content: str, tick: int) -> None:
        with self._lock:
            sim_id = int(sim_id)
            buffer = self.chat_buffers.setdefault(sim_id, {"turns": [], "last_tick": 0})
            turns = buffer["turns"]
            turns.append({"role": role, "content": content})
            max_turns = int(self.config.gameplay("short_term_buffer_turns", 8))
            if len(turns) > max_turns:
                del turns[: len(turns) - max_turns]
            buffer["last_tick"] = int(tick)

    def chat_last_tick(self, sim_id: int) -> int:
        return int(self.chat_buffers.get(int(sim_id), {}).get("last_tick", 0))

    def clear_chat_buffer(self, sim_id: int) -> None:
        with self._lock:
            self.chat_buffers.pop(int(sim_id), None)

    # ── lifecycle reset ──────────────────────────────────────────────────
    def reset_ram(self) -> None:
        """Clear all transient RAM buffers (REQ-MEM-01)."""
        with self._lock:
            self.session_epoch += 1
            self.last_processed_tick = 0
            self.arc_planning = False
            self.metrics["session_resets"] = self.metrics.get("session_resets", 0) + 1
            self._pending_intents = []
            self.chat_buffers = {}
            self.conversations = {}
            self.recap = {}
            self.townie_sightings = {}
            self.background_expanded = set()
            self.profile_generation_attempted = set()
            self.last_relationship_review_tick = {}
            self.paused = False
            self.seats = {}
            self.active_arc = None
            self.catalyst_leases = {}
            self.last_impulse_tick = {}
            self.sleep_state = {}
            self.salient_since_sleep = {}
            self.last_reflect_tick = {}
            self.last_psyche_decay_tick = {}
            self.last_day_tick = 0
            self.speak_history = {}
            self.player_lock_until = {}
            self.census = {}
            self.relationships = {}
            self.zone_context = {}
            self.installed_packs = set()
            self.detected_mods = []
            self.rumors_cache = {}


_state_singleton: Optional[AppState] = None
_state_lock = threading.Lock()


def get_state() -> AppState:
    global _state_singleton
    if _state_singleton is None:
        with _state_lock:
            if _state_singleton is None:
                _state_singleton = AppState()
    return _state_singleton


def reset_state() -> None:
    global _state_singleton
    # Close the active store before dropping the singleton. Async workers (the
    # realtime pool) may still hold closures referencing this AppState, so
    # without an explicit close the working.db handle can outlive the reset and
    # keep the file locked (tests share the on-disk saves dir).
    if _state_singleton is not None:
        try:
            _state_singleton.save_vault.shutdown()
        except Exception:  # noqa: BLE001
            pass
    _state_singleton = None
