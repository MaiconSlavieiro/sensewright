# Sensewright v2 — State Collector (GAME_TICK)
# Python 3.7 compatible

import services
import sims4.math
from sims.sim_info import SimInfo
from sims4communitylib.utils.sims.common_sim_utils import CommonSimUtils
from sims4communitylib.utils.sims.common_mood_utils import CommonMoodUtils

from sensewright_mod.debug_log import log_error, log_exception, safe_call, worker_log_info
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


def _coerce_int(value, default=0):
    """Best-effort coerce a game value (e.g. FamilyFunds) into a JSON-safe int."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


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
    """Get list of installed pack IDs (BUG/REQ A10, plan 2.3).

    Uses S4CL's pack utility when available; degrades to an empty list so the
    sidecar never enables an expansion-gated lever on a false positive.
    """
    packs = []
    try:
        from sims4communitylib.utils.common_pack_utils import CommonPackUtils
        for pack_type in CommonPackUtils.get_installed_pack_types():
            name = _safe_getattr(pack_type, '__name__', None) or str(pack_type)
            if name:
                packs.append(str(name).upper())
    except Exception:
        return packs
    return packs


#: Interaction class-name fragments that mark a conversational interaction.
#: The Mod also reports a reliable ``is_conversing`` flag (BUG-01); the markers
#: are only a last-resort fallback because EA names social classes without them.
_CONVERSATION_MARKERS = ('social', 'talk', 'chat', 'convers', 'get_to_know', 'getknow')


def _as_sim_info(candidate):
    """Return ``candidate`` as a SimInfo if it is a Sim/SimInfo, else None.

    Guards against object targets (chairs, mirrors) that also expose an ``id``.
    """
    if candidate is None:
        return None
    if isinstance(candidate, SimInfo):
        return candidate
    inner = _safe_getattr(candidate, 'sim_info', None)
    if isinstance(inner, SimInfo):
        return inner
    if _safe_getattr(candidate, 'is_sim', False) and inner is not None:
        return inner
    return None


def _resolve_interaction_target_sim_id(current_interaction):
    """Best-effort resolve the Sim id targeted by an interaction (BUG-01).

    A conversational interaction has another Sim as its target. Matching the
    interaction class name is unreliable (``MixerInteraction``, ``GetToKnow``,
    ``TellJoke``… do not contain "social"), so we resolve the target Sim id.
    """
    if current_interaction is None:
        return 0
    candidates = []
    for accessor in ('get_target_sim', 'get_target', 'get_target_sim_info'):
        fn = _safe_getattr(current_interaction, accessor, None)
        if callable(fn):
            candidates.append(_safe_call(fn))
    for attr in ('target_sim', 'target_sim_info', 'target', 'picked_sim'):
        candidates.append(_safe_getattr(current_interaction, attr, None))
    for candidate in candidates:
        sim_info = _as_sim_info(candidate)
        if sim_info is None:
            continue
        target_id = _coerce_int(_safe_getattr(sim_info, 'id', 0), 0)
        if target_id:
            return target_id
    return 0


def _member_sim_id(member):
    """Coerce a social-group member (Sim or SimInfo) to its numeric id."""
    if member is None:
        return 0
    sim_info = _safe_getattr(member, 'sim_info', None)
    if sim_info is not None:
        return _coerce_int(_safe_getattr(sim_info, 'id', 0), 0)
    return _coerce_int(_safe_getattr(member, 'id', 0), 0)


def _resolve_social_group_peer(sim, sim_id):
    """Return the id of another Sim conversing with ``sim``, or 0 (BUG-02).

    The conversation participants live on each *social interaction* in the Sim's
    ``si_state`` (``si.social_group``) — not on the Sim itself. ``Sim`` has no
    ``social_group`` attribute, which made the previous implementation always
    return 0 (observed: ``delta: 12 sims, 0 conversing``).
    """
    for source_name in ('si_state', 'queue'):
        collection = _safe_getattr(sim, source_name, None)
        if collection is None:
            continue
        try:
            for social_interaction in collection:
                social_group = _safe_getattr(social_interaction, 'social_group', None)
                if social_group is None:
                    continue
                try:
                    for member in social_group:
                        member_id = _member_sim_id(member)
                        if member_id and member_id != sim_id:
                            return member_id
                except Exception:
                    continue
        except Exception:
            continue
    return 0


def _get_room_id(sim_info):
    """Return the id of the room ``sim_info`` is in, or 0 if unknown (BUG-02).

    S4CL's accessor computes the block id from position + surface level and is
    version-stable. The previous ``routing_component.current_room_id`` attribute
    does not exist and silently returned 0.
    """
    try:
        from sims4communitylib.utils.sims.common_sim_location_utils import CommonSimLocationUtils
        room_id = CommonSimLocationUtils.get_current_room_id(sim_info)
        if room_id is not None and room_id >= 0:
            return int(room_id)
    except Exception:
        pass
    # Fallback: raw routing component access (defensive; may not exist).
    try:
        sim = _safe_call(CommonSimUtils.get_sim_instance, sim_info)
        routing_component = _safe_getattr(sim, 'routing_component', None)
        if routing_component is not None:
            room_id = _safe_getattr(routing_component, 'current_room_id', 0)
            if room_id:
                return int(room_id)
    except Exception:
        pass
    return 0


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

        # Room ID (BUG-02 fix: `routing_component.current_room_id` does not exist
        # on the Sim object and always returned 0, which disabled the social
        # proximity fallback and the `same_room` pre-flight gate. S4CL exposes a
        # reliable accessor; degrade to 0 (unknown) on any failure.
        room_id = _get_room_id(sim_info)

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

        # Activity / Current interaction / conversation signal (BUG-01/BUG-02)
        activity = 'idle'
        is_conversing = False
        social_target_sim_id = 0
        try:
            sim = _safe_call(CommonSimUtils.get_sim_instance, sim_info)
            if sim is not None:
                # 1. Social-group membership is the most reliable conversation
                #    signal: TS4 keeps the other Sim(s) in the group, while the
                #    current interaction target is often the mixer (None target).
                social_target_sim_id = _resolve_social_group_peer(sim, sim_id)
                if social_target_sim_id:
                    is_conversing = True
                si = _safe_getattr(sim, 'si_state', None)
                if si is not None:
                    current_interaction = _safe_getattr(si, 'current_interaction', None)
                    if current_interaction is not None:
                        activity = _safe_getattr(current_interaction, '__name__', str(current_interaction))
                        # 2. Fallback: resolve the interaction's Sim target directly.
                        if not is_conversing:
                            social_target_sim_id = _resolve_interaction_target_sim_id(current_interaction)
                            if social_target_sim_id and social_target_sim_id != sim_id:
                                is_conversing = True
                        # 3. Last resort: class-name marker matching.
                        if not is_conversing and any(marker in str(activity).lower() for marker in _CONVERSATION_MARKERS):
                            is_conversing = True
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
            is_sleeping = _safe_call(CommonMoodUtils.is_sleeping, sim_info) or False
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
            'is_conversing': is_conversing,
            'social_target_sim_id': social_target_sim_id,
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

        # Aspiration / ambition (P12 / plan task 2.2)
        aspiration = ''
        try:
            aspiration_tracker = _safe_getattr(sim_info, 'aspiration_tracker', None)
            if aspiration_tracker is not None:
                current = _safe_getattr(aspiration_tracker, 'current_aspiration', None)
                if current is not None:
                    aspiration = str(_safe_getattr(current, '__name__', current))
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
            'name': str(_safe_getattr(sim_info, 'full_name', 'Unknown') or 'Unknown'),
            'species': 'HUMAN',  # Simplified
            'age_stage': str(_safe_getattr(sim_info, 'age', 'YOUNGADULT')),
            'traits': traits,
            'likes': likes,
            'dislikes': dislikes,
            'career': career,
            'aspiration': aspiration,
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

        # Add instanced sims currently in the zone (visitors) via S4CL.
        try:
            for sim_info in CommonSimUtils.get_instanced_sim_info_for_all_sims_generator():
                if sim_info is not None and sim_info not in target_sims:
                    target_sims.append(sim_info)
        except Exception as e:
            log_exception('Error collecting instanced sims: {}'.format(e))

        # Limit to agent_seats
        max_seats = get_agent_seats()
        for sim_info in target_sims[:max_seats]:
            delta = _collect_sim_delta(sim_info)
            if delta is not None:
                sims_delta.append(delta)

        # Diagnostic heartbeat (BUG-02 visibility): report the conversation
        # signal and room-id coverage so a session log reveals whether the
        # social layer has anything to work with.
        conversing = [d for d in sims_delta if d.get('is_conversing')]
        with_room = [d for d in sims_delta if d.get('room_id') not in (None, 0)]
        worker_log_info(
            'delta: {} sims, {} conversing, {} room_id, {} sleeping, {} activity-idle'.format(
                len(sims_delta), len(conversing), len(with_room),
                sum(1 for d in sims_delta if d.get('is_sleeping')),
                sum(1 for d in sims_delta if str(d.get('activity') or '').lower() == 'idle'),
            )
        )

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
                    'household_id': _coerce_int(_safe_getattr(household, 'id', 0)),
                    'name': str(_safe_getattr(household, 'name', '') or ''),
                    'home_zone_id': _coerce_int(_safe_getattr(household, 'home_zone_id', 0)),
                    'funds': _coerce_int(_safe_getattr(household, 'funds', 0))
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


#: Compatible-mod signatures (plan task 2.7 / FC5): a lowercase folder/filename
#: fragment that identifies a well-known mod, mapped to the display label.
_COMPAT_MOD_SIGNATURES = {
    'MCCC': ('mc_cmd_center', 'mccc', 'mc_'),
    'WickedWhims': ('wickedwhims',),
    'Basemental': ('basemental',),
    'SliceOfLife': ('sliceoflife', 'slice_of_life'),
}
_detected_mods_cache = None


def _resolve_mods_folder():
    """Best-effort resolve of the user's Mods folder (plan 2.7 / FC5).

    Tries, in order: a walk-up from this module's own ``__file__`` (a
    ``.ts4script`` is loaded from inside ``<user>/Mods``), S4CL's path utility,
    and the game's ``paths`` module. Every strategy is guarded; returns None if
    nothing resolves so the caller degrades to an empty scan.
    """
    import os

    # 1. Walk up from this loaded module, e.g.
    #    <user>/Mods/Sensewright.ts4script/sensewright_mod/state_collector.py.
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        parts = here.replace('/', os.sep).split(os.sep)
        for index in range(len(parts) - 1, -1, -1):
            if parts[index].lower() == 'mods':
                candidate = os.sep.join(parts[:index + 1])
                if os.path.isdir(candidate):
                    return candidate
    except Exception:
        pass

    # 2. S4CL path utility (method name varies by build; guarded).
    s4cl_candidates = (
        ('sims4communitylib.utils.common_path_utils', 'CommonPathUtils',
         ('get_mods_folder', 'get_mods_folder_path')),
    )
    for module_name, class_name, method_names in s4cl_candidates:
        try:
            module = __import__(module_name, fromlist=[class_name])
            cls = _safe_getattr(module, class_name, None)
            for method_name in method_names:
                method = _safe_getattr(cls, method_name, None)
                if callable(method):
                    path = _safe_call(method)
                    if path and os.path.isdir(path):
                        return path
        except Exception:
            continue

    # 3. Game ``paths`` module(s).
    for module_name in ('paths', 'sims4.paths'):
        try:
            module = __import__(module_name, fromlist=['MODS_FOLDER'])
            path = _safe_getattr(module, 'MODS_FOLDER', None)
            if path and os.path.isdir(path):
                return path
        except Exception:
            continue
    return None


def _detect_compatible_mods():
    """Best-effort scan of the Mods folder for known mods (2.7). Cached per session."""
    global _detected_mods_cache
    if _detected_mods_cache is not None:
        return _detected_mods_cache
    detected = []
    try:
        import os
        mods_dir = _resolve_mods_folder()
        if mods_dir and os.path.isdir(mods_dir):
            names = [str(n).lower() for n in os.listdir(mods_dir)]
            for label, needles in _COMPAT_MOD_SIGNATURES.items():
                if any(any(needle in name for name in names) for needle in needles):
                    detected.append(label)
    except Exception as e:
        log_exception('Compatibility scan failed: {}'.format(e))
    _detected_mods_cache = detected
    return detected


def get_current_game_state():
    """Get current game state for autonomy tick."""
    return {
        'world_sim_tick': _get_world_sim_tick(),
        'clock_speed': _get_clock_speed(),
        'active_sim_id': _get_active_sim_id(),
        'player_confidant_sim_id': _get_player_confidant_sim_id(),
        'zone_id': _get_zone_id(),
        'save_id': _get_save_slot_guid(),
        'installed_packs': _get_installed_packs(),
        'detected_mods': _detect_compatible_mods()
    }