"""
Service for generating multiple choice questions from parsed content
"""
import random
from typing import List, Tuple, Dict, Any, Optional
from fastapi import HTTPException
from app.core.config import settings


class QuizGenerator:
    """Generate multiple choice questions from terms and definitions"""
    
    @staticmethod
    def generate_from_structured(
        terms_definitions: List[Tuple[str, str]],
        question_count: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate MCQs from structured term-definition pairs
        
        Args:
            terms_definitions: List of (term, definition) tuples
            question_count: Number of questions to generate (default: all or up to max)
            
        Returns:
            List of question dictionaries with prompt and choices
        """
        if not terms_definitions:
            raise HTTPException(
                status_code=400,
                detail="No valid terms and definitions found"
            )
        
        # Filter out entries with empty definitions
        valid_pairs = [(t, d) for t, d in terms_definitions if d.strip()]
        
        if len(valid_pairs) < settings.MIN_DEFINITIONS_FOR_GENERATION:
            raise HTTPException(
                status_code=400,
                detail=f"Need at least {settings.MIN_DEFINITIONS_FOR_GENERATION} "
                       f"terms with definitions to generate questions. "
                       f"Found only {len(valid_pairs)}."
            )
        
        # Determine how many questions to generate
        if question_count is None:
            # Use all valid pairs, but cap at a reasonable number
            question_count = min(len(valid_pairs), settings.DEFAULT_QUESTIONS_PER_QUIZ)
        else:
            question_count = min(question_count, len(valid_pairs))
        
        # Shuffle pairs for random selection
        random.shuffle(valid_pairs)
        selected_pairs = valid_pairs[:question_count]
        
        questions = []
        
        for idx, (term, correct_definition) in enumerate(selected_pairs):
            # Generate distractors from other definitions
            all_definitions = [d for _, d in valid_pairs if d != correct_definition]
            
            if len(all_definitions) < 3:
                # Not enough unique definitions for distractors
                continue
            
            # Select 3 unique distractors
            distractors = random.sample(all_definitions, 3)
            
            # Create choices
            choices = [
                {"text": correct_definition, "is_correct": True, "position": 0}
            ]
            
            for i, distractor in enumerate(distractors, 1):
                choices.append({
                    "text": distractor,
                    "is_correct": False,
                    "position": i
                })
            
            # Shuffle choices (but keep track of correct position)
            random.shuffle(choices)
            
            # Find correct choice position after shuffling
            for i, choice in enumerate(choices):
                if choice["is_correct"]:
                    choice["position"] = i
                else:
                    choice["position"] = i
            
            # Create question
            question = {
                "prompt": f"What does '{term}' mean?",
                "position": idx,
                "choices": choices
            }
            
            questions.append(question)
        
        return questions
    
    @staticmethod
    def validate_questions(questions: List[Dict[str, Any]]) -> None:
        """Validate generated questions meet requirements"""
        if not questions:
            raise HTTPException(
                status_code=400,
                detail="No questions were generated"
            )
        
        for i, question in enumerate(questions):
            # Check prompt
            if not question.get("prompt") or not isinstance(question["prompt"], str):
                raise HTTPException(
                    status_code=500,
                    detail=f"Question {i+1}: Invalid or missing prompt"
                )
            
            # Check choices
            choices = question.get("choices", [])
            if len(choices) != 4:
                raise HTTPException(
                    status_code=500,
                    detail=f"Question {i+1}: Must have exactly 4 choices, got {len(choices)}"
                )
            
            # Check for exactly one correct choice
            correct_choices = [c for c in choices if c.get("is_correct")]
            if len(correct_choices) != 1:
                raise HTTPException(
                    status_code=500,
                    detail=f"Question {i+1}: Must have exactly one correct choice, got {len(correct_choices)}"
                )
            
            # Check for duplicate choice texts
            choice_texts = [c.get("text", "").strip() for c in choices]
            if len(set(choice_texts)) != len(choice_texts):
                raise HTTPException(
                    status_code=500,
                    detail=f"Question {i+1}: Contains duplicate choice texts"
                )
            
            # Check choice texts are not empty
            for j, choice in enumerate(choices):
                if not choice.get("text") or not isinstance(choice["text"], str):
                    raise HTTPException(
                        status_code=500,
                        detail=f"Question {i+1}, Choice {j+1}: Invalid or missing text"
                    )
    
    @staticmethod
    def format_questions_for_response(
        questions: List[Dict[str, Any]],
        include_correct: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Format questions for API response
        
        Args:
            questions: Raw question data
            include_correct: Whether to include is_correct field in response
            
        Returns:
            Formatted questions with choice IDs (a, b, c, d)
        """
        formatted_questions = []
        
        for q_idx, question in enumerate(questions):
            formatted_question = {
                "id": f"q_{q_idx + 1}",
                "prompt": question["prompt"],
                "position": question.get("position", q_idx),
                "choices": []
            }
            
            # Sort choices by position
            sorted_choices = sorted(question["choices"], key=lambda c: c.get("position", 0))
            
            for c_idx, choice in enumerate(sorted_choices):
                choice_id = chr(97 + c_idx)  # 'a', 'b', 'c', 'd'
                formatted_choice = {
                    "id": choice_id,
                    "text": choice["text"],
                    "position": c_idx
                }
                
                if include_correct:
                    formatted_choice["is_correct"] = choice.get("is_correct", False)
                
                formatted_question["choices"].append(formatted_choice)
            
            formatted_questions.append(formatted_question)
        
        return formatted_questions