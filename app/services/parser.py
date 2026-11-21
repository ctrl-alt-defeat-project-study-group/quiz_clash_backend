"""
Service for parsing and extracting content from uploaded files (.csv, .txt, .pdf, .docx)
"""
import csv
import io
from typing import List, Optional, Tuple
from fastapi import HTTPException, UploadFile

from app.core.config import settings
from app.core.errors import api_error


class FileParser:
    """Parse uploaded files to extract structured (term, definition) content"""

    _SPACED_SEPARATORS = (": ", " - ", " – ", " — ", " -> ", " → ", " = ", " ၊ ")
    _COMPACT_SEPARATORS = (":", "=", "→", "-", "၊")

    @staticmethod
    def _split_entries(text: str) -> List[str]:
        """Split text into individual candidate lines, supporting Myanmar '။' delimiters."""
        entries: List[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if "။" in line:
                for segment in line.split("။"):
                    cleaned = segment.strip()
                    if cleaned:
                        entries.append(cleaned)
            else:
                entries.append(line)
        return entries

    @staticmethod
    def _parse_txt_line(line: str) -> Tuple[str, str]:
        """Parse a single non-empty line into a (term, definition) pair."""
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

        return line.strip(), ""

    @staticmethod
    def _parse_text_lines(content: str) -> List[Tuple[str, str]]:
        """Parse extracted plain text into (term, definition) pairs."""
        terms_definitions: List[Tuple[str, str]] = []
        for entry in FileParser._split_entries(content):
            term, definition = FileParser._parse_txt_line(entry)
            if term:
                terms_definitions.append((term, definition))
        return terms_definitions

    @staticmethod
    def parse_csv(file: UploadFile) -> List[Tuple[str, str]]:
        """Parse CSV file expecting term,definition format (UTF-8 BOM-safe)."""
        try:
            content = file.file.read().decode("utf-8-sig")
            file.file.seek(0)

            reader = csv.reader(io.StringIO(content))
            terms_definitions: List[Tuple[str, str]] = []

            for row in reader:
                if len(row) >= 2:
                    term = row[0].strip()
                    definition = row[1].strip()
                    if term and definition:
                        terms_definitions.append((term, definition))
                elif len(row) == 1 and row[0].strip():
                    terms_definitions.append((row[0].strip(), ""))

            if not terms_definitions:
                raise api_error(
                    400,
                    "EMPTY_FILE",
                    "CSV file is empty or contains no valid term-definition pairs.",
                )

            return terms_definitions

        except HTTPException:
            raise
        except UnicodeDecodeError:
            raise api_error(
                400,
                "VALIDATION_ERROR",
                "File encoding error. Please upload UTF-8 encoded files.",
            )
        except Exception as e:
            raise api_error(
                400,
                "VALIDATION_ERROR",
                f"Error parsing CSV file: {str(e)}",
            )

    @staticmethod
    def parse_txt(file: UploadFile) -> List[Tuple[str, str]]:
        """Parse TXT file line by line across supported EN/MM separator formats."""
        try:
            content = file.file.read().decode("utf-8-sig")
            file.file.seek(0)

            terms_definitions = FileParser._parse_text_lines(content)

            if not terms_definitions:
                raise api_error(
                    400,
                    "EMPTY_FILE",
                    "TXT file is empty or contains no parsable content. "
                    "Expected format: term: definition or term - definition",
                )

            return terms_definitions

        except HTTPException:
            raise
        except UnicodeDecodeError:
            raise api_error(
                400,
                "VALIDATION_ERROR",
                "File encoding error. Please upload UTF-8 encoded files.",
            )
        except Exception as e:
            raise api_error(
                400,
                "VALIDATION_ERROR",
                f"Error parsing TXT file: {str(e)}",
            )

    @staticmethod
    def parse_pdf(file: UploadFile) -> List[Tuple[str, str]]:
        """Extract text from a PDF file using pypdf and parse term-definition pairs."""
        from pypdf import PdfReader

        try:
            raw_bytes = file.file.read()
            file.file.seek(0)

            reader = PdfReader(io.BytesIO(raw_bytes))
            extracted_pages = []
            for page in reader.pages:
                text = page.extract_text() or ""
                if text.strip():
                    extracted_pages.append(text)

            full_text = "\n".join(extracted_pages).strip()
            if not full_text:
                raise api_error(
                    400,
                    "EMPTY_FILE",
                    "PDF file contains no readable study text.",
                )

            terms_definitions = FileParser._parse_text_lines(full_text)
            if not terms_definitions:
                raise api_error(
                    400,
                    "EMPTY_FILE",
                    "PDF file contains no readable term-definition pairs.",
                )

            return terms_definitions

        except HTTPException:
            raise
        except Exception as e:
            raise api_error(
                400,
                "EMPTY_FILE",
                f"Unable to read text from PDF file: {str(e)}",
            )

    @staticmethod
    def parse_docx(file: UploadFile) -> List[Tuple[str, str]]:
        """Extract text from a Word (.docx) file using python-docx."""
        from docx import Document

        try:
            raw_bytes = file.file.read()
            file.file.seek(0)

            doc = Document(io.BytesIO(raw_bytes))
            terms_definitions: List[Tuple[str, str]] = []

            # Parse paragraphs
            paragraph_lines = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
            if paragraph_lines:
                terms_definitions.extend(
                    FileParser._parse_text_lines("\n".join(paragraph_lines))
                )

            # Parse 2+ column tables as direct (term, definition) pairs
            for table in doc.tables:
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    if len(cells) >= 2 and cells[0] and cells[1]:
                        terms_definitions.append((cells[0], cells[1]))
                    elif len(cells) == 1 and cells[0]:
                        terms_definitions.extend(FileParser._parse_text_lines(cells[0]))

            if not terms_definitions:
                raise api_error(
                    400,
                    "EMPTY_FILE",
                    "DOCX file contains no readable study text.",
                )

            return terms_definitions

        except HTTPException:
            raise
        except Exception as e:
            raise api_error(
                400,
                "EMPTY_FILE",
                f"Unable to read text from DOCX file: {str(e)}",
            )

    @staticmethod
    def extract_raw_text(file: UploadFile) -> str:
        """Extract raw plain text from CSV, TXT, PDF, or DOCX without requiring term:definition pairs."""
        filename = (file.filename or "").lower()

        if filename.endswith((".csv", ".txt")):
            try:
                text = file.file.read().decode("utf-8-sig").strip()
            except UnicodeDecodeError:
                raise api_error(
                    400,
                    "VALIDATION_ERROR",
                    "File encoding error. Please upload UTF-8 encoded files.",
                )
            finally:
                file.file.seek(0)

            if not text:
                raise api_error(
                    400,
                    "EMPTY_FILE",
                    "File is empty or contains no readable study text.",
                )
            return text

        if filename.endswith(".pdf"):
            from pypdf import PdfReader

            try:
                raw_bytes = file.file.read()
                file.file.seek(0)

                reader = PdfReader(io.BytesIO(raw_bytes))
                extracted_pages = [
                    (page.extract_text() or "").strip()
                    for page in reader.pages
                ]
                full_text = "\n\n".join(p for p in extracted_pages if p).strip()
                if not full_text:
                    raise api_error(
                        400,
                        "EMPTY_FILE",
                        "PDF file contains no readable study text.",
                    )
                return full_text
            except HTTPException:
                raise
            except Exception as e:
                raise api_error(
                    400,
                    "EMPTY_FILE",
                    f"Unable to read text from PDF file: {str(e)}",
                )

        if filename.endswith(".docx"):
            from docx import Document

            try:
                raw_bytes = file.file.read()
                file.file.seek(0)

                doc = Document(io.BytesIO(raw_bytes))
                parts: List[str] = [
                    p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()
                ]
                for table in doc.tables:
                    for row in table.rows:
                        cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                        if cells:
                            parts.append(" | ".join(cells))

                full_text = "\n".join(parts).strip()
                if not full_text:
                    raise api_error(
                        400,
                        "EMPTY_FILE",
                        "DOCX file contains no readable study text.",
                    )
                return full_text
            except HTTPException:
                raise
            except Exception as e:
                raise api_error(
                    400,
                    "EMPTY_FILE",
                    f"Unable to read text from DOCX file: {str(e)}",
                )

        raise api_error(
            400,
            "UNSUPPORTED_FILE_TYPE",
            "Only CSV, TXT, PDF, and DOCX files are supported.",
        )

    @staticmethod
    def parse_file(file: UploadFile) -> List[Tuple[str, str]]:
        """Parse file based on file extension."""
        filename = (file.filename or "").lower()

        if filename.endswith(".csv"):
            return FileParser.parse_csv(file)
        if filename.endswith(".txt"):
            return FileParser.parse_txt(file)
        if filename.endswith(".pdf"):
            return FileParser.parse_pdf(file)
        if filename.endswith(".docx"):
            return FileParser.parse_docx(file)

        raise api_error(
            400,
            "UNSUPPORTED_FILE_TYPE",
            "Only CSV, TXT, PDF, and DOCX files are supported.",
        )

    @staticmethod
    def validate_file(file: UploadFile, max_size_mb: Optional[int] = None) -> None:
        """Validate uploaded file size and extension."""
        limit_mb = settings.MAX_UPLOAD_SIZE_MB if max_size_mb is None else max_size_mb

        file.file.seek(0, 2)
        file_size = file.file.tell()
        file.file.seek(0)

        max_size = limit_mb * 1024 * 1024
        if file_size > max_size:
            raise api_error(
                413,
                "FILE_TOO_LARGE",
                f"File too large. Maximum size is {limit_mb}MB.",
            )

        if file_size == 0:
            raise api_error(
                400,
                "EMPTY_FILE",
                "File is empty.",
            )

        filename = (file.filename or "").lower()
        allowed_extensions = tuple(ext.lower() for ext in settings.ALLOWED_FILE_TYPES)
        if not filename.endswith(allowed_extensions):
            allowed_str = ", ".join(settings.ALLOWED_FILE_TYPES)
            raise api_error(
                400,
                "UNSUPPORTED_FILE_TYPE",
                f"Only {allowed_str} files are supported.",
            )
