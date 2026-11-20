from setuptools import setup, find_packages

setup(
    name="quizclash-backend",
    version="1.0.0",
    description="FastAPI backend for QuizClash",
    author="QuizClash Team",
    packages=find_packages(),
    install_requires=[
        "fastapi==0.104.1",
        "uvicorn[standard]==0.24.0",
        "python-multipart==0.0.6",
        "sqlalchemy==2.0.23",
        "psycopg2-binary==2.9.9",
        "alembic==1.13.1",
        "pydantic==2.5.0",
        "pydantic-settings==2.1.0",
        "email-validator>=2.1.0",
        "argon2-cffi>=23.1.0",
        "PyJWT>=2.8.0",
        "reportlab==4.0.4",
    ],
    python_requires=">=3.9",
)