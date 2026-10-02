# Sensewright v2 — Catalyst Conversation Tracker (2.9)
# Python 3.7 compatible
#
# The God Director's arc advances when a catalyst beat interaction ends. The
# engine has no discrete "conversation ended" event, so this tracker compares the
# conversing set across autonomy pulses and reports the end of a beat to
# /v1/god/beat-ended, together with a best-effort agent decision.

from sensewright_mod.debug_log import log_debug, log_exception
from sensewright_mod.http_client import post_async, generate_trace_id
from sensewright_mod.state_collector import get_current_game_state
from sensewright_mod.i18n import get_current_language


_CONVERSATION_MARKERS = ('social', 'talk', 'chat', 'convers')

#: sim_id -> last delta observed while conversing.
_conversing = {}


def _is_conversing(activity):
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
        if _is_conversing(sim.get('activity')):
            current[int(sim.get('sim_id', 0))] = sim

    ended = [(sim_id, _conversing[sim_id]) for sim_id in _conversing if sim_id not in current]
    _conversing = current

    for sim_id, sim in ended:
        _report(sim_id, sim)
    return [sim_id for sim_id, _sim in ended]


def _report(sim_id, sim):
    try:
        state = get_current_game_state()
        post_async('/god/beat-ended', {
            'trace_id': generate_trace_id(),
            'sim_id': sim_id,
            'agent_sim_id': sim_id,
            'decision': _infer_decision(sim),
            'player_id': 'player_1',
            'save_id': state['save_id'],
            'world_sim_tick': state['world_sim_tick'],
            'lang': get_current_language(),
        })
        log_debug('catalyst_tracker: reported beat-ended for sim={}'.format(sim_id))
    except Exception as e:
        log_exception('catalyst_tracker: report failed: {}'.format(e))
