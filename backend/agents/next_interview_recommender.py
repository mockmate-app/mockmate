"""
NextInterviewRecommenderAgent
-----------------------------
Builds a "Your Next Interview" recommendation from the user's most recent
feedback-ready sessions (last 3-5), then asks Gemini Flash to produce a short,
actionable recommendation strip for the dashboard.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable
from google.cloud import firestore
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from agents.config import (
    PROJECT as _PROJECT,
    REGION as _REGION,
    FIRESTORE_DATABASE as _DATABASE,
    FIRESTORE_SESSION_COLLECTION as _COL_SESSIONS,
    FIRESTORE_FEEDBACK_COLLECTION as _COL_FEEDBACK,
    GEMINI_MODEL as _MODEL,
)

logger = logging.getLogger(__name__)

_DIM_KEYS = [
    "communication",
    "confidence",
    "structure",
    "technical_depth",
    "domain_vocabulary",
    "posture_presence",
]

_PERSONA_BY_FOCUS = {
    "technical_depth": "cto",
    "domain_vocabulary": "tech_lead",
    "structure": "management_consultant",
    "communication": "hr_manager",
    "confidence": "startup_founder",
    "posture_presence": "recruiter",
}

_TECH_PERSONA_BY_FOCUS = {
    "technical_depth": "tech_lead",
    "domain_vocabulary": "tech_lead",
    "structure": "system_designer",
    "communication": "tech_lead",
    "confidence": "tech_lead",
    "posture_presence": "tech_lead",
}

_VALID_PERSONAS = {
    "neutral",
    "startup_founder",
    "investment_banker",
    "tech_lead",
    "hr_manager",
    "product_manager",
    "vp_engineering",
    "management_consultant",
    "cto",
    "recruiter",
    "algorithm_guru",
    "system_designer",
    "prompt_wizard",
    "ai_engineer",
}

_TECHNICAL_PERSONAS = {
    "tech_lead",
    "cto",
    "algorithm_guru",
    "system_designer",
    "prompt_wizard",
    "ai_engineer",
    "vp_engineering",
    "startup_founder",
    "neutral",
}

_PROMPT = """\
You are MockMate's recommendation engine.
Given the user's recent mock interview performance summary, return a concise and
practical "next interview" recommendation.

Rules:
- Return ONLY valid JSON. No markdown, no extra text.
- Be specific and data-grounded.
- Mention trend direction where relevant (e.g., dropped 8 points across 3 sessions).
- Keep each field short and UI-ready.
- Persona-role fit is mandatory:
    - For technical software roles (e.g. Software Engineer, SDE, Backend, Frontend,
        Full Stack, DevOps, Data Engineer, ML/AI Engineer), choose a technical
        interviewer persona such as tech_lead/cto/system_designer/algorithm_guru/
        prompt_wizard/ai_engineer.
    - Avoid non-technical personas like management_consultant or investment_banker
        for technical software roles.

Input data:
{input_json}

Return EXACTLY this schema:
{{
  "headline": "<short title>",
  "insight": "<one sentence insight about trend>",
  "practice_focus": "<what to practice next>",
  "recommended_persona": "<persona key>",
  "recommended_job_role": "<job role string>",
  "cta": "<short call-to-action sentence>"
}}
"""


class NextInterviewRecommenderAgent:
    """Generates recommendation strip content from recent sessions."""

    def __init__(self) -> None:
        self._client = genai.Client(
            vertexai=True,
            project=_PROJECT,
            location=_REGION,
        )
        self._db = firestore.AsyncClient(project=_PROJECT, database=_DATABASE)

    async def recommend(self, user_id: str, lookback: int = 5) -> dict[str, Any] | None:
        """Return recommendation payload or None when data is insufficient."""
        sessions = await self._fetch_recent_feedback_ready_sessions(user_id, lookback=max(3, lookback))
        if len(sessions) < 3:
            return None

        scored_sessions = []
        for session in sessions:
            sid = str(session.get("session_id") or "")
            if not sid:
                continue
            feedback_doc = await self._db.collection(_COL_FEEDBACK).document(sid).get()
            if not feedback_doc.exists:
                continue
            feedback = feedback_doc.to_dict()
            scored_sessions.append({
                "session_id": sid,
                "created_at": session.get("created_at"),
                "job_role": session.get("job_role"),
                "persona": session.get("persona"),
                "overall_score": session.get("overall_score"),
                "dimension_scores": feedback.get("dimension_scores", {}),
            })

        if len(scored_sessions) < 3:
            return None

        summary = self._build_summary(scored_sessions)

        try:
            llm_payload = await self._call_gemini(summary)
            return {
                "user_id": user_id,
                "sessions_analyzed": len(scored_sessions),
                **llm_payload,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Next recommendation LLM failed; using fallback: %s", exc)
            fallback = self._fallback(summary)
            return {
                "user_id": user_id,
                "sessions_analyzed": len(scored_sessions),
                **fallback,
            }

    async def _fetch_recent_feedback_ready_sessions(
        self,
        user_id: str,
        lookback: int,
    ) -> list[dict[str, Any]]:
        query = (
            self._db.collection(_COL_SESSIONS)
            .where(filter=firestore.FieldFilter("user_id", "==", user_id))
        )

        rows: list[dict[str, Any]] = []
        async for doc in query.stream():
            data = doc.to_dict()
            if data.get("feedback_ready") and data.get("overall_score") is not None:
                rows.append({
                    "session_id": data.get("session_id"),
                    "created_at": data.get("last_retried_at") or data.get("created_at"),
                    "job_role": data.get("job_role"),
                    "persona": data.get("persona"),
                    "overall_score": data.get("overall_score"),
                })

        rows.sort(key=lambda s: s.get("created_at") or "", reverse=True)
        return rows[:lookback]

    @staticmethod
    def _is_technical_role(job_role: str | None) -> bool:
        role = (job_role or "").strip().lower()
        if not role:
            return False
        keywords = (
            "software engineer",
            "sde",
            "developer",
            "backend",
            "front",
            "full stack",
            "devops",
            "platform engineer",
            "site reliability",
            "sre",
            "data engineer",
            "machine learning",
            "ml engineer",
            "ai engineer",
            "system design",
            "architect",
            "qa engineer",
            "security engineer",
        )
        return any(k in role for k in keywords)

    def _allowed_personas_for_role(self, job_role: str | None) -> set[str]:
        if self._is_technical_role(job_role):
            return _TECHNICAL_PERSONAS
        return _VALID_PERSONAS

    def _rule_persona_for(self, weakest_dimension: str | None, job_role: str | None) -> str:
        if self._is_technical_role(job_role):
            return _TECH_PERSONA_BY_FOCUS.get(weakest_dimension or "", "tech_lead")
        return _PERSONA_BY_FOCUS.get(weakest_dimension or "", "neutral")

    def _normalize_persona(self, persona: str | None, job_role: str | None, fallback: str) -> str:
        candidate = (persona or "").strip()
        if candidate not in _VALID_PERSONAS:
            return fallback
        if candidate not in self._allowed_personas_for_role(job_role):
            return fallback
        return candidate

    def _build_summary(self, sessions: list[dict[str, Any]]) -> dict[str, Any]:
        ordered = list(reversed(sessions))
        overall_series = [s.get("overall_score") for s in ordered if isinstance(s.get("overall_score"), (int, float))]

        trends: dict[str, Any] = {}
        for key in _DIM_KEYS:
            series: list[float] = []
            for s in ordered:
                val = (s.get("dimension_scores") or {}).get(key)
                if isinstance(val, (int, float)):
                    series.append(float(val))
            if len(series) >= 2:
                trends[key] = {
                    "first": round(series[0], 1),
                    "last": round(series[-1], 1),
                    "delta": round(series[-1] - series[0], 1),
                    "avg": round(sum(series) / len(series), 1),
                }

        weakest_key = None
        weakest_avg = None
        for key, info in trends.items():
            avg = info.get("avg")
            if not isinstance(avg, (int, float)):
                continue
            if weakest_avg is None or avg < weakest_avg:
                weakest_avg = avg
                weakest_key = key

            suggested_job_role = ordered[-1].get("job_role") if ordered else "Software Engineer"
            suggested_persona = self._rule_persona_for(weakest_key, suggested_job_role)

        return {
            "recent_sessions": [
                {
                    "session_id": s.get("session_id"),
                    "job_role": s.get("job_role"),
                    "persona": s.get("persona"),
                    "overall_score": s.get("overall_score"),
                }
                for s in ordered
            ],
            "overall_score_trend": {
                "first": overall_series[0] if overall_series else None,
                "last": overall_series[-1] if overall_series else None,
                "delta": round(overall_series[-1] - overall_series[0], 1) if len(overall_series) >= 2 else None,
                "avg": round(sum(overall_series) / len(overall_series), 1) if overall_series else None,
            },
            "dimension_trends": trends,
            "weakest_dimension": weakest_key,
            "suggested_persona_from_rule": suggested_persona,
            "suggested_job_role_from_rule": suggested_job_role,
        }

    @retry(
        retry=retry_if_exception_type((ResourceExhausted, ServiceUnavailable, genai_errors.APIError)),
        wait=wait_random_exponential(multiplier=1, max=30),
        stop=stop_after_attempt(4),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _call_gemini(self, summary: dict[str, Any]) -> dict[str, Any]:
        prompt = _PROMPT.format(input_json=json.dumps(summary, indent=2))
        resp = await self._client.aio.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.4,
                max_output_tokens=800,
            ),
        )
        payload = json.loads((resp.text or "{}").strip())
        recommended_job_role = str(payload.get("recommended_job_role") or summary.get("suggested_job_role_from_rule") or "Software Engineer")
        fallback_persona = str(summary.get("suggested_persona_from_rule") or "neutral")
        normalized_persona = self._normalize_persona(
            str(payload.get("recommended_persona") or ""),
            recommended_job_role,
            fallback_persona,
        )

        return {
            "headline": str(payload.get("headline") or "Your Next Interview"),
            "insight": str(payload.get("insight") or "Let's keep improving your consistency."),
            "practice_focus": str(payload.get("practice_focus") or "Practice role-specific weak areas."),
            "recommended_persona": normalized_persona,
            "recommended_job_role": recommended_job_role,
            "cta": str(payload.get("cta") or "Run a focused practice session now."),
        }

    def _fallback(self, summary: dict[str, Any]) -> dict[str, Any]:
        weak = summary.get("weakest_dimension") or "technical_depth"
        dim = weak.replace("_", " ")
        trend = (summary.get("dimension_trends") or {}).get(weak, {})
        delta = trend.get("delta", 0)
        magnitude = abs(float(delta)) if isinstance(delta, (int, float)) else 0.0
        direction = "dropped" if isinstance(delta, (int, float)) and delta < 0 else "is trending flat"

        persona = summary.get("suggested_persona_from_rule") or "neutral"
        job_role = summary.get("suggested_job_role_from_rule") or "Software Engineer"

        return {
            "headline": "Your Next Interview",
            "insight": f"Your {dim} {direction} by {round(magnitude, 1)} points in recent sessions.",
            "practice_focus": f"Focus on improving {dim} with concrete, role-specific examples.",
            "recommended_persona": persona,
            "recommended_job_role": job_role,
            "cta": f"Try a {persona.replace('_', ' ')} interview for {job_role} next.",
        }
