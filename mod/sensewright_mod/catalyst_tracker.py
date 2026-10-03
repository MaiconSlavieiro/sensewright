# Sensewright v2 — Catalyst Conversation Tracker (2.9)
# Python 3.7 compatible
#
# The God Director's arc advances when a catalyst beat interaction ends. The
# engine has no discrete "conversation ended" event, so this tracker compares the
# conversing set across autonomy pulses and reports the end of a beat to
# /v1/god/beat-ended, together with a best-effort agent decision.

from sensewright_mod.debug_log import log_exception, worker_log_info
from sensewright_mod.http_client import post_async, generate_trace_id
from sensewright_mod.state_collector import get_current_game_state
from sensewright_mod.i18n import get_current_language


_CONVERSATION_MARKERS = ('social', 'talk', 'chat', 'convers', 'get_to_know', 'getknow')

#: sim_id -> last delta observed while conversing.
_conversing = {}


def _is_conversing(sim):
    """True when a sim delta marks an active conversation (BUG-01).

    Prefers the reliable ``is_conversing`` flag reported by the state collector
    and only falls back to the interaction class-name markers.
    """
    if isinstance(sim, dict) and sim.get('is_conversing'):
        return True
    activity = sim.get('activity') if isinstance(sim, dict) else sim
    text = str(activity or '').lower()
    return any(marker in text for marker in _CONVERSATION_MARKERS)


def _infer_decision(sim):
    """Map the agent's mood to the accept/reject/fight decision the God reads."""
    mood = str(sim.get('mood') or '').lower()
    if any(token in mood for token in ('angry', 'furious', 'enraged')):
        return 'fight'
    if any(token in mood for token in ('sad', 'tense', 'stressed', 'uncomfortable',
                                       'embarrassed', 'bored')):
        return 'reject'
    return 'accept'


def observe(sims_delta):
    """Return the list of sim ids whose conversation just ended (and report them)."""
    global _conversing
    current = {}
    for sim in sims_delta or []:
        if not isinstance(sim, dict):
            continue
        if _is_conversing(sim):
            current[int(sim.get('sim_id', 0))] = sim

    ended = [(sim_id, _conversing[sim_id]) for sim_id in _conversing if sim_id not in current]
    _conversing = current

    # Diagnostic heartbeat: the God arc only advances when a catalyst conversation
    # ends; this was previously invisible (log_debug). Surface starts/ends so a
    # session log shows whether the tracker is actually seeing conversations.
    if ended:
        worker_log_info('catalyst tracker: {} conversation(s) ended -> beat-ended (sims={})'.format(
            len(ended), [sim_id for sim_id, _sim in ended]))
    elif current and not _catalyst_seen_logged[0]:
        _catalyst_seen_logged[0] = True
        worker_log_info('catalyst tracker: first conversation detected (sims={})'.format(
            sorted(current.keys())))

    for sim_id, sim in ended:
        _report(sim_id, sim)
    return [sim_id for sim_id, _sim in ended]


_catalyst_seen_logged = [False]


def _report(sim_id, sim):
    try:
        state = get_current_game_state()
        decision = _infer_decision(sim)
        # BUG-14: report the conversation peer so the sidecar can gate on whether
        # the conversation actually involved the leased catalyst. Without the peer
        # the sidecar cannot distinguish a catalyst scene from ambient chatter and
        # advances the arc on every random conversation.
        peer_sim_id = sim.get('social_target_sim_id', 0) if isinstance(sim, dict) else 0
        post_async('/god/beat-ended', {
            'trace_id': generate_trace_id(),
            'sim_id': sim_id,
            'agent_sim_id': sim_id,
            'target_sim_id': int(peer_sim_id or 0),
            'decision': decision,
            'player_id': 'player_1',
            'save_id': state['save_id'],
            'world_sim_tick': state['world_sim_tick'],
            'lang': get_current_language(),
        })
        worker_log_info('catalyst tracker: beat-ended posted sim={} peer={} decision={}'.format(
            sim_id, peer_sim_id, decision))
    except Exception as e:
        log_exception('catalyst_tracker: report failed: {}'.format(e))
