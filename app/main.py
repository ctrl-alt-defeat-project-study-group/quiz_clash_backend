"""
QuizClash Backend - Main FastAPI Application
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.api.routes import quizzes, attempts, exports
from app.db.session import engine, Base
from app.db.session import get_db

# Create database tables on startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create database tables
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    
    yield
    
    # Shutdown: Cleanup if needed
    print("Shutting down...")

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

# Include API routers
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
        "redoc": "/redoc"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)