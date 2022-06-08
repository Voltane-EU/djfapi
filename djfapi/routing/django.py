from functools import partial
from typing import Any, List, Optional, Type, TypeVar, Union
import forge
from django.db import models
from fastapi import APIRouter, Security, Path, Body, Depends
from fastapi.security.base import SecurityBase
from ..schemas import Access, Error
from ..utils.fastapi import Pagination, depends_pagination
from ..utils.pydantic_django import transfer_to_orm, TransferAction
from ..exceptions import ValidationError
from .base import TBaseModel, TCreateModel, TUpdateModel
from . import BaseRouter, RouterSchema


def _partial_with_description(func, /, *args, **kwargs):
    wrapped = partial(func, *args, **kwargs)
    wrapped.__doc__ = func.__doc__
    return wrapped


TDjangoModel = TypeVar('TDjangoModel', bound=models.Model)


class DjangoRouterSchema(RouterSchema):
    __router = None

    model: Type[TDjangoModel]
    get: Type[TBaseModel]
    create: Type[TCreateModel] = None
    update: Type[TUpdateModel] = None
    delete_status: Optional[Any] = None
    pagination_options: dict = {}

    def __init__(self, **data: Any) -> None:
        if self.create_multi:
            # create_multi is WIP
            raise NotImplementedError("create_multi is not supported for DjangoRouterSchema")

        super().__init__(**data)

    def objects_filter(self, access: Optional[Access] = None) -> models.Q:
        return models.Q()

    def objects_get_filtered(self, *, access: Optional[Access] = None, pagination: Pagination) -> List[TDjangoModel]:
        return list(pagination.query(self.model.objects, self.objects_filter(access)))

    def object_get_by_id(self, id: str, access: Optional[Access] = None) -> TDjangoModel:
        return self.model.objects.filter(self.objects_filter(access)).get(id=id)

    def object_create(self, *, access: Optional[Access] = None, data: Union[TCreateModel, List[TCreateModel]]) -> List[TDjangoModel]:
        if not isinstance(data, list):
            data = [data]

        elif not self.create_multi:
            raise ValidationError(detail=Error(code='create_multi_disabled'))

        instances = []
        for el in data:
            instance: TDjangoModel = self.model()
            transfer_to_orm(el, instance, action=TransferAction.CREATE, access=access)
            instances.append(instance)

        return instances

    def object_update(self, *, access: Optional[Access] = None, instance: TDjangoModel, data: TUpdateModel, transfer_action: TransferAction) -> TDjangoModel:
        transfer_to_orm(data, instance, action=transfer_action, access=access)

    def object_delete(self, *, access: Optional[Access] = None, instance: TDjangoModel):
        if self.delete_status:
            instance.status = self.delete_status
            instance.save()

        else:
            instance.delete()

    def _security_signature(self, method):
        if not self.security:
            return []

        return [
            forge.kwarg('access', type=Access, default=Security(self.security)),
        ]

    def _path_signature_id(self):
        return forge.kwarg('id', type=str, default=Path(..., min_length=self.model.id.field.max_length, max_length=self.model.id.field.max_length))

    def endpoint_list(self, *, access: Optional[Access] = None, pagination: Pagination):
        return self.list(items=[
            self.get.from_orm(obj)
            for obj in self.objects_get_filtered(
                access=access,
                pagination=pagination,
            )
        ])

    def _create_endpoint_list(self):
        return forge.sign(*[
            *self._security_signature('list'),
            forge.kwarg('pagination', type=Pagination, default=Depends(depends_pagination(**self.pagination_options))),
        ])(self.endpoint_list)

    def endpoint_post(self, *, data: TCreateModel, access: Optional[Access] = None, **kwargs):
        obj = self.object_create(access=access, data=data)
        if len(obj) > 1:
            return [self.get.from_orm(o) for o in obj]

        return self.get.from_orm(obj[0])

    def _create_endpoint_post(self):
        create_type = self.create
        if self.create_multi:
            create_type = List[self.create]

        return forge.sign(*[
            forge.kwarg('data', type=create_type, default=Body(...)),
            *self._security_signature('post'),
        ])(self.endpoint_post)

    def endpoint_get(self, *, id: str = Path(...), access: Optional[Access] = None, **kwargs):
        obj = self.object_get_by_id(id, access=access)
        return self.get.from_orm(obj)

    def _create_endpoint_get(self):
        return forge.sign(*[
            self._path_signature_id(),
            *self._security_signature('get'),
        ])(self.endpoint_get)

    def endpoint_patch(self, *, id: str = Path(...), data: TUpdateModel, access: Optional[Access] = None, **kwargs):
        obj = self.object_get_by_id(id, access=access)
        self.object_update(access=access, instance=obj, data=data, transfer_action=TransferAction.NO_SUBOBJECTS)
        return self.get.from_orm(obj)

    def _create_endpoint_patch(self):
        return forge.sign(*[
            self._path_signature_id(),
            forge.kwarg('data', type=self.update, default=Body(...)),
            *self._security_signature('patch'),
        ])(self.endpoint_patch)

    def endpoint_put(self, *, id: str = Path(...), data, access: Optional[Access] = None, **kwargs):
        obj = self.object_get_by_id(id, access=access)
        self.object_update(access=access, instance=obj, data=data, transfer_action=TransferAction.SYNC)
        return self.get.from_orm(obj)

    def _create_endpoint_put(self):
        return forge.sign(*[
            self._path_signature_id(),
            forge.kwarg('data', type=self.update, default=Body(...)),
            *self._security_signature('put'),
        ])(self.endpoint_put)

    def endpoint_delete(self, *, id: str = Path(...), access: Optional[Access] = None, **kwargs):
        obj = self.object_get_by_id(id, access=access)
        self.object_delete(access=access, instance=obj)

    def _create_endpoint_delete(self):
        return forge.sign(*[
            self._path_signature_id(),
            *self._security_signature('delete'),
        ])(self.endpoint_delete)

    def _create_route_list(self):
        self.__router.add_api_route('', methods=['GET'], endpoint=self._create_endpoint_list(), response_model=self.list)

    def _create_route_post(self):
        self.__router.add_api_route('', methods=['POST'], endpoint=self._create_endpoint_post(), response_model=Union[self.get, List[self.get]] if self.create_multi else self.get)

    def _create_route_get(self):
        self.__router.add_api_route('/{id}', methods=['GET'], endpoint=self._create_endpoint_get(), response_model=self.get)

    def _create_route_patch(self):
        self.__router.add_api_route('/{id}', methods=['PATCH'], endpoint=self._create_endpoint_patch(), response_model=self.get)

    def _create_route_put(self):
        self.__router.add_api_route('/{id}', methods=['PUT'], endpoint=self._create_endpoint_put(), response_model=self.get)

    def _create_route_delete(self):
        self.__router.add_api_route('/{id}', methods=['DELETE'], endpoint=self._create_endpoint_delete(), status_code=204)

    def _create_router(self):
        self.__router = APIRouter(prefix=f'/{self.name}')

        if self.list and self.list is not ...:
            self._create_route_list()

        if self.create and self.create is not ...:
            self._create_route_post()

        if self.get and self.get is not ...:
            self._create_route_get()

        if self.update and self.update is not ...:
            self._create_route_patch()
            self._create_route_put()

        if self.delete:
            self._create_route_delete()

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
