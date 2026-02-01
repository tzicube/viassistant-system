# vitranslation/ai_engine/config.py
import os

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma2:9b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "20"))
vad_filter: bool = False
