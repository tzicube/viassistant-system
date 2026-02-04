# stt_engine/config.py
from dataclasses import dataclass

@dataclass
class WhisperConfig:
    model_size: str = "medium"       # small/medium/large-v3
    device: str = "cpu"            # cuda/cpu
    compute_type: str = "int8_float32"   # float16/int8_float16/int8
    language: str | None = None     # en/vi/zh or None
    vad_filter: bool = True
    beam_size: int = 2
