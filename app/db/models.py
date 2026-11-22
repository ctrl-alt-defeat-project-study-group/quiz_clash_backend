"""
SQLAlchemy database models
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=True)
    display_name = Column(String(100), nullable=False, default="User")
    avatar_url = Column(String(500), nullable=True)
    role = Column(String(20), nullable=False, default="user")  # "user" | "admin"
    is_active = Column(Boolean, nullable=False, default=True)
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    quizzes = relationship(
        "Quiz",
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    attempts = relationship(
        "Attempt",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    email_tokens = relationship(
        "EmailToken",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    oauth_accounts = relationship(
        "OAuthAccount",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    settings = relationship(
        "UserSettings",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    hosted_rooms = relationship(
        "LiveRoom",
        back_populates="host",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def has_password(self) -> bool:
        return bool(self.password_hash)

    @property
    def oauth_providers(self):
        return sorted({acct.provider for acct in (self.oauth_accounts or [])})


class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
        UniqueConstraint("user_id", "provider", name="uq_oauth_user_provider"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = Column(String(32), nullable=False, index=True)  # "google"
    provider_user_id = Column(String(255), nullable=False)
    provider_email = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="oauth_accounts")


class EmailToken(Base):
    __tablename__ = "email_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purpose = Column(String(20), nullable=False)  # "verify" | "reset"
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="email_tokens")


class Quiz(Base):
    __tablename__ = "quizzes"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title = Column(String(255), nullable=False, default="Untitled Quiz")
    category = Column(String(100), nullable=True)
    source_type = Column(String(50), nullable=False)  # "csv", "txt", "structured", "llm"
    source_filename = Column(String(255), nullable=True)
    source_hash = Column(String(64), nullable=True, index=True)  # For duplicate detection
    status = Column(String(50), nullable=False, default="ready")  # ready, draft, published, archived
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    owner = relationship("User", back_populates="quizzes")
    questions = relationship(
        "Question",
        back_populates="quiz",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    attempts = relationship(
        "Attempt",
        back_populates="quiz",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    live_rooms = relationship(
        "LiveRoom",
        back_populates="quiz",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    quiz_id = Column(
        Integer,
        ForeignKey("quizzes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    prompt = Column(Text, nullable=False)
    position = Column(Integer, nullable=False, default=0)  # Order in quiz
    explanation = Column(Text, nullable=True)

    # Relationships
    quiz = relationship("Quiz", back_populates="questions")
    choices = relationship(
        "Choice",
        back_populates="question",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    attempt_answers = relationship(
        "AttemptAnswer",
        back_populates="question",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Choice(Base):
    __tablename__ = "choices"

    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(
        Integer,
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text = Column(Text, nullable=False)
    is_correct = Column(Boolean, nullable=False, default=False)
    position = Column(Integer, nullable=False, default=0)  # Order in question

    # Relationships
    question = relationship("Question", back_populates="choices")
    attempt_answers = relationship(
        "AttemptAnswer",
        back_populates="choice",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Attempt(Base):
    __tablename__ = "attempts"

    id = Column(Integer, primary_key=True, index=True)
    quiz_id = Column(
        Integer,
        ForeignKey("quizzes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    score = Column(Integer, nullable=False, default=0)
    total_questions = Column(Integer, nullable=False)
    duration_seconds = Column(Integer, nullable=True)
    completed_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    quiz = relationship("Quiz", back_populates="attempts")
    user = relationship("User", back_populates="attempts")
    answers = relationship(
        "AttemptAnswer",
        back_populates="attempt",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AttemptAnswer(Base):
    __tablename__ = "attempt_answers"

    id = Column(Integer, primary_key=True, index=True)
    attempt_id = Column(
        Integer,
        ForeignKey("attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id = Column(
        Integer,
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    choice_id = Column(
        Integer,
        ForeignKey("choices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_correct = Column(Boolean, nullable=False)

    # Relationships
    attempt = relationship("Attempt", back_populates="answers")
    question = relationship("Question", back_populates="attempt_answers")
    choice = relationship("Choice", back_populates="attempt_answers")


class LiveRoom(Base):
    __tablename__ = "live_rooms"

    id = Column(Integer, primary_key=True, index=True)
    quiz_id = Column(
        Integer,
        ForeignKey("quizzes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    host_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pin = Column(String(16), unique=True, index=True, nullable=False)
    timer_seconds = Column(Integer, nullable=False, default=20)
    status = Column(String(20), nullable=False, default="lobby")  # lobby, active, finished, closed
    results_json = Column(Text, nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    quiz = relationship("Quiz", back_populates="live_rooms")
    host = relationship("User", back_populates="hosted_rooms")


class UserSettings(Base):
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    theme = Column(String(20), nullable=False, default="system")
    ui_language = Column(String(10), nullable=False, default="en")
    default_questions = Column(Integer, nullable=False, default=10)
    difficulty = Column(String(30), nullable=False, default="Mixed")
    quiz_language = Column(String(30), nullable=False, default="English")
    shuffle_questions = Column(Boolean, nullable=False, default=True)
    show_explanations = Column(Boolean, nullable=False, default=True)
    study_reminders = Column(Boolean, nullable=False, default=False)
    weekly_summary = Column(Boolean, nullable=False, default=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    user = relationship("User", back_populates="settings")
