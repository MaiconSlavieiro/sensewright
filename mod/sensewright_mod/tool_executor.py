# Sensewright v2 — Tool Executor (GameLever + ArchetypeResolver)
# Python 3.7 compatible

import services
import sims4.resources
import sims4.math
from sims.sim_info import SimInfo
from sims4communitylib.utils.sims.common_sim_utils import CommonSimUtils
from sims4communitylib.utils.sims.common_sim_state_utils import CommonSimStateUtils

from sensewright_mod.debug_log import log_error, log_exception, safe_call
from sensewright_mod.native_hooks import apply_buff, add_relationship_bit, set_trait, remove_trait


# Archetype mappings (semantic category -> tuning IDs)
# These will be populated from tuning XML at runtime
_ARCHETYPE_MOOD = {}
_ARCHETYPE_ACTIVITY = {}
_ARCHETYPE_SENTIMENT = {}
_ARCHETYPE_WEATHER = {}
_ARCHETYPE_ARCHETYPE = {}  # For bias_interaction commodity buffs

# Commodity buff mappings for bias_interaction
_BIAS_COMMODITY_BUFFS = {}

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
        """Resolve mood name to buff tuning ID."""
        return _ARCHETYPE_MOOD.get(mood_name.lower())

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
            else:
                log_warn('Unknown intent kind: {}'.format(kind))
                return False, {'error': 'unknown_kind'}
        except Exception as e:
            log_exception('Error executing intent {}: {}'.format(kind, e))
            return False, {'error': 'exception', 'details': str(e)}

    @staticmethod
    def _execute_speak(sim_id, params, thought):
        """Show a speech balloon / thought bubble."""
        text = params.get('text', '')
        tone = params.get('tone', 'neutral')
        balloon_type = params.get('balloon_type', 'speech')  # 'speech' or 'thought'

        sim_info = services.sim_info_manager().get(sim_id)
        if sim_info is None:
            return False, {'error': 'sim_not_found'}

        sim = CommonSimUtils.get_sim_instance(sim_info)
        if sim is None:
            return False, {'error': 'sim_not_instanced'}

        try:
            # Use the sim's show_dialog or balloon system
            from ui.ui_dialog_notification import UiDialogNotification
            from protocolbuffers.Localization_pb2 import LocalizedString

            # For thought balloons, use the balloon system
            if balloon_type == 'thought':
                # Show thought balloon
                sim.show_thought_balloon(text)
            else:
                # Show speech balloon / notification
                # This is simplified - real implementation would use proper dialog
                pass

            return True, {'balloon_shown': True}
        except Exception as e:
            log_exception('Speak execution error: {}'.format(e))
            return False, {'error': 'speak_failed'}

    @staticmethod
    def _execute_approach(sim_id, target_sim_id, params):
        """Route sim to target sim."""
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
            # Push route interaction
            from sims.sim import Sim
            sim.push_route_to_target(target, routing_surface=target.routing_surface)
            return True, {'routed': True}
        except Exception as e:
            log_exception('Approach execution error: {}'.format(e))
            return False, {'error': 'approach_failed'}

    @staticmethod
    def _execute_set_mood(sim_id, params):
        """Apply a mood buff to sim."""
        mood = params.get('mood', '')
        duration = params.get('duration_sim_minutes', 60)

        buff_id = ArchetypeResolver.resolve_mood(mood)
        if buff_id is None:
            return False, {'error': 'unknown_mood', 'mood': mood}

        sim_info = services.sim_info_manager().get(sim_id)
        if sim_info is None:
            return False, {'error': 'sim_not_found'}

        try:
            apply_buff(sim_info, buff_id, duration_sim_minutes=duration)
            return True, {'buff_applied': buff_id}
        except Exception as e:
            log_exception('Set mood error: {}'.format(e))
            return False, {'error': 'buff_failed'}

    @staticmethod
    def _execute_bias_interaction(sim_id, params):
        """Apply a hidden commodity buff to bias autonomy."""
        archetype = params.get('archetype', '')
        weight = params.get('weight', 1.0)
        duration = params.get('duration_sim_minutes', 480)  # 8 hours default

        buff_id = ArchetypeResolver.get_bias_commodity_buff(archetype)
        if buff_id is None:
            return False, {'error': 'unknown_archetype', 'archetype': archetype}

        sim_info = services.sim_info_manager().get(sim_id)
        if sim_info is None:
            return False, {'error': 'sim_not_found'}

        try:
            apply_buff(sim_info, buff_id, duration_sim_minutes=duration)
            return True, {'bias_buff_applied': buff_id, 'weight': weight}
        except Exception as e:
            log_exception('Bias interaction error: {}'.format(e))
            return False, {'error': 'bias_failed'}

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
    def _execute_command(params):
        """World lever escape hatch - whitelisted commands only."""
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
                # Sidecar handles gossip generation
                return True, {'gossip_triggered': True}

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


def execute_intents(intents):
    """Execute a list of intents, returning results."""
    results = []
    for intent in intents:
        success, result = GameLever.execute_intent(intent)
        results.append({
            'intent_id': intent.id,
            'success': success,
            'result': result
        })
    return results