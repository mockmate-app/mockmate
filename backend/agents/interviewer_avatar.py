"""
InterviewerAvatarAgent
----------------------
Generates and caches AI profile pictures for each interviewer using
Imagen 4.0 Fast (Vertex AI). Images are stored in GCS and served lazily —
generated once per unique interviewer name, then reused across all sessions.

GCS layout:
  gs://{GCS_BUCKET}/interviewer-avatars/{name_slug}.jpg

Where name_slug is the lower-cased, hyphen/space-normalized interviewer name
(e.g. "Soo-Yeon" → "soo_yeon").
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable
from google.cloud import storage
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
    before_sleep_log,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

from agents.config import (
    PROJECT as _PROJECT,
    REGION as _REGION,
    GCS_BUCKET as _BUCKET,
    IMAGEN_MODEL as _IMAGEN_MODEL,
    require_env,
)

# GCS_BUCKET is required for this agent
if not _BUCKET:
    _BUCKET = require_env("GCS_BUCKET")

_AVATAR_PREFIX = "interviewer-avatars"
_AVATAR_CACHE_VERSION = "v2"


# ---------------------------------------------------------------------------
# Persona-flavoured descriptors
# These give Imagen richer context so the portrait fits the interviewer's role.
# ---------------------------------------------------------------------------

_PERSONA_STYLE: dict[str, dict[str, str]] = {
    "neutral": {
        "descriptor": "professional corporate interviewer",
        "setting": "clean neutral studio background",
        "attire": "business attire",
        "lighting": "soft professional studio lighting",
        "expression": "confident and approachable expression",
        "vibe": "LinkedIn-style headshot portrait photograph",
    },
    "startup_founder": {
        "descriptor": "tech startup founder",
        "setting": "modern coworking space or trendy café background, slightly blurred",
        "attire": "smart casual — hoodie and blazer, or t-shirt under a jacket",
        "lighting": "warm natural window light",
        "expression": "energetic grin, slightly leaning forward",
        "vibe": "candid portrait photograph with startup energy",
    },
    "investment_banker": {
        "descriptor": "senior investment banker",
        "setting": "sleek corporate office with city skyline visible through glass",
        "attire": "sharp tailored dark suit, crisp white shirt, silk tie",
        "lighting": "dramatic side lighting, high contrast",
        "expression": "composed, measured, subtly intimidating",
        "vibe": "formal corporate portrait photograph",
    },
    "tech_lead": {
        "descriptor": "senior software engineer and tech lead",
        "setting": "home office or engineering workspace with monitors in background, blurred",
        "attire": "casual — plain t-shirt or flannel, comfortable",
        "lighting": "soft ambient indoor lighting",
        "expression": "thoughtful, slightly focused, relaxed half-smile",
        "vibe": "relaxed candid portrait, developer aesthetic",
    },
    "hr_manager": {
        "descriptor": "friendly HR professional",
        "setting": "bright open-plan modern office background, slightly blurred",
        "attire": "smart business casual — colorful blouse or neat polo",
        "lighting": "bright even lighting, warm tones",
        "expression": "warm genuine smile, welcoming and approachable",
        "vibe": "friendly corporate portrait photograph",
    },
    "product_manager": {
        "descriptor": "product manager",
        "setting": "whiteboard or sticky-note wall background, slightly blurred",
        "attire": "business casual — button-up shirt, no tie, sleeves rolled",
        "lighting": "natural office lighting",
        "expression": "engaged and curious, slight smile",
        "vibe": "editorial-style workplace portrait",
    },
    "vp_engineering": {
        "descriptor": "VP of Engineering",
        "setting": "executive office or conference room background",
        "attire": "polished business casual — blazer over a dark crewneck",
        "lighting": "balanced professional studio lighting",
        "expression": "confident, calm authority, slight smile",
        "vibe": "executive leadership portrait photograph",
    },
    "management_consultant": {
        "descriptor": "management consultant",
        "setting": "premium hotel lobby or sleek conference room background",
        "attire": "formal business wear — dark suit, polished shoes visible",
        "lighting": "crisp professional lighting, neutral tones",
        "expression": "poised, analytical, composed",
        "vibe": "formal professional headshot photograph",
    },
    "cto": {
        "descriptor": "Chief Technology Officer",
        "setting": "modern tech office with subtle tech artwork or server racks in background, blurred",
        "attire": "smart-casual to polished — dark henley or turtleneck, or blazer with no tie",
        "lighting": "cool-toned modern lighting",
        "expression": "authoritative yet approachable, direct gaze",
        "vibe": "tech executive editorial portrait",
    },
    "recruiter": {
        "descriptor": "corporate talent recruiter",
        "setting": "cozy office corner or café background, warm tones",
        "attire": "smart casual — neat sweater or blouse, approachable",
        "lighting": "warm soft lighting",
        "expression": "bright welcoming smile, open body language",
        "vibe": "warm friendly portrait photograph",
    },
    "algorithm_guru": {
        "descriptor": "algorithms and data structures specialist",
        "setting": "university office or library with books and whiteboards in background",
        "attire": "academic casual — plain shirt, cardigan, or hoodie",
        "lighting": "soft indoor lighting",
        "expression": "intense focus, knowing half-smile",
        "vibe": "academic portrait photograph",
    },
    "system_designer": {
        "descriptor": "system design and architecture expert",
        "setting": "whiteboard with architecture diagrams in background, blurred",
        "attire": "casual — t-shirt or polo, relaxed",
        "lighting": "natural office lighting",
        "expression": "thoughtful, analytical gaze",
        "vibe": "candid workplace portrait",
    },
    "prompt_wizard": {
        "descriptor": "AI engineer and machine learning specialist",
        "setting": "modern AI lab or tech workspace with screens in background",
        "attire": "modern tech casual — graphic tee or smart hoodie",
        "lighting": "cool-toned ambient lighting",
        "expression": "curious, slightly playful smile",
        "vibe": "modern tech portrait photograph",
    }
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _name_to_slug(name: str) -> str:
    """'Soo-Yeon' → 'soo_yeon'  |  'Mei-Lin' → 'mei_lin'"""
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _build_prompt(name: str, persona: str, gender_hint: str | None = None) -> str:
    style = _PERSONA_STYLE.get(persona, _PERSONA_STYLE["neutral"])
    gender_clause = ""
    if gender_hint:
        normalized = gender_hint.strip().lower()
        if normalized == "male":
            gender_clause = " presenting as male."
        elif normalized == "female":
            gender_clause = " presenting as female."
        elif normalized in {"nonbinary", "non-binary"}:
            gender_clause = " presenting as non-binary."
    return (
        f"{style['vibe']} of {name}, "
        f"a {style['descriptor']}.{gender_clause} "
        f"{style['setting']}, {style['attire']}, "
        f"{style['lighting']}, looking directly at camera with a "
        f"{style['expression']}, photorealistic, high quality, "
        "shoulders and face clearly visible, no text, no watermarks."
    )


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class InterviewerAvatarAgent:
    """Generate (once) and cache AI profile pictures for interviewers."""

    def __init__(self) -> None:
        self._client = genai.Client(
            vertexai=True,
            project=_PROJECT,
            location=_REGION,
        )
        self._storage_client = storage.Client(project=_PROJECT)
        self._bucket = self._storage_client.bucket(_BUCKET)

    # ------------------------------------------------------------------
    # Internal (synchronous — called via run_in_executor)
    # ------------------------------------------------------------------

    def _blob_name(self, name: str, persona: str, gender_hint: str | None = None) -> str:
        gender_slug = (gender_hint or "unspecified").strip().lower().replace("-", "_")
        if not gender_slug:
            gender_slug = "unspecified"
        return (
            f"{_AVATAR_PREFIX}/{_AVATAR_CACHE_VERSION}/"
            f"{_name_to_slug(name)}__{_name_to_slug(persona)}__{_name_to_slug(gender_slug)}.jpg"
        )

    def _exists_in_gcs(self, name: str, persona: str, gender_hint: str | None = None) -> bool:
        return self._bucket.blob(self._blob_name(name, persona, gender_hint)).exists()

    def _download_from_gcs(self, name: str, persona: str, gender_hint: str | None = None) -> bytes:
        blob = self._bucket.blob(self._blob_name(name, persona, gender_hint))
        return blob.download_as_bytes()

    def _upload_to_gcs(self, name: str, persona: str, gender_hint: str | None, image_bytes: bytes) -> None:
        blob = self._bucket.blob(self._blob_name(name, persona, gender_hint))
        blob.upload_from_string(image_bytes, content_type="image/jpeg")
        logger.info(
            "Interviewer avatar uploaded to GCS — name=%s  blob=%s",
            name, blob.name,
        )

    def _sync_get_or_generate(self, name: str, persona: str, gender_hint: str | None = None) -> Optional[bytes]:
        """Synchronous core: check GCS → generate if missing → return bytes."""
        try:
            if self._exists_in_gcs(name, persona, gender_hint):
                logger.debug("Avatar cache hit for '%s'", name)
                return self._download_from_gcs(name, persona, gender_hint)

            # Generate with Imagen
            logger.info(
                "No cached avatar for '%s' — generating with Imagen (persona=%s)",
                name, persona,
            )
            prompt = _build_prompt(name, persona, gender_hint)

            @retry(
                retry=retry_if_exception_type((ResourceExhausted, ServiceUnavailable, genai_errors.APIError)),
                wait=wait_random_exponential(multiplier=1, max=60),
                stop=stop_after_attempt(5),
                before_sleep=before_sleep_log(logger, logging.WARNING),
                reraise=True,
            )
            def _generate_with_retry():
                return self._client.models.generate_images(
                    model=_IMAGEN_MODEL,
                    prompt=prompt,
                    config=genai_types.GenerateImagesConfig(
                        number_of_images=1,
                        aspect_ratio="1:1",
                        output_mime_type="image/jpeg",
                    ),
                )

            response = _generate_with_retry()

            generated = getattr(response, "generated_images", None) or []
            if not generated:
                logger.warning(
                    "Imagen returned no images for '%s' (likely safety filter)", name
                )
                return None

            image_obj = getattr(generated[0], "image", None)
            image_bytes: bytes | None = getattr(image_obj, "image_bytes", None)
            if not image_bytes:
                logger.warning("Imagen response missing image bytes for '%s'", name)
                return None
            self._upload_to_gcs(name, persona, gender_hint, image_bytes)
            return image_bytes

        except Exception:
            logger.exception("Avatar get/generate failed for '%s'", name)
            return None

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def get_or_generate(
        self, name: str, persona: str = "neutral", gender_hint: str | None = None
    ) -> Optional[bytes]:
        """
        Return avatar JPEG bytes for *name*.

        If a cached image exists in GCS it is returned instantly.
        Otherwise Imagen generates a portrait, uploads it to GCS, and
        returns the bytes.  Returns None on any error so callers can
        fall back to a text-initial avatar gracefully.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._sync_get_or_generate, name, persona, gender_hint
        )
