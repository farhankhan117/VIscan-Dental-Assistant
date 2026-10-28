"""Feature B. REQUIRED test: unsupported clinical claims must never appear in a draft."""
import pytest

from clinical_draft import create_clinical_draft, select_dictation_transcript

IMPACTED = "Lower right third molar is horizontally impacted."
INVENTABLE = ["caries", "cavity", "fracture", "cyst", "abscess", "extraction", "surgery", "bone loss",
              "periapical", "radiolucen", "swelling", "root canal"]


def test_dictation_prefers_complete_browser_preview_when_provider_transcript_is_truncated():
    selected, differs = select_dictation_transcript(
        "Lower right third molar is impacted",
        "Lower right third molar is impacted and tooth 36 has caries.",
    )
    assert selected == "Lower right third molar is impacted and tooth 36 has caries."
    assert differs is True


def test_dictation_keeps_distinct_provider_transcript_and_flags_disagreement():
    selected, differs = select_dictation_transcript(
        "Caries on tooth 36.",
        "Caries on tooth 46.",
    )
    assert selected == "Caries on tooth 36."
    assert differs is True


def test_dictation_uses_browser_preview_when_provider_transcript_is_empty():
    assert select_dictation_transcript("", "Caries on tooth 36.") == (
        "Caries on tooth 36.",
        False,
    )


def test_assignment_example_structure():
    r = create_clinical_draft(IMPACTED)
    assert r["status"] == "draft" and r["requires_clinician_review"] is True
    (f,) = r["findings"]
    assert f["observation"] == "horizontal impaction"
    assert f["site"]["fdi_tooth"] == "48" and f["site"]["text"] == "lower right third molar"
    assert f["certainty"] == "stated" and f["source_phrase"] == IMPACTED
    assert "clinician review" in r["report_text"].lower()
    assert "Clinical observations" in r["report_text"]
    assert "Site: lower right third molar (FDI 48)" in r["report_text"]
    assert "stated by the clinician" in r["report_text"]


def test_draft_never_invents_findings():
    text = create_clinical_draft(IMPACTED)["report_text"].lower()
    for term in INVENTABLE:
        assert term not in text, f"invented: {term}"


def test_only_dictated_findings_appear():
    r = create_clinical_draft("Caries on tooth 36.")
    assert [f["observation"] for f in r["findings"]] == ["caries"]
    assert "impact" not in r["report_text"].lower()


def test_unsupported_claim_from_llm_is_discarded():
    """A model that adds a finding the clinician never said must be caught by the validator."""
    def hallucinating_llm(system, user):
        return {"findings": [
            {"observation": "horizontal impaction", "site_text": "lower right third molar", "fdi_tooth": "48",
             "certainty": "stated", "source_phrase": "Lower right third molar is horizontally impacted"},
            {"observation": "periapical abscess", "site_text": "lower right third molar", "fdi_tooth": "48",
             "certainty": "stated", "source_phrase": "with an associated periapical abscess"},   # never said
            {"observation": "caries", "site_text": None, "fdi_tooth": None, "certainty": "stated",
             "source_phrase": "Lower right third molar is horizontally impacted"},               # not in that phrase
        ]}
    r = create_clinical_draft(IMPACTED, llm_call=hallucinating_llm)
    assert [f["observation"] for f in r["findings"]] == ["horizontal impaction"]
    assert len(r["rejected_findings"]) == 2
    assert "abscess" not in r["report_text"].lower() and "caries" not in r["report_text"].lower()
    assert any("discarded" in w for w in r["warnings"])


def test_llm_cannot_invent_a_tooth_number():
    def wrong_tooth(system, user):
        return {"findings": [{"observation": "caries", "site_text": None, "fdi_tooth": "46", "certainty": "stated",
                              "source_phrase": "Caries on tooth 36"}]}
    f = create_clinical_draft("Caries on tooth 36.", llm_call=wrong_tooth)["findings"][0]
    assert f["site"]["fdi_tooth"] == "36"


def test_llm_outage_falls_back_to_rules():
    def down(system, user):
        raise TimeoutError()
    r = create_clinical_draft(IMPACTED, llm_call=down)
    assert r["status"] == "draft" and r["findings"][0]["site"]["fdi_tooth"] == "48"
    assert "unavailable" in r["extraction_method"]


def test_sentences_missed_by_llm_are_not_lost():
    def partial(system, user):
        return {"findings": [{"observation": "caries", "site_text": None, "fdi_tooth": "36", "certainty": "stated",
                              "source_phrase": "Caries on tooth 36."}]}
    r = create_clinical_draft("Caries on tooth 36. Tenderness on percussion.", llm_call=partial)
    assert {f["observation"] for f in r["findings"]} == {"caries", "tenderness"}


def test_uncertainty_is_labelled():
    f = create_clinical_draft("Possible caries on tooth 36.")["findings"][0]
    assert f["certainty"] == "uncertain" and "possible" in f["confidence_note"].lower()


def test_negation_is_labelled_not_reported_as_a_finding():
    r = create_clinical_draft("No swelling noted.")
    assert r["findings"][0]["certainty"] == "negated" and "No swelling" in r["report_text"]


def test_tooth_number_is_not_guessed():
    r = create_clinical_draft("Lower left molar has a visible cavity.")
    site = r["findings"][0]["site"]
    assert site["fdi_tooth"] is None and site["precision"] == "region"
    assert any("not guessed" in w for w in r["warnings"])


def test_unrecognised_wording_is_kept_verbatim_and_flagged():
    r = create_clinical_draft("Patient seems anxious today.")
    f = r["findings"][0]
    assert f["classified"] is False and f["source_phrase"] == "Patient seems anxious today."
    assert any("verbatim" in w for w in r["warnings"])
    assert "Unclassified observation (verbatim" in r["report_text"]
    assert "Anatomical site: not stated" in r["report_text"]
    assert "Patient seems anxious today." in r["report_text"]


def test_two_findings_in_one_sentence_keep_their_own_sites():
    r = create_clinical_draft("Lower right third molar is impacted and tooth 36 has caries.")
    sites = {f["observation"]: f["site"]["fdi_tooth"] for f in r["findings"]}
    assert sites == {"impaction": "48", "caries": "36"}


@pytest.mark.parametrize(
    "transcript,expected",
    [
        ("Tooth thirty six has caries.", "36"),
        ("Tooth thirty-six has caries.", "36"),
        ("Tooth sixteen has caries.", "16"),
        ("Thirty six caries.", "36"),
        ("36 caries, 46 fracture, 48 impacted.", "36"),
        ("Caries on tooth thirty six and fracture on tooth forty six.", "36"),
    ],
)
def test_spoken_and_shorthand_fdi_sites_are_preserved(transcript, expected):
    result = create_clinical_draft(transcript)
    assert result["findings"][0]["site"]["fdi_tooth"] == expected


def test_non_tooth_anatomical_regions_are_preserved():
    result = create_clinical_draft("Tenderness in the lower right jaw.")
    site = result["findings"][0]["site"]
    assert site["fdi_tooth"] is None
    assert site["text"] == "lower right jaw"
    assert site["precision"] == "region"


def test_multiple_shorthand_fdi_findings_keep_their_own_sites():
    result = create_clinical_draft("36 caries, 46 fracture, 48 impacted.")
    sites = {finding["observation"]: finding["site"]["fdi_tooth"] for finding in result["findings"]}
    assert sites == {"caries": "36", "fracture": "46", "impaction": "48"}


def test_every_source_phrase_is_in_the_transcript():
    t = "Possible caries on tooth 36. Lower right third molar is horizontally impacted, no swelling."
    for f in create_clinical_draft(t)["findings"]:
        assert f["source_phrase"] in t


def test_invalid_input():
    assert create_clinical_draft("")["status"] == "error"
    assert create_clinical_draft("   ")["message"] == "Clinical observation is required."
    assert create_clinical_draft(None)["status"] == "error"
    assert create_clinical_draft("x" * 5000)["status"] == "error"
