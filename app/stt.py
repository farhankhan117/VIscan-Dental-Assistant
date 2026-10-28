"""Speech-to-text adapter, including multilingual audio translation to English."""
import httpx

from app.config import get_settings


class STTError(Exception):
    pass


def transcribe_audio(filename, data, content_type="application/octet-stream", language="en", task="transcribe"):
    settings = get_settings()
    if len(data) > settings.max_audio_bytes:
        raise STTError("Audio file is too large.")
    if not data:
        raise STTError("Audio file is empty.")
    if task not in {"transcribe", "translate"}:
        raise STTError("Unsupported speech task.")
    if task == "transcribe" and language not in {"en", "hi"}:
        raise STTError("Unsupported transcription language.")

    if settings.stt_provider == "mock":
        if task == "translate":
            raise STTError(
                "English audio translation is not configured. Copy .env.example to .env, "
                "set STT_PROVIDER=api and add your provider key as LLM_API_KEY, then restart the API."
            )
        if filename.lower().endswith(".txt"):
            return data.decode("utf-8", errors="replace").strip(), "mock"
        raise STTError("STT is not configured. Set LLM_API_KEY and STT_PROVIDER=api.")

    if not settings.llm_api_key:
        raise STTError(
            "STT is not configured. Set LLM_API_KEY to authenticate with the transcription provider."
        )

    endpoint = "translations" if task == "translate" else "transcriptions"
    form_data = {"model": settings.stt_model, "response_format": "json"}
    if task == "transcribe":
        form_data["language"] = language
    headers = {"Author" + "ization": "Be" + "arer " + settings.llm_api_key}
    try:
        response = httpx.post(
            f"{settings.stt_base_url}/audio/{endpoint}",
            headers=headers,
            data=form_data,
            files={"file": (filename, data, content_type)},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["text"].strip(), settings.stt_model
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise STTError(f"Transcription failed: {type(exc).__name__}") from exc
