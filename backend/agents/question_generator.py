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
import re
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable
from google.cloud import firestore
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
    before_sleep_log,
)


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (from shared config)
# ---------------------------------------------------------------------------

from agents.config import (
    PROJECT as _PROJECT,
    REGION as _REGION,
    FIRESTORE_RESUME_COLLECTION as _COLLECTION_RESUMES,
    FIRESTORE_SESSION_COLLECTION as _COLLECTION_SESSIONS,
    FIRESTORE_DATABASE as _DATABASE,
    GEMINI_MODEL as _MODEL,
)

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
    "algorithm_guru": (
        "An algorithms and data structures specialist who tests problem-solving ability, "
        "complexity analysis, and optimal data structure selection. Asks candidates to walk "
        "through their approach, probes edge cases, and pushes for more efficient solutions."
    ),
    "system_designer": (
        "A system design and architecture interviewer who evaluates scalability, reliability, "
        "and trade-off reasoning. Expects candidates to clarify requirements, break problems into "
        "components, and address failure modes and capacity estimation."
    ),
    "prompt_wizard": (
        "An AI/ML interviewer focused on machine learning fundamentals, LLM application design, "
        "prompting and evaluation strategy, model quality trade-offs, safety/guardrails, and "
        "production AI system architecture. Expects concrete discussion of metrics, data quality, "
        "and operational reliability for AI features."
    ),
    "ai_engineer": (
        "An AI/ML interviewer focused on machine learning fundamentals, LLM application design, "
        "prompting and evaluation strategy, model quality trade-offs, safety/guardrails, and "
        "production AI system architecture. Expects concrete discussion of metrics, data quality, "
        "and operational reliability for AI features."
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

━━━ MANDATORY RESUME-FIRST ANALYSIS ━━━

Before writing questions, you MUST internally process the résumé end-to-end and
build a role-fit map:

1) Read ALL relevant resume sections fully (summary, experience, projects,
    skills, achievements, education/certs).
2) Extract concrete evidence points (technologies, domains, responsibilities,
    scale, metrics, outcomes, leadership scope, timelines).
3) Correlate each evidence point with expected responsibilities of {job_role}:
    - direct match,
    - adjacent transfer,
    - likely gap / risk area.
4) Use this correlation to decide what to probe:
    - verify strongest claims,
    - test role-critical skills,
    - pressure-test probable gaps.

Do NOT ask generic résumé questions. Every question must be traceable to either:
  (a) a specific résumé evidence point, or
  (b) a role-critical competency for {job_role}.

━━━ OPTIONAL EXTERNAL GROUNDING ━━━

If needed, use grounded web knowledge to align question topics with current,
real-world expectations for {job_role} (common responsibilities, tools,
interview dimensions). Use grounding only to improve role relevance — never to
invent facts about the candidate beyond the provided résumé.

━━━ CRITICAL: ROLE-SPECIFIC QUESTIONS ━━━

The target job role is **{job_role}**. This MUST drive the majority of your question design:

1. At least 4 out of 6 questions MUST be directly relevant to the day-to-day
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

Generate exactly 6 interview questions as a JSON array. Each element must have:
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
- Questions MUST escalate in difficulty from id 1 → 6.
- Tone and phrasing MUST match the persona described above.
- If difficulty is "easy", avoid highly technical deep-dives but still keep questions role-relevant.
- If difficulty is "hard", include at least 3 technical / system-design questions
  appropriate for {job_role}.
- Do NOT include generic filler questions. Every question should feel tailored
  to this specific candidate applying for this specific role.
- At least 5 out of 6 questions must explicitly mention role-relevant concepts
    for {job_role}, and at least 4 out of 6 must be tied to concrete résumé
    evidence points.
- Every question MUST include exactly 2 follow-up prompts in "follow_ups".
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
        self._client = genai.Client(
            vertexai=True,
            project=_PROJECT,
            location=_REGION,
        )
        self._db = firestore.AsyncClient(project=_PROJECT, database=_DATABASE)
        self._grounding_tools: list[genai_types.Tool] | None = None

        try:
            self._grounding_tools = [
                genai_types.Tool(google_search=genai_types.GoogleSearch())
            ]
            logger.info("Question generation grounding enabled (Google Search).")
        except Exception as exc:
            logger.warning(
                "Question generation grounding unavailable; proceeding without it: %s",
                exc,
            )

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
        job_role   : str   Target job role / role description.
        difficulty : str   "easy" | "medium" | "hard".
        session_id : str   Unused — kept for backwards-compat only.

        Returns
        -------
        list[dict]  The 6 generated question objects.

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

        generation_config = genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.7,        # some creativity, but stays structured
            max_output_tokens=4096,
        )

        @retry(
            retry=retry_if_exception_type((ResourceExhausted, ServiceUnavailable, genai_errors.APIError)),
            wait=wait_random_exponential(multiplier=1, max=60),
            stop=stop_after_attempt(5),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        async def _generate_with_retry(tools: list[genai_types.Tool] | None):
            cfg = generation_config
            if tools:
                cfg = genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.7,
                    max_output_tokens=4096,
                    tools=tools,
                )
            return await self._client.aio.models.generate_content(
                model=_MODEL,
                contents=prompt,
                config=cfg,
            )

        logger.debug(
            "Sending question-generation prompt to Gemini (model=%s, grounding=%s)",
            _MODEL,
            bool(self._grounding_tools),
        )

        if self._grounding_tools:
            try:
                response = await _generate_with_retry(self._grounding_tools)
            except Exception as exc:
                logger.warning(
                    "Grounded question generation failed; retrying without grounding: %s",
                    exc,
                )
                response = await _generate_with_retry(None)
        else:
            response = await _generate_with_retry(None)

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

        questions = self._normalize_questions(questions)
        logger.debug("Received %d normalized questions from Gemini", len(questions))
        return questions

    @staticmethod
    def _normalize_questions(questions: list[Any]) -> list[dict[str, Any]]:
        """Normalize model output to exactly 6 questions, each with 2 follow-ups."""
        normalized: list[dict[str, Any]] = []

        for i, raw in enumerate(questions[:6], start=1):
            if not isinstance(raw, dict):
                continue

            q_text = str(raw.get("question") or "").strip()
            if not q_text:
                continue

            q_type = str(raw.get("type") or "behavioural").strip().lower()
            if q_type not in {"behavioural", "technical", "situational", "curveball"}:
                q_type = "behavioural"

            intent = str(raw.get("intent") or "Assess candidate suitability for the role.").strip()
            follow_ups_raw = raw.get("follow_ups") or []
            follow_ups = [str(f).strip() for f in follow_ups_raw if str(f).strip()]
            follow_ups = follow_ups[:2]

            while len(follow_ups) < 2:
                if len(follow_ups) == 0:
                    follow_ups.append("Can you share one concrete example from your experience?")
                else:
                    follow_ups.append("What was the measurable outcome of that decision?")

            normalized.append(
                {
                    "id": i,
                    "type": q_type,
                    "question": q_text,
                    "intent": intent,
                    "follow_ups": follow_ups,
                }
            )

        if len(normalized) < 6:
            raise ValueError(
                f"Question generator returned only {len(normalized)} usable questions; expected 6."
            )

        return normalized
