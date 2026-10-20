"""Versioned, safe API errors."""

from dataclasses import dataclass
from typing import Any


@dataclass
class ApiError(Exception):
    code: str
    message: str
    status_code: int = 500
    category: str = "internal"
    retryable: bool = False
    details: Any = None
