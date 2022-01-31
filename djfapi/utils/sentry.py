import threading
from functools import wraps
from typing import Callable, Optional, Union, List
from sentry_sdk import start_span, capture_exception as sentry_capture_exception, set_tag
from sentry_sdk.tracing import Span
from contextvars import ContextVar


span: ContextVar[Span] = ContextVar('span')


def instrument_span(op: str, description: Optional[Union[str, Callable]] = None, force_new_span: bool = False, **instrument_kwargs):
    def wrapper(wrapped):
        @wraps(wrapped)
        def with_instrumentation(*args, **kwargs):
            try:
                parent_span = span.get()

            except LookupError:
                parent_span = None

            if parent_span and not force_new_span:
                _span = parent_span.start_child(
                    description=description(*args, **kwargs) if callable(description) else description,
                    **instrument_kwargs,
                )

            else:
                _span = start_span(
                    op=op,
                    description=description(*args, **kwargs) if callable(description) else description,
                    **instrument_kwargs,
                )

            with _span:
                try:
                    _span.set_data("threading.current_thread", threading.current_thread().getName())

                except Exception:
                    pass

                span.set(_span)

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
