import warnings
from datetime import date
from enum import Enum
from functools import cached_property, wraps
from typing import Any, Dict, Generator, List, Optional, Tuple, Type, TypeVar, Union

import forge
from django.db import connections, models
from django.db.transaction import atomic
from djdantic.schemas import Access, Error
from djdantic.schemas.access import AccessScope
from djdantic.utils.dict import remove_none
from djdantic.utils.pydantic import OptionalModel, ReferencedModel, include_reference, to_optional
from djdantic.utils.pydantic_django import TransferAction, transfer_to_orm
from djdantic.utils.typing import get_field_type
from fastapi import APIRouter, Body, Depends, Path, Query, Request, Response, Security
from fastapi._compat import _normalize_errors
from fastapi.dependencies.utils import analyze_param, request_params_to_args
from fastapi.exceptions import RequestValidationError
from fastapi.security.base import SecurityBase
from pydantic import constr, create_model
from pydantic.fields import ModelField, Undefined, UndefinedType
from starlette.status import HTTP_204_NO_CONTENT

from ..exceptions import ValidationError
from ..schemas import errors as error_schemas
from ..utils.fastapi import Pagination, depends_pagination
from ..utils.fastapi_django import AggregateResponse, AggregationFunction, aggregation, request_signalling
from . import Method, RouterSchema, SecurityScopes  # noqa  # import SecurityScopes for user friendly import
from .base import TBaseModel, TCreateModel, TUpdateModel
from .registry import register_router

TDjangoModel = TypeVar('TDjangoModel', bound=models.Model)


class DjangoRouterSchema(RouterSchema):
    __router: APIRouter = None

    parent: Optional['DjangoRouterSchema'] = None
    model: Type[TDjangoModel]
    get: Type[TBaseModel]
    create: Union[Type[TCreateModel], UndefinedType] = None
    update: Union[Type[TUpdateModel], UndefinedType] = None
    delete_status: Optional[Any] = None
    pagination_options: dict = {}
    aggregate_fields: Optional[Union[Type[Enum], UndefinedType]] = None
    aggregate_group_by: Optional[Type[Enum]] = None
    register_router: Optional[Tuple[list, dict]] = None
    do_include_query_fields_in_schema: bool = False

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)

        if self.create_multi:
            # create_multi is WIP
            raise NotImplementedError("create_multi is not supported for DjangoRouterSchema")

        if self.register_router:
            self._create_router()

    def _init_list(self):
        self.list = create_model(
            f"{self.get.__qualname__}List", __module__=self.get.__module__, items=(List[self.get_referenced], ...)
        )

    @property
    def name_singular(self) -> str:
        return self.model.__name__.lower()

    @property
    def related_name_on_parent(self) -> str:
        return self.name

    @property
    def id_field(self):
        name = self.name_singular
        if self.parent:
            name = name.removeprefix(self.parent.name_singular)

        return '%s_id' % name

    @property
    def id_field_placeholder(self):
        return '/{%s}' % self.id_field

    @cached_property
    def model_fields(self) -> Enum:
        def _get_model_fields(model, prefix='', recursion_tree=None):
            if recursion_tree is None:
                recursion_tree = []

            for field in model._meta.get_fields(include_parents=False):
                yield f'{prefix}{field.name}', field

                if isinstance(
                    field, (models.ForeignKey, models.ManyToManyField, models.ManyToOneRel, models.ManyToManyRel)
                ):
                    if self.parent and field.related_model == self.parent.model:
                        continue

                    if field.related_model is model:
                        continue

                    if field.related_model in recursion_tree:
                        continue

                    yield from _get_model_fields(
                        field.related_model,
                        prefix=prefix + field.name + '__',
                        recursion_tree=[*recursion_tree, model],
                    )

        return Enum(f'{self.model.__name__}Fields', {field: ref for field, ref in _get_model_fields(self.model)})

    @cached_property
    def order_fields(self):
        fields = []
        for field in self.model_fields:
            name = field._name_
            if isinstance(field.value, (models.ManyToManyRel, models.ManyToOneRel)):
                name += '__count'

            fields.append(name)
            fields.append('-' + name)

        return Enum(f'{self.model.__name__}OrderFields', {field: field for field in fields})

    @cached_property
    def get_referenced(self):
        if not issubclass(self.get, ReferencedModel):
            return include_reference()(self.get)

        return self.get

    @cached_property
    def update_optional(self):
        if not issubclass(self.update, OptionalModel):
            return to_optional()(self.update)

        return self.update

    @cached_property
    def aggregated_fields(self) -> Enum:
        if self.aggregate_fields:
            return self.aggregate_fields

        fields = {
            '_count': '*',
        }
        fields.update(
            {
                field._name_: field._name_
                for field in self.model_fields
                if isinstance(
                    field.value,
                    (
                        models.IntegerField,
                        models.FloatField,
                        models.DecimalField,
                        models.ManyToManyRel,
                        models.ManyToOneRel,
                        # TODO only include Charfield if aggregate function is count
                        models.CharField,
                    ),
                )
            }
        )
        return Enum(f'{self.model.__name__}AggregateFields', fields)

    @cached_property
    def get_aggregate_group_by(self) -> Enum:
        if self.aggregate_group_by:
            return self.aggregate_group_by

        def generate_group_by_fields():
            for field in self.model_fields:
                if isinstance(field.value, models.CharField) and field.value.choices:
                    yield field._name_

                if isinstance(field.value, models.ForeignKey):
                    yield field._name_

                if isinstance(field.value, (models.DateField, models.DateTimeField)):
                    for field_name, _field_type in self._get_field_variations(field.value):
                        yield field_name

        return Enum(
            f'{self.model.__name__}GroupByFields',
            {field_name: field_name for field_name in generate_group_by_fields()},
        )

    @property
    def router(self) -> APIRouter:
        if not self.__router:
            self._create_router()

        return self.__router

    def _create_router(self):
        prefix = f'/{self.name}'
        if self.parent:
            prefix = self.parent.id_field_placeholder + prefix

        self.__router = APIRouter(prefix=prefix)

        if self.list and self.list is not Undefined:
            self._create_route_list()

        if self.aggregate_fields is not Undefined:
            self._create_route_aggregate()

        if self.create and self.create is not Undefined:
            self._create_route_post()

        if self.get and self.get is not Undefined and self.get_endpoint:
            self._create_route_get()

        if self.update and self.update is not Undefined:
            self._create_route_patch()
            self._create_route_put()

        if self.delete:
            self._create_route_delete()

        child: DjangoRouterSchema
        for child in self.children:
            self.__router.include_router(child.router)

        if self.register_router:
            register_router(self.__router, *self.register_router[0], **self.register_router[1])

    def _additional_responses(self, method: Method):
        responses = {}
        if method in (Method.GET, Method.PATCH, Method.PUT, Method.DELETE) or self.parent:
            responses[404] = {'description': "ObjectDoesNotExist", 'model': error_schemas.ObjectDoesNotExist}

        if method in (Method.POST, Method.PATCH, Method.PUT, Method.DELETE):
            responses[420] = {'description': "IntegrityError", 'model': error_schemas.IntegrityError}

        if self.security:
            responses[401] = {'description': "Unauthorized", 'model': error_schemas.JOSEError}
            responses[403] = {'description': "AccessError", 'model': error_schemas.AccessError}

        return responses

    def _create_route_list(self):
        self.__router.add_api_route(
            '',
            methods=['GET'],
            endpoint=self._create_endpoint_list(),
            response_model=self.list,
            summary=f'{self.model.__name__} list',
            responses=self._additional_responses(Method.GET_LIST),
        )

    def _create_route_aggregate(self):
        self.__router.add_api_route(
            '/aggregate/{aggregation_function}/{field}',
            methods=['GET'],
            endpoint=self._create_endpoint_aggregate(),
            response_model=AggregateResponse,
            summary=f'{self.model.__name__} aggregate',
            responses=self._additional_responses(Method.GET_AGGREGATE),
        )

    def _create_route_post(self):
        self.__router.add_api_route(
            '',
            methods=['POST'],
            endpoint=self._create_endpoint_post(),
            response_model=Union[self.get_referenced, List[self.get_referenced]]
            if self.create_multi
            else self.get_referenced,
            summary=f'{self.model.__name__} create',
            responses=self._additional_responses(Method.POST),
        )

    def _create_route_get(self):
        self.__router.add_api_route(
            self.id_field_placeholder,
            methods=['GET'],
            endpoint=self._create_endpoint_get(),
            response_model=self.get_referenced,
            summary=f'{self.model.__name__} read',
            responses=self._additional_responses(Method.GET),
        )

    def _create_route_patch(self):
        self.__router.add_api_route(
            self.id_field_placeholder,
            methods=['PATCH'],
            endpoint=self._create_endpoint_patch(),
            response_model=self.get_referenced,
            summary=f'{self.model.__name__} update (partial)',
            responses=self._additional_responses(Method.PATCH),
        )

    def _create_route_put(self):
        self.__router.add_api_route(
            self.id_field_placeholder,
            methods=['PUT'],
            endpoint=self._create_endpoint_put(),
            response_model=self.get_referenced,
            summary=f'{self.model.__name__} update',
            responses=self._additional_responses(Method.PUT),
        )

    def _create_route_delete(self):
        self.__router.add_api_route(
            self.id_field_placeholder,
            methods=['DELETE'],
            endpoint=self._create_endpoint_delete(),
            status_code=HTTP_204_NO_CONTENT,
            summary=f'{self.model.__name__} delete',
            responses=self._additional_responses(Method.DELETE),
        )

    def _generate_annotations(self):
        for field in self.model_fields:
            if isinstance(field.value, (models.IntegerField, models.FloatField, models.DecimalField)):
                yield models.Sum(field.name)
                yield models.Avg(field.name)
                yield models.Min(field.name)
                yield models.Max(field.name)

            if isinstance(field.value, models.ManyToManyField):
                yield models.Count(field.name)

    def get_queryset(
        self,
        parent_ids: Optional[List[str]] = None,
        access: Optional[Access] = None,
        pagination: Optional[Pagination] = None,
        is_annotated: bool = False,
        is_aggregated: bool = False,
    ):
        objects = self.model.objects
        if self.parent:
            parent_objects = self.parent.get_queryset(parent_ids[:-1], access, is_annotated=False, is_aggregated=False)
            parent = parent_objects.get(pk=parent_ids[-1])
            objects = getattr(parent, self.related_name_on_parent)

        queryset = objects.filter(self.objects_filter(access))
        distinct_fields = []

        if is_annotated:
            queryset = queryset.annotate(*self._generate_annotations())

        if not is_aggregated and connections.databases[queryset.db]['ENGINE'] == 'django_cockroachdb':
            # cockroachdb returns multiple rows when searching on related fields, therefore perform a distinct on the primary key
            distinct_fields.append('id')

        if distinct_fields:
            return queryset.distinct(*distinct_fields)

        return queryset

    def objects_filter(self, access: Optional[Access] = None) -> models.Q:
        """
        Method used for security filtering, override to add additional filters based on the given user.
        """
        if hasattr(self.model, 'tenant_id'):
            return models.Q(tenant_id=access.tenant_id)

        return models.Q()

    def objects_get_filtered(
        self,
        *,
        parent_ids: Optional[List[str]] = None,
        access: Optional[Access] = None,
        search: models.Q = models.Q(),
        pagination: Pagination,
    ) -> List[TDjangoModel]:
        return list(pagination.query(self.get_queryset(parent_ids, access, pagination=pagination).filter(search)))

    def object_get_by_id(
        self, id: str, parent_ids: Optional[List[str]] = None, access: Optional[Access] = None
    ) -> TDjangoModel:
        return self.get_queryset(parent_ids, access).get(id=id)

    @atomic
    def object_create(
        self,
        *,
        access: Optional[Access] = None,
        data: Union[TCreateModel, List[TCreateModel]],
        parent_id: Optional[str] = None,
    ) -> List[TDjangoModel]:
        if not isinstance(data, list):
            data = [data]

        elif not self.create_multi:
            raise ValidationError(detail=Error(code='create_multi_disabled'))

        instances = []
        for el in data:
            instance: TDjangoModel = self.model()
            if hasattr(self.model, 'tenant_id') and access:
                instance.tenant_id = access.tenant_id

            if parent_id:
                setattr(instance, self.parent.id_field, parent_id)

            transfer_to_orm(el, instance, action=TransferAction.CREATE, access=access)
            instances.append(instance)

        return instances

    @atomic
    def object_update(
        self,
        *,
        access: Optional[Access] = None,
        instance: TDjangoModel,
        data: TUpdateModel,
        transfer_action: TransferAction,
    ) -> TDjangoModel:
        transfer_to_orm(
            data,
            instance,
            action=transfer_action,
            exclude_unset=transfer_action == TransferAction.NO_SUBOBJECTS,
            access=access,
        )

    @atomic
    def object_delete(self, *, access: Optional[Access] = None, instance: TDjangoModel):
        if self.delete_status:
            instance.status = self.delete_status
            instance.save()

        else:
            instance.delete()

    def _get_security_scopes(self, method: Method) -> Optional[List[AccessScope]]:
        if self.security_scopes and getattr(self.security_scopes, method.value):
            return getattr(self.security_scopes, method.value)

        if self.parent:
            if method in (Method.POST, Method.PUT, Method.PATCH, Method.DELETE):
                method = Method.PATCH

            return self.parent._get_security_scopes(method)

        return None

    def _get_security(self, method: Method) -> Tuple[Optional[SecurityBase], Optional[List[AccessScope]]]:
        scopes = self._get_security_scopes(method)
        if not scopes:
            return None, None

        if self.security:
            return self.security, scopes

        if self.parent:
            return self.parent._get_security(method)[0], scopes

        return None, None

    def _security_signature(self, method: Method):
        security, scopes = self._get_security(method)
        if not security:
            return

        yield forge.kwarg(
            'access',
            type=Access,
            default=Security(security, scopes=[str(scope) for scope in scopes or []]),
        )

    def _path_signature_id(self, include_self=True):
        if self.parent:
            yield from self.parent._path_signature_id()

        if include_self:
            yield forge.kwarg(
                self.id_field,
                type=str,
                default=Path(..., min_length=self.model.id.field.max_length, max_length=self.model.id.field.max_length),
            )

    def _get_ids(self, kwargs: dict, include_self=True) -> List[str]:
        return [kwargs[arg.name] for arg in self._path_signature_id(include_self=include_self)]

    def depends_response_headers(self, method: Method, request: Request, response: Response):
        if method in (Method.GET, Method.GET_LIST, Method.GET_AGGREGATE):
            if self.cache_control:
                response.headers['Cache-Control'] = self.cache_control.value

        return response

    def endpoint_list(
        self,
        *,
        access: Optional[Access] = None,
        pagination: Pagination,
        search: models.Q = models.Q(),
        **kwargs,
    ):
        ids = self._get_ids(kwargs, include_self=False)
        return self.list(
            items=[
                self.get_referenced.from_orm(obj)
                for obj in self.objects_get_filtered(
                    parent_ids=ids,
                    access=access,
                    search=search,
                    pagination=pagination,
                )
            ],
        )

    def search_filter(self, _request: Optional[Request] = None, **kwargs: Dict[str, Any]) -> models.Q:
        q = models.Q()

        if _request:
            used_params = [
                field for field in self.search_filter_fields.values() if field.alias in _request.query_params
            ]
            query_values, query_errors = request_params_to_args(used_params, _request.query_params)

            if query_errors:
                raise RequestValidationError(_normalize_errors(query_errors))

        else:
            query_values = kwargs

        for arg, value in query_values.items():
            if value is None:
                continue

            if arg.startswith('not__'):
                query = models.Q(**{arg[5:]: value})
                query.negate()

            else:
                query = models.Q(**{arg: value})

            q &= query

        if self.delete_status and 'status__in' in kwargs and kwargs['status__in'] is None:
            q &= ~models.Q(status=self.delete_status)

        return q

    def _get_field_variations(self, field: models.Field, field_name: str = None, field_type=None):
        field_type = field_type or get_field_type(field)
        field_name = field_name or field.name
        variations = [(field_name, field_type)]

        if isinstance(field, models.DateTimeField):
            variations.append((f'{field_name}__date', date))

        if isinstance(field, (models.DateField, models.DateTimeField)):
            for variation, type_ in [*variations]:
                if type_ not in (date, Optional[date]):
                    continue

                variations.append((f'{variation}__year', int))
                variations.append((f'{variation}__quarter', int))
                variations.append((f'{variation}__month', int))
                variations.append((f'{variation}__day', int))
                variations.append((f'{variation}__week', int))
                variations.append((f'{variation}__week_day', int))

        if isinstance(field, (models.IntegerField, models.FloatField, models.DecimalField)):
            variations.append((f'{field_name}__sum', field_type))
            variations.append((f'{field_name}__avg', float if isinstance(field, models.IntegerField) else field_type))
            variations.append((f'{field_name}__min', field_type))
            variations.append((f'{field_name}__max', field_type))

        return variations

    def _search_filter_field(self, model_field) -> Generator[Tuple[str, Type, dict], None, None]:
        field: models.Field = model_field.value
        if field.name == 'tenant_id' or (getattr(field, 'primary_key', False) and self.model != field.model):
            return

        field_type = get_field_type(field)
        field_name = model_field._name_

        assert (
            isinstance(
                field,
                (
                    models.ManyToManyRel,
                    models.ManyToOneRel,
                ),
            )
            or field_type
        ), f'Field {field.name} on model {self.model} is missing a type annotation'

        query_options = {
            'default': None,
        }

        if isinstance(field, (models.ForeignKey, models.ManyToManyField)):
            field_type = List[constr(min_length=field.max_length, max_length=field.max_length)]
            field_name += '__id'
            query_options.update(alias=field_name)
            field_name += '__in'

            if self.parent and field.related_model == self.parent.model:
                return

        if isinstance(field, models.ManyToManyField):
            return

        if field.null:
            _name = f'{query_options.get("alias") or field_name}__isnull'
            yield _name, bool, {**query_options, 'alias': _name}

        if isinstance(field, (models.ManyToManyRel, models.ManyToOneRel)):
            field_name += '__count'
            field_type = int

        if isinstance(
            field,
            (
                models.DateField,
                models.DateTimeField,
                models.IntegerField,
                models.FloatField,
                models.DecimalField,
                models.ManyToManyRel,
                models.ManyToOneRel,
            ),
        ):
            for variation in self._get_field_variations(field, field_name, field_type):
                name = variation
                type_ = field_type
                if isinstance(variation, tuple):
                    name, type_ = variation

                yield f'{name}__gte', type_, query_options
                yield f'{name}__lte', type_, query_options

        elif isinstance(field, models.CharField):
            if field.choices or getattr(field, 'primary_key', False):
                query_options['alias'] = field_name
                if field_name == 'status' and self.delete_status:
                    query_options[
                        'description'
                    ] = f"When not set, objects with status {self.delete_status} are excluded"

                field_name += '__in'
                field_type = List[field_type]

            else:
                query_options['max_length'] = field.max_length
                yield f'{field_name}__icontains', field_type, query_options

        yield f'{field_name}', field_type, query_options

    @cached_property
    def search_filter_fields(
        self,
    ) -> Dict[str, ModelField]:
        fields = {}
        for model_field in self.model_fields:
            for name, type_, options in self._search_filter_field(model_field):
                fields[name] = analyze_param(
                    param_name=name,
                    annotation=Optional[type_],
                    value=Query(**options),
                    is_path_param=False,
                )[2]
                fields[f'not__{name}'] = analyze_param(
                    param_name=f'not__{name}',
                    annotation=Optional[type_],
                    value=Query(**{**options, 'alias': '!' + options.get('alias', name)}),
                    is_path_param=False,
                )[2]

        return fields

    def create_depends_search(self):
        if self.do_include_query_fields_in_schema:
            if len(self.search_filter_fields) > 100:
                warnings.warn(
                    "Having search query fields in schema when having more then 100 fields can cause massive performance problems while processing each request"
                )

            return forge.sign(
                *[
                    forge.kwarg(
                        name,
                        type=field.annotation,
                        default=field.field_info,
                    )
                    for name, field in self.search_filter_fields.items()
                ]
            )(self.search_filter)

        else:
            return forge.sign(forge.kwarg('_request', type=Request))(self.search_filter)

    def _depends_search(self):
        yield forge.kwarg('search', type=models.Q, default=Depends(self.create_depends_search()))
        yield forge.kwarg(
            'pagination',
            type=Pagination,
            default=Depends(
                forge.modify(
                    'order_by',
                    type=Optional[List[self.order_fields]],
                    default=Query(
                        self.pagination_options.get('default_order_by', list()),
                        include_in_schema=self.do_include_query_fields_in_schema,
                    ),
                )(depends_pagination(**self.pagination_options))
            ),
        )

    def get_endpoint_description(self, method: Method):
        description = ""

        scopes = self._get_security_scopes(method)
        if scopes:
            description += "Scopes: " + ", ".join([f'`{scope}`' for scope in scopes]) + "\n\n"

        if not self.do_include_query_fields_in_schema:
            description += (
                "<details><summary>Query fields</summary>Search query for every field can be negated by prepending <code>!</code><br><br>"
                + "".join(
                    f'- <code>{field.alias}</code> ({field.type_.__name__})<br>'
                    for field in self.search_filter_fields.values()
                    if field.alias[0] != "!"
                )
                + "</details>\n\n"
            )

            description += (
                "<details><summary>Order fields</summary>Search order for every field can be reversed (to desc) by prepending <code>-</code><br><br>"
                + ", ".join(f'<code>{field.name}</code>' for field in self.order_fields if field.name[0] != "-")
                + "</details>\n\n"
            )

        return description or None

    def signature(self, method: Method):
        yield forge.kwarg('request', type=Request)
        yield forge.kwarg('response', type=Response)

        yield from self._path_signature_id(
            include_self=method not in (Method.GET_LIST, Method.GET_AGGREGATE, Method.POST)
        )
        yield from self._security_signature(method)

        if method in (Method.GET_LIST, Method.GET_AGGREGATE):
            yield from self._depends_search()

    def endpoint(self, method: Method, signature: Optional[List] = None):
        """
        Decorates an endpoint method and applies shared signatures
        """
        if not signature:
            signature = []

        def wrapper(endpoint):
            try:
                endpoint = forge.sign(*[*self.signature(method), *signature])(endpoint)

            except Exception:
                raise

            endpoint.__doc__ = self.get_endpoint_description(method)

            @wraps(endpoint)
            def wrapped(*args, request: Request, response: Response, **kwargs):
                self.depends_response_headers(method=method, request=request, response=response)
                return request_signalling(endpoint)(*args, request=request, response=response, **kwargs)

            return wrapped

        return wrapper

    def _create_endpoint_list(self):
        return self.endpoint(Method.GET_LIST)(self.endpoint_list)

    def endpoint_aggregate(
        self,
        *,
        aggregation_function: AggregationFunction = Path(...),
        field: str = Path(...),
        access: Optional[Access] = None,
        pagination: Pagination,
        group_by: Optional[List[str]] = None,
        search: models.Q = models.Q(),
        **kwargs,
    ):
        ids = self._get_ids(kwargs, include_self=False)

        return aggregation(
            self.get_queryset(ids, access, is_annotated=True, is_aggregated=True),
            q_filters=search,
            aggregation_function=aggregation_function,
            field=field,
            group_by=group_by,
            pagination=pagination,
            distinct=True if kwargs['request'].query_params.get('distinct') else False,
        )

    def _create_endpoint_aggregate(self):
        return self.endpoint(
            Method.GET_AGGREGATE,
            signature=[
                forge.kwarg('aggregation_function', type=AggregationFunction, default=Path(...)),
                forge.kwarg('field', type=self.aggregated_fields, default=Path(...)),
                forge.kwarg('group_by', type=Optional[List[self.get_aggregate_group_by]], default=Query(None))
                if self.aggregate_group_by is not ...
                else None,
            ],
        )(self.endpoint_aggregate)

    def endpoint_post(self, *, data: TCreateModel, access: Optional[Access] = None, **kwargs):
        obj = self.object_create(
            access=access, data=data, parent_id=kwargs[self.parent.id_field] if self.parent else None
        )
        if len(obj) > 1:
            return [self.get_referenced.from_orm(o) for o in obj]

        return self.get_referenced.from_orm(obj[0])

    def _create_endpoint_post(self):
        create_type = self.create
        if self.create_multi:
            create_type = List[self.create]

        return self.endpoint(Method.POST, signature=[forge.kwarg('data', type=create_type, default=Body(...))])(
            self.endpoint_post
        )

    def _object_get(self, kwargs, access: Optional[Access] = None):
        ids = self._get_ids(kwargs)
        return self.object_get_by_id(ids[-1], parent_ids=ids[:-1], access=access)

    def endpoint_get(self, *, access: Optional[Access] = None, **kwargs):
        obj = self._object_get(kwargs, access=access)
        return self.get_referenced.from_orm(obj)

    def _create_endpoint_get(self):
        return self.endpoint(Method.GET)(self.endpoint_get)

    def endpoint_patch(self, *, data: TUpdateModel, access: Optional[Access] = None, **kwargs):
        obj = self._object_get(kwargs, access=access)
        self.object_update(access=access, instance=obj, data=data, transfer_action=TransferAction.NO_SUBOBJECTS)
        return self.get_referenced.from_orm(obj)

    def _create_endpoint_patch(self):
        return self.endpoint(
            Method.PATCH,
            signature=[
                forge.kwarg('data', type=self.update_optional, default=Body(...)),
            ],
        )(self.endpoint_patch)

    def endpoint_put(self, *, data, access: Optional[Access] = None, **kwargs):
        obj = self._object_get(kwargs, access=access)
        self.object_update(access=access, instance=obj, data=data, transfer_action=TransferAction.SYNC)
        return self.get_referenced.from_orm(obj)

    def _create_endpoint_put(self):
        return self.endpoint(
            Method.PUT,
            signature=[
                forge.kwarg('data', type=self.update, default=Body(...)),
            ],
        )(self.endpoint_put)

    def endpoint_delete(self, *, access: Optional[Access] = None, **kwargs):
        obj = self._object_get(kwargs, access=access)
        self.object_delete(access=access, instance=obj)

        return Response(status_code=HTTP_204_NO_CONTENT)

    def _create_endpoint_delete(self):
        return self.endpoint(Method.DELETE)(self.endpoint_delete)

    class Config:
        keep_untouched = (cached_property,)
