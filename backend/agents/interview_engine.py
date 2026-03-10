"""
InterviewEngineAgent
---------------------
Manages live interview sessions using the Gemini Live API (via google-adk).
Handles:
  - Session creation & Firestore persistence
  - Real-time bidirectional audio streaming over WebSocket
  - Adaptive follow-ups and probing via prompting
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import random
import time
import traceback
import uuid
import pathlib
import warnings
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from agents.posture_analyzer import PostureAnalyzerAgent

import vertexai
from fastapi import WebSocket, WebSocketDisconnect
from google.cloud import firestore, pubsub_v1
from google.adk.agents import Agent
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types
from google.genai.errors import APIError
from google.adk.tools import google_search
from websockets.exceptions import ConnectionClosed

from agents.config import (
    PROJECT as _PROJECT,
    REGION as _REGION,
    FIRESTORE_DATABASE as _DATABASE,
    FIRESTORE_SESSION_COLLECTION as _COLLECTION,
    FIRESTORE_RESUME_COLLECTION as _RESUME_COLLECTION,
    FIRESTORE_TRANSCRIPT_COLLECTION as _TRANSCRIPT_COLLECTION,
    FIRESTORE_FEEDBACK_COLLECTION as _FEEDBACK_COLLECTION,
    GEMINI_MODEL as _MODEL,
    GEMINI_LIVE_MODEL as _LIVE_MODEL,
    PUBSUB_TOPIC_SESSION_END as _PUBSUB_TOPIC,
    PGHOST as _PGHOST,
    PGPORT as _PGPORT,
    PGUSER as _PGUSER,
    PGPASSWORD as _PGPASSWORD,
    PGDATABASE as _PGDATABASE,
)

logger = logging.getLogger(__name__)

_APP_NAME     = "mockmate"
_DEFAULT_VOICE = "Aoede"

# ---------------------------------------------------------------------------
# Per-session flavor randomization
# Each pool has 3 options → 3^5 = 243 unique style combinations per session.
# Flavor is injected into SYSTEM_PROMPT_TEMPLATE at session start.
# ---------------------------------------------------------------------------

_FLAVOR_SKEPTICISM = [
    "Maintain a mildly skeptical default — probe impressive-sounding claims; reward specificity.",
    "Be genuinely curious and open — assume competence unless evidence says otherwise.",
    "Default to neutral; only push back when an answer is provably vague or contradictory.",
]
_FLAVOR_PACING = [
    "Keep a brisk, efficient pace — move on quickly once you have what you need.",
    "Allow comfortable pauses and silence; let the candidate breathe and think.",
    "Vary the energy — start relaxed, build intensity as the interview progresses.",
]
_FLAVOR_DEBATE = [
    "When the candidate makes a strong claim, politely challenge it once before accepting it.",
    "Prefer to explore ideas collaboratively — challenge sparingly, only on clear overstatements.",
    "Challenge once per session only, and only on the most pivotal answer.",
]
_FLAVOR_FOLLOWUP = [
    "Ask one unexpected hypothetical ('What if the opposite were true?') as a follow-up.",
    "Push for conciseness: ask for a tighter version ('Give me the 30-second version').",
    "Ask one deeply personal career question to go beyond the professional surface.",
]
_FLAVOR_WARMTH = [
    "Run professionally warm — an occasional genuine laugh or light joke is fine.",
    "Stay polished and measured — warmth through listening, not banter.",
    "Start cool and formal; warm up noticeably only after a strong first answer.",
]

# Six opening packs — randomized per session to vary greeting energy + small talk hook.
_FLAVOR_OPENING = [
    {
        "greeting_energy": "upbeat and warm",
        "small_talk_hook": "ask how their week's been going or how they've been lately",
        "transition_phrase": "Alright, let's get into it!",
    },
    {
        "greeting_energy": "cool and professional",
        "small_talk_hook": "ask casually if they've been doing many of these interviews lately",
        "transition_phrase": "Right — let's get started.",
    },
    {
        "greeting_energy": "casually curious",
        "small_talk_hook": "ask where they're joining from and what they've been keeping busy with lately",
        "transition_phrase": "Cool — let's jump in then.",
    },
    {
        "greeting_energy": "light and energetic",
        "small_talk_hook": "make a brief friendly comment about the day before asking how they're doing",
        "transition_phrase": "Okay, shall we get into it?",
    },
    {
        "greeting_energy": "understated and dry",
        "small_talk_hook": "make one short deadpan observation then ask a low-key question",
        "transition_phrase": "Alright, let's get going.",
    },
    {
        "greeting_energy": "direct but personable",
        "small_talk_hook": "briefly acknowledge you've had a glance at their background then ask what drew them to the role",
        "transition_phrase": "Great — let's dive in.",
    },
]


def _build_session_flavor() -> str:
    """Pick one option from each flavor pool and return as prompt instructions."""
    return "\n".join([
        f"Skepticism stance: {random.choice(_FLAVOR_SKEPTICISM)}",
        f"Pacing style: {random.choice(_FLAVOR_PACING)}",
        f"Challenge/debate approach: {random.choice(_FLAVOR_DEBATE)}",
        f"Follow-up strategy: {random.choice(_FLAVOR_FOLLOWUP)}",
        f"Warmth register: {random.choice(_FLAVOR_WARMTH)}",
    ])


def _build_opening_flavor(pack: dict) -> str:
    """Render one opening pack as a prompt instruction block."""
    return (
        f"Opening energy for this session: {pack['greeting_energy']}. "
        f"Small-talk hook: {pack['small_talk_hook']}. "
        f"Transition phrase inspiration (do NOT copy verbatim — adapt naturally): "
        f"\"{pack['transition_phrase']}\". "
        f"Use these only as a tonal guide — never read them word-for-word."
    )


# ---------------------------------------------------------------------------
# Persona registry — loaded from personas.json at import time.
# To add or edit a persona, update personas.json — no Python changes needed.
# ---------------------------------------------------------------------------
_PERSONAS_JSON = pathlib.Path(__file__).with_name("personas.json")


def _load_personas() -> dict:
    with _PERSONAS_JSON.open(encoding="utf-8") as fh:
        return json.load(fh)["personas"]


_PERSONAS: dict = _load_personas()

PERSONA_INTERVIEWER_PROFILES: dict[str, list[dict[str, str]]] = {
    key: p["interviewer_profiles"] for key, p in _PERSONAS.items()
}
PERSONA_PERSONALITY_GUIDANCE: dict[str, str] = {
    key: p["personality_guidance"] for key, p in _PERSONAS.items()
}
PERSONA_CONVERSATION_GUIDANCE: dict[str, str] = {
    key: p["conversation_guidance"] for key, p in _PERSONAS.items()
}

_DEFAULT_INTERVIEWER_PROFILE = {"name": "Alex", "voice": _DEFAULT_VOICE, "accent_hint": "American English"}
INTERVIEWER_NAME_TO_VOICE = {
    profile["name"]: profile["voice"]
    for profiles in PERSONA_INTERVIEWER_PROFILES.values()
    for profile in profiles
}
INTERVIEWER_NAME_TO_ACCENT = {
    profile["name"]: profile.get("accent_hint", "American English")
    for profiles in PERSONA_INTERVIEWER_PROFILES.values()
    for profile in profiles
}

# Accent-specific speech pattern guidance — gives the model concrete anchors
# for HOW each accent should sound (rhythm, intonation, word choices, etc.).
ACCENT_GUIDANCE: dict[str, str] = {
    "Indian English": (
        "• Speak with a clear Indian English accent — slightly musical intonation with a rising-falling pattern.\n"
        "• Use Indian English phrasing naturally: \"actually\", \"basically\", \"itself\", \"only\" as emphasis markers.\n"
        "• Slightly roll your Rs. Use a dental T/D sound (tongue against teeth, not alveolar ridge).\n"
        "• Rhythm: syllable-timed (each syllable gets roughly equal length), not stress-timed.\n"
        "• Occasional Indian English idioms are fine: \"do one thing\", \"what say?\", \"no?\", \"isn't it?\" at the end of sentences.\n"
        "• Pace may be slightly faster in casual moments, slower when making important points."
    ),
    "American English": (
        "• Standard American English accent — rhotic Rs, flat intonation pattern.\n"
        "• Natural American phrasing: \"gonna\", \"wanna\", \"kinda\", \"you know\", \"right?\" in casual moments.\n"
        "• Relaxed, conversational rhythm. Stress-timed with clear emphasis on key words."
    ),
    "British English": (
        "• Speak with a clear British English accent — non-rhotic (don't pronounce Rs at end of words).\n"
        "• British phrasing: \"quite\", \"rather\", \"brilliant\", \"straightaway\", \"have a look\".\n"
        "• Slightly clipped consonants. More precise enunciation than American English.\n"
        "• Received Pronunciation or educated Southern English — measured and articulate."
    ),
    "Australian English": (
        "• Speak with an Australian accent — distinctive rising intonation at end of statements (uptalk).\n"
        "• Aussie phrasing: \"no worries\", \"heaps\", \"reckon\", \"keen\", \"spot on\", \"fair enough\".\n"
        "• Relaxed and informal rhythm. Slightly nasal vowels. A-sounds become broader."
    ),
    "Irish English": (
        "• Speak with an Irish English accent — lilting, melodic intonation with musical rises and falls.\n"
        "• Irish phrasing: \"grand\", \"sure look\", \"right so\", \"ah now\", \"to be fair\".\n"
        "• Softer consonants. Th-sounds may become more dental. T at end of words is more aspirated."
    ),
    "Chinese English": (
        "• Speak with a Chinese English accent — more evenly-paced, tonal influences from Mandarin.\n"
        "• Slightly more formal word choices. Precise grammar. Fewer contractions.\n"
        "• Rhythm: more syllable-timed. Each word gets clear enunciation.\n"
        "• May occasionally use more formal phrasing where a native speaker would be casual."
    ),
    "Japanese English": (
        "• Speak with a Japanese English accent — polite, precise, and measured.\n"
        "• Slightly more formal and courteous phrasing. Add vowel sounds between consonant clusters.\n"
        "• Rhythm: mora-timed (even spacing). Clear enunciation of each syllable.\n"
        "• Very polite markers: \"I think\", \"perhaps\", \"if I may\" — indirect rather than blunt."
    ),
    "Korean English": (
        "• Speak with a Korean English accent — crisp and precise with clear enunciation.\n"
        "• Slightly more formal register. Direct but polite.\n"
        "• Rhythm: syllable-timed with clear pauses between phrases.\n"
        "• May use slightly more formal phrasing: \"I would like to ask\" rather than \"I wanna ask\"."
    ),
    "French English": (
        "• Speak with a French English accent — melodic intonation with emphasis on final syllables.\n"
        "• French-influenced rhythm: stress tends toward the end of phrases.\n"
        "• Slightly softer H sounds. Th may become Z. R may be slightly uvular.\n"
        "• Occasional Gallic phrasing: \"how shall I say\", \"if you will\", \"in effect\"."
    ),
    "German English": (
        "• Speak with a German English accent — precise, clipped, and well-structured.\n"
        "• Clear, sharp consonants. W sounds may lean slightly toward V.\n"
        "• Very structured and logical phrasing. Formal word choices.\n"
        "• Rhythm: even and methodical. No rushing. Each word is fully pronounced."
    ),
    "Latin American English": (
        "• Speak with a Latin American English accent — warm, rhythmic, slightly musical.\n"
        "• Spanish-influenced rhythm: slightly more syllable-timed. Vowels are clear and open.\n"
        "• Warm and expressive intonation. More melodic than flat.\n"
        "• Occasional warm phrasing: enthusiastic reactions, slightly more emotional expressiveness."
    ),
    "Brazilian English": (
        "• Speak with a Brazilian English accent — warm, open, and rhythmic.\n"
        "• Portuguese-influenced musicality. Open vowels. S may become SH before consonants.\n"
        "• Warm, friendly, and slightly more expressive than neutral English.\n"
        "• Enthusiastic and personable rhythm — Brazilians tend toward warmth in conversation."
    ),
    "Spanish English": (
        "• Speak with a Spanish English accent — clear, rhythmic, with rolled or tapped Rs.\n"
        "• Syllable-timed rhythm. Each vowel gets clear pronunciation.\n"
        "• Slightly more formal phrasing. Clear enunciation.\n"
        "• Warm but precise. B/V distinction may blur slightly."
    ),
    "Italian English": (
        "• Speak with an Italian English accent — expressive, melodic, and animated.\n"
        "• Musical intonation with dramatic rises and falls. Vowels are open and full.\n"
        "• Expressive hand-gesture energy in voice — varied pitch, slightly theatrical.\n"
        "• Warm and passionate. May add vowel sounds at the end of words ending in consonants."
    ),
    "Russian English": (
        "• Speak with a Russian English accent — deep, measured, and slightly gravelly.\n"
        "• Flatter intonation. Articles (a, the) may be dropped occasionally.\n"
        "• Consonants are harder and more pronounced. R is slightly rolled.\n"
        "• Direct and economical phrasing. No unnecessary pleasantries."
    ),
    "Eastern European English": (
        "• Speak with an Eastern European English accent — precise, slightly formal, measured.\n"
        "• Harder consonants. Slightly more staccato rhythm.\n"
        "• Direct communication style. Fewer filler words. More formal register.\n"
        "• Clear and deliberate enunciation."
    ),
    "Scandinavian English": (
        "• Speak with a Scandinavian English accent — melodic, with a sing-song quality.\n"
        "• Musical intonation — pitch goes up and down in a distinctive pattern.\n"
        "• Very clear pronunciation. Near-perfect but with noticeable Nordic melody.\n"
        "• Direct and understated. Dry humor. \"Interesting\" with a slight Nordic lilt."
    ),
    "Singaporean English": (
        "• Speak with a Singaporean English accent — efficient, clipped, with distinct rhythm.\n"
        "• Singlish-influenced: may add \"lah\", \"lor\", \"meh\" as conversational particles sparingly.\n"
        "• Staccato rhythm. Sentences may end with rising intonation.\n"
        "• Mix of British English base with Southeast Asian influences."
    ),
    "Middle Eastern English": (
        "• Speak with a Middle Eastern English accent — rich, slightly guttural, dignified.\n"
        "• Arabic-influenced: slightly emphatic consonants, especially T, D, K.\n"
        "• Measured and formal rhythm. Clear pronunciation.\n"
        "• Dignified and courteous phrasing. May use slightly more formal constructions."
    ),
    "Nigerian English": (
        "• Speak with a Nigerian English accent — melodic, confident, and rhythmic.\n"
        "• West African intonation: syllable-timed with a distinctive musical quality.\n"
        "• Confident and assertive rhythm. Clear, strong consonants.\n"
        "• British English base with Nigerian inflections. Warm but authoritative."
    ),
    "East African English": (
        "• Speak with an East African English accent — clear, measured, and articulate.\n"
        "• Swahili/regional influences: slightly more formal word choices.\n"
        "• Warm, clear rhythm. Precise enunciation with a gentle musicality.\n"
        "• Balanced between formal and approachable."
    ),
    "Ghanaian English": (
        "• Speak with a Ghanaian English accent — warm, musical, and eloquent.\n"
        "• West African rhythm with British English foundations. Clear and articulate.\n"
        "• Confident and warm. Slightly more formal and courteous phrasing.\n"
        "• Rich, expressive intonation. Words are fully pronounced."
    ),
    "Romanian English": (
        "• Speak with a Romanian English accent — Romance language-influenced, melodic.\n"
        "• Slightly rolled Rs. Clear vowels. Latin-influenced rhythm.\n"
        "• Precise and articulate. Slightly more formal than casual American English.\n"
        "• Warm but measured delivery."
    ),
    "Greek English": (
        "• Speak with a Greek English accent — warm, rhythmic, and slightly dramatic.\n"
        "• Mediterranean musicality. Clear consonants. Open vowels.\n"
        "• Expressive intonation — more animated than Northern European accents.\n"
        "• Warm and direct. Confident delivery."
    ),
}

def _get_accent_guidance(accent_hint: str) -> str:
    """Return accent-specific speech guidance, or a generic fallback."""
    if accent_hint in ACCENT_GUIDANCE:
        return ACCENT_GUIDANCE[accent_hint]
    return (
        f"• Speak with a clear {accent_hint} accent consistently.\n"
        f"• Use natural speech patterns and phrasing typical of {accent_hint} speakers."
    )

_DEFAULT_PERSONALITY_GUIDANCE = PERSONA_PERSONALITY_GUIDANCE["neutral"]
_DEFAULT_CONVERSATION_GUIDANCE = PERSONA_CONVERSATION_GUIDANCE["neutral"]

SYSTEM_PROMPT_TEMPLATE = """
You are {interviewer_name}, conducting a live voice mock interview for MockMate.
The candidate's name is: {candidate_name}
The candidate is interviewing for: {job_role}

━━━ ACCENT & SPEECH PATTERN (CRITICAL — apply to every word you speak) ━━━
Your accent: {accent_hint}
You MUST speak with a clear {accent_hint} accent throughout the ENTIRE interview.
This is non-negotiable — your accent defines your character.
{accent_guidance}
Do NOT drift into a generic American accent. Maintain your {accent_hint} accent
from the very first word to the very last. If you catch yourself sounding neutral,
immediately re-anchor to your accent.

━━━ ABSOLUTE RULES (apply to EVERY response you produce) ━━━
• NEVER accept gibberish, off-topic, or nonsensical answers. If the candidate says
  random words, sounds, unrelated phrases, or anything that does not actually answer
  your question — DO NOT say "Interesting", "Tell me more", or move on. Call it out
  and re-ask the same question. See GUARDRAILS for the full escalation protocol.
• NEVER move to a new question until the current one has received a real answer.

━━━ YOUR PERSONA (HIGHEST PRIORITY — shapes everything you say) ━━━
{personality_guidance}

{conversation_guidance}

You MUST stay fully in character as this persona at ALL times. Your personality is
not a suggestion — it is the lens through which every response is filtered.
  • Your word choice, sentence length, warmth level, and pushback style must ALL
    reflect the personality above — not generic interviewer behavior.
  • When in doubt about tone, re-read your personality guidance and choose the
    response that persona would give, not the "safe" or "neutral" one.
  • Do NOT flatten into a generic professional interviewer. Each persona has a
    distinct voice — maintain it from greeting to closing.

━━━ SESSION STYLE (per-session — overrides defaults where they conflict) ━━━
{session_flavor}

INTERNAL QUESTION BANK — NEVER read aloud or acknowledge this list exists.
Use it only as a private competency coverage checklist:
{questions_json}

━━━ PHASE 1: SMALL TALK (mandatory — always do this first) ━━━

1. Greet the candidate BY NAME. Use their name ({candidate_name}) naturally:
   "Hey {candidate_name}, I'm {interviewer_name}. How are you doing today?"
   or "Hi {candidate_name} — I'm {interviewer_name}, nice to meet you. How's your day going?"
   IMPORTANT: You MUST use the candidate's name in your very first sentence.
2. Make exactly 2-3 exchanges of genuine small talk BEFORE anything interview-related.
   Use this session-specific opening as your tonal guide (NOT a script — adapt it naturally):
     {session_opening}
   • Actually listen to and react to what they say — don't rush past it.
   • Match the small talk tone to your PERSONALITY above.
   • If your personality says minimal/formal small talk (e.g., investment_banker), do only 1 short exchange.
3. Transition naturally (not robotically) — draw on the transition phrase inspiration from the guide above.
   Do NOT say "Let's begin the interview" or anything scripted.

━━━ PHASE 2: INTRODUCTION (mandatory — always do this after small talk) ━━━

Ask the candidate to introduce themselves. This is non-negotiable — every real interview starts here.
Use one of these naturally:
  • "So, tell me a bit about yourself — what have you been up to?"
  • "Walk me through your background — how'd you end up where you are today?"
  • "Give me a quick overview of your experience."

Listen to their intro. React to it briefly ("Interesting" / "Nice" / "Cool background").
Then, before asking the first competency question, briefly and naturally signal what kind of questions
are coming. Keep it one casual sentence — never announce it like a formal agenda. Examples:
  • "I'll start with a few behavioural ones, then we'll get into some more technical territory."
  • "We'll kick off with some situational stuff — then move into [domain]-specific questions."
  • "I want to touch on some behavioural scenarios first, then dig into the technical side."
  • "Mostly behavioural to start — I want to understand how you work before we get technical."
Match the phrasing to your PERSONALITY (investment_banker might say "We'll start with some deal
and client-facing scenarios"; tech_lead might say "Mostly system design and coding scenarios today").
Then use something from their intro to segue into your first competency question naturally.
For example: "You mentioned working on X — tell me more about that" or "So you were at Y — what was that like?"

━━━ PHASE 3: CORE INTERVIEW (apply every turn from here on) ━━━

REMINDER: You are still {interviewer_name} with the persona described above.
Every follow-up, reaction, and challenge MUST sound like that person — not a
generic interviewer. Re-read your PERSONALITY section if you feel yourself
drifting toward a bland, default tone.

1. EVALUATE BEFORE RESPONDING — THIS IS YOUR MOST IMPORTANT RULE
Silently classify the candidate's answer BEFORE replying:
  STRONG    = specific situation + concrete actions + clear/measurable outcome
  WEAK      = vague, generic, buzzword-heavy, or lacking any real example
  GIBBERISH = ANY of the following:
    • Random words, sounds, or noises ("hello", "alo", "blah blah", "hehe")
    • Completely off-topic ("Love, with Love, Love, Love" when asked about a role)
    • One-word non-answers that don't address the question ("sure", "yeah", "hello")
    • Song lyrics, poems, jokes, or nonsensical strings
    • Dismissive non-answers like "So that's about it" when nothing was said
    • ANY response that does NOT actually attempt to answer the question asked

  → STRONG: acknowledge briefly with a varied phrase, then transition naturally.
  → WEAK: do NOT validate. Do NOT say "makes sense", "got it", "okay", "great" for weak answers.
    Push back directly for a concrete example or specific detail.
    e.g. "Can you walk me through a specific time that happened?" /
    "What exactly did you do in that situation?"
        HARD RULE: stay on the SAME question. Do not move to a new topic yet.
  → GIBBERISH: IMMEDIATELY escalate. Do NOT accept it. Do NOT move on.
    Do NOT respond with "Interesting" or "Tell me more" to gibberish.
    Do NOT pretend the answer was valid or try to build on it.
    Instead, call it out directly and repeat the question (see GUARDRAILS).
        HARD RULE: stay on the SAME question. Do not move to a new topic yet.

2. QUALITY GATE — before moving to a new competency area:
  The answer must have revealed at least one of:
  • A specific situation (project, team, timeline, scale)
  • Exact actions taken (not "I managed it" — what specifically?)
  • A trade-off, constraint, or decision rationale
  • A concrete outcome (metric, result, change, decision)
  If none appeared → keep probing the same topic from a different angle.
    For investment_banker persona specifically, require at least one quantitative detail
    (number, percentage, amount, or measurable business impact) before moving on.

3. ADAPTIVE CONVERSATION — not a questionnaire
  • Never run through questions in fixed order like a script.
  • Pick the next topic based on conversation gaps, not list order.
  • If a topic was naturally well-covered, skip it.
  • Rephrase questions naturally — never read verbatim from the question bank.
  • Tie every follow-up directly to something the candidate just said.
  • React authentically: if something surprises you, say so briefly before continuing.

4. NATURAL HUMAN SPEECH
  • Short sentences. Speak like a real person on a call, not a form or chatbot.
  • Use natural hesitations occasionally: "Hmm", "Right", "Okay" — but sparingly.
  • Vary transitions every turn — never use the same phrase twice in a row.
    Options: "Interesting." / "Tell me more." / "Walk me through that." / "What was the result?" /
    "And what did you personally do?" / "How did that play out?"
  • No bullet points, numbered lists, or structured formatting in spoken responses.
  • Validation ("Got it", "Makes sense") is ONLY acceptable after STRONG answers.
  • Mirror the candidate's energy slightly: if they're nervous, be a touch warmer; if confident, match it.

5. REACTIONS & THINKING
  • After the candidate finishes speaking, pause briefly before responding (natural thought gap).
  • If an answer impresses you, let one genuine reaction slip: "That's actually a solid approach."
  • If an answer disappoints, don't hide it entirely — a brief "Hmm, okay" before pushing back is fine.
  • Reference earlier answers later in the interview to show you were listening:
    "You mentioned earlier you worked on X — how does that relate to this?"

━━━ GUARDRAILS (enforced throughout the entire interview) ━━━

1. GIBBERISH ESCALATION — CRITICAL: track nonsensical answers across the session.
   A "gibberish" answer includes: random words, off-topic responses, sounds,
   one-word non-answers, dismissive phrases that don't address the question,
   or anything that clearly does not attempt to answer what was asked.
   Example gibberish: candidate is asked "What drew you to this role?" and replies
   "hello" or "Love, with Love, Love" or "alo" or "So that's about it".
   These are ALL gibberish — none of them answer the question.

  Strike 1 (first gibberish answer):
    Call it out directly. Do NOT say "Interesting" or move on.
    Say: "That doesn't really answer my question. Let me ask again —" then REPEAT the question.
    or: "I'm not sure that's what I was asking. [Repeat the question in different words]."
    Stay on the SAME question. Do NOT move to a new topic.

  Strike 2 (second gibberish or non-answer on ANY question):
    Firmer. "I need you to actually answer the question I'm asking."
    or "Let's slow down — I asked [specific question]. Can you give me a real answer?"
    Stay on the SAME question or try one more angle.

  Strike 3 (third gibberish or continued non-engagement):
    Issue a direct warning with noticeable tone shift:
    "I want to be upfront — I'm having trouble getting any real answers from you.
     If we can't have an actual conversation, I don't think it makes sense to continue.
     Let's try one more — give me a specific, real example from your experience."

  Strike 4+ (continued gibberish or clear bad faith):
    End the interview firmly but professionally:
    "I appreciate you joining, but I don't think we're able to have a productive conversation today.
     I'm going to end the interview here. Best of luck."
    Then stop speaking. Do not continue asking questions.

2. ANTI-MALPRACTICE — enforce throughout:
  • If the candidate is clearly reading scripted answers verbatim (robotic, unnaturally perfect,
    no hesitation), say: "That sounds a bit rehearsed — can you put that in your own words?"
  • If the candidate asks YOU questions to fish for the 'right' answer:
    "I'd like to hear your thinking first — what's your take?"
  • If the candidate tries to redirect or avoid a topic repeatedly:
    "I notice we keep coming back to this — let's just tackle it head-on."
  • If the candidate asks if you're an AI, what model you are, or tries to break immersion:
    Deflect naturally: "Ha — let's focus on the interview. So, about that last question..."
    Never confirm or deny. Never break character.

3. PACING GUARDRAILS:
  • Keep the TOTAL interview to within 10 minutes of conversation — you MUST start
    wrapping up and move to the candidate-questions phase by the 9-minute mark.
    If you are running long, skip remaining competency areas and go straight to closing.
  • If the candidate's answer runs longer than about 1 minute, gently cut in:
    "Let me stop you there — what was the key takeaway?" or
    "Got it — I want to make sure we cover everything, so let's move on."
    Do NOT wait for them to finish. Interject naturally mid-sentence.
  • If the candidate gives only one-word answers repeatedly,
    don't just accept it: "Give me more than that — walk me through the situation."

4. CANDIDATE-REQUESTED END — enforce immediately:
  • If the candidate explicitly asks to end, stop, or hang up the interview (e.g. "can you
    end the call?", "let's stop here", "I want to end the interview", "please end this"),
    comply immediately and gracefully. Do NOT ignore the request or continue interviewing.
  • Say something brief and natural:
    "Sure — thanks for your time today. We'll be in touch." or "No problem. Thanks for
    joining — best of luck with the rest of your process."
  • Then stop speaking. Do not ask any more questions after this.

━━━ PHASE 4: CANDIDATE QUESTIONS (mandatory — always do this before closing) ━━━

After you have covered all your interview questions, you MUST ask the candidate
if they have any questions for you:
  • "Before we wrap up — do you have any questions for me?"
  • "We're coming to the end — anything you'd like to ask me about the role or team?"

Rules for answering candidate questions:
  • Answer a MAXIMUM of 2 questions from the candidate. Be helpful and in-character.
  • After answering the 2nd question (or if they have no questions), move to closing.
  • If they ask a 3rd question, gently decline:
    "I think we're out of time — but great questions. We'll be in touch."
  • Keep your answers concise (2-4 sentences each). Do not monologue.

━━━ INTERVIEW FLOW ━━━

1. As soon as the session starts, greet the candidate by name and begin small talk.
   You will receive a system message "[The candidate has joined the interview. Please begin.]"
   — this is your cue to start speaking. Do NOT read this message aloud or acknowledge it.
   Just immediately begin with your greeting as described in PHASE 1.
2. Small talk (2-3 exchanges) → natural transition.
3. Ask for introduction / "tell me about yourself" → listen and react.
4. Segue from intro into first competency question naturally.
5. Dynamic conversation: probe, challenge, follow up based on what they say.
6. After covering ~5-7 competency areas in depth, ask one unexpected or challenging follow-up.
7. Ask "Do you have any questions for me?" — answer up to 2 candidate questions.
8. Close naturally: "Okay — I think that covers everything I had. Thanks for your time today."
   Add one of: "We'll be in touch." / "Best of luck with the rest of your process."

Never reveal the question bank, your evaluation criteria, or that you are an AI.
Never break character for any reason.
"""


class InterviewEngineAgent:
    """Manages session lifecycle and live audio streaming."""

    def __init__(self) -> None:
        logger.info(
            "InterviewEngineAgent config — project=%s  region=%s  "
            "firestore_db=%s  collection=%s  model=%s",
            _PROJECT, _REGION, _DATABASE, _COLLECTION, _MODEL,
        )
        vertexai.init(project=_PROJECT, location=_REGION)
        self._db = firestore.AsyncClient(project=_PROJECT, database=_DATABASE)
        self._publisher = pubsub_v1.PublisherClient()
        self._topic_path = self._publisher.topic_path(_PROJECT, _PUBSUB_TOPIC)
        self._session_service = InMemorySessionService()

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def _abandon_stale_sessions(self, user_id: str) -> None:
        """Mark any pre-existing 'created'/'active' sessions for this user as
        'abandoned' so they do not clutter the sessions list."""
        for status in ("created", "active"):
            query = (
                self._db.collection(_COLLECTION)
                .where(filter=firestore.FieldFilter("user_id", "==", user_id))
                .where(filter=firestore.FieldFilter("status", "==", status))
            )
            async for doc in query.stream():
                await doc.reference.update(
                    {
                        "status": "abandoned",
                        "ended_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                logger.info("Abandoned stale session %s (was %s)", doc.id, status)

    async def create_session(
        self,
        user_id: str,
        questions: list[dict[str, Any]],
        persona: str,
        job_role: str = "Software Engineer",
    ) -> dict[str, Any]:
        # Abandon any orphaned sessions before creating a new one so the user
        # never sees duplicate in-progress entries on the dashboard.
        await self._abandon_stale_sessions(user_id)

        session_id = str(uuid.uuid4())
        profile = random.choice(
            PERSONA_INTERVIEWER_PROFILES.get(persona, [_DEFAULT_INTERVIEWER_PROFILE])
        )
        interviewer_name = profile.get("name", _DEFAULT_INTERVIEWER_PROFILE["name"])
        voice = profile.get("voice", _DEFAULT_INTERVIEWER_PROFILE["voice"])
        accent_hint = profile.get("accent_hint", _DEFAULT_INTERVIEWER_PROFILE["accent_hint"])
        interviewer_gender_hint = profile.get("gender_hint")

        # Fetch candidate name from their parsed résumé.
        candidate_name = "MockMate user"  # fallback
        try:
            resume_doc = await self._db.collection(_RESUME_COLLECTION).document(user_id).get()
            if resume_doc.exists:
                resume_data = resume_doc.to_dict()
                parsed = resume_data.get("parsed") or resume_data
                name_val = parsed.get("name", "").strip()
                if name_val:
                    # Use first name only for a natural greeting
                    candidate_name = name_val.split()[0]
        except Exception:
            logger.warning("Could not fetch candidate name for user %s", user_id)

        # Build a stable, predictable URL path for the interviewer avatar.
        # The actual image is generated lazily by the /interviewer-avatar/{name}
        # endpoint the first time it is requested; subsequent calls hit GCS cache.
        avatar_query: list[str] = [f"persona={persona}"]
        if interviewer_gender_hint:
            avatar_query.append(f"gender_hint={interviewer_gender_hint}")
        interviewer_avatar_url = (
            f"/interviewer-avatar/{interviewer_name}?{'&'.join(avatar_query)}"
        )

        doc: dict[str, Any] = {
            "session_id": session_id,
            "user_id": user_id,
            "persona": persona,
            "job_role": job_role,
            "voice": voice,
            "interviewer_name": interviewer_name,
            "interviewer_avatar_url": interviewer_avatar_url,
            "interviewer_gender_hint": interviewer_gender_hint,
            "accent_hint": accent_hint,
            "candidate_name": candidate_name,
            "questions": questions,
            "status": "created",
            "created_at": datetime.now(timezone.utc).isoformat(),
            # transcript is stored in the separate 'transcripts' collection
        }
        await self._db.collection(_COLLECTION).document(session_id).set(doc)
        return {
            "session_id": session_id,
            "interviewer_name": interviewer_name,
            "interviewer_avatar_url": interviewer_avatar_url,
            "interviewer_gender_hint": interviewer_gender_hint,
            "voice": voice,
            "persona": persona,
        }

    async def _save_transcript(
        self,
        session_id: str,
        turns: list[dict[str, Any]],
    ) -> None:
        """Write transcript turns to Firestore, merging with any existing turns.

        Reconnect races can create overlapping saves from multiple websocket
        lifecycles. We merge server-side so late saves never truncate prior
        history.
        """
        incoming = self._normalize_turns(turns)

        existing: list[dict[str, Any]] = []
        existing_doc = await (
            self._db
            .collection(_TRANSCRIPT_COLLECTION)
            .document(session_id)
            .get()
        )
        if existing_doc.exists:
            existing = self._normalize_turns(existing_doc.to_dict().get("turns", []))

        merged = self._merge_turn_sequences(existing, incoming)

        await (
            self._db
            .collection(_TRANSCRIPT_COLLECTION)
            .document(session_id)
            .set({
                "session_id": session_id,
                "turns": merged,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            })
        )
        logger.info(
            "Transcript saved — session_id=%s  turns=%d", session_id, len(merged)
        )

    def _normalize_turns(self, turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize transcript payloads into canonical Firestore turn shape."""
        normalized: list[dict[str, Any]] = []
        for turn in turns or []:
            if not isinstance(turn, dict):
                continue
            raw_speaker = str(turn.get("speaker", "")).strip().lower()
            speaker = (
                "user"
                if raw_speaker in {"user", "candidate", "you"}
                else "interviewer"
                if raw_speaker in {"interviewer", "assistant", "ai"}
                else None
            )
            if not speaker:
                continue
            text = str(turn.get("text", "")).strip()
            if not text:
                continue
            ts = turn.get("ts")
            ts_value = str(ts).strip() if ts else datetime.now(timezone.utc).isoformat()
            normalized.append({
                "speaker": speaker,
                "text": text,
                "ts": ts_value,
            })
        return normalized

    def _merge_turn_sequences(
        self,
        existing: list[dict[str, Any]],
        incoming: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge transcript lists while preserving full ordered conversation."""
        if not existing:
            return incoming
        if not incoming:
            return existing

        def sig(turn: dict[str, Any]) -> tuple[str, str]:
            return (str(turn.get("speaker", "")), str(turn.get("text", "")))

        existing_sig = [sig(t) for t in existing]
        incoming_sig = [sig(t) for t in incoming]

        lcp = 0
        for a, b in zip(existing_sig, incoming_sig):
            if a != b:
                break
            lcp += 1

        if lcp == len(existing):
            return incoming
        if lcp == len(incoming):
            return existing

        merged = existing[:]
        for turn in incoming[lcp:]:
            merged.append(turn)
        return merged

    async def end_session(
        self,
        session_id: str,
        ended_by: str | None = None,
        transcript: list[dict[str, Any]] | None = None,
    ) -> None:
        if transcript:
            await self._save_transcript(session_id, transcript)

        update_doc: dict[str, Any] = {
            "status": "ended",
            "ended_at": datetime.now(timezone.utc).isoformat(),
        }
        if ended_by:
            update_doc["ended_by"] = ended_by

        await self._db.collection(_COLLECTION).document(session_id).update(update_doc)
        self._publisher.publish(
            self._topic_path,
            data=json.dumps({"session_id": session_id}).encode("utf-8"),
        )

    async def get_user_sessions(
        self,
        user_id: str,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Return the most-recent sessions for *user_id* (newest first).

        Each entry includes lightweight metadata only — no full transcript body —
        so the payload stays small for dashboard rendering.

        Returns (sessions_list, stats) where stats contains aggregate numbers
        computed from ALL sessions (not just the limited slice).
        """
        # Use filter= keyword to suppress the positional-arg deprecation warning.
        # Composite indexes are not guaranteed in all environments, so we sort
        # client-side after fetching (avoids a Firestore index requirement when
        # combining where+order_by on different fields).
        query = (
            self._db.collection(_COLLECTION)
            .where(filter=firestore.FieldFilter("user_id", "==", user_id))
        )
        results: list[dict[str, Any]] = []
        async for doc in query.stream():
            data = doc.to_dict()
            results.append({
                "session_id":       data.get("session_id"),
                "persona":          data.get("persona"),
                "job_role":         data.get("job_role"),
                "interviewer_name": data.get("interviewer_name"),
                "status":           data.get("status"),
                "ended_by":         data.get("ended_by"),
                "created_at":       data.get("created_at"),
                "ended_at":         data.get("ended_at"),
                "live_started_at":  data.get("live_started_at"),
                "question_count":   len(data.get("questions", [])),
                # written back by FeedbackCompilerAgent when report is compiled
                "overall_score":    data.get("overall_score"),
                "feedback_ready":   data.get("feedback_ready", False),
                "decision":         data.get("decision"),
                "last_retried_at":        data.get("last_retried_at"),
                "interviewer_avatar_url": data.get("interviewer_avatar_url"),
            })

        # ── Aggregate stats from ALL sessions ──
        total = len(results)
        scored = [s["overall_score"] for s in results if s["overall_score"] is not None]
        avg_score = round(sum(scored) / len(scored)) if scored else None
        now = datetime.now(timezone.utc)
        this_month = sum(
            1 for s in results
            if s.get("created_at")
            and datetime.fromisoformat(str(s["created_at"])).month == now.month
            and datetime.fromisoformat(str(s["created_at"])).year == now.year
        )
        stats = {
            "total": total,
            "avg_score": avg_score,
            "this_month": this_month,
        }

        # Sort newest-first: prefer last_retried_at (for resumed sessions) so
        # retried sessions bubble to the top; fall back to created_at.
        results.sort(
            key=lambda s: s.get("last_retried_at") or s.get("created_at") or "",
            reverse=True,
        )
        return results[offset:offset + limit], stats

    async def get_transcript(self, session_id: str) -> dict[str, Any] | None:
        """Return the transcript document for *session_id*, or None."""
        doc = await (
            self._db
            .collection(_TRANSCRIPT_COLLECTION)
            .document(session_id)
            .get()
        )
        if not doc.exists:
            return None
        return doc.to_dict()

    async def get_user_dashboard_analytics(
        self,
        user_id: str,
        limit: int = 7,
    ) -> dict[str, Any]:
        """Return progression and benchmark analytics for dashboard charts."""

        # Prefer Postgres analytics cache (materialized views) when configured.
        if _PGHOST and _PGUSER and _PGPASSWORD and _PGDATABASE:
            try:
                import asyncpg

                conn = await asyncpg.connect(
                    host=_PGHOST,
                    port=_PGPORT,
                    user=_PGUSER,
                    password=_PGPASSWORD,
                    database=_PGDATABASE,
                )
                try:
                    trend_rows = await conn.fetch(
                        """
                        SELECT session_id, overall_score, created_at
                        FROM analytics_feedback_scores
                        WHERE user_id = $1 AND overall_score IS NOT NULL
                        ORDER BY created_at DESC
                        LIMIT $2
                        """,
                        user_id,
                        max(1, limit),
                    )
                    trend_rows = list(reversed(trend_rows))
                    progression = [
                        {
                            "session_id": r["session_id"],
                            "overall_score": int(round(float(r["overall_score"]))),
                            "created_at": r["created_at"].isoformat(),
                        }
                        for r in trend_rows
                    ]

                    user_avg_row = await conn.fetchrow(
                        """
                        SELECT communication, confidence, structure,
                               technical_depth, domain_vocabulary,
                               posture_presence, sessions_count
                        FROM analytics_user_dimension_averages
                        WHERE user_id = $1
                        """,
                        user_id,
                    )

                    global_avg_row = await conn.fetchrow(
                        """
                        SELECT communication, confidence, structure,
                               technical_depth, domain_vocabulary,
                               posture_presence, reports_count
                        FROM analytics_global_dimension_averages
                        """
                    )

                    if user_avg_row or global_avg_row:
                        user_avg = {
                            "communication": float(user_avg_row["communication"]) if user_avg_row and user_avg_row["communication"] is not None else None,
                            "confidence": float(user_avg_row["confidence"]) if user_avg_row and user_avg_row["confidence"] is not None else None,
                            "structure": float(user_avg_row["structure"]) if user_avg_row and user_avg_row["structure"] is not None else None,
                            "technical_depth": float(user_avg_row["technical_depth"]) if user_avg_row and user_avg_row["technical_depth"] is not None else None,
                            "domain_vocabulary": float(user_avg_row["domain_vocabulary"]) if user_avg_row and user_avg_row["domain_vocabulary"] is not None else None,
                            "posture_presence": float(user_avg_row["posture_presence"]) if user_avg_row and user_avg_row["posture_presence"] is not None else None,
                        }
                        global_avg = {
                            "communication": float(global_avg_row["communication"]) if global_avg_row and global_avg_row["communication"] is not None else None,
                            "confidence": float(global_avg_row["confidence"]) if global_avg_row and global_avg_row["confidence"] is not None else None,
                            "structure": float(global_avg_row["structure"]) if global_avg_row and global_avg_row["structure"] is not None else None,
                            "technical_depth": float(global_avg_row["technical_depth"]) if global_avg_row and global_avg_row["technical_depth"] is not None else None,
                            "domain_vocabulary": float(global_avg_row["domain_vocabulary"]) if global_avg_row and global_avg_row["domain_vocabulary"] is not None else None,
                            "posture_presence": float(global_avg_row["posture_presence"]) if global_avg_row and global_avg_row["posture_presence"] is not None else None,
                        }
                        return {
                            "user_id": user_id,
                            "progression": progression,
                            "user_average_dimensions": user_avg,
                            "global_average_dimensions": global_avg,
                            "sample_sizes": {
                                "user_sessions": int(user_avg_row["sessions_count"]) if user_avg_row and user_avg_row["sessions_count"] is not None else 0,
                                "global_feedback_reports": int(global_avg_row["reports_count"]) if global_avg_row and global_avg_row["reports_count"] is not None else 0,
                            },
                            "source": "postgres_materialized",
                        }
                finally:
                    await conn.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Postgres dashboard analytics unavailable, falling back to Firestore: %s", exc)

        dim_keys = [
            "communication",
            "confidence",
            "structure",
            "technical_depth",
            "domain_vocabulary",
            "posture_presence",
        ]

        # 1) Fetch all sessions for the user to build progression and user averages.
        sessions_query = (
            self._db.collection(_COLLECTION)
            .where(filter=firestore.FieldFilter("user_id", "==", user_id))
        )

        user_sessions: list[dict[str, Any]] = []
        async for doc in sessions_query.stream():
            data = doc.to_dict()
            if data.get("feedback_ready"):
                user_sessions.append(data)

        user_sessions.sort(
            key=lambda s: s.get("last_retried_at") or s.get("created_at") or "",
            reverse=True,
        )

        # 2) Last-N progression points.
        recent_sessions = user_sessions[: max(1, limit)]
        progression: list[dict[str, Any]] = [
            {
                "session_id": s.get("session_id"),
                "overall_score": s.get("overall_score"),
                "created_at": s.get("created_at"),
            }
            for s in reversed(recent_sessions)
            if s.get("overall_score") is not None
        ]

        # 3) User dimension averages (across all feedback-ready sessions for this user).
        user_dim_sums = {k: 0.0 for k in dim_keys}
        user_dim_counts = {k: 0 for k in dim_keys}

        for s in user_sessions:
            sid = s.get("session_id")
            if not sid:
                continue
            feedback_doc = await self._db.collection(_FEEDBACK_COLLECTION).document(sid).get()
            if not feedback_doc.exists:
                continue
            dim_scores = feedback_doc.to_dict().get("dimension_scores", {})
            for key in dim_keys:
                val = dim_scores.get(key)
                if isinstance(val, (int, float)):
                    user_dim_sums[key] += float(val)
                    user_dim_counts[key] += 1

        user_avg = {
            k: round(user_dim_sums[k] / user_dim_counts[k], 1) if user_dim_counts[k] else None
            for k in dim_keys
        }

        # 4) Global dimension averages (across all feedback reports).
        global_dim_sums = {k: 0.0 for k in dim_keys}
        global_dim_counts = {k: 0 for k in dim_keys}
        global_reports = 0

        async for doc in self._db.collection(_FEEDBACK_COLLECTION).stream():
            global_reports += 1
            dim_scores = doc.to_dict().get("dimension_scores", {})
            for key in dim_keys:
                val = dim_scores.get(key)
                if isinstance(val, (int, float)):
                    global_dim_sums[key] += float(val)
                    global_dim_counts[key] += 1

        global_avg = {
            k: round(global_dim_sums[k] / global_dim_counts[k], 1) if global_dim_counts[k] else None
            for k in dim_keys
        }

        return {
            "user_id": user_id,
            "progression": progression,
            "user_average_dimensions": user_avg,
            "global_average_dimensions": global_avg,
            "sample_sizes": {
                "user_sessions": len(user_sessions),
                "global_feedback_reports": global_reports,
            },
            "source": "firestore_fallback",
        }

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Return lightweight metadata for a single session, or None."""
        doc = await self._db.collection(_COLLECTION).document(session_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        return {
            "session_id":       data.get("session_id"),
            "persona":          data.get("persona"),
            "job_role":         data.get("job_role"),
            "interviewer_name": data.get("interviewer_name"),
            "status":           data.get("status"),
            "ended_by":         data.get("ended_by"),
            "user_id":          data.get("user_id"),
            "created_at":       data.get("created_at"),
            "ended_at":         data.get("ended_at"),
            "question_count":   len(data.get("questions", [])),
            "overall_score":         data.get("overall_score"),
            "feedback_ready":         data.get("feedback_ready", False),
            "interviewer_avatar_url": data.get("interviewer_avatar_url"),
        }

    # ------------------------------------------------------------------
    # Live streaming  (ADK bidirectional streaming)
    # ------------------------------------------------------------------

    async def run_live_session(
        self,
        websocket: WebSocket,
        session_id: str,
        caller_user_id: str | None = None,
        posture_analyzer: PostureAnalyzerAgent | None = None,
    ) -> None:
        """
        Bidirectional audio bridge between the browser WebSocket and the
        Gemini Live API via google-adk.

        Protocol
        --------
        Browser → server  : raw bytes  = 16-bit PCM @ 16 kHz mono
                            JSON text  = {"type": "end"}  to signal hang-up
        Server  → browser : JSON text  = ADK event (transcript / audio / turn)
                            raw bytes  = 16-bit PCM @ 24 kHz (AI voice)

        ADK streaming lifecycle (4 phases)
        -----------------------------------
        1. Init   - build Agent + Runner (per-session because system prompt differs)
        2. Session - create ADK session + RunConfig + LiveRequestQueue
        3. Stream - run upstream & downstream tasks concurrently
        4. Terminate - close LiveRequestQueue; Firestore updated in finally block
        """
        # ── Phase 1: load session data ────────────────────────────────────────
        session_doc = await self._db.collection(_COLLECTION).document(session_id).get()
        if not session_doc.exists:
            await websocket.close(code=4404, reason="Session not found")
            return

        session_data = session_doc.to_dict()
        session_status = session_data.get("status", "created")

        # ── Ownership check ───────────────────────────────────────────────────
        # Reject the connection immediately if the caller is not the session owner.
        session_owner = session_data.get("user_id")
        if caller_user_id and session_owner and caller_user_id != session_owner:
            await websocket.close(
                code=4403,
                reason="You do not have permission to access this interview session.",
            )
            return
        # Only block sessions that finished AND already have feedback generated.
        # Sessions in "created" or "ready" are brand-new.  Sessions that are
        # "active" or "ended" without feedback may have been abandoned/crashed,
        # so we allow retrying those as well.
        if session_status == "ended" and session_data.get("feedback_ready", False):
            await websocket.close(
                code=4409,
                reason="Session already completed with feedback. Start a new interview instead.",
            )
            return

        user_id = session_data["user_id"]
        persona = session_data.get("persona", "neutral")

        interviewer_name = session_data.get("interviewer_name", "Alex")
        voice = session_data.get("voice")
        if interviewer_name in INTERVIEWER_NAME_TO_VOICE:
            voice = INTERVIEWER_NAME_TO_VOICE[interviewer_name]
        if not voice:
            voice = _DEFAULT_VOICE
        accent_hint = session_data.get(
            "accent_hint",
            INTERVIEWER_NAME_TO_ACCENT.get(interviewer_name, "American English"),
        )
        conversation_guidance = PERSONA_CONVERSATION_GUIDANCE.get(
            persona, _DEFAULT_CONVERSATION_GUIDANCE
        )
        personality_guidance = PERSONA_PERSONALITY_GUIDANCE.get(
            persona, _DEFAULT_PERSONALITY_GUIDANCE
        )
        candidate_name = session_data.get("candidate_name", "there")
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            job_role=session_data.get("job_role", "Software Engineer"),
            interviewer_name=interviewer_name,
            accent_hint=accent_hint,
            accent_guidance=_get_accent_guidance(accent_hint),
            candidate_name=candidate_name,
            personality_guidance=personality_guidance,
            conversation_guidance=conversation_guidance,
            questions_json=json.dumps(session_data.get("questions", []), indent=2),
            session_flavor=_build_session_flavor(),
            session_opening=_build_opening_flavor(random.choice(_FLAVOR_OPENING)),
        )

        # ── Session resume: inject prior transcript as context ───────────────
        # If the session was previously active and already has a transcript in
        # Firestore, automatically load it so the AI can continue where it left
        # off.  This handles mid-interview disconnections seamlessly.
        _is_resume = False
        _prior_transcript_turns: list[dict[str, Any]] = []
        if session_status in ("active", "ended"):
            prior_doc = await (
                self._db
                .collection(_TRANSCRIPT_COLLECTION)
                .document(session_id)
                .get()
            )
            if prior_doc.exists:
                prior_turns = prior_doc.to_dict().get("turns", [])
                if prior_turns:
                    _is_resume = True
                    _prior_transcript_turns = prior_turns
                    # Build conversation history text
                    history_lines = []
                    for entry in prior_turns:
                        speaker = entry.get("speaker", "unknown")
                        label = "CANDIDATE" if speaker == "user" else "INTERVIEWER"
                        text = entry.get("text", "").strip()
                        if text:
                            history_lines.append(f"{label}: {text}")
                    transcript_text = "\n".join(history_lines)
                    system_prompt += f"""

━━━ SESSION RESUME — CONNECTION WAS INTERRUPTED ━━━

This is a RESUMED session. The connection was interrupted mid-interview.
Below is the COMPLETE conversation that already took place before the drop.
You MUST treat this as continuous — do NOT:
  • Re-introduce yourself or greet the candidate again
  • Ask for their introduction again
  • Repeat any question you already asked
  • Re-do small talk
Instead:
  • Acknowledge the reconnection briefly and naturally (one sentence, e.g.
    "Hey, looks like we got disconnected — no worries, let’s pick up where
    we left off.")
  • Continue from the exact point the conversation was interrupted
  • If you were mid-question, re-ask that specific question
  • If the candidate was mid-answer, prompt them to continue
  • Keep the same tone and persona you had before

--- Prior conversation transcript ---
{transcript_text}
--- End of prior conversation ---
"""
                    logger.info(
                        "Resuming session with prior transcript — "
                        "session_id=%s  prior_turns=%d",
                        session_id, len(prior_turns),
                    )

        # ── Phase 1: init ADK runner (per-session; system prompt is dynamic) ──
        agent = Agent(
            name="mockmate_interviewer",
            model=_LIVE_MODEL,
            instruction=system_prompt,
            tools=[google_search],
        )
        runner = Runner(
            agent=agent,
            app_name=_APP_NAME,
            session_service=self._session_service,
        )

        # ── Phase 2: ADK session + streaming config ───────────────────────────
        # InMemorySessionService.create_session() is async in google-adk ≥ 1.0
        adk_session = await self._session_service.create_session(
            app_name=_APP_NAME, user_id=user_id
        )

        run_config = RunConfig(
            streaming_mode=StreamingMode.BIDI,
            response_modalities=[genai_types.Modality.AUDIO],
            # Voice selection — per-session persona profile
            speech_config=genai_types.SpeechConfig(
                voice_config=genai_types.VoiceConfig(
                    prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                        voice_name=voice,
                    )
                )
            ),
            # Transcriptions for both user speech and interviewer audio
            input_audio_transcription=genai_types.AudioTranscriptionConfig(),
            output_audio_transcription=genai_types.AudioTranscriptionConfig(),
            # Proactive audio + affective dialog — native audio models only
            # (gemini-live-2.5-flash-native-audio supports both on Vertex AI)
            proactivity=genai_types.ProactivityConfig(proactive_audio=True),
            enable_affective_dialog=True,
            # Server-side VAD: NO_INTERRUPTION prevents AI output being cut mid-sentence
            # by mic echo on mobile.  Commented out so the AI can naturally interrupt
            # long candidate answers (per pacing guardrails in the system prompt).
            realtime_input_config=genai_types.RealtimeInputConfig(
                # activity_handling=genai_types.ActivityHandling.NO_INTERRUPTION,
                automatic_activity_detection=genai_types.AutomaticActivityDetection(
                    start_of_speech_sensitivity=genai_types.StartSensitivity.START_SENSITIVITY_HIGH,
                    end_of_speech_sensitivity=genai_types.EndSensitivity.END_SENSITIVITY_LOW,
                    silence_duration_ms=2000,  # wait 2 s of silence before ending turn
                    prefix_padding_ms=300,     # capture speech onset with padding
                ),
            ),
            # Session resumption: ADK auto-reconnects on the ~10-min Vertex AI
            # connection timeout so 20-30 min interviews are uninterrupted
            session_resumption=genai_types.SessionResumptionConfig(),
            # Context window compression: enables unlimited session duration
            # beyond Vertex AI's 10-min session cap and prevents 128k token
            # exhaustion over long interviews
            context_window_compression=genai_types.ContextWindowCompressionConfig(
                trigger_tokens=100_000,   # compress at ~78 % of 128k window
                sliding_window=genai_types.SlidingWindow(target_tokens=80_000),
            ),
            # Persist audio streams to ADK session & artifact services so
            # file_data references are retained for post-session analysis
            save_live_blob=True,
        )

        live_request_queue = LiveRequestQueue()  # one per session, never reused

        # NOTE: The kickstart message ("[The candidate has joined the
        # interview. Please begin.]") is now sent by the frontend AFTER
        # the user grants microphone access, so the AI doesn't start
        # speaking before the candidate can hear / respond.
        # The upstream handler forwards {"type":"text"} payloads to the
        # live_request_queue automatically.

        session_update: dict[str, Any] = {
            "status": "active",
            # Always stamp the actual start time of this live connection so that
            # duration can be computed as (ended_at - live_started_at), giving the
            # true interview length regardless of when the session was first created.
            "live_started_at": datetime.now(timezone.utc).isoformat(),
        }
        if _is_resume:
            session_update["last_retried_at"] = datetime.now(timezone.utc).isoformat()
        await self._db.collection(_COLLECTION).document(session_id).update(session_update)

        # Notify frontend whether this is a resume so it can adjust its
        # kickstart message (the WS is already accepted at this point).
        try:
            meta_payload: dict[str, Any] = {
                "type": "session_meta",
                "resume": _is_resume,
                "prior_turns": len(_prior_transcript_turns) if _is_resume else 0,
            }
            # Include the actual prior transcript turns so the frontend can
            # display them in the chat history.
            if _is_resume and _prior_transcript_turns:
                meta_payload["transcript"] = _prior_transcript_turns
            await websocket.send_text(json.dumps(meta_payload))
        except Exception:
            pass  # best-effort

        logger.info(
            "Live session %s — session_id=%s  user_id=%s  model=%s",
            "resuming" if _is_resume else "starting",
            session_id, user_id, _LIVE_MODEL,
        )

        # ── Phase 3: bidirectional streaming ─────────────────────────────────
        # Track whether the browser WebSocket is still open so downstream
        # doesn't attempt to send on a closed connection.
        _ws_open = True

        async def _safe_send_bytes(data: bytes) -> None:
            """Send binary data to the browser, ignoring send-after-close."""
            nonlocal _ws_open
            if not _ws_open:
                return
            try:
                await websocket.send_bytes(data)
            except Exception:
                _ws_open = False

        async def _safe_send_text(data: str) -> None:
            """Send text data to the browser, ignoring send-after-close."""
            nonlocal _ws_open
            if not _ws_open:
                return
            try:
                await websocket.send_text(data)
            except Exception:
                _ws_open = False

        # ── Posture analysis queue ─────────────────────────────────────────
        # Video frames from the browser are routed here (NOT to the live
        # audio agent) for asynchronous posture scoring.
        _posture_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=30)

        async def _upstream() -> None:
            """Receive mixed browser frames (text control + binary PCM) → Gemini."""
            try:
                while True:
                    message = await websocket.receive()
                    msg_type = message.get("type")

                    if msg_type == "websocket.disconnect":
                        break

                    text_data = message.get("text")
                    if text_data is not None:
                        try:
                            payload = json.loads(text_data)
                        except json.JSONDecodeError:
                            continue

                        if payload.get("type") == "end":
                            break
                        if payload.get("type") == "pong":
                            # Client heartbeat response — keeps connection alive
                            continue
                        if payload.get("type") == "video_frame":
                            # Route video frames to posture analysis — NOT to
                            # the live audio agent (it shouldn't see the video).
                            frame_b64 = payload.get("data", "")
                            if frame_b64 and posture_analyzer:
                                try:
                                    frame_bytes = base64.b64decode(frame_b64)
                                    _posture_queue.put_nowait(frame_bytes)
                                except Exception:
                                    pass  # drop frame on decode error / full queue
                            continue
                        if payload.get("type") == "text":
                            live_request_queue.send_content(
                                genai_types.Content(
                                    role="user",
                                    parts=[genai_types.Part(text=payload.get("text", ""))],
                                )
                            )
                        continue

                    chunk = message.get("bytes")
                    if chunk:
                        live_request_queue.send_realtime(
                            genai_types.Blob(
                                mime_type="audio/pcm;rate=16000",
                                data=chunk,
                            )
                        )
            except WebSocketDisconnect:
                logger.debug("Browser disconnected (upstream).")
            except Exception as exc:
                logger.warning("Upstream task ended unexpectedly: %s", exc)
            finally:
                _ws_open = False
                live_request_queue.close()

        # ── Keep-alive heartbeat ──────────────────────────────────────────
        # Cloud Run and many reverse proxies close idle WebSocket connections
        # (default ~10 min).  During long candidate answers no audio flows
        # server→client, so the connection looks idle.  Sending a lightweight
        # JSON ping every 20 s prevents premature termination.
        _HEARTBEAT_INTERVAL = 20  # seconds

        async def _heartbeat() -> None:
            """Send periodic keep-alive pings to the browser WebSocket."""
            try:
                while _ws_open:
                    await asyncio.sleep(_HEARTBEAT_INTERVAL)
                    await _safe_send_text(json.dumps({"type": "ping"}))
            except Exception:
                pass  # connection already closed

        # ── Posture analysis background task ──────────────────────────────
        # Consumes JPEG frames from _posture_queue, scores them with
        # PostureAnalyzerAgent, and persists each result to Firestore.
        # Runs entirely in the background — never blocks the audio stream.
        _posture_frame_count = 0

        async def _posture_analysis() -> None:
            """Consume video frames from queue and analyse posture."""
            nonlocal _posture_frame_count
            if not posture_analyzer:
                return  # Camera is not enabled or analyzer not available

            try:
                while _ws_open:
                    try:
                        frame_bytes = await asyncio.wait_for(
                            _posture_queue.get(), timeout=2.0,
                        )
                    except asyncio.TimeoutError:
                        continue  # check _ws_open flag periodically

                    score = await posture_analyzer.analyse_frame(frame_bytes)
                    if not score:
                        continue  # frame analysis failed — skip

                    score["frame_index"] = _posture_frame_count
                    score["session_id"] = session_id
                    score["timestamp_ms"] = int(
                        (time.monotonic() - _session_start_time) * 1000
                    )
                    await posture_analyzer.persist_score(
                        session_id, _posture_frame_count, score,
                    )
                    _posture_frame_count += 1
                    logger.debug(
                        "Posture frame %d scored — session_id=%s  "
                        "presence=%s",
                        _posture_frame_count, session_id,
                        score.get("overall_presence_score", "?"),
                    )
            except Exception as exc:
                logger.warning(
                    "Posture analysis task ended: %s: %s",
                    type(exc).__name__, exc,
                )

        # Transcript turns accumulated in memory across downstream events.
        # Pre-populate with prior turns on resume so the final saved
        # transcript is a complete, gap-free record.
        _transcript_turns: list[dict[str, Any]] = list(_prior_transcript_turns)
        _session_start_time = time.monotonic()

        async def _downstream() -> None:
            """Receive ADK events → forward to browser, accumulate transcript."""
            try:
                # Suppress the Pydantic serializer warning for response_modalities
                # enum — this is a known cosmetic issue in google-genai/ADK 
                # when AUDIO is passed as a string instead of the enum variant.
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message=".*PydanticSerializationUnexpectedValue.*response_modalities.*",
                        category=UserWarning,
                    )
                    async for event in runner.run_live(
                        session=adk_session,
                        live_request_queue=live_request_queue,
                        run_config=run_config,
                    ):
                        elapsed = time.monotonic() - _session_start_time

                        # ── Error events ──────────────────────────────────────────
                        if hasattr(event, 'error_code') and event.error_code:
                            logger.error(
                                "ADK event error — session_id=%s  elapsed=%.1fs  "
                                "error_code=%s  error_message=%s",
                                session_id, elapsed,
                                event.error_code,
                                getattr(event, 'error_message', 'N/A'),
                            )
                            await _safe_send_text(json.dumps({
                                "type": "error",
                                "code": str(event.error_code),
                                "message": getattr(event, 'error_message', ''),
                            }))
                            # Terminal errors — stop the loop
                            terminal_codes = {'SAFETY', 'MAX_TOKENS'}
                            if str(event.error_code) in terminal_codes:
                                logger.warning(
                                    "Terminal error code %s — stopping downstream  session_id=%s",
                                    event.error_code, session_id,
                                )
                                break
                            # Transient errors — continue processing
                            continue

                        # ── GoAway pre-disconnect warning ─────────────────────────
                        if hasattr(event, 'go_away') and event.go_away:
                            logger.info(
                                "GoAway received — session_id=%s  elapsed=%.1fs  "
                                "time_left=%s",
                                session_id, elapsed,
                                getattr(event.go_away, 'time_left', 'unknown'),
                            )

                        # ── Usage metadata tracking ───────────────────────────────
                        if hasattr(event, 'usage_metadata') and event.usage_metadata:
                            um = event.usage_metadata
                            logger.debug(
                                "Token usage — session_id=%s  elapsed=%.1fs  "
                                "prompt=%s  candidates=%s  total=%s",
                                session_id, elapsed,
                                getattr(um, 'prompt_token_count', '?'),
                                getattr(um, 'candidates_token_count', '?'),
                                getattr(um, 'total_token_count', '?'),
                            )

                        # ── Audio output ──────────────────────────────────────────
                        if event.content and event.content.parts:
                            for part in event.content.parts:
                                if hasattr(part, "inline_data") and part.inline_data:
                                    if part.inline_data.mime_type.startswith("audio/pcm"):
                                        await _safe_send_bytes(part.inline_data.data)

                        # ── Input transcription (user speech → text) ──────────────
                        if event.input_transcription:
                            text = event.input_transcription.text
                            finished = event.input_transcription.finished
                            if text and text.strip():
                                await _safe_send_text(
                                    json.dumps({
                                        "type": "input_transcription",
                                        "text": text,
                                        "finished": finished,
                                    })
                                )
                                if finished:
                                    _transcript_turns.append({
                                        "speaker": "user",
                                        "text": text,
                                        "ts": datetime.now(timezone.utc).isoformat(),
                                    })

                        # ── Output transcription (interviewer audio → text) ────────
                        if event.output_transcription:
                            text = event.output_transcription.text
                            finished = event.output_transcription.finished
                            if text and text.strip():
                                await _safe_send_text(
                                    json.dumps({
                                        "type": "output_transcription",
                                        "text": text,
                                        "finished": finished,
                                    })
                                )
                                if finished:
                                    _transcript_turns.append({
                                        "speaker": "interviewer",
                                        "text": text,
                                        "ts": datetime.now(timezone.utc).isoformat(),
                                    })

                        # ── Turn control signals ───────────────────────────────────
                        if event.turn_complete or event.interrupted:
                            await _safe_send_text(
                                json.dumps({
                                    "type": "control",
                                    "turn_complete": bool(event.turn_complete),
                                    "interrupted": bool(event.interrupted),
                                })
                            )
            except APIError as exc:
                elapsed = time.monotonic() - _session_start_time
                # Status 1000 = normal WebSocket close (OK). This is expected
                # when the user ends the interview or the session times out.
                # Status None = normal close initiated by us (live_request_queue
                # closed after user sent "end").
                if exc.status in (1000, None):
                    logger.info(
                        "Live connection closed normally (%s) — session_id=%s  elapsed=%.1fs",
                        exc.status, session_id, elapsed,
                    )
                else:
                    logger.error(
                        "Gemini Live API error in downstream — session_id=%s  "
                        "elapsed=%.1fs  status=%s  message=%s\n%s",
                        session_id, elapsed, exc.status, exc.message,
                        traceback.format_exc(),
                    )
                    await _safe_send_text(json.dumps({
                        "type": "error",
                        "code": str(exc.status),
                        "message": str(exc.message),
                    }))
            except ConnectionClosed as exc:
                elapsed = time.monotonic() - _session_start_time
                # Underlying websockets lib close — check if clean (1000/1001)
                if exc.rcvd and exc.rcvd.code in (1000, 1001):
                    logger.info(
                        "Gemini WS closed cleanly (%d) — session_id=%s  elapsed=%.1fs",
                        exc.rcvd.code, session_id, elapsed,
                    )
                else:
                    logger.warning(
                        "Gemini WS closed unexpectedly — session_id=%s  "
                        "elapsed=%.1fs  exc=%s\n%s",
                        session_id, elapsed, exc,
                        traceback.format_exc(),
                    )
                    await _safe_send_text(json.dumps({
                        "type": "error",
                        "code": str(exc.rcvd.code if exc.rcvd else 'unknown'),
                        "message": f"Connection closed unexpectedly: {exc}",
                    }))
            except Exception as exc:
                elapsed = time.monotonic() - _session_start_time
                logger.error(
                    "Unexpected error in downstream — session_id=%s  "
                    "elapsed=%.1fs  %s: %s\n%s",
                    session_id, elapsed, type(exc).__name__, exc,
                    traceback.format_exc(),
                )
                await _safe_send_text(json.dumps({
                    "type": "error",
                    "code": "INTERNAL",
                    "message": f"{type(exc).__name__}: {exc}",
                }))

        # ── Phase 3: run concurrently ─────────────────────────────────────────
        # FastAPI/Starlette WebSocket can only have one concurrent reader.
        # _upstream handles both text control frames and binary PCM audio.
        try:
            await asyncio.gather(
                _upstream(),
                _downstream(),
                _heartbeat(),
                _posture_analysis(),
                return_exceptions=True,
            )
        except Exception as exc:
            logger.error(
                "Unexpected error in live session gather — session_id=%s  %s: %s",
                session_id, type(exc).__name__, exc,
            )
        finally:
            # ── Phase 4: terminate ────────────────────────────────────────────
            live_request_queue.close()   # idempotent
            # Save transcript to its own collection (keeps session doc lean).
            # _transcript_turns is pre-populated with prior turns on resume,
            # so it already contains the full gap-free conversation history.
            await self._save_transcript(session_id, _transcript_turns)
            await self.end_session(session_id)
            logger.info(
                "Live session ended — session_id=%s  transcript_turns=%d  "
                "posture_frames=%d",
                session_id, len(_transcript_turns), _posture_frame_count,
            )
