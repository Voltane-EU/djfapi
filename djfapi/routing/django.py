from functools import partial
from typing import List, Optional, Type, TypeVar
from collections import OrderedDict
import forge
from django.db import models
from pydantic import validate_arguments
from fastapi import APIRouter, Depends, Request, Security, Path
from fastapi.security.base import SecurityBase
from ..schemas import Access
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

    def objects_filter(self, access: Optional[Access] = None) -> models.Q:
        return models.Q()

    def objects_get_filtered(self, access: Optional[Access] = None) -> List[TDjangoModel]:
        return list(self.model.objects.filter(self.objects_filter(access)))

    def objects_get_by_id(self, id: str, access: Optional[Access] = None) -> TDjangoModel:
        return self.model.objects.filter(self.objects_filter(access)).get(id=id)

    def _security_signature(self, method):
        if not self.security:
            return []

        return [
            forge.kwarg('access', type=Access, default=Security(self.security)),
        ]

    def _create_endpoint_list(self):
        def endpoint(access: Optional[Access] = None):
            return self.list(items=[self.get.from_orm(obj) for obj in self.objects_get_filtered()])

        return forge.sign(*[
            *self._security_signature('list'),
        ])(endpoint)

    def _create_endpoint_get(self):
        def endpoint(*, id: str = Path(...), access: Optional[Access] = None, **kwargs):
            obj = self.objects_get_by_id(id, access)
            return self.get.from_orm(obj)

        return forge.sign(*[
            forge.kwarg('id', type=str, default=Path(..., min_length=self.model.id.field.max_length, max_length=self.model.id.field.max_length)),
            *self._security_signature('get'),
        ])(endpoint)

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
