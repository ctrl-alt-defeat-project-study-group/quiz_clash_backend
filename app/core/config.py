"""
Application configuration settings
"""
from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+psycopg://quizclash:quizclash@localhost:5432/quizclash"
    
    # CORS
    FRONTEND_ORIGINS: List[str] = [
        "http://localhost:5173",  # Vite default
        "http://localhost:3000",  # Create React App default
    ]
    
    # File upload settings
    MAX_UPLOAD_SIZE_MB: int = 10  # Maximum file size in MB
    ALLOWED_FILE_TYPES: List[str] = [".csv", ".txt"]
    
    # Quiz generation settings
    DEFAULT_QUESTIONS_PER_QUIZ: int = 10
    MIN_DEFINITIONS_FOR_GENERATION: int = 8  # Need at least 8 definitions for 4 choices per question
    
    # LLM Settings (optional)
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: str = "gpt-3.5-turbo"
    LLM_MAX_TOKENS: int = 500
    
    # PDF Generation
    PDF_FONT_NAME: str = "Helvetica"  # For Japanese, we'll need to add a CJK font
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()