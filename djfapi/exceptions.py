from typing import Any, Optional, Dict
from fastapi.exceptions import HTTPException


class AccessError(HTTPException):
    def __init__(
        self,
        status_code: int = 403,
        detail: Any = None,
        headers: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)


class AuthError(HTTPException):
    def __init__(
        self,
        status_code: int = 401,
        detail: Any = None,
        headers: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)


class ValidationError(HTTPException):
    def __init__(
        self,
        status_code: int = 400,
        detail: Any = None,
        headers: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)


class ConstraintError(HTTPException):
    def __init__(
        self,
        status_code: int = 400,
        detail: Any = None,
        headers: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)


class PreconditionError(HTTPException):
    def __init__(
        self,
        status_code: int = 412,
        detail: Any = None,
        headers: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)

