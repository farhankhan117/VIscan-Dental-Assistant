"""VI-SCAN Dental Assistant API.

Main entry point:  POST /assistant/message   (typed text or a transcript from /transcribe)
The other endpoints expose each feature on its own for testing and for the UI.
"""
import logging
import secrets
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.assistant import apply_open_result, handle_message

from app.clinical_draft import create_clinical_draft
from app.config import get_settings
from app.conversation import handle_follow_up, resolve_context
from app.interpreter import interpret
from app.llm import get_llm_call
from app.report_chatbot import answer_general_dental_question, answer_question_from_report
from app.report_upload import extract_report
from app.retrieval import get_report_by_id, open_patient_report, patients, reports
from app.session import store
from app.stt import STTError, transcribe_audio
from app.validators import validate_text_input


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def require_api_key(x_api_key: Optional[str] = Header(default=None)):
    """Optional shared-secret auth: enforced only when API_KEY is set."""
    expected = get_settings().api_key
    if expected and not (x_api_key and secrets.compare_digest(x_api_key, expected)):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


app = FastAPI(
    title="VI-SCAN Dental Assistant",
    description="Voice-first dental assistant PoC: report retrieval, clinical dictation drafts, "
                "contextual follow-ups and a report-grounded chatbot. Synthetic data only.",
    version="2.0.0",
)
secured = [Depends(require_api_key)]

SESSION_ID = Field(default=None, max_length=64, description="Conversation id; omit to start a new one.")


class AssistantRequest(BaseModel):
    text: str = Field(max_length=5000, description="Typed text or speech-to-text transcript.")
    alternate_text: Optional[str] = Field(
        default=None,
        max_length=5000,
        description="Browser transcript fallback used only to resolve a pending patient choice.",
    )
    session_id: Optional[str] = SESSION_ID
    patient_id: Optional[str] = Field(default=None, max_length=20, description="Set when the clinician picks a candidate.")


class ReportRequest(BaseModel):
    patient_name: Optional[str] = Field(default=None, max_length=80)
    patient_id: Optional[str] = Field(default=None, max_length=20)
    report_type: Optional[str] = Field(default=None, max_length=30)
    session_id: Optional[str] = SESSION_ID


class DictationRequest(BaseModel):
    transcript: str = Field(max_length=5000)


class FollowUpRequest(BaseModel):
    message: str = Field(max_length=5000)
    session_id: Optional[str] = SESSION_ID


class ChatbotRequest(BaseModel):
    question: str = Field(max_length=5000)
    report_id: Optional[str] = Field(default=None, max_length=20)
    session_id: Optional[str] = SESSION_ID


class ChatbotClearRequest(BaseModel):
    session_id: Optional[str] = SESSION_ID


@app.exception_handler(Exception)
async def unhandled(_, exc):
    logging.getLogger("viscan").exception("unhandled error")
    return JSONResponse(status_code=500, content={"status": "error", "message": "Internal server error."})


@app.get("/")
def home():
    s = get_settings()
    return {"message": "VI-SCAN Dental Assistant API is running.",
            "llm_enabled": s.llm_enabled, "auth_required": bool(s.api_key), "synthetic_data_only": True}


@app.get("/dashboard/summary", dependencies=secured)
def dashboard_summary():
    report_types = {}
    for report in reports:
        report_type = report.get("report_type", "Unknown")
        report_types[report_type] = report_types.get(report_type, 0) + 1
    return {
        "patient_count": len(patients),
        "report_count": len(reports),
        "report_type_counts": report_types,
        "synthetic_data_only": True,
    }


@app.post("/assistant/message", dependencies=secured)
def assistant_message(request: AssistantRequest):
    """Full pipeline: interpret -> validate -> tool -> grounded response."""
    return handle_message(
        request.text,
        request.session_id,
        request.patient_id,
        alternate_text=request.alternate_text,
    )


@app.post("/transcribe", dependencies=secured)
async def transcribe(
    file: UploadFile = File(...),
    language: str = Form(default="en"),
    task: str = Form(default="transcribe"),
):
    """Transcribe speech or translate supported audio languages into English."""
    data = await file.read(get_settings().max_audio_bytes + 1)
    try:
        transcript, provider = transcribe_audio(
            file.filename or "audio", data, file.content_type or "",
            language=language, task=task,
        )
    except STTError as exc:
        return {"status": "error", "message": str(exc)}
    return {
        "status": "success",
        "transcript": transcript,
        "provider": provider,
        "task": task,
        "language": "en" if task == "translate" else language,
        "note": "Review the English transcript; speech recognition can mishear names and dental terms.",
    }


@app.post("/reports/search", dependencies=secured)
def search_report(request: ReportRequest):
    session = store.get(request.session_id)
    result = open_patient_report(request.patient_name, request.report_type, request.patient_id)
    apply_open_result(result, session)
    result["session_id"] = session.session_id
    return result


@app.post("/dictation/draft", dependencies=secured)
def create_draft(request: DictationRequest):
    return create_clinical_draft(request.transcript, llm_call=get_llm_call())


@app.post("/conversation/follow-up", dependencies=secured)
def conversation_follow_up(request: FollowUpRequest):
    clean, error = validate_text_input(request.message)
    session = store.get(request.session_id)
    if error:
        result = {"status": "invalid_input", "message": error}
    else:
        result = handle_follow_up(clean, session, interpret(clean, get_llm_call()))
    result["session_id"] = session.session_id
    return result


@app.post("/chatbot/ask", dependencies=secured)
def chatbot_ask(request: ChatbotRequest):
    session = store.get(request.session_id)
    clean_question, error = validate_text_input(request.question)
    if error:
        return {"status": "invalid_input", "message": error, "session_id": session.session_id}
    if request.report_id:
        report = get_report_by_id(request.report_id)
        if report is None:
            return {"status": "report_not_found", "message": "The requested report could not be found.",
                    "session_id": session.session_id}
    elif session.uploaded_report:
        report = session.uploaded_report
    else:
        report, err = resolve_context(session)
        if err:
            result = answer_general_dental_question(clean_question, get_llm_call())
            if result["status"] == "needs_context":
                return {**err, "session_id": session.session_id}
            return {**result, "session_id": session.session_id}
    context_question = (
        session.last_chat_question
        if session.last_chat_report_id == report["report_id"]
        else None
    )
    result = answer_question_from_report(
        clean_question,
        report,
        context_question,
        llm_call=get_llm_call(),
    )
    if result["status"] in {"general_education", "llm_unavailable"}:
        session.clear_chat_context()
    elif result["status"] not in {"error", "needs_context", "report_not_found"}:
        session.set_chat_context(clean_question, report["report_id"])
    result["session_id"] = session.session_id
    return result


@app.post("/chatbot/upload", dependencies=secured)
async def chatbot_upload(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(default=None, max_length=64),
):
    session = store.get(session_id)
    max_upload_bytes = get_settings().max_upload_bytes
    content = await file.read(max_upload_bytes + 1)
    if len(content) > max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Report files must be {max_upload_bytes:,} bytes or smaller.",
        )
    try:
        report = extract_report(file.filename or "", content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.set_uploaded_report(report)
    return {"status": "success", "report": report, "session_id": session.session_id}


@app.post("/chatbot/clear", dependencies=secured)
def chatbot_clear(request: ChatbotClearRequest):
    session = store.get(request.session_id)
    session.clear_chat_context()
    return {"status": "success", "session_id": session.session_id}
