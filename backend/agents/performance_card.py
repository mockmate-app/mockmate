"""
PerformanceCardAgent
--------------------
After feedback is compiled, generates a visually striking AI performance card
for the session using **Imagen 3.0 Fast** (Vertex AI).  The card background is
a unique artistic image themed to the persona + job-role + score, and the
metadata (score, role, persona, motivational line) is supplied as JSON for the
frontend to overlay.

GCS layout:
  gs://{GCS_BUCKET}/performance-cards/{session_id}.jpg

One Imagen 3 API call per session.  Results are cached in GCS + Firestore so
subsequent requests are free.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable
from google.cloud import firestore, storage
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
    GCS_BUCKET as _BUCKET,
    FIRESTORE_DATABASE as _DATABASE,
    FIRESTORE_SESSION_COLLECTION as _COL_SESSIONS,
    FIRESTORE_FEEDBACK_COLLECTION as _COL_FEEDBACK,
    GEMINI_MODEL as _GEMINI_MODEL,
    IMAGEN_MODEL as _IMAGEN_MODEL,
    require_env,
)

logger = logging.getLogger(__name__)

if not _BUCKET:
    _BUCKET = require_env("GCS_BUCKET")

_CARD_PREFIX = "performance-cards"
_COL_PERFORMANCE_CARDS = "performance_cards"

# ---------------------------------------------------------------------------
# Persona-themed visual cues for the background image
# ---------------------------------------------------------------------------

_PERSONA_VISUAL: dict[str, str] = {
    "neutral":               "elegant minimalist corporate office with clean lines",
    "startup_founder":       "vibrant neon-lit startup workspace with creative energy",
    "investment_banker":     "luxurious Wall Street trading floor with golden accents",
    "tech_lead":             "futuristic server room with glowing blue circuits",
    "hr_manager":            "warm inviting modern office space with plants",
    "product_manager":       "sleek product launch stage with spotlight beams",
    "vp_engineering":        "panoramic tech campus view from a glass corner office",
    "management_consultant": "polished boardroom with floor-to-ceiling windows overlooking a skyline",
    "cto":                   "cutting-edge technology lab with holographic displays",
    "recruiter":             "modern networking event space with elegant lighting",
    "algorithm_guru":        "abstract mathematical landscape with flowing geometric patterns",
    "system_designer":       "vast architectural blueprint environment with interconnected systems",
    "prompt_wizard":         "mystical AI neural network visualization with glowing nodes",
    "ai_engineer":           "mystical AI neural network visualization with glowing nodes",
}

# ---------------------------------------------------------------------------
# Score → mood mapping for the image
# ---------------------------------------------------------------------------

def _score_mood(score: int) -> dict[str, str]:
    if score >= 85:
        return {
            "mood": "triumphant, golden sunlight, celebration energy, warm tones",
            "scene_extra": "radiant sunrise over a mountain summit, gold and amber light flooding the scene, a sense of reaching the peak",
            "palette": "warm gold, amber, soft white, champagne highlights",
        }
    if score >= 70:
        return {
            "mood": "confident, bright daylight, optimistic, cool blue and green tones",
            "scene_extra": "clear open sky at golden hour, a path stretching forward into bright light, sense of momentum",
            "palette": "teal, sky blue, soft green, silver accents",
        }
    if score >= 50:
        return {
            "mood": "determined, dawn breaking, hopeful amber tones",
            "scene_extra": "dawn breaking over a horizon, first light cutting through clouds, a new day beginning",
            "palette": "warm amber, deep orange, muted navy, hints of gold",
        }
    return {
        "mood": "dramatic, stormy but clearing, intense purple and deep blue tones",
        "scene_extra": "dramatic storm clouds parting to reveal distant light, rain clearing, resilience",
        "palette": "deep purple, midnight blue, silver edges, faint warm glow on the horizon",
    }


# ---------------------------------------------------------------------------
# Motivational line prompt (Gemini)
# ---------------------------------------------------------------------------

_MOTIVATIONAL_PROMPT = """\
You are a world-class career coach.  Based on the following interview results,
write ONE short, powerful motivational sentence (max 15 words) for the candidate.
The tone should match the score:
- 85+: celebratory and inspiring
- 70-84: encouraging and affirming
- 50-69: motivating with growth mindset
- <50: compassionate, forward-looking

Score: {score}/100
Decision: {decision}
Job role: {job_role}
Persona: {persona}
Strengths: {strengths}

Return ONLY the motivational sentence, nothing else. No quotes, no attribution.
"""

# ---------------------------------------------------------------------------
# Imagen prompt for the card background
# ---------------------------------------------------------------------------

def _build_card_prompt(
    persona: str,
    job_role: str,
    score: int,
    decision: str,
    motivational_line: str = "",
) -> str:
    visual = _PERSONA_VISUAL.get(persona, "professional modern workspace")
    score_info = _score_mood(score)
    mood = score_info["mood"]
    scene_extra = score_info["scene_extra"]
    palette = score_info["palette"]
    trophy = "with a subtle golden trophy silhouette" if score >= 85 else ""

    # Distill the motivational line into visual imagery keywords
    quote_hint = ""
    if motivational_line:
        quote_hint = (
            f"The artwork should visually evoke the feeling of: \"{motivational_line}\". "
            f"Translate this sentiment into abstract visual metaphors — do NOT render any text. "
        )

    return (
        f"Abstract, cinematic wide-format background artwork for a premium achievement card. "
        f"Scene: {visual}, blended with {scene_extra}. "
        f"Mood: {mood}. Color palette: {palette}. {trophy} "
        f"{quote_hint}"
        f"Style: ultra-wide 16:9 aspect ratio, soft bokeh, rich depth of field, "
        f"subtle lens flare, premium gradient overlay transitioning from deep navy/charcoal "
        f"on the left third to the scene on the right. The left side MUST be dark and clean "
        f"enough to serve as a text overlay area. "
        f"NO text, NO letters, NO numbers, NO watermarks, NO people, NO faces. "
        f"Photorealistic, high quality, editorial magazine aesthetic."
    )


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class PerformanceCardAgent:
    """Generate and cache AI performance card backgrounds with metadata."""

    def __init__(self) -> None:
        self._client = genai.Client(
            vertexai=True,
            project=_PROJECT,
            location=_REGION,
        )
        self._storage_client = storage.Client(project=_PROJECT)
        self._bucket = self._storage_client.bucket(_BUCKET)
        self._db = firestore.AsyncClient(project=_PROJECT, database=_DATABASE)
        logger.info("PerformanceCardAgent initialised (bucket=%s)", _BUCKET)

    # ------------------------------------------------------------------
    # GCS helpers
    # ------------------------------------------------------------------

    def _blob_name(self, session_id: str) -> str:
        return f"{_CARD_PREFIX}/{session_id}.jpg"

    def _exists_in_gcs(self, session_id: str) -> bool:
        return self._bucket.blob(self._blob_name(session_id)).exists()

    def _download_from_gcs(self, session_id: str) -> bytes:
        return self._bucket.blob(self._blob_name(session_id)).download_as_bytes()

    def _upload_to_gcs(self, session_id: str, image_bytes: bytes) -> str:
        blob = self._bucket.blob(self._blob_name(session_id))
        blob.upload_from_string(image_bytes, content_type="image/jpeg")
        logger.info("Performance card uploaded — blob=%s", blob.name)
        return blob.name

    # ------------------------------------------------------------------
    # Gemini: motivational line
    # ------------------------------------------------------------------

    async def _generate_motivational_line(
        self,
        score: int,
        decision: str,
        job_role: str,
        persona: str,
        strengths: list[str],
    ) -> str:
        prompt = _MOTIVATIONAL_PROMPT.format(
            score=score,
            decision=decision,
            job_role=job_role,
            persona=persona,
            strengths=", ".join(strengths[:3]) if strengths else "N/A",
        )

        @retry(
            retry=retry_if_exception_type((ResourceExhausted, ServiceUnavailable, genai_errors.APIError)),
            wait=wait_random_exponential(multiplier=1, max=30),
            stop=stop_after_attempt(3),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        async def _call():
            return await self._client.aio.models.generate_content(
                model=_GEMINI_MODEL,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=0.9,
                    max_output_tokens=64,
                ),
            )

        try:
            resp = await _call()
            line = resp.text.strip().strip('"').strip("'")
            # Ensure it's reasonably short
            if len(line) > 120:
                line = line[:117] + "..."
            return line
        except Exception as exc:
            logger.warning("Motivational line generation failed: %s", exc)
            if score >= 70:
                return "Your dedication is paying off — keep pushing forward!"
            return "Every interview is a step closer to your dream role."

    # ------------------------------------------------------------------
    # Imagen: card background
    # ------------------------------------------------------------------

    def _sync_generate_background(
        self,
        session_id: str,
        persona: str,
        job_role: str,
        score: int,
        decision: str,
        motivational_line: str = "",
    ) -> Optional[bytes]:
        """Synchronous background generation (run in executor)."""
        try:
            if self._exists_in_gcs(session_id):
                logger.debug("Performance card cache hit — session=%s", session_id)
                return self._download_from_gcs(session_id)

            prompt = _build_card_prompt(persona, job_role, score, decision, motivational_line)

            @retry(
                retry=retry_if_exception_type((ResourceExhausted, ServiceUnavailable, genai_errors.APIError)),
                wait=wait_random_exponential(multiplier=1, max=60),
                stop=stop_after_attempt(5),
                before_sleep=before_sleep_log(logger, logging.WARNING),
                reraise=True,
            )
            def _gen():
                return self._client.models.generate_images(
                    model=_IMAGEN_MODEL,
                    prompt=prompt,
                    config=genai_types.GenerateImagesConfig(
                        number_of_images=1,
                        aspect_ratio="16:9",
                        output_mime_type="image/jpeg",
                    ),
                )

            response = _gen()
            generated = getattr(response, "generated_images", None) or []
            if not generated:
                logger.warning("Imagen returned no images for performance card (session=%s)", session_id)
                return None

            image_obj = getattr(generated[0], "image", None)
            image_bytes: bytes | None = getattr(image_obj, "image_bytes", None)
            if not image_bytes:
                logger.warning("Imagen response missing image bytes (session=%s)", session_id)
                return None
            self._upload_to_gcs(session_id, image_bytes)
            return image_bytes

        except Exception:
            logger.exception("Performance card generation failed — session=%s", session_id)
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(self, session_id: str) -> dict[str, Any] | None:
        """
        Generate a performance card for a completed session.

        Returns a dict with card metadata + signals that the background image
        is available at the /performance-card/{session_id}/image endpoint.
        Returns None if feedback hasn't been compiled yet.
        """
        # Check if card metadata already exists in Firestore.
        # If metadata exists but the background is missing, force regeneration.
        existing = await self.get_card_metadata(session_id)
        existing_line = None
        if existing:
            existing_line = str(existing.get("motivational_line") or "").strip() or None
            has_background = bool(existing.get("has_background"))
            if has_background:
                loop = asyncio.get_event_loop()
                image_exists = await loop.run_in_executor(
                    None, self._exists_in_gcs, session_id
                )
                if image_exists:
                    return existing
                logger.warning(
                    "Performance card metadata exists but image is missing in GCS; regenerating (session=%s)",
                    session_id,
                )
            else:
                logger.info(
                    "Performance card metadata exists without background; retrying generation (session=%s)",
                    session_id,
                )

        # Fetch feedback
        feedback_doc = await self._db.collection(_COL_FEEDBACK).document(session_id).get()
        if not feedback_doc.exists:
            logger.info("No feedback yet for session %s — skipping card generation", session_id)
            return None
        feedback = feedback_doc.to_dict()

        # Fetch session meta
        session_doc = await self._db.collection(_COL_SESSIONS).document(session_id).get()
        if not session_doc.exists:
            return None
        session = session_doc.to_dict()

        score = feedback.get("overall_score", 0)
        decision = feedback.get("decision", "rejection")
        job_role = session.get("job_role", "Software Engineer")
        persona = session.get("persona", "neutral")
        interviewer_name = session.get("interviewer_name", "Interviewer")
        strengths = feedback.get("strengths", [])

        # Generate motivational line (Gemini — fast), unless we already have one.
        motivational_line = existing_line or await self._generate_motivational_line(
            score, decision, job_role, persona, strengths,
        )

        # Generate background image (Imagen 3 — slower, run in executor)
        # Pass the motivational line so the image visually reflects the quote's sentiment.
        loop = asyncio.get_event_loop()
        image_bytes = await loop.run_in_executor(
            None,
            self._sync_generate_background,
            session_id, persona, job_role, score, decision, motivational_line,
        )

        if image_bytes is None:
            logger.warning(
                "Performance card background unavailable after generation attempt (session=%s)",
                session_id,
            )
            # Do not persist a terminal has_background=False state.
            # Returning None allows callers to retry/poll until generation succeeds.
            return None

        card_meta = {
            "session_id": session_id,
            "score": score,
            "decision": decision,
            "job_role": job_role,
            "persona": persona,
            "interviewer_name": interviewer_name,
            "motivational_line": motivational_line,
            "has_background": True,
            "image_url": f"/performance-card/{session_id}/image",
        }

        # Persist metadata to Firestore
        await self._db.collection(_COL_PERFORMANCE_CARDS).document(session_id).set(card_meta)
        logger.info("Performance card generated — session=%s  score=%d", session_id, score)

        return card_meta

    async def get_card_metadata(self, session_id: str) -> dict[str, Any] | None:
        """Return previously generated card metadata, or None."""
        doc = await self._db.collection(_COL_PERFORMANCE_CARDS).document(session_id).get()
        if not doc.exists:
            return None
        return doc.to_dict()

    async def get_card_image(self, session_id: str) -> Optional[bytes]:
        """Return the card background JPEG bytes from GCS, or None."""
        loop = asyncio.get_event_loop()
        try:
            exists = await loop.run_in_executor(None, self._exists_in_gcs, session_id)
            if not exists:
                # Self-heal: attempt generation if image is missing.
                await self.generate(session_id)
                exists = await loop.run_in_executor(None, self._exists_in_gcs, session_id)
                if not exists:
                    return None
            return await loop.run_in_executor(None, self._download_from_gcs, session_id)
        except Exception:
            logger.exception("Failed to fetch card image for session %s", session_id)
            return None
