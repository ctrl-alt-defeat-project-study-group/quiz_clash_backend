"""
QuizClash Backend - Main FastAPI Application
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.csrf import CSRFOriginMiddleware
from app.core.errors import (
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.production import validate_production_settings
from app.api.routes import (
    admin,
    attempts,
    auth,
    exports,
    live,
    quizzes,
    settings as settings_routes,
)
from app.services.bootstrap import seed_initial_admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast on unsafe production settings; schema is managed by Alembic migrations
    validate_production_settings(settings)
    seed_initial_admin()
    yield


# Create FastAPI app
app = FastAPI(
    title="QuizClash API",
    description="Backend API for QuizClash - Turn study files into interactive quizzes",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CSRF protection for state-changing requests
app.add_middleware(CSRFOriginMiddleware)

# Register global exception handlers
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

# Include API routers
app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(admin.router, prefix="/api/v1", tags=["admin"])
app.include_router(quizzes.router, prefix="/api/v1", tags=["quizzes"])
app.include_router(attempts.router, prefix="/api/v1", tags=["attempts"])
app.include_router(exports.router, prefix="/api/v1", tags=["exports"])
app.include_router(live.router, prefix="/api/v1", tags=["live"])
app.include_router(settings_routes.router, prefix="/api/v1", tags=["settings"])


# Health check endpoint
@app.get("/api/v1/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "service": "quiz-clash-api"}


@app.get("/")
async def root():
    """Root endpoint with API info"""
    return {
        "message": "QuizClash Backend API",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
