from decimal import Decimal
from typing import List, Optional, Union
from enum import Enum
from psycopg2 import errorcodes as psycopg2_error_codes
from pydantic import BaseModel, Extra
from pydantic.error_wrappers import ErrorWrapper
from django.db.models import Q, QuerySet, Manager, aggregates
from django.db.utils import ProgrammingError
from fastapi.exceptions import RequestValidationError
from .fastapi import Pagination


class AggregationFunction(Enum):
    avg = 'avg'
    count = 'count'
    max = 'max'
    min = 'min'
    sum = 'sum'


class AggregateResponse(BaseModel):
    class Value(BaseModel, extra=Extra.allow):
        value: Union[int, float, Decimal]

    values: List[Value]


def aggregation(
    objects: Union[QuerySet, Manager],
    *,
    q_filters: Q = Q(),
    aggregation_function: Enum,
    field: Enum,
    group_by: Optional[List[str]] = None,
    pagination: Pagination,
):
    def aggregate():
        query = objects.filter(q_filters)
        fields = []
        annotations = {
            'value': getattr(aggregates, aggregation_function.value.title())(field.value),
        }

        try:
            if group_by:
                fields += [g.value for g in group_by]
                query = query.values(*fields).annotate(**annotations)
                return list(pagination.query(query).values(*fields, 'value'))

            else:
                query = query.aggregate(**annotations)
                return [query]

        except ProgrammingError as error:
            if error.__cause__.pgcode in (psycopg2_error_codes.UNDEFINED_FUNCTION):
                raise RequestValidationError([
                    ErrorWrapper(ProgrammingError(), ("query", "aggregation_function"))
                ]) from error

            raise

    return {
        'values': aggregate()
    }
