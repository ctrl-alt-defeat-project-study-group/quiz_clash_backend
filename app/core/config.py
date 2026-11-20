"""
Application configuration settings
"""
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional, Union


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    # Database
    DATABASE_URL: str = "postgresql+psycopg2://quizclash:quizclash@localhost:5432/quizclash"
    
    # CORS
    FRONTEND_ORIGINS: Union[List[str], str] = [
        "http://localhost:5173",  # Vite default
        "http://localhost:3000",  # Create React App default
    ]

    @field_validator("FRONTEND_ORIGINS", mode="before")
    @classmethod
    def parse_frontend_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v
    
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
    

settings = Settings()