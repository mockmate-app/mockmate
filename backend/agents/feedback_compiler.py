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

import asyncio
import json
import logging
import os
import traceback
from datetime import datetime, timezone
from typing import Any

import vertexai
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable
from google.cloud import firestore
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
    before_sleep_log,
)
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
_MODEL        = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")           # optional
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

CRITICAL — speaker attribution (MUST enforce):
- The transcript labels each line as CANDIDATE or INTERVIEWER.
- You are evaluating the CANDIDATE ONLY. The INTERVIEWER is the AI — ignore
  their words entirely when assessing vocabulary, technical depth, tone, etc.
- NEVER attribute something the INTERVIEWER said to the candidate. For example,
  if the INTERVIEWER mentions a technology, project, or metric, that does NOT
  count as the candidate demonstrating knowledge of it — unless the CANDIDATE
  also independently discusses it in their own turns.
- When citing specific words, phrases, or examples in your feedback, double-check
  the speaker label. If it says INTERVIEWER, it is NOT the candidate's language.
- Vocabulary calibration and domain_vocabulary scoring must be based EXCLUSIVELY
  on words the CANDIDATE actually spoke.

Scoring rules (enforce strictly):
- communication  : clarity, articulation, active listening, professional tone.
  Deduct heavily for unprofessional behavior, rudeness, hostility, dismissiveness.
- confidence     : calm, grounded delivery — NOT arrogance or aggression.
- structure      : organised, logical answers (STAR / clear reasoning).
- technical_depth: depth and accuracy of domain knowledge demonstrated,
  evaluated against the depth expected for the target role's seniority.
  Only count knowledge the CANDIDATE demonstrated — not topics the INTERVIEWER
  introduced or referenced from the résumé.
- domain_vocabulary: correct and sophisticated use of role-appropriate
  terminology; senior/specialist roles demand higher precision.
  Score based ONLY on vocabulary the CANDIDATE used in their own turns.
{posture_scoring_rule}
- overall_score  : weighted average reflecting the whole picture faithfully,
  anchored to the target role's expectations.
  {overall_posture_note}

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
    "domain_vocabulary": <0-100>{posture_dimension_schema}
  }},
  "strengths": ["<specific strength from transcript>", ...],
  "improvement_areas": ["<specific, actionable improvement>", ...],
  "filler_words": {{"total_count": <int>, "words": [{{"word": "<filler word>", "count": <int>}}, ...]}},
  "vocabulary_calibration": "<assessment with examples from transcript>",
  "tone_analysis": "<honest assessment of tone, attitude, and professionalism — cite specific moments>",
  "technical_depth_analysis": "<detailed analysis of the candidate's technical depth: evaluate specificity of technical answers, use of concrete examples vs vague generalities, accuracy of technical terminology, depth of system design or architectural reasoning, and whether they demonstrated hands-on expertise or only surface-level knowledge. Cite specific moments from the transcript.>",{posture_summary_schema}
  "decision": "offer" | "rejection",
  "decision_letter": "<full text of the mock offer or rejection letter, signed 'The MockMate Hiring Committee'>"
}}

--- Session metadata ---
{session_meta}

--- Interview transcript ---
(Format: SPEAKER: text — INTERVIEWER is the AI, CANDIDATE is the person being evaluated)
{transcript}

{posture_data_section}
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
        """Compute mean posture scores across all frames for the session.

        Posture data is stored as a single document per session with a
        ``frames`` array.  Falls back to the legacy per-frame document
        layout for sessions recorded before the migration.
        """
        scores: dict[str, list[float]] = {
            "posture_score": [],
            "eye_contact_score": [],
            "facial_confidence_score": [],
            "overall_presence_score": [],
        }
        observations: list[str] = []

        # ── New format: single document keyed by session_id ──────────
        doc = await self._db.collection(_COL_POSTURE).document(session_id).get()
        if doc.exists:
            data = doc.to_dict()
            for frame in data.get("frames", []):
                for key in scores:
                    if key in frame:
                        scores[key].append(frame[key])
                observations.extend(frame.get("observations", []))
        else:
            # ── Legacy fallback: one document per frame ───────────────
            query = (
                self._db.collection(_COL_POSTURE)
                .where("session_id", "==", session_id)
            )
            async for legacy_doc in query.stream():
                data = legacy_doc.to_dict()
                for key in scores:
                    if key in data:
                        scores[key].append(data[key])
                observations.extend(data.get("observations", []))

        avg = {k: (sum(v) / len(v) if v else 0) for k, v in scores.items()}
        avg["top_observations"] = list(set(observations))[:5]
        avg["frames_analysed"] = max(len(v) for v in scores.values()) if any(scores.values()) else 0
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

        has_posture = posture_avg.get("frames_analysed", 0) > 0

        if has_posture:
            posture_scoring_rule = (
                "- posture_presence: based solely on the posture data provided below.\n"
                "  Score posture, eye contact, facial confidence, and overall presence."
            )
            overall_posture_note = ""
            posture_dimension_schema = ',\n    "posture_presence": <0-100>'
            posture_summary_schema = '\n  "posture_summary": "<assessment based strictly on posture data>",'
            posture_data_section = (
                "--- Posture scores (aggregated) ---\n"
                + json.dumps(posture_avg, indent=2)
            )
        else:
            posture_scoring_rule = (
                "- posture_presence: DO NOT include this dimension — the candidate's\n"
                "  camera was not enabled so no posture data was captured.\n"
                "  Do NOT include posture_presence in dimension_scores.\n"
                "  Do NOT include posture_summary in the output."
            )
            overall_posture_note = (
                "Posture data is unavailable (camera was off). Compute overall_score\n"
                "  from the five remaining dimensions only — do NOT penalise or\n"
                "  reward for posture."
            )
            posture_dimension_schema = ""
            posture_summary_schema = ""
            posture_data_section = (
                "--- Posture scores ---\n"
                "(Camera was not enabled — no posture data captured. "
                "Exclude posture from all scoring.)"
            )

        prompt = FEEDBACK_PROMPT.format(
            job_role=job_role,
            session_meta=json.dumps(meta, indent=2),
            transcript=transcript_text,
            posture_scoring_rule=posture_scoring_rule,
            overall_posture_note=overall_posture_note,
            posture_dimension_schema=posture_dimension_schema,
            posture_summary_schema=posture_summary_schema,
            posture_data_section=posture_data_section,
        )

        logger.info(
            "Generating feedback report — session=%s  prompt_chars=%d  "
            "transcript_turns=%d  model=%s",
            session.get("session_id", "?"), len(prompt),
            len(transcript_turns), _MODEL,
        )

        _FEEDBACK_TIMEOUT = 180  # seconds — generous for long transcripts

        # Inner call wrapped with tenacity for 429 / 503 resilience.
        @retry(
            retry=retry_if_exception_type((ResourceExhausted, ServiceUnavailable)),
            wait=wait_random_exponential(multiplier=1, max=60),
            stop=stop_after_attempt(5),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        async def _generate_with_retry():
            return await self._model.generate_content_async(
                [Part.from_text(prompt)],
                generation_config=GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.3,
                    max_output_tokens=8192,
                ),
            )

        try:
            response = await asyncio.wait_for(
                _generate_with_retry(),
                timeout=_FEEDBACK_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error(
                "Feedback generation timed out after %ds — session=%s",
                _FEEDBACK_TIMEOUT, session.get("session_id", "?"),
            )
            raise RuntimeError(
                f"Feedback generation timed out after {_FEEDBACK_TIMEOUT}s. "
                "The transcript may be too long. Please try again."
            )
        except Exception as exc:
            logger.error(
                "Feedback generation failed — session=%s  %s: %s\n%s",
                session.get("session_id", "?"),
                type(exc).__name__, exc,
                traceback.format_exc(),
            )
            raise RuntimeError(
                f"Feedback generation failed: {type(exc).__name__}: {exc}"
            ) from exc

        raw_text = response.text
        logger.info(
            "Feedback response received — session=%s  response_chars=%d",
            session.get("session_id", "?"), len(raw_text) if raw_text else 0,
        )

        try:
            return json.loads(raw_text)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error(
                "Feedback JSON parse failed — session=%s  error=%s  "
                "raw_response_first_500=%s",
                session.get("session_id", "?"), exc,
                (raw_text or "")[:500],
            )
            raise RuntimeError(
                "Feedback model returned invalid JSON. Please try again."
            ) from exc

    async def _persist(self, session_id: str, report: dict[str, Any]) -> None:
        await self._db.collection(_COL_FEEDBACK).document(session_id).set(report)
        # Write top-level score back to the session doc so dashboard queries
        # can show scores without loading the full feedback document.
        try:
            await self._db.collection(_COL_SESSIONS).document(session_id).update({
                "overall_score":  report.get("overall_score"),
                "feedback_ready": True,
                "decision":       report.get("decision"),
            })
        except Exception:  # noqa: BLE001
            pass  # best-effort; don't fail the whole compile if this update fails

    async def get_feedback(self, session_id: str) -> dict[str, Any] | None:
        """Return a previously compiled feedback report, or None if not found."""
        doc = await self._db.collection(_COL_FEEDBACK).document(session_id).get()
        if not doc.exists:
            return None
        return doc.to_dict()
