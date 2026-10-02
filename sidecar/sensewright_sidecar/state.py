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
from typing import Any, Dict, List, Optional

from .config import get_config
from .llm import get_scheduler
from .panel_store import PanelStore
from .save_vault import SaveVault

#: Sidecar data directory: <sidecar>/data (saves/, locales/, logs/).
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class AppState:
    """Thread-safe holder for cross-request, cross-session state."""

    def __init__(self) -> None:
        self.config = get_config()
        self.data_dir = _DATA_DIR
        self.save_vault = SaveVault(self.data_dir)
        self.scheduler = get_scheduler()
        self.panel = PanelStore(self.data_dir)
        self._lock = threading.RLock()

        #: Persistent-ish RAM structures (cleared on session-start).
        self.game_pid: Optional[int] = None
        self.active_save_id: Optional[int] = None
        self.current_lang: str = ""
        self.census: Dict[int, Dict[str, Any]] = {}
        self.relationships: Dict[str, Dict[str, Any]] = {}

        # IntentBus: intents produced this tick, returned to the mod on pull.
        self._pending_intents: List[Dict[str, Any]] = []

        # Short-term chat buffers: sim_id -> {"turns": [...], "last_tick": int}
        self.chat_buffers: Dict[int, Dict[str, Any]] = {}

        # Conversation sessions: session_id -> dict
        self.conversations: Dict[str, Dict[str, Any]] = {}

        # Seat manager state.
        self.seats: Dict[int, Dict[str, Any]] = {}

        # God Director state.
        self.active_arc: Optional[Dict[str, Any]] = None
        self.catalyst_leases: Dict[int, Dict[str, Any]] = {}

        # Player-activity lock: sim_id -> absolute wall-clock expiry.
        self.player_lock_until: Dict[int, float] = {}

        # Rumor epidemiology lives in the neighborhoods table, but the hot set is
        # cached here keyed by save_id.
        self.rumors_cache: Dict[str, List[Dict[str, Any]]] = {}

    # ── store access ─────────────────────────────────────────────────────
    def working_store(self):
        return self.save_vault.working_store()

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

    def drain_intents(self) -> List[Dict[str, Any]]:
        with self._lock:
            intents = self._pending_intents
            self._pending_intents = []
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
            self._pending_intents = []
            self.chat_buffers = {}
            self.conversations = {}
            self.seats = {}
            self.active_arc = None
            self.catalyst_leases = {}
            self.player_lock_until = {}
            self.census = {}
            self.relationships = {}
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
    _state_singleton = None
