from typing import List, Union
from pydantic import BaseModel
from pydantic.error_wrappers import ErrorWrapper
from django.db.models import Q, QuerySet
from django.db.models.manager import BaseManager
from django.core.exceptions import FieldDoesNotExist, FieldError
from fastapi.exceptions import RequestValidationError


class Pagination(BaseModel):
    limit: int
    offset: int
    order_by: List[str]

    def query(self, objects: Union[BaseManager, QuerySet], q_filters: Q = Q()) -> QuerySet:
        """
        Filter a given model's BaseManager or pre-filtered Queryset with the given q_filters and apply order_by and offset/limit from the pagination.
        """
        try:
            return objects.filter(q_filters).order_by(*self.order_by)[self.offset:self.limit]

        except (FieldDoesNotExist, FieldError) as error:
            raise RequestValidationError([
                ErrorWrapper(error, ("query", "order_by"))
            ]) from error
