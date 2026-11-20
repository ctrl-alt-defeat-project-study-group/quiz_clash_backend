"""
Language normalization and bilingual (EN / MM) text templates.

Canonical Myanmar code is 'mm' everywhere (Accept-Language, form 'language',
query 'lang'). Legacy ISO code 'my' is silently accepted and normalized to 'mm'.
"""
from typing import Dict, Optional

DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "mm")


def normalize_language(raw: Optional[str]) -> str:
    """Normalize a language string or Accept-Language header to 'en' or 'mm'."""
    if not raw or not isinstance(raw, str):
        return DEFAULT_LANGUAGE

    # Parse Accept-Language style lists (e.g., "my-MM,en;q=0.8")
    for part in raw.split(","):
        tag = part.split(";", 1)[0].strip().lower()
        if not tag:
            continue
        primary = tag.split("-", 1)[0].split("_", 1)[0]
        if primary in ("mm", "my"):
            return "mm"
        if primary == "en":
            return "en"

    return DEFAULT_LANGUAGE


def resolve_request_language(
    explicit: Optional[str] = None,
    accept_language: Optional[str] = None,
) -> str:
    """Resolve effective language: explicit param wins over Accept-Language header."""
    if explicit is not None and explicit.strip():
        return normalize_language(explicit)
    if accept_language is not None and accept_language.strip():
        return normalize_language(accept_language)
    return DEFAULT_LANGUAGE


def contains_myanmar(text: str) -> bool:
    """Return True if text contains Myanmar Unicode characters."""
    for ch in text:
        code = ord(ch)
        if (0x1000 <= code <= 0x109F) or (0xAA60 <= code <= 0xAA7F) or (0xA9E0 <= code <= 0xA9FF):
            return True
    return False


def format_question_prompt(term: str, language: str = "en") -> str:
    """Return the localized MCQ prompt template for a given term."""
    lang = normalize_language(language)
    if lang == "mm":
        return f"'{term}' ၏ အဓိပ္ပာယ်မှာ အဘယ်နည်း။"
    return f"What does '{term}' mean?"


EXPORT_LABELS: Dict[str, Dict[str, str]] = {
    "en": {
        "quiz_prefix": "Quiz",
        "answer_key_prefix": "Answer Key",
        "instructions": (
            "Please select the correct answer for each question. "
            "Write your answer in the space provided."
        ),
        "answer_blank": "Answer: __________",
        "warning": (
            "This document contains the correct answers. "
            "Do not distribute to students before the quiz."
        ),
        "col_question": "Question",
        "col_correct_answer": "Correct Answer",
        "detailed_answers": "Detailed Answers",
        "correct_answer_label": "Correct Answer",
        "explanation_label": "Explanation",
    },
    "mm": {
        "quiz_prefix": "မေးခွန်းလွှာ",
        "answer_key_prefix": "အဖြေမှန်လွှာ",
        "instructions": (
            "မေးခွန်းတစ်ခုစီအတွက် မှန်ကန်သောအဖြေကို ရွေးချယ်ပြီး "
            "ကွက်လပ်တွင် ဖြည့်စွက်ပါ။"
        ),
        "answer_blank": "အဖြေ - __________",
        "warning": (
            "ဤစာရွက်စာတမ်းတွင် အဖြေမှန်များ ပါဝင်ပါသည်။ "
            "စာမေးပွဲမစတင်မီ ကျောင်းသားများအား မဖြန့်ဝေပါနှင့်။"
        ),
        "col_question": "မေးခွန်း",
        "col_correct_answer": "အဖြေမှန်",
        "detailed_answers": "အသေးစိတ် အဖြေများ",
        "correct_answer_label": "အဖြေမှန်",
        "explanation_label": "ရှင်းလင်းချက်",
    },
}


def get_export_labels(language: str = "en") -> Dict[str, str]:
    """Return localized static labels for PDF/Word exports."""
    return EXPORT_LABELS[normalize_language(language)]
