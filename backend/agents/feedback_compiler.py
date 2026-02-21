"""
FeedbackCompilerAgent
----------------------
After a session ends, aggregates all data sources (transcript, posture scores,
session metadata) and calls Gemini 1.5 Flash to produce:
  - A multimodal feedback report (tone, vocabulary, posture, confidence, structure)
  - A mock hiring decision letter (offer or rejection with specific reasoning)

Results are persisted in Firestore and returned to the caller.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import vertexai
from google.cloud import firestore
from vertexai.generative_models import GenerativeModel, Part

_PROJECT = os.getenv("GCP_PROJECT_ID", "mockmate-project")
_REGION = os.getenv("GCP_REGION", "us-central1")
_COL_SESSIONS = "sessions"
_COL_POSTURE = "posture_scores"
_COL_FEEDBACK = "feedback"

FEEDBACK_PROMPT = """
You are a world-class interview coach and talent evaluator.

Below is the full data from a mock interview session. Analyse it holistically
and return ONLY a JSON object matching this schema exactly:

{{
  "overall_score": <0-100>,
  "dimension_scores": {{
    "communication": <0-100>,
    "confidence": <0-100>,
    "structure": <0-100>,
    "technical_depth": <0-100>,
    "domain_vocabulary": <0-100>,
    "posture_presence": <0-100>
  }},
  "strengths": ["<strength 1>", "<strength 2>", "<strength 3>"],
  "improvement_areas": ["<area 1>", "<area 2>", "<area 3>"],
  "filler_words": {{"count": <int>, "examples": ["<word>", ...]}},
  "vocabulary_calibration": "<brief assessment>",
  "tone_analysis": "<brief assessment>",
  "posture_summary": "<brief assessment based on posture data>",
  "decision": "offer" | "rejection",
  "decision_letter": "<full text of the mock offer or rejection letter, signed 'The MockMate Hiring Committee'>"
}}

--- Session metadata ---
{session_meta}

--- Interview transcript ---
{transcript}

--- Posture scores (aggregated) ---
{posture_summary}
"""


class FeedbackCompilerAgent:
    """Compiles multimodal feedback and mock hiring decision after a session."""

    def __init__(self) -> None:
        vertexai.init(project=_PROJECT, location=_REGION)
        self._model = GenerativeModel("gemini-1.5-flash")
        self._db = firestore.AsyncClient(project=_PROJECT)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def compile(self, session_id: str) -> dict[str, Any]:
        session = await self._fetch_session(session_id)
        posture_avg = await self._aggregate_posture(session_id)
        report = await self._generate_report(session, posture_avg)
        report["session_id"] = session_id
        report["compiled_at"] = datetime.now(timezone.utc).isoformat()
        await self._persist(session_id, report)
        return report

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    async def _fetch_session(self, session_id: str) -> dict[str, Any]:
        doc = await self._db.collection(_COL_SESSIONS).document(session_id).get()
        if not doc.exists:
            raise ValueError(f"Session '{session_id}' not found.")
        return doc.to_dict()

    async def _aggregate_posture(self, session_id: str) -> dict[str, Any]:
        """Compute mean posture scores across all frames for the session."""
        query = (
            self._db.collection(_COL_POSTURE)
            .where("session_id", "==", session_id)
        )
        docs = query.stream()
        scores = {
            "posture_score": [],
            "eye_contact_score": [],
            "facial_confidence_score": [],
            "overall_presence_score": [],
        }
        observations: list[str] = []
        async for doc in docs:
            data = doc.to_dict()
            for key in scores:
                if key in data:
                    scores[key].append(data[key])
            observations.extend(data.get("observations", []))

        avg = {k: (sum(v) / len(v) if v else 0) for k, v in scores.items()}
        avg["top_observations"] = list(set(observations))[:5]
        return avg

    async def _generate_report(
        self, session: dict[str, Any], posture_avg: dict[str, Any]
    ) -> dict[str, Any]:
        meta = {
            "user_id": session.get("user_id"),
            "persona": session.get("persona"),
            "questions_count": len(session.get("questions", [])),
            "status": session.get("status"),
            "created_at": session.get("created_at"),
            "ended_at": session.get("ended_at"),
        }
        transcript_lines = session.get("transcript", [])
        transcript_text = "\n".join(
            f"{entry.get('role', 'unknown').upper()}: {entry.get('text', '')}"
            for entry in transcript_lines
        )

        prompt = FEEDBACK_PROMPT.format(
            session_meta=json.dumps(meta, indent=2),
            transcript=transcript_text or "(no transcript recorded)",
            posture_summary=json.dumps(posture_avg, indent=2),
        )
        response = await self._model.generate_content_async(
            [Part.from_text(prompt)],
            generation_config={"response_mime_type": "application/json"},
        )
        return json.loads(response.text)

    async def _persist(self, session_id: str, report: dict[str, Any]) -> None:
        await self._db.collection(_COL_FEEDBACK).document(session_id).set(report)
