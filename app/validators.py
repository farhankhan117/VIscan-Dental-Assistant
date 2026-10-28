"""Business-rule validation that sits between the LLM and the tools.

The LLM proposes ("this looks like an open_report request for 'Priya'").
Code in this file decides whether that proposal is acceptable before any
tool runs.
"""
import re


from app.vocab import normalize_report_type
from app.config import get_settings

ALLOWED_INTENTS = {"open_report", "dictate_finding", "followup_summary", "ask_question", "unknown"}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_NAME_OK = re.compile(r"^[A-Za-z][A-Za-z .'\-]{0,59}$")
_UNSTORED_REPORT_LABEL = re.compile(
    r"\b(?:panoramic|panorama|pano|orthopantomo\w*|periapical)\b",
    re.I,
)
PRONOUN_GENDER = {"she": "F", "her": "F", "hers": "F", "he": "M", "him": "M", "his": "M"}


def validate_text_input(text):
    """Return (clean_text, error_message). Exactly one of them is None."""
    if not isinstance(text, str):
        return None, "Input must be text."
    clean = _CONTROL.sub("", text).strip()
    if not clean:
        return None, "Input is empty."
    limit = get_settings().max_input_chars
    if len(clean) > limit:
        return None, f"Input is too long ({len(clean)} characters; limit {limit})."
    return clean, None


def validate_interpretation(text, interp):
    """Return a list of problems with an LLM-produced interpretation ([] = OK).

    Key guard: every word of a patient name the model returns must literally
    appear in what the clinician said, so a model cannot invent a patient.
    """
    problems = []
    if interp.intent not in ALLOWED_INTENTS:
        problems.append(f"intent '{interp.intent}' not allowed")
    if interp.patient_name:
        if not _NAME_OK.match(interp.patient_name):
            problems.append("patient_name has invalid characters or length")
        spoken = set(re.findall(r"[a-z]+", text.casefold()))
        missing = [w for w in re.findall(r"[a-z]+", interp.patient_name.casefold()) if w not in spoken]
        if missing:
            problems.append(f"patient_name words not present in the utterance: {missing}")
    if interp.report_type:
        _, valid = normalize_report_type(interp.report_type)
        if not valid:
            problems.append(f"report_type '{interp.report_type}' not supported")
    if interp.intent == "open_report" and _UNSTORED_REPORT_LABEL.search(text):
        problems.append("report type must use its exact stored label")
    return problems


def pronoun_conflicts(pronoun, gender):
    """True if a gendered pronoun contradicts the active patient's gender."""
    expected = PRONOUN_GENDER.get((pronoun or "").lower())
    return bool(expected and gender and expected != gender)


_JUDGMENT = re.compile(
    r"\b(will|should|would|needs?|needed|recommend\w*|advis\w*|prognos\w*|diagnos\w*|surgery|surgical|urgent\w*|"
    r"risks?|prescri\w*|medication|antibiotics?|next\s+step|what\s+to\s+do|how\s+long|cost)\b", re.I)
_LOOKUP = re.compile(r"\b(mention\w*|say|says|state[sd]?|record\w*|note[sd]?|list\w*)\b", re.I)


def is_clinical_judgment_question(question):
    """Questions that ask for advice / prediction rather than what the report says."""
    return bool(_JUDGMENT.search(question)) and not _LOOKUP.search(question)
