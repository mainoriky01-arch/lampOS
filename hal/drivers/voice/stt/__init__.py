"""Speech-to-text (STT) package: provider ABC + pluggable engines."""

from hal.drivers.voice.stt.autonomous import AutonomousSTT
from hal.drivers.voice.stt.deepgram import DeepgramSTT
from hal.drivers.voice.stt.provider import STTProvider, STTSession
from hal.drivers.voice.stt.whisper import WhisperSTT

__all__ = [
    "AutonomousSTT",
    "DeepgramSTT",
    "STTProvider",
    "STTSession",
    "WhisperSTT",
]
