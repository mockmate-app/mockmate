# MockMate

> MockMate is an AI-powered mock interview platform that conducts real, adaptive interview sessions using voice, vision, and personalized question generation. MockMate analyzes not just what you say but how you say it — scoring your tone, posture, vocabulary, and confidence in real time. At the end of every session, you receive a detailed feedback report and a mock hiring decision letter, so you walk into every real interview already knowing how it ends.
>
> MockMate - _Interview practice, without the nerves._

### The Problem
Job interviews are high-stakes, deeply personal, and almost impossible to practice realistically. Most candidates prepare by reading lists of common questions, rehearsing answers alone in a mirror, or paying hundreds of dollars for human coaching sessions they can only afford once or twice. The result is that people fail interviews not because they are unqualified — but because they are underprepared for the *experience* of being interviewed. The pressure, the unexpected follow-ups, the judgment of silence, the moment an interviewer pushes back on your answer — none of that can be simulated by reading a blog post or watching a YouTube video.

Existing platforms like Final Round AI and Huru offer some form of AI interview practice, but they fall into the same trap: they are either text-based, too generic, or they only evaluate you after the session is over. None of them simulate the real emotional and social dynamics of a live interview. None of them see you. And none of them tell you honestly whether you would have gotten the job.

### The Solution
MockMate is a real-time AI interview coach that conducts full mock interviews using voice, vision, and resume-personalized question generation — and evaluates everything, not just your words.

You upload your resume. MockMate reads it and generates questions specifically targeting your experience, your career transitions, and the bold claims you've made on paper. You choose an interviewer persona — from a supportive startup founder to an aggressive investment banker. You sit down, speak naturally, and MockMate interviews you live. Mid-session, it injects curveball questions and deliberate interruptions to simulate real interview unpredictability. While you speak, a parallel vision model watches your posture, eye contact, and facial confidence through your webcam. When the session ends, you receive a full multimodal feedback report — tone analysis, vocabulary calibration, posture scores, filler word timestamps — and a mock offer or rejection letter with specific reasoning, just like a real recruiter would send.

Every session updates your skill progression dashboard, tracking your improvement across communication, confidence, structure, technical depth, and domain vocabulary over time.

### Key Features
- **Resume-Aware Question Generation** — MockMate reads your actual resume and generates hyper-personalized questions rather than generic prompts. If you claim to have led a team of 30, expect to be asked exactly how you handled underperformance.
- **Live Interviewer Personas** — choose from multiple interviewer archetypes with distinct questioning styles, pressure levels, and follow-up behaviors. The experience is fundamentally different depending on who you're practicing against.
- **Stress Injection Engine** — mid-interview, MockMate deliberately interrupts, challenges your answers, or introduces surprise questions. Real interviews are unpredictable; your practice should be too.
- **Posture & Presence Vision Analysis** — using your webcam, MockMate scores your non-verbal communication in real time. After the session you receive a split report: what you said versus how you came across.
- **Mock Hiring Decision Letter** — at the end of every session, MockMate generates a simulated offer or rejection letter with specific, personalized reasoning. This makes feedback feel consequential rather than academic.
- **Skill Progression Dashboard** — every session contributes to a longitudinal skill graph that tracks your growth over time and unlocks harder interview modes as your scores improve.

### Technologies Used
MockMate is built on Google's Gemini Live API for real-time conversational interviewing, Gemini 2.0 Flash vision for posture and presence analysis, and Gemini 1.5 Flash for resume parsing, jargon calibration, and offer letter generation. The agent pipeline is orchestrated using Google ADK, with all model calls routed through Vertex AI. The backend is a FastAPI application containerized and deployed on Google Cloud Run. Session data, user profiles, and skill scores are stored in Firestore. Resumes and session recordings are stored in Cloud Storage. A Pub/Sub stream handles async communication between the live interview engine and the parallel vision analysis worker. The frontend is built in Next.js with WebSocket-based real-time audio and video streaming.

### USP & Differentiation
Most interview platforms evaluate what you say. MockMate evaluates who you are under pressure — your voice, your body, your vocabulary, your resilience when interrupted. It is the only platform that combines live voice interviewing, real-time vision analysis, resume personalization, adversarial stress injection, and a consequential hiring decision output in a single session. It does not just prepare you for interview questions — it prepares you for the full human experience of being interviewed.
