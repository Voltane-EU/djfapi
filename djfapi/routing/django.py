from functools import partial
import inspect
from typing import List, Optional, Type, TypeVar
from collections import OrderedDict
from django.db import models
from pydantic import validate_arguments
from fastapi import APIRouter, Depends, Request, Security, Path
from fastapi.security.base import SecurityBase
from ..utils.fastapi import Pagination, depends_pagination
from . import BaseRouter, RouterSchema


def _partial_with_description(func, /, *args, **kwargs):
    wrapped = partial(func, *args, **kwargs)
    wrapped.__doc__ = func.__doc__
    return wrapped


TDjangoModel = TypeVar('TDjangoModel', bound=models.Model)


class DjangoRouterSchema(RouterSchema):
    __router = None

    model: Type[TDjangoModel]

    def objects_get_filtered(self) -> List[TDjangoModel]:
        return list(self.model.objects.filter())

    def objects_get_by_id(self, id: str) -> TDjangoModel:
        return self.model.objects.get(id=id)

    def _create_endpoint_list(self):
        def endpoint():
            return self.list(items=[self.get.from_orm(obj) for obj in self.objects_get_filtered()])

        return endpoint

    def _create_endpoint_get(self):
        def endpoint(id: str = Path(...)):
            obj = self.objects_get_by_id(id)
            return self.get.from_orm(obj)

        signature = inspect.signature(endpoint)
        parameters = OrderedDict(signature.parameters)
        
        parameters.update(id=parameters['id'].replace(
            default=Path(..., min_length=self.model.id.field.max_length, max_length=self.model.id.field.max_length),
        ))

        signature.replace(parameters=parameters.values())

        endpoint.__signature__ = signature

        return endpoint

    def _create_route_list(self):
        self.__router.add_api_route('', endpoint=self._create_endpoint_list())

    def _create_route_get(self):
        self.__router.add_api_route('/{id}', endpoint=self._create_endpoint_get())

    def _create_router(self):
        self.__router = APIRouter(prefix=f'/{self.name}')

        if self.list and self.list is not ...:
            self._create_route_list()

        if self.get and self.get is not ...:
            self._create_route_get()

    @property
    def router(self) -> APIRouter:
        if not self.__router:
            self._create_router()

        return self.__router


class ModelRouter(BaseRouter):
    __model: models.Model
    __router: APIRouter
    __schema: RouterSchema
    __security: Optional[SecurityBase]

    def __init_subclass__(cls, model: models.Model, router: APIRouter, schema: RouterSchema, security: Optional[SecurityBase] = None) -> None:
        cls.__model = model
        cls.__router = router
        cls.__schema = schema
        cls.__security = security

        super().__init_subclass__()

        cls.init_routes()

    @classmethod
    def _add_api_route(cls, path, func, method='GET', response_model=None):
        cls.__router.add_api_route(
            path,
            endpoint=_partial_with_description(func, cls),
            response_model=response_model,
            methods=[method],
            **getattr(func, 'route_options', {}),
        )

    @classmethod
    def init_routes(cls):
        pass
