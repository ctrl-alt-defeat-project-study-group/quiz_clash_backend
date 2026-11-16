"""
Service for parsing and extracting content from uploaded files
"""
import csv
import re
from typing import List, Tuple, Optional
from fastapi import UploadFile, HTTPException
import io


class FileParser:
    """Parse uploaded files to extract structured content"""
    
    @staticmethod
    def parse_csv(file: UploadFile) -> List[Tuple[str, str]]:
        """Parse CSV file expecting term,definition format"""
        try:
            content = file.file.read().decode('utf-8')
            file.file.seek(0)  # Reset file pointer
            
            # Parse CSV
            reader = csv.reader(io.StringIO(content))
            terms_definitions = []
            
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
                    detail="CSV file is empty or contains no valid term-definition pairs"
                )
            
            return terms_definitions
            
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=400,
                detail="File encoding error. Please upload UTF-8 encoded files."
            )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error parsing CSV file: {str(e)}"
            )
    
    @staticmethod
    def parse_txt(file: UploadFile) -> List[Tuple[str, str]]:
        """Parse TXT file with various formats"""
        try:
            content = file.file.read().decode('utf-8')
            file.file.seek(0)  # Reset file pointer
            
            terms_definitions = []
            
            # Try to detect common formats
            
            # Format 1: term: definition
            if ':' in content:
                lines = content.split('\n')
                for line in lines:
                    if ':' in line:
                        parts = line.split(':', 1)
                        if len(parts) == 2:
                            term = parts[0].strip()
                            definition = parts[1].strip()
                            if term:
                                terms_definitions.append((term, definition))
            
            # Format 2: term - definition
            elif '-' in content:
                lines = content.split('\n')
                for line in lines:
                    if '-' in line:
                        parts = line.split('-', 1)
                        if len(parts) == 2:
                            term = parts[0].strip()
                            definition = parts[1].strip()
                            if term:
                                terms_definitions.append((term, definition))
            
            # Format 3: Simple list (one per line)
            else:
                lines = content.split('\n')
                for line in lines:
                    line = line.strip()
                    if line:
                        # Try to split on any separator
                        for sep in [' - ', ': ', ' = ', ' → ', ' -> ']:
                            if sep in line:
                                parts = line.split(sep, 1)
                                if len(parts) == 2:
                                    term = parts[0].strip()
                                    definition = parts[1].strip()
                                    if term:
                                        terms_definitions.append((term, definition))
                                    break
                        else:
                            # No separator found, treat as term only
                            terms_definitions.append((line, ""))
            
            if not terms_definitions:
                raise HTTPException(
                    status_code=400,
                    detail="TXT file is empty or contains no parsable content. "
                           "Expected format: term: definition or term - definition"
                )
            
            return terms_definitions
            
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=400,
                detail="File encoding error. Please upload UTF-8 encoded files."
            )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error parsing TXT file: {str(e)}"
            )
    
    @staticmethod
    def parse_file(file: UploadFile) -> List[Tuple[str, str]]:
        """Parse file based on file extension"""
        filename = file.filename.lower()
        
        if filename.endswith('.csv'):
            return FileParser.parse_csv(file)
        elif filename.endswith('.txt'):
            return FileParser.parse_txt(file)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {filename}. Only .csv and .txt files are supported."
            )
    
    @staticmethod
    def validate_file(file: UploadFile, max_size_mb: int = 10) -> None:
        """Validate uploaded file"""
        # Check file size
        file.file.seek(0, 2)  # Seek to end
        file_size = file.file.tell()
        file.file.seek(0)  # Reset to beginning
        
        max_size = max_size_mb * 1024 * 1024
        if file_size > max_size:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size is {max_size_mb}MB"
            )
        
        if file_size == 0:
            raise HTTPException(
                status_code=400,
                detail="File is empty"
            )
        
        # Check file extension
        filename = file.filename.lower()
        if not (filename.endswith('.csv') or filename.endswith('.txt')):
            raise HTTPException(
                status_code=400,
                detail="Only .csv and .txt files are supported"
            )