# Sensewright v2 — Native Hooks (Hidden SimInfo, Buffs, Sentiments, Traits, Dreams)
# Python 3.7 compatible

import services
import sims4.resources
import sims4.math
from sims.sim_info import SimInfo
from sims.household import Household
from sims4communitylib.utils.sims.common_sim_utils import CommonSimUtils
from sims4communitylib.utils.sims.common_household_utils import CommonHouseholdUtils
from sims4communitylib.utils.sims.common_sim_spawn_utils import CommonSimSpawnUtils
from sims4communitylib.utils.sims.common_trait_utils import CommonTraitUtils
from sims4communitylib.utils.sims.common_buff_utils import CommonBuffUtils
from sims4communitylib.utils.sims.common_relationship_utils import CommonRelationshipUtils
from sims4communitylib.enums.common_age import CommonAge
from sims4communitylib.enums.common_gender import CommonGender
from sims4communitylib.enums.common_species import CommonSpecies

from sensewright_mod.debug_log import log_debug, log_error, log_exception, log_info, log_warn, safe_call


# Global state
_player_confidant_sim_id = 0
_player_confidant_household_id = 0

# Trait and Buff tuning IDs (populated from package at runtime)
_TRAIT_HIDDEN_NOWALKBY = 0
_BUFF_DREAM_EPIPHANY = 0
_BUFF_DREAM_SURREAL = 0
_BUFF_DREAM_OMEN = 0
_BUFF_DREAM_NIGHTMARE = 0
_BUFF_MISSING_PLAYER = 0

# Commodity buffs for bias_interaction
_BIAS_COMMODITY_BUFFS = {}

# Native mood tuning id -> Sensewright emotion buff id (set_mood channel)
_MOOD_BUFFS = {}


def _safe_getattr(obj, attr, default=None):
    try:
        return getattr(obj, attr, default)
    except Exception:
        return default


def _safe_call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception:
        return None


def register_tuning_ids(trait_hidden_nowalkby, buff_dream_epiphany, buff_dream_surreal,
                        buff_dream_omen, buff_dream_nightmare, bias_commodity_buffs):
    """Register tuning IDs from package at startup."""
    global _TRAIT_HIDDEN_NOWALKBY, _BUFF_DREAM_EPIPHANY, _BUFF_DREAM_SURREAL
    global _BUFF_DREAM_OMEN, _BUFF_DREAM_NIGHTMARE, _BIAS_COMMODITY_BUFFS

    _TRAIT_HIDDEN_NOWALKBY = trait_hidden_nowalkby
    _BUFF_DREAM_EPIPHANY = buff_dream_epiphany
    _BUFF_DREAM_SURREAL = buff_dream_surreal
    _BUFF_DREAM_OMEN = buff_dream_omen
    _BUFF_DREAM_NIGHTMARE = buff_dream_nightmare
    _BIAS_COMMODITY_BUFFS = bias_commodity_buffs or {}


def register_missing_player_buff(buff_id):
    """Register the 'missing player' moodlet tuning ID."""
    global _BUFF_MISSING_PLAYER
    _BUFF_MISSING_PLAYER = buff_id


def register_mood_buffs(mood_buffs):
    """Register the native-mood-id -> emotion-buff-id map (set_mood channel)."""
    global _MOOD_BUFFS
    _MOOD_BUFFS = dict(mood_buffs or {})


def get_missing_player_buff():
    """Return the 'missing player' moodlet tuning ID."""
    return _BUFF_MISSING_PLAYER


def get_player_confidant_sim_id():
    """Get the player confidant sim ID."""
    return _player_confidant_sim_id


_HIDDEN_HOUSEHOLD_NAME = 'Sensewright Hidden Household'


def get_or_create_player_confidant(player_name=None):
    """Get or create the hidden SimInfo representing the player (Model A).

    Uses S4CL's spawn utilities so the SimInfo/Household are constructed through
    the engine's supported path (direct SimInfo()/Household() construction does
    not match TS4's signatures and raises TypeError).
    """
    global _player_confidant_sim_id, _player_confidant_household_id

    if _player_confidant_sim_id > 0:
        sim_info = services.sim_info_manager().get(_player_confidant_sim_id)
        if sim_info is not None:
            return sim_info

    household = _get_or_create_hidden_household()
    if household is None:
        log_error('Failed to create hidden household for player confidant')
        return None

    try:
        sim_info = CommonSimSpawnUtils.create_sim_info(
            CommonSpecies.HUMAN,
            gender=CommonGender.FEMALE,
            age=CommonAge.YOUNGADULT,
            first_name=player_name or 'Confidente',
            last_name='Sensewright',
            household=household,
            source='sensewright',
        )
        if sim_info is None:
            log_error('CommonSimSpawnUtils.create_sim_info returned None')
            return None

        # Hidden trait prevents physical instantiation on lot.
        if _TRAIT_HIDDEN_NOWALKBY > 0:
            CommonTraitUtils.add_trait(sim_info, _TRAIT_HIDDEN_NOWALKBY)

        # Protect from culling.
        try:
            sim_info._culling_immunity = True
        except Exception:
            pass

        _player_confidant_sim_id = sim_info.id
        _player_confidant_household_id = household.id

        log_info('Created player confidant SimInfo: {} (ID: {})'.format(sim_info.full_name, sim_info.id))
        return sim_info

    except Exception as e:
        log_exception('Failed to create player confidant: {}'.format(e))
        return None


def _get_or_create_hidden_household():
    """Get or create the hidden household for the player confidant."""
    household_manager = services.household_manager()
    if household_manager is None:
        return None

    # Look for the existing hidden household by its stable name marker.
    for household in household_manager.values():
        if _safe_getattr(household, 'name', None) == _HIDDEN_HOUSEHOLD_NAME:
            return household

    try:
        household = CommonHouseholdUtils.create_empty_household(as_hidden_household=True)
        household.name = _HIDDEN_HOUSEHOLD_NAME
        try:
            household.description = ''
        except Exception:
            pass
        return household
    except Exception as e:
        log_exception('Failed to create hidden household: {}'.format(e))
        return None


def apply_buff(sim_info, buff_id, duration_sim_minutes=60):
    """Apply a buff to a sim.

    S4CL's CommonBuffUtils.add_buff does not accept a duration; the buff's
    tuned lifetime governs it. `duration_sim_minutes` is kept for call-site
    compatibility only. Returns False when the buff tuning could not be loaded
    or the engine rejected it, so callers never report a false success.
    """
    if sim_info is None or buff_id == 0:
        return False

    try:
        if CommonBuffUtils.load_buff_by_id(buff_id) is None:
            log_warn('Buff {} not loaded; cannot apply'.format(buff_id))
            return False
        result = CommonBuffUtils.add_buff(sim_info, buff_id)
        if not result:
            log_warn('Engine rejected buff {}'.format(buff_id))
            return False
        return True
    except Exception as e:
        log_exception('Failed to apply buff {}: {}'.format(buff_id, e))
        return False


def remove_buff(sim_info, buff_id):
    """Remove a buff from a sim."""
    if sim_info is None or buff_id == 0:
        return False

    try:
        CommonBuffUtils.remove_buff(sim_info, buff_id)
        return True
    except Exception as e:
        log_exception('Failed to remove buff {}: {}'.format(buff_id, e))
        return False


def has_buff(sim_info, buff_id):
    """Check if sim has a buff."""
    if sim_info is None or buff_id == 0:
        return False

    try:
        return CommonBuffUtils.has_buff(sim_info, buff_id)
    except Exception:
        return False


def _request_balloon(sim_info, text):
    """Best-effort thought balloon during sleep (3.8).

    The engine exposes no stable public balloon API, so try the per-Sim balloon
    methods when present and otherwise rely on the buff reason (which already
    carries the narrative). Never raises.
    """
    if not text:
        return False
    sim = _safe_call(CommonSimUtils.get_sim_instance, sim_info)
    if sim is None:
        return False
    for method_name in ('show_thought_balloon', 'show_speech_balloon'):
        method = _safe_getattr(sim, method_name, None)
        if callable(method):
            try:
                method(text)
                return True
            except Exception:
                continue
    # Native balloon request path (varies across game builds).
    try:
        from balloons.balloon_request import BalloonRequest
        request = BalloonRequest(sim_info, text)
        request.send()
        return True
    except Exception:
        return False


def apply_dream_buff(sim_info, archetype, dream_narrative):
    """Apply the dream buff and surface the narrative in the moodlet (3.8).

    The narrative is passed as the buff's ``buff_reason`` (TS4 appends it to the
    moodlet tooltip) and a best-effort sleep balloon is requested. S4CL owns the
    supported buff path, so this never raises.
    """
    buff_map = {
        'epiphany': _BUFF_DREAM_EPIPHANY,
        'surreal': _BUFF_DREAM_SURREAL,
        'omen': _BUFF_DREAM_OMEN,
        'nightmare': _BUFF_DREAM_NIGHTMARE
    }

    buff_id = buff_map.get((archetype or '').lower())
    if buff_id == 0:
        log_warn('Unknown dream archetype: {}'.format(archetype))
        return False

    applied = False
    try:
        # Newer S4CL accepts buff_reason; the dream narrative lands in the tooltip.
        result = CommonBuffUtils.add_buff(sim_info, buff_id, buff_reason=dream_narrative or None)
        applied = result if isinstance(result, bool) else bool(getattr(result, 'result', True))
    except TypeError:
        # Older S4CL signature without buff_reason.
        try:
            CommonBuffUtils.add_buff(sim_info, buff_id)
            applied = True
        except Exception as e:
            log_exception('Failed to apply dream buff: {}'.format(e))
            return False
    except Exception as e:
        log_exception('Failed to apply dream buff: {}'.format(e))
        return False

    if dream_narrative:
        if not _request_balloon(sim_info, dream_narrative):
            log_debug('dream balloon API unavailable; narrative carried by the buff reason')
    return applied


def add_relationship_bit(sim_info, target_sim_info, bit_id):
    """Add a relationship bit (sentiment) between two sims."""
    if sim_info is None or target_sim_info is None or bit_id == 0:
        return False

    try:
        CommonRelationshipUtils.add_relationship_bit(sim_info, target_sim_info, bit_id)
        return True
    except Exception as e:
        log_exception('Failed to add relationship bit {}: {}'.format(bit_id, e))
        return False


def remove_relationship_bit(sim_info, target_sim_info, bit_id):
    """Remove a relationship bit."""
    if sim_info is None or target_sim_info is None or bit_id == 0:
        return False

    try:
        CommonRelationshipUtils.remove_relationship_bit(sim_info, target_sim_info, bit_id)
        return True
    except Exception as e:
        log_exception('Failed to remove relationship bit {}: {}'.format(bit_id, e))
        return False


def has_relationship_bit(sim_info, target_sim_info, bit_id):
    """Check if relationship bit exists."""
    if sim_info is None or target_sim_info is None or bit_id == 0:
        return False

    try:
        return CommonRelationshipUtils.has_relationship_bit_with_sim(sim_info, target_sim_info, bit_id)
    except Exception:
        return False


def set_trait(sim_info, trait_id):
    """Add a trait to a sim (for likes/dislikes/trait swap)."""
    if sim_info is None or trait_id == 0:
        return False

    try:
        CommonTraitUtils.add_trait(sim_info, trait_id)
        return True
    except Exception as e:
        log_exception('Failed to add trait {}: {}'.format(trait_id, e))
        return False


def remove_trait(sim_info, trait_id):
    """Remove a trait from a sim."""
    if sim_info is None or trait_id == 0:
        return False

    try:
        CommonTraitUtils.remove_trait(sim_info, trait_id)
        return True
    except Exception as e:
        log_exception('Failed to remove trait {}: {}'.format(trait_id, e))
        return False


def has_trait(sim_info, trait_id):
    """Check if sim has a trait."""
    if sim_info is None or trait_id == 0:
        return False

    try:
        return CommonTraitUtils.has_trait(sim_info, trait_id)
    except Exception:
        return False


def add_social_motive_gain(sim_info, amount=50):
    """Increase social motive for chat interaction."""
    if sim_info is None:
        return False

    try:
        from sims4communitylib.utils.sims.common_sim_motive_utils import CommonSimMotiveUtils
        from sims4communitylib.enums.motives_enum import CommonMotiveId
        CommonSimMotiveUtils.increase_motive_level(sim_info, CommonMotiveId.SOCIAL, amount)
        return True
    except Exception as e:
        log_exception('Failed to add social motive: {}'.format(e))
        return False


def add_fun_motive_gain(sim_info, amount=30):
    """Increase fun motive for chat interaction."""
    if sim_info is None:
        return False

    try:
        from sims4communitylib.utils.sims.common_sim_motive_utils import CommonSimMotiveUtils
        from sims4communitylib.enums.motives_enum import CommonMotiveId
        CommonSimMotiveUtils.increase_motive_level(sim_info, CommonMotiveId.FUN, amount)
        return True
    except Exception as e:
        log_exception('Failed to add fun motive: {}'.format(e))
        return False


def trigger_want_message_player(sim_info):
    """Apply the 'missing player' moodlet when the sim is lonely/sad (A4).

    The native Wants system has no public API for injecting custom Wants, so a
    visible moodlet (localized 'Missing {player_name}') is the diegetic trigger
    instead. The player name is injected as a {0.String} token when available.
    """
    if sim_info is None:
        return False

    buff_id = _BUFF_MISSING_PLAYER
    if buff_id == 0:
        # Fall back to the dream-epiphany buff slot if the package lacks the moodlet.
        buff_id = _BUFF_DREAM_EPIPHANY
    if buff_id == 0:
        return False

    try:
        CommonBuffUtils.add_buff(sim_info, buff_id, buff_reason='sensewright')
        return True
    except Exception:
        pass

    return apply_buff(sim_info, buff_id, 120)


def apply_mood(sim_info, mood_id):
    """Apply a mood (Types.MOOD statistic) to a sim, defensively.

    Attempts the documented S4CL set_mood API first, then the native mood
    tracker, and finally falls back to applying the mood as a buff. Never raises.
    """
    if sim_info is None or mood_id is None or mood_id == 0:
        return False

    # Primary path: apply the registered emotion buff for this mood. TS4 derives
    # a Sim's mood from active buffs, so this is the only reliable way to hold it.
    try:
        buff_id = _MOOD_BUFFS.get(int(mood_id))
        if buff_id and apply_buff(sim_info, buff_id, 90):
            return True
    except Exception:
        pass

    try:
        from sims4communitylib.utils.sims.common_sim_state_utils import CommonSimStateUtils
        if hasattr(CommonSimStateUtils, 'set_mood'):
            result = CommonSimStateUtils.set_mood(sim_info, mood_id)
            if result is not None:
                return True
    except Exception:
        pass

    try:
        setter = _safe_getattr(sim_info, 'set_mood', None)
        if callable(setter):
            setter(mood_id)
            return True
    except Exception:
        pass

    try:
        tracker = _safe_getattr(sim_info, 'mood_tracker', None)
        if tracker is not None:
            set_mood_fn = _safe_getattr(tracker, 'set_mood', None)
            if callable(set_mood_fn):
                set_mood_fn(mood_id)
                return True
    except Exception:
        pass

    # Last-resort: treat the mood id as a buff (best-effort).
    return apply_buff(sim_info, mood_id, 60)


def get_bias_commodity_buffs():
    """Get the bias commodity buff mappings."""
    return dict(_BIAS_COMMODITY_BUFFS)