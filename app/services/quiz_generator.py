"""
Service for generating multiple choice questions from parsed content
"""
import random
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.errors import api_error
from app.core.language import format_question_prompt


class QuizGenerator:
    """Generate multiple choice questions from terms and definitions"""

    @staticmethod
    def generate_from_structured(
        terms_definitions: List[Tuple[str, str]],
        question_count: Optional[int] = None,
        language: str = "en",
    ) -> List[Dict[str, Any]]:
        """
        Generate MCQs from structured term-definition pairs.

        Args:
            terms_definitions: List of (term, definition) tuples
            question_count: Number of questions to generate (default: all or up to max)

        Returns:
            List of question dictionaries with prompt, explanation, and choices
        """
        if not terms_definitions:
            raise api_error(
                400,
                "EMPTY_FILE",
                "No valid terms and definitions found.",
            )

        if question_count is not None and question_count <= 0:
            raise api_error(
                422,
                "VALIDATION_ERROR",
                "question_count must be greater than 0.",
            )

        # Filter empty entries and deduplicate pairs by normalized term
        valid_pairs: List[Tuple[str, str]] = []
        seen_terms = set()
        for raw_term, raw_def in terms_definitions:
            term = raw_term.strip()
            definition = raw_def.strip()
            if not term or not definition:
                continue
            term_key = term.casefold()
            if term_key in seen_terms:
                continue
            seen_terms.add(term_key)
            valid_pairs.append((term, definition))

        if len(valid_pairs) < settings.MIN_DEFINITIONS_FOR_GENERATION:
            raise api_error(
                400,
                "EMPTY_FILE",
                f"Need at least {settings.MIN_DEFINITIONS_FOR_GENERATION} "
                f"unique terms with definitions to generate questions. "
                f"Found only {len(valid_pairs)}.",
            )

        # Build deduplicated definition pool (case-insensitive) for unique distractors
        unique_definitions_by_key: Dict[str, str] = {}
        for _, definition in valid_pairs:
            def_key = definition.casefold()
            if def_key not in unique_definitions_by_key:
                unique_definitions_by_key[def_key] = definition

        # Determine how many questions to generate
        if question_count is None:
            target_count = min(len(valid_pairs), settings.DEFAULT_QUESTIONS_PER_QUIZ)
        else:
            target_count = min(question_count, len(valid_pairs))

        # Shuffle pairs for random selection
        shuffled_pairs = list(valid_pairs)
        random.shuffle(shuffled_pairs)
        selected_pairs = shuffled_pairs[:target_count]

        questions: List[Dict[str, Any]] = []

        for term, correct_definition in selected_pairs:
            correct_key = correct_definition.casefold()
            other_definitions = [
                definition
                for def_key, definition in unique_definitions_by_key.items()
                if def_key != correct_key
            ]

            if len(other_definitions) < 3:
                # Not enough unique definitions for distractors
                continue

            distractors = random.sample(other_definitions, 3)

            choices = [{"text": correct_definition, "is_correct": True, "position": 0}]
            for idx, distractor in enumerate(distractors, 1):
                choices.append({"text": distractor, "is_correct": False, "position": idx})

            random.shuffle(choices)
            for idx, choice in enumerate(choices):
                choice["position"] = idx

            questions.append(
                {
                    "prompt": format_question_prompt(term, language),
                    "explanation": f"{term}: {correct_definition}",
                    "position": len(questions),
                    "choices": choices,
                }
            )

        return questions

    @staticmethod
    def validate_questions(questions: List[Dict[str, Any]]) -> None:
        """Validate generated questions meet requirements"""
        if not questions:
            raise api_error(
                500,
                "GENERATION_FAILED",
                "No questions were generated.",
            )

        for i, question in enumerate(questions):
            if not question.get("prompt") or not isinstance(question["prompt"], str):
                raise api_error(
                    500,
                    "GENERATION_FAILED",
                    f"Question {i+1}: Invalid or missing prompt.",
                )

            choices = question.get("choices", [])
            if len(choices) != 4:
                raise api_error(
                    500,
                    "GENERATION_FAILED",
                    f"Question {i+1}: Must have exactly 4 choices, got {len(choices)}.",
                )

            correct_choices = [c for c in choices if c.get("is_correct")]
            if len(correct_choices) != 1:
                raise api_error(
                    500,
                    "GENERATION_FAILED",
                    f"Question {i+1}: Must have exactly one correct choice, got {len(correct_choices)}.",
                )

            choice_texts = [c.get("text", "").strip() for c in choices]
            if len(set(choice_texts)) != len(choice_texts):
                raise api_error(
                    500,
                    "GENERATION_FAILED",
                    f"Question {i+1}: Contains duplicate choice texts.",
                )

            for j, choice in enumerate(choices):
                if not choice.get("text") or not isinstance(choice["text"], str):
                    raise api_error(
                        500,
                        "GENERATION_FAILED",
                        f"Question {i+1}, Choice {j+1}: Invalid or missing text.",
                    )

    @staticmethod
    def format_questions_for_response(
        questions: List[Dict[str, Any]],
        include_correct: bool = False,
    ) -> List[Dict[str, Any]]:
        """Format questions for API response"""
        formatted_questions = []

        for q_idx, question in enumerate(questions):
            formatted_question: Dict[str, Any] = {
                "id": f"q_{q_idx + 1}",
                "prompt": question["prompt"],
                "position": question.get("position", q_idx),
                "choices": [],
            }
            if include_correct:
                formatted_question["explanation"] = question.get("explanation")

            sorted_choices = sorted(question["choices"], key=lambda c: c.get("position", 0))

            for c_idx, choice in enumerate(sorted_choices):
                choice_id = chr(97 + c_idx)  # 'a', 'b', 'c', 'd'
                formatted_choice = {
                    "id": choice_id,
                    "text": choice["text"],
                    "position": c_idx,
                }

                if include_correct:
                    formatted_choice["is_correct"] = choice.get("is_correct", False)

                formatted_question["choices"].append(formatted_choice)

            formatted_questions.append(formatted_question)

        return formatted_questions
