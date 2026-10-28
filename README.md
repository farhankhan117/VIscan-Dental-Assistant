# VI-SCAN Dental Assistant (proof of concept)

A voice-first dental assistant backend that (A) finds patient reports from a typed or spoken request, (B) turns clinical
dictation into a structured, reviewable draft, (C) handles context-dependent follow-ups such as "Summarize her report",
and (bonus) answers questions grounded in the selected report.

> **Synthetic data only. Not a medical device. Every draft requires clinician review.**

## Quick start

On Windows, run these from the project directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env  # optional; no key is needed for offline mode
```

Start the API in terminal 1:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn main:app --app-dir app --reload
```

Start the UI in terminal 2:

```powershell
.\.venv\Scripts\Activate.ps1
python -m streamlit run app/ui.py
```

Open the UI at `http://localhost:8501`; the API docs are at `http://127.0.0.1:8000/docs`.
Run the offline tests and regenerate the demo output with:

```powershell
python -m pytest -v
python scripts/run_demo.py
```

It runs fully **without any API key** (deterministic rules). Add `LLM_API_KEY` to switch on LLM interpretation and
LLM dictation extraction; both are validated and fall back to the rules on any failure.

One persistent English voice control is shared across all workspaces, with behavior routed to the active page; a
quick-switch bar links the workspaces. The standalone Voice Assistant page has been removed; use the control at
the top of the active workspace. The Clinical Draft microphone creates a draft automatically after a pause and then stops listening;
start it again for another dictation. Review its structured
findings and readable report before use. The report-chat microphone sends questions only to the selected report
chatbot, and report answers appear as text without spoken playback. General dental education requires a configured LLM; only the question is sent to it, never the selected or uploaded report. Say “move to the clinical draft”, “open Find Patient
Report”, “show the report chatbot”, or “switch to Dashboard” to navigate by voice. “Open voice assistant” returns
to Dashboard. Common speech-recognition typos and filler after a recognized workspace name are tolerated; ambiguous
destinations are not guessed. The Clinical Draft page summarizes the
number of extracted observations and verbatim items needing clinician interpretation. A report lookup stays on the current page; the selected report is available to the chatbot without an automatic workspace switch. Clinical dictation on the Clinical Draft page creates a draft after a pause. Say “open Clinical Draft” to switch
there. On that page, speech other than a clear page-navigation command is saved
as the draft source transcript and converted into a review-required draft.
Use Chrome or Edge and allow microphone access. Voice recognition and playback are English-only. After a pause,
the audio is sent to the configured Whisper-compatible English transcription endpoint when available; the result
replaces the live preview and is sent to the active page's voice handler. In offline mock mode, browser English
recognition is used as a fallback. No send/generate button click is needed after speaking; the transcript and
resulting draft remain editable. To enable provider transcription, set `LLM_API_KEY` and `STT_PROVIDER=api` in
`.env` and restart the API. Clinical dictation compares a successful provider transcript with the browser preview; if they differ, review both and optionally use the browser preview before rebuilding the draft. Use **Clear** beside the microphone to discard a recording or clear the transcript.

Start the microphone for a hands-free conversation. On Dashboard, Find Patient Report, and Ask About a Report,
short pauses submit each spoken turn automatically; the assistant speaks English replies where applicable and
stays ready for the next command. Clinical Draft stops listening after a dictated turn. Use **Test voice** beside the microphone
to check browser speech output and device volume. Switching workspaces keeps the shared voice control active, and
clinical dictation cancels queued speech before creating the draft. Saying “stop” or “end” ends the conversation
without a spoken confirmation; late microphone audio and speech playback are discarded. It does not interrupt with
repeated idle questions. Clinical Draft preserves the transcript for review. Allowing echo cancellation, noise
suppression and automatic gain control helps in noisy rooms. Temporary browser speech-recognition interruptions are
retried while the conversation is active. When names match multiple patients, say the selected patient ID digit by digit (for example,
“P zero two one”, “P 0 2 1” or “patient twenty one”); spoken report IDs such as “R zero zero five” are also
accepted. If the speech provider mishears an ID, the browser transcript is checked before asking again. The
pending patient and report type remain in context until a valid choice is made. Say **“stop”** or **“end
conversation”**, or tap the microphone to end the session. English voice commands work in offline mode. After opening a report, the
assistant reads its key details. You can ask
follow-up questions or dictate clinical
observations without restarting the microphone.

Each workspace function has its own focused page in the sidebar; dashboard quick actions open the corresponding
page. The Ask About a Report page includes report search and chat attachments; search by patient name or ID, choose the report type,
and explicitly select the correct patient when names are similar. The selected report becomes the chatbot source,
and changing reports clears the previous conversation. Search accepts a patient name, ID, or both; if both are
provided they must identify the same patient. Report upload is optional; the report chatbot also accepts PDF, DOCX, and image uploads
(PNG/APNG, JPEG/JFIF, WebP, TIFF, BMP, GIF, ICO, PNM, TGA, and PCX variants). Text-based PDFs and DOCX files are extracted locally by the API; scanned
PDFs and images use local Tesseract OCR. Install Tesseract OCR and ensure `tesseract.exe` is on `PATH` to enable
OCR. Uploads are size-limited by `MAX_UPLOAD_BYTES` (10 MB by default) and are kept only in the API's in-memory
session until it expires or the API restarts; uploaded content is not kept as a permanent file. Attach a report directly in the chat input, optionally with a question; an upload without a question is summarized from its extracted text, and the report stays active for follow-ups. The Clinical Draft page shows a readable report and editable finding/site/certainty fields, plus editable structured JSON containing only findings (observation, anatomical site, and certainty) and `readable_draft_report`. JSON edits are validated and applied to the draft; edited fields require clinician confirmation, and source transcript evidence
is retained internally but omitted from the editable JSON. Unrecognized speech is preserved verbatim as an unclassified observation
with its source phrase and an explicitly unstated anatomical site; it is never silently converted into a dental
finding. If provider transcription is unavailable on the Clinical Draft page, the original browser transcript can
still be drafted for clinician review. Use **Correct transcript and rebuild the
draft** to fix speech-recognition errors and regenerate the report/findings from the corrected transcript.
Voice replies are spoken in English where applicable. Report-chat answers are displayed as text.

## Try it (curl)

```bash
curl -s localhost:8000/assistant/message -H 'content-type: application/json' \
  -d '{"text":"Open Priya Verma'"'"'s latest OPG report"}'
# take session_id from the response, then:
curl -s localhost:8000/assistant/message -H 'content-type: application/json' \
  -d '{"text":"Summarize her report","session_id":"<session_id>"}'
```
More scenarios with real outputs: [`docs/DEMO_OUTPUT.md`](docs/DEMO_OUTPUT.md).

## Synthetic dataset

The fictional dataset is stored in [`data/patients.json`](data/patients.json) and
[`data/reports.json`](data/reports.json). Patient records contain `patient_id`, `name`, `date_of_birth`, and `gender`.
Report records contain `report_id`, `patient_id`, `report_type`, an ISO `date` (`YYYY-MM-DD`), a string array of
`findings`, readable `report_text`, and `synthetic: true`. It includes 50 patients (including duplicate/similar names)
and 100 reports, with at least two reports per patient. The app validates unique IDs, patient references, supported
report types, dates, findings, synthetic markers, and minimum dataset coverage when loading the data at startup.
Report searches use the dataset's exact stored type labels (`OPG`, `IOPA`, `Bitewing`, `CBCT`); unsupported synonyms
such as "panoramic" are rejected rather than silently substituted for another report type.

## Model / provider choices

| Role | Default | Why |
|---|---|---|
| LLM (intent parsing, optional dictation extraction) | Any OpenAI-compatible chat API; default `llama-3.3-70b-versatile` on Groq | Free tier, JSON mode, low latency. Change `LLM_BASE_URL` / `LLM_MODEL` for OpenAI, OpenRouter, Gemini's OpenAI endpoint or local Ollama. Verify the model name on your provider's console. |
| Speech-to-text and translation | `whisper-large-v3` via the same API (`STT_PROVIDER=api`) | `/audio/translations` converts supported speech languages to English; `mock` mode is for offline demos. |
| Everything else | No model | Retrieval, validation, ambiguity checks, summaries and chatbot answers are deterministic code. |

## Environment variables (`.env.example`)

`LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, `STT_PROVIDER` (`api`|`mock`), `STT_BASE_URL`,
`STT_MODEL`,
`API_KEY` (optional shared secret, sent as `X-API-Key`), `MAX_INPUT_CHARS`, `SESSION_TTL_SECONDS`,
`VISCAN_API_URL` / `VISCAN_API_KEY` (UI).

## API

| Endpoint | Purpose |
|---|---|
| `GET /dashboard/summary` | Synthetic patient/report counts for the dashboard |
| `POST /assistant/message` | **Main entry.** `{text, session_id?, patient_id?}`: interpret, validate, run tools, answer with sources |
| `POST /transcribe` | Audio file plus `task=transcribe` (optional `language=en|hi`) or `task=translate` (English output); review it, then send to `/assistant/message` |
| `POST /reports/search` | Structured retrieval: `{patient_name? , patient_id?, report_type?}` |
| `POST /dictation/draft` | `{transcript}` to structured draft JSON |
| `POST /conversation/follow-up` | `{message, session_id}`, uses server-side context |
| `POST /chatbot/ask` | `{question, report_id? or session_id}`; follow-ups inherit the previous question's topic only for the same active report |
| `POST /chatbot/clear` | `{session_id}` clears server-side chatbot follow-up context |

Outcomes are returned as HTTP 200 with a `status` field (`success`, `ambiguous`, `report_not_found`, `needs_context`,
`needs_clarification`, `not_in_report`, `unsupported_question`, `draft`, ...). Malformed requests get 422, bad API key 401.

## How it stays safe (see `docs/ARCHITECTURE.md`)

* **LLM interprets, code decides.** The model only returns `{intent, patient_name, report_type, ...}`. Pydantic parses it;
  `validators.py` rejects it if, for example, the patient name contains a word the clinician never said. Patient lookup,
  ambiguity and report selection are deterministic (`retrieval.py`).
* **Never guess identity.** Several matches, a typo or a partial name all end in a question, never an auto-pick. A pronoun
  is resolved only from the server-side session, and a gender mismatch ("his" for a female patient) triggers a question.
* **Never invent findings.** Each draft finding carries the exact `source_phrase`; LLM-proposed findings that are not
  traceable to the transcript are discarded and listed in `rejected_findings`. A tooth number is only given when the
  wording identifies the tooth ("lower left molar" stays a region). Explicit FDI numbers (including spoken numbers
  such as "tooth thirty six") and bare valid FDI numbers near a recognised finding are supported; a number is never
  inferred from an unspecified region. Named regions such as "lower right jaw" are preserved. Hedges and negations
  are labelled. `requires_clinician_review` is always `true`.
* **Grounded answers.** Chatbot and summaries quote the report's own sentences with report ID, type, date and finding
  index. The Ask About a Report page shows a persistent conversational thread, supports follow-up questions about the
  same report, and accepts voice input through the shared microphone. "Not mentioned" is never turned into "absent".
  Prognosis/treatment questions are refused.
* **Client data is not trusted.** The earlier design accepted a `previous_result` object from the client; context now
  lives on the server and the report is re-read from the dataset on every turn.

## Tests

`python -m pytest -v` runs the offline test suite (LLM/STT are faked, and the real HTTP client code is exercised against a local fake provider). The three assignment-required tests are
`test_correct_report_retrieval`, `test_ambiguous_patient_identity_exact_duplicate` and
`test_unsupported_claim_from_llm_is_discarded` (plus `test_draft_never_invents_findings`).

## Production considerations

* **Privacy.** Real use would involve PHI. Required: encryption in transit and at rest, no PHI in logs (logs here record
  only intent/status/latency), a BAA/DPA with any LLM/STT vendor or a self-hosted model, data-residency review, and
  de-identification where possible. Only the utterance (not the patient database) is sent to the LLM.
* **Authorization.** This PoC has one optional shared `API_KEY`. Production needs per-clinician authentication (OIDC),
  role- and clinic-scoped access to patients, an audit trail of who opened which report, and object-level checks
  (`/chatbot/ask` accepts a `report_id`, which must be authorized per user).
* **Latency.** The rules path answers in about 1 ms (see `latency_ms` in each response). An LLM call adds a network round trip
  (bounded by `LLM_TIMEOUT_SECONDS`, one retry on malformed JSON only, then fallback to rules). Not benchmarked against a live provider.
* **Cost.** An interpretation call is roughly 300-400 tokens and a dictation extraction 400-600, so cost per request is
  small, and zero on a free tier or in rules-only mode. Measure with your provider's pricing. Cheap mitigations: skip the
  LLM when rules are confident, cache nothing PHI-related, and use a small model for interpretation.
* **Reliability.** Timeouts, bad JSON, schema errors and provider outages degrade to rules; unexpected exceptions return a
  generic 500/`error` without internals; inputs are length-limited and sanitised; sessions expire (`SESSION_TTL_SECONDS`).

## Known limitations

* The LLM/STT client code is tested against a local fake OpenAI-compatible server, not a live provider. Run once with a real key before demoing (`LLM_API_KEY=...`) and check `llm_enabled: true` on `GET /`.
* Summaries and chatbot answers are extractive (they quote the report). They do not paraphrase or reason across findings.
* Dictation vocabulary is a fixed list of common findings; unknown wording is kept verbatim and flagged. English only.
  Bare tooth numbers are only recognised when they form a valid FDI number near a recognised finding; ambiguous numbers
  elsewhere are not treated as sites. Chatbot topic answers only use matching statements from the selected report.
* Sessions are in memory (single process). No persistence, no multi-user isolation beyond the session id.
* Patient matching is name-based; no phonetic matching for spoken Indian names beyond simple fuzzy matching.
* STT accuracy on dental terms is not evaluated; the UI makes the transcript editable before processing.
* No real PACS/EHR integration, no imaging model (out of scope).

## Project structure

```
app/  main.py (API) · assistant.py (pipeline) · interpreter.py · validators.py · retrieval.py (tools)
      clinical_draft.py · conversation.py · report_chatbot.py · session.py · llm.py · stt.py · vocab.py · config.py · ui.py
data/ patients.json (50, incl. 4 duplicate-name pairs) · reports.json (100)      scripts/ generate_mock_data.py · run_demo.py
tests/  docs/ARCHITECTURE.md · DEMO_OUTPUT.md · COVER_NOTE.md
```
