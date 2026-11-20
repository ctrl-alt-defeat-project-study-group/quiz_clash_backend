# QuizClash Backend

FastAPI backend for QuizClash - Turn study files into interactive quizzes.

## Features

- **File Upload**: CSV/TXT file upload with validation
- **Quiz Generation**: Automatic multiple-choice question generation from term-definition pairs
- **Quiz Management**: Create, preview, and edit quizzes
- **Quiz Taking**: Submit answers and get server-graded results
- **PDF Export**: Generate questions-only and answer-key PDFs
- **RESTful API**: Clean API following OpenAPI specification

## Technology Stack

- **Python 3.9+**
- **FastAPI**: Modern, fast web framework
- **SQLAlchemy 2.0**: ORM for database operations
- **PostgreSQL**: Primary database
- **Pydantic**: Data validation and settings management
- **ReportLab**: PDF generation
- **Alembic**: Database migrations

## Quick Start

### 1. Prerequisites

- Python 3.9 or higher
- PostgreSQL 12 or higher
- pip (Python package manager)

### 2. Setup

```bash
# Clone the repository
cd /path/to/quizclash/backend

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Linux/Mac:
source .venv/bin/activate
# On Windows:
# .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env

# Edit .env with your database credentials
# DATABASE_URL=postgresql+psycopg2://username:password@localhost:5432/dbname
```

### 3. Database Setup

```bash
# Create PostgreSQL database
createdb quizclash

# Create database tables
python -c "from app.db.session import engine, Base; Base.metadata.create_all(bind=engine)"
```

### 4. Run the Server

```bash
# Development server with auto-reload
uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`

- **API Documentation**: `http://localhost:8000/docs` (Swagger UI)
- **Alternative Docs**: `http://localhost:8000/redoc` (ReDoc)

## API Endpoints

### Health Check
- `GET /api/v1/health` - Service health status

### Quizzes
- `POST /api/v1/quizzes` - Upload file and generate quiz
- `GET /api/v1/quizzes/{quiz_id}` - Get playable quiz (no answers)
- `GET /api/v1/quizzes/{quiz_id}/preview` - Get quiz with answers (for editing)
- `PATCH /api/v1/quizzes/{quiz_id}` - Update quiz

### Attempts
- `POST /api/v1/quizzes/{quiz_id}/attempts` - Submit answers and get results
- `GET /api/v1/attempts/{attempt_id}` - Get attempt results

### Exports
- `GET /api/v1/quizzes/{quiz_id}/exports?kind=questions` - Questions-only PDF
- `GET /api/v1/quizzes/{quiz_id}/exports?kind=answers` - Answer key PDF

## File Format Support

### CSV Files
- Expected format: `term,definition`
- First row can be headers
- Supports UTF-8 encoding
- Example:
  ```
  食べる,to eat
  読む,to read
  書く,to write
  ```

### TXT Files
- Multiple formats supported:
  - `term: definition`
  - `term - definition`
  - One term per line (no definition)
- Example:
  ```
  食べる: to eat
  読む - to read
  書く = to write
  ```

## Development

### Running Tests
```bash
pytest tests/
```

### Database Migrations
```bash
# Initialize Alembic (first time)
alembic init alembic

# Create migration
alembic revision --autogenerate -m "Description"

# Apply migration
alembic upgrade head
```

### Code Formatting
```bash
# Install development dependencies
pip install black isort

# Format code
black app/
isort app/
```

## Project Structure

```
backend/
├── app/
│   ├── main.py                 # FastAPI application
│   ├── core/
│   │   └── config.py           # Configuration settings
│   ├── api/
│   │   └── routes/             # API route handlers
│   │       ├── quizzes.py
│   │       ├── attempts.py
│   │       └── exports.py
│   ├── db/
│   │   ├── session.py          # Database session management
│   │   └── models.py           # SQLAlchemy models
│   ├── schemas/                # Pydantic schemas
│   │   ├── quiz.py
│   │   └── attempt.py
│   └── services/               # Business logic
│       ├── parser.py           # File parsing
│       ├── quiz_generator.py   # Question generation
│       └── pdf_generator.py    # PDF export
├── alembic/                    # Database migrations
├── tests/                      # Test files
├── requirements.txt            # Python dependencies
└── .env.example                # Environment template
```

## Deployment

### Production Considerations

1. **Database**: Use managed PostgreSQL service (AWS RDS, Azure Database, etc.)
2. **Environment Variables**: Set all required variables in production environment
3. **CORS**: Update `FRONTEND_ORIGINS` with production frontend URLs
4. **File Upload Limits**: Adjust `MAX_UPLOAD_SIZE_MB` as needed
5. **Security**: Use HTTPS, implement proper authentication (Phase 2)

### Docker Deployment

```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## License

MIT