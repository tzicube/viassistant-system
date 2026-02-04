from __future__ import annotations

from dataclasses import dataclass

import os
import tempfile
import threading

import pyttsx3

from stt_engine.config import WhisperConfig
from stt_engine.whisper_gpu import transcribe_wav


@dataclass
class STTConfig:
    model_size: str = "medium"    
    device: str = "cuda"
    compute_type: str = "float16"
    language: str | None = "en"
    vad_filter: bool = False
    beam_size: int = 2


@dataclass
class TTSConfig:
    rate: int = 120
    prefer_female: bool = True


_voice_id = None
_voice_lock = threading.Lock()


def _get_preferred_voice_id(prefer_female: bool) -> str | None:
    global _voice_id
    if not prefer_female:
        return None
    if _voice_id is None:
        with _voice_lock:
            if _voice_id is None:
                eng = pyttsx3.init()
                try:
                    for v in eng.getProperty("voices") or []:
                        vid = (getattr(v, "id", "") or "").lower()
                        name = (getattr(v, "name", "") or "").lower()
                        gender = (getattr(v, "gender", "") or "").lower()
                        if "zira" in vid or "zira" in name or "female" in gender:
                            _voice_id = v.id
                            break
                finally:
                    try:
                        eng.stop()
                    except Exception:
                        pass
    return _voice_id


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

    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        engine = pyttsx3.init()
        engine.setProperty("rate", cfg.rate)
        vid = _get_preferred_voice_id(cfg.prefer_female)
        if vid:
            engine.setProperty("voice", vid)
        engine.save_to_file(text, path)
        engine.runAndWait()
        try:
            engine.stop()
        except Exception:
            pass
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


def stt_tts_pipeline(wav_path: str, stt_cfg: STTConfig, tts_cfg: TTSConfig | None = None):
    text = stt_wav_to_text(wav_path, stt_cfg)
    audio = tts_text_to_wav_bytes(text, tts_cfg)
    return text, audio
