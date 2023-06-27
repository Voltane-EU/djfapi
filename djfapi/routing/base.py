from __future__ import annotations
from enum import Enum
from typing import List, Optional, Sequence, Type, Any, TypeVar, Dict, Union
from abc import ABC
from pydantic import BaseModel, root_validator, create_model, Extra, Field
from pydantic.fields import UndefinedType
from fastapi.security.base import SecurityBase
from ..utils.fastapi import CacheControl
from djdantic.schemas.access import AccessScope


TBaseModel = TypeVar("TBaseModel", bound=BaseModel)
TCreateModel = TypeVar("TCreateModel", bound=BaseModel)
TUpdateModel = TypeVar("TUpdateModel", bound=BaseModel)


class Method(Enum):
    GET_LIST = "list"
    GET_AGGREGATE = "aggregate"
    GET = "get"
    POST = "post"
    PATCH = "patch"
    PUT = "put"
    DELETE = "delete"


_list = list


class SecurityScopes(BaseModel):
    get: Optional[List[AccessScope]] = Field(default_factory=_list)
    list: Optional[List[AccessScope]] = Field(default_factory=_list)
    aggregate: Optional[List[AccessScope]] = Field(default_factory=_list)
    post: Optional[List[AccessScope]] = Field(default_factory=_list)
    patch: Optional[List[AccessScope]] = Field(default_factory=_list)
    put: Optional[List[AccessScope]] = Field(default_factory=_list)
    delete: Optional[List[AccessScope]] = Field(default_factory=_list)

    auto: Optional[List[str]]

    @root_validator(pre=True)
    def transform_scopes(cls, values):
        for key in ("get", "list", "aggregate", "post", "patch", "put", "delete"):
            if values.get(key):
                values[key] = [
                    AccessScope.from_str(scope) if isinstance(scope, str) else scope
                    for scope in values[key]
                ]

        if values.get("get"):
            for key in ("list", "aggregate"):
                if not values.get(key):
                    values[key] = values["get"]

        return values

    def __get__(self):
        if self.auto:
            return self

        return self


class RouterSchema(BaseModel, arbitrary_types_allowed=True, extra=Extra.allow):
    name: str
    list: Optional[Union[Type[BaseModel], UndefinedType]] = None
    get: Type[TBaseModel]
    get_endpoint: bool = True
    create: Optional[Union[Type[TCreateModel], UndefinedType]] = None
    create_multi: bool = False
    update: Optional[Union[Type[TUpdateModel], UndefinedType]] = None
    delete: bool = True
    children: List[RouterSchema] = []
    parent: Optional[RouterSchema] = None
    security: Optional[SecurityBase] = None
    security_scopes: Optional[SecurityScopes] = None
    cache_control: Optional[CacheControl] = None

    def _init_list(self):
        self.list = create_model(
            f"{self.get.__qualname__}List",
            __module__=self.get.__module__,
            items=(List[self.get], ...),
        )

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)

        for child in self.children:
            child.parent = self

        if not self.list:
            self._init_list()


RouterSchema.update_forward_refs()


class BaseRouter(ABC):
    pass
