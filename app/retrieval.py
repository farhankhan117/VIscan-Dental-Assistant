"""Deterministic "tools": patient search and report retrieval.

This is the business-rule layer. The LLM never reads or writes this data; it
only produces an interpretation that gets validated and then passed here.
Rules enforced here:
  * never auto-pick between several patients (ambiguous -> ask)
  * never auto-accept a fuzzy / prefix name match (confirm first)
  * never return a different report type than the one requested
"""
import difflib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

from app.vocab import SUPPORTED_REPORT_TYPES, normalize_report_type

PROJECT_FOLDER = Path(__file__).resolve().parents[1]
DATA_FOLDER = PROJECT_FOLDER / "data"


def load_json_file(file_path):
    if not file_path.exists():
        raise FileNotFoundError(f"Required data file was not found: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


patients = load_json_file(DATA_FOLDER / "patients.json")
reports = load_json_file(DATA_FOLDER / "reports.json")


def validate_dataset(patient_rows, report_rows):
    """Fail fast when the synthetic dataset is incomplete or internally inconsistent."""
    if not isinstance(patient_rows, list) or len(patient_rows) < 5:
        raise ValueError("Synthetic dataset must contain at least five patients.")
    if not isinstance(report_rows, list):
        raise ValueError("Synthetic reports must be a list.")

    patient_ids = [p.get("patient_id") for p in patient_rows if isinstance(p, dict)]
    if len(patient_ids) != len(patient_rows) or any(
        not isinstance(value, str) or not value.strip() for value in patient_ids
    ):
        raise ValueError("Every synthetic patient must have a patient_id.")
    if len(set(patient_ids)) != len(patient_ids):
        raise ValueError("Synthetic patient IDs must be unique.")
    if any(not isinstance(p.get("name"), str) or not p["name"].strip() for p in patient_rows):
        raise ValueError("Every synthetic patient must have a name.")

    first_names = Counter(p["name"].split()[0].casefold() for p in patient_rows)
    if not any(count > 1 for count in first_names.values()):
        raise ValueError("Synthetic dataset must include patients with similar names.")

    patient_id_set = set(patient_ids)
    report_ids = []
    reports_per_patient = Counter()
    supported_types = {report_type.casefold() for report_type in SUPPORTED_REPORT_TYPES}
    for report in report_rows:
        if not isinstance(report, dict):
            raise ValueError("Every synthetic report must be an object.")
        report_id = report.get("report_id")
        patient_id = report.get("patient_id")
        if not isinstance(report_id, str) or not report_id.strip():
            raise ValueError("Every synthetic report must have a report_id.")
        if not isinstance(patient_id, str) or not patient_id.strip():
            raise ValueError(f"Synthetic report {report_id} must have a patient_id.")
        if patient_id not in patient_id_set:
            raise ValueError(f"Synthetic report {report_id} references unknown patient {patient_id}.")
        report_type = report.get("report_type")
        if not isinstance(report_type, str) or report_type.casefold() not in supported_types:
            raise ValueError(f"Synthetic report {report_id} has an unsupported report type.")
        try:
            date.fromisoformat(report.get("date", ""))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Synthetic report {report_id} must have an ISO-format date.") from exc
        findings = report.get("findings")
        if not isinstance(findings, list) or not all(isinstance(item, str) and item.strip() for item in findings):
            raise ValueError(f"Synthetic report {report_id} must have a list of non-empty findings.")
        if not isinstance(report.get("report_text"), str) or not report["report_text"].strip():
            raise ValueError(f"Synthetic report {report_id} must have report_text.")
        if report.get("synthetic") is not True:
            raise ValueError(f"Synthetic report {report_id} must be explicitly marked synthetic.")
        report_ids.append(report_id)
        reports_per_patient[patient_id] += 1

    if len(set(report_ids)) != len(report_ids):
        raise ValueError("Synthetic report IDs must be unique.")
    patients_without_two_reports = [patient_id for patient_id in patient_ids if reports_per_patient[patient_id] < 2]
    if patients_without_two_reports:
        raise ValueError("Every synthetic patient must have at least two reports.")


validate_dataset(patients, reports)


# ------------------------------------------------------------------ patients
def _norm(name):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z\s]", " ", str(name).casefold())).strip()


def get_patient(patient_id):
    return next((p for p in patients if str(p.get("patient_id")) == str(patient_id)), None)


def find_patients(name):
    """Return {"match_type": exact|token|prefix|fuzzy|none, "patients": [...]}.

    exact  - full name equal            ("Priya Verma")
    token  - every query word equals a name word ("Priya", "Sharma")
    prefix - query words are prefixes of name words ("Pri") -> must be confirmed
    fuzzy  - close spelling ("Priyaa Verma")              -> must be confirmed
    """
    q = _norm(name) if isinstance(name, str) else ""
    if not q:
        return {"match_type": "none", "patients": []}
    q_tokens = q.split()
    named = [(p, _norm(p.get("name", ""))) for p in patients]

    exact = [p for p, n in named if n == q]
    if exact:
        return {"match_type": "exact", "patients": exact}

    token = [p for p, n in named if all(t in n.split() for t in q_tokens)]
    if token:
        return {"match_type": "token", "patients": token}

    prefix = [p for p, n in named
              if all(len(t) >= 3 and any(w.startswith(t) for w in n.split()) for t in q_tokens)]
    if prefix:
        return {"match_type": "prefix", "patients": prefix}

    close = set(difflib.get_close_matches(q, [n for _, n in named], n=5, cutoff=0.82))
    fuzzy = [p for p, n in named if n in close]
    if fuzzy:
        return {"match_type": "fuzzy", "patients": fuzzy}
    return {"match_type": "none", "patients": []}


def search_patient(name):
    """Backwards-compatible: just the list of matching patients."""
    return find_patients(name)["patients"]


def _candidate(p):
    return {"patient_id": p.get("patient_id"), "name": p.get("name"),
            "date_of_birth": p.get("date_of_birth"), "gender": p.get("gender")}


# ------------------------------------------------------------------- reports
def get_patient_reports(patient_id, report_type=None):
    wanted, _ = normalize_report_type(report_type)
    return [r for r in reports
            if str(r.get("patient_id")) == str(patient_id)
            and (wanted is None or str(r.get("report_type")).casefold() == wanted.casefold())]


def get_latest_report(patient_id, report_type=None):
    matching = get_patient_reports(patient_id, report_type)
    if not matching:
        return None
    return max(matching, key=lambda r: (str(r.get("date", "")), str(r.get("report_id", ""))))


def _enrich(report, patient):
    out = dict(report)
    out["patient_id"] = patient.get("patient_id")
    out["patient_name"] = patient.get("name")
    out["patient"] = {"patient_id": patient.get("patient_id"), "name": patient.get("name")}
    return out


def _available(patient_id):
    rows = sorted(get_patient_reports(patient_id), key=lambda r: r["date"], reverse=True)
    return [{"report_id": r["report_id"], "report_type": r["report_type"], "date": r["date"]} for r in rows]


def open_patient_report(patient_name=None, report_type=None, patient_id=None):
    """Resolve the patient, then return their latest report of the given type.

    Status values: success | ambiguous | not_found | needs_patient |
                   invalid_report_type | report_not_found
    """
    wanted, valid = normalize_report_type(report_type)
    if not valid:
        return {"status": "invalid_report_type",
                "message": f"Unsupported report type '{report_type}'. Supported types: "
                           f"{', '.join(SUPPORTED_REPORT_TYPES)}.",
                "supported_report_types": SUPPORTED_REPORT_TYPES}

    if patient_id:
        patient = get_patient(patient_id)
        if patient is None:
            return {"status": "not_found", "message": f"No patient with ID {patient_id}."}
        if isinstance(patient_name, str) and patient_name.strip():
            matching_ids = {
                match["patient_id"] for match in find_patients(patient_name)["patients"]
            }
            if patient["patient_id"] not in matching_ids:
                return {
                    "status": "not_found",
                    "message": (
                        f"Patient name '{patient_name.strip()}' does not match ID {patient_id}."
                    ),
                }
    else:
        if not isinstance(patient_name, str) or not patient_name.strip():
            return {"status": "needs_patient", "message": "Which patient? Please give a name or patient ID."}
        found = find_patients(patient_name)
        matches, mtype = found["patients"], found["match_type"]
        if not matches:
            return {"status": "not_found", "message": f"No patient found matching '{patient_name.strip()}'."}
        if len(matches) > 1 or mtype in {"prefix", "fuzzy"}:
            if len(matches) > 1 and mtype in {"exact", "token"}:
                msg = f"{len(matches)} patients match '{patient_name.strip()}'. Which one do you mean?"
            else:
                msg = f"No exact match for '{patient_name.strip()}'. Did you mean one of these?"
            return {"status": "ambiguous", "match_type": mtype, "message": msg,
                    "requested_report_type": wanted,
                    "patients": [_candidate(p) for p in matches]}
        patient = matches[0]

    report = get_latest_report(patient["patient_id"], wanted)
    if report is None:
        have = sorted({r["report_type"] for r in get_patient_reports(patient["patient_id"])})
        return {"status": "report_not_found",
                "message": f"No {wanted or ''} report found for {patient['name']} ({patient['patient_id']}). "
                           f"Available report types: {', '.join(have) if have else 'none'}.".replace("No  ", "No "),
                "patient_id": patient["patient_id"], "patient_name": patient["name"],
                "available_reports": _available(patient["patient_id"])}

    return {"status": "success", "patient_id": patient["patient_id"], "patient_name": patient["name"],
            "gender": patient.get("gender"), "report": _enrich(report, patient),
            "available_reports": _available(patient["patient_id"])}


def get_report_by_id(report_id):
    for report in reports:
        if str(report.get("report_id")) == str(report_id):
            patient = get_patient(report.get("patient_id"))
            return _enrich(report, patient) if patient else dict(report)
    return None


def open_report_by_id(report_id):
    """Same response shape as open_patient_report, for one specific report."""
    report = get_report_by_id(report_id)
    if report is None or not get_patient(report.get("patient_id")):
        return {"status": "not_found", "message": f"No report with ID {report_id}."}
    patient = get_patient(report["patient_id"])
    return {"status": "success", "patient_id": patient["patient_id"], "patient_name": patient["name"],
            "gender": patient.get("gender"), "report": report,
            "available_reports": _available(patient["patient_id"])}
