# 🦷 VI-SCAN Dental Assistant

**A Voice-First Dental Assistant for Patient Report Retrieval and Clinical Dictation**

VI-SCAN Dental Assistant is a Python-based application built with FastAPI and Streamlit to support dental reporting workflows through voice interaction, patient report retrieval, and structured clinical draft generation.

The application is designed to help users locate patient reports and convert dictated clinical observations into editable drafts while highlighting uncertainty and keeping the clinician in control of the final report.

## ✨ Features

- 🎙️ **Voice-Based Interaction** — Interact with the assistant using supported voice workflows.
- 🔎 **Patient Report Retrieval** — Search for patient reports using patient names and report-related requests.
- ⚠️ **Ambiguity Handling** — Handle similar patient names and missing reports.
- 📝 **Clinical Dictation** — Generate editable, structured drafts from clinical observations.
- ✅ **Uncertainty Indicators** — Highlight uncertain information for clinician review.
- 💬 **Report Workflow Support** — Include report summarization within the existing clinical draft/report workflow.
- ⚙️ **REST API** — Provide backend functionality through FastAPI.
- 🖥️ **Interactive Interface** — Use a Streamlit-based frontend.
- 🧪 **Automated Testing** — Include tests for core application functionality.
- 📂 **Synthetic Data** — Use mock patient and report records for development and testing.

## 🛠️ Tech Stack

| Technology | Purpose |
|---|---|
| Python | Application logic |
| FastAPI | Backend API |
| Streamlit | User interface |
| JSON | Synthetic patient and report data |
| Pytest | Automated testing |

## 📁 Project Structure

```text
viscan-dental-assistant/
├── app/
│   ├── main.py
│   ├── ui.py
│   ├── assistant.py
│   ├── clinical_draft.py
│   ├── conversation.py
│   ├── interpreter.py
│   ├── retrieval.py
│   └── ...
├── data/
│   ├── patients.json
│   └── reports.json
├── docs/
│   ├── ARCHITECTURE.md
│   ├── COVER_NOTE.md
│   └── DEMO_OUTPUT.md
├── scripts/
├── tests/
├── .env.example
├── requirements.txt
└── README.md
```

## 🚀 Getting Started

### Prerequisites

- Python installed on your system
- pip package manager

### 1. Install dependencies

Open a terminal in the project directory and run:

```bash
pip install -r requirements.txt
```

### 2. Start the backend

```bash
python -m uvicorn app.main:app --reload
```

API documentation will be available at:

`http://127.0.0.1:8000/docs`

### 3. Start the frontend

Open another terminal in the project directory and run:

```bash
python -m streamlit run app/ui.py
```

Open the local URL displayed in the terminal.

### 4. Run tests

```bash
python -m pytest -q
```

## 📚 Documentation

- **System Architecture:** `docs/ARCHITECTURE.md`
- **Submission Notes:** `docs/COVER_NOTE.md`
- **Demo Outputs:** `docs/DEMO_OUTPUT.md`


## ⚠️ Current Limitations

- The report-based chatbot and its context-aware follow-up functionality are not yet fully functional.
- Optional external LLM services may require configuration and further validation.
- The application has not been validated for clinical use.

## 🔮 Future Improvements

- Complete and validate report-based chatbot functionality.
- Improve context-aware follow-up questions.
- Enhance error handling, test coverage, and usability.
- Integrate supported workflows into a more unified assistant experience.
- Explore model training or fine-tuning using an appropriate dataset, subject to data availability and privacy requirements.

## 🔒 Data Privacy and Safety

This project uses synthetic/mock patient and report data for development and demonstration.

Generated clinical drafts are intended for review by a qualified clinician and must not be treated as diagnoses or a replacement for professional clinical judgment.

API keys and other secrets should be stored in local environment variables and must not be committed to the repository.

## 👨‍💻 Author

**Farhan Khan**

---

*Developed as part of the VI-SCAN Diagnostics*
