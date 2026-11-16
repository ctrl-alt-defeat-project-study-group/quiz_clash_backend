"""
API routes for quiz exports (PDF generation)
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import tempfile
import os

from app.db.session import get_db
from app.db.models import Quiz, Question, Choice
from app.services.pdf_generator import PDFGenerator

router = APIRouter()


def parse_quiz_id(quiz_id_str: str) -> int:
    """Parse numeric quiz ID from string format"""
    try:
        if '_' in quiz_id_str:
            return int(quiz_id_str.split('_')[-1])
        return int(quiz_id_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid quiz ID format")


@router.get("/quizzes/{quiz_id}/exports")
async def export_quiz_pdf(
    quiz_id: str,
    kind: str = "questions",  # "questions" or "answers"
    db: Session = Depends(get_db)
):
    """
    Export quiz as PDF
    
    - **kind**: "questions" for questions-only PDF, "answers" for answer key PDF
    """
    if kind not in ["questions", "answers"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid kind parameter. Use 'questions' or 'answers'"
        )
    
    # Parse quiz ID
    quiz_numeric_id = parse_quiz_id(quiz_id)
    
    # Get quiz with questions and choices
    db_quiz = db.query(Quiz).filter(Quiz.id == quiz_numeric_id).first()
    if not db_quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    
    # Get all questions sorted by position
    db_questions = db.query(Question).filter(
        Question.quiz_id == quiz_numeric_id
    ).order_by(Question.position).all()
    
    if not db_questions:
        raise HTTPException(status_code=400, detail="Quiz has no questions")
    
    # Prepare data for PDF generation
    questions_data = []
    
    for q_idx, db_question in enumerate(db_questions):
        # Sort choices by position
        sorted_choices = sorted(db_question.choices, key=lambda c: c.position)
        
        question_data = {
            "number": q_idx + 1,
            "prompt": db_question.prompt,
            "choices": []
        }
        
        # Find correct choice for answer key
        correct_choice_letter = None
        for c_idx, db_choice in enumerate(sorted_choices):
            choice_letter = chr(97 + c_idx)  # 'a', 'b', 'c', 'd'
            question_data["choices"].append({
                "letter": choice_letter,
                "text": db_choice.text
            })
            
            if db_choice.is_correct:
                correct_choice_letter = choice_letter
        
        # Add correct answer for answer key
        if kind == "answers":
            question_data["correct_answer"] = correct_choice_letter
        
        questions_data.append(question_data)
    
    # Generate PDF
    pdf_generator = PDFGenerator()
    
    # Create temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
        pdf_path = tmp_file.name
        
        if kind == "questions":
            pdf_generator.generate_questions_pdf(
                quiz_title=db_quiz.title,
                questions=questions_data,
                output_path=pdf_path
            )
            filename = f"quiz_questions_{db_quiz.title.replace(' ', '_')}.pdf"
        else:  # answers
            pdf_generator.generate_answers_pdf(
                quiz_title=db_quiz.title,
                questions=questions_data,
                output_path=pdf_path
            )
            filename = f"quiz_answers_{db_quiz.title.replace(' ', '_')}.pdf"
    
    try:
        # Return PDF file
        return FileResponse(
            path=pdf_path,
            filename=filename,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
    finally:
        # Clean up temporary file after sending
        try:
            os.unlink(pdf_path)
        except:
            pass  # Ignore cleanup errors