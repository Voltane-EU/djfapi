import os
import warnings
from typing import List, Optional, Tuple, Type
from enum import Enum
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, validate_model, SecretStr
from pydantic.fields import SHAPE_SINGLETON, SHAPE_LIST, Undefined
from django.db import models
from django.db.models.fields.related_descriptors import ManyToManyDescriptor, ReverseManyToOneDescriptor
from django.db.transaction import atomic
from ...schemas import Access
from ..sentry import instrument_span, span as span_ctx
from ..pydantic import Reference
from ..asyncio import is_async
from .checks import check_field_access

if os.getenv('USE_ASYNCIO'):
    from ..asyncio import sync_to_async

else:
    from ..sync import sync_to_async


class TransferAction(Enum):
    CREATE = 'CREATE'
    SYNC = 'SYNC'
    NO_SUBOBJECTS = 'NO_SUBOBJECTS'


@instrument_span(
    op='transfer_to_orm',
    description=lambda pydantic_obj, django_obj, *args, **kwargs: f'{pydantic_obj} to {django_obj}',
)
def transfer_to_orm(
    pydantic_obj: BaseModel,
    django_obj: models.Model,
    *,
    action: Optional[TransferAction] = None,
    exclude_unset: bool = False,
    access: Optional[Access] = None,
    created_submodels: Optional[list] = None,
    _just_return_objs: bool = False,
) -> Optional[Tuple[List[models.Model], List[models.Model]]]:
    """
    Transfers the field contents of pydantic_obj to django_obj.
    For this to work it is required to have orm_field set on all of the pydantic_obj's fields, which has to point to the django model attribute.

    It also works for nested pydantic models which point to a field on the **same** django model.

    Example:

    ```python
    from pydantic import BaseModel, Field
    from django.db import models

    class Address(models.Model):
        name = models.CharField(max_length=56)

    class AddressRequest(BaseModel):
        name: str = Field(orm_field=Address.name)
    ```
    """
    if is_async():
        return sync_to_async(transfer_to_orm)(
            pydantic_obj=pydantic_obj,
            django_obj=django_obj,
            action=action,
            exclude_unset=exclude_unset,
            access=access,
            created_submodels=created_submodels,
        )

    span = span_ctx.get()
    span.set_tag('transfer_to_orm.action', action)
    span.set_tag('transfer_to_orm.exclude_unset', exclude_unset)
    span.set_data('transfer_to_orm.access', access)
    span.set_data('transfer_to_orm.pydantic_obj', pydantic_obj)
    span.set_data('transfer_to_orm.django_obj', django_obj)

    if created_submodels:
        warnings.warn("Use transfer_to_orm with kwarg action instead of created_submodels", category=DeprecationWarning)
        action = TransferAction.CREATE

    if not action:
        warnings.warn("Use transfer_to_orm with kwarg action", category=DeprecationWarning)

    subobjects = created_submodels or []
    existing_objects = []

    if access:
        check_field_access(pydantic_obj, access)

    pydantic_values: Optional[dict] = pydantic_obj.dict(exclude_unset=True) if exclude_unset else None

    def populate_default(pydantic_cls, django_obj):
        for key, field in pydantic_cls.__fields__.items():
            orm_field = field.field_info.extra.get('orm_field')
            if not orm_field and issubclass(field.type_, BaseModel):
                populate_default(field.type_, django_obj)

            else:
                if 'orm_field' in field.field_info.extra and field.field_info.extra['orm_field'] is None:
                    # Do not raise error when orm_field was explicitly set to None
                    continue

                assert orm_field, "orm_field not set on %r of %r" % (field, pydantic_cls)

                setattr(
                    django_obj,
                    orm_field.field.attname,
                    field.field_info.default if field.field_info.default is not Undefined and field.field_info.default is not ... else None,
                )

    for key, field in pydantic_obj.__fields__.items():
        orm_method = field.field_info.extra.get('orm_method')
        if orm_method:
            if exclude_unset and key not in pydantic_values:
                continue

            value = getattr(pydantic_obj, field.name)
            if isinstance(value, SecretStr):
                value = value.get_secret_value()

            orm_method(django_obj, value)
            continue

        orm_field = field.field_info.extra.get('orm_field')
        if not orm_field:
            if 'orm_field' in field.field_info.extra and field.field_info.extra['orm_field'] is None:
                # Do not raise error when orm_field was explicitly set to None
                continue

            if not (field.shape == SHAPE_SINGLETON and issubclass(field.type_, BaseModel)):
                raise AttributeError("orm_field not found on %r" % field)

        value = getattr(pydantic_obj, field.name)
        if field.shape == SHAPE_SINGLETON:
            if not orm_field and issubclass(field.type_, BaseModel):
                if value is None:
                    if exclude_unset and key not in pydantic_values:
                        continue

                    populate_default(field.type_, django_obj)

                elif isinstance(value, BaseModel):
                    sub_transfer = transfer_to_orm(pydantic_obj=value, django_obj=django_obj, exclude_unset=exclude_unset, access=access, action=action, _just_return_objs=True)
                    subobjects += sub_transfer[0]
                    existing_objects += sub_transfer[1]

                else:
                    raise NotImplementedError

            else:
                if exclude_unset and key not in pydantic_values:
                    continue

                if orm_field.field.is_relation and isinstance(value, models.Model):
                    value = value.pk

                if isinstance(orm_field.field, models.JSONField) and value:
                    if isinstance(value, BaseModel):
                        value = value.dict()

                    elif isinstance(value, dict):
                        pass

                    else:
                        raise NotImplementedError

                setattr(django_obj, orm_field.field.attname, value)

        elif field.shape == SHAPE_LIST:
            if not value:
                continue

            elif isinstance(orm_field, ManyToManyDescriptor):
                relatedmanager = getattr(django_obj, orm_field.field.attname)
                related_model = relatedmanager.through
                obj_fields = {relatedmanager.source_field_name: django_obj}
                existing_object_ids = set()
                if action == TransferAction.SYNC:
                    existing_object_ids = set(related_model.objects.filter(**obj_fields).values_list('id', flat=True))

                for val in value:
                    def get_subobj(force_create: bool = False):
                        obj_manytomany_fields = {**obj_fields}
                        if getattr(val, 'id', None):
                            obj_manytomany_fields[relatedmanager.target_field.attname] = val.id

                        else:
                            raise NotImplementedError

                        if force_create or action == TransferAction.CREATE:
                            return related_model(**obj_manytomany_fields)

                        elif action == TransferAction.SYNC:
                            try:
                                return related_model.objects.get(**obj_manytomany_fields)

                            except related_model.DoesNotExist:
                                return get_subobj(force_create=True)

                        else:
                            raise NotImplementedError

                    sub_obj = get_subobj()
                    existing_object_ids.discard(sub_obj.id)
                    subobjects.append(sub_obj)
                    sub_transfer = transfer_to_orm(val, sub_obj, exclude_unset=exclude_unset, access=access, action=action, _just_return_objs=True)
                    subobjects += sub_transfer[0]
                    existing_objects += sub_transfer[1]

                existing_objects += related_model.objects.filter(id__in=list(existing_object_ids))

            elif isinstance(orm_field, ReverseManyToOneDescriptor):
                relatedmanager = getattr(django_obj, orm_field.rel.name)
                related_model: Type[models.Model] = relatedmanager.field.model
                obj_fields = {relatedmanager.field.name: django_obj}

                existing_object_ids = set()
                if action == TransferAction.SYNC:
                    existing_object_ids = set(related_model.objects.filter(**obj_fields).values_list('id', flat=True))

                val: BaseModel
                for val in value:
                    def get_subobj(force_create: bool = False):
                        if action == TransferAction.SYNC and not getattr(val, 'id', None) and not 'sync_matching' in field.field_info.extra:
                            force_create = True

                        if force_create or action == TransferAction.CREATE:
                            create_fields = {}
                            if getattr(val, 'id', None):
                                create_fields['id'] = getattr(val, 'id', None)

                            return related_model(**obj_fields, **create_fields)

                        elif action == TransferAction.SYNC:
                            try:
                                if getattr(val, 'id', None):
                                    return related_model.objects.get(id=val.id, **obj_fields)

                                elif 'sync_matching' in field.field_info.extra:
                                    matching = field.field_info.extra['sync_matching']
                                    if isinstance(matching, list):
                                        matching_search = models.Q()
                                        pydantic_field_name: str
                                        match_orm_field: models.Field
                                        for pydantic_field_name, match_orm_field in matching:
                                            match_value = val
                                            for _field in pydantic_field_name.split('.'):
                                                match_value = getattr(match_value, _field)

                                            if isinstance(match_value, Reference):
                                                match_value = match_value.id

                                            matching_search &= models.Q(**{match_orm_field.field.attname: match_value})

                                        return related_model.objects.filter(**obj_fields).get(matching_search)

                                    elif isinstance(matching, callable):
                                        raise NotImplementedError

                                    else:
                                        raise NotImplementedError

                                else:
                                    raise NotImplementedError

                            except related_model.DoesNotExist:
                                return get_subobj(force_create=True)

                        else:
                            raise NotImplementedError

                    sub_obj = get_subobj()
                    existing_object_ids.discard(sub_obj.id)
                    subobjects.append(sub_obj)
                    sub_transfer = transfer_to_orm(val, sub_obj, exclude_unset=exclude_unset, access=access, action=action, _just_return_objs=True)
                    subobjects += sub_transfer[0]
                    existing_objects += sub_transfer[1]

                existing_objects += related_model.objects.filter(id__in=list(existing_object_ids))

            else:
                raise NotImplementedError

        else:
            raise NotImplementedError

    if subobjects and not action:
        raise AssertionError('action is not defined but subobjects exist')

    if _just_return_objs:
        return subobjects, existing_objects

    if action in (TransferAction.CREATE, TransferAction.SYNC, TransferAction.NO_SUBOBJECTS) and created_submodels is None:
        with atomic():
            django_obj.save()

            if action in (TransferAction.CREATE, TransferAction.SYNC):
                if action == TransferAction.SYNC:
                    for obj in existing_objects:
                        obj.delete()

                for obj in subobjects:
                    obj.save()


async def update_orm(model: Type[BaseModel], orm_obj: models.Model, input: BaseModel, *, access: Optional[Access] = None) -> BaseModel:
    """
    Apply (partial) changes given in `input` to an orm_obj and return an instance of `model` with the full data of the orm including the updated fields.
    """
    warnings.warn("Use transfer_to_orm with exclude_unset=True instead of this function", category=DeprecationWarning)

    if access:
        check_field_access(input, access)

    data = await model.from_orm(orm_obj)
    input_dict: dict = input.dict(exclude_unset=True)

    def update(model: BaseModel, input: dict):
        for key, value in input.items():
            if isinstance(value, dict):
                attr = getattr(model, key)
                if attr is None:
                    setattr(model, key, model.__fields__[key].type_.parse_obj(value))

                else:
                    update(attr, value)

            else:
                setattr(model, key, value)

    update(data, input_dict)

    values, fields_set, validation_error = validate_model(model, data.dict())
    if validation_error:
        raise RequestValidationError(validation_error.raw_errors)

    transfer_to_orm(data, orm_obj)
    return data
