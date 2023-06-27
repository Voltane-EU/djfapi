from typing import Optional
from enum import Enum
from fastapi import FastAPI
from django import setup as django_setup
from django.core.exceptions import ObjectDoesNotExist
from django.db.utils import IntegrityError
from jose.exceptions import JOSEError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from .routing.registry import include_routers
from .handlers import error as error_handlers


class AuthType(str, Enum):
    REFRESH = "refresh"
    TRANSACTION = "transaction"


class DjangoFastAPI(FastAPI):
    healthcheck_url: str = "/"

    def __init__(
        self,
        *args,
        auth_type: Optional[AuthType] = None,
        **kwargs,
    ):
        self.auth_type = auth_type
        super().__init__(*args, **kwargs)

    async def healthcheck(self, request: Request) -> JSONResponse:
        return JSONResponse(None)

    def setup(self) -> None:
        django_setup(set_prefix=False)

        super().setup()

        self.add_route(self.healthcheck_url, self.healthcheck)

        if self.auth_type is None:
            pass

        elif self.auth_type == AuthType.REFRESH:
            from .security.auth import RefreshTokenSchema

            self._auth_schema = RefreshTokenSchema()

        elif self.auth_type == AuthType.TRANSACTION:
            raise NotImplementedError

        else:
            raise ValueError("auth_type must be one of " + ", ".join(t.value for t in AuthType))

        include_routers(self)
        self._add_exception_handlers()

    def _add_exception_handlers(self):
        self.add_exception_handler(HTTPException, error_handlers.http_exception_handler)
        self.add_exception_handler(Exception, error_handlers.generic_exception_handler)
        self.add_exception_handler(ObjectDoesNotExist, error_handlers.object_does_not_exist_handler)
        self.add_exception_handler(IntegrityError, error_handlers.integrity_error_handler)
        self.add_exception_handler(JOSEError, error_handlers.jose_error_handler)
