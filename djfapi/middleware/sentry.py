from starlette.types import Message
from sentry_sdk import Hub


class SentryAsgiMiddleware:
    __slots__ = ('app',)

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def _send(message: Message):
            try:
                message.get('headers', list()).append(
                    (b'X-Flow-ID', Hub.current.scope.transaction.to_traceparent())
                )

            except AttributeError:
                pass

            await send(message)

        return await self.app(scope, receive, _send)
