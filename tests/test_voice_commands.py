import pytest

from viscan_voice_commands import navigation_target, voice_route


@pytest.mark.parametrize(
    "command,page",
    [
        ("go to clinical draft", "Clinical Draft"),
        ("move to the clinical draft", "Clinical Draft"),
        ("move to the clinical dfraft", "Clinical Draft"),
        ("Move to the clinical draft or somewhere", "Clinical Draft"),
        ("I want to go to the clinical draft now", "Clinical Draft"),
        ("Can you move me to the clinical draft please", "Clinical Draft"),
        ("Show me the clinical draft", "Clinical Draft"),
        ("Open the clinical dictation page", "Clinical Draft"),
        ("switch to dashboard", "Dashboard"),
        ("take me to patient report search", "Find Patient Report"),
        ("show the report chatbot", "Ask About a Report"),
        ("go to the report chat", "Ask About a Report"),
        ("open voice assistant", "Dashboard"),
        ("switch to the assitant page", "Dashboard"),
        ("go to patient report seach", "Find Patient Report"),
    ],
)
def test_navigation_target_recognizes_workspace_commands(command, page):
    assert navigation_target(command) == page


@pytest.mark.parametrize(
    "command",
    [
        "Open Priya Verma's OPG report",
        "show findings from the report",
        "lower right molar is impacted",
        "go to clinical draft and dictate the findings",
        "move that finding to clinical draft",
    ],
)
def test_navigation_target_does_not_consume_clinical_or_report_commands(command):
    assert navigation_target(command) is None


@pytest.mark.parametrize(
    "command",
    [
        "Possible caries on tooth 36",
        "Please document slight tenderness near the lower molar",
        "Transcript the patient reports mild jaw discomfort",
    ],
)
def test_unclassified_or_clinical_speech_on_draft_page_is_saved_as_draft(command):
    assert voice_route(command, "Clinical Draft") == ("dictation", None)


@pytest.mark.parametrize(
    "command,expected_route",
    [
        ("Open Priya Verma's OPG report", ("dictation", None)),
        ("What does the report say about caries?", ("dictation", None)),
        ("go to dashboard", ("navigate", "Dashboard")),
    ],
)
def test_page_navigation_and_report_commands_keep_their_routes(command, expected_route):
    assert voice_route(command, "Clinical Draft") == expected_route


@pytest.mark.parametrize(
    "dictation",
    [
        "Open Priya Verma's OPG report",
        "The report shows caries on tooth 36.",
        "Showed tenderness on the lower molar.",
        "Please document the report finding: fracture on tooth 46.",
    ],
)
def test_non_navigation_speech_on_clinical_draft_stays_as_dictation(dictation):
    assert voice_route(dictation, "Clinical Draft") == ("dictation", None)


def test_speech_from_report_chat_page_stays_in_the_report_chatbot():
    assert voice_route("What about tooth 36?", "Ask About a Report") == ("report_chat", None)
    assert voice_route("go to clinical draft", "Ask About a Report") == ("navigate", "Clinical Draft")


@pytest.mark.parametrize(
    "destination",
    [
        "Dashboard",
        "Find Patient Report",
        "Clinical Draft",
        "Ask About a Report",
    ],
)
@pytest.mark.parametrize("current_page", [
    "Dashboard",
    "Find Patient Report",
    "Clinical Draft",
    "Ask About a Report",
])
def test_voice_navigation_reaches_every_page_from_every_page(destination, current_page):
    assert voice_route(f"move me to {destination}", current_page) == (
        "navigate",
        destination,
    )


def test_voice_assistant_navigation_opens_dashboard_workspace():
    assert navigation_target("open voice assistant") == "Dashboard"


def test_non_english_navigation_phrases_are_not_interpreted():
    assert navigation_target("clinical draft kholo") is None


def test_voice_navigation_fuzzy_match_does_not_guess_ambiguous_destinations():
    assert navigation_target("move to the report page") is None
    assert navigation_target("open Priya Verma's OPG report") is None
