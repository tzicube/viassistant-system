# stt_engine/stream.py
from __future__ import annotations

import os
import time
import wave
import tempfile
from dataclasses import dataclass

from .config import WhisperConfig
from .whisper_gpu import transcribe_wav

@dataclass
class AudioFormat:
    sample_rate: int = 16000
    channels: int = 1
    sampwidth: int = 2  # PCM16

class RealtimeWhisperStreamer:
    """
    Practical streaming:
    - buffer PCM16
    - every ~0.8s transcribe full buffer -> cumulative text
    """
    def __init__(self, cfg: WhisperConfig, fmt: AudioFormat | None = None):
        self.cfg = cfg
        self.fmt = fmt or AudioFormat()
        self.buf = bytearray()
        self.last_ts = 0.0
        self.min_interval = 0.8
        self.max_sec = 15.0

    def push(self, pcm16: bytes):
        self.buf.extend(pcm16)
        max_bytes = int(self.max_sec * self.fmt.sample_rate * self.fmt.channels * self.fmt.sampwidth)
        if len(self.buf) > max_bytes:
            self.buf = self.buf[-max_bytes:]

    def ready(self) -> bool:
        return (time.time() - self.last_ts) >= self.min_interval and len(self.buf) > 0

    def transcribe_cumulative(self) -> str:
        self.last_ts = time.time()
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            self._write_wav(path, bytes(self.buf))
            return transcribe_wav(path, self.cfg)
        finally:
            try:
                os.remove(path)
            except Exception:
                pass

    def _write_wav(self, path: str, pcm: bytes):
        with wave.open(path, "wb") as wf:
            wf.setnchannels(self.fmt.channels)
            wf.setsampwidth(self.fmt.sampwidth)
            wf.setframerate(self.fmt.sample_rate)
            wf.writeframes(pcm)
