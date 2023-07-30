import logging
from typing import Any, Optional
from jose.exceptions import JOSEError, ExpiredSignatureError
from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from django.core.exceptions import ObjectDoesNotExist
from django.db.utils import IntegrityError, OperationalError, InternalError
from django.db.models import RestrictedError, ProtectedError
from djdantic.schemas import Error
from djdantic.exceptions import AccessError

try:
    from psycopg2.errorcodes import lookup

    db_error_lookup = lambda exc: lookup(exc.pgcode).lower()

except ImportError:
    from psycopg.errors import _sqlcodes

    db_error_lookup = lambda exc: list(
        {code: err for code, err in _sqlcodes.items() if isinstance(exc, err)}.keys(),
    )[1].lower()


try:
    from sentry_sdk import last_event_id, capture_exception as _capture_exception
    from sentry_sdk.integrations.logging import ignore_logger

except ImportError:
    _capture_exception = lambda exc: None
    last_event_id = lambda: None

else:
    ignore_logger(__name__)


_logger = logging.getLogger(__name__)


def capture_exception(exc):
    _logger.exception(exc)
    return _capture_exception(exc)


async def respond_details(
    request: Request,
    content: Any,
    status_code: int = 500,
    headers: Optional[dict] = None,
    event_id: Optional[str] = None,
):
    response = {
        'detail': jsonable_encoder(content),
    }

    event_id = event_id or last_event_id() or request.scope.get('sentry_event_id')
    if event_id:
        response['event_id'] = event_id

    return JSONResponse(
        content=response,
        status_code=status_code,
        headers=headers,
    )


async def http_exception_handler(request: Request, exc: HTTPException):
    event_id = capture_exception(exc)
    content = exc.detail

    if isinstance(content, str):
        content = Error(
            type=exc.__class__.__name__,
            message=content,
        )

    if isinstance(content, Error) and not content.type:
        content.type = exc.__class__.__name__

    return await respond_details(
        request,
        content,
        status_code=exc.status_code,
        headers=getattr(exc, 'headers', None),
        event_id=event_id,
    )


async def object_does_not_exist_handler(request: Request, exc: ObjectDoesNotExist):
    event_id = capture_exception(exc)
    return await respond_details(
        request,
        Error(
            type=exc.__class__.__name__,
            message=str(exc),
            code=f'not_exist:{exc.__class__.__qualname__.split(".")[0].lower()}',
        ),
        status_code=404,
        event_id=event_id,
    )


async def integrity_error_handler(request: Request, exc: IntegrityError):
    event_id = capture_exception(exc)
    code = None
    if not isinstance(exc, (RestrictedError, ProtectedError)) and exc.__cause__:
        try:
            code = db_error_lookup(exc.__cause__)
            if exc.__cause__.diag.constraint_name:
                code += ":" + exc.__cause__.diag.constraint_name

            elif exc.__cause__.diag.column_name:
                code += ":" + exc.__cause__.diag.column_name

        except AttributeError:
            pass

    return await respond_details(
        request,
        Error(
            type=exc.__class__.__name__,
            code=code,
        ),
        status_code=420,
        event_id=event_id,
    )


async def jose_error_handler(request: Request, exc: JOSEError):
    event_id = None
    if not isinstance(exc, ExpiredSignatureError):
        event_id = capture_exception(exc)

    return await respond_details(
        request,
        Error(
            type=exc.__class__.__name__,
            message=str(exc),
        ),
        status_code=401,
        event_id=event_id,
    )


async def generic_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, NotImplementedError):
        return await respond_details(request, Error(type='InternalServerError'), status_code=501)

    if isinstance(exc, (InternalError, OperationalError)):
        return await respond_details(request, Error(type=exc.__class__.__name__), status_code=503)

    if isinstance(exc, AccessError):
        content = exc.detail
        if not content.type:
            content.type = exc.__class__.__name__

        return await respond_details(
            request,
            content,
            status_code=403,
        )

    return await respond_details(request, Error(type='InternalServerError'))
