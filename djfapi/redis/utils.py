from typing import Optional
from django.conf import settings
from redis.asyncio import Redis as RedisAsync, RedisCluster as RedisAsyncCluster
from redis import Redis, RedisCluster


CONNECTIONS = {}


def get_connection(
    redis_url: Optional[str] = None, use_async: bool = False, is_cluster: Optional[bool] = None
) -> 'Redis':
    if is_cluster is None:
        is_cluster = getattr(settings, 'REDIS_IS_CLUSTER', False)

    if use_async:
        R = RedisAsyncCluster if is_cluster else RedisAsync

    else:
        R = RedisCluster if is_cluster else Redis

    redis_url = redis_url or getattr(settings, 'REDIS_URL', None) or 'redis://localhost:6379/0'

    try:
        return CONNECTIONS[(redis_url, use_async)]

    except KeyError:
        CONNECTIONS[(redis_url, use_async)] = R.from_url(redis_url)
        return CONNECTIONS[(redis_url, use_async)]
