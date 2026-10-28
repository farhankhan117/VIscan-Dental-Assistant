"""Regenerate data/patients.json and data/reports.json (100% synthetic).

    python scripts/generate_mock_data.py

Keeps the original 50 patients (adds `gender`). Hand-written reports are
used for the demo-critical patients; everyone else gets seeded random but
clinically sensible findings. Re-running gives identical output.
"""
import json
import random
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"

FEMALE_FIRST = {"Priya", "Aisha", "Neha", "Sara", "Meera", "Ananya", "Ishita", "Pooja", "Zoya", "Nisha",
                "Maya", "Tanya", "Diya", "Ritika", "Simran", "Lavanya", "Fatima", "Aditi", "Shreya", "Mira",
                "Anjali", "Sana", "Kavya"}

patients = json.loads((DATA / "patients.json").read_text(encoding="utf-8"))
for p in patients:
    p["gender"] = "F" if p["name"].split()[0] in FEMALE_FIRST else "M"

# --------------------------------------------------------------- curated reports
CURATED = {
    "P001": [  # Priya Sharma (1995) - two OPGs so "latest" is meaningful, plus an IOPA
        ("OPG", "2025-03-12", ["Mild horizontal alveolar bone loss in the lower left molar region.",
                               "No periapical radiolucency is seen.",
                               "Upper right third molar (18) is missing."]),
        ("IOPA", "2026-01-15", ["Periapical radiolucency at the apex of tooth 36."]),
        ("OPG", "2026-03-02", ["Lower right third molar (48) is mesioangularly impacted.",
                               "Mesial caries on tooth 37.",
                               "Mild maxillary sinus pneumatization is noted bilaterally."]),
    ],
    "P021": [  # second "Priya Sharma" (1993)
        ("OPG", "2025-09-05", ["Upper left third molar (28) is vertically impacted.",
                               "Radiopaque restoration in tooth 46 with no evident secondary caries."]),
        ("Bitewing", "2026-02-10", ["Interproximal caries on the distal surface of tooth 36.",
                                    "Calculus deposits are noted interproximally."]),
    ],
    "P002": [  # Priya Verma
        ("OPG", "2025-03-12", ["Generalized mild horizontal alveolar bone loss in the posterior regions.",
                               "Radiopaque restoration in tooth 46 with no evident secondary caries.",
                               "No periapical radiolucency is seen."]),
        ("OPG", "2026-05-20", ["Lower left third molar (38) is horizontally impacted.",
                               "Root canal filling is present in tooth 26.",
                               "Periapical radiolucency associated with tooth 36."]),
        ("CBCT", "2026-06-11", ["The root of the lower left third molar (38) lies in close proximity to the inferior alveolar canal.",
                                "No cortical fracture is seen."]),
    ],
    "P006": [  # Neha Kapoor - deliberately has NO OPG (missing-report test)
        ("IOPA", "2025-11-02", ["Widening of the periodontal ligament space at tooth 46."]),
        ("CBCT", "2026-04-18", ["Adequate bone height is noted in the lower right first molar region.",
                                "No cortical fracture is seen."]),
    ],
    "P003": [("OPG", "2025-08-14", ["Lower right third molar (48) is distoangularly impacted.",
                                    "No periapical radiolucency is seen."]),
             ("IOPA", "2026-02-27", ["Root canal filling in tooth 26 is adequately condensed."])],
    "P026": [("OPG", "2025-12-01", ["Full coverage crown on tooth 16.",
                                    "Mild horizontal alveolar bone loss in the posterior regions."]),
             ("IOPA", "2026-03-19", ["No periapical pathology is seen at tooth 16."])],
    "P004": [("OPG", "2025-06-09", ["Occlusal caries on tooth 46.", "No periapical radiolucency is seen."]),
             ("Bitewing", "2026-01-22", ["Interproximal caries on the distal surface of tooth 36."])],
    "P031": [("OPG", "2025-10-30", ["Lower left third molar (38) is horizontally impacted."]),
             ("OPG", "2026-04-04", ["Lower left third molar (38) is horizontally impacted.",
                                    "Distal caries on tooth 37."])],
    "P005": [("OPG", "2025-07-21", ["Upper right third molar (18) is missing.",
                                    "Mild maxillary sinus pneumatization is noted bilaterally."]),
             ("CBCT", "2026-05-08", ["No cortical fracture is seen."])],
    "P036": [("OPG", "2025-09-17", ["Periapical radiolucency at the apex of tooth 11."]),
             ("IOPA", "2026-02-03", ["Periapical radiolucency at the apex of tooth 11.",
                                     "Widening of the periodontal ligament space at tooth 11."])],
}

# --------------------------------------------------------------- random pools
OPG_SLOTS = [
    [None, "Lower right third molar (48) is mesioangularly impacted.",
     "Lower left third molar (38) is horizontally impacted.", "Upper left third molar (28) is vertically impacted."],
    [None, "Occlusal caries on tooth 46.", "Mesial caries on tooth 37.", "Distal caries on tooth 26."],
    ["No periapical radiolucency is seen.", "Periapical radiolucency associated with tooth 36.",
     "Periapical radiolucency at the apex of tooth 11."],
    [None, "Mild horizontal alveolar bone loss in the posterior regions.", "Localized vertical bone loss at tooth 31."],
    [None, "Radiopaque restoration in tooth 46 with no evident secondary caries.",
     "Root canal filling is present in tooth 26.", "Full coverage crown on tooth 16."],
    [None, "Mild maxillary sinus pneumatization is noted bilaterally.", "Upper right third molar (18) is missing."],
]
IOPA_TEMPLATES = ["Periapical radiolucency at the apex of tooth {t}.",
                  "Root canal filling in tooth {t} is adequately condensed.",
                  "Widening of the periodontal ligament space at tooth {t}.",
                  "No periapical pathology is seen at tooth {t}."]
BITEWING_POOL = ["Interproximal caries on the distal surface of tooth {t}.",
                 "Mild horizontal bone loss in the posterior regions.",
                 "Calculus deposits are noted interproximally.",
                 "No interproximal caries is seen."]
CBCT_POOL = ["The root of tooth 38 lies in close proximity to the inferior alveolar canal.",
             "No cortical fracture is seen.",
             "Adequate bone height is noted in the lower right first molar region."]
TEETH = [11, 16, 26, 36, 37, 46, 47]


def random_reports(rng):
    out = []
    opg = [s for s in (rng.choice(slot) for slot in OPG_SLOTS) if s]
    out.append(("OPG", f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}", opg[:4]))
    kind = rng.choice(["IOPA", "Bitewing", "CBCT", "OPG"])
    date = f"2026-{rng.randint(1, 9):02d}-{rng.randint(1, 28):02d}"
    t = rng.choice(TEETH)
    if kind == "IOPA":
        out.append((kind, date, [rng.choice(IOPA_TEMPLATES).format(t=t)]))
    elif kind == "Bitewing":
        out.append((kind, date, [x.format(t=t) for x in rng.sample(BITEWING_POOL, 2)]))
    elif kind == "CBCT":
        out.append((kind, date, rng.sample(CBCT_POOL, 2)))
    else:
        out.append((kind, date, [s for s in (rng.choice(slot) for slot in OPG_SLOTS) if s][:3]))
    return out


rng = random.Random(42)
reports, n = [], 0
excluded_reports = {
    # Keep report IDs stable while maintaining the 100-report demo dataset.
    ("P001", "IOPA", "2026-01-15"),
    ("P002", "OPG", "2025-03-12"),
}
for p in patients:
    rows = CURATED.get(p["patient_id"]) or random_reports(rng)
    for rtype, date, findings in sorted(rows, key=lambda r: r[1]):
        n += 1
        if (p["patient_id"], rtype, date) in excluded_reports:
            continue
        reports.append({
            "report_id": f"R{n:03d}", "patient_id": p["patient_id"], "report_type": rtype,
            "date": date, "findings": findings, "report_text": " ".join(findings), "synthetic": True,
        })

(DATA / "patients.json").write_text(json.dumps(patients, indent=2, ensure_ascii=False), encoding="utf-8")
(DATA / "reports.json").write_text(json.dumps(reports, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"wrote {len(patients)} patients, {len(reports)} reports")
