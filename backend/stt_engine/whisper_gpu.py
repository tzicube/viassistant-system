# stt_engine/whisper_gpu.py
from __future__ import annotations
import threading
from .config import WhisperConfig

_model_lock = threading.Lock()
_cached = {}

def _load_model(cfg: WhisperConfig):
    from faster_whisper import WhisperModel  # pip install faster-whisper
    return WhisperModel(cfg.model_size, device=cfg.device, compute_type=cfg.compute_type)

def get_model(cfg: WhisperConfig):
    key = (cfg.model_size, cfg.device, cfg.compute_type)
    with _model_lock:
        if key in _cached:
            return _cached[key]
        m = _load_model(cfg)
        _cached[key] = m
        return m

def transcribe_wav(wav_path: str, cfg: WhisperConfig) -> str:
    model = get_model(cfg)
    segments, _ = model.transcribe(
        wav_path,
        language=cfg.language,
        vad_filter=cfg.vad_filter,
        beam_size=cfg.beam_size,
        condition_on_previous_text=True,
    )
    out = []
    for s in segments:
        if s.text:
            out.append(s.text.strip())
    return " ".join(out).strip()
