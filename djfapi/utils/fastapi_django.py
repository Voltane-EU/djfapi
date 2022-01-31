import os
from typing import List, Optional, Union
from enum import Enum
from psycopg2 import errorcodes as psycopg2_error_codes
from pydantic.error_wrappers import ErrorWrapper
from django.db.models import Q, QuerySet, Manager, aggregates
from django.db.utils import ProgrammingError
from fastapi.exceptions import RequestValidationError
from .fastapi import Pagination

if os.getenv('USE_ASYNCIO'):
    from .asyncio import sync_to_async

else:
    from .sync import sync_to_async


class AggregationFunction(Enum):
    avg = 'avg'
    count = 'count'
    max = 'max'
    min = 'min'
    sum = 'sum'


async def aggregation(
    objects: Union[QuerySet, Manager],
    *,
    q_filters: Q = Q(),
    aggregation_function: Enum,
    field: Enum,
    group_by: Optional[List[str]] = None,
    pagination: Pagination,
):
    @sync_to_async
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
        'values': await aggregate()
    }