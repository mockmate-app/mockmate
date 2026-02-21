"""
MockMate — Cloud Run entrypoint
FastAPI backend that wires together all ADK agents and exposes
REST + WebSocket endpoints consumed by the Next.js frontend.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
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


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
async def health_check():
    return {"status": "ok", "service": "mockmate-backend"}


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

@app.post("/resume/upload", tags=["resume"])
async def upload_resume(user_id: str, file: UploadFile = File(...)):
    """Parse an uploaded résumé PDF/DOCX and store structured data."""
    content = await file.read()
    result = await app.state.resume_parser.parse(
        file_bytes=content,
        filename=file.filename,
        user_id=user_id,
    )
    return {"user_id": user_id, "resume_data": result}


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

@app.post("/session/start", tags=["session"])
async def start_session(config: SessionConfig):
    """Generate personalised interview questions and create a session."""
    questions = await app.state.question_generator.generate(
        user_id=config.user_id,
        persona=config.persona,
        job_role=config.job_role,
        difficulty=config.difficulty,
    )
    session_id = await app.state.interview_engine.create_session(
        user_id=config.user_id,
        questions=questions,
        persona=config.persona,
    )
    return {"session_id": session_id, "question_count": len(questions)}


@app.post("/session/{session_id}/end", tags=["session"])
async def end_session(session_id: str):
    """Mark a session as complete."""
    await app.state.interview_engine.end_session(session_id)
    return {"session_id": session_id, "status": "ended"}


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

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
    """
    await websocket.accept()
    engine: InterviewEngineAgent = websocket.app.state.interview_engine
    try:
        await engine.run_live_session(websocket, session_id)
    except WebSocketDisconnect:
        await engine.end_session(session_id)


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

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8080)), reload=True)
