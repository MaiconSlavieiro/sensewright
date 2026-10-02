# Sensewright v2 — State Collector (GAME_TICK)
# Python 3.7 compatible

import services
import sims4.math
from sims.sim_info import SimInfo
from sims4communitylib.utils.sims.common_sim_utils import CommonSimUtils
from sims4communitylib.utils.sims.common_sim_state_utils import CommonSimStateUtils

from sensewright_mod.debug_log import log_error, log_exception, safe_call
from sensewright_mod.config import get_agent_seats


# Cache for performance
_sim_info_cache = {}
_cache_valid_tick = -1


def _safe_getattr(obj, attr, default=None):
    """Safely get attribute, returning default on any error."""
    try:
        return getattr(obj, attr, default)
    except Exception:
        return default


def _safe_call(func, *args, **kwargs):
    """Safely call a function, returning None on any error."""
    try:
        return func(*args, **kwargs)
    except Exception:
        return None


def _get_sim_info(sim_id):
    """Get SimInfo by ID with caching."""
    global _sim_info_cache, _cache_valid_tick
    current_tick = _get_world_sim_tick()
    if current_tick != _cache_valid_tick:
        _sim_info_cache.clear()
        _cache_valid_tick = current_tick

    if sim_id in _sim_info_cache:
        return _sim_info_cache[sim_id]

    sim_info = _safe_call(services.sim_info_manager().get, sim_id)
    if sim_info is not None:
        _sim_info_cache[sim_id] = sim_info
    return sim_info


def _get_world_sim_tick():
    """Get current world sim tick (absolute ticks)."""
    try:
        clock = services.game_clock_service()
        if clock is not None:
            now = clock.now()
            if now is not None:
                return now.absolute_ticks()
    except Exception:
        pass
    return 0


def _get_clock_speed():
    """Get current clock speed (0=paused, 1=normal, 2=fast, 3=ultra)."""
    try:
        clock = services.game_clock_service()
        if clock is not None:
            return _safe_getattr(clock, 'clock_speed', 1)
    except Exception:
        pass
    return 1


def _get_active_sim_id():
    """Get the active sim ID."""
    try:
        active_sim = services.active_sim_info()
        if active_sim is not None:
            return active_sim.id
    except Exception:
        pass
    return 0


def _get_player_confidant_sim_id():
    """Get the player confidant sim ID (hidden SimInfo)."""
    # This will be set by native_hooks when the confidant is created/retrieved
    from sensewright_mod.native_hooks import get_player_confidant_sim_id as get_confidant
    return get_confidant()


def _get_zone_id():
    """Get current zone ID."""
    try:
        return services.current_zone_id()
    except Exception:
        return 0


def _get_save_slot_guid():
    """Get save slot GUID."""
    try:
        from lot51_core.lib.save import get_save_slot_guid
        return get_save_slot_guid()
    except Exception:
        return 'unknown'


def _get_installed_packs():
    """Get list of installed pack IDs."""
    packs = []
    try:
        pack_manager = services.get_instance_manager(sims4.resources.Types.GAMEPLAY_DATA)
        # This is a simplified version - real implementation would check specific packs
        # For now return empty list, sidecar can infer from other data
    except Exception:
        pass
    return packs


def _collect_sim_delta(sim_info):
    """Collect volatile state delta for a single sim."""
    if sim_info is None:
        return None

    try:
        sim_id = sim_info.id

        # Mood
        mood = 'fine'
        try:
            mood_stat = _safe_getattr(sim_info, 'mood', None)
            if mood_stat is not None:
                mood = _safe_getattr(mood_stat, '__name__', str(mood_stat))
        except Exception:
            pass

        # Needs (motives)
        needs = {}
        try:
            commodity_tracker = _safe_getattr(sim_info, 'commodity_tracker', None)
            if commodity_tracker is not None:
                for commodity_type in (services.get_instance_manager(sims4.resources.Types.STATISTIC).types.values()):
                    try:
                        stat = commodity_tracker.get_statistic(commodity_type, add=False)
                        if stat is not None:
                            needs[commodity_type.__name__] = stat.get_value()
                    except Exception:
                        pass
        except Exception:
            pass

        # Room ID
        room_id = 0
        try:
            sim = _safe_call(CommonSimUtils.get_sim_instance, sim_info)
            if sim is not None:
                routing_component = _safe_getattr(sim, 'routing_component', None)
                if routing_component is not None:
                    room_id = _safe_getattr(routing_component, 'current_room_id', 0)
        except Exception:
            pass

        # Position
        pos = {'x': 0.0, 'y': 0.0, 'z': 0.0}
        try:
            sim = _safe_call(CommonSimUtils.get_sim_instance, sim_info)
            if sim is not None:
                position = _safe_getattr(sim, 'position', None)
                if position is not None:
                    pos = {'x': float(position.x), 'y': float(position.y), 'z': float(position.z)}
        except Exception:
            pass

        # Activity / Current interaction
        activity = 'idle'
        try:
            sim = _safe_call(CommonSimUtils.get_sim_instance, sim_info)
            if sim is not None:
                si = _safe_getattr(sim, 'si_state', None)
                if si is not None:
                    current_interaction = _safe_getattr(si, 'current_interaction', None)
                    if current_interaction is not None:
                        activity = _safe_getattr(current_interaction, '__name__', str(current_interaction))
        except Exception:
            pass

        # Interaction queue length
        queue_len = 0
        try:
            sim = _safe_call(CommonSimUtils.get_sim_instance, sim_info)
            if sim is not None:
                si_state = _safe_getattr(sim, 'si_state', None)
                if si_state is not None:
                    queue_len = len(_safe_getattr(si_state, 'interaction_queue', []))
        except Exception:
            pass

        # Is sleeping
        is_sleeping = False
        try:
            is_sleeping = _safe_call(CommonSimStateUtils.is_sleeping, sim_info) or False
        except Exception:
            pass

        # Is off lot duty (work/school rabbit hole)
        is_off_lot_duty = False
        try:
            career_tracker = _safe_getattr(sim_info, 'career_tracker', None)
            if career_tracker is not None:
                career = _safe_getattr(career_tracker, 'current_career', None)
                if career is not None:
                    is_off_lot_duty = _safe_getattr(career, 'is_at_work', False)
            # Also check school for children/teens
            if not is_off_lot_duty:
                school_tracker = _safe_getattr(sim_info, 'school_tracker', None)
                if school_tracker is not None:
                    is_off_lot_duty = _safe_getattr(school_tracker, 'is_at_school', False)
        except Exception:
            pass

        # Wants (simplified - just count)
        wants = []
        try:
            want_tracker = _safe_getattr(sim_info, 'want_tracker', None)
            if want_tracker is not None:
                wants_list = _safe_getattr(want_tracker, 'wants', [])
                for want in wants_list[:5]:  # Limit to 5
                    wants.append(_safe_getattr(want, '__name__', str(want)))
        except Exception:
            pass

        # Obligatory tasks (career daily task, homework, etc.)
        obligatory_tasks = []
        try:
            career_tracker = _safe_getattr(sim_info, 'career_tracker', None)
            if career_tracker is not None:
                career = _safe_getattr(career_tracker, 'current_career', None)
                if career is not None:
                    daily_task = _safe_getattr(career, 'daily_task', None)
                    if daily_task is not None:
                        obligatory_tasks.append('career_daily_task')
        except Exception:
            pass

        return {
            'sim_id': sim_id,
            'mood': mood,
            'needs': needs,
            'room_id': room_id,
            'pos': pos,
            'activity': activity,
            'queue': queue_len,
            'is_sleeping': is_sleeping,
            'is_off_lot_duty': is_off_lot_duty,
            'wants': wants,
            'obligatory_tasks': obligatory_tasks
        }
    except Exception as e:
        log_exception('Error collecting sim delta for {}: {}'.format(sim_id, e))
        return None


def _collect_full_sim_census(sim_info):
    """Collect full static census data for a sim."""
    if sim_info is None:
        return None

    try:
        sim_id = sim_info.id

        # Traits
        traits = []
        try:
            trait_tracker = _safe_getattr(sim_info, 'trait_tracker', None)
            if trait_tracker is not None:
                for trait in _safe_getattr(trait_tracker, 'traits', []):
                    traits.append(_safe_getattr(trait, '__name__', str(trait)))
        except Exception:
            pass

        # Likes/Dislikes
        likes = []
        dislikes = []
        try:
            trait_tracker = _safe_getattr(sim_info, 'trait_tracker', None)
            if trait_tracker is not None:
                for like in _safe_getattr(trait_tracker, 'likes', []):
                    likes.append(_safe_getattr(like, '__name__', str(like)))
                for dislike in _safe_getattr(trait_tracker, 'dislikes', []):
                    dislikes.append(_safe_getattr(dislike, '__name__', str(dislike)))
        except Exception:
            pass

        # Career
        career = None
        try:
            career_tracker = _safe_getattr(sim_info, 'career_tracker', None)
            if career_tracker is not None:
                current_career = _safe_getattr(career_tracker, 'current_career', None)
                if current_career is not None:
                    career = _safe_getattr(current_career, '__name__', str(current_career))
        except Exception:
            pass

        # Schedule blocks (simplified)
        schedule_blocks = []
        try:
            career_tracker = _safe_getattr(sim_info, 'career_tracker', None)
            if career_tracker is not None:
                career = _safe_getattr(career_tracker, 'current_career', None)
                if career is not None:
                    work_hours = _safe_getattr(career, 'work_hours', None)
                    if work_hours is not None:
                        schedule_blocks.append({
                            'type': 'work',
                            'days': _safe_getattr(work_hours, 'days', []),
                            'start_hour': _safe_getattr(work_hours, 'start_time', 0),
                            'end_hour': _safe_getattr(work_hours, 'end_time', 0)
                        })
        except Exception:
            pass

        # Family links
        family_links = []
        try:
            relationship_tracker = _safe_getattr(sim_info, 'relationship_tracker', None)
            if relationship_tracker is not None:
                for rel in _safe_getattr(relationship_tracker, 'relationships', []):
                    target_id = _safe_getattr(rel, 'target_sim_id', 0)
                    if target_id > 0:
                        rel_bits = _safe_getattr(rel, 'relationship_bits', [])
                        for bit in rel_bits:
                            bit_name = _safe_getattr(bit, '__name__', str(bit))
                            if 'family' in bit_name.lower() or 'parent' in bit_name.lower() or 'child' in bit_name.lower() or 'sibling' in bit_name.lower() or 'spouse' in bit_name.lower():
                                family_links.append({'target_sim_id': target_id, 'relationship': bit_name})
                                break
        except Exception:
            pass

        # Household ID
        household_id = 0
        try:
            household = _safe_getattr(sim_info, 'household', None)
            if household is not None:
                household_id = _safe_getattr(household, 'id', 0)
        except Exception:
            pass

        # Is player (in active household)
        is_player = False
        try:
            active_household = services.active_household()
            if active_household is not None:
                is_player = (household_id == active_household.id)
        except Exception:
            pass

        return {
            'sim_id': sim_id,
            'name': _safe_getattr(sim_info, 'full_name', 'Unknown'),
            'species': 'HUMAN',  # Simplified
            'age_stage': _safe_getattr(sim_info, 'age', 'YOUNGADULT'),
            'traits': traits,
            'likes': likes,
            'dislikes': dislikes,
            'career': career,
            'schedule_blocks': schedule_blocks,
            'family_links': family_links,
            'household_id': household_id,
            'is_player': is_player
        }
    except Exception as e:
        log_exception('Error collecting census for {}: {}'.format(sim_id, e))
        return None


def collect_sims_delta(active_only=False):
    """Collect sims_delta for all active/seat sims."""
    world_sim_tick = _get_world_sim_tick()
    sims_delta = []

    try:
        sim_info_manager = services.sim_info_manager()
        if sim_info_manager is None:
            return sims_delta

        # Get active household sims + visitors on lot
        active_household = services.active_household()
        target_sims = []

        if active_household is not None:
            for sim_info in active_household.sim_infos:
                target_sims.append(sim_info)

        # Add instanced sims on current lot (visitors)
        zone = services.current_zone()
        if zone is not None:
            for sim in zone.sims:
                sim_info = _safe_getattr(sim, 'sim_info', None)
                if sim_info is not None and sim_info not in target_sims:
                    target_sims.append(sim_info)

        # Limit to agent_seats
        max_seats = get_agent_seats()
        for sim_info in target_sims[:max_seats]:
            delta = _collect_sim_delta(sim_info)
            if delta is not None:
                sims_delta.append(delta)

    except Exception as e:
        log_exception('Error in collect_sims_delta: {}'.format(e))

    return sims_delta


def collect_full_census():
    """Collect full census for session start."""
    sims = []
    households = []
    relationships = []

    try:
        sim_info_manager = services.sim_info_manager()
        if sim_info_manager is None:
            return sims, households, relationships

        # All sims in save
        for sim_info in sim_info_manager.values():
            census = _collect_full_sim_census(sim_info)
            if census is not None:
                sims.append(census)

        # Households
        household_manager = services.household_manager()
        if household_manager is not None:
            for household in household_manager.values():
                households.append({
                    'household_id': household.id,
                    'name': _safe_getattr(household, 'name', ''),
                    'home_zone_id': _safe_getattr(household, 'home_zone_id', 0),
                    'funds': _safe_getattr(household, 'funds', 0)
                })

        # Relationships (simplified)
        for sim_info in sim_info_manager.values():
            rel_tracker = _safe_getattr(sim_info, 'relationship_tracker', None)
            if rel_tracker is not None:
                for rel in _safe_getattr(rel_tracker, 'relationships', []):
                    target_id = _safe_getattr(rel, 'target_sim_id', 0)
                    if target_id > sim_info.id:  # Avoid duplicates
                        relationships.append({
                            'sim_id': sim_info.id,
                            'target_sim_id': target_id,
                            'friendship': _safe_getattr(rel, 'friendship', 0),
                            'romance': _safe_getattr(rel, 'romance', 0),
                            'tracks': []
                        })

    except Exception as e:
        log_exception('Error in collect_full_census: {}'.format(e))

    return sims, households, relationships


def get_current_game_state():
    """Get current game state for autonomy tick."""
    return {
        'world_sim_tick': _get_world_sim_tick(),
        'clock_speed': _get_clock_speed(),
        'active_sim_id': _get_active_sim_id(),
        'player_confidant_sim_id': _get_player_confidant_sim_id(),
        'zone_id': _get_zone_id(),
        'save_id': _get_save_slot_guid(),
        'installed_packs': _get_installed_packs()
    }