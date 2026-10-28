"""Dental vocabulary + pure text helpers. No database, no LLM, no I/O.

Everything here is deterministic, so the rule-based path and the validation
of LLM output can share exactly the same logic.
"""
import re

# ---------------------------------------------------------------- report types
SUPPORTED_REPORT_TYPES = ["OPG", "IOPA", "Bitewing", "CBCT"]

_TYPE_ALIASES = {
    "opg": "OPG",
    "iopa": "IOPA",
    "bitewing": "Bitewing", "bite-wing": "Bitewing", "bite wing": "Bitewing",
    "cbct": "CBCT",
}

_TYPE_PATTERNS = [
    (re.compile(r"\bopg\b", re.I), "OPG"),
    (re.compile(r"\biopa\b", re.I), "IOPA"),
    (re.compile(r"\bbite[\s-]?wings?\b", re.I), "Bitewing"),
    (re.compile(r"\b(?:cbct|cone[\s-]?beam)\b", re.I), "CBCT"),
]


def normalize_report_type(value):
    """Return (canonical_type_or_None, is_valid). None / 'any' means 'no filter'."""
    if value is None:
        return None, True
    v = str(value).strip().casefold()
    if v in {"", "any", "any report", "all", "report"}:
        return None, True
    if v in _TYPE_ALIASES:
        return _TYPE_ALIASES[v], True
    for canonical in SUPPORTED_REPORT_TYPES:
        if v == canonical.casefold():
            return canonical, True
    return None, False


def extract_report_type(text):
    """Find a report type mentioned in free text (rule-based)."""
    for pattern, canonical in _TYPE_PATTERNS:
        if pattern.search(text or ""):
            return canonical
    return None


# ---------------------------------------------------------------- tooth sites
_VERT = {"upper": "upper", "maxillary": "upper", "lower": "lower", "mandibular": "lower"}
_QUAD_DIGIT = {("upper", "right"): 1, ("upper", "left"): 2, ("lower", "left"): 3, ("lower", "right"): 4}
_DIGIT_QUAD = {v: " ".join(k) for k, v in _QUAD_DIGIT.items()}
_ORD = {"1st": "first", "2nd": "second", "3rd": "third"}
_TOOTH_NUMBER = {
    ("central", "incisor"): 1, ("lateral", "incisor"): 2,
    ("first", "premolar"): 4, ("second", "premolar"): 5,
    ("first", "molar"): 6, ("second", "molar"): 7, ("third", "molar"): 8,
}
TOOTH_NAME = {1: "central incisor", 2: "lateral incisor", 3: "canine", 4: "first premolar",
              5: "second premolar", 6: "first molar", 7: "second molar", 8: "third molar"}

_V, _H = r"upper|lower|maxillary|mandibular", r"right|left"
_ORDW = r"central|lateral|first|second|third|1st|2nd|3rd"
_KIND = (
    r"incisor|canine|cuspid|premolar|molar|wisdom\s+tooth|tooth|teeth|"
    r"jaw|gums?|arch|alveolar\s+ridge|ridge|palate|cheek|lip|tongue"
)
_NAMED_SITE = re.compile(
    rf"\b(?:(?P<v>{_V})\s+(?P<h>{_H})|(?P<h2>{_H})\s+(?P<v2>{_V}))"
    rf"(?:\s+(?:(?P<ord>{_ORDW})\s+)?(?P<kind>{_KIND})s?)?", re.I)
_EXPLICIT = re.compile(
    r"(?:\b(?:tooth|teeth)\s*(?:no\.?|number)?|#)\s*"
    r"((?:[1-4][1-8])(?:\s*(?:,|and|&|/)\s*[1-4][1-8])*)\b", re.I)
_PAREN = re.compile(r"\(([1-4][1-8])\)")
_SPOKEN_FDI = re.compile(
    r"\b(?:(?:tooth|teeth)\s+(?:number\s+)?)?"
    r"(?P<number>ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty)(?:[\s-]+(?P<ones>one|two|three|four|five|six|seven|eight|nine))?\b",
    re.I,
)
_SPOKEN_TENS = {"ten": 10, "twenty": 20, "thirty": 30, "forty": 40}
_SPOKEN_ONES = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}
_SPOKEN_TEENS = {
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_BARE_FDI = re.compile(r"(?<!\w)([1-4][1-8])(?!\w)")


def fdi_description(fdi):
    return f"{_DIGIT_QUAD[int(fdi[0])]} {TOOTH_NAME[int(fdi[1])]}"


def find_sites(text):
    """Anatomical sites mentioned in text, in order of appearance.

    A tooth number (FDI) is only produced when the wording identifies the
    tooth unambiguously ("lower right third molar", "tooth 36"). A phrase such
    as "lower left molar" is returned as a *region* with fdi_tooth=None; the
    tooth number is never guessed.
    """
    sites = []
    for m in _NAMED_SITE.finditer(text or ""):
        vert = _VERT[(m.group("v") or m.group("v2")).lower()]
        side = (m.group("h") or m.group("h2")).lower()
        quadrant = f"{vert} {side}"
        kind = re.sub(r"\s+", " ", (m.group("kind") or "").lower())
        ordinal = (m.group("ord") or "").lower() or None
        ordinal = _ORD.get(ordinal, ordinal)

        number = None
        if kind.startswith("wisdom"):
            number = 8
        elif kind in {"canine", "cuspid"}:
            number = 3
        elif kind:
            number = _TOOTH_NUMBER.get((ordinal, kind))

        if number:
            fdi = f"{_QUAD_DIGIT[(vert, side)]}{number}"
            label, precision = re.sub(r"\s+", " ", m.group(0).strip().lower()), "tooth"
        else:
            fdi, precision = None, "region"
            if kind in {"molar", "premolar", "incisor"}:
                label = f"{quadrant} {kind} region"
            elif kind in {"jaw", "gum", "gums", "arch", "alveolar ridge", "ridge",
                          "palate", "cheek", "lip", "tongue"}:
                label = f"{quadrant} {kind}"
            else:
                label = f"{quadrant} region"
        sites.append({"text": label, "fdi_tooth": fdi, "quadrant": quadrant,
                      "precision": precision, "start": m.start()})

    seen = {s["fdi_tooth"] for s in sites if s["fdi_tooth"]}
    explicit = [(m.start(), n) for m in _EXPLICIT.finditer(text or "")
                for n in re.findall(r"[1-4][1-8]", m.group(1))]
    explicit += [(m.start(), m.group(1)) for m in _PAREN.finditer(text or "")]
    for match in _SPOKEN_FDI.finditer(text or ""):
        number_word = match.group("number").casefold()
        if number_word in _SPOKEN_TEENS:
            if match.group("ones"):
                continue
            value = _SPOKEN_TEENS[number_word]
        else:
            if not match.group("ones"):
                continue
            value = _SPOKEN_TENS[number_word] + _SPOKEN_ONES[match.group("ones").casefold()]
        fdi = str(value)
        if len(fdi) == 2 and fdi[0] in "1234" and fdi[1] in "12345678":
            explicit.append((match.start(), fdi))
    for match in _BARE_FDI.finditer(text or ""):
        start, end = match.span()
        context = (text or "")[max(0, start - 28):min(len(text or ""), end + 28)]
        if find_observations(context):
            explicit.append((start, match.group(1)))
    for start, num in explicit:
        if num in seen:
            continue
        seen.add(num)
        sites.append({"text": f"tooth {num} ({fdi_description(num)})", "fdi_tooth": num,
                      "quadrant": _DIGIT_QUAD[int(num[0])], "precision": "tooth", "start": start})
    return sorted(sites, key=lambda s: s["start"])


def public_site(site):
    return None if site is None else {k: v for k, v in site.items() if k != "start"}


# ---------------------------------------------------------------- observations
OBSERVATION_PATTERNS = {
    "impaction": r"\bimpact(?:ed|ion)\b",
    "caries": r"\b(?:caries|carious|cavity|cavities|decay(?:ed)?)\b",
    "periapical radiolucency": r"\b(?:periapical\s+(?:radiolucenc\w+|lesions?|pathology)|radiolucenc\w+|radiolucent)\b",
    "bone loss": r"\b(?:(?:alveolar\s+)?bone\s+(?:loss|resorption))\b",
    "missing tooth": r"\b(?:missing|edentulous)\b",
    "fracture": r"\b(?:fractur\w+|cracked)\b",
    "restoration": r"\b(?:restoration|restored|filling|filled)\b",
    "root canal treatment": r"\b(?:root\s+canal|rct|endodontically\s+treated)\b",
    "crown": r"\b(?:crown|crowned)\b",
    "tenderness": r"\btender(?:ness)?\b",
    "swelling": r"\bswelling\b",
    "sinus finding": r"\bsinus\b",
    "calculus": r"\b(?:calculus|tartar)\b",
    "cyst": r"\bcyst\w*\b",
    "abscess": r"\babscess\w*\b",
    "mobility": r"\b(?:mobile|mobility)\b",
    "periodontal ligament widening": r"\bperiodontal\s+ligament\b",
    "proximity to inferior alveolar canal": r"\binferior\s+alveolar\s+canal\b",
}
_OBS_RE = {k: re.compile(v, re.I) for k, v in OBSERVATION_PATTERNS.items()}
_ANGULATION = re.compile(r"\b(horizontal|mesioangular|distoangular|vertical)(?:ly)?\b", re.I)


def find_observations(text):
    """[(canonical_name, start)] ordered by position (first hit per concept)."""
    hits = []
    for name, rx in _OBS_RE.items():
        m = rx.search(text or "")
        if m:
            hits.append((name, m.start()))
    return sorted(hits, key=lambda h: h[1])


def concepts(text):
    return {name for name, _ in find_observations(text)}


def observation_label(canonical, clause):
    """Readable label. Adds detail (e.g. 'horizontal') only if it is in the clause."""
    if canonical == "impaction":
        m = _ANGULATION.search(clause)
        if m:
            return f"{m.group(1).lower()} impaction"
    return canonical


# ------------------------------------------------------- certainty / negation
_HEDGE = re.compile(
    r"(?:\b(?:possible|possibly|probable|probably|suspected|suspicious|likely|unlikely|may|might|could|"
    r"appears?|appearing|seems?|seemingly|suggestive|suggests?|query|questionable|uncertain|not\s+sure|"
    r"cannot\s+(?:be\s+)?(?:rule[d]?\s+out|excluded))\b|\?)", re.I)
_NEG_BEFORE = re.compile(r"\b(?:no|not|without|nil|denies|negative\s+for|free\s+of|ruled\s+out)\b", re.I)
_NEG_AFTER = re.compile(r"\b(?:absent|not\s+(?:seen|present|noted|identified|evident)|ruled\s+out)\b", re.I)


def find_hedge(text):
    m = _HEDGE.search(text or "")
    return m.group(0) if m else None


def is_negated(clause, obs_start):
    before = " ".join(clause[:obs_start].split()[-4:])
    after = " ".join(clause[obs_start:].split()[:7])
    return bool(_NEG_BEFORE.search(before) or _NEG_AFTER.search(after))


def has_negation(text):
    return bool(_NEG_BEFORE.search(text or "") or _NEG_AFTER.search(text or ""))


# ------------------------------------------------------------- sentence utils
def split_sentences(text):
    parts = re.split(r"(?<=[.;!?])\s+|\n+", (text or "").strip())
    return [p.strip() for p in parts if p and p.strip()]


_CLAUSE_SPLIT = re.compile(r"\s*(?:,|\band\b|\bbut\b|\balso\b|\bwhile\b)\s*", re.I)


def split_clauses(sentence):
    """Split a sentence into clauses, but only where *both* sides contain an
    observation, so 'caries on teeth 36 and 46' stays in one piece. Every
    clause is an exact substring of the input."""
    s = sentence.strip()
    bounds, last = [], 0
    for m in _CLAUSE_SPLIT.finditer(s):
        bounds.append((last, m.start()))
        last = m.end()
    bounds.append((last, len(s)))
    clauses, (cur_start, cur_end) = [], bounds[0]
    for b_start, b_end in bounds[1:]:
        if find_observations(s[cur_start:cur_end]) and find_observations(s[b_start:b_end]):
            clauses.append(s[cur_start:cur_end].strip())
            cur_start, cur_end = b_start, b_end
        else:
            cur_end = b_end
    clauses.append(s[cur_start:cur_end].strip())
    return [c for c in clauses if c]


def norm_ws(text):
    return re.sub(r"\s+", " ", (text or "").strip()).casefold()


_STOP = set("""the a an and or of in on at to for with is are was were be been this that there their his her
its it as by from any have has had does did do what which who whom when where why how can could will would should
report reports patient tell show give about please also into than then them they she he say says said mention
mentioned mentions noted note""".split())
_SITE_WORDS = {"upper", "lower", "left", "right", "maxillary", "mandibular", "tooth", "teeth", "molar", "premolar",
               "incisor", "canine", "third", "second", "first", "region", "regions", "side"}


def content_stems(text):
    words = re.findall(r"[a-z]{4,}", (text or "").casefold())
    return {w[:5] for w in words if w not in _STOP and w not in _SITE_WORDS}
