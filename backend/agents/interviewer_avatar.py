"""
InterviewerAvatarAgent
----------------------
Generates and caches AI profile pictures for each interviewer using
Imagen 3.0 Fast (Vertex AI). Images are stored in GCS and served lazily —
generated once per unique interviewer name, then reused across all sessions.

GCS layout:
  gs://{GCS_BUCKET}/interviewer-avatars/{name_slug}.jpg

Where name_slug is the lower-cased, hyphen/space-normalized interviewer name
(e.g. "Soo-Yeon" → "soo_yeon").
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional

import vertexai
from google.cloud import storage
from vertexai.preview.vision_models import ImageGenerationModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _require(var: str) -> str:
    val = os.getenv(var, "").strip()
    if not val:
        raise EnvironmentError(
            f"Required environment variable '{var}' is not set."
        )
    return val


_PROJECT       = _require("GOOGLE_CLOUD_PROJECT")
_REGION        = _require("GOOGLE_CLOUD_LOCATION")
_BUCKET        = _require("GCS_BUCKET")
_AVATAR_PREFIX = "interviewer-avatars"
_IMAGEN_MODEL  = os.getenv("IMAGEN_MODEL", "imagen-3.0-fast-generate-001")


# ---------------------------------------------------------------------------
# Persona-flavoured descriptors
# These give Imagen richer context so the portrait fits the interviewer's role.
# ---------------------------------------------------------------------------

_PERSONA_DESCRIPTOR: dict[str, str] = {
    "neutral":               "professional corporate interviewer",
    "startup_founder":       "tech startup founder wearing smart casual attire",
    "investment_banker":     "senior investment banker in a sharp tailored suit",
    "tech_lead":             "senior software engineer in business casual",
    "hr_manager":            "friendly HR professional with an approachable look",
    "product_manager":       "product manager in business casual attire",
    "vp_engineering":        "VP of Engineering with a confident look",
    "management_consultant": "management consultant in formal business wear",
    "cto":                   "Chief Technology Officer with an authoritative presence",
    "recruiter":             "corporate talent recruiter with a welcoming expression",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _name_to_slug(name: str) -> str:
    """'Soo-Yeon' → 'soo_yeon'  |  'Mei-Lin' → 'mei_lin'"""
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _build_prompt(name: str, persona: str) -> str:
    descriptor = _PERSONA_DESCRIPTOR.get(persona, "professional interviewer")
    return (
        f"Professional LinkedIn-style headshot portrait photograph of {name}, "
        f"a {descriptor}. "
        "Clean neutral studio background, business attire, "
        "soft professional studio lighting, looking directly at camera with a "
        "confident and approachable expression, photorealistic, high quality, "
        "shoulders and face clearly visible, no text, no watermarks."
    )


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class InterviewerAvatarAgent:
    """Generate (once) and cache AI profile pictures for interviewers."""

    def __init__(self) -> None:
        vertexai.init(project=_PROJECT, location=_REGION)
        self._storage_client = storage.Client(project=_PROJECT)
        self._bucket = self._storage_client.bucket(_BUCKET)
        # Model loaded lazily to avoid startup latency
        self._model: Optional[ImageGenerationModel] = None

    # ------------------------------------------------------------------
    # Internal (synchronous — called via run_in_executor)
    # ------------------------------------------------------------------

    def _get_model(self) -> ImageGenerationModel:
        if self._model is None:
            logger.info("Loading Imagen model: %s", _IMAGEN_MODEL)
            self._model = ImageGenerationModel.from_pretrained(_IMAGEN_MODEL)
        return self._model

    def _blob_name(self, name: str) -> str:
        return f"{_AVATAR_PREFIX}/{_name_to_slug(name)}.jpg"

    def _exists_in_gcs(self, name: str) -> bool:
        return self._bucket.blob(self._blob_name(name)).exists()

    def _download_from_gcs(self, name: str) -> bytes:
        blob = self._bucket.blob(self._blob_name(name))
        return blob.download_as_bytes()

    def _upload_to_gcs(self, name: str, image_bytes: bytes) -> None:
        blob = self._bucket.blob(self._blob_name(name))
        blob.upload_from_string(image_bytes, content_type="image/jpeg")
        logger.info(
            "Interviewer avatar uploaded to GCS — name=%s  blob=%s",
            name, blob.name,
        )

    def _sync_get_or_generate(self, name: str, persona: str) -> Optional[bytes]:
        """Synchronous core: check GCS → generate if missing → return bytes."""
        try:
            if self._exists_in_gcs(name):
                logger.debug("Avatar cache hit for '%s'", name)
                return self._download_from_gcs(name)

            # Generate with Imagen
            logger.info(
                "No cached avatar for '%s' — generating with Imagen (persona=%s)",
                name, persona,
            )
            prompt = _build_prompt(name, persona)
            model = self._get_model()
            response = model.generate_images(
                prompt=prompt,
                number_of_images=1,
                aspect_ratio="1:1",
                person_generation="allow_adult",
                language="en",
                safety_filter_level="block_few",
            )

            if not response.images:
                logger.warning(
                    "Imagen returned no images for '%s' (likely safety filter)", name
                )
                return None

            image_bytes: bytes = response.images[0]._image_bytes
            self._upload_to_gcs(name, image_bytes)
            return image_bytes

        except Exception:
            logger.exception("Avatar get/generate failed for '%s'", name)
            return None

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def get_or_generate(
        self, name: str, persona: str = "neutral"
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
            None, self._sync_get_or_generate, name, persona
        )
