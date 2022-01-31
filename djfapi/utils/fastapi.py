from typing import List, Optional
from fastapi import Query
from ..schemas import Pagination


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
            order_by=order_by,
        )

    return get_pagination
