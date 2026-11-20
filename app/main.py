"""
QuizClash Backend - Main FastAPI Application
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.csrf import CSRFOriginMiddleware
from app.api.routes import admin, attempts, auth, exports, quizzes
from app.services.bootstrap import seed_initial_admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is managed by Alembic migrations (not create_all at startup)
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

# Include API routers
app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(admin.router, prefix="/api/v1", tags=["admin"])
app.include_router(quizzes.router, prefix="/api/v1", tags=["quizzes"])
app.include_router(attempts.router, prefix="/api/v1", tags=["attempts"])
app.include_router(exports.router, prefix="/api/v1", tags=["exports"])


# Health check endpoint
@app.get("/api/v1/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "QuizClash API"}


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
