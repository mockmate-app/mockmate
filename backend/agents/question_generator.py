"""
QuestionGeneratorAgent
----------------------
Generates a personalised, ordered question set for a mock interview session
by combining the candidate's résumé data with the chosen interviewer persona
and target job role. Uses Gemini 1.5 Flash via Vertex AI.
"""

from __future__ import annotations

import json
import os
from typing import Any

import vertexai
from google.cloud import firestore
from vertexai.generative_models import GenerativeModel, Part

_PROJECT = os.getenv("GCP_PROJECT_ID", "mockmate-project")
_REGION = os.getenv("GCP_REGION", "us-central1")
_COLLECTION_RESUMES = "resumes"
_COLLECTION_SESSIONS = "sessions"

PERSONA_DESCRIPTIONS: dict[str, str] = {
    "neutral": "A professional, balanced interviewer who is thorough but fair.",
    "startup_founder": (
        "An energetic startup founder who cares deeply about ownership, bias for action, "
        "and culture fit. Asks fast-paced, open-ended questions and pushes back on vague answers."
    ),
    "investment_banker": (
        "A high-pressure investment banker who values precision, numbers, and structured thinking. "
        "Expects STAR-format answers with quantifiable results and does not tolerate filler words."
    ),
    "tech_lead": (
        "A senior engineering lead who digs into technical depth, system design trade-offs, "
        "and code quality. Asks follow-up questions that expose gaps in understanding."
    ),
    "hr_manager": (
        "An HR manager focused on behavioural competencies, team collaboration, conflict resolution, "
        "and alignment with company values."
    ),
}

GENERATION_PROMPT = """
You are an expert interview coach designing a mock interview question set.

Candidate résumé data (JSON):
{resume_json}

Interviewer persona: {persona_name}
Persona description: {persona_desc}

Target job role: {job_role}
Difficulty level: {difficulty}  (easy | medium | hard)

Generate exactly 12 interview questions as a JSON array. Each element must have:
{{
  "id": <1-based integer>,
  "type": "behavioural" | "technical" | "situational" | "curveball",
  "question": "<the question text>",
  "intent": "<why this question is being asked>",
  "follow_ups": ["<follow-up 1>", "<follow-up 2>"]
}}

Rules:
- At least 3 questions must reference specific details from the résumé.
- At least 2 questions must be curveballs (unexpected angle or challenge).
- Questions must escalate in difficulty.
- Tailor tone and phrasing to match the persona.

Return ONLY the JSON array.
"""


class QuestionGeneratorAgent:
    """Generates a personalised interview question set."""

    def __init__(self) -> None:
        vertexai.init(project=_PROJECT, location=_REGION)
        self._model = GenerativeModel("gemini-1.5-flash")
        self._db = firestore.AsyncClient(project=_PROJECT)

    async def generate(
        self,
        user_id: str,
        persona: str,
        job_role: str,
        difficulty: str,
    ) -> list[dict[str, Any]]:
        resume_data = await self._fetch_resume(user_id)
        questions = await self._call_gemini(resume_data, persona, job_role, difficulty)
        return questions

    # ------------------------------------------------------------------

    async def _fetch_resume(self, user_id: str) -> dict[str, Any]:
        doc = await self._db.collection(_COLLECTION_RESUMES).document(user_id).get()
        if not doc.exists:
            raise ValueError(f"No résumé found for user '{user_id}'. Please upload one first.")
        return doc.to_dict()

    async def _call_gemini(
        self,
        resume_data: dict[str, Any],
        persona: str,
        job_role: str,
        difficulty: str,
    ) -> list[dict[str, Any]]:
        persona_desc = PERSONA_DESCRIPTIONS.get(persona, PERSONA_DESCRIPTIONS["neutral"])
        prompt = GENERATION_PROMPT.format(
            resume_json=json.dumps(resume_data, indent=2),
            persona_name=persona,
            persona_desc=persona_desc,
            job_role=job_role,
            difficulty=difficulty,
        )
        response = await self._model.generate_content_async(
            [Part.from_text(prompt)],
            generation_config={"response_mime_type": "application/json"},
        )
        return json.loads(response.text)
