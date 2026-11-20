"""
Shared helpers for parsing prefixed string IDs (e.g., quiz_12, q_5, attempt_3, att_3).
"""
from typing import Sequence, Union
from fastapi import HTTPException


def parse_prefixed_id(
    raw_id: str,
    prefixes: Union[str, Sequence[str]],
    *,
    status_code: int = 400,
    detail: str = "Invalid ID format",
) -> int:
    """Parse a positive integer ID from either '<prefix>_<int>' or '<int>'."""
    allowed_prefixes = (prefixes,) if isinstance(prefixes, str) else tuple(prefixes)

    value = raw_id.strip() if isinstance(raw_id, str) else ""
    if not value:
        raise HTTPException(status_code=status_code, detail=detail)

    numeric_part = value
    if "_" in value:
        prefix, _, rest = value.partition("_")
        if prefix not in allowed_prefixes or not rest:
            raise HTTPException(status_code=status_code, detail=detail)
        numeric_part = rest

    if not numeric_part.isdigit():
        raise HTTPException(status_code=status_code, detail=detail)

    numeric_id = int(numeric_part)
    if numeric_id <= 0:
        raise HTTPException(status_code=status_code, detail=detail)

    return numeric_id
