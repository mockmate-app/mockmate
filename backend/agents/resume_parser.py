"""
ResumeParserAgent
-----------------
Uses Gemini 1.5 Flash (via Vertex AI) to extract structured data from an
uploaded résumé (PDF or DOCX) and persists it in Firestore.
"""

from __future__ import annotations

import io
import json
import os
import uuid
from typing import Any

import PyPDF2
import docx
import vertexai
from google.cloud import firestore, storage
from vertexai.generative_models import GenerativeModel, Part

_PROJECT = os.getenv("GCP_PROJECT_ID", "mockmate-project")
_REGION = os.getenv("GCP_REGION", "us-central1")
_BUCKET = os.getenv("GCS_BUCKET", "mockmate-resumes")
_COLLECTION = "resumes"

PARSE_PROMPT = """
You are a precise resume parser. Given the raw text of a candidate's resume,
extract and return ONLY a valid JSON object with the following keys:

{
  "name": string,
  "email": string,
  "phone": string,
  "summary": string,
  "skills": [string],
  "experience": [
    {
      "title": string,
      "company": string,
      "duration": string,
      "highlights": [string]
    }
  ],
  "education": [
    {
      "degree": string,
      "institution": string,
      "year": string
    }
  ],
  "certifications": [string],
  "bold_claims": [string]
}

The "bold_claims" array must list any extraordinary or quantified achievements
that an interviewer should probe (e.g., "Led a team of 30", "Grew revenue 3x").

Resume text:
\"\"\"
{resume_text}
\"\"\"
"""


class ResumeParserAgent:
    """Parses résumés and stores structured data in Firestore."""

    def __init__(self) -> None:
        vertexai.init(project=_PROJECT, location=_REGION)
        self._model = GenerativeModel("gemini-1.5-flash")
        self._db = firestore.AsyncClient(project=_PROJECT)
        self._storage = storage.Client(project=_PROJECT)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def parse(
        self, file_bytes: bytes, filename: str, user_id: str
    ) -> dict[str, Any]:
        """
        1. Upload raw file to GCS.
        2. Extract text (PDF or DOCX).
        3. Call Gemini to produce structured JSON.
        4. Persist result in Firestore.
        5. Return structured dict.
        """
        gcs_uri = self._upload_to_gcs(file_bytes, filename, user_id)
        resume_text = self._extract_text(file_bytes, filename)
        structured = await self._parse_with_gemini(resume_text)
        structured["gcs_uri"] = gcs_uri
        structured["user_id"] = user_id
        await self._persist(user_id, structured)
        return structured

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _upload_to_gcs(self, data: bytes, filename: str, user_id: str) -> str:
        bucket = self._storage.bucket(_BUCKET)
        blob_name = f"{user_id}/{uuid.uuid4()}_{filename}"
        blob = bucket.blob(blob_name)
        blob.upload_from_file(io.BytesIO(data), content_type="application/octet-stream")
        return f"gs://{_BUCKET}/{blob_name}"

    @staticmethod
    def _extract_text(data: bytes, filename: str) -> str:
        if filename.lower().endswith(".pdf"):
            reader = PyPDF2.PdfReader(io.BytesIO(data))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        if filename.lower().endswith(".docx"):
            doc = docx.Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs)
        # Fallback — treat as plain text
        return data.decode("utf-8", errors="ignore")

    async def _parse_with_gemini(self, resume_text: str) -> dict[str, Any]:
        prompt = PARSE_PROMPT.format(resume_text=resume_text)
        response = await self._model.generate_content_async(
            [Part.from_text(prompt)],
            generation_config={"response_mime_type": "application/json"},
        )
        return json.loads(response.text)

    async def _persist(self, user_id: str, data: dict[str, Any]) -> None:
        doc_ref = self._db.collection(_COLLECTION).document(user_id)
        await doc_ref.set(data, merge=True)
