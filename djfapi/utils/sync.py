import os
from typing import Callable, Optional
from asyncio import coroutine
from functools import wraps
from asgiref import sync
from .sentry import instrument_span, span as span_ctx


def sync_to_async(callable: Optional[Callable] = None, **wrapper_kwargs):
    if os.getenv('SYNC_TO_ASYNC_NOT_THREAD_SENSITIVE') and 'thread_sensitive' not in wrapper_kwargs:
        wrapper_kwargs['thread_sensitive'] = False

    @wraps(callable)
    @instrument_span('sync_to_async')
    def wrapper(*args, **kwargs):
        return sync.sync_to_async(
            instrument_span(
                'sync_to_async.callable',
                description=callable.__name__,
            )(callable),
        **wrapper_kwargs)(*args, **kwargs)

    if callable is None:
        return lambda c: sync_to_async(c, **wrapper_kwargs)

    return coroutine(wrapper)


def async_to_sync(callable: Optional[Callable] = None, **wrapper_kwargs):
    @wraps(callable)
    @instrument_span('async_to_sync')
    def wrapper(*args, **kwargs):
        return sync.async_to_sync(
            instrument_span(
                'async_to_sync.callable',
                description=callable.__name__,
            )(callable),
        **wrapper_kwargs)(*args, **kwargs)

    if callable is None:
        return lambda c: async_to_sync(c, **wrapper_kwargs)

    return wrapper
