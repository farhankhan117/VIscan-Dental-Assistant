import pytest

from draft_export import (
    apply_structured_draft_edits,
    build_editable_draft_json,
    build_structured_draft,
)


def _draft_for_json_edit():
    return {
        "title": "Clinical dictation draft",
        "patient_name": "Synthetic patient",
        "source_transcript": "Lower right third molar is horizontally impacted.",
        "report_text": "Original report text.",
        "findings": [{
            "id": 1,
            "observation": "horizontal impaction",
            "classified": True,
            "site": {"text": "lower right third molar", "fdi_tooth": "48"},
            "certainty": "stated",
            "source_phrase": "Lower right third molar is horizontally impacted.",
        }],
    }


def _json_for_edit():
    return {
        "readable_draft_report": "Updated report text.",
        "findings": [{
            "observation": "horizontal impaction with a clinician note",
            "anatomical_site": "lower right third molar",
            "certainty": "stated",
        }],
    }


def test_json_editor_applies_content_but_preserves_original_source_evidence():
    updated = apply_structured_draft_edits(_draft_for_json_edit(), _json_for_edit())

    assert updated["report_text"] == "Updated report text."
    assert updated["findings"][0]["observation"] == "horizontal impaction with a clinician note"
    assert updated["findings"][0]["source_phrase"] == (
        "Lower right third molar is horizontally impacted."
    )
    assert updated["json_edited_finding_ids"] == ["1"]
    assert updated["json_edited_readable_report"] is True
    assert updated["requires_clinician_review"] is True
    exported = build_structured_draft(
        draft=updated,
        edited_rows=[{
            "ID": "1",
            "Finding": updated["findings"][0]["observation"],
            "Anatomical site": updated["findings"][0]["site"]["text"],
            "Certainty": updated["findings"][0]["certainty"],
            "Source words": updated["findings"][0]["source_phrase"],
        }],
        title=updated["title"],
        patient_name=updated["patient_name"],
        report_text=updated["report_text"],
        created_at="2026-10-28T01:00:00",
    )
    assert exported["findings"][0]["requires_clinician_confirmation"] is True
    assert exported["readable_report_requires_clinician_confirmation"] is True


def test_json_editor_rejects_removed_findings_and_invalid_certainty():
    draft = _draft_for_json_edit()
    edited = _json_for_edit()
    edited["findings"] = []
    with pytest.raises(ValueError, match="adding or removing findings"):
        apply_structured_draft_edits(draft, edited)

    edited = _json_for_edit()
    edited["findings"][0]["certainty"] = "certain"
    with pytest.raises(ValueError, match="certainty"):
        apply_structured_draft_edits(draft, edited)

    edited = _json_for_edit()
    edited["source_transcript"] = "changed source"
    with pytest.raises(ValueError, match="only findings and readable_draft_report"):
        apply_structured_draft_edits(draft, edited)


def test_editable_json_contains_only_requested_fields():
    structured = build_structured_draft(
        draft=_draft_for_json_edit(),
        edited_rows=[{
            "ID": "1",
            "Finding": "horizontal impaction",
            "Anatomical site": "lower right third molar (FDI 48)",
            "Certainty": "stated",
            "Source words": "Lower right third molar is horizontally impacted.",
        }],
        title="Clinical dictation draft",
        patient_name="Synthetic patient",
        report_text="Original report text.",
        created_at="2026-10-28T01:00:00",
    )

    editable = build_editable_draft_json(structured)
    assert set(editable) == {"findings", "readable_draft_report"}
    assert set(editable["findings"][0]) == {
        "observation",
        "anatomical_site",
        "certainty",
    }
    assert editable["findings"][0]["anatomical_site"] == (
        "lower right third molar (FDI 48)"
    )


def test_structured_export_keeps_evidence_and_review_metadata():
    source_finding = {
        "id": 1,
        "observation": "horizontal impaction",
        "classified": True,
        "site": {
            "text": "lower right third molar",
            "fdi_tooth": "48",
            "precision": "tooth",
        },
        "certainty": "stated",
        "confidence_note": "Stated directly by the clinician.",
        "source_phrase": "Lower right third molar is horizontally impacted.",
    }
    result = build_structured_draft(
        draft={
            "source_transcript": source_finding["source_phrase"],
            "report_text": "Draft report text.",
            "findings": [source_finding],
            "warnings": ["Review tooth number."],
            "extraction_method": "rules",
        },
        edited_rows=[{
            "ID": "1",
            "Finding": "horizontal impaction",
            "Anatomical site": "lower right third molar (FDI 48)",
            "Certainty": "stated",
            "Source words": source_finding["source_phrase"],
        }],
        title="Clinical dictation draft",
        patient_name="Synthetic patient",
        report_text="Draft report text.",
        created_at="2026-10-27T01:00:00",
    )

    assert result["requires_clinician_review"] is True
    assert result["review_status"] == "pending_clinician_review"
    assert result["readable_report"] == "Draft report text."
    assert result["source_transcript"] == source_finding["source_phrase"]
    assert result["readable_report_edited"] is False
    assert result["findings"][0]["anatomical_site"]["fdi_tooth"] == "48"
    assert result["findings"][0]["source_phrase"] == source_finding["source_phrase"]
    assert result["findings"][0]["transcript_supported"] is True
    assert result["edited_finding_ids_require_confirmation"] == []


def test_structured_export_flags_edited_finding_for_clinician_confirmation():
    result = build_structured_draft(
        draft={
            "source_transcript": "Lower right third molar is horizontally impacted.",
            "report_text": "Original readable report.",
            "findings": [{
                "id": 1,
                "observation": "horizontal impaction",
                "classified": True,
                "site": {"text": "lower right third molar", "fdi_tooth": "48"},
                "certainty": "stated",
                "source_phrase": "Lower right third molar is horizontally impacted.",
            }],
        },
        edited_rows=[{
            "ID": "1",
            "Finding": "periapical abscess",
            "Anatomical site": "lower right third molar",
            "Certainty": "stated",
            "Source words": "Lower right third molar is horizontally impacted.",
        }],
        title="Clinical dictation draft",
        patient_name="Not specified",
        report_text="Edited report text.",
        created_at="2026-10-27T01:00:00",
    )

    finding = result["findings"][0]
    assert finding["clinician_edited"] is True
    assert finding["transcript_supported"] is False
    assert finding["requires_clinician_confirmation"] is True
    assert result["edited_finding_ids_require_confirmation"] == ["1"]
    assert result["readable_report_requires_clinician_confirmation"] is True
    assert finding["source_phrase"] == "Lower right third molar is horizontally impacted."
