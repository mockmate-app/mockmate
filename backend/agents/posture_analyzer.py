"""
PostureAnalyzerAgent
---------------------
Analyses video frames from the candidate's webcam during a live mock
interview using Gemini Flash (vision).  Provides two usage modes:

1. **Standalone WebSocket** (`run_live_analysis`) — legacy mode where the
   browser opens a dedicated `/ws/vision/{session_id}` connection.
2. **Inline analysis** (`analyse_frame` / `persist_score`) — called from
   `InterviewEngineAgent` during a live session.  Video frames arrive
   through the main interview WebSocket, and the interview engine routes
   them here for scoring & persistence.

Scores are persisted per-frame in Firestore's `posture_scores` collection
and aggregated by `FeedbackCompilerAgent` when generating the post-session
report.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import traceback
from datetime import datetime, timezone
from typing import Any

import vertexai
from fastapi import WebSocket
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable
from google.cloud import firestore
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
    before_sleep_log,
)
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
_MODEL      = os.getenv("POSTURE_MODEL", "gemini-2.5-flash-lite")           # optional

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
    """Analyses candidate webcam frames for posture & presence scoring."""

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
    # Public API — inline analysis (used by InterviewEngineAgent)
    # ------------------------------------------------------------------

    async def analyse_frame(self, frame_bytes: bytes) -> dict[str, Any]:
        """Analyse a single JPEG frame and return the score dict.

        Returns an empty dict on failure so as not to crash the caller.
        """
        try:
            image_part = Part.from_image(Image.from_bytes(frame_bytes))
            text_part = Part.from_text(ANALYSIS_PROMPT)

            @retry(
                retry=retry_if_exception_type((ResourceExhausted, ServiceUnavailable)),
                wait=wait_random_exponential(multiplier=1, max=30),
                stop=stop_after_attempt(3),
                before_sleep=before_sleep_log(logger, logging.WARNING),
                reraise=True,
            )
            async def _generate_with_retry():
                return await self._model.generate_content_async(
                    [image_part, text_part],
                    generation_config=GenerationConfig(
                        response_mime_type="application/json",
                        temperature=0.1,
                        max_output_tokens=512,
                    ),
                )

            response = await _generate_with_retry()
            return json.loads(response.text)
        except Exception as exc:
            logger.warning(
                "Posture analysis failed for frame: %s: %s\n%s",
                type(exc).__name__, exc, traceback.format_exc(),
            )
            return {}

    async def persist_score(
        self, session_id: str, frame_index: int, score: dict[str, Any],
    ) -> None:
        """Append a frame score to the single per-session posture document.

        All frame scores for a session are batched into one Firestore
        document (keyed by session_id) with a ``frames`` array.  This
        cuts Firestore document count from O(N) to O(1) per session.
        """
        try:
            score["recorded_at"] = datetime.now(timezone.utc).isoformat()
            doc_ref = self._db.collection(_COLLECTION).document(session_id)
            await doc_ref.set(
                {
                    "session_id": session_id,
                    "frames": firestore.ArrayUnion([score]),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                merge=True,
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist posture score — session=%s frame=%d: %s",
                session_id, frame_index, exc,
            )

    # ------------------------------------------------------------------
    # Legacy WebSocket mode (standalone /ws/vision endpoint)
    # ------------------------------------------------------------------

    async def run_live_analysis(self, websocket: WebSocket, session_id: str) -> None:
        """
        Each incoming message from the browser is expected to be a JSON string:
          { "frame": "<base64-encoded JPEG>", "timestamp_ms": <int> }

        For each frame, this method:
          1. Decodes the JPEG bytes.
          2. Sends the frame to Gemini Flash for vision analysis.
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
            score = await self.analyse_frame(frame_bytes)
            if not score:
                continue
            score["frame_index"] = frame_count
            score["timestamp_ms"] = timestamp_ms
            score["session_id"] = session_id

            await self.persist_score(session_id, frame_count, score)
            await websocket.send_text(json.dumps(score))
            frame_count += 1
