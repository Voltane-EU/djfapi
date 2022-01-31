from typing import Mapping, Optional, Type, TypeVar, Union
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, validate_model
from django.db import models
from django.db.models.manager import Manager
from ...security.jwt import access as access_ctx
from ..django import AllowAsyncUnsafe
from .django_to_pydantic import transfer_from_orm


class DjangoORMBaseModel(BaseModel):
    @classmethod
    def from_orm(cls, obj: models.Model, filter_submodel: Optional[Mapping[Manager, models.Q]] = None):
        return transfer_from_orm(cls, obj, filter_submodel=filter_submodel)

    class Config:
        orm_mode = True


def validate_object(obj: BaseModel, is_request: bool = True):
    *_, validation_error = validate_model(obj.__class__, obj.__dict__)
    if validation_error:
        if is_request:
            raise RequestValidationError(validation_error.raw_errors)

        raise validation_error


TDjangoModel = TypeVar('TDjangoModel', bound=models.Model)

def orm_object_validator(model: Type[TDjangoModel], value: Union[str, models.Q]) -> TDjangoModel:
    if isinstance(value, str):
        value = models.Q(id=value)

    access = access_ctx.get()
    if access and hasattr(model, 'tenant_id'):
        value &= models.Q(tenant_id=access.tenant_id)

    with AllowAsyncUnsafe():
        try:
            return model.objects.get(value)

        except model.DoesNotExist:
            raise ValueError('reference_not_exist')
