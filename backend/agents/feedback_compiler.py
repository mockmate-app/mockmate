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
import logging
import os
from datetime import datetime, timezone
from typing import Any

import vertexai
from google.cloud import firestore
from vertexai.generative_models import GenerationConfig, GenerativeModel, Part

logger = logging.getLogger(__name__)


def _require(var: str) -> str:
    """Return env var value or raise a clear error if it is missing/empty."""
    val = os.getenv(var, "").strip()
    if not val:
        raise EnvironmentError(
            f"Required environment variable '{var}' is not set. "
            f"Add it to your .env file and restart the server."
        )
    return val


_PROJECT      = _require("GOOGLE_CLOUD_PROJECT")
_REGION       = _require("GOOGLE_CLOUD_LOCATION")
_DATABASE     = os.getenv("FIRESTORE_DATABASE", "(default)")               # optional
_MODEL        = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-001")           # optional
_COL_SESSIONS     = os.getenv("FIRESTORE_SESSION_COLLECTION", "sessions")       # optional
_COL_TRANSCRIPTS  = os.getenv("FIRESTORE_TRANSCRIPT_COLLECTION", "transcripts") # optional
_COL_POSTURE      = os.getenv("FIRESTORE_POSTURE_COLLECTION", "posture_scores") # optional
_COL_FEEDBACK     = os.getenv("FIRESTORE_FEEDBACK_COLLECTION", "feedback")      # optional

FEEDBACK_PROMPT = """
You are a rigorous, unbiased interview coach and senior hiring manager.
Your job is to produce HONEST, ACCURATE, SPECIFIC feedback grounded entirely
in what actually happened in the transcript below. Do NOT invent positives
or soften negatives — if the candidate was rude, disrespectful, incoherent,
or unprofessional, say so directly and reflect it in every relevant score.

Target role context (apply before scoring anything):
- The candidate is interviewing for: {job_role}
- Infer the typical years of experience (YoE) a competitive hire for this role
  would have (e.g. Junior SWE ≈ 0-2 yrs, Senior SWE ≈ 5+ yrs, Staff ≈ 8+ yrs,
  VP/Director ≈ 12+ yrs). State that assumed YoE range in your feedback.
- Calibrate every dimension score against the bar expected for THAT role at THAT
  seniority level — not against a generic standard.
  * A junior candidate who gives textbook answers for their level should score
    well, even if a senior engineer would have gone deeper.
  * A candidate interviewing for a senior/principal/director role who gives
    shallow or junior-level answers should score poorly, even if those answers
    would be acceptable for an early-career hire.
- In decision_letter, explicitly state the assumed YoE bar for the role and
  explain whether the candidate met, exceeded, or fell short of it.

Scoring rules (enforce strictly):
- communication  : clarity, articulation, active listening, professional tone.
  Deduct heavily for interrupting, rudeness, hostility, dismissiveness.
- confidence     : calm, grounded delivery — NOT arrogance or aggression.
- structure      : organised, logical answers (STAR / clear reasoning).
- technical_depth: depth and accuracy of domain knowledge demonstrated,
  evaluated against the depth expected for the target role's seniority.
- domain_vocabulary: correct and sophisticated use of role-appropriate
  terminology; senior/specialist roles demand higher precision.
- posture_presence: based solely on posture data provided.
- overall_score  : weighted average reflecting the whole picture faithfully,
  anchored to the target role's expectations.

Tone & professionalism:
- If the candidate was rude, sarcastic, hostile, dismissive, or used
  inappropriate language, call it out explicitly in tone_analysis.
- This MUST be reflected in lower communication and confidence scores.
- Do NOT award high overall scores to candidates who were unprofessional,
  regardless of technical ability.

If the transcript is absent or very short, set all scores to 0 and say so.

Return ONLY valid JSON matching this schema exactly — no markdown fences,
no extra keys, no trailing commas:

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
  "strengths": ["<specific strength from transcript>", ...],
  "improvement_areas": ["<specific, actionable improvement>", ...],
  "filler_words": {{"count": <int>, "examples": ["<word>", ...]}},
  "vocabulary_calibration": "<assessment with examples from transcript>",
  "tone_analysis": "<honest assessment of tone, attitude, and professionalism — cite specific moments>",
  "posture_summary": "<assessment based strictly on posture data>",
  "decision": "offer" | "rejection",
  "decision_letter": "<full text of the mock offer or rejection letter, signed 'The MockMate Hiring Committee'>"
}}

--- Session metadata ---
{session_meta}

--- Interview transcript ---
(Format: SPEAKER: text — INTERVIEWER is the AI, CANDIDATE is the person being evaluated)
{transcript}

--- Posture scores (aggregated) ---
{posture_summary}
"""


class FeedbackCompilerAgent:
    """Compiles multimodal feedback and mock hiring decision after a session."""

    def __init__(self) -> None:
        logger.info(
            "FeedbackCompilerAgent config — project=%s  region=%s  "
            "firestore_db=%s  model=%s",
            _PROJECT, _REGION, _DATABASE, _MODEL,
        )
        vertexai.init(project=_PROJECT, location=_REGION)
        self._model = GenerativeModel(_MODEL)
        self._db = firestore.AsyncClient(project=_PROJECT, database=_DATABASE)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def compile(self, session_id: str) -> dict[str, Any]:
        session = await self._fetch_session(session_id)
        transcript_turns = await self._fetch_transcript(session_id)
        posture_avg = await self._aggregate_posture(session_id)
        report = await self._generate_report(session, transcript_turns, posture_avg)
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

    async def _fetch_transcript(self, session_id: str) -> list[dict[str, Any]]:
        """Fetch transcript turns from the dedicated transcripts collection."""
        doc = await self._db.collection(_COL_TRANSCRIPTS).document(session_id).get()
        if not doc.exists:
            logger.warning("No transcript found for session '%s'", session_id)
            return []
        return doc.to_dict().get("turns", [])

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
        self, session: dict[str, Any], transcript_turns: list[dict[str, Any]], posture_avg: dict[str, Any]
    ) -> dict[str, Any]:
        meta = {
            "user_id": session.get("user_id"),
            "persona": session.get("persona"),
            "job_role": session.get("job_role", "Software Engineer"),
            "questions_count": len(session.get("questions", [])),
            "status": session.get("status"),
            "created_at": session.get("created_at"),
            "ended_at": session.get("ended_at"),
        }

        job_role = meta["job_role"]

        # Build transcript text — turns are {speaker: user|interviewer, text, ts}
        if transcript_turns:
            lines = []
            for entry in transcript_turns:
                speaker = entry.get("speaker", "unknown")
                label = "CANDIDATE" if speaker == "user" else "INTERVIEWER"
                text = entry.get("text", "").strip()
                if text:
                    lines.append(f"{label}: {text}")
            transcript_text = "\n".join(lines)
        else:
            transcript_text = "(no transcript recorded — do not fabricate content; set all scores to 0)"

        prompt = FEEDBACK_PROMPT.format(
            job_role=job_role,
            session_meta=json.dumps(meta, indent=2),
            transcript=transcript_text,
            posture_summary=json.dumps(posture_avg, indent=2),
        )
        response = await self._model.generate_content_async(
            [Part.from_text(prompt)],
            generation_config=GenerationConfig(
                response_mime_type="application/json",
                temperature=0.3,
                max_output_tokens=4096,
            ),
        )
        return json.loads(response.text)

    async def _persist(self, session_id: str, report: dict[str, Any]) -> None:
        await self._db.collection(_COL_FEEDBACK).document(session_id).set(report)
        # Write top-level score back to the session doc so dashboard queries
        # can show scores without loading the full feedback document.
        try:
            await self._db.collection(_COL_SESSIONS).document(session_id).update({
                "overall_score":  report.get("overall_score"),
                "feedback_ready": True,
            })
        except Exception:  # noqa: BLE001
            pass  # best-effort; don't fail the whole compile if this update fails

    async def get_feedback(self, session_id: str) -> dict[str, Any] | None:
        """Return a previously compiled feedback report, or None if not found."""
        doc = await self._db.collection(_COL_FEEDBACK).document(session_id).get()
        if not doc.exists:
            return None
        return doc.to_dict()
