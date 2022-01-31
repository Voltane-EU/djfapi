from typing import List
from enum import Enum
from pydantic import BaseModel


class Status(Enum):
    OK = 'OK'
    WARNING = 'WARNING'
    FAILURE = 'FAILURE'


class Health(BaseModel):
    class Check(BaseModel):
        class CheckError(BaseModel):
            type: str
            message: str

        name: str
        status: Status
        errors: List[CheckError]

    status: Status
    checks: List[Check]
