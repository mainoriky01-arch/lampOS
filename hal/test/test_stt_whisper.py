"""Unit tests for WhisperSTT provider.

All tests run without network access or hardware.  HTTP calls are mocked with
unittest.mock so the test suite passes on any development machine.
"""

import io
import wave
from unittest.mock import MagicMock, patch

import pytest

from hal.drivers.voice.stt.whisper import WhisperSTT, WhisperSTTSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(
    base_url="http://localhost:8000/v1",
    api_key="",
    model="whisper-1",
    language="it",
    sample_rate=16000,
) -> WhisperSTTSession:
    return WhisperSTTSession(
        base_url=base_url,
        api_key=api_key,
        model=model,
        language=language,
        sample_rate=sample_rate,
    )


def _silent_pcm(duration_s: float = 0.1, sample_rate: int = 16000) -> bytes:
    """Return PCM 16-bit mono silence for `duration_s` seconds."""
    num_frames = int(sample_rate * duration_s)
    return b"\x00\x00" * num_frames  # 2 bytes per frame (16-bit)


# ---------------------------------------------------------------------------
# a) send_audio accumulates correctly
# ---------------------------------------------------------------------------

def test_send_audio_accumulates_buffer():
    session = _make_session()
    session.start(lambda t, f: None)

    chunk_a = b"\x01\x02" * 100
    chunk_b = b"\x03\x04" * 200
    session.send_audio(chunk_a)
    session.send_audio(chunk_b)

    with session._lock:
        buf = bytes(session._buffer)

    assert buf == chunk_a + chunk_b


# ---------------------------------------------------------------------------
# b) close() with empty buffer does not make an HTTP request
# ---------------------------------------------------------------------------

def test_close_empty_buffer_no_http():
    session = _make_session()
    cb = MagicMock()
    session.start(cb)

    with patch("requests.post") as mock_post:
        session.close()

    mock_post.assert_not_called()
    cb.assert_not_called()
    assert session.is_closed()


# ---------------------------------------------------------------------------
# c) close() with audio builds WAV and calls endpoint with correct params
# ---------------------------------------------------------------------------

def test_close_posts_correct_params():
    session = _make_session(model="whisper-1", language="it", sample_rate=16000)
    cb = MagicMock()
    session.start(cb)
    session.send_audio(_silent_pcm())

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"text": "ciao mondo"}
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.post", return_value=mock_resp) as mock_post:
        session.close()

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args

    # Correct URL
    assert call_kwargs[0][0] == "http://localhost:8000/v1/audio/transcriptions"

    # model and language in the form data
    data = call_kwargs[1]["data"]
    assert data["model"] == "whisper-1"
    assert data["language"] == "it"

    # File is a WAV container
    file_tuple = call_kwargs[1]["files"]["file"]
    _name, wav_bytes, _mime = file_tuple
    wf = wave.open(io.BytesIO(wav_bytes))
    assert wf.getnchannels() == 1
    assert wf.getsampwidth() == 2
    assert wf.getframerate() == 16000

    # Transcript callback fired once with is_final=True
    cb.assert_called_once_with("ciao mondo", True)


# ---------------------------------------------------------------------------
# d) HTTP errors (500, timeout, connection refused) do not raise exceptions
# ---------------------------------------------------------------------------

def test_close_http_500_no_exception():
    import requests as req
    session = _make_session()
    session.start(lambda t, f: None)
    session.send_audio(_silent_pcm())

    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = req.exceptions.HTTPError("500 Server Error")

    with patch("requests.post", return_value=mock_resp):
        session.close()  # must not raise

    assert session.is_closed()


def test_close_timeout_no_exception():
    import requests as req
    session = _make_session()
    session.start(lambda t, f: None)
    session.send_audio(_silent_pcm())

    with patch("requests.post", side_effect=req.exceptions.Timeout):
        session.close()  # must not raise

    assert session.is_closed()


def test_close_connection_error_no_exception():
    import requests as req
    session = _make_session()
    session.start(lambda t, f: None)
    session.send_audio(_silent_pcm())

    with patch("requests.post", side_effect=req.exceptions.ConnectionError("refused")):
        session.close()  # must not raise

    assert session.is_closed()


# ---------------------------------------------------------------------------
# e) Successful response calls on_transcript with the correct text
# ---------------------------------------------------------------------------

def test_close_success_calls_on_transcript():
    session = _make_session()
    received = []
    session.start(lambda t, f: received.append((t, f)))
    session.send_audio(_silent_pcm())

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"text": "  buongiorno  "}
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.post", return_value=mock_resp):
        session.close()

    assert received == [("buongiorno", True)]


def test_close_empty_text_does_not_call_on_transcript():
    session = _make_session()
    cb = MagicMock()
    session.start(cb)
    session.send_audio(_silent_pcm())

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"text": "   "}
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.post", return_value=mock_resp):
        session.close()

    cb.assert_not_called()


# ---------------------------------------------------------------------------
# f) WhisperSTT.available reflects base_url configuration
# ---------------------------------------------------------------------------

def test_available_true_when_base_url_set():
    provider = WhisperSTT(base_url="http://mac-mini.local:8000/v1")
    assert provider.available is True


def test_available_false_when_base_url_empty():
    provider = WhisperSTT(base_url="")
    assert provider.available is False


# ---------------------------------------------------------------------------
# Extra: close() is idempotent (safe to call multiple times)
# ---------------------------------------------------------------------------

def test_close_idempotent():
    session = _make_session()
    session.start(lambda t, f: None)
    session.send_audio(_silent_pcm())

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"text": "test"}
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.post", return_value=mock_resp) as mock_post:
        session.close()
        session.close()

    assert mock_post.call_count == 1  # only fired once


# ---------------------------------------------------------------------------
# Extra: api_key is included as Bearer token when non-empty
# ---------------------------------------------------------------------------

def test_api_key_sent_as_bearer():
    session = _make_session(api_key="test-secret")
    session.start(lambda t, f: None)
    session.send_audio(_silent_pcm())

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"text": "ok"}
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.post", return_value=mock_resp) as mock_post:
        session.close()

    headers = mock_post.call_args[1]["headers"]
    assert headers.get("Authorization") == "Bearer test-secret"


def test_no_api_key_sends_no_auth_header():
    session = _make_session(api_key="")
    session.start(lambda t, f: None)
    session.send_audio(_silent_pcm())

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"text": "ok"}
    mock_resp.raise_for_status = MagicMock()

    with patch("requests.post", return_value=mock_resp) as mock_post:
        session.close()

    headers = mock_post.call_args[1]["headers"]
    assert "Authorization" not in headers


# ---------------------------------------------------------------------------
# Extra: send_audio after close() is a no-op
# ---------------------------------------------------------------------------

def test_send_audio_after_close_is_noop():
    session = _make_session()
    session.start(lambda t, f: None)

    with patch("requests.post") as mock_post:
        session.close()  # empty buffer, no HTTP
        session.send_audio(b"\x00" * 100)

    with session._lock:
        assert len(session._buffer) == 0
