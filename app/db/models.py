"""
SQLAlchemy database models
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base


class Quiz(Base):
    __tablename__ = "quizzes"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False, default="Untitled Quiz")
    source_type = Column(String(50), nullable=False)  # "csv", "txt", "structured", "llm"
    source_hash = Column(String(64), nullable=True)  # For duplicate detection
    status = Column(String(50), nullable=False, default="draft")  # draft, published, archived
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    questions = relationship("Question", back_populates="quiz", cascade="all, delete-orphan")
    attempts = relationship("Attempt", back_populates="quiz", cascade="all, delete-orphan")
    
    # For Phase 2: owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # owner = relationship("User", back_populates="quizzes")


class Question(Base):
    __tablename__ = "questions"
    
    id = Column(Integer, primary_key=True, index=True)
    quiz_id = Column(Integer, ForeignKey("quizzes.id"), nullable=False)
    prompt = Column(Text, nullable=False)
    position = Column(Integer, nullable=False, default=0)  # Order in quiz
    
    # Relationships
    quiz = relationship("Quiz", back_populates="questions")
    choices = relationship("Choice", back_populates="question", cascade="all, delete-orphan")


class Choice(Base):
    __tablename__ = "choices"
    
    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    text = Column(Text, nullable=False)
    is_correct = Column(Boolean, nullable=False, default=False)
    position = Column(Integer, nullable=False, default=0)  # Order in question
    
    # Relationships
    question = relationship("Question", back_populates="choices")
    # For attempt tracking
    attempt_answers = relationship("AttemptAnswer", back_populates="choice")


class Attempt(Base):
    __tablename__ = "attempts"
    
    id = Column(Integer, primary_key=True, index=True)
    quiz_id = Column(Integer, ForeignKey("quizzes.id"), nullable=False)
    score = Column(Integer, nullable=False, default=0)
    total_questions = Column(Integer, nullable=False)
    completed_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    quiz = relationship("Quiz", back_populates="attempts")
    answers = relationship("AttemptAnswer", back_populates="attempt", cascade="all, delete-orphan")
    
    # For Phase 2: user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # user = relationship("User", back_populates="attempts")


class AttemptAnswer(Base):
    __tablename__ = "attempt_answers"
    
    id = Column(Integer, primary_key=True, index=True)
    attempt_id = Column(Integer, ForeignKey("attempts.id"), nullable=False)
    question_id = Column(Integer, nullable=False)  # Reference to question, not ForeignKey for flexibility
    choice_id = Column(Integer, nullable=False)  # Reference to choice
    is_correct = Column(Boolean, nullable=False)
    
    # Relationships
    attempt = relationship("Attempt", back_populates="answers")
    choice = relationship("Choice", back_populates="attempt_answers")


# Phase 2: User model
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships (commented out for Phase 1)
    # quizzes = relationship("Quiz", back_populates="owner")
    # attempts = relationship("Attempt", back_populates="user")