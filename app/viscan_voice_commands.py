"""Small deterministic helpers for voice-only workspace navigation."""
from difflib import SequenceMatcher
import re


_NAVIGATION_ALIASES = {
    "Dashboard": (
        "dashboard",
        "home",
        "home page",
        "homepage",
        "main page",
        "workspace home",
        "voice assistant",
        "assistant page",
        "talk to assistant",
        "voice page",
        "assistant",
    ),
    "Find Patient Report": (
        "find patient report",
        "patient report search",
        "find a patient",
        "find patient",
        "patient search",
        "search reports",
        "find report",
        "report search",
        "patient records",
    ),
    "Clinical Draft": (
        "clinical draft",
        "clinical dictation",
        "dictation page",
        "draft page",
        "draft",
        "dictation",
    ),
    "Ask About a Report": (
        "ask about a report",
        "ask report",
        "report assistant",
        "report chatbot",
        "chatbot page",
        "report chat",
        "ask chatbot",
    ),
}
_NAVIGATION_PREFIX = re.compile(
    r"^\s*(?:(?:please|hey|okay|ok|can\s+you)\s+)?"
    r"(?:(?:i\s+(?:want|need)\s+to\s+)?"
    r"(?:go|move|switch|navigate)\s+(?:me\s+)?to|"
    r"take\s+me\s+to|switch\s+to|go\s+to|navigate\s+to|open|show(?:\s+me)?)\s+"
    r"(?:the\s+)?(.+?)\s*$",
    re.I,
)
_TRAILING_FILLER = re.compile(
    r"\s+(?:or\s+(?:somewhere|something|some place)|somewhere|something|some place|"
    r"now|please|for me|to there|there)\s*[.!?]*\s*$",
    re.I,
)
_FUZZY_THRESHOLD = 0.76
_FUZZY_MARGIN = 0.06


def _normalize(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", text.casefold())).strip()


def _page_for_destination(destination):
    destination = re.sub(r"\s+page$", "", destination.strip(), flags=re.I)
    destination = re.sub(r"^(?:the|my)\s+", "", destination, flags=re.I)
    destination = _normalize(destination)
    for page, aliases in _NAVIGATION_ALIASES.items():
        if destination in {_normalize(alias) for alias in aliases}:
            return page

    scores = []
    for page, aliases in _NAVIGATION_ALIASES.items():
        best_score = max(
            SequenceMatcher(None, destination, _normalize(alias)).ratio()
            for alias in aliases
        )
        scores.append((best_score, page))
    scores.sort(reverse=True)
    if (
        scores
        and scores[0][0] >= _FUZZY_THRESHOLD
        and (len(scores) == 1 or scores[0][0] - scores[1][0] >= _FUZZY_MARGIN)
    ):
        return scores[0][1]
    return None


def _clean_destination(destination):
    destination = destination.strip().rstrip(".!?")
    destination = re.sub(r"\s+page$", "", destination, flags=re.I)
    while True:
        cleaned = _TRAILING_FILLER.sub("", destination).strip()
        if cleaned == destination:
            return destination
        destination = cleaned


def navigation_target(text):
    """Resolve clear page-switch commands, allowing common speech-recognition typos."""
    if not isinstance(text, str):
        return None
    clean_text = text.strip().rstrip(".!?")
    match = _NAVIGATION_PREFIX.match(clean_text)
    if match:
        destination = _clean_destination(match.group(1))
        page = _page_for_destination(destination)
        if page:
            return page
    return None


def voice_route(text, current_page):
    """Route navigation before page-specific questions and draft dictation."""
    destination = navigation_target(text)
    if destination:
        return "navigate", destination
    if current_page == "Ask About a Report":
        return "report_chat", None
    if current_page == "Clinical Draft":
        return "dictation", None
    return "assistant", None
