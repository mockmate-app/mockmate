"""
QuestionGeneratorAgent
----------------------
Generates a personalised, ordered question set for a mock interview session
by combining the candidate's résumé data with the chosen interviewer persona
and target job role. Uses Gemini 2.0 Flash via Vertex AI, mirrors the
structure and conventions of ResumeParserAgent.

Flow
----
  1. Validate persona / difficulty inputs.
  2. Fetch the latest parsed résumé for the user from Firestore.
  3. Build a structured prompt and call Gemini 2.0 Flash.
  4. Strip any accidental markdown fences from the model response.
  5. Persist the question set to Firestore (keyed by session_id).
  6. Return the question list to the caller.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import vertexai
from google.cloud import firestore
from vertexai.generative_models import GenerationConfig, GenerativeModel, Part

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (override via environment variables)
# ---------------------------------------------------------------------------


def _require(var: str) -> str:
    """Return env var value or raise a clear error if it is missing/empty."""
    val = os.getenv(var, "").strip()
    if not val:
        raise EnvironmentError(
            f"Required environment variable '{var}' is not set. "
            f"Add it to your .env file and restart the server."
        )
    return val


_PROJECT              = _require("GOOGLE_CLOUD_PROJECT")
_REGION               = _require("GOOGLE_CLOUD_LOCATION")
_COLLECTION_RESUMES   = os.getenv("FIRESTORE_RESUME_COLLECTION", "resumes")    # optional
_COLLECTION_SESSIONS  = os.getenv("FIRESTORE_SESSION_COLLECTION", "sessions")  # optional
_DATABASE             = os.getenv("FIRESTORE_DATABASE", "(default)")            # optional
_MODEL                = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-001")       # optional

# ---------------------------------------------------------------------------
# Persona registry
# ---------------------------------------------------------------------------

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
    "product_manager": (
        "A seasoned product manager who probes user empathy, data-driven decision making, "
        "prioritisation frameworks, and cross-functional stakeholder management. "
        "Expects quantified product outcomes and clear discovery processes."
    ),
    "vp_engineering": (
        "A VP of Engineering who evaluates engineering leadership, team building, process maturity, "
        "and architectural decision-making at scale. Asks about org design, hiring, and managing "
        "technical risk across multiple teams."
    ),
    "management_consultant": (
        "A management consultant who expects MECE thinking, hypothesis-led communication, and "
        "quantitative analysis. Asks for structured recommendations backed by market data and "
        "clear problem-solving frameworks."
    ),
    "cto": (
        "A Chief Technology Officer who balances big-picture technology strategy with deep "
        "architectural judgment. Probes build-vs-buy decisions, handling technical debt at "
        "company scale, and leading engineering org transformation."
    ),
    "recruiter": (
        "An executive recruiter who focuses on career narrative, motivations behind transitions, "
        "cultural fit, and self-awareness. Asks what the candidate is optimising for next and "
        "probes soft skills like communication and adaptability."
    ),
}

_VALID_DIFFICULTIES = {"easy", "medium", "hard"}

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

GENERATION_PROMPT = """\
You are an expert interview coach designing a mock interview question set.
Return ONLY a valid JSON array — no markdown fences, no prose outside the array.

Candidate résumé data (JSON):
{resume_json}

Interviewer persona : {persona_name}
Persona description : {persona_desc}

Target job role     : {job_role}
Difficulty level    : {difficulty}  (easy | medium | hard)

━━━ CRITICAL: ROLE-SPECIFIC QUESTIONS ━━━

The target job role is **{job_role}**. This MUST drive the majority of your question design:

1. At least 4 out of 8 questions MUST be directly relevant to the day-to-day
   responsibilities, skills, and challenges of a {job_role}.
   - For example, if the role is "DevOps Engineer", ask about CI/CD pipelines,
     infrastructure-as-code, monitoring, incident response, container orchestration, etc.
   - If the role is "Product Manager", ask about prioritisation frameworks,
     stakeholder management, metrics, roadmap trade-offs, etc.
   - If the role is "Data Scientist", ask about model selection, feature engineering,
     A/B testing, production ML pipelines, etc.
   - Adapt to ANY role — do not use generic questions that could apply to any job.

2. Technical questions MUST match the domain of {job_role}:
   - Do NOT ask front-end questions to a backend engineer.
   - Do NOT ask system design questions to a non-technical role.
   - DO ask role-appropriate technical depth (e.g. SQL optimisation for a Data Analyst,
     security architecture for a Security Engineer, etc.)

3. Behavioural and situational questions should be framed in contexts relevant to {job_role}:
   - Instead of generic "tell me about a time you led a team", ask
     "tell me about a time you led a {job_role}-specific initiative" or relate the
     scenario to challenges typical of the role.

━━━ GENERAL RULES ━━━

Generate exactly 8 interview questions as a JSON array. Each element must have:
{{
  "id"        : <1-based integer>,
  "type"      : "behavioural" | "technical" | "situational" | "curveball",
  "question"  : "<the question text>",
  "intent"    : "<one sentence — why this question is being asked>",
  "follow_ups": ["<follow-up 1>", "<follow-up 2>"]
}}

Rules (strictly enforced):
- At least 3 questions MUST reference specific details found in the résumé
  (e.g. a named project, technology, company, or metric the candidate listed).
- At least 2 questions MUST be curveballs — unexpected angle or provocative
  challenge designed to test composure and original thinking.
- Questions MUST escalate in difficulty from id 1 → 8.
- Tone and phrasing MUST match the persona described above.
- If difficulty is "easy", avoid highly technical deep-dives but still keep questions role-relevant.
- If difficulty is "hard", include at least 3 technical / system-design questions
  appropriate for {job_role}.
- Do NOT include generic filler questions. Every question should feel tailored
  to this specific candidate applying for this specific role.
"""

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class QuestionGeneratorAgent:
    """Generates a personalised interview question set and persists it to Firestore."""

    def __init__(self) -> None:
        logger.info(
            "QuestionGeneratorAgent config — project=%s  region=%s  "
            "firestore_db=%s  resume_col=%s  session_col=%s  model=%s",
            _PROJECT, _REGION, _DATABASE, _COLLECTION_RESUMES, _COLLECTION_SESSIONS, _MODEL,
        )
        vertexai.init(project=_PROJECT, location=_REGION)
        self._model = GenerativeModel(_MODEL)
        self._db = firestore.AsyncClient(project=_PROJECT, database=_DATABASE)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        user_id: str,
        persona: str,
        job_role: str,
        difficulty: str,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Generate a personalised interview question set.

        Parameters
        ----------
        user_id    : str   Authenticated user's ID.
        persona    : str   One of the keys in PERSONA_DESCRIPTIONS.
        job_role   : str   Target job title / role description.
        difficulty : str   "easy" | "medium" | "hard".
        session_id : str   Unused — kept for backwards-compat only.

        Returns
        -------
        list[dict]  The 8 generated question objects.

        Raises
        ------
        ValueError          If inputs fail validation or résumé is missing.
        json.JSONDecodeError If Gemini returns unparseable output.
        """
        self._validate_inputs(persona, difficulty, job_role)

        logger.info(
            "Generating questions — user=%s  persona=%s  role=%s  difficulty=%s",
            user_id, persona, job_role, difficulty,
        )

        resume_data = await self._fetch_resume(user_id)
        questions   = await self._call_gemini(resume_data, persona, job_role, difficulty)

        # NOTE: questions are NOT persisted here — the interview engine's
        # create_session() writes the single authoritative session document
        # (including questions) to Firestore.  Writing here too was causing
        # a duplicate "questions-only" session doc with a different UUID.
        logger.info(
            "Generated %d questions for user %s",
            len(questions), user_id,
        )

        return questions

    async def get_questions(self, session_id: str) -> list[dict[str, Any]] | None:
        """
        Retrieve a previously generated question set from Firestore.

        Returns the list of question objects, or *None* if not found.
        """
        doc = await self._db.collection(_COLLECTION_SESSIONS).document(session_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        return data.get("questions")

    async def get_question(
        self, session_id: str, question_id: int
    ) -> dict[str, Any] | None:
        """Return a single question by its 1-based *question_id*, or *None*."""
        questions = await self.get_questions(session_id)
        if questions is None:
            return None
        for q in questions:
            if q.get("id") == question_id:
                return q
        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_inputs(persona: str, difficulty: str, job_role: str) -> None:
        """Raise ValueError for any invalid parameters before hitting GCP."""
        if persona not in PERSONA_DESCRIPTIONS:
            valid = ", ".join(f"'{k}'" for k in PERSONA_DESCRIPTIONS)
            raise ValueError(
                f"Unknown persona '{persona}'. Valid options: {valid}."
            )
        if difficulty not in _VALID_DIFFICULTIES:
            raise ValueError(
                f"Invalid difficulty '{difficulty}'. "
                f"Must be one of: {', '.join(sorted(_VALID_DIFFICULTIES))}."
            )
        if not job_role or not job_role.strip():
            raise ValueError("job_role must not be empty.")

    async def _fetch_resume(self, user_id: str) -> dict[str, Any]:
        """Fetch the latest parsed résumé for *user_id* from Firestore."""
        doc = await self._db.collection(_COLLECTION_RESUMES).document(user_id).get()
        if not doc.exists:
            raise ValueError(
                f"No résumé found for user '{user_id}'. "
                "Please upload and parse a résumé before starting an interview."
            )
        data = doc.to_dict()
        logger.debug("Fetched résumé for user %s (resume_id=%s)", user_id, data.get("resume_id"))
        return data

    async def _call_gemini(
        self,
        resume_data: dict[str, Any],
        persona: str,
        job_role: str,
        difficulty: str,
    ) -> list[dict[str, Any]]:
        """Send the generation prompt to Gemini and return the parsed list."""
        persona_desc = PERSONA_DESCRIPTIONS[persona]
        prompt = GENERATION_PROMPT.format(
            resume_json=json.dumps(resume_data, indent=2),
            persona_name=persona,
            persona_desc=persona_desc,
            job_role=job_role,
            difficulty=difficulty,
        )

        generation_config = GenerationConfig(
            response_mime_type="application/json",
            temperature=0.7,        # some creativity, but stays structured
            max_output_tokens=4096,
        )

        logger.debug("Sending question-generation prompt to Gemini (model=%s)", _MODEL)
        response = await self._model.generate_content_async(
            [Part.from_text(prompt)],
            generation_config=generation_config,
        )

        raw_text = response.text.strip()

        # Strip accidental markdown fences (```json ... ```)
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$",           "", raw_text)

        try:
            questions = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            logger.error(
                "Gemini returned non-JSON output (first 500 chars): %s", raw_text[:500]
            )
            raise json.JSONDecodeError(
                f"Gemini response is not valid JSON: {exc.msg}",
                exc.doc,
                exc.pos,
            ) from exc

        if not isinstance(questions, list):
            raise ValueError(
                f"Expected a JSON array from Gemini, got {type(questions).__name__}."
            )

        logger.debug("Received %d questions from Gemini", len(questions))
        return questions
