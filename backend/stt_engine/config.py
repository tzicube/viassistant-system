# stt_engine/config.py
from dataclasses import dataclass

@dataclass
class WhisperConfig:
    model_size: str = "tiny"        # small/medium/large-v3
    device: str = "cuda"             # cuda/cpu
    compute_type: str = "float16"    # float16/int8_float16/int8
    language: str | None = None      # en/vi/zh or None
    vad_filter: bool = False
<<<<<<< HEAD
    beam_size: int = 2.5
=======
    beam_size: int = 2
>>>>>>> 3bbeab7851a08a59d059c303722c0b4f52657571
