# Sensewright v2 — Native Hooks (Hidden SimInfo, Buffs, Sentiments, Traits, Dreams)
# Python 3.7 compatible

import services
import sims4.resources
import sims4.math
from sims.sim_info import SimInfo
from sims.household import Household
from sims4communitylib.utils.sims.common_sim_utils import CommonSimUtils
from sims4communitylib.utils.sims.common_household_utils import CommonHouseholdUtils
from sims4communitylib.utils.sims.common_trait_utils import CommonTraitUtils
from sims4communitylib.utils.sims.common_buff_utils import CommonBuffUtils
from sims4communitylib.utils.sims.common_relationship_utils import CommonRelationshipUtils

from sensewright_mod.debug_log import log_error, log_exception, log_info, safe_call


# Global state
_player_confidant_sim_id = 0
_player_confidant_household_id = 0

# Trait and Buff tuning IDs (populated from package at runtime)
_TRAIT_HIDDEN_NOWALKBY = 0
_BUFF_DREAM_EPIPHANY = 0
_BUFF_DREAM_SURREAL = 0
_BUFF_DREAM_OMEN = 0
_BUFF_DREAM_NIGHTMARE = 0

# Commodity buffs for bias_interaction
_BIAS_COMMODITY_BUFFS = {}


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


def get_player_confidant_sim_id():
    """Get the player confidant sim ID."""
    return _player_confidant_sim_id


def get_or_create_player_confidant(player_name=None):
    """Get or create the hidden SimInfo representing the player (Model A)."""
    global _player_confidant_sim_id, _player_confidant_household_id

    if _player_confidant_sim_id > 0:
        sim_info = services.sim_info_manager().get(_player_confidant_sim_id)
        if sim_info is not None:
            return sim_info

    # Create hidden household
    household = _get_or_create_hidden_household()
    if household is None:
        log_error('Failed to create hidden household for player confidant')
        return None

    # Create SimInfo in hidden household
    try:
        from sims.sim_info import SimInfo
        from sims.sim_info_types import Age, Gender, Species
        from sims4.resources import Types

        # Create sim info data
        sim_info = SimInfo(
            household=household,
            gender=Gender.FEMALE,  # Default, can be customized
            age=Age.YOUNGADULT,
            species=Species.HUMAN,
            name=player_name or 'Confidente'
        )

        # Add hidden trait to prevent physical instantiation
        if _TRAIT_HIDDEN_NOWALKBY > 0:
            CommonTraitUtils.add_trait(sim_info, _TRAIT_HIDDEN_NOWALKBY)

        # Protect from culling
        sim_info._culling_immunity = True

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

    # Look for existing hidden household with our marker
    for household in household_manager.values():
        if _safe_getattr(household, '_sensewright_hidden', False):
            return household

    # Create new hidden household
    try:
        household = Household(household_id=0)
        household._sensewright_hidden = True
        household.hidden = True
        household.name = 'Sensewright Hidden Household'

        # Add to household manager
        household_manager.add(household)
        return household
    except Exception as e:
        log_exception('Failed to create hidden household: {}'.format(e))
        return None


def apply_buff(sim_info, buff_id, duration_sim_minutes=60):
    """Apply a buff to a sim."""
    if sim_info is None or buff_id == 0:
        return False

    try:
        CommonBuffUtils.add_buff(sim_info, buff_id, duration=duration_sim_minutes)
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


def apply_dream_buff(sim_info, archetype, dream_narrative):
    """Apply the appropriate dream buff with narrative in tooltip token."""
    buff_map = {
        'epiphany': _BUFF_DREAM_EPIPHANY,
        'surreal': _BUFF_DREAM_SURREAL,
        'omen': _BUFF_DREAM_OMEN,
        'nightmare': _BUFF_DREAM_NIGHTMARE
    }

    buff_id = buff_map.get(archetype.lower())
    if buff_id == 0:
        log_warn('Unknown dream archetype: {}'.format(archetype))
        return False

    # The buff tooltip uses {0.String} token for the dream narrative
    # We need to apply the buff with the narrative as a token
    try:
        # Apply buff with custom tooltip token
        # This requires the buff to be tuned with a TunableLocalizedStringFactory
        # that accepts a {0.String} token
        from sims4.localization import LocalizationHelperTuning
        from protocolbuffers.Localization_pb2 import LocalizedString

        # Create localized string with the dream narrative
        token = LocalizationHelperTuning.get_raw_text(dream_narrative)

        # Apply buff - the tooltip will pick up the token
        CommonBuffUtils.add_buff(sim_info, buff_id, duration=240,  # 4 hours
                                 additional_tokens=(token,))
        return True
    except Exception as e:
        log_exception('Failed to apply dream buff: {}'.format(e))
        # Fallback: apply without token
        try:
            CommonBuffUtils.add_buff(sim_info, buff_id, duration=240)
            return True
        except Exception:
            return False


def add_relationship_bit(sim_info, target_sim_info, bit_id):
    """Add a relationship bit (sentiment) between two sims."""
    if sim_info is None or target_sim_info is None or bit_id == 0:
        return False

    try:
        CommonRelationshipUtils.add_relationship_bit(sim_info.id, target_sim_info.id, bit_id)
        return True
    except Exception as e:
        log_exception('Failed to add relationship bit {}: {}'.format(bit_id, e))
        return False


def remove_relationship_bit(sim_info, target_sim_info, bit_id):
    """Remove a relationship bit."""
    if sim_info is None or target_sim_info is None or bit_id == 0:
        return False

    try:
        CommonRelationshipUtils.remove_relationship_bit(sim_info.id, target_sim_info.id, bit_id)
        return True
    except Exception as e:
        log_exception('Failed to remove relationship bit {}: {}'.format(bit_id, e))
        return False


def has_relationship_bit(sim_info, target_sim_info, bit_id):
    """Check if relationship bit exists."""
    if sim_info is None or target_sim_info is None or bit_id == 0:
        return False

    try:
        return CommonRelationshipUtils.has_relationship_bit(sim_info.id, target_sim_info.id, bit_id)
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
        commodity_tracker = _safe_getattr(sim_info, 'commodity_tracker', None)
        if commodity_tracker is None:
            return False

        # Find social motive statistic
        stat = commodity_tracker.get_statistic(sims4.resources.Types.STATISTIC, add=False)
        # This is simplified - real implementation would find the specific social motive
        # For now, use CommonSimStateUtils
        from sims4communitylib.utils.sims.common_sim_state_utils import CommonSimStateUtils
        CommonSimStateUtils.add_motive_value(sim_info, 'social', amount)
        return True
    except Exception as e:
        log_exception('Failed to add social motive: {}'.format(e))
        return False


def add_fun_motive_gain(sim_info, amount=30):
    """Increase fun motive for chat interaction."""
    if sim_info is None:
        return False

    try:
        from sims4communitylib.utils.sims.common_sim_state_utils import CommonSimStateUtils
        CommonSimStateUtils.add_motive_value(sim_info, 'fun', amount)
        return True
    except Exception as e:
        log_exception('Failed to add fun motive: {}'.format(e))
        return False


def trigger_want_message_player(sim_info):
    """Trigger the native 'Want to message player' want (if possible)."""
    # This is difficult to implement reliably - using moodlet as alternative
    return apply_buff(sim_info, _BUFF_DREAM_EPIPHANY, 120)  # Placeholder


def get_bias_commodity_buffs():
    """Get the bias commodity buff mappings."""
    return dict(_BIAS_COMMODITY_BUFFS)