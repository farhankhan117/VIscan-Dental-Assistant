from draft_pdf import create_draft_pdf


def test_pdf_includes_a_structured_clinician_review_draft():
    pdf = create_draft_pdf({
        "title": "Dictation",
        "created_at": "2026-10-27T01:00:00",
        "extraction_method": "rules",
        "report_text": "DRAFT: not verified. Horizontal impaction at lower right third molar.",
        "source_transcript": "नीचे का दायाँ तीसरा दाँत क्षैतिज रूप से प्रभावित है।",
        "findings": [
            {
                "observation": "horizontal impaction",
                "site": {"text": "lower right third molar", "fdi_tooth": "48"},
                "certainty": "stated",
                "source_phrase": "Lower right third molar is horizontally impacted.",
            }
        ],
        "warnings": ["Clinician review is required."],
    }, "Priya Verma")

    assert pdf.startswith(b"%PDF-")
    assert b"%%EOF" in pdf
