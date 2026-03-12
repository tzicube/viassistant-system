# stt_engine/stream.py
from __future__ import annotations

import os
import time
import wave
import tempfile
import array
from dataclasses import dataclass

from .config import WhisperConfig
from .whisper_gpu import transcribe_wav

STREAM_INPUT_GAIN = float(os.getenv("STT_INPUT_GAIN", "1.6"))  # linear gain ceiling for quiet mic
STREAM_TARGET_PEAK = 28000  # clamp target to avoid clipping (int16 max is 32767)

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
    def __init__(self, cfg: WhisperConfig, fmt: AudioFormat | None = None, input_gain: float | None = None):
        self.cfg = cfg
        self.fmt = fmt or AudioFormat()
        self.buf = bytearray()
        self.last_ts = 0.0
        # shorter interval => faster commit/translation start
        self.min_interval = 0.4  # seconds
        self.max_sec = 300.0     # cap buffer to ~5 minutes to avoid drift and RAM blow-up
        self.trim_sec = 300.0     # keep only last N seconds when transcribing
        self.input_gain = max(1.0, float(input_gain or STREAM_INPUT_GAIN))
        self._target_peak = STREAM_TARGET_PEAK

    def push(self, pcm16: bytes):
        pcm16 = pcm16 or b""

        # Apply simple auto-gain for quiet mic input
        if self.input_gain > 1.01 and pcm16:
            pcm16 = self._apply_gain(pcm16)

        self.buf.extend(pcm16)
        max_bytes = int(self.max_sec * self.fmt.sample_rate * self.fmt.channels * self.fmt.sampwidth)
        if len(self.buf) > max_bytes:
            self.buf = self.buf[-max_bytes:]

    def ready(self) -> bool:
        return (time.time() - self.last_ts) >= self.min_interval and len(self.buf) > 0

    def transcribe_cumulative(self) -> str:
        self.last_ts = time.time()

        # Trim buffer to recent window to avoid ever-growing latency
        window_bytes = int(self.trim_sec * self.fmt.sample_rate * self.fmt.channels * self.fmt.sampwidth)
        if window_bytes > 0 and len(self.buf) > window_bytes:
            self.buf = self.buf[-window_bytes:]

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

    def _apply_gain(self, pcm: bytes) -> bytes:
        """
        Lightweight peak-based gain: boost up to input_gain but cap at target peak to avoid clipping.
        """
        arr = array.array("h")
        arr.frombytes(pcm)
        if not arr:
            return pcm

        max_abs = max(abs(v) for v in arr) or 1
        target = self._target_peak
        gain = min(self.input_gain, target / max_abs)
        if gain <= 1.02:  # skip tiny changes to save CPU
            return pcm

        for i, v in enumerate(arr):
            nv = int(v * gain)
            if nv > 32767:
                nv = 32767
            elif nv < -32768:
                nv = -32768
            arr[i] = nv

        return arr.tobytes()


def make_realtime_streamer(language: str | None = None) -> RealtimeWhisperStreamer:
    """
    Factory for virecord line-1 STT.
    Keeps virecord code slim; adjust defaults in stt_engine/config.py.
    """
    return RealtimeWhisperStreamer(WhisperConfig(language=language))
