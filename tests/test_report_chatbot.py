"""Bonus chatbot: grounded answers only. Unsupported questions must not be guessed."""
import pytest

from report_chatbot import answer_question_from_report as ask
from retrieval import get_report_by_id

REPORT = get_report_by_id("R005")      # Priya Verma OPG 2026-05-20: impaction 38, RCT 26, periapical radiolucency 36


def test_answer_is_the_reports_own_sentence_with_evidence():
    r = ask("Is the lower left third molar impacted?", REPORT)
    assert r["status"] == "success"
    assert "Lower left third molar (38) is horizontally impacted." in r["answer"]
    assert r["evidence"][0]["finding_index"] == 1 and r["source_report_id"] == "R005"


def test_topic_not_in_report_is_declined_not_guessed():
    r = ask("Is there a fracture?", REPORT)
    assert r["status"] == "not_in_report" and r["evidence"] == []
    assert "not confirmation that it is absent" in r["answer"]


def test_tooth_specific_question_does_not_borrow_another_tooths_finding():
    r = ask("Is there caries on tooth 36?", REPORT)              # report has a lesion at 36 but no caries
    assert r["status"] == "not_in_report"


def test_negated_statement_is_quoted_not_converted_to_yes():
    negated = {**REPORT, "findings": ["No periapical radiolucency is seen."]}
    r = ask("Is there any periapical lesion?", negated)
    assert "No periapical radiolucency is seen." in r["answer"]
    assert not r["answer"].lower().startswith("yes")


def test_clinical_judgment_is_refused():
    r = ask("Will the patient need surgery?", REPORT)
    assert r["status"] == "unsupported_question" and r["source_report_id"] == "R005"


def test_lookup_style_question_about_surgery_is_not_refused():
    assert ask("Does the report mention surgery?", REPORT)["status"] == "not_in_report"


def test_generic_and_metadata_questions():
    for question in (
        "What does the report say?",
        "Explain this report",
        "List all the findings",
        "What is written in this report?",
        "Analyze this report",
        "What can you tell me?",
    ):
        assert len(ask(question, REPORT)["evidence"]) == 3
    assert "R005" in ask("Which report is this?", REPORT)["answer"]


@pytest.mark.parametrize(
    "question",
    [
        "What does this report mention?",
        "Tell me all details about this report",
        "Give me all findings",
        "Show me everything in this report",
        "What is mentioned about this report?",
    ],
)
def test_natural_report_summary_requests_return_grounded_findings(question):
    result = ask(question, REPORT)
    assert result["status"] == "success"
    assert len(result["evidence"]) == len(REPORT["findings"]) == 3


@pytest.mark.parametrize(
    "question",
    [
        "What does the report say about caries?",
        "What does this report mention about surgery?",
    ],
)
def test_report_specific_questions_are_not_misread_as_summary_requests(question):
    result = ask(question, REPORT)
    assert result["status"] == "not_in_report"
    assert result["evidence"] == []


def test_contextual_followup_inherits_prior_topic_and_matches_followup_tooth():
    result = ask(
        "What about tooth 36?",
        REPORT,
        context_question="Is there any periapical lesion?",
    )
    assert result["status"] == "success"
    assert "Periapical radiolucency associated with tooth 36." in result["answer"]
    assert result["evidence"][0]["report_id"] == "R005"


def test_contextual_followup_keeps_prior_finding_constraint():
    result = ask(
        "What about tooth 36?",
        REPORT,
        context_question="Is there caries?",
    )
    assert result["status"] == "not_in_report"
    assert result["evidence"][0]["text"] == "Periapical radiolucency associated with tooth 36."
    assert "matching both that finding and that tooth" in result["answer"]


def test_missing_report_or_question():
    assert ask("What does the report say?", None)["status"] == "needs_context"
    assert ask("  ", REPORT)["status"] == "error"


def test_general_dental_education_does_not_send_report_content_to_model():
    calls = []

    def fake_llm(system, user):
        calls.append((system, user))
        return {"answer": "Fluoride helps strengthen tooth enamel."}

    result = ask("What does fluoride do?", REPORT, llm_call=fake_llm)

    assert result["status"] == "general_education"
    assert "strengthen tooth enamel" in result["answer"]
    assert calls[0][1] == "What does fluoride do?"
    assert "Lower left third molar" not in calls[0][1]


def test_general_education_explicitly_reports_missing_model():
    result = ask("What does fluoride do?", REPORT)
    assert result["status"] == "llm_unavailable"
    assert "no language model is configured" in result["answer"]
