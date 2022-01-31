from starlette.types import Message
from sentry_sdk.integrations.asgi import SentryAsgiMiddleware as BaseSentryAsgiMiddleware
from sentry_sdk import Hub


class SentryAsgiMiddleware(BaseSentryAsgiMiddleware):
    def event_processor(self, event, hint, asgi_scope):
        if event.get('type') != 'transaction':
            asgi_scope['sentry_event_id'] = event['event_id']

        return super().event_processor(event, hint, asgi_scope)

    async def _run_asgi3(self, scope, receive, send):
        async def _send(message: Message):
            try:
                message.get('headers', list()).append(
                    (b'X-Flow-ID', Hub.current.scope.transaction.to_traceparent())
                )

            except AttributeError:
                pass

            await send(message)

        return await self._run_app(scope, lambda: self.app(scope, receive, _send))

