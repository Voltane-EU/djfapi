from __future__ import annotations
from enum import Enum
from typing import List, Optional, Sequence, Type, Any, TypeVar, Dict
from abc import ABC
from pydantic import BaseModel, root_validator, create_model, Extra
from fastapi.security.base import SecurityBase


TBaseModel = TypeVar('TBaseModel', bound=BaseModel)
TCreateModel = TypeVar('TCreateModel', bound=BaseModel)
TUpdateModel = TypeVar('TUpdateModel', bound=BaseModel)


class Method(Enum):
    GET_LIST = 'list'
    GET_AGGREGATE = 'aggregate'
    GET = 'get'
    POST = 'post'
    PATCH = 'patch'
    PUT = 'put'
    DELETE = 'delete'


class RouterSchema(BaseModel, arbitrary_types_allowed=True, extra=Extra.allow):
    name: str
    list: Optional[Type[BaseModel]] = None
    get: Type[TBaseModel]
    create: Optional[Type[TCreateModel]] = None
    create_multi: bool = False
    update: Optional[Type[TUpdateModel]] = None
    delete: bool = True
    children: List[RouterSchema] = []
    parent: Optional[RouterSchema] = None
    security: Optional[SecurityBase] = None
    security_scopes: Optional[Dict[Method, Sequence[str]]] = None

    def _init_list(self):
        self.list = create_model(f"{self.get.__qualname__}List", __module__=self.get.__module__, items=(List[self.get], ...))

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)

        for child in self.children:
            child.parent = self

        if not self.list:
            self._init_list()


RouterSchema.update_forward_refs()


class BaseRouter(ABC):
    pass
