"""
PostureAnalyzerAgent
---------------------
Receives base-64 encoded video frames from the browser over a WebSocket,
sends them to Gemini 2.0 Flash (vision) for real-time posture and presence
scoring, persists scores per-frame in Firestore, and streams scored results
back to the browser.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import vertexai
from fastapi import WebSocket
from google.cloud import firestore
from vertexai.generative_models import GenerationConfig, GenerativeModel, Image, Part

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


_PROJECT    = _require("GOOGLE_CLOUD_PROJECT")
_REGION     = _require("GOOGLE_CLOUD_LOCATION")
_COLLECTION = os.getenv("FIRESTORE_POSTURE_COLLECTION", "posture_scores")  # optional
_DATABASE   = os.getenv("FIRESTORE_DATABASE", "(default)")                  # optional
_MODEL      = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")             # optional

ANALYSIS_PROMPT = """
You are a professional interview coach analysing a single video frame from a
live mock interview.

Evaluate the candidate on the following dimensions and return ONLY a JSON object:
{
  "posture_score": <0-100>,
  "eye_contact_score": <0-100>,
  "facial_confidence_score": <0-100>,
  "overall_presence_score": <0-100>,
  "observations": ["<short observation 1>", "<short observation 2>"]
}

Scoring rubric:
- posture_score: upright (100) → slouched (0)
- eye_contact_score: looking at camera (100) → looking away (0)
- facial_confidence_score: calm/engaged expression (100) → nervous/blank (0)
- overall_presence_score: weighted average of the above + professional appearance

Keep observations concise (≤10 words each).
"""


class PostureAnalyzerAgent:
    """Streams per-frame posture scores using Gemini 2.0 Flash vision."""

    def __init__(self) -> None:
        logger.info(
            "PostureAnalyzerAgent config — project=%s  region=%s  "
            "firestore_db=%s  collection=%s  model=%s",
            _PROJECT, _REGION, _DATABASE, _COLLECTION, _MODEL,
        )
        vertexai.init(project=_PROJECT, location=_REGION)
        self._model = GenerativeModel(_MODEL)
        self._db = firestore.AsyncClient(project=_PROJECT, database=_DATABASE)

    # ------------------------------------------------------------------
    # Live analysis loop
    # ------------------------------------------------------------------

    async def run_live_analysis(self, websocket: WebSocket, session_id: str) -> None:
        """
        Each incoming message from the browser is expected to be a JSON string:
          { "frame": "<base64-encoded JPEG>", "timestamp_ms": <int> }

        For each frame, this method:
          1. Decodes the JPEG bytes.
          2. Sends the frame to Gemini 2.0 Flash for vision analysis.
          3. Persists the scored result in Firestore.
          4. Sends the score JSON back to the browser.
        """
        frame_count = 0
        async for raw_message in websocket.iter_text():
            payload: dict[str, Any] = json.loads(raw_message)
            frame_b64: str = payload.get("frame", "")
            timestamp_ms: int = payload.get("timestamp_ms", 0)

            if not frame_b64:
                continue

            frame_bytes = base64.b64decode(frame_b64)
            score = await self._analyse_frame(frame_bytes)
            score["frame_index"] = frame_count
            score["timestamp_ms"] = timestamp_ms
            score["session_id"] = session_id

            await self._persist(session_id, frame_count, score)
            await websocket.send_text(json.dumps(score))
            frame_count += 1

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _analyse_frame(self, frame_bytes: bytes) -> dict[str, Any]:
        image_part = Part.from_image(Image.from_bytes(frame_bytes))
        text_part = Part.from_text(ANALYSIS_PROMPT)
        response = await self._model.generate_content_async(
            [image_part, text_part],
            generation_config=GenerationConfig(
                response_mime_type="application/json",
                temperature=0.1,
                max_output_tokens=512,
            ),
        )
        return json.loads(response.text)

    async def _persist(
        self, session_id: str, frame_index: int, score: dict[str, Any]
    ) -> None:
        doc_id = f"{session_id}_frame_{frame_index:06d}"
        score["recorded_at"] = datetime.now(timezone.utc).isoformat()
        await (
            self._db.collection(_COLLECTION)
            .document(doc_id)
            .set(score)
        )
