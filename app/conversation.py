"""Feature C: context-dependent follow-ups ("Summarize her report").

The active patient/report lives in the server-side session, never in a
client-supplied blob. A pronoun is resolved only when it is unambiguous:
  * there is an active report, and
  * the pronoun's gender does not contradict the active patient.
Otherwise we ask instead of guessing.
"""
from app.retrieval import get_report_by_id
from app.validators import pronoun_conflicts


def evidence_for(report, only=None):
    """Evidence entries: which report, and which recorded statement."""
    rows = []
    for i, text in enumerate(report.get("findings", []), 1):
        if only is None or i in only:
            rows.append({"report_id": report["report_id"], "report_type": report.get("report_type"),
                         "report_date": report.get("date"), "finding_index": i, "text": text})
    return rows


def resolve_context(session, pronoun=None):
    """Return (report, error_response). Exactly one is None."""
    if session.report_id is None:
        if session.pending_candidates:
            return None, {"status": "ambiguous", "message": "Which patient do you mean? Please choose one first.",
                          "patients": session.pending_candidates}
        return None, {"status": "needs_context",
                      "message": "No report is selected yet. Open a patient's report first, e.g. "
                                 "\"Open Priya Verma's latest OPG report\"."}
    if pronoun_conflicts(pronoun, session.gender):
        return None, {"status": "needs_clarification",
                      "message": f"'{pronoun}' doesn't match the active patient ({session.patient_name}). "
                                 "Which patient do you mean?"}
    report = get_report_by_id(session.report_id)
    if report is None:
        return None, {"status": "error", "message": "The active report is no longer available."}
    return report, None


def summarize_report(report):
    """Extractive summary: restates only what the report recorded, nothing added."""
    findings = report.get("findings", [])
    head = (f"{report.get('report_type')} report dated {report.get('date')} for "
            f"{report.get('patient_name')} ({report.get('patient_id')})")
    if not findings:
        return f"{head} contains no recorded findings."
    numbered = " ".join(f"({i}) {t}" for i, t in enumerate(findings, 1))
    return f"{head} records {len(findings)} finding{'s' if len(findings) != 1 else ''}: {numbered}"


def handle_follow_up(message, session, interpretation=None):
    pronoun = interpretation.pronoun if interpretation else None
    report, error = resolve_context(session, pronoun)
    if error:
        return error
    if "summar" not in message.casefold():
        return {"status": "unsupported_request",
                "message": "I can summarize the selected report. For other questions, ask about its content "
                           "(e.g. \"What does the report say about caries?\")."}
    answer = summarize_report(report)
    note = (f"Resolved '{pronoun}' to {report['patient_name']} ({report['patient_id']}) from the report opened earlier."
            if pronoun else f"Used the active report for {report['patient_name']} ({report['patient_id']}).")
    return {"status": "success", "patient_id": report["patient_id"], "patient_name": report["patient_name"],
            "report_id": report["report_id"], "report_type": report.get("report_type"), "report_date": report.get("date"),
            "answer": answer, "summary": answer, "source_findings": report.get("findings", []),
            "evidence": evidence_for(report), "context_resolution": note}
