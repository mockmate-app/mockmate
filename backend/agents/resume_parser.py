"""
ResumeParserAgent
-----------------
Uses Gemini 2.0 Flash (via Vertex AI) to extract structured data from an
uploaded résumé (PDF or DOCX), stores the raw file in GCS, and persists
the structured result in Firestore.

Flow
----
  1. Detect MIME type and upload the raw file to GCS.
  2. Extract readable text from the file (PyPDF2 for PDF, python-docx for DOCX).
  3. Call Gemini 2.0 Flash with a strict JSON schema prompt.
  4. Strip any accidental markdown fences from the model response.
  5. Persist the structured document in Firestore (keyed by user_id).
  6. Return the structured dict to the caller.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import PyPDF2
import docx
import vertexai
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable
from google.cloud import firestore, storage
from google.cloud.exceptions import GoogleCloudError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
    before_sleep_log,
)
from vertexai.generative_models import GenerationConfig, GenerativeModel, Part

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (override via environment variables)
# ---------------------------------------------------------------------------

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
_BUCKET     = _require("GCS_BUCKET")
_COLLECTION = os.getenv("FIRESTORE_RESUME_COLLECTION", "resumes")  # optional, sensible default
_DATABASE   = os.getenv("FIRESTORE_DATABASE", "(default)")          # optional, sensible default
_MODEL      = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")     # optional, sensible default

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

PARSE_PROMPT = """\
You are a precise resume parser. Given the raw text of a candidate's resume,
extract and return ONLY a valid JSON object with exactly the following keys.
Do NOT include markdown fences or any text outside the JSON object.

{{
  "name": "<string>",
  "email": "<string>",
  "phone": "<string>",
  "summary": "<string>",
  "skills": ["<string>"],
  "experience": [
    {{
      "title": "<string>",
      "company": "<string>",
      "duration": "<string>",
      "highlights": ["<string>"]
    }}
  ],
  "education": [
    {{
      "degree": "<string>",
      "institution": "<string>",
      "year": "<string>"
    }}
  ],
  "certifications": ["<string>"],
  "bold_claims": ["<string>"],
  "suggested_job_titles": ["<string>"]
}}

Rules:
- "skills"      → flat list of individual skills/technologies.
- "bold_claims" → extraordinary or quantified achievements an interviewer
                  should probe, e.g. "Led a team of 30 engineers",
                  "Grew ARR 3× to $12 M". Include at least one entry if any
                  such claim exists; return an empty array otherwise.
- "suggested_job_titles" → 4-6 realistic job titles the candidate would be
                  a strong fit for, based on their skills, experience, and
                  seniority level. Titles should be specific and varied
                  (e.g. "Senior Backend Engineer", "Platform Engineering Lead",
                  "Staff Software Engineer", "Engineering Manager").
                  Do NOT repeat the candidate's current/past titles verbatim;
                  instead suggest aspirational or lateral roles they could
                  credibly interview for.
- If a field cannot be found, use an empty string or empty array.

Resume text:
\"\"\"
{resume_text}
\"\"\"
"""

# ---------------------------------------------------------------------------
# MIME type helpers
# ---------------------------------------------------------------------------

_MIME_MAP = {
    ".pdf":  "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc":  "application/msword",
    ".txt":  "text/plain",
}

_SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt"}


def _mime_for(filename: str) -> str:
    ext = os.path.splitext(filename.lower())[1]
    return _MIME_MAP.get(ext, "application/octet-stream")


def _ext_of(filename: str) -> str:
    return os.path.splitext(filename.lower())[1]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class ResumeParserAgent:
    """Parses résumés and stores structured data in Firestore."""

    def __init__(self) -> None:
        logger.info(
            "ResumeParserAgent config — project=%s  region=%s  bucket=%s  "
            "firestore_db=%s  collection=%s  model=%s",
            _PROJECT, _REGION, _BUCKET, _DATABASE, _COLLECTION, _MODEL,
        )
        vertexai.init(project=_PROJECT, location=_REGION)
        self._model = GenerativeModel(_MODEL)
        self._db = firestore.AsyncClient(project=_PROJECT, database=_DATABASE)
        self._storage = storage.Client(project=_PROJECT)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def parse(
        self,
        file_bytes: bytes,
        filename: str,
        user_id: str,
    ) -> dict[str, Any]:
        """
        Full resume-parse pipeline.

        Parameters
        ----------
        file_bytes : bytes   Raw file content.
        filename   : str     Original filename (used to detect format).
        user_id    : str     Caller's user identifier.

        Returns
        -------
        dict  Structured parsed resume including GCS URI and metadata.

        Raises
        ------
        ValueError          If the file extension is not supported.
        GoogleCloudError    If GCS upload or Firestore write fails.
        json.JSONDecodeError If Gemini returns unparseable output.
        """
        ext = _ext_of(filename)
        if ext not in _SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type '{ext}'. "
                f"Accepted: {', '.join(sorted(_SUPPORTED_EXTENSIONS))}"
            )

        resume_id = str(uuid.uuid4())

        # 1. Upload raw file to GCS
        gcs_uri = self._upload_to_gcs(file_bytes, filename, user_id, resume_id)
        logger.info("Uploaded resume to %s", gcs_uri)

        # 2. Extract plain text
        resume_text = self._extract_text(file_bytes, filename)
        if not resume_text.strip():
            raise ValueError("Could not extract any text from the uploaded file.")

        # 3. Parse with Gemini
        structured = await self._parse_with_gemini(resume_text)

        # 4. Attach metadata
        structured.update(
            {
                "resume_id":  resume_id,
                "user_id":    user_id,
                "gcs_uri":    gcs_uri,
                "filename":   filename,
                "parsed_at":  datetime.now(timezone.utc).isoformat(),
            }
        )

        # 5. Persist to Firestore
        await self._persist(user_id, resume_id, structured)
        logger.info("Persisted resume %s for user %s", resume_id, user_id)

        return structured

    async def get_resume(self, user_id: str) -> dict[str, Any] | None:
        """Return the most-recently parsed resume for *user_id*, or None."""
        doc = await self._db.collection(_COLLECTION).document(user_id).get()
        return doc.to_dict() if doc.exists else None

    async def get_resume_file(self, user_id: str) -> tuple[bytes, str] | None:
        """Return (file_bytes, content_type) for the raw uploaded file, or None."""
        data = await self.get_resume(user_id)
        if not data:
            return None
        gcs_uri = data.get("gcs_uri", "")
        filename = data.get("filename", "resume.pdf")
        if not gcs_uri.startswith("gs://"):
            return None
        # Parse gs://bucket/blob_name
        without_scheme = gcs_uri[5:]
        bucket_name, _, blob_name = without_scheme.partition("/")
        try:
            bucket = self._storage.bucket(bucket_name)
            blob   = bucket.blob(blob_name)
            file_bytes = blob.download_as_bytes()
            content_type = blob.content_type or _mime_for(filename)
            return file_bytes, content_type
        except GoogleCloudError as exc:
            logger.error("GCS download failed for user %s: %s", user_id, exc)
            return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _upload_to_gcs(
        self, data: bytes, filename: str, user_id: str, resume_id: str
    ) -> str:
        """Upload *data* to GCS and return the gs:// URI."""
        try:
            bucket    = self._storage.bucket(_BUCKET)
            blob_name = f"{user_id}/{resume_id}_{filename}"
            blob      = bucket.blob(blob_name)
            blob.upload_from_file(
                io.BytesIO(data),
                content_type=_mime_for(filename),
            )
            return f"gs://{_BUCKET}/{blob_name}"
        except GoogleCloudError as exc:
            logger.error("GCS upload failed: %s", exc)
            raise

    @staticmethod
    def _extract_text(data: bytes, filename: str) -> str:
        """Extract readable text from a PDF, DOCX, DOC, or plain-text file."""
        ext = _ext_of(filename)

        if ext == ".pdf":
            reader = PyPDF2.PdfReader(io.BytesIO(data))
            pages  = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(pages)

        if ext in {".docx", ".doc"}:
            document = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in document.paragraphs)

        # Plain text fallback
        return data.decode("utf-8", errors="ignore")

    async def _parse_with_gemini(self, resume_text: str) -> dict[str, Any]:
        """Send *resume_text* to Gemini and return the parsed JSON dict."""
        prompt = PARSE_PROMPT.format(resume_text=resume_text)

        generation_config = GenerationConfig(
            response_mime_type="application/json",
            temperature=0.1,          # low temperature for deterministic extraction
            max_output_tokens=4096,
        )

        @retry(
            retry=retry_if_exception_type((ResourceExhausted, ServiceUnavailable)),
            wait=wait_random_exponential(multiplier=1, max=60),
            stop=stop_after_attempt(5),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        async def _generate_with_retry():
            return await self._model.generate_content_async(
                [Part.from_text(prompt)],
                generation_config=generation_config,
            )

        response = await _generate_with_retry()

        raw_text = response.text.strip()

        # Strip accidental markdown fences (```json ... ```)
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$",           "", raw_text)

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            logger.error("Gemini returned non-JSON output: %s", raw_text[:500])
            raise json.JSONDecodeError(
                f"Gemini response is not valid JSON: {exc.msg}",
                exc.doc,
                exc.pos,
            ) from exc

    async def _persist(
        self, user_id: str, resume_id: str, data: dict[str, Any]
    ) -> None:
        """Write structured resume data to Firestore."""
        # Top-level document per user (always latest)
        user_doc = self._db.collection(_COLLECTION).document(user_id)
        await user_doc.set(data, merge=True)

        # Also write to a sub-collection for history
        history_doc = user_doc.collection("history").document(resume_id)
        await history_doc.set(data)
