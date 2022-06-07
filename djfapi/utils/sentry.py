import threading
from functools import wraps
from typing import Callable, Optional, Union
from sentry_sdk import Hub, start_span, capture_exception as sentry_capture_exception, set_tag


def instrument_span(op: Optional[str] = None, description: Optional[Union[str, Callable[..., str]]] = None, force_new_span: bool = False, **instrument_kwargs):
    def wrapper(wrapped):
        @wraps(wrapped)
        def with_instrumentation(*args, **kwargs):
            parent_span = Hub.current.scope.span

            span_args = {
                'op': op or wrapped.__qualname__,
                'description': description(*args, **kwargs) if callable(description) else description,
                **instrument_kwargs,
            }

            if parent_span and not force_new_span:
                _span = parent_span.start_child(**span_args)

            else:
                _span = start_span(**span_args)

            with _span:
                _span.set_data("threading.current_thread", threading.current_thread().getName())

                return wrapped(*args, **kwargs)

        return with_instrumentation

    return wrapper


def capture_exception(func: Optional[Callable] = None):
    def _capture_exception(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)

            except Exception as error:
                set_tag('capture_exception.function', f'{func.__module__}.{func.__qualname__}')
                sentry_capture_exception(error)
                raise

        return wrapper

    if func:
        return _capture_exception(func)

    return _capture_exception
