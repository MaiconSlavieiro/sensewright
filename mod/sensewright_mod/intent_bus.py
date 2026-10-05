# Sensewright v2 — Intent Bus
# Python 3.7 compatible

import time
import threading
from collections import deque

from sensewright_mod.config import (
    get_intent_default_ttl, get_intent_max_retries
)
from sensewright_mod.debug_log import log_error, log_exception, log_warn, worker_log_warn


# Intent kinds
INTENT_KINDS = frozenset([
    'speak', 'approach', 'set_mood', 'bias_interaction',
    'prefer_target', 'set_goal', 'remember', 'forget', 'command', 'spawn_npc'
])

# Expiration types
EXPIRES_ON_TYPES = frozenset(['ttl', 'next_sleep', 'zone_transition'])

# Physical/social intent kinds that have short TTL
PHYSICAL_SOCIAL_KINDS = frozenset(['speak', 'approach', 'command', 'spawn_npc'])

# Cognitive intent kinds that expire on sleep
COGNITIVE_KINDS = frozenset(['bias_interaction', 'prefer_target', 'set_goal', 'remember', 'forget'])


class Intent(object):
    """Normalized intent shape."""

    __slots__ = (
        'id', 'trace_id', 'sim_id', 'kind', 'target_sim_id',
        'params', 'thought', 'narration', 'delay_sim_minutes',
        'ttl_sim_minutes', 'expires_on', 'priority', 'source',
        'retry_count', 'max_retries', '_created_tick', '_dispatched'
    )

    def __init__(self, id, trace_id, sim_id, kind, target_sim_id=None,
                 params=None, thought=None, narration=None,
                 delay_sim_minutes=0.0, ttl_sim_minutes=None,
                 expires_on=None, priority=0, source='agent',
                 retry_count=0, max_retries=None):
        self.id = id
        self.trace_id = trace_id
        self.sim_id = sim_id
        self.kind = kind
        self.target_sim_id = target_sim_id
        self.params = params or {}
        self.thought = thought
        self.narration = narration
        self.delay_sim_minutes = float(delay_sim_minutes)
        self.ttl_sim_minutes = float(ttl_sim_minutes) if ttl_sim_minutes is not None else get_intent_default_ttl()
        self.expires_on = expires_on or self._default_expires_on(kind)
        self.priority = int(priority)
        self.source = source
        self.retry_count = int(retry_count)
        self.max_retries = int(max_retries) if max_retries is not None else get_intent_max_retries()
        self._created_tick = 0
        self._dispatched = False

    def _default_expires_on(self, kind):
        if kind in PHYSICAL_SOCIAL_KINDS:
            return 'ttl'
        elif kind in COGNITIVE_KINDS:
            return 'next_sleep'
        return 'ttl'

    def to_dict(self):
        return {
            'id': self.id,
            'trace_id': self.trace_id,
            'sim_id': self.sim_id,
            'kind': self.kind,
            'target_sim_id': self.target_sim_id,
            'params': self.params,
            'thought': self.thought,
            'narration': self.narration,
            'delay_sim_minutes': self.delay_sim_minutes,
            'ttl_sim_minutes': self.ttl_sim_minutes,
            'expires_on': self.expires_on,
            'priority': self.priority,
            'source': self.source,
            'retry_count': self.retry_count,
            'max_retries': self.max_retries
        }

    @classmethod
    def from_dict(cls, data):
        intent = cls(
            id=data.get('id', ''),
            trace_id=data.get('trace_id', ''),
            sim_id=data.get('sim_id', 0),
            kind=data.get('kind', ''),
            target_sim_id=data.get('target_sim_id'),
            params=data.get('params', {}),
            thought=data.get('thought'),
            narration=data.get('narration'),
            delay_sim_minutes=data.get('delay_sim_minutes', 0.0),
            ttl_sim_minutes=data.get('ttl_sim_minutes'),
            expires_on=data.get('expires_on'),
            priority=data.get('priority', 0),
            source=data.get('source', 'agent'),
            retry_count=data.get('retry_count', 0),
            max_retries=data.get('max_retries')
        )
        intent._created_tick = data.get('_created_tick', 0)
        intent._dispatched = data.get('_dispatched', False)
        return intent


class IntentBus(object):
    """Manages inbound intents: delay, dispatch, expiration, pause handling."""

    def __init__(self):
        self._intents = []  # List of Intent objects
        self._lock = threading.RLock()
        self._last_tick = 0
        self._paused = False
        self._next_sleep_tick = {}  # sim_id -> tick when they next sleep
        self._last_expiry_log_at = 0.0
        #: Closed-loop telemetry (R1): outcomes awaiting the next autonomy pulse.
        #: Bounded so a burst can never grow unbounded in RAM.
        self._outcomes = deque(maxlen=1024)

    def add_intent(self, intent_data):
        """Add an intent from sidecar response."""
        with self._lock:
            try:
                if isinstance(intent_data, dict):
                    intent = Intent.from_dict(intent_data)
                else:
                    intent = intent_data

                # Set creation tick
                intent._created_tick = self._get_current_tick()

                # Cap physical/social intents to 15 sim-minutes TTL
                if intent.kind in PHYSICAL_SOCIAL_KINDS and intent.ttl_sim_minutes > 15.0:
                    intent.ttl_sim_minutes = 15.0

                self._intents.append(intent)
                return True
            except Exception as e:
                log_exception('Failed to add intent: {}'.format(e))
                return False

    def add_intents(self, intents_list):
        """Add multiple intents."""
        for intent_data in intents_list:
            self.add_intent(intent_data)

    def _get_current_tick(self):
        """Get current world sim tick."""
        try:
            from sensewright_mod.state_collector import _get_world_sim_tick
            return _get_world_sim_tick()
        except Exception:
            return 0

    def _get_clock_speed(self):
        """Get current clock speed."""
        try:
            from sensewright_mod.state_collector import _get_clock_speed
            return _get_clock_speed()
        except Exception:
            return 1

    def update(self):
        """Call from GAME_TICK to process delays, dispatch, and expire intents."""
        with self._lock:
            current_tick = self._get_current_tick()
            clock_speed = self._get_clock_speed()

            # Handle pause
            if clock_speed == 0:
                if not self._paused:
                    self._paused = True
                self._last_tick = current_tick
                return []  # No dispatch when paused

            if self._paused:
                self._paused = False

            # Calculate sim minutes elapsed since last tick
            if self._last_tick > 0:
                tick_diff = current_tick - self._last_tick
                # 1 sim minute = 1000 ticks (approximate)
                sim_minutes_elapsed = tick_diff / 1000.0
            else:
                sim_minutes_elapsed = 0.0

            self._last_tick = current_tick

            ready_intents = []
            remaining_intents = []
            expired_intents = []

            for intent in self._intents:
                # Check expiration
                if self._is_expired(intent, current_tick):
                    expired_intents.append(intent)
                    # R1: report the silent loss back to the sidecar so it can
                    # adapt (e.g. stop re-issuing intents that never run).
                    self._outcomes.append({
                        'intent_id': str(intent.id),
                        'status': 'expired',
                        'reason': 'expired_on_{}'.format(intent.expires_on),
                        'sim_tick': int(current_tick),
                        'action_id': None,
                    })
                    continue  # Drop expired intent

                # Update delay
                if intent.delay_sim_minutes > 0:
                    intent.delay_sim_minutes -= sim_minutes_elapsed
                    if intent.delay_sim_minutes <= 0:
                        intent.delay_sim_minutes = 0.0

                # Check if ready to dispatch
                if intent.delay_sim_minutes <= 0 and not intent._dispatched:
                    intent._dispatched = True
                    ready_intents.append(intent)
                else:
                    remaining_intents.append(intent)

            self._intents = remaining_intents

            # Diagnostic heartbeat: intents that expired are a *silent loss* and
            # previously left zero trace, so surface them (throttled).
            if expired_intents:
                self._log_expired(expired_intents)

            return ready_intents

    def _log_expired(self, expired_intents):
        """Log a throttled summary of expired intents (previously silent)."""
        now = time.monotonic()
        if now - self._last_expiry_log_at < 30.0:
            return
        self._last_expiry_log_at = now
        by_kind = {}
        by_sim = {}
        for intent in expired_intents:
            by_kind[intent.kind] = by_kind.get(intent.kind, 0) + 1
            if intent.sim_id:
                by_sim[intent.sim_id] = by_sim.get(intent.sim_id, 0) + 1
        worker_log_warn('intent bus: expired {} intents kinds={} sims={} (ttl/sleep/zone loss)'.format(
            len(expired_intents), by_kind, by_sim))

    def _is_expired(self, intent, current_tick):
        """Check if intent has expired."""
        # TTL expiration
        if intent.expires_on == 'ttl':
            created_tick = intent._created_tick
            ttl_ticks = intent.ttl_sim_minutes * 1000.0  # Convert sim minutes to ticks
            if current_tick - created_tick > ttl_ticks:
                return True

        # Zone transition expiration
        if intent.expires_on == 'zone_transition':
            # This is checked externally via clear_zone_intents()
            pass

        # Next sleep expiration
        if intent.expires_on == 'next_sleep':
            # Check if sim has slept since intent creation
            next_sleep = self._next_sleep_tick.get(intent.sim_id, 0)
            if next_sleep > 0 and next_sleep > intent._created_tick:
                return True

        return False

    def clear_zone_intents(self):
        """Clear all intents that expire on zone transition."""
        with self._lock:
            self._intents = [
                intent for intent in self._intents
                if intent.expires_on != 'zone_transition'
            ]

    def mark_sleep(self, sim_id):
        """Mark that a sim has slept (for next_sleep expiration)."""
        with self._lock:
            current_tick = self._get_current_tick()
            self._next_sleep_tick[sim_id] = current_tick

    def get_pending_intents(self, sim_id=None):
        """Get all pending (not yet dispatched) intents, optionally filtered by sim."""
        with self._lock:
            if sim_id is None:
                return [i for i in self._intents if not i._dispatched]
            return [i for i in self._intents if not i._dispatched and i.sim_id == sim_id]

    def get_dispatched_intents(self, sim_id=None):
        """Get all dispatched but not yet executed intents."""
        with self._lock:
            if sim_id is None:
                return [i for i in self._intents if i._dispatched]
            return [i for i in self._intents if i._dispatched and i.sim_id == sim_id]

    def retry_intent(self, intent_id):
        """Increment retry count for an intent."""
        with self._lock:
            for intent in self._intents:
                if intent.id == intent_id:
                    intent.retry_count += 1
                    intent._dispatched = False  # Re-queue for dispatch
                    intent.delay_sim_minutes = 1.0  # Small delay before retry
                    return True
            return False

    def remove_intent(self, intent_id):
        """Remove an intent by ID."""
        with self._lock:
            self._intents = [i for i in self._intents if i.id != intent_id]

    def clear_all(self):
        """Clear all intents."""
        with self._lock:
            self._intents.clear()
            self._next_sleep_tick.clear()

    def record_outcome(self, intent_id, status, reason='', sim_tick=None, action_id=None):
        """Record an intent's execution outcome (R1) for the next autonomy pulse.

        ``status`` is one of ``applied|failed|expired|preempted_by_player``.
        The sidecar uses these to learn whether an intent actually ran (it can no
        longer treat fire-and-forget as success).
        """
        if not intent_id:
            return
        if status not in ('applied', 'failed', 'expired', 'preempted_by_player'):
            status = 'failed'
        if sim_tick is None:
            sim_tick = self._get_current_tick()
        with self._lock:
            self._outcomes.append({
                'intent_id': str(intent_id),
                'status': status,
                'reason': str(reason or ''),
                'sim_tick': int(sim_tick or 0),
                'action_id': str(action_id) if action_id is not None else None,
            })

    def drain_outcomes(self):
        """Return and clear all pending outcomes (called from the autonomy pulse)."""
        with self._lock:
            outcomes = list(self._outcomes)
            self._outcomes.clear()
            return outcomes

    def get_stats(self):
        """Get bus statistics."""
        with self._lock:
            return {
                'total': len(self._intents),
                'pending': len([i for i in self._intents if not i._dispatched]),
                'dispatched': len([i for i in self._intents if i._dispatched]),
                'paused': self._paused
            }


# Global instance
_intent_bus = None


def get_intent_bus():
    global _intent_bus
    if _intent_bus is None:
        _intent_bus = IntentBus()
    return _intent_bus


def create_intent(sim_id, kind, target_sim_id=None, params=None, thought=None,
                  narration=None, delay_sim_minutes=0.0, ttl_sim_minutes=None,
                  expires_on=None, priority=0, source='agent', trace_id=None):
    """Factory function to create a new intent."""
    from sensewright_mod.http_client import generate_trace_id
    if trace_id is None:
        trace_id = generate_trace_id()

    import uuid
    intent_id = uuid.uuid4().hex[:16]

    return Intent(
        id=intent_id,
        trace_id=trace_id,
        sim_id=sim_id,
        kind=kind,
        target_sim_id=target_sim_id,
        params=params,
        thought=thought,
        narration=narration,
        delay_sim_minutes=delay_sim_minutes,
        ttl_sim_minutes=ttl_sim_minutes,
        expires_on=expires_on,
        priority=priority,
        source=source
    )