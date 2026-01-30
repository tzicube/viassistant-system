# stt_engine/whisper_gpu.py
from __future__ import annotations

import threading
from .config import WhisperConfig

_model_lock = threading.Lock()
_cached: dict[tuple[str, str, str], object] = {}


def _load_model(cfg: WhisperConfig):
    from faster_whisper import WhisperModel  # pip install faster-whisper
    return WhisperModel(
        cfg.model_size,
        device=cfg.device,
        compute_type=cfg.compute_type,
    )


def get_model(cfg: WhisperConfig):
    key = (cfg.model_size, cfg.device, cfg.compute_type)
    with _model_lock:
        m = _cached.get(key)
        if m is not None:
            return m
        m = _load_model(cfg)
        _cached[key] = m
        return m


def transcribe_wav(wav_path: str, cfg: WhisperConfig) -> str:
    """
    Stable transcription for file-based wav.
    NOTE: don't strip/collapse spaces too early; return raw joined text.
    """
    model = get_model(cfg)

    segments, _info = model.transcribe(
        wav_path,
        language=cfg.language,                 # "en"/"vi"/"zh" or None
        vad_filter=cfg.vad_filter,
        beam_size=max(1, int(cfg.beam_size or 1)),

        # IMPORTANT: reduce hallucination / "continue writing"
        condition_on_previous_text=False,

        # More deterministic
        temperature=0.0,

        # Guardrails against no-speech / garbage
        no_speech_threshold=0.6,
        log_prob_threshold=-1.0,
        compression_ratio_threshold=2.4,
    )

    out: list[str] = []
    for s in segments:
        t = (s.text or "")
        if t:
            # keep internal spaces; only strip ends
            out.append(t.strip())

    return " ".join(out)
