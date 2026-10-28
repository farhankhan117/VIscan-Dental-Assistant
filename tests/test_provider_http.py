"""Exercises the real provider clients against a local fake OpenAI-compatible server."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from assistant import handle_message
from clinical_draft import create_clinical_draft
from llm import LLMError, chat_json, get_llm_call
from stt import STTError, transcribe_audio

REPLIES = []
SEEN = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        SEEN.append((self.path, self.headers.get("Authorization"), body))
        if self.path.endswith("/audio/translations"):
            return self._send(200, json.dumps({"text": "Lower right third molar is horizontally impacted."}))
        if self.path.endswith("/audio/transcriptions"):
            return self._send(200, json.dumps({"text": "open priya verma's latest opg report"}))
        status, content = REPLIES.pop(0)
        self._send(status, json.dumps({"choices": [{"message": {"content": content}}]}))

    def _send(self, status, text):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(text.encode())


@pytest.fixture
def provider(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "2")
    REPLIES.clear()
    SEEN.clear()
    yield
    server.shutdown()


INTENT = {
    "intent": "open_report",
    "patient_name": "Priya Verma",
    "report_type": "OPG",
    "recency": "latest",
    "pronoun": None,
    "context_reference": False,
}


def test_chat_json_sends_auth_and_json_mode_and_parses_fenced_output(provider):
    REPLIES.append((200, "```json\n" + json.dumps(INTENT) + "\n```"))
    assert chat_json("sys", "user")["intent"] == "open_report"
    path, auth, body = SEEN[0]
    assert path == "/v1/chat/completions"
    assert auth == "Be" + "arer test-key"
    assert json.loads(body)["response_format"] == {"type": "json_object"}
    assert json.loads(body)["temperature"] == 0


def test_one_retry_on_malformed_json_then_success(provider):
    REPLIES.extend([(200, "not json"), (200, json.dumps(INTENT))])
    assert chat_json("s", "u")["patient_name"] == "Priya Verma"
    assert len(SEEN) == 2


def test_two_malformed_replies_raise(provider):
    REPLIES.extend([(200, "nope"), (200, "still nope")])
    with pytest.raises(LLMError):
        chat_json("s", "u")


def test_http_error_raises(provider):
    REPLIES.append((500, "{}"))
    with pytest.raises(LLMError):
        chat_json("s", "u")


def test_full_pipeline_uses_llm_when_valid(provider):
    REPLIES.append((200, json.dumps(INTENT)))
    result = handle_message("Open Priya Verma's latest OPG report", llm_call=get_llm_call())
    assert result["status"] == "success"
    assert result["interpretation"]["source"] == "llm"


def test_pipeline_falls_back_when_llm_invents_a_name(provider):
    REPLIES.append((200, json.dumps({**INTENT, "patient_name": "Priya Kapoor"})))
    result = handle_message("Open Priya Verma's latest OPG report", llm_call=get_llm_call())
    assert result["status"] == "success"
    assert result["interpretation"]["source"] == "rules"


def test_dictation_with_http_llm_discards_ungrounded_finding(provider):
    reply = {"findings": [
        {"observation": "horizontal impaction", "site_text": None, "fdi_tooth": "48", "certainty": "stated",
         "source_phrase": "Lower right third molar is horizontally impacted"},
        {"observation": "cyst", "site_text": None, "fdi_tooth": None, "certainty": "stated",
         "source_phrase": "cystic lesion present"},
    ]}
    REPLIES.append((200, json.dumps(reply)))
    result = create_clinical_draft(
        "Lower right third molar is horizontally impacted.", llm_call=get_llm_call()
    )
    assert [item["observation"] for item in result["findings"]] == ["horizontal impaction"]
    assert len(result["rejected_findings"]) == 1


def test_stt_api_provider_posts_multipart(provider, monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "api")
    text, _ = transcribe_audio("clip.wav", b"RIFF....", "audio/wav", language="hi")
    assert text.startswith("open priya")
    path, auth, body = SEEN[0]
    assert path == "/v1/audio/transcriptions"
    assert auth == "Be" + "arer test-key"
    assert b'name="language"\r\n\r\nhi' in body
    assert b"whisper-large-v3" in body


def test_stt_rejects_unsupported_language(provider, monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "api")
    with pytest.raises(STTError, match="Unsupported transcription language"):
        transcribe_audio("clip.wav", b"RIFF....", "audio/wav", language="fr")


def test_stt_translation_uses_multilingual_english_translation_endpoint(provider, monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "api")
    text, model = transcribe_audio("speech.webm", b"audio", "audio/webm", task="translate")
    assert text == "Lower right third molar is horizontally impacted."
    assert model == "whisper-large-v3"
    path, auth, body = SEEN[0]
    assert path == "/v1/audio/translations"
    assert auth == "Be" + "arer test-key"
    assert b'name="language"' not in body
    assert b"whisper-large-v3" in body


def test_mock_provider_does_not_claim_to_translate(provider, monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "mock")
    with pytest.raises(STTError, match="English audio translation is not configured"):
        transcribe_audio("speech.webm", b"audio", "audio/webm", task="translate")
