# Sensewright v2 — HTTP Client (Worker Thread)
# Python 3.7 compatible

import json
import queue
import threading
import time
import urllib.request
import urllib.error
import subprocess
import sys
import os
import traceback

from sensewright_mod.config import (
    get_sidecar_api_url, get_sidecar_health_url, get_request_timeout,
    get_health_timeout, get_sidecar_url
)
from sensewright_mod.debug_log import (
    worker_log_info, worker_log_warn, worker_log_error, worker_log_exception,
    init_worker_logger
)


# Global queues for inter-thread communication
_outbound_queue = queue.Queue()      # Main thread -> Worker thread (requests)
_inbound_intents_queue = queue.Queue()  # Worker thread -> Main thread (intents/responses)

_worker_thread = None
_worker_running = False
_sidecar_process = None
_game_pid = None
_shutdown_event = threading.Event()

# Trace ID counter
_trace_counter = 0
_trace_lock = threading.Lock()


def generate_trace_id():
    """Generate an 8-char hex trace ID."""
    global _trace_counter
    with _trace_lock:
        _trace_counter = (_trace_counter + 1) & 0xFFFFFFFF
        return 'tr_{:08x}'.format(_trace_counter)


def get_outbound_queue():
    return _outbound_queue


def get_inbound_intents_queue():
    return _inbound_intents_queue


def _read_python_txt():
    """Read the sidecar Python executable from sidecar/python.txt."""
    try:
        # The sidecar lives next to the .ts4script (sibling of the installed
        # mod folder), matching the i18n bundle resolution convention: three
        # dirname hops from __file__ reach the real Mods\Sensewright folder.
        mod_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        python_txt = os.path.join(mod_root, 'sidecar', 'python.txt')
        if os.path.exists(python_txt):
            with open(python_txt, 'r', encoding='utf-8') as f:
                line = f.readline().strip()
                if line:
                    return line
    except Exception:
        pass
    # Fallback: try common Python 3.12+ names
    return 'python3.12'


def _start_sidecar_process():
    """Start the sidecar process via subprocess.Popen with CREATE_NO_WINDOW."""
    global _sidecar_process
    if _sidecar_process is not None:
        try:
            if _sidecar_process.poll() is None:
                return True
        except Exception:
            pass

    python_exe = _read_python_txt()
    mod_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sidecar_dir = os.path.join(mod_root, 'sidecar')
    sidecar_main = os.path.join(sidecar_dir, 'main.py')

    if not os.path.exists(sidecar_main):
        worker_log_warn('Sidecar main.py not found at: {}'.format(sidecar_main))
        return False

    try:
        # Windows: CREATE_NO_WINDOW = 0x08000000
        creation_flags = 0
        if sys.platform == 'win32':
            creation_flags = 0x08000000

        # Bind the sidecar lifetime to the game: the PID is passed at launch so
        # the sidecar watchdog can shut it down when the game exits, even if the
        # /lifecycle/attach request never lands.
        game_pid = str(os.getpid())
        env = dict(os.environ)
        env['SENSEWRIGHT_GAME_PID'] = game_pid

        _sidecar_process = subprocess.Popen(
            [python_exe, 'main.py', '--game-pid', game_pid],
            cwd=sidecar_dir,
            creationflags=creation_flags,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL
        )
        worker_log_info('Started sidecar process (PID: {})'.format(_sidecar_process.pid))
        return True
    except Exception as e:
        worker_log_error('Failed to start sidecar: {}'.format(e))
        _sidecar_process = None
        return False


def _probe_sidecar_health():
    """Probe sidecar health endpoint with short timeout."""
    url = get_sidecar_health_url()
    timeout = get_health_timeout()
    try:
        req = urllib.request.Request(url, method='GET')
        response = urllib.request.urlopen(req, timeout=timeout)
        if response.getcode() == 200:
            data = json.loads(response.read().decode('utf-8'))
            return data.get('status') == 'ok'
    except Exception:
        pass
    return False


def _ensure_sidecar_running():
    """Ensure sidecar is running, auto-boot if needed."""
    if _probe_sidecar_health():
        return True

    worker_log_info('Sidecar not responding, attempting autoboot...')
    if _start_sidecar_process():
        # Wait a bit for sidecar to start
        for _ in range(10):
            time.sleep(0.5)
            if _probe_sidecar_health():
                worker_log_info('Sidecar autoboot successful')
                return True
        worker_log_warn('Sidecar started but health check still failing')
    else:
        worker_log_warn('Sidecar autoboot failed, running in degraded mode')
    return False


def _make_request(method, endpoint, payload=None, timeout=None):
    """Make an HTTP request to the sidecar."""
    url = get_sidecar_api_url(endpoint)
    if timeout is None:
        timeout = get_request_timeout()

    headers = {'Content-Type': 'application/json'}
    data = None
    if payload is not None:
        # default=str keeps game objects (e.g. FamilyFunds) from aborting a
        # request with a non-serializable payload.
        data = json.dumps(payload, default=str).encode('utf-8')

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        response = urllib.request.urlopen(req, timeout=timeout)
        resp_data = response.read().decode('utf-8')
        if resp_data:
            return json.loads(resp_data)
        return {'ok': True}
    except urllib.error.HTTPError as e:
        worker_log_error('HTTP error {} for {}: {}'.format(e.code, endpoint, e.read().decode('utf-8', errors='ignore')))
        return {'ok': False, 'error': 'http_{}'.format(e.code)}
    except urllib.error.URLError as e:
        worker_log_error('URL error for {}: {}'.format(endpoint, e))
        return {'ok': False, 'error': 'url_error'}
    except Exception as e:
        worker_log_exception('Request exception for {}: {}'.format(endpoint, e))
        return {'ok': False, 'error': 'exception'}


def _worker_loop():
    """Main worker thread loop."""
    global _worker_running
    worker_log_info('Worker thread started')

    # Initialize worker logger
    init_worker_logger()

    # Ensure sidecar is running
    _ensure_sidecar_running()

    # Attach to game process
    global _game_pid
    _game_pid = os.getpid()
    _make_request('POST', '/lifecycle/attach', {'game_pid': _game_pid})

    while _worker_running and not _shutdown_event.is_set():
        try:
            # Process outbound queue (non-blocking)
            try:
                request = _outbound_queue.get_nowait()
                _process_outbound_request(request)
            except queue.Empty:
                pass

            # Small sleep to prevent busy-waiting
            time.sleep(0.01)

        except Exception as e:
            worker_log_exception('Worker loop error: {}'.format(e))
            time.sleep(0.1)

    worker_log_info('Worker thread stopped')


def _process_outbound_request(request):
    """Process a single outbound request from the main thread."""
    try:
        method = request.get('method', 'POST')
        endpoint = request.get('endpoint', '')
        payload = request.get('payload', {})
        callback = request.get('callback', None)
        trace_id = request.get('trace_id', generate_trace_id())

        # Add trace_id to payload if not present
        if isinstance(payload, dict) and 'trace_id' not in payload:
            payload['trace_id'] = trace_id

        response = _make_request(method, endpoint, payload)

        # Put response in inbound queue for main thread
        if callback is not None:
            _inbound_intents_queue.put({
                'type': 'response',
                'trace_id': trace_id,
                'endpoint': endpoint,
                'response': response,
                'callback': callback
            })
        else:
            _inbound_intents_queue.put({
                'type': 'response',
                'trace_id': trace_id,
                'endpoint': endpoint,
                'response': response
            })

    except Exception as e:
        worker_log_exception('Failed to process outbound request: {}'.format(e))


def start_worker():
    """Start the worker thread."""
    global _worker_thread, _worker_running
    if _worker_running:
        return

    _worker_running = True
    _shutdown_event.clear()
    _worker_thread = threading.Thread(target=_worker_loop, name='SensewrightWorker', daemon=True)
    _worker_thread.start()


def stop_worker():
    """Stop the worker thread."""
    global _worker_running, _worker_thread, _sidecar_process
    _worker_running = False
    _shutdown_event.set()

    if _worker_thread is not None:
        _worker_thread.join(timeout=2.0)
        _worker_thread = None

    # Terminate sidecar process if we started it
    if _sidecar_process is not None:
        try:
            _sidecar_process.terminate()
            _sidecar_process.wait(timeout=2.0)
        except Exception:
            try:
                _sidecar_process.kill()
            except Exception:
                pass
        _sidecar_process = None


def post_async(endpoint, payload, callback=None):
    """Queue a POST request to be sent by the worker thread."""
    trace_id = generate_trace_id()
    _outbound_queue.put({
        'method': 'POST',
        'endpoint': endpoint,
        'payload': payload,
        'callback': callback,
        'trace_id': trace_id
    })
    return trace_id


def get_async(endpoint, callback=None):
    """Queue a GET request to be sent by the worker thread."""
    trace_id = generate_trace_id()
    _outbound_queue.put({
        'method': 'GET',
        'endpoint': endpoint,
        'payload': {},
        'callback': callback,
        'trace_id': trace_id
    })
    return trace_id


def process_inbound_queue():
    """Process inbound responses/intents on the main thread. Call from GAME_TICK."""
    processed = 0
    while processed < 50:  # Limit per tick to avoid frame hitch
        try:
            item = _inbound_intents_queue.get_nowait()
            _handle_inbound_item(item)
            processed += 1
        except queue.Empty:
            break
    return processed


def _queue_response_intents(response):
    """Add any intents carried by a sidecar response to the intent bus."""
    if not isinstance(response, dict):
        return
    intents = response.get('intents')
    if not intents:
        return
    try:
        from sensewright_mod.intent_bus import get_intent_bus
        get_intent_bus().add_intents(intents)
        worker_log_info('queued {} intent(s) from sidecar: {}'.format(
            len(intents), [i.get('kind') for i in intents if isinstance(i, dict)]))
    except Exception as e:
        from sensewright_mod.debug_log import log_exception
        log_exception('Failed to queue response intents: {}'.format(e))


def _handle_inbound_item(item):
    """Handle an inbound item (response or intents)."""
    try:
        item_type = item.get('type')
        if item_type == 'response':
            response = item.get('response')
            callback = item.get('callback')
            if callback is not None:
                try:
                    callback(response, item.get('trace_id'))
                except Exception as e:
                    from sensewright_mod.debug_log import log_exception
                    log_exception('Callback error: {}'.format(e))
            else:
                # Responses without a callback (e.g. /autonomy/tick) can carry
                # intents the sidecar wants applied on the main thread.
                _queue_response_intents(response)
        elif item_type == 'intents':
            _queue_response_intents(item)
    except Exception as e:
        from sensewright_mod.debug_log import log_exception
        log_exception('Inbound item handling error: {}'.format(e))


# Convenience functions for specific endpoints
def post_lifecycle_attach():
    return post_async('/lifecycle/attach', {'game_pid': os.getpid()})


def post_lifecycle_session_start(player_id, save_id, world_sim_tick, lang):
    return post_async('/lifecycle/session-start', {
        'player_id': player_id,
        'save_id': save_id,
        'world_sim_tick': world_sim_tick,
        'lang': lang
    })


def post_lifecycle_zone_transition(player_id, save_id, new_zone_id, world_sim_tick):
    return post_async('/lifecycle/zone-transition', {
        'player_id': player_id,
        'save_id': save_id,
        'new_zone_id': new_zone_id,
        'world_sim_tick': world_sim_tick
    })


def post_lifecycle_save(player_id, save_id, previous_save_id, world_sim_tick):
    payload = {
        'player_id': player_id,
        'save_id': save_id,
        'world_sim_tick': world_sim_tick
    }
    if previous_save_id:
        payload['previous_save_id'] = previous_save_id
    return post_async('/lifecycle/save', payload)


def post_census(player_id, save_id, world_sim_tick, sims, households, relationships, installed_packs):
    return post_async('/census', {
        'player_id': player_id,
        'save_id': save_id,
        'world_sim_tick': world_sim_tick,
        'sims': sims,
        'households': households,
        'relationships': relationships,
        'installed_packs': installed_packs
    })


def post_autonomy_tick(trace_id, player_id, save_id, world_sim_tick, clock_speed,
                       active_sim_id, player_confidant_sim_id, sims_delta, lang):
    return post_async('/autonomy/tick', {
        'trace_id': trace_id,
        'player_id': player_id,
        'save_id': save_id,
        'world_sim_tick': world_sim_tick,
        'clock_speed': clock_speed,
        'active_sim_id': active_sim_id,
        'player_confidant_sim_id': player_confidant_sim_id,
        'sims_delta': sims_delta,
        'lang': lang
    })


def post_chat(trace_id, sim_id, channel, player_id, save_id, world_sim_tick, message, lang, callback=None):
    return post_async('/chat', {
        'trace_id': trace_id,
        'sim_id': sim_id,
        'channel': channel,
        'player_id': player_id,
        'save_id': save_id,
        'world_sim_tick': world_sim_tick,
        'message': message,
        'lang': lang
    }, callback=callback)


def post_hey(trace_id, sim_id, player_id, save_id, world_sim_tick, message, lang, callback=None):
    return post_async('/hey', {
        'trace_id': trace_id,
        'sim_id': sim_id,
        'player_id': player_id,
        'save_id': save_id,
        'world_sim_tick': world_sim_tick,
        'message': message,
        'lang': lang
    }, callback=callback)


def post_events(trace_id, sim_id, player_id, save_id, world_sim_tick,
                event_category, content, impact, witnesses, lang, target_sim_id=None):
    payload = {
        'trace_id': trace_id,
        'sim_id': sim_id,
        'player_id': player_id,
        'save_id': save_id,
        'world_sim_tick': world_sim_tick,
        'event_category': event_category,
        'content': content,
        'impact': impact,
        'witnesses': witnesses,
        'lang': lang
    }
    if target_sim_id is not None:
        payload['target_sim_id'] = target_sim_id
    return post_async('/events', payload)


def post_player_activity(player_id, save_id, idle, clock_speed):
    return post_async('/config/player-activity', {
        'player_id': player_id,
        'save_id': save_id,
        'idle': idle,
        'clock_speed': clock_speed
    })