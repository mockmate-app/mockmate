"""
Shared configuration for all MockMate agents.
Centralises environment-variable reads, Firestore collection names,
model identifiers, and Postgres connection details.
"""

from __future__ import annotations

import os


def require_env(var: str) -> str:
    """Return env var value or raise a clear error if it is missing/empty."""
    val = os.getenv(var, "").strip()
    if not val:
        raise EnvironmentError(
            f"Required environment variable '{var}' is not set. "
            f"Add it to your .env file and restart the server."
        )
    return val


# ── Google Cloud ────────────────────────────────────────────────────────────
PROJECT = require_env("GOOGLE_CLOUD_PROJECT")
REGION  = require_env("GOOGLE_CLOUD_LOCATION")

# ── Firestore ──────────────────────────────────────────────────────────────
FIRESTORE_DATABASE           = os.getenv("FIRESTORE_DATABASE", "(default)")
FIRESTORE_SESSION_COLLECTION = os.getenv("FIRESTORE_SESSION_COLLECTION", "sessions")
FIRESTORE_RESUME_COLLECTION  = os.getenv("FIRESTORE_RESUME_COLLECTION", "resumes")
FIRESTORE_TRANSCRIPT_COLLECTION = os.getenv("FIRESTORE_TRANSCRIPT_COLLECTION", "transcripts")
FIRESTORE_FEEDBACK_COLLECTION   = os.getenv("FIRESTORE_FEEDBACK_COLLECTION", "feedback")
FIRESTORE_POSTURE_COLLECTION    = os.getenv("FIRESTORE_POSTURE_COLLECTION", "posture_scores")

# ── GCS ────────────────────────────────────────────────────────────────────
GCS_BUCKET = os.getenv("GCS_BUCKET", "").strip()  # required only by some agents

# ── Model identifiers ─────────────────────────────────────────────────────
GEMINI_MODEL      = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_LIVE_MODEL = os.getenv("MOCKMATE_LIVE_MODEL", "gemini-live-2.5-flash-native-audio")
POSTURE_MODEL     = os.getenv("POSTURE_MODEL", "gemini-2.5-flash-lite")
IMAGEN_MODEL      = os.getenv("IMAGEN_MODEL", "imagen-3.0-fast-generate-001")

# ── Postgres (Better Auth) ─────────────────────────────────────────────────
PGHOST     = os.getenv("PGHOST", "").strip()
PGPORT     = int(os.getenv("PGPORT", "5432"))
PGUSER     = os.getenv("PGUSER", "").strip()
PGPASSWORD = os.getenv("PGPASSWORD", "").strip()
PGDATABASE = os.getenv("PGDATABASE", "").strip()
