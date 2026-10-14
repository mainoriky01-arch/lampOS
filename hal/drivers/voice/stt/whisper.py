"""Whisper STT provider — batch speech-to-text via an OpenAI-compatible HTTP endpoint.

Trade-off vs. Deepgram/Autonomous streaming:
    This provider buffers all audio received via send_audio() and sends a single
    HTTP POST to /audio/transcriptions when close() is called.  The transcript
    arrives only after the full utterance ends *and* the round-trip HTTP request
    completes, so perceived latency is higher than a true streaming provider.
    The benefit is that any local Whisper-compatible server (faster-whisper-server,
    speaches, whisper.cpp HTTP, …) works without cloud credentials or cost.
"""

import io
import logging
import threading
import wave
from typing import Callable, Optional

import requests

from hal.drivers.voice.stt.provider import STTProvider, STTSession

logger = logging.getLogger("hal.voice.stt")

DEFAULT_MODEL = "whisper-1"
DEFAULT_SAMPLE_RATE = 16000
_CONNECT_TIMEOUT_S = 5
_READ_TIMEOUT_S = 30


class WhisperSTTSession(STTSession):
    """A single batch STT session: buffer audio → POST WAV on close → one transcript."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        language: Optional[str],
        sample_rate: int,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._language = language
        self._sample_rate = sample_rate

        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._closed = False
        self._on_transcript: Optional[Callable[[str, bool], None]] = None

    # ------------------------------------------------------------------
    # STTSession interface
    # ------------------------------------------------------------------

    def start(self, on_transcript: Callable[[str, bool], None]) -> bool:
        """Store the callback. No network connection is opened here."""
        self._on_transcript = on_transcript
        logger.info(
            "WhisperSTT session started (url=%s, model=%s, lang=%s)",
            self._base_url,
            self._model,
            self._language,
        )
        return True

    def send_audio(self, data: bytes):
        """Accumulate PCM audio chunks; thread-safe."""
        if self._closed:
            return
        with self._lock:
            self._buffer.extend(data)

    def close(self):
        """Encode buffered audio as WAV, POST to Whisper, call on_transcript once."""
        if self._closed:
            return
        self._closed = True

        with self._lock:
            audio_bytes = bytes(self._buffer)
            self._buffer = bytearray()

        if not audio_bytes:
            logger.info("WhisperSTT: close() called with empty buffer — skipping HTTP request")
            return

        wav_bytes = self._encode_wav(audio_bytes)
        logger.info(
            "WhisperSTT: sending %d PCM bytes (%d WAV bytes) to %s",
            len(audio_bytes),
            len(wav_bytes),
            self._base_url,
        )

        text = self._post_transcription(wav_bytes)
        if text and self._on_transcript:
            self._on_transcript(text, True)

    def is_closed(self) -> bool:
        return self._closed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _encode_wav(self, pcm: bytes) -> bytes:
        """Wrap raw 16-bit mono PCM in a WAV container."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self._sample_rate)
            wf.writeframes(pcm)
        return buf.getvalue()

    def _post_transcription(self, wav_bytes: bytes) -> Optional[str]:
        """POST multipart request; return transcript text or None on error."""
        url = f"{self._base_url}/audio/transcriptions"
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
        data: dict = {"model": self._model}
        if self._language:
            data["language"] = self._language

        try:
            resp = requests.post(
                url,
                headers=headers,
                files=files,
                data=data,
                timeout=(_CONNECT_TIMEOUT_S, _READ_TIMEOUT_S),
            )
            resp.raise_for_status()
            payload = resp.json()
            text = payload.get("text", "").strip()
            logger.info("WhisperSTT: transcript received (%d chars)", len(text))
            return text or None
        except requests.exceptions.ConnectionError as e:
            logger.error("WhisperSTT: connection refused or unreachable: %s", e)
        except requests.exceptions.Timeout:
            logger.error("WhisperSTT: request timed out (read_timeout=%ss)", _READ_TIMEOUT_S)
        except requests.exceptions.HTTPError as e:
            logger.error("WhisperSTT: HTTP error %s", e)
        except Exception as e:
            logger.error("WhisperSTT: unexpected error during transcription: %s", e)
        return None


class WhisperSTT(STTProvider):
    """OpenAI-compatible batch Whisper STT provider for local servers.

    Requires a running HTTP server that implements POST /audio/transcriptions
    (faster-whisper-server, speaches, whisper.cpp HTTP mode, etc.).
    No api_key is required — most local servers accept any value or none.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
        language: Optional[str] = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ):
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._language = language
        self._sample_rate = sample_rate
        logger.info(
            "WhisperSTT ready (url=%s, model=%s, lang=%s)",
            base_url,
            model,
            language,
        )

    def create_session(self) -> STTSession:
        return WhisperSTTSession(
            base_url=self._base_url,
            api_key=self._api_key,
            model=self._model,
            language=self._language,
            sample_rate=self._sample_rate,
        )

    @property
    def available(self) -> bool:
        """True when base_url is set; no api_key required for local servers."""
        return bool(self._base_url)

    @property
    def name(self) -> str:
        return f"WhisperSTT({self._model})"
