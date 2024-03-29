from pathlib import Path
from typing import Optional


class NonEmptyDirectoryError(ValueError):
    def __init__(self, message: str, path: Optional[Path] = None) -> None:
        super().__init__(message)
        self.path = path


class AbortOperationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def __str__(self) -> str:
        return self.message
