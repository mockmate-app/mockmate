"""
InterviewEngineAgent
---------------------
Manages live interview sessions using the Gemini Live API (via google-adk).
Handles:
  - Session creation & Firestore persistence
  - Real-time bidirectional audio streaming over WebSocket
  - Stress injection (curveball / interruption injection mid-session)
  - Publishing session-end events to Pub/Sub
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import vertexai
from fastapi import WebSocket
from google.cloud import firestore, pubsub_v1
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types
from vertexai.generative_models import GenerativeModel

_PROJECT = os.getenv("GCP_PROJECT_ID", "mockmate-project")
_REGION = os.getenv("GCP_REGION", "us-central1")
_COLLECTION = "sessions"
_PUBSUB_TOPIC = os.getenv("PUBSUB_TOPIC_SESSION_END", "session-end")

SYSTEM_PROMPT_TEMPLATE = """
You are MockMate, an AI interviewer conducting a mock interview.

Persona: {persona}

You have access to the following question set (JSON):
{questions_json}

Interview rules:
1. Ask questions one at a time, in the given order.
2. After each candidate answer, provide a brief, neutral acknowledgement and probe
   with a follow-up if the answer is vague or incomplete.
3. After question 6, inject a curveball or deliberately challenge the candidate's
   previous answer to simulate real interview pressure.
4. Keep your language concise and professional — you are evaluating, not tutoring.
5. Never reveal the scoring rubric or that you are an AI unless directly asked.
6. When all questions are exhausted, say: "Thank you, that concludes our interview today."
"""


class InterviewEngineAgent:
    """Manages session lifecycle and live audio streaming."""

    def __init__(self) -> None:
        vertexai.init(project=_PROJECT, location=_REGION)
        self._db = firestore.AsyncClient(project=_PROJECT)
        self._publisher = pubsub_v1.PublisherClient()
        self._topic_path = self._publisher.topic_path(_PROJECT, _PUBSUB_TOPIC)
        self._session_service = InMemorySessionService()

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def create_session(
        self,
        user_id: str,
        questions: list[dict[str, Any]],
        persona: str,
    ) -> str:
        session_id = str(uuid.uuid4())
        doc: dict[str, Any] = {
            "session_id": session_id,
            "user_id": user_id,
            "persona": persona,
            "questions": questions,
            "status": "created",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "transcript": [],
        }
        await self._db.collection(_COLLECTION).document(session_id).set(doc)
        return session_id

    async def end_session(self, session_id: str) -> None:
        await self._db.collection(_COLLECTION).document(session_id).update(
            {"status": "ended", "ended_at": datetime.now(timezone.utc).isoformat()}
        )
        self._publisher.publish(
            self._topic_path,
            data=json.dumps({"session_id": session_id}).encode("utf-8"),
        )

    # ------------------------------------------------------------------
    # Live streaming
    # ------------------------------------------------------------------

    async def run_live_session(self, websocket: WebSocket, session_id: str) -> None:
        """
        Streams audio bytes between the browser and the Gemini Live API.
        The browser sends binary audio chunks; this method forwards them to
        Gemini and streams AI audio responses back in real time.
        """
        session_doc = await self._db.collection(_COLLECTION).document(session_id).get()
        if not session_doc.exists:
            await websocket.close(code=4404, reason="Session not found")
            return

        session_data = session_doc.to_dict()
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            persona=session_data.get("persona", "neutral"),
            questions_json=json.dumps(session_data.get("questions", []), indent=2),
        )

        agent = Agent(
            name="mockmate_interviewer",
            model="gemini-2.0-flash-live-001",
            instruction=system_prompt,
        )
        runner = Runner(
            agent=agent,
            app_name="mockmate",
            session_service=self._session_service,
        )

        adk_session = await self._session_service.create_session(
            app_name="mockmate", user_id=session_data["user_id"]
        )

        await self._db.collection(_COLLECTION).document(session_id).update(
            {"status": "active"}
        )

        try:
            async for audio_chunk in websocket.iter_bytes():
                content = genai_types.Content(
                    role="user",
                    parts=[genai_types.Part.from_bytes(data=audio_chunk, mime_type="audio/pcm")],
                )
                async for event in runner.run_async(
                    user_id=session_data["user_id"],
                    session_id=adk_session.id,
                    new_message=content,
                ):
                    if event.content and event.content.parts:
                        for part in event.content.parts:
                            if hasattr(part, "inline_data") and part.inline_data:
                                await websocket.send_bytes(part.inline_data.data)
                            elif part.text:
                                await websocket.send_text(
                                    json.dumps({"type": "transcript", "text": part.text})
                                )
        finally:
            await self.end_session(session_id)
