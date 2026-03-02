# MockMate — Backend

FastAPI backend for MockMate, an AI-powered mock interview platform. It exposes REST and WebSocket endpoints consumed by the Next.js frontend and orchestrates a collection of Google Vertex AI / Gemini agents.

---

## Architecture overview

```
frontend (Next.js)
       │
       │  REST / WebSocket
       ▼
  main.py  (FastAPI, Cloud Run)
       │
       ├── ResumeParserAgent       → GCS (raw file) + Firestore (structured JSON)
       ├── QuestionGeneratorAgent  → Gemini 2.0 Flash
       ├── InterviewEngineAgent    → Gemini Live API (WebSocket audio stream)
       ├── PostureAnalyzerAgent    → Gemini Vision (WebSocket video frames)
       └── FeedbackCompilerAgent  → Firestore (session data)
```

### Google Cloud services used

| Service | Purpose |
|---|---|
| **Vertex AI (Gemini 2.0 Flash)** | Resume parsing, question generation, feedback |
| **Gemini Live API** | Real-time audio interview streaming |
| **Cloud Storage** | Raw résumé file storage |
| **Cloud Firestore** | Structured resume data, session state, feedback reports |
| **Cloud Pub/Sub** | `session-end` event bus |
| **Cloud Run** | Serverless container hosting |

---

## Prerequisites

| Tool | Required version | Install |
|---|---|---|
| **Python** | **3.13 exactly** | [python.org/downloads](https://www.python.org/downloads/) |
| pip | latest | bundled with Python 3.13 |
| Google Cloud SDK | latest | [cloud.google.com/sdk](https://cloud.google.com/sdk/docs/install) |

> **Why exactly 3.13?**  
> Build issues with wheel files for _pillow_ and _pydantic-core_ is a known issue when using Python 3.14 on macOS, primarily due to compilation dependencies and early support for the new Python version. Python **3.13** has pre-built wheels for all required packages and is what the project is tested against.

Verify your Python version before continuing:

```bash
python3.13 --version
# Must print Python 3.13.x
```

If `python3.13` is not found, download it from [python.org](https://www.python.org/downloads/) or install via your package manager:

```bash
# macOS (Homebrew)
brew install python@3.13

# Ubuntu / Debian
sudo apt install python3.13 python3.13-venv
```

---

## Local development

### 1. Clone the repo

```bash
git clone https://github.com/your-org/mockmate.git
cd mockmate/backend
```

### 2. Create a virtual environment

Always use `python3.13` explicitly to avoid picking up the system Python and
triggering wheel build errors:

```bash
python3.13 -m venv .venv
```

**Activate the environment:**

| Platform | Command |
|---|---|
| macOS / Linux | `source .venv/bin/activate` |
| Windows (PowerShell) | `.venv\Scripts\Activate.ps1` |
| Windows (cmd) | `.venv\Scripts\activate.bat` |

Your prompt will change to show `(.venv)` when active. Confirm the right Python is in use:

```bash
python --version
# Should print Python 3.13.x
```

### 3. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your values:

```dotenv
# Google Cloud project
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=us-central1

# Cloud Storage — bucket must already exist
GCS_BUCKET=mockmate-storage

# Firestore — use (default) unless you created a named database
FIRESTORE_DATABASE=(default)
FIRESTORE_RESUME_COLLECTION=resumes

# Pub/Sub
PUBSUB_TOPIC_SESSION_END=session-end

# CORS — comma-separated list of allowed frontend origins
ALLOWED_ORIGINS=http://localhost:3000
```

### 5. Authenticate with Google Cloud

You have two options:

**Option A — user credentials (quickest for local dev):**
```bash
# 1. Log in and obtain application default credentials
gcloud auth application-default login

# 2. Set your active project (used by gcloud CLI commands)
gcloud config set project YOUR_PROJECT_ID

# 3. Attach the quota project to ADC (required for Vertex AI billing)
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

**Option B — service account key:**
```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
```

The service account needs these IAM roles:

| Role | Why |
|---|---|
| `roles/aiplatform.user` | Call Gemini via Vertex AI |
| `roles/storage.objectAdmin` | Upload/read files in GCS bucket |
| `roles/datastore.user` | Read/write Firestore documents |
| `roles/pubsub.publisher` | Publish session-end events |

### 6. Start the development server

Make sure your virtual environment is activated (you should see `(.venv)` in
your prompt), then run:

```bash
python main.py
```

Or with uvicorn directly for hot-reload:

```bash
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

> **Tip:** always run commands from inside the activated venv. If you see
> errors about missing modules or wrong Python version, double-check that
> `python --version` prints 3.13+ before proceeding.

The API is now available at **http://localhost:8080**.  
Interactive docs: **http://localhost:8080/docs**

---

## API reference

### Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check |

### Resume

| Method | Path | Description |
|---|---|---|
| `POST` | `/resume/upload?user_id=<id>` | Upload PDF/DOCX, parse with Gemini, store in GCS + Firestore |
| `GET` | `/resume/{user_id}` | Retrieve the latest parsed résumé for a user |

**Upload example:**
```bash
curl -X POST "http://localhost:8080/resume/upload?user_id=user_abc" \
  -F "file=@/path/to/resume.pdf"
```

**Response (201):**
```json
{
  "user_id": "user_abc",
  "resume_id": "f47ac10b-...",
  "gcs_uri": "gs://mockmate-storage/user_abc/<uuid>_resume.pdf",
  "parsed_at": "2026-02-22T13:00:00+00:00",
  "resume_data": {
    "name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "+1-555-0100",
    "summary": "...",
    "skills": ["Python", "Kubernetes"],
    "experience": [...],
    "education": [...],
    "certifications": [...],
    "bold_claims": ["Grew ARR 3× to $12M"]
  }
}
```

Accepted file types: `.pdf`, `.docx`, `.doc`, `.txt` (max 10 MB).

### Session

| Method | Path | Description |
|---|---|---|
| `POST` | `/session/start` | Generate questions and create an interview session |
| `POST` | `/session/{session_id}/end` | Mark session as complete |

**Start session body:**
```json
{
  "user_id": "user_abc",
  "persona": "neutral",
  "job_role": "Software Engineer",
  "difficulty": "medium"
}
```

`persona` options: `neutral`, `startup_founder`, `investment_banker`  
`difficulty` options: `easy`, `medium`, `hard`

### Feedback

| Method | Path | Description |
|---|---|---|
| `POST` | `/feedback/generate` | Compile full feedback report for a session |

**Body:**
```json
{ "session_id": "<session_id>" }
```

### WebSockets

| Path | Description |
|---|---|
| `ws://localhost:8080/ws/interview/{session_id}` | Real-time audio interview (send audio chunks, receive AI interviewer audio) |
| `ws://localhost:8080/ws/vision/{session_id}` | Real-time posture analysis (send base64 video frames, receive posture scores) |

---

## Typical end-to-end flow

```
1. POST /resume/upload          → get resume_id + parsed resume_data
2. POST /session/start          → get session_id + questions
3. WS  /ws/interview/{id}       → conduct live interview
4. WS  /ws/vision/{id}          → stream video for posture scoring  (parallel)
5. POST /session/{id}/end       → mark session complete
6. POST /feedback/generate      → receive full feedback report
```

---

## Docker

### Build

```bash
docker build -t mockmate-backend .
```

### Run locally

```bash
docker run -p 8080:8080 \
  --env-file .env \
  -e GOOGLE_APPLICATION_CREDENTIALS=/creds/sa-key.json \
  -v /path/to/sa-key.json:/creds/sa-key.json:ro \
  mockmate-backend
```

---

## Deploy to Cloud Run

```bash
# Build and push to Artifact Registry
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/mockmate-backend

# Deploy
gcloud run deploy mockmate-backend \
  --image gcr.io/YOUR_PROJECT_ID/mockmate-backend \
  --platform managed \
  --region us-central1 \
  --memory 1Gi \
  --cpu 1 \
  --env-vars-file cloudrun-env.yaml \
  --allow-unauthenticated

> **Tip:** Create a `cloudrun-env.yaml` file (see `.env.example` for keys) and pass it via `--env-vars-file` to safely handle env vars containing commas (e.g. `ALLOWED_ORIGINS`). Keep this file out of source control.
```

On Cloud Run the service account is attached directly — no `GOOGLE_APPLICATION_CREDENTIALS` key file is needed.

---

## Project structure

```
backend/
├── main.py                  # FastAPI app, routes, WebSocket handlers
├── requirements.txt         # Python dependencies
├── Dockerfile               # Multi-stage production image
├── .env.example             # Environment variable template
└── agents/
    ├── resume_parser.py     # GCS upload + Gemini resume extraction
    ├── question_generator.py# Personalised interview question generation
    ├── interview_engine.py  # Gemini Live API session management
    ├── posture_analyzer.py  # Real-time video posture scoring
    └── feedback_compiler.py # Post-session feedback aggregation
```
