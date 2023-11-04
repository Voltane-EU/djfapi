from ..security.jwt import JWTTokenDjangoPermissions
from .utils import get_connection


class AbstractUserTransactionTokenDjangoPermissions2RedisMixin:
    redis_url = None
    redis = None

    def _save_transaction_token(self, token_id: str):
        permissions = [
            JWTTokenDjangoPermissions.convert_permission_to_scope(permission)
            for permission in self.get_all_permissions()
        ]
        if not permissions:
            return

        if not self.redis:
            self.redis = get_connection(self.redis_url)

        key = f'access:token:{token_id}:scopes'
        self.redis.sadd(
            key,
            *permissions,
        )
        self.redis.expire(key, 310)  # Transaction Token expires after 5 minutes (300s) + buffer (10s)
