"""Pipeline orchestrator:  text -> interpret (LLM, validated) -> route -> tools -> response.

Every response carries the interpretation that was used (transparency), a
`sources` list (which report the answer came from) and the latency.
"""
import logging
import re
import time

from app.clinical_draft import create_clinical_draft
from app.conversation import handle_follow_up, resolve_context
from app.interpreter import Interpretation, interpret
from app.llm import get_llm_call
from app.report_chatbot import answer_question_from_report
from app.retrieval import get_report_by_id, open_patient_report, open_report_by_id, patients, reports
from app.session import store
from app.validators import pronoun_conflicts, validate_text_input

log = logging.getLogger("viscan.assistant")
_PID, _RID = re.compile(r"\bP\d{3,}\b", re.I), re.compile(r"\bR\d{3,}\b", re.I)
_ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3}
_OPTION_NUMBERS = {
    "one": 0, "1": 0, "first": 0, "1st": 0,
    "two": 1, "2": 1, "second": 1, "2nd": 1,
    "three": 2, "3": 2, "third": 2, "3rd": 2,
    "four": 3, "4": 3, "fourth": 3, "4th": 3,
}
_SPOKEN_DIGITS = {
    "zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2", "to": "2", "too": "2", "three": "3",
    "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
_SPOKEN_TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_SPOKEN_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_ID_FILLERS = {"as", "in", "is", "number", "no", "id", "the", "code", "patient", "report"}
_OPEN_VERB = re.compile(r"\b(?:open|show|find|fetch|pull up|bring up|display|retrieve|load|view)\b", re.I)
_QUESTION_SHAPE = re.compile(
    r"^\W*(?:(?:please|hey|ok|okay)\s+)?(?:is|are|does|do|did|was|were|what|which|where|when|why|"
    r"how|any|can|could|will|would|should|has|have|tell\s+me)\b",
    re.I,
)
_REPORT_DETAIL_REQUEST = re.compile(
    r"\b(?:details?|findings?|impression|observations?|report\s+(?:say|says|show|shows|contain|contains|"
    r"include|includes|detail|details)|tell\s+me\s+about)\b",
    re.I,
)
_DEFAULT = object()


def _spoken_digits(tokens):
    """Convert spoken/recognized number words into ID digits."""
    digits = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.isdigit():
            digits.extend(token)
            index += 1
        elif token in _SPOKEN_DIGITS:
            digits.append(_SPOKEN_DIGITS[token])
            index += 1
        elif token in _SPOKEN_TEENS:
            digits.extend(str(_SPOKEN_TEENS[token]))
            index += 1
        elif token in _SPOKEN_TENS:
            number = _SPOKEN_TENS[token]
            if index + 1 < len(tokens) and tokens[index + 1] in _SPOKEN_DIGITS:
                number += int(_SPOKEN_DIGITS[tokens[index + 1]])
                index += 1
            digits.extend(str(number))
            index += 1
        else:
            break
    return "".join(digits)


def _spoken_code(text, prefix, known_ids):
    """Resolve spoken letter/digit codes only when they match one known ID."""
    known_ids = {str(value).upper() for value in known_ids}
    direct = re.search(rf"\b{re.escape(prefix)}\s*[- ]?\s*(\d{{1,3}})\b", text, re.I)
    if direct:
        normalized = f"{prefix}{direct.group(1).zfill(3)}".upper()
        if normalized in known_ids:
            return normalized

    tokens = re.findall(r"[a-z]+|\d+", text.casefold().replace("-", " "))
    markers = {
        prefix.casefold(),
        *({"pee", "pea"} if prefix.upper() == "P" else {"are"}),
    }
    starts = [index + 1 for index, token in enumerate(tokens) if token in markers]
    starts.extend(
        index + 1 for index, token in enumerate(tokens)
        if token in {"id", "number", "no"} and index + 1 < len(tokens)
    )
    if prefix.upper() == "P":
        starts.extend(index + 1 for index, token in enumerate(tokens) if token == "patient")
        starts.extend(
            index + 1 for index, token in enumerate(tokens)
            if token in {"open", "show", "find", "fetch", "view", "load"}
        )
    elif prefix.upper() == "R":
        starts.extend(index + 1 for index, token in enumerate(tokens) if token == "report")
    if prefix.upper() == "P" and tokens and all(
        token in _SPOKEN_DIGITS or token in _SPOKEN_TEENS or token in _SPOKEN_TENS or token.isdigit()
        for token in tokens
    ):
        starts.append(0)

    possible = set()
    for start in starts:
        while start < len(tokens) and tokens[start] in _ID_FILLERS:
            start += 1
        digits = _spoken_digits(tokens[start:start + 6])
        if digits:
            normalized_digits = digits.lstrip("0") or "0"
            possible.update(
                item for item in known_ids
                if item[1:].lstrip("0") == normalized_digits
            )
    return next(iter(possible)) if len(possible) == 1 else None


def _spoken_candidate_id(text, candidates):
    """Match a spoken patient ID only against the patients awaiting confirmation."""
    candidate_ids = {str(item.get("patient_id", "")).upper() for item in candidates}
    return _spoken_code(text, "P", candidate_ids)


def _spoken_patient_id(text):
    return _spoken_code(text, "P", (item.get("patient_id") for item in patients))


def _spoken_report_id(text):
    direct = _RID.search(text)
    if direct:
        report_id = direct.group(0).upper()
        return report_id if any(item.get("report_id") == report_id for item in reports) else None
    return _spoken_code(text, "R", (item.get("report_id") for item in reports))


def _spoken_candidate_index(text):
    match = re.search(
        r"\b(?:option|choice)\s+(one|two|three|four|1|1st|2|2nd|3|3rd|4|4th)\b",
        text.casefold(),
    )
    return _OPTION_NUMBERS[match.group(1)] if match else None


def apply_open_result(res, session):
    """Update session memory from an open-report result (success / ambiguous only)."""
    if res["status"] == "success":
        session.set_report(res)
    elif res["status"] == "ambiguous":
        session.set_pending(res["patients"], res.get("requested_report_type"))
    return res


def _open(interp, text, session, pid):
    rtype = interp.report_type
    rid = _RID.search(text)
    if rid:
        return apply_open_result(open_report_by_id(rid.group(0).upper()), session)
    if pid:
        res = open_patient_report(patient_id=pid, report_type=rtype)
    elif interp.patient_name:
        res = open_patient_report(patient_name=interp.patient_name, report_type=rtype)
    elif interp.context_reference:
        if not session.patient_id:
            return {"status": "needs_context", "message": "I don't know who you mean yet. Which patient?"}
        if pronoun_conflicts(interp.pronoun, session.gender):
            return {"status": "needs_clarification",
                    "message": f"'{interp.pronoun}' doesn't match the active patient ({session.patient_name}). Which patient?"}
        res = open_patient_report(patient_id=session.patient_id, report_type=rtype)
        if res["status"] == "success":
            res["context_resolution"] = f"Resolved '{interp.pronoun or 'this patient'}' to {res['patient_name']} ({res['patient_id']})."
    else:
        res = {"status": "needs_patient", "message": "Which patient? Please give a name or patient ID."}
    if res["status"] == "success" and interp.recency == "earlier":
        res["message"] = "Showing the latest match. Earlier reports are listed in available_reports; say \"open report R0xx\" for one."
    return apply_open_result(res, session)


def _sources(resp):
    out = []
    rep = resp.get("report")
    if isinstance(rep, dict):
        out.append(rep)
    elif resp.get("report_id") or resp.get("source_report_id"):
        rep = get_report_by_id(resp.get("report_id") or resp.get("source_report_id"))
        if rep:
            out.append(rep)
    return [{"report_id": r["report_id"], "report_type": r.get("report_type"), "date": r.get("date"),
             "patient_id": r.get("patient_id"), "patient_name": r.get("patient_name")} for r in out]


def handle_message(text, session_id=None, patient_id=None, llm_call=_DEFAULT, alternate_text=None):
    t0 = time.perf_counter()
    if llm_call is _DEFAULT:
        llm_call = get_llm_call()
    session = store.get(session_id)
    interp = None

    clean, error = validate_text_input(text)
    if error:
        resp = {"status": "invalid_input", "message": error}
    else:
        try:
            pid = patient_id or (m.group(0).upper() if (m := _PID.search(clean)) else None)
            spoken_rid = _spoken_report_id(clean)
            if not spoken_rid and isinstance(alternate_text, str):
                alternate_clean, alternate_error = validate_text_input(alternate_text)
                if not alternate_error:
                    spoken_rid = _spoken_report_id(alternate_clean)
            if not pid:
                pid = _spoken_patient_id(clean)
            if not pid and isinstance(alternate_text, str):
                alternate_clean, alternate_error = validate_text_input(alternate_text)
                if not alternate_error:
                    pid = _spoken_patient_id(alternate_clean)
            force_open = False
            selection_error = False
            if session.pending_candidates and not spoken_rid:  # the previous turn asked "which patient?"
                ordinal = _spoken_candidate_index(clean)
                if ordinal is None:
                    ordinal = next(
                        (_ORDINALS[w] for w in re.findall(r"[a-z0-9]+", clean.casefold()) if w in _ORDINALS),
                        None,
                    )
                spoken_pid = _spoken_candidate_id(clean, session.pending_candidates)
                if not spoken_pid and isinstance(alternate_text, str):
                    alternate_clean, alternate_error = validate_text_input(alternate_text)
                    if not alternate_error:
                        spoken_pid = _spoken_candidate_id(alternate_clean, session.pending_candidates)
                if ordinal is not None and not pid and not spoken_pid and ordinal < len(session.pending_candidates):
                    pid, force_open = session.pending_candidates[ordinal]["patient_id"], True
                elif spoken_pid:
                    pid, force_open = spoken_pid, True
                elif pid:
                    candidate_ids = {item.get("patient_id") for item in session.pending_candidates}
                    if pid in candidate_ids:
                        force_open = True
                    else:
                        selection_error = True
                elif patient_id:
                    selection_error = True
                elif not re.search(r"\b(?:open|show|find|fetch|pull up|bring up|display|retrieve|load|view)\b", clean, re.I):
                    selection_error = True
            if selection_error:
                interp = Interpretation(intent="open_report", report_type=session.pending_report_type)
                resp = {
                    "status": "ambiguous",
                    "message": "I still need you to choose one of these patients. Please say the patient ID clearly, "
                               "for example, 'P zero two one', or say the option number.",
                    "patients": session.pending_candidates,
                    "requested_report_type": session.pending_report_type,
                }
            elif force_open:
                interp = Interpretation(intent="open_report", report_type=session.pending_report_type)
            else:
                interp = interpret(clean, llm_call)

            explicit_report_lookup = bool(
                _OPEN_VERB.search(clean)
                and (
                    pid
                    or spoken_rid
                    or interp.patient_name
                    or (interp.context_reference and interp.report_type)
                )
            )
            is_report_question = bool(
                _QUESTION_SHAPE.search(clean)
                or clean.rstrip().endswith("?")
                or _REPORT_DETAIL_REQUEST.search(clean)
            )
            if (
                session.report_id
                and not explicit_report_lookup
                and is_report_question
                and interp.intent != "dictate_finding"
            ):
                interp.intent = "ask_question"

            if selection_error:
                pass
            elif spoken_rid:
                interp.intent = "open_report"
                resp = apply_open_result(open_report_by_id(spoken_rid), session)
            elif interp.intent == "open_report":
                resp = _open(interp, clean, session, pid)
            elif interp.intent == "followup_summary":
                if pid or interp.patient_name:
                    resp = _open(interp, clean, session, pid)
                    if resp["status"] == "success":
                        resp = handle_follow_up(clean, session, None)
                else:
                    resp = handle_follow_up(clean, session, interp)
            elif interp.intent == "ask_question":
                report, err = resolve_context(session, interp.pronoun)
                resp = err or answer_question_from_report(
                    clean,
                    report,
                    llm_call=llm_call,
                )
            elif interp.intent == "dictate_finding":
                resp = create_clinical_draft(clean, llm_call=llm_call)
            else:
                resp = {"status": "unsupported_request",
                        "message": "I couldn't understand that request. Please rephrase it in English."}
        except Exception:                                  # never leak internals to the client
            log.exception("assistant pipeline failure")
            resp = {"status": "error", "message": "Something went wrong while processing the request."}

    latency = round((time.perf_counter() - t0) * 1000, 1)
    resp["session_id"] = session.session_id
    resp["interpretation"] = interp.model_dump() if interp else None
    resp["sources"] = _sources(resp)
    resp["latency_ms"] = latency
    log.info("intent=%s status=%s source=%s latency_ms=%s", interp.intent if interp else None,
             resp.get("status"), interp.source if interp else None, latency)   # no PHI in logs
    return resp
