from typing import List, Optional
from enum import Enum
from fastapi import Query
from ..schemas import Pagination


class CacheControl(Enum):
    NO_CACHE = 'no-cache'


def depends_pagination(max_limit: Optional[int] = 1000, default_order_by: Optional[List[str]] = None):
    def get_pagination(
        limit: Optional[int] = Query(None, le=max_limit, ge=1),
        offset: Optional[int] = Query(None, ge=0),
        order_by: List[str] = Query(default_order_by or list()),
    ) -> Pagination:
        if offset is None:
            offset = 0

        return Pagination(
            limit=offset + (limit or max_limit),
            offset=offset,
            order_by=[col.value if isinstance(col, Enum) else col for col in order_by],
        )

    return get_pagination
