from typing import Any, Optional
from pydantic import BaseModel


class Error(BaseModel):
    type: Optional[str] = None
    message: Optional[str] = None
    code: Optional[str] = None
    event_id: Optional[str] = None
    detail: Optional[Any] = None
