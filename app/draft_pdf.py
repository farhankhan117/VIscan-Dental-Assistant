"""Create a readable, structured PDF for clinician review."""
from datetime import datetime
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

NAVY = colors.HexColor("#10233f")
TEAL = colors.HexColor("#17627b")
PALE_BLUE = colors.HexColor("#edf4f8")
GRID = colors.HexColor("#d7e1ea")
MUTED = colors.HexColor("#52647a")


def _paragraph(value, style):
    text = escape(str(value if value not in (None, "") else "Not specified"))
    return Paragraph(text.replace("\n", "<br/>"), style)


def _register_unicode_font():
    candidates = (
        (Path("C:/Windows/Fonts/Nirmala.ttf"), Path("C:/Windows/Fonts/NirmalaB.ttf")),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
         Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
        (Path("/Library/Fonts/Arial Unicode.ttf"), Path("/Library/Fonts/Arial Unicode.ttf")),
    )
    for regular, bold in candidates:
        if regular.is_file():
            pdfmetrics.registerFont(TTFont("ViscanUnicode", str(regular)))
            pdfmetrics.registerFont(
                TTFont("ViscanUnicode-Bold", str(bold if bold.is_file() else regular))
            )
            registerFontFamily(
                "ViscanUnicode",
                normal="ViscanUnicode",
                bold="ViscanUnicode-Bold",
                italic="ViscanUnicode",
                boldItalic="ViscanUnicode-Bold",
            )
            return "ViscanUnicode", "ViscanUnicode-Bold"
    return "Helvetica", "Helvetica-Bold"


def _format_created_at(value):
    if not value:
        return "Not specified"
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y, %I:%M %p")
    except (TypeError, ValueError):
        return str(value)


def _site_label(finding):
    site = finding.get("site") or finding.get("anatomical_site")
    if isinstance(site, dict):
        label = site.get("text") or "Not stated"
        tooth = site.get("fdi_tooth")
        return f"{label} (FDI {tooth})" if tooth else label
    return str(site or "Not stated")


def _draw_footer(canvas, document):
    canvas.saveState()
    width, _ = letter
    canvas.setStrokeColor(GRID)
    canvas.line(document.leftMargin, 0.48 * inch, width - document.rightMargin, 0.48 * inch)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(document.leftMargin, 0.31 * inch, "Confidential clinical draft • Verify before use")
    canvas.drawRightString(width - document.rightMargin, 0.31 * inch, f"Page {document.page}")
    canvas.restoreState()


def create_draft_pdf(draft, patient_name="Not specified"):
    """Return the editable clinical draft as formatted PDF bytes."""
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.68 * inch,
        leftMargin=0.68 * inch,
        topMargin=0.62 * inch,
        bottomMargin=0.72 * inch,
        title=str(draft.get("title") or "Clinical Dictation Draft"),
        author="VI-SCAN Dental Assistant",
    )
    styles = getSampleStyleSheet()
    regular_font, bold_font = _register_unicode_font()
    title_style = ParagraphStyle(
        "ViscanTitle",
        parent=styles["Title"],
        fontName=bold_font,
        fontSize=19,
        leading=24,
        alignment=TA_CENTER,
        textColor=NAVY,
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "ViscanSubtitle",
        parent=styles["Normal"],
        fontName=regular_font,
        fontSize=9,
        leading=13,
        alignment=TA_CENTER,
        textColor=TEAL,
        spaceAfter=12,
    )
    heading_style = ParagraphStyle(
        "ViscanHeading",
        parent=styles["Heading2"],
        fontName=bold_font,
        fontSize=12,
        leading=15,
        textColor=NAVY,
        spaceBefore=4,
        spaceAfter=7,
    )
    body_style = ParagraphStyle(
        "ViscanBody",
        parent=styles["BodyText"],
        fontName=regular_font,
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor("#253449"),
        spaceAfter=3,
    )
    small_style = ParagraphStyle(
        "ViscanSmall",
        parent=body_style,
        fontSize=8,
        leading=11,
    )
    label_style = ParagraphStyle(
        "ViscanLabel",
        parent=small_style,
        fontName=bold_font,
        textColor=MUTED,
    )
    header_style = ParagraphStyle(
        "ViscanTableHeader",
        parent=small_style,
        fontName=bold_font,
        textColor=colors.white,
    )

    story = [
        _paragraph(draft.get("title") or "Clinical Dictation Draft", title_style),
        _paragraph("DRAFT REPORT  |  PENDING CLINICIAN REVIEW", subtitle_style),
        HRFlowable(width="100%", thickness=1.2, color=TEAL, spaceAfter=12),
    ]

    metadata = [
        [_paragraph("PATIENT", label_style), _paragraph(patient_name, body_style),
         _paragraph("CREATED", label_style), _paragraph(_format_created_at(draft.get("created_at")), body_style)],
        [_paragraph("REVIEW STATUS", label_style), _paragraph("Pending clinician review", body_style),
         _paragraph("EXTRACTION", label_style), _paragraph(draft.get("extraction_method", "rules"), body_style)],
    ]
    metadata_table = Table(
        metadata,
        colWidths=[0.95 * inch, 2.45 * inch, 0.95 * inch, 2.4 * inch],
        hAlign="LEFT",
    )
    metadata_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
        ("BOX", (0, 0), (-1, -1), 0.5, GRID),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([metadata_table, Spacer(1, 15), _paragraph("Readable report", heading_style)])
    story.append(_paragraph(draft.get("report_text", ""), body_style))
    story.extend([Spacer(1, 11), _paragraph("Structured findings", heading_style)])

    headers = ["#", "Finding", "Anatomical site", "Certainty", "Source words"]
    rows = [[_paragraph(header, header_style) for header in headers]]
    findings = draft.get("findings") or []
    for index, finding in enumerate(findings, 1):
        if not isinstance(finding, dict):
            continue
        observation = (
            finding.get("observation")
            or finding.get("source_phrase")
            or "Unclassified observation"
        )
        rows.append([
            _paragraph(index, small_style),
            _paragraph(observation, small_style),
            _paragraph(_site_label(finding), small_style),
            _paragraph(finding.get("certainty") or "uncertain", small_style),
            _paragraph(finding.get("source_phrase") or "Not available", small_style),
        ])
    if len(rows) == 1:
        rows.append([_paragraph("No findings were extracted.", small_style), "", "", "", ""])
    findings_table = Table(
        rows,
        colWidths=[0.28 * inch, 1.55 * inch, 1.55 * inch, 0.78 * inch, 2.55 * inch],
        repeatRows=1,
        hAlign="LEFT",
    )
    findings_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TEAL),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE_BLUE]),
        ("GRID", (0, 0), (-1, -1), 0.45, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    if len(rows) == 2 and not findings:
        findings_table.setStyle(TableStyle([("SPAN", (0, 1), (4, 1))]))
    story.append(findings_table)

    transcript = draft.get("source_transcript")
    if transcript:
        story.extend([
            Spacer(1, 13),
            _paragraph("Original source transcript", heading_style),
            _paragraph(transcript, body_style),
        ])
    warnings = draft.get("warnings") or []
    if warnings:
        story.extend([Spacer(1, 10), _paragraph("Review notes", heading_style)])
        for warning in warnings:
            story.append(_paragraph(f"• {warning}", small_style))
    story.extend([
        Spacer(1, 14),
        _paragraph(
            "Synthetic demonstration document. Not for diagnosis. "
            "Verify the transcript, findings, anatomical sites, and certainty; "
            "clinician approval is required before clinical use.",
            small_style,
        ),
    ])
    document.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return buffer.getvalue()
