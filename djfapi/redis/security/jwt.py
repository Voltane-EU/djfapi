from typing import Optional
from djfapi.security.jwt import JWTToken
from ..utils import get_connection


class JWTTokenRedis(JWTToken):
    def __init__(self, *args, redis_url: Optional[str] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.redis = get_connection(redis_url, use_async=True)

    async def _create_access(self, token):
        access = await super()._create_access(token)
        scopes = await self.redis.smembers(f'access:token:{access.jti}:scopes')
        access.token.aud = [str(scope, 'utf-8') for scope in scopes]
        return access
