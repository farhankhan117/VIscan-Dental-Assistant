"""Build an auditable structured JSON export for clinician review."""


def apply_structured_draft_edits(draft, edited_json):
    """Apply the compact editable JSON fields without changing source evidence."""
    if not isinstance(edited_json, dict) or set(edited_json) != {
        "findings",
        "readable_draft_report",
    }:
        raise ValueError("JSON must contain only findings and readable_draft_report.")

    report_text = edited_json.get("readable_draft_report")
    findings = edited_json.get("findings")
    if not isinstance(report_text, str) or not isinstance(findings, list):
        raise ValueError("readable_draft_report must be text and findings must be a list.")

    originals = [
        item for item in draft.get("findings", [])
        if isinstance(item, dict)
    ]
    if len(findings) != len(originals):
        raise ValueError("Keep the original findings; adding or removing findings is not supported.")

    edited_ids = set(draft.get("json_edited_finding_ids", []))
    updated_findings = []
    for index, (finding, original) in enumerate(zip(findings, originals), 1):
        finding_id = str(original.get("id", index))
        if not isinstance(finding, dict):
            raise ValueError("Each finding must be a JSON object.")
        if set(finding) != {"observation", "anatomical_site", "certainty"}:
            raise ValueError("Each finding may contain only observation, anatomical_site, and certainty.")
        observation = finding.get("observation")
        certainty = finding.get("certainty")
        site = finding.get("anatomical_site")
        if not isinstance(observation, str) or not observation.strip():
            raise ValueError(f"Finding {finding_id} needs a non-empty observation.")
        if certainty not in {"stated", "uncertain", "negated"}:
            raise ValueError(f"Finding {finding_id} has an unsupported certainty value.")
        if not isinstance(site, str):
            raise ValueError(f"Finding {finding_id} anatomical_site must be text.")

        original_site = original.get("site") or {}
        if not isinstance(original_site, dict):
            original_site = {"text": str(original_site)}
        original_site_text = original_site.get("text") or "Not stated"
        original_tooth = original_site.get("fdi_tooth")
        if original_tooth:
            original_site_text = f"{original_site_text} (FDI {original_tooth})"
        unchanged = (
            observation.strip()
            == str(original.get("observation") or original.get("source_phrase") or "Unclassified observation")
            and site == original_site_text
            and certainty == str(original.get("certainty") or "uncertain")
        )
        if not unchanged:
            edited_ids.add(finding_id)

        if unchanged:
            updated_site = dict(original_site)
        else:
            updated_site = {
                "text": None if site in {"", "Not stated"} else site,
            }
        updated_findings.append({
            **original,
            "observation": observation.strip(),
            "site": updated_site,
            "certainty": certainty,
        })

    updated = {
        **draft,
        "report_text": report_text,
        "findings": updated_findings,
        "requires_clinician_review": True,
        "json_edited_finding_ids": sorted(edited_ids),
        "json_edited_readable_report": (
            bool(draft.get("json_edited_readable_report"))
            or report_text != draft.get("report_text", "")
        ),
    }
    updated["warnings"] = list(draft.get("warnings") or [])
    if (edited_ids or updated["json_edited_readable_report"]) and not any(
        "JSON editor" in warning for warning in updated["warnings"]
    ):
        updated["warnings"].append("Content edited in the JSON editor requires clinician confirmation.")
    return updated


def build_editable_draft_json(structured_draft):
    """Return only the clinician-requested editable fields for JSON output."""
    findings = []
    for finding in structured_draft.get("findings", []):
        site = finding.get("anatomical_site") or {}
        if isinstance(site, dict):
            site_text = site.get("text") or "Not stated"
            tooth = site.get("fdi_tooth")
            if tooth:
                site_text = f"{site_text} (FDI {tooth})"
        else:
            site_text = str(site)
        findings.append({
            "observation": finding.get("observation", ""),
            "anatomical_site": site_text,
            "certainty": finding.get("certainty", "uncertain"),
        })
    return {
        "findings": findings,
        "readable_draft_report": structured_draft.get("readable_report", ""),
    }


def build_structured_draft(
    draft,
    edited_rows,
    title,
    patient_name,
    report_text,
    created_at,
):
    original_by_id = {
        str(item.get("id", index)): item
        for index, item in enumerate(draft.get("findings", []), 1)
        if isinstance(item, dict)
    }
    findings = []
    edited_ids = []
    json_edited_ids = {str(item) for item in draft.get("json_edited_finding_ids", [])}

    for row in edited_rows:
        finding_id = str(row.get("ID", ""))
        original = original_by_id.get(finding_id, {})
        original_site = original.get("site") or {}
        if not isinstance(original_site, dict):
            original_site = {"text": str(original_site)}

        original_observation = (
            original.get("observation")
            or original.get("source_phrase")
            or "Unclassified observation"
        )
        observation = str(row.get("Finding") or "").strip()
        site_text = str(row.get("Anatomical site") or "").strip()
        certainty = str(row.get("Certainty") or "uncertain")
        original_site_text = original_site.get("text", "")
        original_tooth = original_site.get("fdi_tooth")
        original_display_site = (
            f"{original_site_text} (FDI {original_tooth})"
            if original_tooth else original_site_text
        )
        unchanged = (
            observation == str(original_observation)
            and site_text == (original_display_site or "Not stated")
            and certainty == str(original.get("certainty") or "uncertain")
            and finding_id not in json_edited_ids
        )
        if not unchanged:
            edited_ids.append(finding_id)

        site = {"text": None if site_text in {"", "Not stated", "Not specified"} else site_text}
        if unchanged:
            site.update(original_site)
        findings.append({
            "id": original.get("id", finding_id),
            "observation": observation,
            "classified": original.get("classified", False),
            "anatomical_site": site,
            "certainty": certainty,
            "confidence_note": original.get("confidence_note", ""),
            "source_phrase": original.get("source_phrase", ""),
            "transcript_supported": unchanged,
            "clinician_edited": not unchanged,
            "requires_clinician_confirmation": not unchanged,
        })

    return {
        "schema_version": "1.0",
        "status": "draft",
        "title": title,
        "patient_name": patient_name,
        "created_at": created_at,
        "review_status": "pending_clinician_review",
        "requires_clinician_review": True,
        "source_transcript": draft.get("source_transcript", ""),
        "readable_report": report_text,
        "readable_report_edited": (
            report_text != draft.get("report_text", "")
            or bool(draft.get("json_edited_readable_report"))
        ),
        "readable_report_requires_clinician_confirmation": (
            report_text != draft.get("report_text", "")
            or bool(draft.get("json_edited_readable_report"))
        ),
        "extraction_method": draft.get("extraction_method", "rules"),
        "findings": findings,
        "warnings": list(draft.get("warnings") or []),
        "edited_finding_ids_require_confirmation": edited_ids,
    }
