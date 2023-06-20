from enum import Enum
from pydantic import BaseModel
from djdantic import schemas


class ObjectDoesNotExist(BaseModel):
    class Error(schemas.Error):
        code: str = 'not_exist:...'

    detail: Error


class IntegrityError(BaseModel):
    class Error(schemas.Error):
        type: str = 'IntegrityError'

    detail: Error


class AccessError(BaseModel):
    class Error(schemas.Error):
        type: str = 'AccessError'

    detail: Error


class JOSEError(BaseModel):
    class Error(schemas.Error):
        class JOSEErrorTypes(Enum):
            JWTClaimsError = 'JWTClaimsError'
            ExpiredSignatureError = 'ExpiredSignatureError'

        type: JOSEErrorTypes

    detail: Error
