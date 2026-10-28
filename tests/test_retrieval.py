"""Feature A: deterministic retrieval. REQUIRED tests: correct retrieval + ambiguous identity."""
import pytest

from retrieval import find_patients, get_report_by_id, open_patient_report, patients, reports, validate_dataset


def test_synthetic_dataset_is_validated_at_startup():
    validate_dataset(patients, reports)


def test_dataset_validation_rejects_reports_for_unknown_patients():
    orphan = {**reports[0], "report_id": "INVALID", "patient_id": "P999"}
    with pytest.raises(ValueError, match="unknown patient"):
        validate_dataset(patients, [*reports, orphan])


def test_dataset_validation_requires_two_reports_per_patient():
    patient_id = patients[0]["patient_id"]
    remaining = [report for report in reports if report["patient_id"] != patient_id]
    remaining.append(next(report for report in reports if report["patient_id"] == patient_id))
    with pytest.raises(ValueError, match="at least two reports"):
        validate_dataset(patients, remaining)


def test_correct_report_retrieval():
    result = open_patient_report("Priya Verma", "OPG")
    assert result["status"] == "success"
    assert result["patient_id"] == "P002"
    assert result["report"]["report_type"] == "OPG"


def test_latest_means_most_recent_date():
    result = open_patient_report("Priya Verma", "OPG")          # has OPGs dated 2025-03-12 and 2026-05-20
    assert result["report"]["date"] == "2026-05-20"


def test_report_type_is_never_substituted():
    # Priya Verma's newest report overall is a CBCT; asking for OPG must not return it.
    assert open_patient_report("Priya Verma", "CBCT")["report"]["report_type"] == "CBCT"
    assert open_patient_report("Priya Verma", "OPG")["report"]["report_type"] == "OPG"


def test_every_patient_type_filter_returns_only_latest_matching_type():
    for patient in patients:
        for report_type in {r["report_type"] for r in reports if r["patient_id"] == patient["patient_id"]}:
            matching = [
                report for report in reports
                if report["patient_id"] == patient["patient_id"]
                and report["report_type"].casefold() == report_type.casefold()
            ]
            result = open_patient_report(patient_id=patient["patient_id"], report_type=report_type)
            assert result["status"] == "success"
            assert result["report"]["patient_id"] == patient["patient_id"]
            assert result["report"]["report_type"] == report_type
            assert result["report"]["date"] == max(report["date"] for report in matching)


def test_ambiguous_patient_identity_exact_duplicate():
    result = open_patient_report("Priya Sharma", "OPG")
    assert result["status"] == "ambiguous"
    assert {p["patient_id"] for p in result["patients"]} == {"P001", "P021"}
    assert "report" not in result                                # nothing is guessed or leaked


def test_ambiguous_first_name_only():
    result = open_patient_report("Priya", "OPG")
    assert result["status"] == "ambiguous"
    assert {p["patient_id"] for p in result["patients"]} == {"P001", "P002", "P021"}


def test_candidates_include_dob_to_help_disambiguation():
    result = open_patient_report("Priya Sharma")
    assert {p["date_of_birth"] for p in result["patients"]} == {"1995-04-12", "1993-10-29"}


def test_patient_id_resolves_duplicate_name():
    result = open_patient_report(patient_id="P021", report_type="OPG")
    assert result["status"] == "success" and result["patient_name"] == "Priya Sharma"
    assert result["report"]["patient_id"] == "P021"


def test_patient_name_and_id_can_be_used_together_to_disambiguate():
    result = open_patient_report("Priya Sharma", report_type="OPG", patient_id="P021")
    assert result["status"] == "success"
    assert result["report"]["patient_id"] == "P021"


def test_patient_name_and_id_must_identify_the_same_patient():
    result = open_patient_report("Priya Verma", report_type="OPG", patient_id="P021")
    assert result["status"] == "not_found"
    assert "does not match ID" in result["message"]


def test_missing_report_for_known_patient():
    result = open_patient_report("Neha Kapoor", "OPG")           # Neha has only IOPA + CBCT
    assert result["status"] == "report_not_found"
    assert result["patient_id"] == "P006"
    assert "CBCT" in result["message"] and "report" not in result


def test_unsupported_report_type_rejected():
    assert open_patient_report("Priya Verma", "MRI")["status"] == "invalid_report_type"


@pytest.mark.parametrize("requested_type", ["panoramic", "periapical", "pano"])
def test_unstored_report_type_alias_is_not_substituted(requested_type):
    result = open_patient_report("Priya Verma", requested_type)
    assert result["status"] == "invalid_report_type"


def test_unknown_patient_and_empty_input():
    assert open_patient_report("Zzyzx Qwerty", "OPG")["status"] == "not_found"
    assert open_patient_report("   ", "OPG")["status"] == "needs_patient"
    assert open_patient_report(patient_id="P999")["status"] == "not_found"


def test_typo_needs_confirmation_never_auto_selected():
    result = open_patient_report("Prya Verma", "OPG")
    assert result["status"] == "ambiguous" and result["match_type"] == "fuzzy"
    assert [p["patient_id"] for p in result["patients"]] == ["P002"]


def test_match_types():
    assert find_patients("priya verma")["match_type"] == "exact"
    assert find_patients("Verma")["match_type"] == "token"
    assert find_patients("Pri")["match_type"] == "prefix"


def test_unknown_report_id():
    assert get_report_by_id("R999") is None
