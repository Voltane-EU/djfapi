from enum import Enum
from typing import List, Optional, Sequence

from django import setup as django_setup
from django.core.exceptions import ObjectDoesNotExist
from django.db.utils import IntegrityError
from fastapi import FastAPI
from fastapi._compat import ModelField
from fastapi.openapi import utils
from fastapi.routing import APIRoute

try:
    from fastapi.utils import create_response_field

except ImportError:
    from fastapi.utils import create_model_field as create_response_field  # as of fastapi 0.115.0

from jose.exceptions import JOSEError
from pydantic import Field, create_model
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute

from .handlers import error as error_handlers
from .routing.registry import include_routers


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


__super_get_fields_from_routes = utils.get_fields_from_routes


def get_fields_from_routes(
    routes: Sequence[BaseRoute],
) -> List[ModelField]:
    flat_models = __super_get_fields_from_routes(routes)
    for route in routes:
        if (
            getattr(route, "include_in_schema", None)
            and isinstance(route, APIRoute)
            and route.openapi_extra
            and '_djfapi_query_fields' in route.openapi_extra
        ):
            model_name = f'{route.path}_QueryFields'
            flat_models.append(
                create_response_field(
                    model_name,
                    create_model(
                        model_name,
                        __module__='_route_query_fields',
                        **{
                            name: (field.annotation, Field(alias=field.alias))
                            for name, field in route.openapi_extra.pop('_djfapi_query_fields').items()
                        },
                    ),
                )
            )

    return flat_models


utils.get_fields_from_routes = get_fields_from_routes
