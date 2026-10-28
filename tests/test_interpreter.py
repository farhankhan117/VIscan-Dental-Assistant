"""LLM interpretation is untrusted: validated, with rule-based fallback."""
import pytest

from interpreter import interpret, interpret_rules


@pytest.mark.parametrize("text,intent,name,rtype", [
    ("Open Priya's latest OPG report", "open_report", "Priya", "OPG"),
    ("Show me Priya Verma's OPG", "open_report", "Priya Verma", "OPG"),
    ("Get the latest CBCT for Rahul Mehta", "open_report", "Rahul Mehta", "CBCT"),
    ("Open Priya Verma's panoramic report", "open_report", "Priya Verma", "PANORAMIC"),
    ("Open Priya Verma's periapical report", "open_report", "Priya Verma", "PERIAPICAL"),
    ("Summarize her report", "followup_summary", None, None),
    ("Lower right third molar is horizontally impacted", "dictate_finding", None, None),
    ("Is there any periapical lesion?", "ask_question", None, None),
    ("hello there", "unknown", None, None),
])
def test_rule_interpretation(text, intent, name, rtype):
    i = interpret_rules(text)
    assert (i.intent, i.patient_name, i.report_type) == (intent, name, rtype)


@pytest.mark.parametrize("text", [
    "Open Priya Verma's panoramic report",
    "Open Priya Verma's periapical report",
])
def test_assistant_does_not_map_unstored_report_names_to_another_type(client, text):
    result = client.post("/assistant/message", json={"text": text}).json()
    assert result["status"] == "invalid_report_type"


def test_pronoun_is_captured_not_turned_into_a_name():
    i = interpret_rules("Summarize her report")
    assert i.pronoun == "her" and i.context_reference and i.patient_name is None


def good_llm(system, user):
    return {"intent": "open_report", "patient_name": "Priya", "report_type": "opg", "recency": "latest",
            "pronoun": None, "context_reference": False}


def test_valid_llm_output_is_used_and_normalised():
    i = interpret("Open Priya's latest OPG report", good_llm)
    assert i.source == "llm" and i.report_type == "OPG" and i.patient_name == "Priya"


def test_llm_invented_patient_name_is_rejected():
    def hallucinating(system, user):
        return {**good_llm(system, user), "patient_name": "Priya Kapoor"}   # 'Kapoor' was never said
    i = interpret("Open Priya's latest OPG report", hallucinating)
    assert i.source == "rules" and "not present in the utterance" in i.fallback_reason
    assert i.patient_name == "Priya"


def test_llm_cannot_substitute_opg_for_spoken_panoramic_label():
    def maps_synonym_to_opg(system, user):
        return {**good_llm(system, user), "report_type": "OPG"}

    i = interpret("Open Priya's panoramic report", maps_synonym_to_opg)
    assert i.source == "rules" and i.report_type == "PANORAMIC"


@pytest.mark.parametrize("bad", [
    lambda s, u: {"intent": "delete_everything"},                       # not an allowed intent
    lambda s, u: {"intent": "open_report", "report_type": "MRI"},       # unsupported type
    lambda s, u: {"intent": "open_report", "recency": "yesterday"},     # schema violation
])
def test_invalid_llm_output_falls_back_to_rules(bad):
    i = interpret("Open Priya Verma's OPG", bad)
    assert i.source == "rules" and i.intent == "open_report"


def test_llm_outage_falls_back_to_rules():
    def down(system, user):
        raise TimeoutError("provider timed out")
    i = interpret("Open Priya Verma's OPG", down)
    assert i.source == "rules" and i.patient_name == "Priya Verma" and "TimeoutError" in i.fallback_reason
