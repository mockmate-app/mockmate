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
import traceback
from datetime import datetime, timezone
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

from agents.config import (
    PROJECT as _PROJECT,
    REGION as _REGION,
    FIRESTORE_DATABASE as _DATABASE,
    FIRESTORE_SESSION_COLLECTION as _COL_SESSIONS,
    FIRESTORE_RESUME_COLLECTION as _COL_RESUMES,
    FIRESTORE_TRANSCRIPT_COLLECTION as _COL_TRANSCRIPTS,
    FIRESTORE_FEEDBACK_COLLECTION as _COL_FEEDBACK,
    FIRESTORE_POSTURE_COLLECTION as _COL_POSTURE,
    GEMINI_MODEL as _MODEL,
    PGHOST as _PGHOST,
    PGPORT as _PGPORT,
    PGUSER as _PGUSER,
    PGPASSWORD as _PGPASSWORD,
    PGDATABASE as _PGDATABASE,
)

logger = logging.getLogger(__name__)

FEEDBACK_PROMPT = """
You are a rigorous, unbiased interview coach and senior hiring manager.
Your job is to produce HONEST, ACCURATE, SPECIFIC feedback grounded entirely
in what actually happened in the transcript below. Do NOT invent positives
or soften negatives — if the candidate was rude, disrespectful, incoherent,
or unprofessional, say so directly and reflect it in every relevant score.

Personalization context (MUST apply in this STRICT priority order):
- Evaluate using ALL FOUR inputs, but weight them in this exact order:
    1) Candidate responses in the transcript (PRIMARY — this is what they actually
       demonstrated; weigh this the heaviest in every score)
    2) Target job role ({job_role}) and its expected seniority bar
    3) Interview difficulty level (easy / medium / hard)
    4) Candidate resume (supporting context — use it to verify claims and detect
       over-claiming, but NEVER inflate scores just because the resume looks good)
- The transcript is king. A strong resume with weak interview answers = low scores.
  A modest resume with strong interview answers = high scores.
- Infer candidate YoE from resume (use experience durations + seniority cues).
- Infer expected YoE range for this target role (e.g. Junior SWE ≈ 0-2,
    Mid ≈ 2-5, Senior ≈ 5-8, Staff+ ≈ 8+, Director/VP ≈ 12+).
- Calibrate scores based on gap/alignment between candidate YoE/profile and role bar.
- Difficulty impacts expectations: "hard" demands deeper, more precise answers;
  "easy" tolerates more hand-waving but still requires substantive responses.

Calibration rules (strict):
- Lower YoE candidates:
    * prioritize clarity, fundamentals, breadth, learning mindset, and structured thinking.
    * tolerate moderate filler words and limited depth if reasoning is sound.
- Higher YoE / senior-role candidates:
    * require stronger depth, tradeoff analysis, precision, ownership impact, and architecture-level reasoning.
    * tolerate less vagueness, filler-heavy communication, or shallow examples.
- Resume alignment:
    * Compare transcript performance against what the resume implies.
    * Call out over-claiming or mismatch (e.g., resume suggests deep expertise but answers are superficial).
    * Reward consistency when transcript evidence supports resume claims.
- Role alignment:
    * Judge suitability for the specific interview role, not generic employability.

Decision-letter requirements (must include):
- inferred candidate YoE,
- inferred YoE bar for the target role,
- resume-to-role fit,
- transcript-backed strengths and gaps,
- posture impact if available.

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

Transcript quality control (CRITICAL):
- The transcript may contain occasional ASR artifacts/noise (e.g., stray one-word
    fragments, repeated nonsense like "love love love", accidental greetings,
    or clipped syllables).
- The ASR engine may also mistranscribe English speech as words from other
    languages (Hindi, Spanish, French, Japanese, etc.) or produce foreign-script
    characters. These are transcription errors, NOT evidence that the candidate
    was speaking another language. Ignore such fragments entirely — do NOT
    penalize the candidate for them or mention them in your feedback.
- Treat low-signal noise as non-evidence. Do NOT interpret these artifacts as
    explicit candidate claims, intent, or knowledge.
- Prioritize substantive candidate turns that include coherent reasoning,
    concrete examples, and role-relevant content.
- Never anchor scoring on a single noisy line; form judgments from sustained,
    relevant evidence across multiple meaningful candidate turns.

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
    "decision_reason": "<2-4 sentence plain-language reason for why this is an offer/rejection, grounded in transcript evidence and calibrated to job role + difficulty>",
  "decision_letter": "<full text of the mock offer or rejection letter, signed 'The MockMate Hiring Committee'>"
}}

--- Session metadata ---
{session_meta}

--- Parsed resume context ---
{resume_context}

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
        self._client = genai.Client(
            vertexai=True,
            project=_PROJECT,
            location=_REGION,
        )
        self._db = firestore.AsyncClient(project=_PROJECT, database=_DATABASE)
        self._pg_pool = None
        self._pg_ready = False

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def compile(self, session_id: str) -> dict[str, Any]:
        session = await self._fetch_session(session_id)
        transcript_turns = await self._fetch_transcript(session_id)
        posture_avg = await self._aggregate_posture(session_id)
        resume_data = await self._fetch_resume(session.get("user_id"))
        report = await self._generate_report(
            session,
            transcript_turns,
            posture_avg,
            resume_data,
        )

        # Post-process model output so decision policy remains consistent and
        # clearly explained across roles and difficulties.
        report = self._postprocess_report(report, session, posture_avg)
        report["session_id"] = session_id
        report["compiled_at"] = datetime.now(timezone.utc).isoformat()
        await self._persist(session_id, report, session)
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

    async def _fetch_resume(self, user_id: str | None) -> dict[str, Any] | None:
        """Fetch parsed resume for a user, or None if unavailable."""
        if not user_id:
            return None
        doc = await self._db.collection(_COL_RESUMES).document(user_id).get()
        if not doc.exists:
            logger.info("No resume found for user '%s'", user_id)
            return None
        return doc.to_dict()

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
                .where(filter=firestore.FieldFilter("session_id", "==", session_id))
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
        self,
        session: dict[str, Any],
        transcript_turns: list[dict[str, Any]],
        posture_avg: dict[str, Any],
        resume_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        meta = {
            "user_id": session.get("user_id"),
            "persona": session.get("persona"),
            "job_role": session.get("job_role", "Software Engineer"),
            "difficulty": session.get("difficulty", "medium"),
            "questions_count": len(session.get("questions", [])),
            "status": session.get("status"),
            "created_at": session.get("created_at"),
            "ended_at": session.get("ended_at"),
            "resume_available": bool(resume_data),
        }

        job_role = meta["job_role"]

        # Build transcript text from cleaned turns so accidental ASR noise does not
        # disproportionately affect feedback/scoring.
        transcript_text, transcript_meta = self._build_feedback_transcript_text(transcript_turns)

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
            resume_context=json.dumps(resume_data, indent=2) if resume_data else "(No parsed resume available for this user)",
            transcript=transcript_text,
            posture_scoring_rule=posture_scoring_rule,
            overall_posture_note=overall_posture_note,
            posture_dimension_schema=posture_dimension_schema,
            posture_summary_schema=posture_summary_schema,
            posture_data_section=posture_data_section,
        )

        logger.info(
            "Generating feedback report — session=%s  prompt_chars=%d  "
            "transcript_turns=%d  kept_turns=%d  dropped_low_signal=%d  model=%s",
            session.get("session_id", "?"), len(prompt),
            len(transcript_turns),
            transcript_meta.get("kept_turns", 0),
            transcript_meta.get("dropped_low_signal_candidate_turns", 0),
            _MODEL,
        )

        _FEEDBACK_TIMEOUT = 180  # seconds — generous for long transcripts

        # Inner call wrapped with tenacity for 429 / 503 resilience.
        @retry(
            retry=retry_if_exception_type((ResourceExhausted, ServiceUnavailable, genai_errors.APIError)),
            wait=wait_random_exponential(multiplier=1, max=60),
            stop=stop_after_attempt(5),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        async def _generate_with_retry():
            return await self._client.aio.models.generate_content(
                model=_MODEL,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
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

    @staticmethod
    def _is_low_signal_candidate_turn(text: str) -> bool:
        """Heuristic filter for accidental ASR gibberish/low-signal snippets."""
        t = str(text or "").strip()
        if not t:
            return True

        lowered = t.lower()
        words = [w for w in lowered.replace("\n", " ").split(" ") if w]
        if not words:
            return True

        # Non-Latin script detection: interviews are conducted in English, so
        # text that is predominantly non-Latin (Devanagari, CJK, Arabic, etc.)
        # is almost certainly an ASR mis-transcription artifact.
        alpha_chars = [c for c in t if c.isalpha()]
        if alpha_chars:
            latin_count = sum(1 for c in alpha_chars if c.isascii())
            if latin_count / len(alpha_chars) < 0.5:
                return True

        # Very short interjections are not reliable evidence for scoring.
        low_signal_singletons = {
            "hi", "hello", "hey", "hmm", "hm", "uh", "uhh", "um", "umm",
            "ok", "okay", "yes", "yeah", "yep", "no", "nope", "nah", "alo",
            "huh", "hmm.", "hmm,",
        }
        if len(words) <= 2 and all(w.strip(".,!?;:") in low_signal_singletons for w in words):
            return True

        # Repeated-token gibberish like "love love love" or "blah blah".
        unique = {w.strip(".,!?;:") for w in words if w.strip(".,!?;:")}
        if len(words) >= 3 and len(unique) == 1:
            return True
        if len(words) >= 4 and len(unique) <= 2 and max(words.count(w) for w in set(words)) >= 3:
            return True

        # Ultra-short one-word fragments are typically clipping noise.
        if len(words) == 1 and len(words[0].strip(".,!?;:")) <= 2:
            return True

        return False

    def _build_feedback_transcript_text(
        self,
        transcript_turns: list[dict[str, Any]],
    ) -> tuple[str, dict[str, int]]:
        if not transcript_turns:
            return (
                "(no transcript recorded — do not fabricate content; set all scores to 0)",
                {"kept_turns": 0, "kept_candidate_turns": 0, "dropped_low_signal_candidate_turns": 0},
            )

        lines: list[str] = []
        kept_candidate = 0
        dropped_low_signal = 0

        for entry in transcript_turns:
            speaker = str(entry.get("speaker", "")).strip().lower()
            text = str(entry.get("text", "")).strip()
            if not text:
                continue

            if speaker == "user":
                if self._is_low_signal_candidate_turn(text):
                    dropped_low_signal += 1
                    continue
                label = "CANDIDATE"
                kept_candidate += 1
            else:
                label = "INTERVIEWER"

            lines.append(f"{label}: {text}")

        if kept_candidate == 0:
            return (
                "(transcript had no reliable candidate content after noise filtering — set all scores to 0 and explain this)",
                {
                    "kept_turns": 0,
                    "kept_candidate_turns": 0,
                    "dropped_low_signal_candidate_turns": dropped_low_signal,
                },
            )

        return (
            "\n".join(lines),
            {
                "kept_turns": len(lines),
                "kept_candidate_turns": kept_candidate,
                "dropped_low_signal_candidate_turns": dropped_low_signal,
            },
        )

    def _postprocess_report(
        self,
        report: dict[str, Any],
        session: dict[str, Any],
        posture_avg: dict[str, Any],
    ) -> dict[str, Any]:
        report = dict(report or {})
        decision = str(report.get("decision") or "rejection").strip().lower()
        if decision not in {"offer", "rejection"}:
            decision = "rejection"

        overall = self._safe_score(report.get("overall_score"))
        role = str(session.get("job_role") or "Software Engineer")
        difficulty = str(session.get("difficulty") or "medium").strip().lower()

        threshold = self._decision_threshold(role, difficulty)
        calibrated_decision = "offer" if overall >= threshold else "rejection"

        # Always compute the reason ourselves to guarantee consistent
        # polarity: offers emphasise positives, rejections emphasise
        # improvement areas.
        reason = self._build_decision_reason(
            decision=calibrated_decision,
            overall=overall,
            threshold=threshold,
            role=role,
            difficulty=difficulty,
            strengths=report.get("strengths", []),
            improvements=report.get("improvement_areas", []),
        )

        report["overall_score"] = overall
        report["decision"] = calibrated_decision
        report["decision_reason"] = reason
        report["posture_data_used"] = posture_avg.get("frames_analysed", 0) > 0
        report["posture_frames_analysed"] = int(posture_avg.get("frames_analysed", 0) or 0)

        original_decision = decision
        letter = str(report.get("decision_letter") or "").strip()
        if calibrated_decision != original_decision or not letter:
            report["decision_letter"] = self._compose_decision_letter(
                decision=calibrated_decision,
                role=role,
                reason=reason,
                strengths=report.get("strengths", []),
                improvements=report.get("improvement_areas", []),
            )

        return report

    @staticmethod
    def _safe_score(value: Any) -> int:
        try:
            score = int(round(float(value)))
        except Exception:  # noqa: BLE001
            score = 0
        return max(0, min(100, score))

    @staticmethod
    def _role_level(job_role: str) -> int:
        """Infer seniority level (0-4) from any job role string.

        Returns:
            0 = intern / trainee
            1 = junior / entry-level
            2 = mid-level (default)
            3 = senior / lead / manager
            4 = staff+ / principal / executive
        """
        role = job_role.lower()

        # Level 0 — Intern / Trainee
        if any(k in role for k in ("intern", "trainee", "apprentice", "co-op", "coop")):
            return 0

        # Level 1 — Junior / Entry
        if any(k in role for k in (
            "junior", "entry", "new grad", "graduate", "fresher",
            "associate i", "analyst i",
            "sde1", "sde 1", "sde-1", "swe1", "swe 1",
            "l3", "level 3", "e3", "ic1", "ic2",
        )):
            return 1

        # Level 4 — Staff+ / Principal / Executive (check before level 3
        # because "staff" and "chief" should not match "lead"/"manager" first)
        if any(k in role for k in (
            "staff", "principal", "architect", "distinguished", "fellow",
            "chief", "cto", "cfo", "ceo", "coo", "cmo", "cio", "cpo",
            "evp", "svp",
            "sde4", "sde 4", "sde-4", "swe4", "swe 4",
            "l6", "l7", "l8", "level 6", "level 7", "level 8",
            "e6", "e7", "ic6", "ic7",
        )):
            return 4

        # Level 3 — Senior / Lead / Manager / Director
        if any(k in role for k in (
            "senior", "sr.", "sr ",
            "lead", "manager", "director", "vp", "vice president",
            "head of", "head,",
            "sde3", "sde 3", "sde-3", "swe3", "swe 3",
            "l5", "level 5", "e5", "ic5", "ic4",
        )):
            return 3

        # Level 2 — Mid-level (explicit markers)
        if any(k in role for k in (
            "ii", " 2", "mid", "intermediate",
            "sde2", "sde 2", "sde-2", "swe2", "swe 2",
            "l4", "level 4", "e4", "ic3",
        )):
            return 2

        # Default: assume mid-level for unrecognized roles
        return 2

    def _decision_threshold(self, job_role: str, difficulty: str) -> int:
        """Compute the pass/fail threshold dynamically from role seniority and difficulty.

        The threshold is stricter for senior roles (they're expected to perform
        better) and slightly more lenient for harder difficulty (tougher questions).
        """
        base = 75

        role_offsets = {
            0: -10,  # intern / trainee
            1: -7,   # junior / entry
            2: -3,   # mid-level          → medium lands at 72
            3: 0,    # senior / lead       → medium lands at 75
            4: 3,    # staff+ / executive  → medium lands at 78
        }
        difficulty_offsets = {
            "easy":   -5,   # easier questions → slightly lower bar
            "medium":  0,   # baseline
            "hard":   -3,   # harder questions → small leniency
        }

        level = self._role_level(job_role)
        threshold = base + role_offsets.get(level, 0) + difficulty_offsets.get(difficulty, 0)
        return max(58, min(82, threshold))

    def _build_decision_reason(
        self,
        decision: str,
        overall: int,
        threshold: int,
        role: str,
        difficulty: str,
        strengths: Any,
        improvements: Any,
    ) -> str:
        strengths_list = [str(s).strip() for s in (strengths or []) if str(s).strip()]
        improvements_list = [str(s).strip() for s in (improvements or []) if str(s).strip()]

        s1 = strengths_list[0] if len(strengths_list) > 0 else "some relevant fundamentals"
        s2 = strengths_list[1] if len(strengths_list) > 1 else None
        g1 = improvements_list[0] if len(improvements_list) > 0 else "more depth and specificity in responses"
        g2 = improvements_list[1] if len(improvements_list) > 1 else None

        if decision == "offer":
            para1 = (
                f"This was a strong interview. For a {role} position on {difficulty} difficulty, "
                f"we were looking for a score of at least {threshold} — and you came in at {overall}. "
                f"That tells us you're well-calibrated for this level."
            )
            para2 = f"What stood out most was {s1.lower()}."
            if s2:
                para2 += f" We also noticed {s2.lower()}, which reinforced the overall impression."
            para3 = (
                f"That said, there's always room to grow. If we had to pick one thing to sharpen "
                f"for your next round, it would be {g1.lower()}."
            )
            if g2:
                para3 += f" {g2} would also take you to the next level."
            return f"{para1}\n\n{para2}\n\n{para3}"

        para1 = (
            f"This was a solid effort, but for a {role} position on {difficulty} difficulty, "
            f"we needed to see a score of at least {threshold} to move forward — and "
            f"this session came in at {overall}. The gap isn't insurmountable, but it's there."
        )
        para2 = (
            f"The biggest area holding things back was {g1.lower()}. "
            f"In a real interview loop, this is the kind of thing that separates a 'maybe' from a 'yes'."
        )
        if g2:
            para2 += f" Beyond that, {g2.lower()} would also make a noticeable difference."
        para3 = (
            f"On the positive side, {s1.lower()} — that's a real strength to build on."
        )
        if s2:
            para3 += f" {s2} was also a bright spot."
        para3 += " The foundation is there. A few more focused practice sessions and the outcome could look very different."
        return f"{para1}\n\n{para2}\n\n{para3}"

    def _compose_decision_letter(
        self,
        decision: str,
        role: str,
        reason: str,
        strengths: Any,
        improvements: Any,
    ) -> str:
        strengths_list = [str(s).strip() for s in (strengths or []) if str(s).strip()]
        improvements_list = [str(s).strip() for s in (improvements or []) if str(s).strip()]

        if decision == "offer":
            letter = (
                f"Dear Candidate,\n\n"
                f"Thank you for taking the time to interview for the {role} position. "
                f"We're pleased to let you know that based on this session, we'd like to extend an offer.\n\n"
                f"{reason}\n\n"
            )
            if strengths_list:
                highlights = ", ".join(s.lower().rstrip(". ") for s in strengths_list[:3])
                letter += (
                    f"A few highlights from the conversation: {highlights}. "
                    f"These are the kinds of signals that make us confident in this decision.\n\n"
                )
            if improvements_list:
                areas = " and ".join(s.lower().rstrip(". ") for s in improvements_list[:2])
                letter += (
                    f"As you settle into the role, we'd encourage you to keep working on {areas}. "
                    f"Even strong candidates have growth edges — leaning into yours will set you apart.\n\n"
                )
            letter += "We're excited about what's ahead.\n\nSincerely,\nThe MockMate Hiring Committee"
            return letter

        letter = (
            f"Dear Candidate,\n\n"
            f"Thank you for interviewing for the {role} position. We appreciate the time and "
            f"effort you put into this session. After careful review, we've decided not to move "
            f"forward with an offer at this time.\n\n"
            f"{reason}\n\n"
        )
        if improvements_list:
            areas = " and ".join(s.lower().rstrip(". ") for s in improvements_list[:2])
            letter += (
                f"If you were to come back for another round, the single biggest unlock would be {areas}. "
                f"Practicing with that specific focus would meaningfully change the outcome.\n\n"
            )
        if strengths_list:
            highlights = " and ".join(s.lower().rstrip(". ") for s in strengths_list[:2])
            letter += (
                f"We don't want to leave you without the good news: {highlights} came through clearly "
                f"and would serve you well in any interview setting. Don't lose that.\n\n"
            )
        letter += (
            "This isn't the end of the road — it's a data point. Use the feedback, "
            "practice deliberately, and come back stronger.\n\n"
            "Sincerely,\nThe MockMate Hiring Committee"
        )
        return letter

    async def _persist(
        self,
        session_id: str,
        report: dict[str, Any],
        session: dict[str, Any],
    ) -> None:
        await self._db.collection(_COL_FEEDBACK).document(session_id).set(report)
        # Write top-level score back to the session doc so dashboard queries
        # can show scores without loading the full feedback document.
        try:
            await self._db.collection(_COL_SESSIONS).document(session_id).update({
                "overall_score":    report.get("overall_score"),
                "dimension_scores": report.get("dimension_scores"),
                "feedback_ready":   True,
                "decision":         report.get("decision"),
                "decision_reason":  report.get("decision_reason"),
            })
        except Exception:  # noqa: BLE001
            pass  # best-effort; don't fail the whole compile if this update fails

        # Best-effort Postgres analytics cache + materialized views.
        try:
            await self._upsert_postgres_analytics(session, report)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Postgres analytics update skipped: %s", exc)

    async def get_feedback(self, session_id: str) -> dict[str, Any] | None:
        """Return a previously compiled feedback report, or None if not found."""
        doc = await self._db.collection(_COL_FEEDBACK).document(session_id).get()
        if not doc.exists:
            return None
        return doc.to_dict()

    async def _get_pg_pool(self):
        """Lazily create a Postgres pool when PG env vars are configured."""
        if not (_PGHOST and _PGUSER and _PGPASSWORD and _PGDATABASE):
            return None
        if self._pg_pool is not None:
            return self._pg_pool

        import asyncpg

        self._pg_pool = await asyncpg.create_pool(
            host=_PGHOST,
            port=_PGPORT,
            user=_PGUSER,
            password=_PGPASSWORD,
            database=_PGDATABASE,
            min_size=1,
            max_size=5,
        )
        return self._pg_pool

    async def _ensure_pg_analytics_objects(self, conn) -> None:
        if self._pg_ready:
            return

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analytics_feedback_scores (
              session_id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL,
              overall_score DOUBLE PRECISION,
              communication DOUBLE PRECISION,
              confidence DOUBLE PRECISION,
              structure DOUBLE PRECISION,
              technical_depth DOUBLE PRECISION,
              domain_vocabulary DOUBLE PRECISION,
              posture_presence DOUBLE PRECISION
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS analytics_feedback_scores_user_created_idx "
            "ON analytics_feedback_scores (user_id, created_at DESC)"
        )

        await conn.execute(
            """
            CREATE MATERIALIZED VIEW IF NOT EXISTS analytics_user_dimension_averages AS
            SELECT
              user_id,
              ROUND(AVG(communication)::numeric, 1) AS communication,
              ROUND(AVG(confidence)::numeric, 1) AS confidence,
              ROUND(AVG(structure)::numeric, 1) AS structure,
              ROUND(AVG(technical_depth)::numeric, 1) AS technical_depth,
              ROUND(AVG(domain_vocabulary)::numeric, 1) AS domain_vocabulary,
              ROUND(AVG(posture_presence)::numeric, 1) AS posture_presence,
              COUNT(*)::INT AS sessions_count
            FROM analytics_feedback_scores
            GROUP BY user_id
            """
        )
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS analytics_user_dimension_averages_user_uidx "
            "ON analytics_user_dimension_averages (user_id)"
        )

        await conn.execute(
            """
            CREATE MATERIALIZED VIEW IF NOT EXISTS analytics_global_dimension_averages AS
            SELECT
              ROUND(AVG(communication)::numeric, 1) AS communication,
              ROUND(AVG(confidence)::numeric, 1) AS confidence,
              ROUND(AVG(structure)::numeric, 1) AS structure,
              ROUND(AVG(technical_depth)::numeric, 1) AS technical_depth,
              ROUND(AVG(domain_vocabulary)::numeric, 1) AS domain_vocabulary,
              ROUND(AVG(posture_presence)::numeric, 1) AS posture_presence,
              COUNT(*)::INT AS reports_count
            FROM analytics_feedback_scores
            """
        )
        self._pg_ready = True

    async def _upsert_postgres_analytics(
        self,
        session: dict[str, Any],
        report: dict[str, Any],
    ) -> None:
        pool = await self._get_pg_pool()
        if pool is None:
            return

        dim = report.get("dimension_scores", {})
        created_at_raw = session.get("created_at") or session.get("ended_at")
        try:
            created_at = datetime.fromisoformat(str(created_at_raw)) if created_at_raw else datetime.now(timezone.utc)
        except Exception:  # noqa: BLE001
            created_at = datetime.now(timezone.utc)

        async with pool.acquire() as conn:
            await self._ensure_pg_analytics_objects(conn)
            await conn.execute(
                """
                INSERT INTO analytics_feedback_scores (
                  session_id, user_id, created_at, overall_score,
                  communication, confidence, structure,
                  technical_depth, domain_vocabulary, posture_presence
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                ON CONFLICT (session_id) DO UPDATE SET
                  user_id = EXCLUDED.user_id,
                  overall_score = EXCLUDED.overall_score,
                  communication = EXCLUDED.communication,
                  confidence = EXCLUDED.confidence,
                  structure = EXCLUDED.structure,
                  technical_depth = EXCLUDED.technical_depth,
                  domain_vocabulary = EXCLUDED.domain_vocabulary,
                  posture_presence = EXCLUDED.posture_presence
                """,
                str(report.get("session_id") or session.get("session_id") or ""),
                str(session.get("user_id") or ""),
                created_at,
                report.get("overall_score"),
                dim.get("communication"),
                dim.get("confidence"),
                dim.get("structure"),
                dim.get("technical_depth"),
                dim.get("domain_vocabulary"),
                dim.get("posture_presence"),
            )

            await conn.execute("REFRESH MATERIALIZED VIEW analytics_user_dimension_averages")
            await conn.execute("REFRESH MATERIALIZED VIEW analytics_global_dimension_averages")
