# Submission note (edit to your own words before sending)

**What works**
- Feature A: natural-language retrieval ("Open Priya's latest OPG report") with intent/entity extraction, deterministic
  lookup, "latest" by date, ambiguity handling (exact duplicates, first-name-only, typos), missing-report and unsupported-type handling.
- Feature B: dictation to editable structured JSON (observation, site with FDI tooth number when stated, certainty,
  source phrase) plus a readable draft, always flagged for clinician review. Nothing is added that was not dictated.
- Feature C: server-side conversation memory; "Summarize her report" resolves "her" without re-asking, shows report ID/type/date and the
  exact findings used; asks when there is no context, an unresolved ambiguity, or a gender mismatch.
- Bonus: report-grounded chatbot (extractive answers with evidence; "not mentioned" never becomes "absent"; prognosis/treatment refused).
- LLM (OpenAI-compatible, optional) only interprets and proposes; code validates. Falls back to rules on any failure.
- 91 automated tests (offline), Streamlit UI, STT endpoint, mock dataset (50 patients, 4 duplicate-name pairs, 100 reports),
  documented demo calls (`docs/DEMO_OUTPUT.md`), README and architecture doc.

**What is incomplete**
- The LLM and Whisper client code is tested against a local fake provider but I have not benchmarked a live provider. Offline behaviour is fully verified.
- Summaries/answers are extractive rather than generative; the dictation vocabulary is limited and English only.
- In-memory sessions, a single shared API key instead of real authN/authZ, no audit log, no benchmarking against a live provider.

**With more time**
- Generative summaries with sentence-level citation verification; a larger, clinician-reviewed dental vocabulary / terminology mapping.
- Persistent sessions (Redis), per-clinician auth with scoped access and audit logging, PHI-safe logging and a self-hosted model option.
- Evaluation set for STT on dental terms and for dictation extraction (precision/recall of findings, hallucination rate).
- Phonetic matching for Indian names, voice confirmation of the candidate list, and the scan-booking agent with a confirm-before-write step.
