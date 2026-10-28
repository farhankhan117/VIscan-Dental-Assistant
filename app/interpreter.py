"""Step 1 of the pipeline: turn free text into {intent, entities}.

The LLM (if configured) only *interprets*. Whatever it returns is parsed with
Pydantic and checked by validators.validate_interpretation(); on any failure
(timeout, bad JSON, invented patient name, ...) we fall back to the
deterministic rules below. Nothing here touches patient data.
"""
import re
from typing import Literal, Optional

from pydantic import BaseModel

from app.validators import validate_interpretation
from app.vocab import extract_report_type, find_observations, find_sites, normalize_report_type

Intent = Literal["open_report", "dictate_finding", "followup_summary", "ask_question", "unknown"]


class Interpretation(BaseModel):
    intent: Intent = "unknown"
    patient_name: Optional[str] = None
    report_type: Optional[str] = None
    recency: Literal["latest", "earlier"] = "latest"
    pronoun: Optional[str] = None          # she/her/he/him/his/they/it as spoken
    context_reference: bool = False        # "this report", "her", "the same patient"
    source: Literal["llm", "rules"] = "rules"
    fallback_reason: Optional[str] = None


# ----------------------------------------------------------------- rule-based
_VERBS = r"open|show|get|fetch|find|pull\s+up|bring\s+up|display|retrieve|load|view"
_OPEN = re.compile(rf"\b(?:{_VERBS})\b", re.I)
_SUMMARY = re.compile(r"\bsummar\w*", re.I)
_QUESTION = re.compile(r"^\W*(?:(?:please|hey|ok|okay)\s+)?(?:is|are|does|do|did|was|were|what|which|where|when|why|"
                       r"how|any|can|could|will|would|should|has|have|tell\s+me)\b", re.I)
_REPORT_Q = re.compile(r"\b(?:findings?|impression|says?|mention\w*)\b", re.I)
_GENDERED = re.compile(r"\b(she|her|hers|he|him|his)\b", re.I)
_CONTEXT = re.compile(r"\b(?:this|that|same|current|selected)\s+(?:patient|report|one)\b|\b(?:they|their|them|it|its)\b", re.I)
_EARLIER = re.compile(r"\b(?:previous|earlier|older|oldest|first)\b", re.I)
_IDS = re.compile(r"\b[PR]\d{3,}\b")

_FILLERS = {"me", "the", "a", "an", "up", "please", "latest", "last", "recent", "newest", "previous", "earlier",
            "older", "oldest", "first", "summary", "of", "to", "for", "on"}
_UNSUPPORTED_TYPE = re.compile(
    r"\b(mri|ct|ultrasound|cephalogram|ceph|photo|photograph|panoramic|panorama|pano|"
    r"orthopantomo\w*)\b",
    re.I,
)
_UNSTORED_PERIAPICAL_TYPE = re.compile(r"\bperiapical\b", re.I)
_STOP = {"mri", "ct", "ultrasound", "cephalogram", "ceph", "photo", "photograph", "opg", "iopa", "cbct", "bitewing", "bite", "wing", "panoramic", "periapical", "x", "ray", "xray",
         "report", "reports", "scan", "scans", "record", "records", "file", "and", "with", "from", "please",
         "her", "his", "him", "she", "he", "their", "it", "this", "that", "s"}
_VERB_TOKENS = {"open", "show", "get", "fetch", "find", "pull", "bring", "display", "retrieve", "load", "view",
                "summarize", "summarise", "summary", "summarizing"}


def _tokens(text):
    return re.findall(r"[A-Za-z][A-Za-z0-9.'\-]*", text.replace("\u2019", "'"))


def _clean(tok):
    return re.sub(r"'s$", "", tok).strip(".'-")


def _collect(tokens):
    name = []
    for tok in tokens:
        c = _clean(tok)
        if c.casefold() in _STOP or not c or _IDS.fullmatch(c.upper()):
            break
        if not name and c.casefold() in _FILLERS:
            continue
        if c.casefold() in _FILLERS:
            break
        name.append(c)
        if len(name) == 4 or tok.endswith(("'s", "\u2019s")):
            break
    return " ".join(name) or None


def _extract_name(text):
    toks = _tokens(text)
    low = [t.casefold() for t in toks]
    for i, t in enumerate(low):                      # strategy B: name right after the verb
        if t in _VERB_TOKENS:
            name = _collect(toks[i + 1:])
            if name:
                return name
    for i, t in enumerate(low):                      # strategy A: "... of/for <name>"
        if t in {"of", "for"}:
            name = _collect(toks[i + 1:])
            if name:
                return name
    return None


def interpret_rules(text):
    t = text.strip()
    pron = _GENDERED.search(t)
    ctx_only = _CONTEXT.search(t)
    unsupported = _UNSUPPORTED_TYPE.search(t)
    if unsupported is None and _OPEN.search(t):
        unsupported = _UNSTORED_PERIAPICAL_TYPE.search(t)
    base = dict(
        # an unsupported type (e.g. MRI) is kept as-is so the tool layer rejects it, never silently ignored
        report_type=extract_report_type(t) or (unsupported.group(0).upper() if unsupported else None),
        recency="earlier" if _EARLIER.search(t) else "latest",
        pronoun=pron.group(1).lower() if pron else (ctx_only.group(0).lower() if ctx_only and ctx_only.group(0).lower() in {"they", "their", "them", "it", "its"} else None),
        context_reference=bool(pron or ctx_only),
        source="rules",
    )
    if _SUMMARY.search(t):
        intent = "followup_summary"
    elif _OPEN.search(t) and (extract_report_type(t) or _extract_name(t) or base["context_reference"] or _IDS.search(t)):
        intent = "open_report"
    elif _QUESTION.search(t) or t.endswith("?") or _REPORT_Q.search(t):
        intent = "ask_question"
    elif find_observations(t) or find_sites(t):
        intent = "dictate_finding"
    else:
        intent = "unknown"
    name = _extract_name(t) if intent in {"open_report", "followup_summary"} else None
    return Interpretation(intent=intent, patient_name=name, **base)


# ------------------------------------------------------------------ LLM-based
INTERPRETER_SYSTEM = """You are the intent parser for a dental clinic voice assistant.
You do NOT answer questions and do NOT look anything up. You only classify the request and extract entities.
Return ONLY one JSON object with exactly these keys:
{"intent": "open_report" | "dictate_finding" | "followup_summary" | "ask_question" | "unknown",
 "patient_name": string or null,
 "report_type": "OPG" | "IOPA" | "Bitewing" | "CBCT" | null,
 "recency": "latest" | "earlier",
 "pronoun": "she" | "her" | "he" | "him" | "his" | "they" | "it" | null,
 "context_reference": true | false}
Definitions:
- open_report: the clinician wants to open / find a patient's report.
- dictate_finding: the clinician is stating a clinical observation to be recorded.
- followup_summary: asks for a summary of a report.
- ask_question: asks a question about the content of a report.
- unknown: anything else.
Rules: patient_name must be copied exactly from the text (first name only is fine); never guess, complete or
correct a name. Only use a report type if the clinician used its exact stored label; never convert synonyms such
as "panoramic" to OPG or "periapical" to IOPA. If the text refers to someone with a pronoun or "this report", set pronoun / context_reference
and leave patient_name null. Use null when a field is not stated."""

_FIELDS = ("intent", "patient_name", "report_type", "recency", "pronoun", "context_reference")


def interpret_llm(text, llm_call):
    data = llm_call(INTERPRETER_SYSTEM, text)
    clean = {k: data[k] for k in _FIELDS if data.get(k) is not None}
    if clean.get("report_type"):
        canonical, valid = normalize_report_type(clean["report_type"])
        clean["report_type"] = canonical if valid else clean["report_type"]
    if isinstance(clean.get("pronoun"), str):
        clean["pronoun"] = clean["pronoun"].lower()
    interp = Interpretation(**clean, source="llm")
    problems = validate_interpretation(text, interp)
    if problems:
        raise ValueError("; ".join(problems))
    return interp


def interpret(text, llm_call=None):
    """LLM first (if available and valid), deterministic rules otherwise."""
    if llm_call is None:
        return interpret_rules(text)
    try:
        return interpret_llm(text, llm_call)
    except Exception as exc:  # timeout, bad JSON, schema error, failed validation...
        fallback = interpret_rules(text)
        fallback.fallback_reason = f"LLM interpretation rejected ({type(exc).__name__}: {str(exc)[:120]})"
        return fallback
