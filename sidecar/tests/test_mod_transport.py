"""Exercise the real worker transport without importing the game runtime."""
import importlib.util
import socket
import sys
import types
from pathlib import Path

import pytest


@pytest.fixture
def client(monkeypatch):
    package = types.ModuleType('sensewright_mod')
    package.__path__ = []
    monkeypatch.setitem(sys.modules, 'sensewright_mod', package)
    for name, functions in {
        'config': ['get_sidecar_api_url', 'get_sidecar_health_url',
                   'get_request_timeout', 'get_health_timeout', 'get_sidecar_url'],
        'debug_log': ['worker_log_info', 'worker_log_warn', 'worker_log_error',
                      'worker_log_exception', 'init_worker_logger'],
    }.items():
        stub = types.ModuleType('sensewright_mod.' + name)
        for function in functions:
            setattr(stub, function, lambda *args: None)
        monkeypatch.setitem(sys.modules, stub.__name__, stub)
    path = Path(__file__).resolve().parents[2] / 'mod/sensewright_mod/http_client.py'
    spec = importlib.util.spec_from_file_location('transport_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_coalesced_ticks_preserve_action_history(client):
    first = {'intent_id': 'a', 'status': 'applied'}
    second = {'intent_id': 'b', 'status': 'failed'}
    for tick, outcomes in [(1, [first]), (2, [second]), (3, [])]:
        client.post_async('/autonomy/tick', {
            'world_sim_tick': tick, 'outcomes': outcomes,
            'sims_delta': [{'sim_id': 1, 'mood': str(tick)}],
        })
    payload = client._next_item()['payload']
    assert payload['outcomes'] == [first, second]
    assert payload['world_sim_tick'] == 3
    assert payload['sims_delta'] == [{'sim_id': 1, 'mood': '3'}]
    assert client._next_item() is None


def test_full_queue_evicts_event_for_save_without_reordering(client, monkeypatch):
    monkeypatch.setattr(client, '_REALTIME_MAX', 3)
    for endpoint in ['/chat', '/events', '/hey', '/lifecycle/save']:
        client.post_async(endpoint, {})
    assert [client._next_item()['endpoint'] for _ in range(3)] == [
        '/chat', '/hey', '/lifecycle/save']
    assert client._next_item() is None


@pytest.mark.parametrize('failure', ['eof', 'timeout', 'connect'])
def test_unhealthy_sse_falls_back_without_reconnect_spin(client, monkeypatch, failure):
    calls = []
    waits = []

    class EmptyStream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __iter__(self):
            if failure == 'timeout':
                raise socket.timeout()
            return iter([])

    def connect(*args, **kwargs):
        calls.append(kwargs['timeout'])
        assert len(calls) <= 2, 'Unhealthy streams must enter polling fallback'
        if failure == 'connect':
            raise OSError('offline')
        return EmptyStream()

    def poll():
        client._worker_running = False

    monkeypatch.setattr(client, 'get_sidecar_api_url', lambda endpoint: 'http://localhost' + endpoint)
    monkeypatch.setattr(client.urllib.request, 'urlopen', connect)
    monkeypatch.setattr(client._shutdown_event, 'wait', lambda seconds: waits.append(seconds))
    monkeypatch.setattr(client, '_maybe_intent_pull', poll)
    client._session_started[0] = True
    client._worker_running = True
    client._sse_stream_loop()
    assert calls == [15.0, 15.0]
    assert len(waits) >= 2


def test_http_response_is_closed(client, monkeypatch):
    class Response:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.closed = True

        def read(self):
            return b'{"ok": true}'

    response = Response()
    monkeypatch.setattr(client, 'get_sidecar_api_url', lambda endpoint: 'http://localhost' + endpoint)
    monkeypatch.setattr(client.urllib.request, 'urlopen', lambda *args, **kwargs: response)
    assert client._make_request('GET', '/status', timeout=1) == {'ok': True}
    assert response.closed
