"""Report-grounded chat plus general dental education.

Report answers are extractive and cite exact evidence; the general-education
path receives only the question, never the selected or uploaded report.
"""
import re

from app.conversation import evidence_for
from app.llm import LLMError
from app.validators import is_clinical_judgment_question
from app.vocab import concepts, content_stems, find_sites

_GENERIC = re.compile(
    r"\b(findings?|impression|details?|observations?|summar\w*|analy[sz]\w*|review|"
    r"describ\w*|explain\w*|list|"
    r"(?:tell|show|give)\s+me\s+(?:everything|all(?:\s+the)?\s+(?:details?|findings?|observations?))|"
    r"tell\s+me\s+(?:about|what)|what(?:'s|\s+is|\s+are)\s+(?:in|written|recorded)|"
    r"what\s+can\s+you\s+tell\s+me|what\s+is\s+(?:important|the\s+main\s+(?:finding|point))|"
    r"what\s+(?:is|are)\s+(?:mentioned|recorded|written)\s+(?:in|about)\s+(?:(?:this|the)\s+)?report|"
    r"what\s+(?:does|did)\s+(?:(?:this|the)\s+)?report\s+(?:say|show|state|contain|include|mention)|"
    r"what\s+(?:(?:this|the)\s+)?report\s+mentions?)\b",
    re.I,
)
_META = re.compile(r"\b(which\s+report|report\s+id|what\s+type|which\s+type|what\s+date|which\s+date|when\s+was|date\s+of)\b", re.I)
_CONTEXTUAL_FOLLOWUP = re.compile(
    r"^\s*(?:(?:and|but|also)\s+)?(?:what\s+about|how\s+about|and|also|what\s+else|"
    r"tell\s+me\s+more|explain\s+(?:that|it)|does\s+it|is\s+it|was\s+it)\b",
    re.I,
)
_SPECIFIC_TOPIC = re.compile(
    r"\b(?:about|regarding|concerning|around|on|at)\s+"
    r"(?!this\s+report\b|the\s+report\b|report\b)[a-z0-9]+\b",
    re.I,
)
_GENERAL_EDUCATION = re.compile(
    r"\b(?:what\s+(?:is|are|does)\b|meaning\s+of\b|"
    r"how\s+(?:do|can|does|should)\b|why\s+(?:does|do|is|are)\b|"
    r"explain\b|tips?\s+for\b)\s*",
    re.I,
)
_REPORT_REFERENCE = re.compile(
    r"\b(?:report|scan|x[\s-]?ray|recorded|mentioned|source\s+document|"
    r"this\s+finding|these\s+findings|in\s+the\s+file)\b",
    re.I,
)
_REPORT_FACT_QUESTION = re.compile(
    r"^\s*(?:is|are|does|do|did|was|were|has|have|"
    r"can\s+you\s+(?:find|see|confirm)|is\s+there|are\s+there)\b",
    re.I,
)

_GENERAL_DENTAL_SYSTEM = (
    "You are a dental-health education assistant. Answer the user's general question "
    "clearly and concisely. If it is unrelated to dental health, say you specialize in "
    "dental-health education. Do not diagnose, prescribe, estimate prognosis, or recommend "
    "individual treatment. Explain uncertainty and encourage a licensed dentist to assess "
    "personal symptoms. For severe facial swelling, difficulty breathing or swallowing, "
    "uncontrolled bleeding, or major trauma, advise urgent in-person care. This is general "
    "education, not a diagnosis. Return a JSON object with one string field named answer."
)


def _answer_general_question(question, report, llm_call):
    base = _base(report) if report else {}
    if not llm_call:
        return {
            **base,
            "status": "llm_unavailable",
            "evidence": [],
            "answer": (
                "General dental education is unavailable because no language model is configured. "
                "Questions about this report can still be answered from its recorded text."
            ),
        }
    try:
        response = llm_call(_GENERAL_DENTAL_SYSTEM, question)
    except LLMError as exc:
        return {
            **base,
            "status": "error",
            "evidence": [],
            "answer": f"General dental information is temporarily unavailable ({exc}).",
        }
    answer = response.get("answer") if isinstance(response, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        return {
            **base,
            "status": "error",
            "evidence": [],
            "answer": "The general dental assistant returned no usable answer. Please try again.",
        }
    return {
        **base,
        "status": "general_education",
        "evidence": [],
        "answer": answer.strip(),
    }


def answer_general_dental_question(question, llm_call=None):
    """Answer general dental education without requiring or sending a report."""
    if not isinstance(question, str) or not question.strip():
        return {"status": "error", "evidence": [], "answer": "Question is required."}
    if is_clinical_judgment_question(question):
        return {
            "status": "unsupported_question",
            "evidence": [],
            "answer": (
                "I can't diagnose, recommend individual treatment, or predict an outcome. "
                "Please discuss personal symptoms and treatment options with a licensed dentist."
            ),
        }
    if (
        _REPORT_REFERENCE.search(question)
        or _REPORT_FACT_QUESTION.search(question)
        or _CONTEXTUAL_FOLLOWUP.search(question)
        or _fdis(question)
    ):
        return {
            "status": "needs_context",
            "evidence": [],
            "answer": "Select or upload the report you are asking about first.",
        }
    return _answer_general_question(question, None, llm_call)


def _fdis(text):
    return {s["fdi_tooth"] for s in find_sites(text) if s["fdi_tooth"]}


def _base(report):
    return {"source_report_id": report["report_id"], "report_type": report.get("report_type"),
            "report_date": report.get("date"), "patient_name": report.get("patient_name")}


def answer_question_from_report(question, report, context_question=None, llm_call=None):
    if not report:
        return {"status": "needs_context", "message": "Please select a valid report first."}
    if not isinstance(question, str) or not question.strip():
        return {"status": "error", "message": "Question is required."}
    base = _base(report)
    findings = report.get("findings", [])

    if _META.search(question):
        return {**base, "status": "success", "evidence": [],
                "answer": f"This is report {report['report_id']}: {report.get('report_type')} dated "
                          f"{report.get('date')} for {report.get('patient_name')} ({report.get('patient_id')})."}

    if is_clinical_judgment_question(question):
        return {**base, "status": "unsupported_question", "evidence": evidence_for(report),
                "answer": "That needs clinical judgment (prognosis, treatment or advice), which the report "
                          "does not state and I will not infer. The recorded findings are shown for your review."}

    if (
        _GENERAL_EDUCATION.search(question)
        and not _REPORT_REFERENCE.search(question)
        and not _CONTEXTUAL_FOLLOWUP.search(question)
    ):
        return _answer_general_question(question, report, llm_call)

    q_concepts, q_fdis, q_stems = concepts(question), _fdis(question), content_stems(question)
    if (
        _GENERIC.search(question)
        and not (q_concepts or q_fdis)
        and not _SPECIFIC_TOPIC.search(question)
    ):
        return {**base, "status": "success", "evidence": evidence_for(report),
                "answer": "The report records: " + " ".join(f"({i}) {t}" for i, t in enumerate(findings, 1))
                          if findings else "The report contains no recorded findings."}

    if context_question and _CONTEXTUAL_FOLLOWUP.search(question):
        q_concepts |= concepts(context_question)
        q_fdis |= _fdis(context_question)
        q_stems |= content_stems(context_question)
    scored = []
    for i, text in enumerate(findings, 1):
        c_hit, f_hit = concepts(text) & q_concepts, _fdis(text) & q_fdis
        s_hit = content_stems(text) & q_stems if not (q_concepts or q_fdis) else set()
        scored.append((i, bool(c_hit), bool(f_hit), bool(s_hit)))

    if q_concepts and q_fdis:                      # must match both the finding and the tooth
        hits = [i for i, c, f, _ in scored if c and f]
        related = [i for i, c, f, _ in scored if (c or f) and i not in hits]
        if not hits:
            return {**base, "status": "not_in_report", "evidence": evidence_for(report, set(related)),
                    "answer": "The report has no statement matching both that finding and that tooth. "
                              "This is not confirmation that it is absent. Related statements (if any) are shown."}
    else:
        hits = [i for i, c, f, s in scored if c or f or s]

    if not hits:
        if (
            llm_call
            and not _REPORT_REFERENCE.search(question)
            and not _REPORT_FACT_QUESTION.search(question)
            and not _CONTEXTUAL_FOLLOWUP.search(question)
            and not q_fdis
        ):
            return _answer_general_question(question, report, llm_call)
        topic = ", ".join(sorted(q_concepts)) or "that topic"
        return {**base, "status": "not_in_report", "evidence": [],
                "answer": f"This report does not mention {topic}. That is not confirmation that it is absent; "
                          "please check the source report."}
    quotes = " ".join(f"\u201c{findings[i - 1]}\u201d" for i in hits)
    return {**base, "status": "success", "evidence": evidence_for(report, set(hits)),
            "answer": f"The report states: {quotes}"}
