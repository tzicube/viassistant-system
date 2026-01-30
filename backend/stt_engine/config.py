# stt_engine/config.py
from dataclasses import dataclass

@dataclass
class WhisperConfig:
    model_size: str = "large-v3"       # small/medium/large-v3
    device: str = "cuda"            # cuda/cpu
    compute_type: str = "float16"   # float16/int8_float16/int8
    language: str | None = None     # en/vi/zh or None
    vad_filter: bool = True
    beam_size: int = 1
