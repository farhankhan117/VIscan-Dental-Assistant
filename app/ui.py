# ============================================================
# VI-SCAN DENTAL ASSISTANT
# File: app/ui.py
# Purpose: Streamlit user interface
# ============================================================

# STEP 1: Import application dependencies
import json
import os
import base64
import importlib
from datetime import datetime
from html import escape
from pathlib import Path

import requests
import streamlit as st
import streamlit.components.v1 as components

from viscan_voice_commands import voice_route
from clinical_draft import select_dictation_transcript
import draft_export

if not hasattr(draft_export, "build_editable_draft_json"):
    draft_export = importlib.reload(draft_export)


# STEP 2: Configure the Streamlit page
st.set_page_config(
    page_title="VI-SCAN Dental Assistant",
    page_icon="🦷",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_URL = os.getenv(
    "VISCAN_API_URL",
    "http://127.0.0.1:8000",
).rstrip("/")

TIMEOUT = 20
live_speech = components.declare_component(
    "viscan_live_speech_english",
    path=str(Path(__file__).parent / "components" / "live_speech"),
)

PAGES = [
    "Dashboard",
    "Find Patient Report",
    "Clinical Draft",
    "Ask About a Report",
]


# STEP 3: Apply professional UI styling
st.markdown(
    """
    <style>
    .stApp {
        background: #f4f7fb;
    }

    [data-testid="stSidebar"] {
        background: #10233f;
    }

    [data-testid="stSidebar"] * {
        color: #f2f6ff;
    }

    .hero {
        background: linear-gradient(120deg, #10233f, #17627b);
        color: white;
        padding: 28px;
        border-radius: 16px;
        margin-bottom: 22px;
    }

    .hero h1 {
        color: white;
        margin: 0;
        font-size: 30px;
    }

    .hero p {
        color: #e0edf7;
        margin: 10px 0 0 0;
    }

    .report-card {
        background: white;
        border: 1px solid #dfe7f1;
        padding: 20px;
        border-radius: 14px;
        margin: 10px 0;
    }

    .report-label {
        color: #64748b;
        font-size: 13px;
    }

    .report-value {
        color: #14243b;
        font-size: 20px;
        font-weight: 650;
        overflow-wrap: anywhere;
    }

    .report-body {
        background: white;
        border: 1px solid #dfe7f1;
        border-radius: 12px;
        padding: 20px;
        line-height: 1.7;
        color: #253449;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
    }

    div.stButton > button {
        min-height: 42px;
        border-radius: 9px;
        font-weight: 600;
    }

    div[data-testid="stButton"] > button[kind="primary"],
    div[data-testid="stDownloadButton"] > button,
    button[data-testid="stBaseButton-primary"] {
        background: linear-gradient(120deg, #17627b, #1e7892);
        border: 0;
        color: white;
    }

    div[data-testid="stButton"] > button[kind="primary"]:hover,
    div[data-testid="stDownloadButton"] > button:hover,
    button[data-testid="stBaseButton-primary"]:hover {
        background: linear-gradient(120deg, #124e64, #17627b);
        border: 0;
        color: white;
    }

    [data-testid="stMetric"] {
        background: white;
        border: 1px solid #dfe7f1;
        border-radius: 12px;
        padding: 14px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# STEP 4: Initialize persistent UI state
DEFAULTS = {
    "navigation": "Dashboard",
    "pending_navigation": None,
    "selected_report": None,
    "selected_report_id": "",
    "last_search_result": None,
    "last_search_report_type": None,
    "last_transcript": "",
    "draft_result": None,
    "chat_history": [],
    "last_followup_result": None,
    "selected_patient": None,
    "session_id": None,
    "assistant_result": None,
    "report_chat_messages": [],
    "report_chat_search_result": None,
    "dictation_text": "",
    "assistant_input": "",
    "assistant_input_widget": "",
    "last_live_transcript": "",
    "last_audio_transcription_id": "",
    "last_speech_clear_id": "",
    "last_voice_session_end_id": "",
    "dictation_transcription_warning": "",
    "dictation_provider_transcript": "",
    "dictation_browser_transcript": "",
    "draft_revision": 0,
    "voice_speak_text": "",
    "voice_speak_id": 0,
    "voice_cancel_speech_id": 0,
    "voice_stop_listening_id": 0,
    "last_rendered_page": None,
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value

pending_navigation = st.session_state.pop("pending_navigation", None)
if st.session_state.get("navigation") not in PAGES:
    st.session_state["navigation"] = "Dashboard"
if pending_navigation == "Voice Assistant":
    pending_navigation = "Dashboard"
if pending_navigation in PAGES:
    st.session_state["navigation"] = pending_navigation


def navigate_to(page_name):
    st.session_state["navigation"] = page_name


def queue_navigation(page_name):
    if page_name in PAGES:
        st.session_state["pending_navigation"] = page_name


def cancel_voice_output():
    st.session_state["voice_speak_text"] = ""
    st.session_state["voice_cancel_speech_id"] += 1


def save_dictation_input(widget_key):
    st.session_state["dictation_text"] = st.session_state.get(widget_key, "")


def is_dictation_target(widget_key):
    return widget_key == "dictation_input" or widget_key.startswith("dictation_input_")


def save_assistant_input():
    st.session_state["assistant_input"] = st.session_state.get("assistant_input_widget", "")


# STEP 6: Connect the UI to the FastAPI backend
def api_request(method, endpoint, payload=None):
    """Send a request to the backend and handle common errors."""

    # Server-side conversation memory: every call carries the same session id,
    # so follow-ups such as "Summarize her report" know who "her" is.
    if method == "POST" and isinstance(payload, dict) and st.session_state.get("session_id"):
        payload = {**payload, "session_id": st.session_state["session_id"]}

    headers = {"X-API-Key": os.getenv("VISCAN_API_KEY")} if os.getenv("VISCAN_API_KEY") else {}

    try:
        response = requests.request(
            method,
            f"{API_URL}{endpoint}",
            json=payload,
            headers=headers,
            timeout=TIMEOUT,
        )

        try:
            result = response.json()
        except ValueError:
            result = {
                "status": "error",
                "message": "Backend returned an invalid response.",
            }

        if not response.ok:
            if isinstance(result, dict):
                message = result.get(
                    "detail",
                    result.get("message", "Request failed."),
                )
            else:
                message = "Request failed."

            return {
                "status": "error",
                "message": message,
                "http_status": response.status_code,
            }

        if isinstance(result, dict) and result.get("session_id"):
            st.session_state["session_id"] = result["session_id"]

        return (
            result
            if isinstance(result, dict)
            else {"status": "success", "data": result}
        )

    except requests.exceptions.ConnectionError:
        return {
            "status": "error",
            "message": (
                "Backend connection failed. Start the FastAPI server "
                "and try again."
            ),
        }

    except requests.exceptions.Timeout:
        return {
            "status": "error",
            "message": "The request timed out. Please try again.",
        }

    except requests.exceptions.RequestException as exc:
        return {
            "status": "error",
            "message": str(exc),
        }


def api_upload_report(uploaded_file):
    """Upload a supported report document to the session-scoped API."""
    data = {}
    if st.session_state.get("session_id"):
        data["session_id"] = st.session_state["session_id"]
    headers = {"X-API-Key": os.getenv("VISCAN_API_KEY")} if os.getenv("VISCAN_API_KEY") else {}
    try:
        response = requests.post(
            f"{API_URL}/chatbot/upload",
            files={
                "file": (
                    uploaded_file.name,
                    uploaded_file.getvalue(),
                    uploaded_file.type or "application/octet-stream",
                )
            },
            data=data,
            headers=headers,
            timeout=60,
        )
        try:
            result = response.json()
        except ValueError:
            result = {"status": "error", "message": "Backend returned an invalid response."}
        if not response.ok:
            return {
                "status": "error",
                "message": result.get("detail", result.get("message", "Report upload failed.")),
            }
        if result.get("session_id"):
            st.session_state["session_id"] = result["session_id"]
        return result
    except requests.exceptions.ConnectionError:
        return {"status": "error", "message": "Backend connection failed. Start the FastAPI server and try again."}
    except requests.exceptions.Timeout:
        return {"status": "error", "message": "Report upload timed out. Please try again."}
    except requests.exceptions.RequestException as exc:
        return {"status": "error", "message": str(exc)}


def process_assistant_message(text=None, patient_id=None, alternate_text=None):
    message = (text if text is not None else st.session_state.get("assistant_input_widget", "")).strip()
    if not message and not patient_id:
        st.session_state["assistant_result"] = {
            "status": "invalid_input",
            "message": "Speak or type a message first.",
        }
        return
    payload = {"text": message or "select"}
    if alternate_text:
        payload["alternate_text"] = alternate_text
    if patient_id:
        payload["patient_id"] = patient_id
    result = api_request("POST", "/assistant/message", payload)
    st.session_state["assistant_result"] = result
    st.session_state["voice_speak_text"] = spoken_response_for(result)
    st.session_state["voice_speak_id"] += 1
    if message:
        st.session_state["assistant_input"] = message
    report = get_report(result)
    if report and result.get("status") == "success":
        if st.session_state.get("selected_report_id") != report_id_of(report):
            st.session_state["report_chat_messages"] = []
        st.session_state["selected_report"] = report
        st.session_state["selected_report_id"] = report_id_of(report)
    elif result.get("status") == "draft":
        cancel_voice_output()
        st.session_state["voice_stop_listening_id"] += 1
        result.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
        st.session_state["draft_result"] = result
        st.session_state["draft_revision"] += 1
        queue_navigation("Clinical Draft")
        st.session_state["last_rendered_page"] = "Clinical Draft"


def process_voice_dictation(
    transcript,
    provider_unavailable=False,
    widget_key="dictation_input",
    alternate_transcript=None,
):
    """Turn a finished voice transcript into the editable clinical draft."""
    clean_transcript, transcripts_differ = select_dictation_transcript(
        transcript,
        alternate_transcript,
    )
    st.session_state["dictation_provider_transcript"] = str(transcript or "").strip()
    st.session_state["dictation_browser_transcript"] = str(alternate_transcript or "").strip()
    st.session_state["dictation_transcription_warning"] = (
        "Speech-to-text and the browser preview differed. Verify the transcript below "
        "before using the draft."
        if transcripts_differ
        else ""
    )
    if not clean_transcript:
        return
    cancel_voice_output()
    st.session_state["voice_stop_listening_id"] += 1
    st.session_state[widget_key] = clean_transcript
    st.session_state["dictation_text"] = clean_transcript
    st.session_state["last_transcript"] = clean_transcript
    with st.spinner("Creating a draft from your dictation..."):
        result = api_request("POST", "/dictation/draft", {"transcript": clean_transcript})
    if is_error(result):
        st.session_state["voice_action_message"] = (
            "Draft creation failed: "
            + str(result.get("message", "The transcript could not be processed."))
        )
        st.rerun()
        return
    result.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
    if provider_unavailable:
        result.setdefault("warnings", []).insert(
            0,
            "Provider transcription was unavailable. The browser's English transcript was kept verbatim "
            "for clinician review.",
        )
    st.session_state["draft_result"] = result
    st.session_state["draft_revision"] += 1
    st.session_state["voice_action_message"] = ""
    st.rerun()


def spoken_response_for(result):
    """Create a concise spoken response while keeping evidence visible in the page."""
    if not isinstance(result, dict):
        return "I couldn't complete that request. Please try again."
    status = result.get("status")
    if status == "ambiguous":
        candidates = result.get("patients") or []
        choices = "; ".join(
            f"{index + 1}: {candidate.get('name')} (patient ID {candidate.get('patient_id')})"
            for index, candidate in enumerate(candidates)
        )
        if choices:
            return (
                f"I found more than one matching patient. {choices}. "
                "Please say the patient ID clearly, for example, P zero two one, "
                "or say option one, option two, or option three. "
                "I will keep listening until you say stop or end."
            )
        return "I found more than one matching patient. Please clarify which patient you mean."
    if is_error(result):
        message = result.get("message") or "I couldn't complete that request."
        return message

    if status == "draft":
        return (
            "I've prepared a draft from the dictated observations. Please review it before clinical use."
        )

    report = get_report(result)
    answer = result.get("answer")
    if answer:
        source = result.get("sources") or result.get("evidence") or []
        if source and isinstance(source[0], dict):
            item = source[0]
            source_id = item.get("report_id", "the selected report")
            source_type = item.get("report_type")
            source_date = item.get("report_date") or item.get("date")
            source_label = ", ".join(str(part) for part in (source_id, source_type, source_date) if part)
            return f"{answer} Source: {source_label}."
        return answer
    if result.get("message"):
        return str(result["message"])
    if report:
        patient = report.get("patient") or {}
        patient_name = report.get("patient_name") or patient.get("name") or "the patient"
        report_type = report.get("report_type") or "requested"
        report_date = report.get("report_date") or report.get("date")
        report_id = report_id_of(report)
        detail = f" dated {report_date}" if report_date else ""
        identifier = f", report ID {report_id}" if report_id else ""
        findings = report.get("findings") or []
        spoken_findings = []
        for finding in findings[:5]:
            if isinstance(finding, dict):
                spoken_findings.append(
                    str(finding.get("description") or finding.get("finding") or finding.get("text") or "")
                )
            else:
                spoken_findings.append(str(finding))
        findings_text = (
            " The findings are: " + " ".join(spoken_findings)
            if spoken_findings else ""
        )
        return (
            f"I found {patient_name}'s {report_type} report{detail}{identifier}.{findings_text} "
            "It is open on screen."
        )
    return str(result.get("message") or "Done.")


def process_spoken_command(
    transcript,
    provider_unavailable=False,
    alternate_transcript=None,
    input_key=None,
):
    """Run a recognized voice request and refresh the page with its spoken reply."""
    action, destination = voice_route(transcript, st.session_state.get("navigation"))
    if action == "navigate":
        cancel_voice_output()
        queue_navigation(destination)
        st.rerun()
    if input_key:
        st.session_state[input_key] = transcript
        if is_dictation_target(input_key):
            st.session_state["dictation_text"] = transcript
        elif input_key == "assistant_input_widget":
            st.session_state["assistant_input"] = transcript
    if action == "report_chat":
        process_report_chat_question(transcript)
        st.rerun()
    if action == "dictation":
        process_voice_dictation(
            transcript,
            provider_unavailable=provider_unavailable,
            widget_key=input_key if is_dictation_target(input_key or "") else "dictation_input",
            alternate_transcript=alternate_transcript,
        )
        st.rerun()
    with st.spinner("Following your voice command..."):
        process_assistant_message(transcript, alternate_text=alternate_transcript)
    st.rerun()


def process_report_chat_question(question):
    """Ask the active report chatbot and persist the turn with its evidence."""
    clean_question = str(question or "").strip()
    if not clean_question:
        return
    payload = {"question": clean_question}
    report = st.session_state.get("selected_report") or {}
    if report and not report.get("uploaded"):
        payload["report_id"] = report_id_of(report)
    result = api_request("POST", "/chatbot/ask", payload)
    answer = result.get("answer") or result.get("message") or "No response was returned."
    st.session_state["report_chat_messages"].extend(
        [
            {"role": "user", "content": clean_question},
            {
                "role": "assistant",
                "content": answer,
                "status": result.get("status"),
                "evidence": result.get("evidence") or [],
                "source_report_id": result.get("source_report_id"),
                "report_type": result.get("report_type"),
                "report_date": result.get("report_date"),
                "patient_name": result.get("patient_name"),
            },
        ]
    )
def clear_report_chat():
    """Clear the visible thread and its server-side follow-up context."""
    result = api_request("POST", "/chatbot/clear", {})
    if result.get("status") == "success":
        st.session_state["report_chat_messages"] = []
    else:
        show_error(result)


def activate_uploaded_report(result):
    report = result.get("report") if isinstance(result, dict) else None
    if result.get("status") != "success" or not isinstance(report, dict):
        show_error(result)
        return False
    if st.session_state.get("selected_report_id") != report_id_of(report):
        st.session_state["report_chat_messages"] = []
    st.session_state["selected_report"] = report
    st.session_state["selected_report_id"] = report_id_of(report)
    st.session_state["selected_patient"] = None
    st.session_state["report_chat_search_result"] = None
    return True


def open_report_for_chat(payload, requested_type=None, expected_patient_id=None):
    """Open a searched report and make it the grounded source for report chat."""
    result = api_request("POST", "/reports/search", payload)
    st.session_state["report_chat_search_result"] = result
    if result.get("status") != "success":
        if result.get("status") != "ambiguous":
            show_error(result)
        return False

    report = get_report(result)
    if not report:
        show_error({
            "status": "error",
            "message": "The search did not return a report to open.",
        })
        return False

    returned_patient_id = str(report.get("patient_id", ""))
    returned_type = str(report.get("report_type", ""))
    if expected_patient_id and returned_patient_id != str(expected_patient_id):
        show_error({
            "status": "error",
            "message": "The search returned a different patient than requested; the report was not opened.",
        })
        return False
    if requested_type and returned_type.casefold() != requested_type.casefold():
        show_error({
            "status": "error",
            "message": f"Requested {requested_type}, but the search returned {returned_type}; the report was not opened.",
        })
        return False

    if st.session_state.get("selected_report_id") != report_id_of(report):
        st.session_state["report_chat_messages"] = []
    st.session_state["selected_report"] = report
    st.session_state["selected_report_id"] = report_id_of(report)
    st.session_state["selected_patient"] = {
        "patient_id": returned_patient_id,
        "name": report.get("patient_name", "Selected patient"),
    }
    return True


def is_english_live_transcript(text):
    """Allow the English browser recognizer as a fallback if provider STT is offline."""
    letters = [char for char in text if char.isalpha()]
    return bool(letters) and sum(char.isascii() for char in letters) / len(letters) >= 0.85


def render_assistant_result():
    result = st.session_state.get("assistant_result")
    if not isinstance(result, dict):
        return

    st.markdown("#### Assistant response")
    interpretation = result.get("interpretation") or {}
    if interpretation:
        st.caption(f"Understood as {interpretation.get('intent', 'request')}")

    if result.get("status") == "ambiguous":
        st.warning(result.get("message", "Please choose the correct patient."))
        for candidate in result.get("patients", []):
            patient_id = candidate.get("patient_id")
            label = (
                f"{candidate.get('name', 'Unknown patient')} · "
                f"ID {patient_id} · DOB {candidate.get('date_of_birth', 'not provided')}"
            )
            if patient_id:
                st.button(
                    label,
                    key=f"assistant_candidate_{patient_id}",
                    on_click=process_assistant_message,
                    args=("select", patient_id),
                )
        return

    if is_error(result):
        show_error(result)
        return

    report = None if result.get("status") == "draft" else get_report(result)
    if report:
        st.success(result.get("context_resolution") or "Report opened.")
        render_report(report)
    elif result.get("status") == "draft":
        st.success("Draft created. Open Clinical Draft to edit and review it.")
        if result.get("report_text"):
            st.markdown("**Draft report — clinician review required**")
            st.text(result["report_text"])
        for finding in result.get("findings", []):
            site = (finding.get("site") or {}).get("text", "site not specified")
            st.markdown(f"- **{finding.get('observation', 'Finding')}** at {site} ({finding.get('certainty', 'uncertain')})")
        st.caption("Clinician review required.")
        st.button(
            "Edit clinical draft",
            on_click=navigate_to,
            args=("Clinical Draft",),
            key="assistant_edit_draft",
        )
    elif result.get("answer"):
        st.markdown(result["answer"])
        if result.get("context_resolution"):
            st.caption(result["context_resolution"])
        evidence = result.get("evidence") or []
        sources = result.get("sources") or []
        if evidence or sources:
            st.markdown("**Source evidence**")
            for item in evidence:
                st.markdown(f"- {format_evidence(item)}")
            if not evidence:
                for source in sources:
                    st.markdown(
                        f"- Report {source.get('report_id')} "
                        f"({source.get('report_type')}, {source.get('date')})"
                    )
    elif result.get("message"):
        st.info(result["message"])


# STEP 7: Normalize common backend response formats
def get_report(result):
    """Extract a report from common API response structures."""

    if not isinstance(result, dict):
        return None

    for key in ("report", "selected_report"):
        value = result.get(key)
        if isinstance(value, dict):
            return value

    data = result.get("data")

    if isinstance(data, dict):
        if "report_id" in data or "report_text" in data:
            return data

        if isinstance(data.get("report"), dict):
            return data["report"]

    if "report_id" in result or "report_text" in result:
        return result

    return None


def report_id_of(report):
    """Get the report's unique identifier."""

    if not isinstance(report, dict):
        return ""

    return str(report.get("report_id") or report.get("id") or "")


def is_error(result):
    """Identify unsuccessful API responses."""

    return (
        not isinstance(result, dict)
        or result.get("status")
        in {
            "error",
            "ambiguous",
            "not_found",
            "report_not_found",
            "needs_context",
            "needs_patient",
            "needs_clarification",
            "invalid_report_type",
            "invalid_input",
            "unsupported_request",
        }
        or result.get("success") is False
    )


def show_error(result):
    """Display an API error or clarification message."""

    if not isinstance(result, dict):
        st.error("Unexpected backend response.")
        return

    status = result.get("status", "")

    message = (
        result.get("message")
        or result.get("detail")
        or "The request could not be completed."
    )

    if status == "ambiguous":
        st.warning(
            "Multiple patients matched. Select the correct patient "
            "before opening a report."
        )
    elif status in {
        "not_found", "report_not_found", "needs_context", "needs_patient",
        "needs_clarification", "invalid_report_type", "invalid_input",
        "unsupported_request",
    }:
        st.warning(str(message))
    else:
        st.error(str(message))


def format_evidence(item):
    """One readable line per evidence entry returned by the backend."""

    if not isinstance(item, dict):
        return str(item)

    return (
        f"Report {item.get('report_id')} ({item.get('report_type')}, "
        f"{item.get('report_date')}), finding {item.get('finding_index')}: "
        f"{item.get('text')}"
    )


# STEP 8: Display a readable report instead of raw JSON
def render_report(report):
    """Render report metadata, findings, and source text."""

    if not isinstance(report, dict):
        st.info("No report is selected.")
        return

    report_id = report_id_of(report)

    # STEP 8A: Resolve available patient and report metadata
    patient = report.get("patient", {})

    if not isinstance(patient, dict):
        patient = {}

    patient_name = (
        report.get("patient_name")
        or patient.get("name")
        or report.get("name")
        or "Name unavailable from API"
    )

    patient_id = (
        report.get("patient_id")
        or patient.get("patient_id")
        or patient.get("id")
        or "Not supplied"
    )

    report_type = (
        report.get("report_type")
        or report.get("type")
        or "Not specified"
    )

    report_date = (
        report.get("report_date")
        or report.get("date")
        or "Not specified"
    )

    st.markdown("### Dental report")

    # STEP 8B: Show report metadata in readable cards
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown(
            f"""
            <div class="report-card">
                <div class="report-label">Report ID</div>
                <div class="report-value">
                    {escape(str(report_id or "Not supplied"))}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            f"""
            <div class="report-card">
                <div class="report-label">Patient</div>
                <div class="report-value">
                    {escape(str(patient_name))}
                </div>
                <div class="report-label">
                    Patient ID: {escape(str(patient_id))}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col3:
        st.markdown(
            f"""
            <div class="report-card">
                <div class="report-label">Report type</div>
                <div class="report-value">
                    {escape(str(report_type))}
                </div>
                <div class="report-label">
                    Date: {escape(str(report_date))}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # STEP 8C: Render findings as readable text
    findings = report.get("findings", [])

    st.markdown("#### Findings")

    if isinstance(findings, list):
        for finding in findings:
            if isinstance(finding, dict):
                finding_text = (
                    finding.get("description")
                    or finding.get("finding")
                    or finding.get("text")
                    or json.dumps(finding, ensure_ascii=False)
                )
            else:
                finding_text = str(finding)

            st.markdown(f"- {finding_text}")

    elif isinstance(findings, dict):
        for key, value in findings.items():
            st.markdown(
                f"- **{key.replace('_', ' ').title()}:** {value}"
            )

    elif findings:
        st.write(str(findings))

    else:
        st.info("No findings were supplied in this report.")

    # STEP 8D: Render original report text
    report_text = (
        report.get("report_text")
        or report.get("text")
        or report.get("summary")
    )

    st.markdown("#### Original report text")

    if report_text:
        st.markdown(
            f'<div class="report-body">'
            f'{escape(str(report_text))}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("The API did not supply report text.")

    st.caption(
        "Synthetic demonstration data only. "
        "This report is not for diagnosis."
    )


def render_voice_capture(target_key, speak_text=""):
    """Capture speech for the active page and populate its editable text input."""
    continuous = True
    speech_result = live_speech(
        language="en-US",
        speak_text=speak_text,
        speech_id=st.session_state["voice_speak_id"],
        cancel_speech_id=st.session_state["voice_cancel_speech_id"],
        continuous=True,
        stop_listening_id=st.session_state["voice_stop_listening_id"],
        dictation_mode=is_dictation_target(target_key),
        key="speech_capture_workspace",
    )
    if speak_text and st.session_state.get("voice_speak_text") == speak_text:
        st.session_state["voice_speak_text"] = ""
    if not isinstance(speech_result, dict):
        return

    session_end_id = speech_result.get("session_end_id")
    if speech_result.get("session_ended") and session_end_id:
        if session_end_id != st.session_state.get("last_voice_session_end_id"):
            st.session_state["last_voice_session_end_id"] = session_end_id
            cancel_voice_output()
        return

    clear_id = speech_result.get("clear_id")
    if speech_result.get("action") == "clear":
        if clear_id != st.session_state.get("last_speech_clear_id"):
            st.session_state["last_speech_clear_id"] = clear_id
            st.session_state[target_key] = ""
            if is_dictation_target(target_key):
                st.session_state["dictation_text"] = ""
            if target_key == "assistant_input_widget":
                st.session_state["assistant_input"] = ""
            st.session_state["voice_action_message"] = ""
        return

    transcript = speech_result.get("transcript", "")
    audio_id = speech_result.get("audio_id")
    if speech_result.get("listening"):
        st.session_state["voice_action_message"] = ""
    if transcript and not audio_id:
        st.session_state[target_key] = transcript
        if is_dictation_target(target_key):
            st.session_state["dictation_text"] = transcript
        elif target_key == "assistant_input_widget":
            st.session_state["assistant_input"] = transcript

    if audio_id and audio_id != st.session_state.get("last_audio_transcription_id"):
        st.session_state["last_audio_transcription_id"] = audio_id
        try:
            response = requests.post(
                f"{API_URL}/transcribe",
                files={
                    "file": (
                        "speech.webm",
                        base64.b64decode(speech_result.get("audio_base64", "")),
                        speech_result.get("audio_type", "audio/webm"),
                    )
                },
                data={"task": "transcribe", "language": "en"},
                headers=(
                    {"X-API-Key": os.getenv("VISCAN_API_KEY")}
                    if os.getenv("VISCAN_API_KEY")
                    else {}
                ),
                timeout=60,
            )
            recognition_result = response.json()
            if response.ok and recognition_result.get("status") == "success":
                recognized_text = recognition_result["transcript"].strip()
                process_spoken_command(
                    recognized_text,
                    alternate_transcript=transcript if continuous else None,
                    input_key=target_key,
                )
            else:
                # Browser recognition can still execute English commands when provider
                # transcription is unavailable. Non-English transcripts are never
                # mislabeled or sent through English-only intent extraction.
                live_transcript = transcript.strip()
                if is_dictation_target(target_key) and live_transcript:
                    process_spoken_command(
                        live_transcript,
                        provider_unavailable=True,
                        input_key=target_key,
                    )
                elif live_transcript and voice_route(
                    live_transcript, st.session_state.get("navigation")
                )[0] == "navigate":
                    process_spoken_command(
                        live_transcript,
                        provider_unavailable=True,
                        input_key=target_key,
                    )
                elif live_transcript and (
                    is_english_live_transcript(live_transcript)
                ):
                    process_spoken_command(
                        live_transcript,
                        provider_unavailable=True,
                        input_key=target_key,
                    )
                else:
                    message = recognition_result.get("message", "English speech recognition failed.")
                    if not is_english_live_transcript(transcript):
                        message = "I couldn't recognize that command clearly. Please repeat it slowly in English."
                    st.warning(message)
                    if continuous and transcript.strip():
                        st.session_state["voice_speak_text"] = message
                        st.session_state["voice_speak_id"] += 1
                        st.rerun()
        except (requests.exceptions.RequestException, ValueError, TypeError) as exc:
            live_transcript = transcript.strip()
            if is_dictation_target(target_key) and live_transcript:
                process_spoken_command(
                    live_transcript,
                    provider_unavailable=True,
                    input_key=target_key,
                )
            elif live_transcript and voice_route(
                live_transcript, st.session_state.get("navigation")
            )[0] == "navigate":
                process_spoken_command(
                    live_transcript,
                    provider_unavailable=True,
                    input_key=target_key,
                )
            elif live_transcript and is_english_live_transcript(live_transcript):
                process_spoken_command(
                    live_transcript,
                    provider_unavailable=True,
                    input_key=target_key,
                )
            elif continuous and live_transcript:
                message = "I couldn't recognize that command clearly. Please repeat it slowly in English."
                st.session_state["voice_action_message"] = message
                st.session_state["voice_speak_text"] = message
                st.session_state["voice_speak_id"] += 1
                st.rerun()
            else:
                st.error(f"Audio transcription failed: {type(exc).__name__}")

    action_message = st.session_state.get("voice_action_message")
    if action_message:
        st.error(action_message)
        st.session_state["voice_action_message"] = ""
    if speech_result.get("error"):
        st.warning(speech_result["error"])


# STEP 9: Render the sidebar
with st.sidebar:
    st.markdown("# 🦷 VI-SCAN")
    st.caption("Dental Assistant Workspace")
    st.divider()

    page = st.radio(
        "WORKSPACE",
        PAGES,
        key="navigation",
    )
    if page != st.session_state.get("last_rendered_page"):
        st.session_state["last_rendered_page"] = page

    st.divider()
    st.markdown("**System connection**")

    health = api_request("GET", "/")

    if health.get("status") == "error":
        st.error("Backend disconnected")
        st.caption(health.get("message", ""))
    else:
        st.success("Backend reachable")

    st.caption("Synthetic data only")
    st.caption("Clinician review required")


with st.container(horizontal=True, horizontal_alignment="distribute"):
    for destination, label in (
        ("Dashboard", "Home"),
        ("Find Patient Report", "Find report"),
        ("Clinical Draft", "Clinical draft"),
        ("Ask About a Report", "Ask report"),
    ):
        st.button(
            label,
            key=f"workspace_jump_{destination}",
            type="primary" if page == destination else "secondary",
            width="stretch",
            on_click=queue_navigation,
            args=(destination,),
        )

voice_targets = {
    "Dashboard": "assistant_input_widget",
    "Find Patient Report": "assistant_voice_input_patient_search",
    "Clinical Draft": f"dictation_input_{st.session_state['draft_revision']}",
    "Ask About a Report": "report_chat_voice_input",
}
render_voice_capture(
    voice_targets[page],
    speak_text=st.session_state.get("voice_speak_text", ""),
)


# STEP 11: Dashboard and navigation actions
if page == "Dashboard":
    st.markdown(
        """
        <div class="hero">
            <h1>VI-SCAN Dental Assistant</h1>
            <p>One focused workspace for patient reports, voice dictation, and review-ready drafts.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.session_state.get("assistant_result"):
        with st.container(border=True):
            render_assistant_result()
    st.subheader("Workspace overview")
    st.caption("Your patient and report counts are loaded from the synthetic demo dataset.")
    dashboard = api_request("GET", "/dashboard/summary")

    metric1, metric2, metric3 = st.columns(3)

    with metric1:
        st.metric(
            "Synthetic patients",
            dashboard.get("patient_count", "—"),
        )

    with metric2:
        st.metric(
            "Available reports",
            dashboard.get("report_count", "—"),
        )

    with metric3:
        st.metric(
            "Active report",
            st.session_state["selected_report_id"] or "None",
        )

    if dashboard.get("status") == "error":
        st.warning(dashboard.get("message", "Could not load dataset counts."))
    else:
        report_types = dashboard.get("report_type_counts", {})
        if report_types:
            st.caption("Reports by type: " + " · ".join(
                f"{name}: {count}" for name, count in sorted(report_types.items())
            ))

    draft_status = "Ready for review" if st.session_state["draft_result"] else "No draft yet"
    st.info(f"Clinical draft: **{draft_status}** — clinician review is always required.")

    st.markdown("### Quick actions")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("#### 🔎 Patient reports")
        st.write("Search patients and select the correct record.")

        st.button(
            "Find report",
            use_container_width=True,
            on_click=navigate_to,
            args=("Find Patient Report",),
            key="dashboard_find_report",
        )

    with col2:
        st.markdown("#### 💬 Report chatbot")
        st.write("Ask questions about a selected report.")

        st.button(
            "Ask about a report",
            use_container_width=True,
            on_click=navigate_to,
            args=("Ask About a Report",),
            key="dashboard_ask_report",
        )

    with col3:
        st.markdown("#### 📝 Clinical draft")
        st.write("Create and review a structured dictation draft.")
        st.button(
            "Create a draft",
            use_container_width=True,
            on_click=navigate_to,
            args=("Clinical Draft",),
            key="dashboard_clinical_draft",
        )

    st.markdown("### Current report")

    if st.session_state["selected_report"]:
        render_report(st.session_state["selected_report"])
    else:
        st.info(
            "No report selected yet. Start by searching for a patient."
        )


# STEP 12: Patient report search and duplicate-name selection
elif page == "Find Patient Report":
    st.subheader("Find Patient Report")
    st.write(
        "Search for a patient, review matching identities, "
        "then open the report."
    )
    if st.session_state.get("assistant_result"):
        with st.container(border=True):
            render_assistant_result()

    with st.form("patient_search"):
        patient_name = st.text_input(
            "Patient name",
            placeholder="Example: Priya Sharma",
        )

        report_type = st.selectbox(
            "Report type",
            [
                "Any report",
                "OPG",
                "Bitewing",
                "IOPA",
                "CBCT",
            ],
            key="report_type_filter",
        )
        st.caption("Choose the report type exactly as it is recorded in the patient file.")

        search_clicked = st.form_submit_button(
            "Search reports",
            type="primary",
            use_container_width=True,
        )
    if search_clicked:
        st.session_state["selected_report"] = None
        st.session_state["selected_report_id"] = ""
        st.session_state["selected_patient"] = None
        st.session_state["report_chat_messages"] = []
        st.session_state["last_search_report_type"] = (
            st.session_state["report_type_filter"]
            if st.session_state["report_type_filter"] != "Any report"
            else None
        )
        if not patient_name.strip():
            st.warning("Please enter a patient name.")
        else:
            payload = {
                "patient_name": patient_name.strip(),
            }

            if st.session_state["last_search_report_type"]:
                payload["report_type"] = st.session_state["last_search_report_type"]

            with st.spinner("Searching records..."):
                result = api_request(
                    "POST",
                    "/reports/search",
                    payload,
                )

            st.session_state["last_search_result"] = result

            if is_error(result) and result.get("status") != "ambiguous":
                show_error(result)

    # STEP 12A: Show duplicate matches as selectable identities
    result = st.session_state.get("last_search_result")

    if isinstance(result, dict):
        candidates = (
            result.get("candidates")
            or result.get("patients")
            or result.get("matches")
            or []
        )

        if result.get("status") == "ambiguous" and candidates:
            st.warning(
                "Multiple patients have this name. Select a patient "
                "and confirm their identity before opening a report."
            )

            candidate_labels = []

            for candidate in candidates:
                name = candidate.get("name", "Unknown name")
                pid = (
                    candidate.get("patient_id")
                    or candidate.get("id")
                    or "Unknown ID"
                )
                candidate_labels.append(f"{name} — {pid}")

            selected_label = st.selectbox(
                "Select the correct patient",
                candidate_labels,
                key="duplicate_patient_choice",
                help="Choose the correct patient using their details.",
            )

            selected_index = candidate_labels.index(selected_label)
            candidate = candidates[selected_index]

            # STEP 12B: Display available identity details
            st.markdown("#### Selected patient details")

            details = {
                "Patient name": candidate.get("name", "Not supplied"),
                "Patient ID": (
                    candidate.get("patient_id")
                    or candidate.get("id")
                    or "Not supplied"
                ),
            }

            for key, value in candidate.items():
                if key not in {"name", "patient_id", "id"}:
                    details[key.replace("_", " ").title()] = value

            detail_cols = st.columns(2)

            for index, (key, value) in enumerate(details.items()):
                with detail_cols[index % 2]:
                    st.markdown(f"**{key}**")
                    st.write(value)

            st.caption(
                "Duplicate names are never guessed. Choose the correct identity, "
                "then click the button below to open that patient's report."
            )

            # STEP 12C: Open report for the selected patient ID
            if st.button(
                "Open this patient's report",
                type="primary",
                key="open_selected_patient",
            ):
                patient_id = (
                    candidate.get("patient_id")
                    or candidate.get("id")
                )

                if not patient_id:
                    st.error("This candidate has no patient ID.")
                else:
                    selected_payload = {
                        "patient_id": str(patient_id),
                    }

                    requested_type = st.session_state.get("last_search_report_type")
                    if requested_type:
                        selected_payload["report_type"] = requested_type

                    with st.spinner(
                        "Opening selected patient's report..."
                    ):
                        selected_result = api_request(
                            "POST",
                            "/reports/search",
                            selected_payload,
                        )

                    if is_error(selected_result) or selected_result.get("status") != "success":
                        show_error(selected_result)
                    else:
                        selected_report = get_report(selected_result)

                        if selected_report:
                            returned_patient_id = str(selected_report.get("patient_id", ""))
                            returned_type = str(selected_report.get("report_type", ""))
                            if returned_patient_id != str(patient_id):
                                st.error(
                                    "The backend returned a report for a different patient. "
                                    "It was not opened."
                                )
                            elif requested_type and returned_type.casefold() != requested_type.casefold():
                                st.error(
                                    "The backend returned a different report type than requested. "
                                    "It was not opened."
                                )
                            else:
                                st.session_state["selected_patient"] = candidate
                                st.session_state["selected_report"] = selected_report
                                st.session_state["selected_report_id"] = report_id_of(selected_report)
                                st.session_state["report_chat_messages"] = []
                                st.success(
                                    f"Opened {returned_type} report for "
                                    f"{selected_report.get('patient_name', candidate.get('name', 'selected patient'))}."
                                )
                                st.rerun()
                        else:
                            st.warning(
                                "The backend did not return a report. "
                                "Check patient-ID request handling in "
                                "app/main.py."
                            )

        else:
            # STEP 12D: Render a directly returned report
            report = get_report(result)

            if report and not is_error(result):
                requested_type = st.session_state.get("last_search_report_type")
                if requested_type and str(report.get("report_type", "")).casefold() != requested_type.casefold():
                    st.error(
                        f"Requested {requested_type}, but the backend returned "
                        f"{report.get('report_type', 'an unknown type')}. Report was not opened."
                    )
                else:
                    st.success(
                        f"Retrieved {report.get('report_type', 'report')} report "
                        f"for {report.get('patient_name', 'selected patient')}."
                    )

                    st.session_state["selected_report"] = report
                    st.session_state["selected_report_id"] = report_id_of(report)
                    st.session_state["report_chat_messages"] = []

                    render_report(report)

                    st.button(
                        "Ask chatbot about this report",
                        on_click=navigate_to,
                        args=("Ask About a Report",),
                    )

    # STEP 12E: Keep the active report available
    if st.session_state["selected_report"]:
        st.divider()
        st.markdown("### Active report")
        render_report(st.session_state["selected_report"])


# STEP 14: Clinical draft generation and editing
elif page == "Clinical Draft":
    st.subheader("Clinical draft")
    st.write(
        "Dictate or enter examination observations, then review the structured draft before exporting it."
    )
    dictation_widget_key = voice_targets[page]
    transcription_warning = st.session_state.get("dictation_transcription_warning")
    if transcription_warning:
        st.warning(transcription_warning)
        provider_transcript = st.session_state.get("dictation_provider_transcript", "")
        browser_transcript = st.session_state.get("dictation_browser_transcript", "")
        with st.expander("Compare speech recognition results"):
            st.markdown("**Speech-to-text**")
            st.write(provider_transcript or "No provider transcript was returned.")
            st.markdown("**Browser preview**")
            st.write(browser_transcript or "No browser transcript was returned.")
            if browser_transcript and st.button(
                "Use browser preview instead",
                key="use_browser_dictation_transcript",
            ):
                st.session_state[dictation_widget_key] = browser_transcript
                st.session_state["dictation_text"] = browser_transcript
                st.session_state["last_transcript"] = browser_transcript
                st.session_state["dictation_transcription_warning"] = ""
                st.rerun()

    if dictation_widget_key not in st.session_state:
        st.session_state[dictation_widget_key] = (
            st.session_state.get("dictation_text")
            or st.session_state.get("last_transcript", "")
        )
    transcript = st.text_area(
        "Clinical dictation transcript",
        height=160,
        key=dictation_widget_key,
        on_change=save_dictation_input,
        args=(dictation_widget_key,),
        placeholder=(
            "Example: Lower right third molar is horizontally impacted."
        ),
    )

    if st.button(
        "Generate draft",
        type="primary",
        use_container_width=True,
    ):
        st.session_state["dictation_transcription_warning"] = ""
        if not transcript.strip():
            st.warning("Enter or dictate a transcript first.")
        else:
            with st.spinner("Generating structured draft..."):
                result = api_request(
                    "POST",
                    "/dictation/draft",
                    {"transcript": transcript.strip()},
                )

            if is_error(result):
                show_error(result)
            else:
                st.session_state["last_transcript"] = transcript.strip()
                st.session_state["dictation_text"] = transcript.strip()
                result.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
                st.session_state["draft_result"] = result
                st.session_state["draft_revision"] += 1
                st.success(
                    "Draft generated. Please review and edit it."
                )

    # STEP 14A: Display fields in an editable form
    draft = st.session_state.get("draft_result")

    if draft:
        st.divider()
        st.markdown("### Clinical draft report")
        st.caption("Review every section before use. This draft is not a signed clinical report.")
        findings_for_summary = [
            item for item in draft.get("findings", []) if isinstance(item, dict)
        ]
        unclassified_count = sum(
            not bool(item.get("classified")) for item in findings_for_summary
        )
        summary_col, unclassified_col, review_col = st.columns(3)
        with summary_col:
            st.metric("Structured observations", len(findings_for_summary))
        with unclassified_col:
            st.metric("Needs clinician interpretation", unclassified_count)
        with review_col:
            st.metric("Review status", "Pending")
        st.caption(
            "The original dictation and each source phrase are preserved so you can verify every observation."
        )
        revision = st.session_state["draft_revision"]
        suffix = str(revision)
        selected_report = st.session_state.get("selected_report") or {}
        selected_patient = selected_report.get("patient") or {}
        selected_patient_details = st.session_state.get("selected_patient") or {}
        patient_default = (
            selected_report.get("patient_name")
            or selected_patient.get("name")
            or selected_patient_details.get("name")
            or draft.get("patient_name")
            or ""
        )
        patient_name = st.text_input(
            "Patient name (optional)",
            value=patient_default,
            key=f"draft_patient_name_{suffix}",
        )
        report_title = st.text_input(
            "Report title",
            value=draft.get("title") or "Clinical dictation draft",
            key=f"draft_title_{suffix}",
        )
        report_text_key = f"draft_readable_report_{suffix}"
        report_text_default = str(
            draft.get("report_text")
            or draft.get("source_transcript")
            or st.session_state["last_transcript"]
        )
        if report_text_key not in st.session_state:
            st.session_state[report_text_key] = report_text_default
        report_text = st.session_state[report_text_key]
        st.markdown("#### Report preview")
        with st.container(border=True):
            st.markdown(
                '<div class="report-body">'
                f'{escape(str(report_text)).replace(chr(10), "<br>")}'
                "</div>",
                unsafe_allow_html=True,
            )
        with st.expander("Edit readable report", expanded=False):
            report_text = st.text_area(
                "Edit report text",
                height=150,
                key=report_text_key,
                help="This text is included in the PDF and JSON exports.",
            )

        finding_rows = []
        for item in draft.get("findings", []):
            if not isinstance(item, dict):
                continue
            site = item.get("site") or {}
            site_text = site.get("text", "") if isinstance(site, dict) else str(site)
            tooth = site.get("fdi_tooth") if isinstance(site, dict) else None
            if tooth:
                site_text = f"{site_text} (FDI {tooth})"
            source_phrase = item.get("source_phrase", "")
            finding_rows.append({
                "ID": str(item.get("id", len(finding_rows) + 1)),
                "Finding": item.get("observation") or source_phrase or "Unclassified observation",
                "Anatomical site": site_text or "Not stated",
                "Certainty": item.get("certainty") or "uncertain",
                "Source words": source_phrase,
                "Classified": bool(item.get("classified")),
            })

        st.markdown("#### Structured findings")
        edited_findings = []
        if finding_rows:
            for row in finding_rows:
                with st.container(border=True):
                    st.markdown(f"**Finding {row['ID']}**")
                    if row["Classified"]:
                        st.caption("Structured finding")
                    else:
                        st.caption(
                            "Unclassified transcript wording — preserved verbatim; "
                            "no clinical interpretation added."
                        )
                    finding_col, site_col = st.columns(2)
                    with finding_col:
                        edited_observation = st.text_input(
                            "Finding",
                            value=row["Finding"],
                            key=f"draft_finding_{suffix}_{row['ID']}",
                        )
                    with site_col:
                        edited_site = st.text_input(
                            "Anatomical site",
                            value=row["Anatomical site"],
                            key=f"draft_site_{suffix}_{row['ID']}",
                        )
                    edited_certainty = st.selectbox(
                        "Certainty",
                        ["stated", "uncertain", "negated"],
                        index=(
                            ["stated", "uncertain", "negated"].index(row["Certainty"])
                            if row["Certainty"] in {"stated", "uncertain", "negated"}
                            else 1
                        ),
                        key=f"draft_certainty_{suffix}_{row['ID']}",
                    )
                    st.markdown("**Source evidence**")
                    st.caption(row["Source words"] or "No source phrase was returned.")
                    edited_findings.append({
                        "ID": row["ID"],
                        "Finding": edited_observation,
                        "Anatomical site": edited_site,
                        "Certainty": edited_certainty,
                        "Source words": row["Source words"],
                    })
        else:
            st.info("No findings were extracted from the transcript.")
        with st.expander("Original source transcript", expanded=False):
            st.write(draft.get("source_transcript") or st.session_state["last_transcript"])

        warnings = draft.get("warnings") or []
        if warnings:
            with st.expander(f"Review notes ({len(warnings)})", expanded=False):
                for warning in warnings:
                    st.write(f"- {warning}")

        st.info("**Review status:** Pending clinician review · clinician approval required")
        if draft.get("extraction_method"):
            st.caption(f"Extraction method: {draft['extraction_method']}")

        edited_draft = {
            **draft,
            "title": report_title,
            "patient_name": patient_name.strip() or "Not specified",
            "report_text": report_text,
            "source_transcript": draft.get("source_transcript") or st.session_state["last_transcript"],
            "requires_clinician_review": True,
            "review_status": "Pending clinician review",
            "created_at": draft.get("created_at") or datetime.now().isoformat(timespec="seconds"),
        }
        from draft_pdf import create_draft_pdf

        structured_draft = draft_export.build_structured_draft(
            draft=edited_draft,
            edited_rows=edited_findings,
            title=report_title.strip() or "Clinical dictation draft",
            patient_name=patient_name.strip() or "Not specified",
            report_text=report_text,
            created_at=edited_draft["created_at"],
        )
        editable_json = draft_export.build_editable_draft_json(structured_draft)
        if (
            structured_draft["edited_finding_ids_require_confirmation"]
            or structured_draft["readable_report_requires_clinician_confirmation"]
        ):
            st.warning(
                "The report or structured findings were edited. The JSON marks edited content "
                "as requiring clinician confirmation against the transcript."
            )
        pdf_draft = {
            **edited_draft,
            "title": report_title.strip() or "Clinical dictation draft",
            "patient_name": patient_name.strip() or "Not specified",
            "report_text": report_text,
            "findings": [
                {
                    **row,
                    "observation": row.get("Finding", ""),
                    "site": {"text": row.get("Anatomical site", "")},
                    "certainty": row.get("Certainty", "uncertain"),
                    "source_phrase": row.get("Source words", ""),
                }
                for row in edited_findings
            ],
        }
        export_pdf, export_json = st.columns(2)
        with export_pdf:
            st.download_button(
                "Download report as PDF",
                data=create_draft_pdf(pdf_draft, pdf_draft["patient_name"]),
                file_name="viscan_clinical_draft.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )
        with export_json:
            st.download_button(
                "Download structured JSON",
                data=json.dumps(editable_json, indent=2, ensure_ascii=False),
                file_name="viscan_clinical_draft.json",
                mime="application/json",
                use_container_width=True,
            )
        with st.form(f"draft_json_form_{suffix}"):
            edited_json_text = st.text_area(
                "Editable structured JSON",
                value=json.dumps(editable_json, indent=2, ensure_ascii=False),
                height=320,
                key=f"draft_json_editor_{suffix}",
                help="Only the stated findings, anatomical sites, certainty, and readable draft report are included.",
            )
            apply_json_edits = st.form_submit_button(
                "Apply JSON edits",
                width="stretch",
            )
        if apply_json_edits:
            try:
                updated_draft = draft_export.apply_structured_draft_edits(
                    draft,
                    json.loads(edited_json_text),
                )
            except (json.JSONDecodeError, ValueError) as exc:
                st.error(f"Could not apply JSON edits: {exc}")
            else:
                st.session_state["draft_result"] = updated_draft
                st.session_state["draft_revision"] += 1
                st.success("JSON edits applied. Review the updated draft before use.")
                st.rerun()

        st.markdown("#### Correct transcript")
        st.caption(
            "Fix speech-recognition mistakes here. Applying changes reruns extraction "
            "and updates both the readable report and structured findings."
        )
        with st.form(f"correct_transcript_form_{suffix}"):
            corrected_transcript = st.text_area(
                "Transcript to apply",
                value=draft.get("source_transcript") or st.session_state.get("last_transcript", ""),
                height=110,
                key=f"corrected_transcript_{suffix}",
            )
            apply_transcript_changes = st.form_submit_button(
                "Apply changes and update report",
                type="primary",
                use_container_width=True,
            )
        if apply_transcript_changes:
            st.session_state["dictation_transcription_warning"] = ""
            if not corrected_transcript.strip():
                st.warning("The corrected transcript cannot be empty.")
            else:
                with st.spinner("Updating the draft from the corrected transcript..."):
                    corrected_result = api_request(
                        "POST",
                        "/dictation/draft",
                        {"transcript": corrected_transcript.strip()},
                    )
                if is_error(corrected_result):
                    show_error(corrected_result)
                else:
                    corrected_result.setdefault(
                        "created_at",
                        datetime.now().isoformat(timespec="seconds"),
                    )
                    st.session_state["dictation_text"] = corrected_transcript.strip()
                    st.session_state["last_transcript"] = corrected_transcript.strip()
                    st.session_state["draft_result"] = corrected_result
                    st.session_state["draft_revision"] += 1
                    st.success("Transcript applied. The report and structured findings were rebuilt.")
                    st.rerun()


# STEP 15: Report-aware chatbot and contextual follow-up
elif page == "Ask About a Report":
    st.subheader("Ask about a report")
    report = st.session_state.get("selected_report")

    if report or st.session_state["report_chat_messages"]:
        if st.button("Clear conversation", key="clear_report_chat"):
            clear_report_chat()
            st.rerun()

    messages = st.session_state["report_chat_messages"]

    for message in messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    chat_prompt = st.chat_input(
        "Ask a question or attach a report",
        key="report_chat_input",
        accept_file=True,
        file_type=[
            "pdf", "docx", "apng", "bmp", "gif", "ico", "jfif", "jpe", "jpg",
            "jpeg", "pbm", "pcx", "pfm", "pgm", "png", "pnm", "ppm", "tga",
            "tif", "tiff", "webp",
        ],
    )
    if chat_prompt:
        question = chat_prompt.text.strip()
        attachments = chat_prompt.files
        if attachments:
            uploaded_file = attachments[0]
            with st.spinner("Uploading report and preparing it for chat..."):
                upload_result = api_upload_report(uploaded_file)
            if activate_uploaded_report(upload_result):
                st.session_state["report_chat_messages"].append({
                    "role": "user",
                    "content": f"Attached report: {uploaded_file.name}",
                })
                if question:
                    process_report_chat_question(question)
                else:
                    process_report_chat_question(
                        "Summarize this report and list its recorded findings."
                    )
                st.rerun()
        elif question:
            process_report_chat_question(question)
            st.rerun()

    st.divider()
    st.subheader("Choose a report")
    st.caption(
        "Search by patient name or ID, or upload a report file. For similar names, choose the matching patient."
    )
    with st.form("report_chat_search_form"):
        search_name_col, search_id_col = st.columns(2)
        with search_name_col:
            chat_patient_name = st.text_input(
                "Patient name",
                placeholder="Example: Priya Verma",
                key="report_chat_patient_name",
            )
        with search_id_col:
            chat_patient_id = st.text_input(
                "Patient ID",
                placeholder="Example: P002",
                key="report_chat_patient_id",
            )
        chat_report_type = st.selectbox(
            "Report type",
            ["Any report", "OPG", "Bitewing", "IOPA", "CBCT"],
            key="report_chat_report_type",
        )
        search_chat_report = st.form_submit_button(
            "Search and open report",
            type="primary",
            use_container_width=True,
        )

    if search_chat_report:
        name = chat_patient_name.strip()
        patient_id = chat_patient_id.strip()
        if not name and not patient_id:
            st.warning("Enter a patient name, patient ID, or both.")
            st.session_state["report_chat_search_result"] = None
        else:
            payload = {}
            if name:
                payload["patient_name"] = name
            if patient_id:
                payload["patient_id"] = patient_id
            requested_type = (
                chat_report_type if chat_report_type != "Any report" else None
            )
            if requested_type:
                payload["report_type"] = requested_type
            if open_report_for_chat(
                payload,
                requested_type=requested_type,
                expected_patient_id=chat_patient_id.strip() or None,
            ):
                st.rerun()

    search_result = st.session_state.get("report_chat_search_result")
    if isinstance(search_result, dict) and search_result.get("status") == "ambiguous":
        candidates = search_result.get("patients") or search_result.get("candidates") or []
        if candidates:
            candidate_labels = [
                f"{candidate.get('name', 'Unknown name')} — "
                f"{candidate.get('patient_id') or candidate.get('id', 'Unknown ID')}"
                for candidate in candidates
            ]
            selected_candidate_label = st.selectbox(
                "Choose the correct patient",
                candidate_labels,
                key="report_chat_patient_choice",
            )
            selected_candidate = candidates[candidate_labels.index(selected_candidate_label)]
            st.caption(
                "The patient ID is shown to help distinguish patients with similar names."
            )
            if st.button(
                "Open selected patient's report",
                type="primary",
                key="open_report_chat_candidate",
            ):
                candidate_patient_id = (
                    selected_candidate.get("patient_id")
                    or selected_candidate.get("id")
                )
                if not candidate_patient_id:
                    st.error("The selected patient has no ID; the report was not opened.")
                else:
                    requested_type = (
                        st.session_state.get("report_chat_report_type")
                        if st.session_state.get("report_chat_report_type") != "Any report"
                        else None
                    )
                    payload = {"patient_id": str(candidate_patient_id)}
                    if requested_type:
                        payload["report_type"] = requested_type
                    if open_report_for_chat(
                        payload,
                        requested_type=requested_type,
                        expected_patient_id=candidate_patient_id,
                    ):
                        st.rerun()

# STEP 16: Add a consistent safety footer
st.divider()

st.caption(
    "VI-SCAN Dental Assistant | Synthetic data only | "
    "Not for diagnosis | Clinician review required"
)