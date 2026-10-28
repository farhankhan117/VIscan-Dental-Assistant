"""Runtime settings, read from environment variables (see .env.example).

Settings are read on every call (not cached) so tests can change them.
"""
import os
from dataclasses import dataclass
from pathlib import Path

try:  # optional: load a local .env file if python-dotenv is installed
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:  # pragma: no cover
    pass


@dataclass(frozen=True)
class Settings:
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    llm_timeout: float
    stt_base_url: str
    stt_model: str
    stt_provider: str
    api_key: str
    max_input_chars: int
    max_audio_bytes: int
    max_upload_bytes: int
    session_ttl_seconds: int

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)


def get_settings() -> Settings:
    env = os.getenv
    llm_base = env("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
    return Settings(
        llm_api_key=env("LLM_API_KEY", "").strip(),
        llm_base_url=llm_base,
        llm_model=env("LLM_MODEL", "llama-3.3-70b-versatile"),
        llm_timeout=float(env("LLM_TIMEOUT_SECONDS", "8")),
        stt_base_url=env("STT_BASE_URL", llm_base).rstrip("/"),
        stt_model=env("STT_MODEL", "whisper-large-v3"),
        stt_provider=env("STT_PROVIDER", "api" if env("LLM_API_KEY") else "mock"),
        api_key=env("API_KEY", "").strip(),
        max_input_chars=int(env("MAX_INPUT_CHARS", "1500")),
        max_audio_bytes=int(env("MAX_AUDIO_BYTES", str(10 * 1024 * 1024))),
        max_upload_bytes=int(env("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
        session_ttl_seconds=int(env("SESSION_TTL_SECONDS", "1800")),
    )
