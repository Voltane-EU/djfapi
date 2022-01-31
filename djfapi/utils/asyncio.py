from asyncio import coroutine, get_event_loop
from functools import partial, wraps
from typing import Callable, Optional
from .sentry import instrument_span, span as span_ctx


def is_async():
    try:
        event_loop = get_event_loop()

    except RuntimeError:
        pass

    else:
        if event_loop.is_running():
            return True

    return False


def _sync_to_async(func):
    @wraps(func)
    async def run(*args, **kwargs):
        return await get_event_loop().run_in_executor(None, partial(func, *args, **kwargs))

    return run


def sync_to_async(callable: Optional[Callable] = None, **wrapper_kwargs):
    @wraps(callable)
    @instrument_span('asyncio.sync_to_async')
    def wrapper(*args, **kwargs):
        return _sync_to_async(
            instrument_span(
                'asyncio.sync_to_async.callable',
                description=callable.__name__,
            )(callable),
        **wrapper_kwargs)(*args, **kwargs)

    if callable is None:
        return lambda c: sync_to_async(c, **wrapper_kwargs)

    return coroutine(wrapper)
