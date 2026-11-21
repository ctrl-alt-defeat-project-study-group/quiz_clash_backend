"""
AI quiz generation service powered by Gemini 2.5 Flash with native Google Search grounding.

Pipeline:
1. Stage 1 (analyze_document): Summarize uploaded study text and extract top keywords.
2. Stage 2 (research_keywords): Optional Google Search grounding on extracted keywords
   to gather concise factual notes and common misconceptions (graceful fallback on error).
3. Stage 3 (generate_questions): Generate validated multiple-choice questions (EN/MM)
   using strict JSON schema output with one automatic validation retry.
"""
import json
import logging
import random
from typing import Any, Dict, List

import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.core.errors import api_error
from app.services.quiz_generator import QuizGenerator

logger = logging.getLogger("quizclash.llm")

_ANALYSIS_SCHEMA: Dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "summary": {"type": "STRING"},
        "keywords": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
        },
    },
    "required": ["summary", "keywords"],
}

_QUESTIONS_SCHEMA: Dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "questions": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "prompt": {"type": "STRING"},
                    "explanation": {"type": "STRING"},
                    "choices": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "text": {"type": "STRING"},
                                "is_correct": {"type": "BOOLEAN"},
                            },
                            "required": ["text", "is_correct"],
                        },
                    },
                },
                "required": ["prompt", "explanation", "choices"],
            },
        }
    },
    "required": ["questions"],
}


class LLMQuizGenerator:
    """Generate multiple-choice questions from unstructured text using Gemini API."""

    @staticmethod
    def _language_label(language: str) -> str:
        return "Myanmar (Burmese)" if language == "mm" else "English"

    @staticmethod
    def _call_gemini(payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        api_key = (settings.LLM_API_KEY or "").strip()
        if not api_key:
            raise api_error(
                503,
                "GENERATION_FAILED",
                "AI quiz generation is not configured on the server. Set LLM_API_KEY to enable it.",
            )

        base_url = settings.LLM_API_BASE_URL.rstrip("/")
        url = f"{base_url}/models/{settings.LLM_MODEL}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }

        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            logger.warning("Gemini API request timed out after %ss: %s", timeout, exc)
            raise api_error(
                503,
                "GENERATION_FAILED",
                "AI quiz generation timed out. Please try again.",
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("Gemini API network error: %s", exc)
            raise api_error(
                503,
                "GENERATION_FAILED",
                "Unable to reach the AI provider. Please try again later.",
            ) from exc

        if response.status_code == 429:
            raise api_error(
                503,
                "GENERATION_FAILED",
                "AI provider quota exceeded. Please try again shortly.",
            )
        if response.status_code >= 400:
            logger.warning(
                "Gemini API returned HTTP %s: %s",
                response.status_code,
                response.text[:500],
            )
            raise api_error(
                503,
                "GENERATION_FAILED",
                "AI provider returned an error while generating the quiz.",
            )

        try:
            return response.json()
        except ValueError as exc:
            raise api_error(
                503,
                "GENERATION_FAILED",
                "AI provider returned an unreadable response.",
            ) from exc

    @staticmethod
    def _extract_response_text(response_json: Dict[str, Any]) -> str:
        candidates = response_json.get("candidates") or []
        if not candidates:
            raise api_error(
                500,
                "GENERATION_FAILED",
                "AI provider returned no candidates.",
            )

        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(
            part.get("text", "") for part in parts if isinstance(part, dict)
        ).strip()
        if not text:
            raise api_error(
                500,
                "GENERATION_FAILED",
                "AI provider returned an empty response.",
            )
        return text

    @classmethod
    def analyze_document(cls, raw_text: str, language: str = "en") -> Dict[str, Any]:
        """Stage 1: Summarize the uploaded document and extract top study keywords."""
        truncated = raw_text[: settings.LLM_MAX_INPUT_CHARS]
        lang_name = cls._language_label(language)
        max_kw = max(3, settings.LLM_MAX_KEYWORDS)

        prompt = (
            f"Analyze the following study material and respond in {lang_name}.\n"
            f"1. Write a concise 3-6 sentence summary capturing the core topics and facts.\n"
            f"2. Extract up to {max_kw} high-signal keywords or key concepts that best represent "
            f"the study material and would benefit from factual verification or enrichment.\n\n"
            f"Study material:\n\"\"\"\n{truncated}\n\"\"\""
        )

        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1024,
                "responseMimeType": "application/json",
                "responseSchema": _ANALYSIS_SCHEMA,
            },
        }

        data = cls._call_gemini(payload, timeout=settings.LLM_TIMEOUT_SECONDS)
        text = cls._extract_response_text(data)

        try:
            parsed = json.loads(text)
        except ValueError as exc:
            raise api_error(
                500,
                "GENERATION_FAILED",
                "Failed to parse document analysis from AI provider.",
            ) from exc

        summary = str(parsed.get("summary") or "").strip()
        raw_keywords = parsed.get("keywords") or []

        keywords: List[str] = []
        seen = set()
        for kw in raw_keywords:
            cleaned = str(kw).strip()
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            keywords.append(cleaned)
            if len(keywords) >= settings.LLM_MAX_KEYWORDS:
                break

        return {"summary": summary, "keywords": keywords}

    @classmethod
    def research_keywords(
        cls,
        keywords: List[str],
        summary: str,
        language: str = "en",
    ) -> str:
        """
        Stage 2: Use Gemini native Google Search grounding on extracted keywords only.
        Never sends raw private file text; falls back gracefully to empty string on error.
        """
        if not keywords:
            return ""

        lang_name = cls._language_label(language)
        keyword_list = ", ".join(keywords[: settings.LLM_MAX_KEYWORDS])

        prompt = (
            f"Use Google Search to briefly research these study keywords: {keyword_list}.\n"
            f"Topic context: {summary[:600]}\n\n"
            f"Write concise bullet-point factual reference notes in {lang_name} covering:\n"
            f"- Clear definitions and key facts for each keyword\n"
            f"- Related concepts or common misconceptions (useful for realistic multiple-choice distractors)\n"
            f"Keep the total response under 400 words."
        )

        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1024,
            },
        }

        try:
            data = cls._call_gemini(
                payload,
                timeout=settings.LLM_WEB_SEARCH_TIMEOUT_SECONDS,
            )
            return cls._extract_response_text(data)
        except HTTPException as exc:
            logger.warning(
                "Web search enrichment failed (falling back to file-only): %s",
                exc.detail,
            )
            return ""
        except Exception as exc:
            logger.warning(
                "Unexpected error during web search enrichment (falling back to file-only): %s",
                exc,
            )
            return ""

    @staticmethod
    def _normalize_questions(
        raw_questions: List[Dict[str, Any]],
        expected_count: int,
    ) -> List[Dict[str, Any]]:
        if not isinstance(raw_questions, list) or not raw_questions:
            raise api_error(500, "GENERATION_FAILED", "AI returned no questions.")

        normalized: List[Dict[str, Any]] = []
        for idx, item in enumerate(raw_questions[:expected_count]):
            if not isinstance(item, dict):
                raise api_error(
                    500,
                    "GENERATION_FAILED",
                    f"Question {idx + 1}: Invalid question object.",
                )

            prompt_text = str(item.get("prompt") or "").strip()
            explanation_text = str(item.get("explanation") or "").strip() or None
            raw_choices = item.get("choices") or []

            choices: List[Dict[str, Any]] = []
            for c in raw_choices:
                if not isinstance(c, dict):
                    continue
                choices.append(
                    {
                        "text": str(c.get("text") or "").strip(),
                        "is_correct": bool(c.get("is_correct", False)),
                    }
                )

            random.shuffle(choices)
            for c_idx, choice in enumerate(choices):
                choice["position"] = c_idx

            normalized.append(
                {
                    "prompt": prompt_text,
                    "explanation": explanation_text,
                    "position": idx,
                    "choices": choices,
                }
            )

        if len(normalized) < expected_count:
            raise api_error(
                500,
                "GENERATION_FAILED",
                f"Expected {expected_count} questions, but AI generated {len(normalized)}.",
            )

        QuizGenerator.validate_questions(normalized)
        return normalized

    @classmethod
    def generate_questions(
        cls,
        raw_text: str,
        summary: str,
        web_notes: str,
        question_count: int,
        language: str = "en",
        difficulty: str = "Mixed",
    ) -> List[Dict[str, Any]]:
        """Stage 3: Generate validated multiple-choice questions with 1 automatic retry."""
        truncated = raw_text[: settings.LLM_MAX_INPUT_CHARS]
        lang_name = cls._language_label(language)

        web_section = (
            f"\nWeb Research Notes (use only to clarify keywords, enrich explanations, and craft plausible distractors):\n"
            f"\"\"\"\n{web_notes}\n\"\"\"\n"
            if web_notes.strip()
            else ""
        )

        base_prompt = (
            f"You are an expert quiz author. Generate exactly {question_count} high-quality "
            f"multiple-choice questions in {lang_name}.\n\n"
            f"Rules:\n"
            f"- Difficulty level: {difficulty}.\n"
            f"- The uploaded study document and summary are the PRIMARY source of truth. "
            f"Stay strictly aligned with the document's topics.\n"
            f"- Every question MUST have exactly 4 distinct, non-empty choices.\n"
            f"- Exactly 1 choice MUST have is_correct=true and the other 3 MUST have is_correct=false.\n"
            f"- Make distractors plausible and concise (avoid 'All of the above' / 'None of the above').\n"
            f"- Include a clear 1-2 sentence explanation for why the correct answer is right.\n"
            f"- Write ALL prompts, choices, and explanations in {lang_name}.\n\n"
            f"Document Summary:\n\"\"\"\n{summary}\n\"\"\"\n"
            f"{web_section}\n"
            f"Uploaded Study Document:\n\"\"\"\n{truncated}\n\"\"\""
        )

        last_error: HTTPException | None = None
        retry_feedback = ""

        for attempt in range(2):
            prompt = base_prompt if attempt == 0 else (
                f"{base_prompt}\n\n"
                f"IMPORTANT CORRECTION FROM PREVIOUS ATTEMPT:\n{retry_feedback}\n"
                f"Fix this issue and return exactly {question_count} valid questions."
            )

            payload = {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.3 if attempt == 0 else 0.1,
                    "maxOutputTokens": settings.LLM_MAX_TOKENS,
                    "responseMimeType": "application/json",
                    "responseSchema": _QUESTIONS_SCHEMA,
                },
            }

            data = cls._call_gemini(payload, timeout=settings.LLM_TIMEOUT_SECONDS)
            text = cls._extract_response_text(data)

            try:
                parsed = json.loads(text)
                raw_questions = parsed.get("questions") if isinstance(parsed, dict) else None
                return cls._normalize_questions(raw_questions or [], expected_count=question_count)
            except ValueError as exc:
                retry_feedback = f"Previous output was not valid JSON: {exc}"
                last_error = api_error(
                    500,
                    "GENERATION_FAILED",
                    "AI provider returned malformed JSON for quiz questions.",
                )
            except HTTPException as exc:
                if exc.status_code == 503:
                    raise
                detail_msg = (
                    exc.detail.get("message")
                    if isinstance(exc.detail, dict)
                    else str(exc.detail)
                )
                retry_feedback = f"Validation failed: {detail_msg}"
                last_error = exc

        assert last_error is not None
        raise last_error

    @classmethod
    def generate_from_text(
        cls,
        raw_text: str,
        question_count: int,
        language: str = "en",
        difficulty: str = "Mixed",
        use_web_search: bool = True,
    ) -> List[Dict[str, Any]]:
        """Run full AI pipeline: analyze -> optional web search -> generate validated MCQs."""
        analysis = cls.analyze_document(raw_text, language=language)
        summary = analysis["summary"]
        keywords = analysis["keywords"]

        web_notes = ""
        if use_web_search and keywords:
            web_notes = cls.research_keywords(
                keywords=keywords,
                summary=summary,
                language=language,
            )

        return cls.generate_questions(
            raw_text=raw_text,
            summary=summary,
            web_notes=web_notes,
            question_count=question_count,
            language=language,
            difficulty=difficulty,
        )
