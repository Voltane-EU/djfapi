from decimal import Decimal
from functools import wraps
from typing import List, Optional, Union
from enum import Enum
from pydantic import BaseModel, Extra
from pydantic.error_wrappers import ErrorWrapper
from django.db.models import Q, QuerySet, Manager, aggregates
from django.db.utils import ProgrammingError
from django.core import signals
from fastapi.exceptions import RequestValidationError
from .fastapi import Pagination

try:
    from psycopg2.errorcodes import UNDEFINED_FUNCTION

    UndefinedFunction = None

except ImportError:
    from psycopg.errors import UndefinedFunction

    UNDEFINED_FUNCTION = None


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
    distinct: bool = False,
):
    def aggregate():
        query = objects.filter(q_filters)
        fields = []
        if distinct and field.value == '*':
            raise RequestValidationError(
                [ErrorWrapper(ValueError(), ('query', 'distinct'))]
            )

        annotations = {
            'value': getattr(
                aggregates,
                aggregation_function.value.title()
            )(field.value, distinct=distinct),
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
            if (UndefinedFunction and isinstance(error.__cause__, UndefinedFunction)) or (
                UNDEFINED_FUNCTION and error.__cause__.pgcode == UNDEFINED_FUNCTION
            ):
                raise RequestValidationError(
                    [ErrorWrapper(ProgrammingError(), ('query', 'aggregation_function'))]
                ) from error

            raise

    return {'values': aggregate()}


def request_signalling(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        signals.request_started.send(sender='request_signalling_wrapper')
        result = func(*args, **kwargs)
        signals.request_finished.send(sender='request_signalling_wrapper')
        return result

    return wrapper
