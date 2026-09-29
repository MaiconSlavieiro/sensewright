"""
Tests for http_client module.
Run with system Python (3.10+).
"""

import sys
import os
import json
import urllib.error
import urllib.request
from unittest.mock import patch

# Add mod directory to path
mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

import pytest
from simssense_mod import http_client
from simssense_mod.http_client import SidecarUnreachable, SidecarError


class MockResponse:
    """Mock urllib response."""
    def __init__(self, data: dict, status: int = 200):
        self._data = json.dumps(data).encode("utf-8")
        self.status = status

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class MockURLError(urllib.error.URLError):
    pass


def test_post_json_success():
    """Test successful POST request."""
    mock_response = MockResponse({"reply": "Hello", "tool_calls": []})

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        result = http_client.post_json("/v1/test", {"key": "value"})

        assert result == {"reply": "Hello", "tool_calls": []}
        mock_urlopen.assert_called_once()

        # Check request was made with correct args
        call_args = mock_urlopen.call_args[0][0]
        assert call_args.get_method() == "POST"
        # Headers are case-insensitive in urllib, check case-insensitively
        headers_lower = {k.lower(): v for k, v in call_args.headers.items()}
        assert "content-type" in headers_lower
        assert headers_lower["content-type"] == "application/json"


def test_get_json_success():
    """Test successful GET request."""
    mock_response = MockResponse({"ok": True, "version": "0.1.0"})

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        result = http_client.get_json("/v1/health")

        assert result == {"ok": True, "version": "0.1.0"}
        mock_urlopen.assert_called_once()

        call_args = mock_urlopen.call_args[0][0]
        assert call_args.get_method() == "GET"


def test_sidecar_unreachable_on_connection_error():
    """Test SidecarUnreachable is raised on connection error."""
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        with pytest.raises(SidecarUnreachable):
            http_client.get_json("/v1/health")


def test_sidecar_error_on_http_error():
    """Test SidecarError is raised on HTTP error status."""
    # Create a mock HTTPError
    class MockHTTPError(urllib.error.HTTPError):
        def __init__(self, code, msg):
            self.code = code
            self.msg = msg
            self.headers = {}

        def read(self):
            return b'{"error": "bad request"}'

    with patch("urllib.request.urlopen", side_effect=MockHTTPError(400, "Bad Request")):
        with pytest.raises(SidecarError) as exc_info:
            http_client.post_json("/v1/test", {})

        assert exc_info.value.status == 400
        assert "bad request" in exc_info.value.body


def test_sidecar_error_401_clears_cache():
    """Test that 401 errors clear the runtime cache."""
    # Patch the function where it's used in http_client module
    with patch("simssense_mod.http_client.clear_runtime_cache") as mock_clear:
        class MockHTTPError(urllib.error.HTTPError):
            def __init__(self, code, msg):
                self.code = code
                self.msg = msg
                self.headers = {}

            def read(self):
                return b'{"error": "unauthorized"}'

        with patch("urllib.request.urlopen", side_effect=MockHTTPError(401, "Unauthorized")):
            with pytest.raises(SidecarError):
                http_client.post_json("/v1/test", {})
            mock_clear.assert_called_once()


def test_chat_endpoint():
    """Test chat convenience function."""
    mock_response = MockResponse({"reply": "Hi there!", "tool_calls": []})

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        with patch.object(http_client, "get_base_url", return_value="http://127.0.0.1:8765"):
            with patch.object(http_client, "get_auth_header", return_value={"X-SimsSense-Token": "test"}):
                result = http_client.chat(
                    sim={"player_id": "local", "save_id": "save1", "sim_id": 123},
                    message="Hello",
                    context={},
                    lang="en"
                )

                assert result["reply"] == "Hi there!"
                request = mock_urlopen.call_args[0][0]
                assert request.full_url == "http://127.0.0.1:8765/v1/chat"


def test_post_json_sanitizes_non_json_objects():
    """Game objects must be dropped so only primitives travel (review item 5)."""
    mock_response = MockResponse({"ok": True})

    class GameObject:
        def __str__(self):
            return "<GameObject>"

    payload = {
        "context": {
            "relationships": [{"track": GameObject(), "depth": 12.0}],
            "ok": True,
        },
        "stray": GameObject(),
    }

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        result = http_client.post_json("/v1/chat", payload)

    assert result == {"ok": True}
    request = mock_urlopen.call_args[0][0]
    sent = json.loads(request.data.decode("utf-8"))
    assert sent == {"context": {"relationships": [{"depth": 12.0}], "ok": True}}
    assert b"<GameObject>" not in request.data


def test_post_json_sanitizes_non_finite_floats():
    """NaN/inf are not valid JSON and must become null."""
    mock_response = MockResponse({"ok": True})

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        http_client.post_json("/v1/test", {"a": float("inf"), "b": float("nan"), "c": 1.5})

    request = mock_urlopen.call_args[0][0]
    sent = json.loads(request.data.decode("utf-8"))
    assert sent == {"a": None, "b": None, "c": 1.5}


def test_base_url_does_not_duplicate_v1_prefix():
    """Regression: the `/v1` prefix must appear exactly once in every URL."""
    with patch("urllib.request.urlopen", return_value=MockResponse({})) as mock_urlopen:
        http_client.get_json("/v1/health")

        request = mock_urlopen.call_args[0][0]
        assert request.full_url.count("/v1/") == 1
        assert request.full_url.endswith("/v1/health")


def test_health_endpoint_no_auth():
    """Test health endpoint doesn't require auth."""
    mock_response = MockResponse({"ok": True, "version": "0.1.0"})

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        result = http_client.health()

        assert result == {"ok": True, "version": "0.1.0"}
        call_args = mock_urlopen.call_args[0][0]
        # Health should not have auth header
        assert "X-SimsSense-Token" not in call_args.headers


def test_health_omits_auth_but_other_calls_send_it():
    """M1: health passes no_auth=True while other calls still send the token."""
    mock_response = MockResponse({"ok": True})

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        with patch.object(http_client, "get_auth_header",
                          return_value={"X-SimsSense-Token": "test-token"}):
            http_client.health()
            health_request = mock_urlopen.call_args[0][0]
            health_headers = {k.lower(): v for k, v in health_request.headers.items()}
            assert "x-simssense-token" not in health_headers

            http_client.get_json("/v1/status")
            status_request = mock_urlopen.call_args[0][0]
            status_headers = {k.lower(): v for k, v in status_request.headers.items()}
            assert status_headers.get("x-simssense-token") == "test-token"


def test_serialization_failure_raises_unreachable(monkeypatch):
    """M2: a json.dumps failure is handled instead of escaping raw."""
    def boom(*args, **kwargs):
        raise TypeError("not serializable")

    monkeypatch.setattr(http_client.json, "dumps", boom)

    with pytest.raises(SidecarUnreachable):
        http_client.post_json("/v1/test", {"a": 1})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])