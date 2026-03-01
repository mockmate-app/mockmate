"""
MockMate Interviewer Agent — ADK Streaming definition
------------------------------------------------------
This module is the canonical agent definition used by:
  1. The standalone ADK project (`adk web` for local dev/testing)
  2. The InterviewEngineAgent (via build_agent()) in production

The agent is built dynamically per-session so the system prompt can embed
the candidate's actual question set and chosen interviewer persona.

Environment variables
---------------------
GOOGLE_GENAI_USE_VERTEXAI   TRUE for Vertex AI (production), FALSE for Google AI Studio (dev)
GOOGLE_CLOUD_PROJECT         Required when USE_VERTEXAI=TRUE
GOOGLE_CLOUD_LOCATION        Required when USE_VERTEXAI=TRUE  (e.g. us-central1)
GOOGLE_API_KEY               Required when USE_VERTEXAI=FALSE
MOCKMATE_LIVE_MODEL          Override the Live model (optional)
"""

from __future__ import annotations

import os

from google.adk.agents import Agent

# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------
# Vertex AI GA model — recommended for production
_DEFAULT_VERTEX_MODEL  = "gemini-live-2.5-flash-native-audio"
# Gemini AI Studio model — for local dev without Google Cloud
_DEFAULT_STUDIO_MODEL  = "gemini-2.5-flash-native-audio-preview-12-2025"

_USE_VERTEX = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "TRUE").upper() == "TRUE"
_LIVE_MODEL = os.getenv(
    "MOCKMATE_LIVE_MODEL",
    _DEFAULT_VERTEX_MODEL if _USE_VERTEX else _DEFAULT_STUDIO_MODEL,
)

# ---------------------------------------------------------------------------
# Default system prompt (used by `adk web` dev UI)
# ---------------------------------------------------------------------------
_DEFAULT_INSTRUCTION = """
You are MockMate, an AI interviewer conducting a professional mock interview.
Persona: Neutral professional — balanced, thorough, and fair.

Interview rules:
1. Greet the candidate warmly and start the interview immediately.
2. Ask questions one at a time; wait for the candidate to finish before speaking.
3. Acknowledge each answer briefly and naturally, then move on.
4. After the 6th question, increase pressure — challenge a vague answer or add a curveball.
5. Keep your language concise and professional. You are evaluating, not tutoring.
6. When all questions are exhausted, say: "Thank you, that concludes our interview today."

Since no question set was provided, conduct a general software-engineering interview.
"""


def build_agent(
    system_prompt: str | None = None,
    model: str | None = None,
) -> Agent:
    """
    Build a MockMate interviewer Agent.

    Parameters
    ----------
    system_prompt : str | None
        Custom instruction (includes persona + question set). Falls back to
        the generic default when omitted (useful for `adk web`).
    model : str | None
        Override Live model. Defaults to MOCKMATE_LIVE_MODEL env var.

    Returns
    -------
    Agent  Ready-to-use ADK Agent instance.
    """
    return Agent(
        name="mockmate_interviewer",
        model=model or _LIVE_MODEL,
        instruction=system_prompt or _DEFAULT_INSTRUCTION,
    )


# ---------------------------------------------------------------------------
# `root_agent` — required by `adk web` / ADK CLI to discover the agent
# ---------------------------------------------------------------------------
root_agent = build_agent()
