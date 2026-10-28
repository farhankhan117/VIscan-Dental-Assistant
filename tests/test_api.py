"""End-to-end through the HTTP layer."""
from io import BytesIO

from docx import Document
from reportlab.pdfgen import canvas


def say(client, text, **kw):
    r = client.post("/assistant/message", json={"text": text, **kw})
    assert r.status_code == 200
    return r.json()


def test_health(client):
    body = client.get("/").json()
    assert body["message"] == "VI-SCAN Dental Assistant API is running." and body["llm_enabled"] is False


def test_dashboard_summary_reports_mock_dataset_counts(client):
    response = client.get("/dashboard/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["patient_count"] >= 5
    assert body["report_count"] == 100
    assert body["report_count"] >= body["patient_count"]
    assert sum(body["report_type_counts"].values()) == body["report_count"]
    assert body["synthetic_data_only"] is True


def test_full_demo_flow(client):
    first = say(client, "Open Priya's latest OPG report")                    # 3 Priyas -> must ask
    assert first["status"] == "ambiguous" and len(first["patients"]) == 3
    sid = first["session_id"]
    opened = say(client, "choose", session_id=sid, patient_id="P002")
    assert opened["status"] == "success" and opened["report"]["date"] == "2026-05-20"
    summary = say(client, "Summarize her report", session_id=sid)
    assert summary["status"] == "success" and summary["sources"][0]["report_id"] == opened["report"]["report_id"]
    grounded_chat = client.post(
        "/chatbot/ask",
        json={"question": "Is there any periapical lesion?", "session_id": sid},
    ).json()
    assert grounded_chat["status"] == "success"
    assert grounded_chat["source_report_id"] == opened["report"]["report_id"]
    answer = say(client, "Is there any periapical lesion?", session_id=sid)
    assert answer["status"] == "success" and "tooth 36" in answer["answer"]
    assert answer["interpretation"]["intent"] == "ask_question" and answer["latency_ms"] >= 0
    follow_up = say(client, "What about tooth 36?", session_id=sid)
    assert follow_up["sources"][0]["report_id"] == opened["report"]["report_id"]
    assert "tooth 36" in follow_up["answer"]


def test_browser_transcript_resolves_patient_when_provider_transcript_mishears_id(client):
    first = say(client, "Open Priya's latest OPG report")
    assert first["status"] == "ambiguous"
    response = client.post(
        "/assistant/message",
        json={
            "text": "open the patient report",
            "alternate_text": "P zero two one",
            "session_id": first["session_id"],
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "success"
    assert result["patient_id"] == "P021"
    assert result["report"]["report_type"] == "OPG"


def test_ambiguous_voice_search_accepts_a_spoken_patient_id_and_open_command(client):
    first = say(client, "Open Priya's latest OPG report")
    assert first["status"] == "ambiguous"

    opened = say(
        client,
        "P zero two one, open her report",
        session_id=first["session_id"],
    )

    assert opened["status"] == "success"
    assert opened["patient_id"] == "P021"
    assert opened["report"]["patient_id"] == "P021"


def test_missing_report_message(client):
    r = say(client, "Open Neha Kapoor's OPG")
    assert r["status"] == "report_not_found" and "CBCT" in r["message"]


def test_dictation_via_assistant_and_endpoint(client):
    t = "Lower right third molar is horizontally impacted."
    via_assistant = say(client, t)
    via_endpoint = client.post("/dictation/draft", json={"transcript": t}).json()
    for r in (via_assistant, via_endpoint):
        assert r["status"] == "draft" and r["requires_clinician_review"] is True
        assert r["findings"][0]["site"]["fdi_tooth"] == "48"


def test_reports_search_endpoint_supports_patient_id(client):
    ok = client.post("/reports/search", json={"patient_id": "P021", "report_type": "OPG"}).json()
    assert ok["status"] == "success" and ok["patient_id"] == "P021"
    assert ok["report"]["patient_id"] == "P021"
    assert ok["report"]["report_id"] == "R043"
    assert ok["report"]["date"] == "2025-09-05"
    amb = client.post("/reports/search", json={"patient_name": "Priya Sharma", "report_type": "OPG"}).json()
    assert amb["status"] == "ambiguous"
    assert {candidate["patient_id"] for candidate in amb["patients"]} == {"P001", "P021"}


def test_reports_search_endpoint_validates_optional_name_and_id_pair(client):
    match = client.post(
        "/reports/search",
        json={"patient_name": "Priya Sharma", "patient_id": "P021"},
    ).json()
    assert match["status"] == "success" and match["patient_id"] == "P021"
    mismatch = client.post(
        "/reports/search",
        json={"patient_name": "Priya Verma", "patient_id": "P021"},
    ).json()
    assert mismatch["status"] == "not_found"


def _docx_bytes():
    document = Document()
    document.add_paragraph("Tooth 36 has a periapical radiolucency.")
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _pdf_bytes():
    buffer = BytesIO()
    page = canvas.Canvas(buffer)
    page.drawString(72, 720, "Tooth 36 has a periapical radiolucency.")
    page.save()
    return buffer.getvalue()


def test_uploaded_docx_becomes_session_scoped_chatbot_source(client):
    upload = client.post(
        "/chatbot/upload",
        files={"file": ("fictional-report.docx", _docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert upload.status_code == 200
    body = upload.json()
    assert body["status"] == "success"
    assert body["report"]["patient_name"] == "fictional-report.docx"
    sid = body["session_id"]

    answer = client.post(
        "/chatbot/ask",
        json={"question": "What is mentioned about tooth 36?", "session_id": sid},
    ).json()
    assert answer["status"] == "success"
    assert answer["source_report_id"] == body["report"]["report_id"]
    assert "periapical radiolucency" in answer["answer"]


def test_uploaded_pdf_extracts_text_for_chatbot(client):
    upload = client.post(
        "/chatbot/upload",
        files={"file": ("fictional-report.pdf", _pdf_bytes(), "application/pdf")},
    )
    assert upload.status_code == 200
    answer = client.post(
        "/chatbot/ask",
        json={
            "question": "Summarize this report and list its recorded findings.",
            "session_id": upload.json()["session_id"],
        },
    ).json()
    assert answer["status"] == "success"
    assert "periapical radiolucency" in answer["answer"]


def test_chatbot_upload_rejects_unsupported_extensions(client):
    response = client.post(
        "/chatbot/upload",
        files={"file": ("report.exe", b"not a report", "application/octet-stream")},
    )
    assert response.status_code == 422
    assert "Supported report formats" in response.json()["detail"]


def test_follow_up_endpoint_uses_server_side_context_not_client_data(client):
    sid = client.post("/reports/search", json={"patient_name": "Priya Verma", "report_type": "OPG"}).json()["session_id"]
    forged = {"report_id": "FAKE", "report_text": "Forged text", "findings": ["forged"]}
    r = client.post("/conversation/follow-up", json={"message": "Summarize her report", "session_id": sid,
                                                    "previous_result": {"status": "success", "report": forged}}).json()
    assert r["status"] == "success" and r["report_id"] != "FAKE" and "forged" not in r["answer"].lower()


def test_chatbot_endpoint(client):
    ok = client.post("/chatbot/ask", json={"question": "What does the report say?", "report_id": "R005"}).json()
    assert ok["status"] == "success" and ok["source_report_id"] == "R005"
    assert client.post("/chatbot/ask", json={"question": "x?", "report_id": "R999"}).json()["status"] == "report_not_found"
    guess = client.post("/chatbot/ask", json={"question": "Will the patient need surgery?", "report_id": "R005"}).json()
    assert guess["status"] == "unsupported_question"
    assert client.post("/chatbot/ask", json={"question": "What does the report say?"}).json()["status"] == "needs_context"


def test_chatbot_answers_general_dental_question_without_a_report(client, monkeypatch):
    import main

    calls = []

    def fake_llm(system, user):
        calls.append((system, user))
        return {"answer": "Fluoride helps strengthen tooth enamel."}

    monkeypatch.setattr(main, "get_llm_call", lambda: fake_llm)
    result = client.post(
        "/chatbot/ask",
        json={"question": "What does fluoride do?"},
    ).json()

    assert result["status"] == "general_education"
    assert "strengthen tooth enamel" in result["answer"]
    assert calls[0][1] == "What does fluoride do?"


def test_chatbot_followups_keep_context_for_the_same_report_and_can_be_cleared(client):
    opened = client.post(
        "/reports/search",
        json={"patient_id": "P002", "report_type": "OPG"},
    ).json()
    sid = opened["session_id"]
    first = client.post(
        "/chatbot/ask",
        json={"question": "Is there caries?", "session_id": sid},
    ).json()
    followup = client.post(
        "/chatbot/ask",
        json={"question": "What about tooth 36?", "session_id": sid},
    ).json()
    assert first["source_report_id"] == followup["source_report_id"] == opened["report"]["report_id"]
    assert first["status"] == followup["status"] == "not_in_report"
    assert followup["evidence"][0]["text"] == "Periapical radiolucency associated with tooth 36."

    cleared = client.post("/chatbot/clear", json={"session_id": sid}).json()
    assert cleared["status"] == "success"
    after_clear = client.post(
        "/chatbot/ask",
        json={"question": "What about tooth 36?", "session_id": sid},
    ).json()
    assert after_clear["status"] == "success"
    assert "Periapical radiolucency associated with tooth 36." in after_clear["answer"]


def test_input_validation(client):
    assert client.post("/assistant/message", json={"text": "x" * 6000}).status_code == 422     # hard cap
    assert say(client, "   ")["status"] == "invalid_input"
    assert say(client, "x" * 2000)["status"] == "invalid_input"                                # configurable cap
    assert client.post("/assistant/message", json={}).status_code == 422


def test_unknown_request_gets_help(client):
    assert say(client, "what is the weather")["status"] == "needs_context"       # a question, but no report is open
    unknown = say(client, "hello there")
    assert unknown["status"] == "unsupported_request"
    assert unknown["message"] == "I couldn't understand that request. Please rephrase it in English."


def test_api_key_enforced_when_configured(client, monkeypatch):
    monkeypatch.setenv("API_KEY", "secret123")
    assert client.post("/assistant/message", json={"text": "hi"}).status_code == 401
    assert client.post("/assistant/message", json={"text": "hi"}, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/assistant/message", json={"text": "hi"}, headers={"X-API-Key": "secret123"}).status_code == 200
    assert client.get("/").status_code == 200                                                    # health stays open


def test_transcribe_then_assistant(client):
    audio = client.post("/transcribe", files={"file": ("dictation.txt", b"Open Priya Verma's latest OPG report", "text/plain")})
    assert audio.json()["status"] == "success"
    assert say(client, audio.json()["transcript"])["status"] == "success"
    hindi = client.post(
        "/transcribe",
        data={"language": "hi"},
        files={"file": ("dictation.txt", "नमस्ते".encode("utf-8"), "text/plain")},
    )
    assert hindi.json()["status"] == "success" and hindi.json()["transcript"] == "नमस्ते"
    bad = client.post("/transcribe", files={"file": ("clip.wav", b"RIFFxxxx", "audio/wav")}).json()
    assert bad["status"] == "error" and "not configured" in bad["message"]
    assert client.post("/transcribe", files={"file": ("empty.wav", b"", "audio/wav")}).json()["status"] == "error"


def test_llm_failure_does_not_break_the_api(client, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "dummy")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9")          # nothing listens here -> connection error
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "1")
    r = say(client, "Open Priya Verma's latest OPG report")
    assert r["status"] == "success" and r["interpretation"]["source"] == "rules"
    assert "LLM" in r["interpretation"]["fallback_reason"]
