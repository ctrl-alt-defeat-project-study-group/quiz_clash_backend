"""
Service for parsing and extracting content from uploaded files
"""
import csv
import io
from typing import List, Optional, Tuple
from fastapi import UploadFile, HTTPException

from app.core.config import settings


class FileParser:
    """Parse uploaded files to extract structured content"""

    _SPACED_SEPARATORS = (": ", " - ", " – ", " — ", " -> ", " → ", " = ")
    _COMPACT_SEPARATORS = (":", "=", "→", "-")

    @staticmethod
    def _parse_txt_line(line: str) -> Tuple[str, str]:
        """Parse a single non-empty TXT line into a (term, definition) pair."""
        # Prefer the earliest spaced separator so definitions containing other punctuation stay intact
        best_sep = None
        best_idx = len(line)
        for sep in FileParser._SPACED_SEPARATORS:
            idx = line.find(sep)
            if idx != -1 and idx < best_idx:
                best_idx = idx
                best_sep = sep

        if best_sep is not None:
            term, definition = line.split(best_sep, 1)
            return term.strip(), definition.strip()

        for sep in FileParser._COMPACT_SEPARATORS:
            if sep in line:
                term, definition = line.split(sep, 1)
                return term.strip(), definition.strip()

        return line, ""

    @staticmethod
    def parse_csv(file: UploadFile) -> List[Tuple[str, str]]:
        """Parse CSV file expecting term,definition format"""
        try:
            content = file.file.read().decode("utf-8")
            file.file.seek(0)  # Reset file pointer

            reader = csv.reader(io.StringIO(content))
            terms_definitions: List[Tuple[str, str]] = []

            for row in reader:
                if len(row) >= 2:
                    term = row[0].strip()
                    definition = row[1].strip()
                    if term and definition:  # Skip empty rows
                        terms_definitions.append((term, definition))
                elif len(row) == 1 and row[0].strip():
                    # Single column - treat as term only
                    terms_definitions.append((row[0].strip(), ""))

            if not terms_definitions:
                raise HTTPException(
                    status_code=400,
                    detail="CSV file is empty or contains no valid term-definition pairs",
                )

            return terms_definitions

        except HTTPException:
            raise
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=400,
                detail="File encoding error. Please upload UTF-8 encoded files.",
            )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error parsing CSV file: {str(e)}",
            )

    @staticmethod
    def parse_txt(file: UploadFile) -> List[Tuple[str, str]]:
        """Parse TXT file line by line across supported separator formats"""
        try:
            content = file.file.read().decode("utf-8")
            file.file.seek(0)  # Reset file pointer

            terms_definitions: List[Tuple[str, str]] = []

            for raw_line in content.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                term, definition = FileParser._parse_txt_line(line)
                if term:
                    terms_definitions.append((term, definition))

            if not terms_definitions:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "TXT file is empty or contains no parsable content. "
                        "Expected format: term: definition or term - definition"
                    ),
                )

            return terms_definitions

        except HTTPException:
            raise
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=400,
                detail="File encoding error. Please upload UTF-8 encoded files.",
            )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error parsing TXT file: {str(e)}",
            )

    @staticmethod
    def parse_file(file: UploadFile) -> List[Tuple[str, str]]:
        """Parse file based on file extension"""
        filename = (file.filename or "").lower()

        if filename.endswith(".csv"):
            return FileParser.parse_csv(file)
        if filename.endswith(".txt"):
            return FileParser.parse_txt(file)

        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {filename}. Only .csv and .txt files are supported.",
        )

    @staticmethod
    def validate_file(file: UploadFile, max_size_mb: Optional[int] = None) -> None:
        """Validate uploaded file"""
        limit_mb = settings.MAX_UPLOAD_SIZE_MB if max_size_mb is None else max_size_mb

        # Check file size
        file.file.seek(0, 2)  # Seek to end
        file_size = file.file.tell()
        file.file.seek(0)  # Reset to beginning

        max_size = limit_mb * 1024 * 1024
        if file_size > max_size:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size is {limit_mb}MB",
            )

        if file_size == 0:
            raise HTTPException(
                status_code=400,
                detail="File is empty",
            )

        # Check file extension
        filename = (file.filename or "").lower()
        allowed_extensions = tuple(ext.lower() for ext in settings.ALLOWED_FILE_TYPES)
        if not filename.endswith(allowed_extensions):
            allowed_str = ", ".join(settings.ALLOWED_FILE_TYPES)
            raise HTTPException(
                status_code=400,
                detail=f"Only {allowed_str} files are supported",
            )
