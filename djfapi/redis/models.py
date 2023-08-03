from .utils import get_connection


class AbstractUserTransactionTokenDjangoPermissions2RedisMixin:
    redis_url = None
    redis = None

    def _save_transaction_token(self, token_id: str):
        if not self.redis:
            self.redis = get_connection(self.redis_url)

        key = f'access:token:{token_id}:scopes'
        self.redis.sadd(key, *self.get_all_permissions())
        self.redis.expire(key, int(timedelta(minutes=5).total_seconds()))
