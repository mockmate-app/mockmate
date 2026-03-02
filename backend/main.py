"""
MockMate — Cloud Run entrypoint
FastAPI backend that wires together all ADK agents and exposes
REST + WebSocket endpoints consumed by the Next.js frontend.
"""

from __future__ import annotations

# Load .env FIRST — before any module-level os.getenv() calls in agent files.
from dotenv import load_dotenv
load_dotenv(override=True)

import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Enable DEBUG logging for our agents when LOG_LEVEL=DEBUG (default: INFO)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logging.getLogger("agents").setLevel(os.getenv("LOG_LEVEL", "DEBUG").upper())

from agents.resume_parser import ResumeParserAgent
from agents.question_generator import QuestionGeneratorAgent
from agents.interview_engine import InterviewEngineAgent
from agents.posture_analyzer import PostureAnalyzerAgent
from agents.feedback_compiler import FeedbackCompilerAgent

# ---------------------------------------------------------------------------
# Lifespan — initialise/teardown shared resources
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise agents once at startup and store them on app.state
    app.state.resume_parser = ResumeParserAgent()
    app.state.question_generator = QuestionGeneratorAgent()
    app.state.interview_engine = InterviewEngineAgent()
    app.state.posture_analyzer = PostureAnalyzerAgent()
    app.state.feedback_compiler = FeedbackCompilerAgent()
    yield
    # Teardown (if needed) goes here


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="MockMate API",
    description="AI-powered mock interview platform backend.",
    version="1.0.0",
    lifespan=lifespan,
)

_raw_origins = os.getenv("ALLOWED_ORIGINS", "").strip()
_allow_origins: list[str] = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins
    else ["*"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SessionConfig(BaseModel):
    user_id: str
    persona: str = "neutral"          # e.g. "startup_founder", "investment_banker"
    job_role: str = "Software Engineer"
    difficulty: str = "medium"        # "easy" | "medium" | "hard"


class FeedbackRequest(BaseModel):
    session_id: str


class SessionEndRequest(BaseModel):
    ended_by: str | None = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
async def health_check():
    return {"status": "ok", "service": "mockmate-backend"}


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

_ACCEPTED_CONTENT_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "text/plain",
}
_ACCEPTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt"}


@app.post("/resume/upload", tags=["resume"], status_code=201)
async def upload_resume(user_id: str, file: UploadFile = File(...)):
    """
    Upload a résumé (PDF / DOCX) and return structured JSON.

    **Flow**
    1. Validate file type.
    2. Upload raw bytes to Google Cloud Storage.
    3. Extract text and call Gemini 2.0 Flash for structured parsing.
    4. Persist result in Firestore (keyed by *user_id*).
    5. Return structured JSON.

    **Query params**
    - `user_id` — authenticated user's ID (required).

    **Form data**
    - `file` — the résumé file (PDF, DOCX, DOC, or TXT).
    """
    if not user_id or not user_id.strip():
        raise HTTPException(status_code=400, detail="user_id must not be empty.")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ACCEPTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type '{ext}'. "
                f"Accepted extensions: {', '.join(sorted(_ACCEPTED_EXTENSIONS))}"
            ),
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > 10 * 1024 * 1024:  # 10 MB guard
        raise HTTPException(status_code=413, detail="File exceeds the 10 MB size limit.")

    try:
        result = await app.state.resume_parser.parse(
            file_bytes=content,
            filename=file.filename,
            user_id=user_id.strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Resume parsing failed for user %s", user_id)
        raise HTTPException(status_code=500, detail=f"Resume parsing failed: {exc}") from exc

    return JSONResponse(
        status_code=201,
        content={
            "user_id":     user_id,
            "resume_id":   result.get("resume_id"),
            "gcs_uri":     result.get("gcs_uri"),
            "parsed_at":   result.get("parsed_at"),
            "resume_data": result,
        },
    )


@app.get("/resume/{user_id}", tags=["resume"])
async def get_resume(user_id: str):
    """
    Retrieve the most-recently parsed résumé for *user_id* from Firestore.

    Returns 404 if no résumé has been parsed for this user yet.
    """
    try:
        data = await app.state.resume_parser.get_resume(user_id)
    except Exception as exc:
        logger.exception("Firestore read failed for user %s", user_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"No parsed résumé found for user '{user_id}'.",
        )

    return {"user_id": user_id, "resume_data": data}


@app.get("/resume/{user_id}/file", tags=["resume"])
async def get_resume_file(user_id: str):
    """
    Stream the raw uploaded résumé file (PDF / DOCX) from GCS.
    Returns 404 if no résumé exists for this user.
    """
    try:
        result = await app.state.resume_parser.get_resume_file(user_id)
    except Exception as exc:
        logger.exception("GCS download failed for user %s", user_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"No résumé file found for user '{user_id}'.",
        )
    file_bytes, content_type = result
    return StreamingResponse(
        iter([file_bytes]),
        media_type=content_type,
        headers={"Content-Disposition": "inline"},
    )

@app.post("/session/start", tags=["session"])
async def start_session(config: SessionConfig):
    """Generate personalised interview questions and create a session."""
    questions = await app.state.question_generator.generate(
        user_id=config.user_id,
        persona=config.persona,
        job_role=config.job_role,
        difficulty=config.difficulty,
    )
    session_meta = await app.state.interview_engine.create_session(
        user_id=config.user_id,
        questions=questions,
        persona=config.persona,
        job_role=config.job_role,
    )
    return {
        "session_id":     session_meta["session_id"],
        "interviewer_name": session_meta["interviewer_name"],
        "voice": session_meta["voice"],
        "question_count": len(questions),
        "questions":      questions,
        "persona":        config.persona,
        "job_role":       config.job_role,
        "difficulty":     config.difficulty,
    }


@app.get("/session/{session_id}/questions", tags=["session"])
async def get_session_questions(session_id: str):
    """Retrieve the generated question set for an existing session."""
    questions = await app.state.question_generator.get_questions(session_id)
    if questions is None:
        raise HTTPException(
            status_code=404,
            detail=f"No questions found for session '{session_id}'.",
        )
    return {"session_id": session_id, "questions": questions, "question_count": len(questions)}


@app.get("/session/{session_id}", tags=["session"])
async def get_session(session_id: str):
    """Return lightweight metadata for a single session."""
    data = await app.state.interview_engine.get_session(session_id)
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found.",
        )
    return data


@app.post("/session/{session_id}/end", tags=["session"])
async def end_session(session_id: str, req: SessionEndRequest | None = None):
    """Mark a session as complete."""
    await app.state.interview_engine.end_session(
        session_id,
        ended_by=req.ended_by if req else None,
    )
    return {"session_id": session_id, "status": "ended"}


@app.get("/sessions/user/{user_id}", tags=["session"])
async def list_user_sessions(user_id: str, limit: int = 10):
    """Return the most-recent sessions for a user (lightweight — no full transcript)."""
    sessions = await app.state.interview_engine.get_user_sessions(user_id, limit=limit)
    return {"user_id": user_id, "sessions": sessions, "count": len(sessions)}


@app.get("/transcript/{session_id}", tags=["session"])
async def get_transcript(session_id: str):
    """Return the full transcript (list of turns) for a session."""
    data = await app.state.interview_engine.get_transcript(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Transcript not found.")
    return data


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

@app.get("/feedback/{session_id}", tags=["feedback"])
async def read_feedback(session_id: str):
    """Return a previously compiled feedback report (does NOT regenerate)."""
    report = await app.state.feedback_compiler.get_feedback(session_id)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail=f"No feedback found for session '{session_id}'.",
        )
    return report

@app.post("/feedback/generate", tags=["feedback"])
async def generate_feedback(req: FeedbackRequest):
    """Compile full multimodal feedback and mock hiring decision letter."""
    report = await app.state.feedback_compiler.compile(req.session_id)
    return report


# ---------------------------------------------------------------------------
# WebSocket — live interview audio stream
# ---------------------------------------------------------------------------

@app.websocket("/ws/interview/{session_id}")
async def websocket_interview(websocket: WebSocket, session_id: str):
    """
    Streams audio chunks from the browser to the Gemini Live API and
    returns AI interviewer responses in real time.
    run_live_session() fully manages the session lifecycle (including ending
    it), so we do NOT call end_session() here on disconnect.
    """
    await websocket.accept()
    engine: InterviewEngineAgent = websocket.app.state.interview_engine
    try:
        await engine.run_live_session(websocket, session_id)
    except WebSocketDisconnect:
        logger.debug("Browser disconnected from /ws/interview/%s", session_id)
    except Exception as exc:
        logger.error(
            "Unhandled error in /ws/interview/%s — %s: %s",
            session_id, type(exc).__name__, exc,
        )


# ---------------------------------------------------------------------------
# WebSocket — posture / vision stream
# ---------------------------------------------------------------------------

@app.websocket("/ws/vision/{session_id}")
async def websocket_vision(websocket: WebSocket, session_id: str):
    """
    Receives base-64 encoded video frames from the browser and returns
    real-time posture & presence scores.
    """
    await websocket.accept()
    analyzer: PostureAnalyzerAgent = websocket.app.state.posture_analyzer
    try:
        await analyzer.run_live_analysis(websocket, session_id)
    except WebSocketDisconnect:
        pass


# ---------------------------------------------------------------------------
# Entrypoint (local dev)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8080)),
        reload=True,
        # Only watch the agents package — main.py is always watched automatically.
        # Do NOT include "." here; it would pull in .venv and trigger constant reloads.
        reload_dirs=["agents"],
    )
