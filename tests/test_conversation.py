"""Feature C: context-dependent follow-ups."""
import pytest

from assistant import handle_message
import assistant as assistant_module
from session import store

NO_LLM = dict(llm_call=None)


def open_priya_verma():
    r = handle_message("Open Priya Verma's latest OPG report", **NO_LLM)
    assert r["status"] == "success"
    return r["session_id"]


def test_her_resolves_without_asking_again_and_shows_evidence():
    sid = open_priya_verma()
    r = handle_message("Summarize her report", session_id=sid, **NO_LLM)
    assert r["status"] == "success" and r["patient_name"] == "Priya Verma"
    assert r["report_id"] == r["evidence"][0]["report_id"]                 # evidence names the source report
    assert r["sources"][0]["report_id"] == r["report_id"]
    assert "Resolved 'her'" in r["context_resolution"]
    for finding in r["source_findings"]:                                    # extractive: nothing added
        assert finding in r["summary"]


def test_report_detail_followups_use_opened_report_without_searching_again(monkeypatch):
    opened = handle_message("Open Priya Verma's latest OPG report", **NO_LLM)
    sid = opened["session_id"]
    searches = []
    real_open = assistant_module.open_patient_report

    def track_search(*args, **kwargs):
        searches.append((args, kwargs))
        return real_open(*args, **kwargs)

    def misclassify_as_open_report(system, user):
        return {
            "intent": "open_report",
            "patient_name": None,
            "report_type": None,
            "recency": "latest",
            "pronoun": "it",
            "context_reference": True,
        }

    monkeypatch.setattr(assistant_module, "open_patient_report", track_search)
    questions = (
        ("What are the details of this report?", misclassify_as_open_report),
        ("Tell me the findings in the report", None),
        ("What does this report show?", None),
    )
    for question, llm_call in questions:
        result = handle_message(question, session_id=sid, llm_call=llm_call)
        assert result["status"] == "success"
        assert result["interpretation"]["intent"] == "ask_question"
        assert result["source_report_id"] == opened["report"]["report_id"]
        assert result["sources"][0]["report_id"] == opened["report"]["report_id"]
        assert "OPG report dated" in result["answer"] or "report records" in result["answer"]
    assert searches == []


def test_explicit_new_report_request_still_searches_for_requested_report(monkeypatch):
    opened = handle_message("Open Priya Verma's latest OPG report", **NO_LLM)
    sid = opened["session_id"]
    searches = []
    real_open = assistant_module.open_patient_report

    def track_search(*args, **kwargs):
        searches.append(kwargs)
        return real_open(*args, **kwargs)

    monkeypatch.setattr(assistant_module, "open_patient_report", track_search)
    result = handle_message("Open her CBCT report", session_id=sid, **NO_LLM)
    assert result["status"] == "success"
    assert result["report"]["report_type"] == "CBCT"
    assert searches == [{"patient_id": "P002", "report_type": "CBCT"}]


def test_without_context_it_asks_instead_of_guessing():
    r = handle_message("Summarize her report", **NO_LLM)
    assert r["status"] == "needs_context"


def test_pronoun_that_contradicts_patient_gender_asks():
    sid = open_priya_verma()
    r = handle_message("Summarize his report", session_id=sid, **NO_LLM)
    assert r["status"] == "needs_clarification"


def test_unresolved_ambiguity_blocks_pronoun_follow_up():
    r = handle_message("Open Priya's OPG", **NO_LLM)
    assert r["status"] == "ambiguous"
    follow = handle_message("Summarize her report", session_id=r["session_id"], **NO_LLM)
    assert follow["status"] == "ambiguous" and len(follow["patients"]) == 3


def test_ambiguity_resolved_by_patient_id_then_follow_up_works():
    r = handle_message("Open Priya Sharma's OPG", **NO_LLM)
    sid = r["session_id"]
    chosen = handle_message("select", session_id=sid, patient_id="P021", **NO_LLM)
    assert chosen["status"] == "success" and chosen["report"]["patient_id"] == "P021"
    assert chosen["report"]["report_type"] == "OPG"                         # remembered the original request
    summary = handle_message("Summarize her report", session_id=sid, **NO_LLM)
    assert summary["patient_id"] == "P021"


@pytest.mark.parametrize(
    "patient_name,spoken_id,expected_id",
    [
        ("Priya", "P zero zero one", "P001"),
        ("Priya", "patient ID P zero zero two", "P002"),
        ("Priya", "P zero twenty one", "P021"),
        ("Priya", "P 0 2 1", "P021"),
        ("Priya", "P 0 0 21", "P021"),
        ("Priya", "patient twenty one", "P021"),
        ("Priya Sharma", "P zero zero one", "P001"),
        ("Priya Sharma", "P zero twenty one", "P021"),
        ("Rahul Mehta", "P zero zero three", "P003"),
        ("Rahul Mehta", "P zero twenty six", "P026"),
        ("Aisha Khan", "P zero zero four", "P004"),
        ("Aisha Khan", "P zero thirty one", "P031"),
        ("Arjun Singh", "P zero zero five", "P005"),
        ("Arjun Singh", "P zero thirty six", "P036"),
    ],
)
def test_spoken_patient_id_selects_pending_duplicate_name_and_keeps_context(
    patient_name, spoken_id, expected_id
):
    ambiguous = handle_message(f"Open {patient_name} latest OPG report", **NO_LLM)
    assert ambiguous["status"] == "ambiguous"
    assert expected_id in {item["patient_id"] for item in ambiguous["patients"]}

    selected = handle_message(spoken_id, session_id=ambiguous["session_id"], **NO_LLM)
    assert selected["status"] == "success"
    assert selected["patient_id"] == expected_id
    assert selected["report"]["patient_id"] == expected_id
    assert selected["report"]["report_type"] == "OPG"

    follow_up = handle_message("What are the details of this report?", session_id=ambiguous["session_id"], **NO_LLM)
    assert follow_up["status"] == "success"
    assert follow_up["source_report_id"] == selected["report"]["report_id"]
    assert follow_up["sources"][0]["patient_id"] == expected_id


def test_spoken_id_must_match_one_of_the_pending_candidates():
    ambiguous = handle_message("Open Priya's latest OPG report", **NO_LLM)
    response = handle_message("P zero nine nine", session_id=ambiguous["session_id"], **NO_LLM)

    assert response["status"] == "ambiguous"
    assert "choose one" in response["message"]
    assert {item["patient_id"] for item in response["patients"]} == {"P001", "P002", "P021"}
    assert store.get(ambiguous["session_id"]).pending_report_type == "OPG"


def test_spoken_patient_id_works_without_a_pending_duplicate_name():
    for request in (
        "Open patient ID P zero two one OPG",
        "Open patient twenty one OPG",
        "Open P as in patient zero two one OPG",
    ):
        result = handle_message(request, **NO_LLM)
        assert result["status"] == "success"
        assert result["patient_id"] == "P021"
        assert result["report"]["report_type"] == "OPG"


def test_spoken_report_id_opens_the_exact_report():
    opened = handle_message("Open Priya Verma OPG report", **NO_LLM)
    assert opened["status"] == "success"
    for request in ("Open report R zero zero five", "Open report number five", "Open R 0 0 5"):
        result = handle_message(request, session_id=opened["session_id"], **NO_LLM)
        assert result["status"] == "success"
        assert result["report"]["report_id"] == "R005"


def test_ambiguity_resolved_by_ordinal():
    r = handle_message("Open Priya's OPG", **NO_LLM)
    chosen = handle_message("the second one", session_id=r["session_id"], **NO_LLM)
    assert chosen["status"] == "success" and chosen["patient_name"] == "Priya Verma"


def test_ambiguity_can_be_resolved_by_spoken_option_number():
    r = handle_message("Open Priya's OPG", **NO_LLM)
    chosen = handle_message("option two", session_id=r["session_id"], **NO_LLM)
    assert chosen["status"] == "success" and chosen["patient_id"] == "P002"


def test_new_patient_replaces_context():
    sid = open_priya_verma()
    handle_message("Open Rahul Mehta's OPG", session_id=sid, **NO_LLM)       # ambiguous -> context unchanged
    assert store.get(sid).patient_name == "Priya Verma"
    handle_message("Open Aman Saxena's OPG", session_id=sid, **NO_LLM)
    assert store.get(sid).patient_name == "Aman Saxena"


def test_sessions_are_isolated():
    open_priya_verma()
    other = handle_message("Summarize her report", **NO_LLM)                # different, new session
    assert other["status"] == "needs_context"


def test_explicit_name_in_follow_up_overrides_context():
    sid = open_priya_verma()
    r = handle_message("Summarize Aman Saxena's latest OPG", session_id=sid, **NO_LLM)
    assert r["status"] == "success" and r["patient_name"] == "Aman Saxena"


def test_off_topic_follow_up_gets_no_made_up_answer():
    sid = open_priya_verma()
    r = handle_message("Tell me the weather", session_id=sid, **NO_LLM)
    assert r["status"] in {"unsupported_request", "not_in_report"} and not r.get("evidence")



def test_pronoun_open_uses_session_patient():
    sid = open_priya_verma()
    r = handle_message("Show me her CBCT", session_id=sid, **NO_LLM)
    assert r["status"] == "success" and r["report"]["report_type"] == "CBCT" and r["patient_id"] == "P002"
