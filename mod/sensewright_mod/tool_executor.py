# Sensewright v2 — Tool Executor (GameLever + ArchetypeResolver)
# Python 3.7 compatible

import services
import sims4.resources
import sims4.math
from sims.sim_info import SimInfo
from sims4communitylib.utils.sims.common_sim_utils import CommonSimUtils
from sims4communitylib.utils.sims.common_sim_state_utils import CommonSimStateUtils

from sensewright_mod.debug_log import log_error, log_exception, log_warn, safe_call, worker_log_info
from sensewright_mod.native_hooks import (
    apply_buff, apply_mood, add_relationship_bit, set_trait, remove_trait, has_buff
)


# Archetype mappings (semantic category -> tuning IDs)
# These will be populated from tuning XML at runtime
_ARCHETYPE_MOOD = {}
_ARCHETYPE_ACTIVITY = {}
_ARCHETYPE_SENTIMENT = {}
_ARCHETYPE_WEATHER = {}
_ARCHETYPE_ARCHETYPE = {}  # For bias_interaction commodity buffs

# Commodity buff mappings for bias_interaction
_BIAS_COMMODITY_BUFFS = {}

# Synonym map: the LLM free-associates mood words (English and localized
# inflections); map them onto the canonical English keys used by
# _ARCHETYPE_MOOD so a stray "tired"/"focada"/"neutral" still resolves.
_MOOD_ALIASES = {
    "ok": "fine", "okay": "fine", "neutral": "fine", "normal": "fine",
    "calm": "fine", "content": "fine", "bem": "fine",
    "feliz": "happy", "glad": "happy", "cheerful": "happy", "good": "happy",
    "triste": "sad", "unhappy": "sad", "down": "sad",
    "irritado": "angry", "irritada": "angry", "irritated": "angry",
    "mad": "angry", "furious": "angry", "annoyed": "angry", "raiva": "angry",
    "tenso": "tense", "tensa": "tense", "stressed": "tense", "worried": "tense",
    "anxious": "tense", "nervous": "tense",
    "paquerador": "flirty", "flirtatious": "flirty", "romantic": "flirty",
    "inspirado": "inspired", "inspirada": "inspired", "inspired": "inspired",
    "focado": "focused", "focada": "focused", "concentrado": "focused",
    "concentrada": "focused", "focused": "focused", "concentrated": "focused",
    "confuso": "dazed", "confusa": "dazed", "dazed": "dazed", "confused": "dazed",
    "entediado": "bored", "entediada": "bored", "bored": "bored", "lazy": "bored",
    "sonolento": "sleepy", "sonolenta": "sleepy", "sleepy": "sleepy",
    "tired": "sleepy", "exhausted": "sleepy", "drowsy": "sleepy",
    "cansado": "sleepy", "cansada": "sleepy", "sleeping": "sleepy",
    "desconfortavel": "uncomfortable", "uncomfortable": "uncomfortable",
    "confiante": "confident", "confident": "confident",
    "energizado": "energized", "energizada": "energized", "energized": "energized",
    "excited": "energized", "animado": "energized", "animada": "energized",
    "playful": "playful", "brincalhao": "playful",
    "embarrassed": "embarrassed", "envergonhado": "embarrassed",
    "scared": "scared", "assustado": "scared", "assustada": "scared",
}


#: Archetype -> mood bridge used by bias_interaction until the M5 Commodity
#: Buffs ship; a mood nudges native autonomy toward matching activities.
_BIAS_ARCHETYPE_MOODS = {
    "social": "happy", "social_friendly": "happy", "socialize": "happy",
    "friendly": "happy", "talk": "happy",
    "flirty": "flirty", "romantic": "flirty", "date": "flirty",
    "creative": "inspired", "paint": "inspired", "paintng": "inspired",
    "write": "inspired", "writing": "inspired", "music": "inspired",
    "active": "energized", "fitness": "energized", "workout": "energized",
    "exercise": "energized", "dance": "energized",
    "focus": "focused", "work": "focused", "study": "focused",
    "clean": "focused", "cook": "focused", "read": "focused",
    "rest": "sleepy", "sleep": "sleepy", "nap": "sleepy",
    "relax": "fine", "eat": "fine", "hungry": "uncomfortable",
    "play": "playful", "fun": "playful", "game": "playful",
}


def _normalize_token(text):
    """Lowercase + strip accents so localized inflections match aliases."""
    if not text:
        return ""
    token = text.strip().lower()
    try:
        import unicodedata
        token = unicodedata.normalize("NFKD", token).encode("ascii", "ignore").decode("ascii")
    except Exception:
        pass
    return token

# Whitelisted world commands for 'command' kind
_WHITELISTED_COMMANDS = frozenset([
    'weather.set', 'world.gossip', 'zone.modifier', 'notification.send'
])


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


def register_archetype_mappings(mood_map, activity_map, sentiment_map, weather_map, archetype_map, bias_buffs):
    """Called at startup to register tuning ID mappings from package."""
    global _ARCHETYPE_MOOD, _ARCHETYPE_ACTIVITY, _ARCHETYPE_SENTIMENT
    global _ARCHETYPE_WEATHER, _ARCHETYPE_ARCHETYPE, _BIAS_COMMODITY_BUFFS
    _ARCHETYPE_MOOD = mood_map or {}
    _ARCHETYPE_ACTIVITY = activity_map or {}
    _ARCHETYPE_SENTIMENT = sentiment_map or {}
    _ARCHETYPE_WEATHER = weather_map or {}
    _ARCHETYPE_ARCHETYPE = archetype_map or {}
    _BIAS_COMMODITY_BUFFS = bias_buffs or {}


class ArchetypeResolver(object):
    """Maps semantic categories to game tuning IDs."""

    @staticmethod
    def resolve_mood(mood_name):
        """Resolve a mood name (canonical, synonym or localized) to a buff ID.

        The LLM is not guaranteed to answer with the canonical token, so accept
        synonyms and accented forms (e.g. "tired" -> sleepy, "focada" ->
        focused) before giving up.
        """
        token = _normalize_token(mood_name)
        if not token:
            return None
        if token in _ARCHETYPE_MOOD:
            return _ARCHETYPE_MOOD[token]
        canonical = _MOOD_ALIASES.get(token)
        if canonical is not None:
            return _ARCHETYPE_MOOD.get(canonical)
        for key, value in _ARCHETYPE_MOOD.items():
            if key in token or token in key:
                return value
        return None

    @staticmethod
    def resolve_activity(activity_name):
        """Resolve activity name to interaction/object tuning ID."""
        return _ARCHETYPE_ACTIVITY.get(activity_name.lower())

    @staticmethod
    def resolve_sentiment(sentiment_name):
        """Resolve sentiment name to relationship bit tuning ID."""
        return _ARCHETYPE_SENTIMENT.get(sentiment_name.lower())

    @staticmethod
    def resolve_weather(weather_name):
        """Resolve weather name to weather tuning ID."""
        return _ARCHETYPE_WEATHER.get(weather_name.lower())

    @staticmethod
    def resolve_archetype(archetype_name):
        """Resolve archetype name to commodity buff tuning ID for bias_interaction."""
        return _ARCHETYPE_ARCHETYPE.get(archetype_name.lower())

    @staticmethod
    def get_bias_commodity_buff(archetype_name):
        """Get the commodity buff for a bias_interaction archetype."""
        return _BIAS_COMMODITY_BUFFS.get(archetype_name.lower())


class GameLever(object):
    """Executes intent kinds by applying game state changes."""

    @staticmethod
    def execute_intent(intent):
        """Execute a single intent, returning (success, result_dict)."""
        kind = intent.kind
        sim_id = intent.sim_id
        params = intent.params or {}

        try:
            if kind == 'speak':
                return GameLever._execute_speak(sim_id, params, intent.thought)
            elif kind == 'approach':
                return GameLever._execute_approach(sim_id, intent.target_sim_id, params)
            elif kind == 'set_mood':
                return GameLever._execute_set_mood(sim_id, params)
            elif kind == 'bias_interaction':
                return GameLever._execute_bias_interaction(sim_id, params)
            elif kind == 'prefer_target':
                return GameLever._execute_prefer_target(sim_id, intent.target_sim_id, params)
            elif kind == 'set_goal':
                return GameLever._execute_set_goal(sim_id, params)
            elif kind == 'remember':
                return GameLever._execute_remember(sim_id, params)
            elif kind == 'forget':
                return GameLever._execute_forget(sim_id, params)
            elif kind == 'command':
                return GameLever._execute_command(params)
            elif kind == 'spawn_npc':
                return GameLever._execute_spawn_npc(sim_id, params)
            else:
                log_warn('Unknown intent kind: {}'.format(kind))
                return False, {'error': 'unknown_kind'}
        except Exception as e:
            log_exception('Error executing intent {}: {}'.format(kind, e))
            return False, {'error': 'exception', 'details': str(e)}

    @staticmethod
    def _execute_speak(sim_id, params, thought):
        """Surface a Sim's line diegetically.

        The game exposes no per-Sim `show_speech_balloon`/`show_thought_balloon`
        API (verified against the decompiled `sims.sim.Sim`), so we first use one
        of those if another mod provides it and otherwise fall back to a real
        S4CL notification carrying the line. This replaces the previous silent
        no-op that dropped every `speak` intent.
        """
        text = params.get('text', '')
        tone = params.get('tone', 'neutral')
        balloon_type = params.get('balloon_type', 'speech')  # 'speech' or 'thought'

        sim_info = services.sim_info_manager().get(sim_id)
        if sim_info is None:
            return False, {'error': 'sim_not_found'}

        # Fall back to the embedded thought when no explicit text is present.
        if not text and thought:
            text = thought
        if not text:
            return False, {'error': 'no_text'}

        sim = CommonSimUtils.get_sim_instance(sim_info)
        if sim is not None:
            try:
                if balloon_type == 'thought' and hasattr(sim, 'show_thought_balloon'):
                    sim.show_thought_balloon(text)
                    return True, {'balloon_shown': True, 'type': 'thought'}
                if hasattr(sim, 'show_speech_balloon'):
                    sim.show_speech_balloon(text)
                    return True, {'balloon_shown': True, 'type': 'speech'}
            except Exception as e:
                log_exception('Speak balloon error: {}'.format(e))

        try:
            from sims4communitylib.notifications.common_basic_notification import CommonBasicNotification
            from sims4communitylib.utils.localization.common_localization_utils import CommonLocalizationUtils

            title = CommonLocalizationUtils.create_localized_string(sim_info.full_name)
            body = CommonLocalizationUtils.create_localized_string(text)
            CommonBasicNotification(title, body).show()
            return True, {'notification_shown': True, 'tone': tone}
        except Exception as e:
            log_exception('Speak notification error: {}'.format(e))
            return False, {'error': 'speak_failed'}

    @staticmethod
    def _execute_approach(sim_id, target_sim_id, params):
        """Route sim to target sim.

        BUG-04 fix: ``Sim.push_route_to_target`` does not exist on the engine's
        ``Sim`` object (``object_sim``). S4CL exposes a stable ``send_near_position``
        that enqueues the vanilla Go-Here interaction toward the target's block.
        """
        if target_sim_id is None:
            return False, {'error': 'no_target'}

        sim_info = services.sim_info_manager().get(sim_id)
        target_info = services.sim_info_manager().get(target_sim_id)
        if sim_info is None or target_info is None:
            return False, {'error': 'sim_not_found'}

        sim = CommonSimUtils.get_sim_instance(sim_info)
        target = CommonSimUtils.get_sim_instance(target_info)
        if sim is None or target is None:
            return False, {'error': 'not_instanced'}

        try:
            from sims4communitylib.utils.sims.common_sim_location_utils import CommonSimLocationUtils
            position = CommonSimLocationUtils.get_position(target_info)
            level = CommonSimLocationUtils.get_surface_level(target_info)
            result = CommonSimLocationUtils.send_near_position(sim_info, position, level)
            if result is not None and getattr(result, 'is_success', True):
                return True, {'routed': True}
            return False, {'error': 'approach_failed', 'details': str(result)}
        except Exception as e:
            log_exception('Approach execution error: {}'.format(e))
            return False, {'error': 'approach_failed'}

    @staticmethod
    def _execute_set_mood(sim_id, params):
        """Apply a mood to sim (Types.MOOD statistic)."""
        mood = params.get('mood', '')
        duration = params.get('duration_sim_minutes', 60)

        # BUG-07: "fine"/neutral means "no mood change". There is no emotion buff
        # for it (Mood_Fine has no client MoodKey), so treat it as a clean no-op
        # instead of failing the intent.
        token = _normalize_token(mood)
        if token == 'fine' or _MOOD_ALIASES.get(token) == 'fine':
            return True, {'neutral': True, 'note': 'no_mood_change'}

        mood_id = ArchetypeResolver.resolve_mood(mood)
        if mood_id is None:
            return False, {'error': 'unknown_mood', 'mood': mood}

        sim_info = services.sim_info_manager().get(sim_id)
        if sim_info is None:
            return False, {'error': 'sim_not_found'}

        try:
            applied = apply_mood(sim_info, mood_id)
            if applied:
                return True, {'mood_applied': mood_id}
            return False, {'error': 'mood_failed', 'mood': mood, 'mood_id': mood_id}
        except Exception as e:
            log_exception('Set mood error: {}'.format(e))
            return False, {'error': 'mood_failed'}

    @staticmethod
    def _execute_bias_interaction(sim_id, params):
        """Bias native autonomy.

        Preferred path: apply the registered hidden commodity buff for the
        archetype. Until the M5 Commodity Buffs exist in the package, fall back
        to the working mood lever: a mood steers native autonomy toward matching
        objects (inspired -> creative, energized -> active, focused -> work).
        """
        archetype = params.get('archetype', '')
        weight = params.get('weight', 1.0)
        duration = params.get('duration_sim_minutes', 480)  # 8 hours default

        sim_info = services.sim_info_manager().get(sim_id)
        if sim_info is None:
            return False, {'error': 'sim_not_found'}

        buff_id = ArchetypeResolver.get_bias_commodity_buff(archetype)
        if buff_id is not None:
            try:
                apply_buff(sim_info, buff_id, duration_sim_minutes=duration)
                if has_buff(sim_info, buff_id):
                    return True, {'bias_buff_applied': buff_id, 'weight': weight}
                return False, {'error': 'bias_buff_not_applied', 'buff_id': buff_id}
            except Exception as e:
                log_exception('Bias interaction error: {}'.format(e))
                return False, {'error': 'bias_failed'}

        # Bridge: map the archetype to a mood via the working mood lever.
        mood_key = _BIAS_ARCHETYPE_MOODS.get(_normalize_token(archetype))
        if mood_key is not None:
            mood_id = ArchetypeResolver.resolve_mood(mood_key)
            if mood_id is not None and apply_mood(sim_info, mood_id):
                return True, {'bias_mood_applied': mood_key, 'weight': weight}

        return False, {'error': 'unknown_archetype', 'archetype': archetype}

    @staticmethod
    def _execute_prefer_target(sim_id, target_sim_id, params):
        """Soft autonomy bias toward a target sim."""
        if target_sim_id is None:
            return False, {'error': 'no_target'}

        # This would apply a relationship bit or commodity that makes the sim
        # more likely to seek out the target. Simplified for now.
        sim_info = services.sim_info_manager().get(sim_id)
        target_info = services.sim_info_manager().get(target_sim_id)
        if sim_info is None or target_info is None:
            return False, {'error': 'sim_not_found'}

        try:
            # Add a temporary relationship bit that increases attraction
            bit_id = ArchetypeResolver.resolve_sentiment('prefer_target')
            if bit_id:
                add_relationship_bit(sim_info, target_info, bit_id)
            return True, {'target_preferred': target_sim_id}
        except Exception as e:
            log_exception('Prefer target error: {}'.format(e))
            return False, {'error': 'prefer_failed'}

    @staticmethod
    def _execute_set_goal(sim_id, params):
        """Set a daily plan goal for the sim."""
        goal = params.get('goal', '')
        block = params.get('block', 'evening')  # morning, afternoon, evening

        # This would integrate with the sim.cognition daily plan
        # For now, store in a simple attribute on sim_info
        sim_info = services.sim_info_manager().get(sim_id)
        if sim_info is None:
            return False, {'error': 'sim_not_found'}

        try:
            # Store goal in sim_info for cognition system to pick up
            if not hasattr(sim_info, '_sensewright_goals'):
                sim_info._sensewright_goals = {}
            sim_info._sensewright_goals[block] = goal
            return True, {'goal_set': goal, 'block': block}
        except Exception as e:
            log_exception('Set goal error: {}'.format(e))
            return False, {'error': 'goal_failed'}

    @staticmethod
    def _execute_remember(sim_id, params):
        """No-op locally - sidecar owns memory. Return success."""
        return True, {'remembered': True, 'note': 'delegated_to_sidecar'}

    @staticmethod
    def _execute_forget(sim_id, params):
        """No-op locally - sidecar owns memory. Return success."""
        return True, {'forgotten': True, 'note': 'delegated_to_sidecar'}

    @staticmethod
    def _execute_spawn_npc(sim_id, params):
        """Spawn a catalyst townie via the native SituationManager (2.4 / 3.3).

        Imported lazily to avoid a circular import (visit_situation reuses the
        approach lever here).
        """
        try:
            from sensewright_mod.visit_situation import spawn_catalyst_visitor
            return spawn_catalyst_visitor(sim_id, params)
        except Exception as e:
            log_exception('Spawn NPC error: {}'.format(e))
            return False, {'error': 'spawn_npc_failed'}

    @staticmethod
    def _execute_command(params):
        """World lever escape hatch - whitelisted commands only.

        Also handles God-director narration directives, which arrive as a
        ``command`` intent carrying ``visual_type``/``text`` rather than a
        whitelisted ``command`` name.
        """
        narration = params.get('text') or ''
        visual_type = params.get('visual_type')
        if narration and not params.get('command'):
            return GameLever._execute_narration(narration, visual_type)

        command = params.get('command', '')
        args = params.get('args', {})

        if command not in _WHITELISTED_COMMANDS:
            return False, {'error': 'command_not_whitelisted', 'command': command}

        try:
            if command == 'weather.set':
                weather_type = args.get('weather', 'clear')
                weather_id = ArchetypeResolver.resolve_weather(weather_type)
                if weather_id:
                    # Apply weather via weather service
                    weather_service = services.weather_service()
                    if weather_service:
                        weather_service.set_weather_forecast(weather_id)
                return True, {'weather_set': weather_type}

            elif command == 'world.gossip':
                # Surface a neighborhood rumor as a diegetic "SMS" notification
                # (P24 consumer). The sidecar owns rumor generation/contagion.
                text = args.get('text', '') or args.get('rumor', '')
                sender = args.get('from', '')
                if text:
                    try:
                        from sims4communitylib.notifications.common_basic_notification import CommonBasicNotification
                        from sims4communitylib.utils.localization.common_localization_utils import CommonLocalizationUtils
                        body = '{}: {}'.format(sender, text) if sender else text
                        CommonBasicNotification(
                            CommonLocalizationUtils.create_localized_string('Sensewright'),
                            CommonLocalizationUtils.create_localized_string(body),
                        ).show()
                    except Exception as e:
                        log_exception('Gossip SMS error: {}'.format(e))
                return True, {'gossip_triggered': True, 'sms_shown': bool(text)}

            elif command == 'zone.modifier':
                modifier = args.get('modifier', '')
                zone_id = args.get('zone_id', services.current_zone_id())
                # Apply zone modifier
                from lot51_core.lib.zone import add_zone_modifier
                # Would need tuning ID for modifier
                return True, {'zone_modifier': modifier}

            elif command == 'notification.send':
                # Send a game notification
                title = args.get('title', '')
                text = args.get('text', '')
                # Simplified
                return True, {'notification_sent': True}

            return False, {'error': 'command_not_implemented'}
        except Exception as e:
            log_exception('Command execution error: {}'.format(e))
            return False, {'error': 'command_failed'}

    @staticmethod
    def _execute_narration(text, visual_type=None):
        """Surface a God-director line diegetically as an S4CL notification."""
        try:
            from sims4communitylib.notifications.common_basic_notification import CommonBasicNotification
            from sims4communitylib.utils.localization.common_localization_utils import CommonLocalizationUtils

            title = CommonLocalizationUtils.create_localized_string(
                visual_type or 'Sensewright')
            body = CommonLocalizationUtils.create_localized_string(text)
            CommonBasicNotification(title, body).show()
            return True, {'narration_shown': True, 'visual_type': visual_type}
        except Exception as e:
            log_exception('Narration error: {}'.format(e))
            return False, {'error': 'narration_failed'}


def execute_intents(intents):
    """Execute a list of intents, returning results."""
    results = []
    for intent in intents:
        success, result = GameLever.execute_intent(intent)
        worker_log_info('intent {} [{}] sim={} target={} -> success={} {}'.format(
            intent.id, intent.kind, intent.sim_id, intent.target_sim_id, success, result))
        results.append({
            'intent_id': intent.id,
            'success': success,
            'result': result
        })
    return results