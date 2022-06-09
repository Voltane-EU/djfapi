from enum import Enum
from functools import partial
from typing import Any, List, Optional, Type, TypeVar, Union
import forge
from django.db import models
from fastapi import APIRouter, Security, Path, Body, Depends, Query
from fastapi.security.base import SecurityBase
from ..schemas import Access, Error
from ..utils.fastapi import Pagination, depends_pagination
from ..utils.pydantic_django import transfer_to_orm, TransferAction
from ..utils.fastapi_django import AggregationFunction, aggregation
from ..exceptions import ValidationError
from .base import TBaseModel, TCreateModel, TUpdateModel
from . import BaseRouter, RouterSchema, Method


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
    aggregate_fields: Optional[Type[Enum]] = None
    aggregate_group_by: Optional[Type[Enum]] = None

    @property
    def name_singular(self) -> str:
        self.name_singular = _name = self.model.__name__.lower()
        return _name

    @property
    def related_name_on_parent(self) -> str:
        self.related_name_on_parent = _name = self.name
        return _name

    def get_queryset(self, parent_ids: Optional[List[str]] = None, access: Optional[Access] = None):
        if self.parent:
            return getattr(self.parent.get_queryset(parent_ids[:-1], access).get(pk=parent_ids[-1]), self.related_name_on_parent).filter(self.objects_filter(access))

        return self.model.objects.filter(self.objects_filter(access))

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)

        if self.create_multi:
            # create_multi is WIP
            raise NotImplementedError("create_multi is not supported for DjangoRouterSchema")

    def objects_filter(self, access: Optional[Access] = None) -> models.Q:
        if hasattr(self.model, 'tenant_id'):
            return models.Q(tenant_id=access.tenant_id)

        return models.Q()

    def objects_get_filtered(self, *, parent_ids: Optional[List[str]] = None, access: Optional[Access] = None, pagination: Pagination) -> List[TDjangoModel]:
        return list(pagination.query(self.get_queryset(parent_ids, access)))

    def object_get_by_id(self, id: str, parent_ids: Optional[List[str]] = None, access: Optional[Access] = None) -> TDjangoModel:
        return self.get_queryset(parent_ids, access).get(id=id)

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

    def _security_signature(self, method: Method):
        if not self.security:
            return []

        return [
            forge.kwarg('access', type=Access, default=Security(self.security, scopes=self.security_scopes and self.security_scopes.get(method))),
        ]

    def _path_signature_id(self, include_self=True):
        ids = self.parent._path_signature_id() if self.parent else []
        if include_self:
            ids.append(forge.kwarg(self.id_field, type=str, default=Path(..., min_length=self.model.id.field.max_length, max_length=self.model.id.field.max_length)))

        return ids

    def _get_ids(self, kwargs: dict, include_self=True):
        ids = self._path_signature_id(include_self=include_self)
        return [kwargs[arg.name] for arg in ids]

    def _get_id(self, kwargs: dict):
        return kwargs[self._path_signature_id()[-1].name]

    def endpoint_list(self, *, access: Optional[Access] = None, pagination: Pagination, **kwargs):
        ids = self._get_ids(kwargs, include_self=False)
        return self.list(items=[
            self.get.from_orm(obj)
            for obj in self.objects_get_filtered(
                parent_ids=ids,
                access=access,
                pagination=pagination,
            )
        ])

    def _create_endpoint_list(self):
        return forge.sign(*[
            *self._path_signature_id(include_self=False),
            *self._security_signature(Method.GET_LIST),
            forge.kwarg('pagination', type=Pagination, default=Depends(depends_pagination(**self.pagination_options))),
        ])(self.endpoint_list)

    def endpoint_aggregate(
        self,
        *,
        aggregation_function: AggregationFunction = Path(...),
        field: str = Path(...),
        access: Optional[Access] = None,
        pagination: Pagination,
        group_by: Optional[List[str]] = None,
        **kwargs,
    ):
        ids = self._get_ids(kwargs, include_self=False)
        q_filters = models.Q()

        return aggregation(
            self.get_queryset(ids, access),
            q_filters=q_filters,
            aggregation_function=aggregation_function,
            field=field,
            group_by=group_by,
            pagination=pagination,
        )


    def _create_endpoint_aggregate(self):
        return forge.sign(*[arg for arg in [
            *self._path_signature_id(include_self=False),
            *self._security_signature(Method.GET_AGGREGATE),
            forge.kwarg('aggregation_function', type=AggregationFunction, default=Path(...)),
            forge.kwarg('field', type=self.aggregate_fields, default=Path(...)),
            forge.kwarg('group_by', type=Optional[List[self.aggregate_group_by]], default=Query(None)) if self.aggregate_group_by else None,
            forge.kwarg('pagination', type=Pagination, default=Depends(depends_pagination(**self.pagination_options))),
        ] if arg])(self.endpoint_aggregate)

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
            *self._path_signature_id(include_self=False),
            forge.kwarg('data', type=create_type, default=Body(...)),
            *self._security_signature(Method.POST),
        ])(self.endpoint_post)

    def _object_get(self, kwargs, access: Optional[Access] = None):
        ids = self._get_ids(kwargs)
        return self.object_get_by_id(ids[-1], parent_ids=ids[:-1], access=access)

    def endpoint_get(self, *, access: Optional[Access] = None, **kwargs):
        obj = self._object_get(kwargs, access=access)
        return self.get.from_orm(obj)

    def _create_endpoint_get(self):
        return forge.sign(*[
            *self._path_signature_id(),
            *self._security_signature(Method.GET),
        ])(self.endpoint_get)

    def endpoint_patch(self, *, data: TUpdateModel, access: Optional[Access] = None, **kwargs):
        obj = self._object_get(kwargs, access=access)
        self.object_update(access=access, instance=obj, data=data, transfer_action=TransferAction.NO_SUBOBJECTS)
        return self.get.from_orm(obj)

    def _create_endpoint_patch(self):
        return forge.sign(*[
            *self._path_signature_id(),
            forge.kwarg('data', type=self.update, default=Body(...)),
            *self._security_signature(Method.PATCH),
        ])(self.endpoint_patch)

    def endpoint_put(self, *, data, access: Optional[Access] = None, **kwargs):
        obj = self._object_get(kwargs, access=access)
        self.object_update(access=access, instance=obj, data=data, transfer_action=TransferAction.SYNC)
        return self.get.from_orm(obj)

    def _create_endpoint_put(self):
        return forge.sign(*[
            *self._path_signature_id(),
            forge.kwarg('data', type=self.update, default=Body(...)),
            *self._security_signature(Method.PUT),
        ])(self.endpoint_put)

    def endpoint_delete(self, *, access: Optional[Access] = None, **kwargs):
        obj = self._object_get(kwargs, access=access)
        self.object_delete(access=access, instance=obj)

        return ''

    def _create_endpoint_delete(self):
        return forge.sign(*[
            *self._path_signature_id(),
            *self._security_signature(Method.DELETE),
        ])(self.endpoint_delete)

    @property
    def id_field(self):
        name = self.name_singular
        if self.parent:
            name = name.removeprefix(self.parent.name_singular)

        return '%s_id' % name

    @property
    def id_field_placeholder(self):
        return '/{%s}' % self.id_field

    def _create_route_list(self):
        self.__router.add_api_route('', methods=['GET'], endpoint=self._create_endpoint_list(), response_model=self.list)

    def _create_route_aggregate(self):
        self.__router.add_api_route('/aggregate/{aggregation_function}/{field}', methods=['GET'], endpoint=self._create_endpoint_aggregate())  # TODO response_model

    def _create_route_post(self):
        self.__router.add_api_route('', methods=['POST'], endpoint=self._create_endpoint_post(), response_model=Union[self.get, List[self.get]] if self.create_multi else self.get)

    def _create_route_get(self):
        self.__router.add_api_route(self.id_field_placeholder, methods=['GET'], endpoint=self._create_endpoint_get(), response_model=self.get)

    def _create_route_patch(self):
        self.__router.add_api_route(self.id_field_placeholder, methods=['PATCH'], endpoint=self._create_endpoint_patch(), response_model=self.get)

    def _create_route_put(self):
        self.__router.add_api_route(self.id_field_placeholder, methods=['PUT'], endpoint=self._create_endpoint_put(), response_model=self.get)

    def _create_route_delete(self):
        self.__router.add_api_route(self.id_field_placeholder, methods=['DELETE'], endpoint=self._create_endpoint_delete(), status_code=204)

    def _create_router(self):
        prefix = f'/{self.name}'
        if self.parent:
            prefix = self.parent.id_field_placeholder + prefix

        self.__router = APIRouter(prefix=prefix)

        if self.list and self.list is not ...:
            self._create_route_list()

        if self.aggregate_fields:
            self._create_route_aggregate()

        if self.create and self.create is not ...:
            self._create_route_post()

        if self.get and self.get is not ...:
            self._create_route_get()

        if self.update and self.update is not ...:
            self._create_route_patch()
            self._create_route_put()

        if self.delete:
            self._create_route_delete()

        child: DjangoRouterSchema
        for child in self.children:
            self.__router.include_router(child.router)

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
