"""Feature B: clinical dictation -> structured, editable draft report.

Safety design
-------------
* Every finding carries `source_phrase`, an exact substring of the transcript.
* Rule-based extraction (default) only recognises terms from a fixed dental
  vocabulary, and never guesses a tooth number: "lower left molar" stays a
  *region* because the transcript does not say which molar.
* Optional LLM extraction is treated as untrusted. validate_llm_findings()
  drops any finding whose observation, tooth number or source phrase is not
  traceable to the transcript. Dropped items are reported, never silently used.
* Any sentence the LLM did not cover falls back to the rules, so clinician
  content is never lost either.
* The draft is always `requires_clinician_review: true`.
"""
import re

from app.validators import validate_text_input
from app.vocab import (concepts, content_stems, find_hedge, find_observations, find_sites, has_negation,
                   is_negated, norm_ws, observation_label, public_site, split_clauses, split_sentences)

CERTAINTY_NOTE = {
    "stated": "Stated directly by the clinician.",
    "uncertain": "Clinician expressed uncertainty ('{hedge}').",
    "negated": "Clinician indicated this is absent; verify the negation was captured correctly.",
}


def select_dictation_transcript(provider_transcript, browser_transcript):
    """Prefer a longer browser preview only when it contains the provider transcript."""
    provider = str(provider_transcript or "").strip()
    browser = str(browser_transcript or "").strip()

    def normalize(text):
        return re.sub(r"\W+", " ", text.casefold()).strip()

    provider_normalized = normalize(provider)
    browser_normalized = normalize(browser)

    if not provider:
        return browser, False
    if not browser:
        return provider, False

    differs = provider_normalized != browser_normalized
    if (
        len(browser_normalized) > len(provider_normalized)
        and provider_normalized in browser_normalized
    ):
        return browser, differs
    return provider, differs


def _finding(clause, label, site, certainty, hedge=None, classified=True):
    return {
        "observation": label,
        "classified": classified,
        "site": public_site(site),
        "certainty": certainty,
        "confidence_note": CERTAINTY_NOTE[certainty].format(hedge=hedge or ""),
        "source_phrase": clause,
    }


# ---------------------------------------------------------------- rule-based
def extract_rule_findings(sentence):
    findings = []
    for clause in split_clauses(sentence):
        obs, sites = find_observations(clause), find_sites(clause)
        hedge = find_hedge(clause)
        if not obs:                                   # keep the clinician's words, unclassified
            findings.append(_finding(clause, None, sites[0] if len(sites) == 1 else None,
                                     "uncertain" if hedge else "stated", hedge, classified=False))
            continue
        pairs = []
        if len(obs) == 1 and len(sites) > 1:          # "caries on teeth 36 and 46" -> one per tooth
            pairs = [(obs[0], s) for s in sites]
        else:
            for o in obs:                             # nearest site before the observation, else after
                before = [s for s in sites if s["start"] <= o[1]]
                after = [s for s in sites if s["start"] > o[1]]
                pairs.append((o, before[-1] if before else (after[0] if after else None)))
        for (name, start), site in pairs:
            certainty = "negated" if is_negated(clause, start) else ("uncertain" if hedge else "stated")
            findings.append(_finding(clause, observation_label(name, clause), site, certainty, hedge))
    return findings


# ----------------------------------------------------------- LLM (untrusted)
EXTRACTOR_SYSTEM = """You extract dental findings from a clinician's dictation.
Use ONLY what is explicitly stated. Never add, infer, complete or interpret findings.
For every finding copy the clinician's exact words into "source_phrase".
Return ONLY JSON: {"findings": [{"observation": string, "site_text": string or null,
"fdi_tooth": string or null, "certainty": "stated" | "uncertain" | "negated", "source_phrase": string}]}
If nothing clinical is stated return {"findings": []}."""


def validate_llm_findings(transcript, candidates):
    """Keep only LLM findings that are provably grounded in the transcript.

    Returns (accepted_findings, rejected=[{"candidate":..., "reason":...}]).
    """
    accepted, rejected = [], []
    t_norm = norm_ws(transcript)
    for cand in candidates if isinstance(candidates, list) else []:
        if not isinstance(cand, dict):
            rejected.append({"candidate": cand, "reason": "not an object"})
            continue
        phrase = str(cand.get("source_phrase") or "").strip()
        obs = str(cand.get("observation") or "").strip()
        reason = None
        if not phrase or norm_ws(phrase) not in t_norm:
            reason = "source_phrase is not an exact part of the transcript"
        elif not obs:
            reason = "no observation"
        else:
            obs_concepts, phrase_concepts = concepts(obs), concepts(phrase)
            if obs_concepts:
                if not obs_concepts <= phrase_concepts:
                    reason = f"observation {sorted(obs_concepts - phrase_concepts)} not found in source phrase"
            elif not content_stems(obs) <= content_stems(phrase):
                reason = "observation wording not found in source phrase"
        if reason:
            rejected.append({"candidate": cand, "reason": reason})
            continue

        sites, warnings = find_sites(phrase), []
        site, fdi = None, str(cand.get("fdi_tooth") or "").strip() or None
        if fdi:
            site = next((s for s in sites if s["fdi_tooth"] == fdi), None)
            if site is None:
                warnings.append(f"Model proposed tooth {fdi}, which the transcript does not state; tooth number omitted.")
        if site is None and sites:
            site = sites[0] if len(sites) == 1 else None
        if site is None and cand.get("site_text") and norm_ws(cand["site_text"]) in norm_ws(phrase):
            site = {"text": str(cand["site_text"]).strip(), "fdi_tooth": None, "quadrant": None,
                    "precision": "region", "start": 0}

        hedge = find_hedge(phrase)
        common = sorted(concepts(phrase) & concepts(obs))
        label = observation_label(common[0], phrase) if common else obs
        claimed = cand.get("certainty")
        if has_negation(phrase) and any(is_negated(phrase, st) for _, st in find_observations(phrase)):
            certainty = "negated"
        elif hedge or claimed == "uncertain":         # may only become *more* cautious
            certainty = "uncertain"
        else:
            certainty = "stated"
        f = _finding(phrase, label, site, certainty, hedge or "model flagged uncertainty")
        f["warnings"] = warnings
        accepted.append(f)
    return accepted, rejected


# -------------------------------------------------------------------- render
def _site_text(site):
    if not site:
        return None
    if site["fdi_tooth"] and not site["text"].startswith("tooth"):
        return f"{site['text']} (FDI {site['fdi_tooth']})"
    return site["text"]


def render_report_text(findings):
    lines = [
        "DRAFT CLINICAL REPORT — PENDING CLINICIAN REVIEW",
        "",
        "Clinical observations",
    ]
    for i, f in enumerate(findings, 1):
        site = _site_text(f["site"])
        where = f" — Site: {site}" if site else " — Anatomical site: not stated"
        if not f["classified"]:
            certainty = "uncertain" if f["certainty"] == "uncertain" else "as stated"
            lines.append(
                f'{i}. Unclassified observation (verbatim, {certainty}){where}: '
                f'"{f["source_phrase"]}"'
            )
        elif f["certainty"] == "negated":
            lines.append(
                f"{i}. No {f['observation']}{where} "
                "(as stated by the clinician; verify negation)."
            )
        elif f["certainty"] == "uncertain":
            lines.append(
                f"{i}. Possible {f['observation']}{where} "
                "(clinician expressed uncertainty)."
            )
        else:
            lines.append(
                f"{i}. {f['observation'].capitalize()}{where} "
                "(stated by the clinician)."
            )
    if not findings:
        lines.append("No observations could be extracted from the transcript.")
    lines.extend([
        "",
        "This draft includes only the dictated observations. "
        "Unmentioned findings have not been assessed.",
        "Verify all wording and approve before clinical use.",
    ])
    return "\n".join(lines)


# -------------------------------------------------------------------- public
def create_clinical_draft(transcript, llm_call=None):
    clean, error = validate_text_input(transcript)
    if error:
        return {"status": "error", "message": "Clinical observation is required." if error == "Input is empty." else error}

    rejected, method, llm_findings = [], "rules", []
    if llm_call is not None:
        try:
            data = llm_call(EXTRACTOR_SYSTEM, clean)
            llm_findings, rejected = validate_llm_findings(clean, data.get("findings", []))
            method = "llm+validator"
        except Exception as exc:
            method = f"rules (LLM unavailable: {type(exc).__name__})"

    findings = []
    for sentence in split_sentences(clean):
        s_norm = norm_ws(sentence)
        covered = [f for f in llm_findings if norm_ws(f["source_phrase"]) in s_norm]
        findings.extend(covered or extract_rule_findings(sentence))

    warnings = []
    for i, f in enumerate(findings, 1):
        warnings += [f"Finding {i}: {w}" for w in f.pop("warnings", [])]
        if not f["classified"]:
            warnings.append(f"Finding {i}: wording not recognised as a standard finding; kept verbatim.")
        if f["site"] is None:
            warnings.append(f"Finding {i}: no anatomical site stated.")
        elif f["site"]["precision"] == "region":
            warnings.append(f"Finding {i}: tooth number not stated ('{f['site']['text']}'); not guessed.")
        if f["certainty"] == "negated":
            warnings.append(f"Finding {i}: negation detected; verify.")
        f["id"] = i
    if rejected:
        warnings.append(f"{len(rejected)} model-proposed finding(s) were discarded because they were not grounded in the transcript.")

    sites = []
    for f in findings:
        label = _site_text(f["site"])
        if label and label not in sites:
            sites.append(label)
    return {
        "status": "draft",
        "requires_clinician_review": True,
        "review_status": "pending_clinician_review",
        "source_transcript": clean,
        "extraction_method": method,
        "findings": findings,
        "anatomical_site": "; ".join(sites) if sites else "Not specified in transcript",
        "report_text": render_report_text(findings),
        "warnings": warnings,
        "rejected_findings": rejected,
    }
