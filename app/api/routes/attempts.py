"""
API routes for quiz attempts
"""
from typing import Dict, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import Quiz, Question, Choice, Attempt, AttemptAnswer
from app.schemas.attempt import AttemptCreate, AttemptResponse

router = APIRouter()


def parse_quiz_id(quiz_id_str: str) -> int:
    """Parse numeric quiz ID from string format"""
    try:
        if '_' in quiz_id_str:
            return int(quiz_id_str.split('_')[-1])
        return int(quiz_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid quiz ID format")


def parse_question_id(question_id_str: str) -> int:
    """Parse numeric question ID from string format"""
    try:
        if '_' in question_id_str:
            return int(question_id_str.split('_')[-1])
        return int(question_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid question ID format")


def get_choice_mapping(questions: List[Question]) -> Dict[str, Dict[str, int]]:
    """
    Create mapping from API choice IDs (a, b, c, d) to database choice IDs
    
    Returns: {question_id: {choice_letter: db_choice_id}}
    """
    choice_mapping = {}
    
    for question in questions:
        # Sort choices by position
        sorted_choices = sorted(question.choices, key=lambda c: c.position)
        question_mapping = {}
        
        for idx, choice in enumerate(sorted_choices):
            choice_letter = chr(97 + idx)  # 'a', 'b', 'c', 'd'
            question_mapping[choice_letter] = choice.id
        
        # Use string format for question ID in mapping
        question_key = f"q_{question.id}"
        choice_mapping[question_key] = question_mapping
    
    return choice_mapping


@router.post("/quizzes/{quiz_id}/attempts", response_model=AttemptResponse)
async def submit_attempt(
    quiz_id: str,
    attempt_data: AttemptCreate,
    db: Session = Depends(get_db)
):
    """
    Submit answers for a quiz and get graded results
    
    - Calculates score on server
    - Stores attempt in database
    - Returns detailed results
    """
    # Parse quiz ID
    quiz_numeric_id = parse_quiz_id(quiz_id)
    
    # Get quiz with questions and choices
    db_quiz = db.query(Quiz).filter(Quiz.id == quiz_numeric_id).first()
    if not db_quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    
    # Get all questions for this quiz
    db_questions = db.query(Question).filter(Question.quiz_id == quiz_numeric_id).all()
    if not db_questions:
        raise HTTPException(status_code=400, detail="Quiz has no questions")
    
    # Create choice mapping
    choice_mapping = get_choice_mapping(db_questions)
    
    # Create database attempt
    db_attempt = Attempt(
        quiz_id=quiz_numeric_id,
        score=0,
        total_questions=len(db_questions)
    )
    db.add(db_attempt)
    db.flush()  # Get attempt ID
    
    # Process each answer
    correct_count = 0
    question_results = []
    
    # Create a mapping from question string ID to database question
    question_map = {f"q_{q.id}": q for q in db_questions}
    
    for answer in attempt_data.answers:
        # Get question from mapping
        db_question = question_map.get(answer.question_id)
        if not db_question:
            # Question not found in this quiz
            continue
        
        # Get correct choice for this question
        correct_choice = None
        for choice in db_question.choices:
            if choice.is_correct:
                correct_choice = choice
                break
        
        if not correct_choice:
            # No correct choice defined (shouldn't happen with validation)
            continue
        
        # Get selected choice ID from mapping
        question_choice_map = choice_mapping.get(answer.question_id, {})
        selected_db_choice_id = question_choice_map.get(answer.choice_id)
        
        if not selected_db_choice_id:
            # Invalid choice letter
            continue
        
        # Get selected choice from database
        selected_choice = db.query(Choice).filter(Choice.id == selected_db_choice_id).first()
        if not selected_choice:
            continue
        
        # Check if answer is correct
        is_correct = (selected_choice.id == correct_choice.id)
        
        if is_correct:
            correct_count += 1
        
        # Create attempt answer record
        db_attempt_answer = AttemptAnswer(
            attempt_id=db_attempt.id,
            question_id=db_question.id,
            choice_id=selected_choice.id,
            is_correct=is_correct
        )
        db.add(db_attempt_answer)
        
        # Prepare result for response
        question_result = {
            "question_id": answer.question_id,
            "question_prompt": db_question.prompt,
            "selected_choice_id": answer.choice_id,
            "selected_choice_text": selected_choice.text,
            "correct_choice_id": get_choice_letter(db_question.choices, correct_choice.id),
            "correct_choice_text": correct_choice.text,
            "is_correct": is_correct
        }
        question_results.append(question_result)
    
    # Update attempt score
    db_attempt.score = correct_count
    
    # Calculate percentage
    percentage = (correct_count / len(db_questions) * 100) if db_questions else 0
    
    db.commit()
    db.refresh(db_attempt)
    
    # Return response
    return {
        "id": f"attempt_{db_attempt.id}",
        "quiz_id": f"quiz_{quiz_numeric_id}",
        "score": correct_count,
        "total_questions": len(db_questions),
        "percentage": round(percentage, 2),
        "completed_at": db_attempt.completed_at,
        "questions": question_results
    }


@router.get("/attempts/{attempt_id}", response_model=AttemptResponse)
async def get_attempt(
    attempt_id: str,
    db: Session = Depends(get_db)
):
    """
    Get attempt results by ID
    """
    # Parse attempt ID
    try:
        if '_' in attempt_id:
            attempt_numeric_id = int(attempt_id.split('_')[-1])
        else:
            attempt_numeric_id = int(attempt_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    # Get attempt with answers
    db_attempt = db.query(Attempt).filter(Attempt.id == attempt_numeric_id).first()
    if not db_attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    # Get quiz
    db_quiz = db.query(Quiz).filter(Quiz.id == db_attempt.quiz_id).first()
    if not db_quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    
    # Get all attempt answers with related data
    db_answers = db.query(AttemptAnswer).filter(
        AttemptAnswer.attempt_id == attempt_numeric_id
    ).all()
    
    question_results = []
    
    for db_answer in db_answers:
        # Get question
        db_question = db.query(Question).filter(Question.id == db_answer.question_id).first()
        if not db_question:
            continue
        
        # Get selected choice
        selected_choice = db.query(Choice).filter(Choice.id == db_answer.choice_id).first()
        if not selected_choice:
            continue
        
        # Get correct choice for this question
        correct_choice = None
        for choice in db_question.choices:
            if choice.is_correct:
                correct_choice = choice
                break
        
        if not correct_choice:
            continue
        
        # Prepare result
        question_result = {
            "question_id": f"q_{db_question.id}",
            "question_prompt": db_question.prompt,
            "selected_choice_id": get_choice_letter(db_question.choices, selected_choice.id),
            "selected_choice_text": selected_choice.text,
            "correct_choice_id": get_choice_letter(db_question.choices, correct_choice.id),
            "correct_choice_text": correct_choice.text,
            "is_correct": db_answer.is_correct
        }
        question_results.append(question_result)
    
    # Calculate percentage
    percentage = (db_attempt.score / db_attempt.total_questions * 100) if db_attempt.total_questions > 0 else 0
    
    return {
        "id": f"attempt_{db_attempt.id}",
        "quiz_id": f"quiz_{db_attempt.quiz_id}",
        "score": db_attempt.score,
        "total_questions": db_attempt.total_questions,
        "percentage": round(percentage, 2),
        "completed_at": db_attempt.completed_at,
        "questions": question_results
    }


def get_choice_letter(choices: List[Choice], target_choice_id: int) -> str:
    """Get choice letter (a, b, c, d) from database choice ID"""
    # Sort choices by position
    sorted_choices = sorted(choices, key=lambda c: c.position)
    
    for idx, choice in enumerate(sorted_choices):
        if choice.id == target_choice_id:
            return chr(97 + idx)  # 'a', 'b', 'c', 'd'
    
    return "?"  # Should not happen with valid data