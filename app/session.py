"""Server-side conversation memory.

The old design trusted a `previous_result` blob sent by the client, which let
a caller forge the "selected report". Now the server remembers which patient /
report is active, keyed by session_id, and re-reads the report from the
dataset every time.
"""
import re
import threading
import time
import uuid
from dataclasses import dataclass, field

from app.config import get_settings

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


@dataclass
class SessionState:
    session_id: str
    patient_id: str | None = None
    patient_name: str | None = None
    gender: str | None = None
    report_id: str | None = None
    pending_candidates: list = field(default_factory=list)   # waiting for "which patient?"
    pending_report_type: str | None = None
    last_chat_question: str | None = None
    last_chat_report_id: str | None = None
    uploaded_report: dict | None = None
    updated_at: float = field(default_factory=time.time)

    def set_report(self, result):
        report = result["report"]
        self.patient_id, self.patient_name = result["patient_id"], result["patient_name"]
        self.gender, self.report_id = result.get("gender"), report["report_id"]
        self.uploaded_report = None
        self.clear_pending()
        self.clear_chat_context()

    def set_uploaded_report(self, report):
        self.uploaded_report = report
        self.patient_id = None
        self.patient_name = report.get("patient_name")
        self.gender = None
        self.clear_pending()
        self.clear_chat_context()

    def set_pending(self, candidates, report_type):
        self.pending_candidates, self.pending_report_type = list(candidates), report_type

    def clear_pending(self):
        self.pending_candidates, self.pending_report_type = [], None

    def set_chat_context(self, question, report_id):
        self.last_chat_question = question
        self.last_chat_report_id = report_id

    def clear_chat_context(self):
        self.last_chat_question = None
        self.last_chat_report_id = None


class SessionStore:
    def __init__(self):
        self._data, self._lock = {}, threading.Lock()

    def get(self, session_id=None):
        """Return the session for an id (creating it). Invalid ids get a fresh one."""
        ttl, now = get_settings().session_ttl_seconds, time.time()
        with self._lock:
            for sid in [s for s, v in self._data.items() if now - v.updated_at > ttl]:
                del self._data[sid]
            if not session_id or not _ID_RE.match(session_id):
                session_id = uuid.uuid4().hex
            state = self._data.setdefault(session_id, SessionState(session_id))
            state.updated_at = now
            return state

    def clear(self):
        with self._lock:
            self._data.clear()


store = SessionStore()
