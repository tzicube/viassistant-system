from __future__ import annotations

from dataclasses import dataclass

import asyncio
import logging
import os
import subprocess

from stt_engine.config import WhisperConfig
from stt_engine.whisper_gpu import transcribe_wav

logger = logging.getLogger("viassistant.tts")


@dataclass
class STTConfig:
    model_size: str = "medium"
    device: str = "cuda"
    compute_type: str = "float16"
    language: str | None = "en"
    vad_filter: bool = False
    beam_size: int = 15


@dataclass
class TTSConfig:
    edge_voice: str = (os.getenv("VI_EDGE_TTS_VOICE") or "en-US-JennyNeural").strip()
    edge_rate: str = (os.getenv("VI_EDGE_TTS_RATE") or "+0%").strip()
    edge_pitch: str = (os.getenv("VI_EDGE_TTS_PITCH") or "+0Hz").strip()
    edge_volume: str = (os.getenv("VI_EDGE_TTS_VOLUME") or "+0%").strip()

async def _edge_tts_to_mp3_bytes(text: str, cfg: TTSConfig) -> bytes:
    # Lazy import so server can still start even if edge_tts is missing.
    import edge_tts  # type: ignore

    communicate = edge_tts.Communicate(
        text=text,
        voice=cfg.edge_voice,
        rate=cfg.edge_rate,
        volume=cfg.edge_volume,
        pitch=cfg.edge_pitch,
    )

    out = bytearray()
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            out.extend(chunk["data"])
    return bytes(out)


def _ffmpeg_mp3_to_wav_bytes(mp3_bytes: bytes) -> bytes:
    if not mp3_bytes:
        return b""

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "mp3",
        "-i",
        "pipe:0",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        "-f",
        "wav",
        "pipe:1",
    ]
    p = subprocess.run(
        cmd,
        input=mp3_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if p.returncode != 0:
        err = (p.stderr or b"").decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"ffmpeg convert failed rc={p.returncode}: {err}")
    return p.stdout


def _tts_text_to_wav_bytes_edge(text: str, cfg: TTSConfig) -> bytes:
    mp3_bytes = asyncio.run(_edge_tts_to_mp3_bytes(text, cfg))
    return _ffmpeg_mp3_to_wav_bytes(mp3_bytes)


def stt_wav_to_text(wav_path: str, cfg: STTConfig) -> str:
    whisper_cfg = WhisperConfig(
        model_size=cfg.model_size,
        device=cfg.device,
        compute_type=cfg.compute_type,
        language=cfg.language,
        vad_filter=cfg.vad_filter,
        beam_size=cfg.beam_size,
    )
    return (transcribe_wav(wav_path, whisper_cfg) or "").strip()


def tts_text_to_wav_bytes(text: str, cfg: TTSConfig | None = None) -> bytes:
    cfg = cfg or TTSConfig()
    text = (text or "").strip()
    if not text:
        return b""

    try:
        return _tts_text_to_wav_bytes_edge(text, cfg)
    except Exception as e:
        logger.exception("[tts] edge-tts failed: %s", e)
        raise


def stt_tts_pipeline(wav_path: str, stt_cfg: STTConfig, tts_cfg: TTSConfig | None = None):
    text = stt_wav_to_text(wav_path, stt_cfg)
    audio = tts_text_to_wav_bytes(text, tts_cfg)
    return text, audio
