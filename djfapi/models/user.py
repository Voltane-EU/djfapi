from typing import Optional, Tuple, Set, List
from datetime import timedelta
from jose import jwt
from django.utils.crypto import get_random_string
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings
from django.db import models
from djdantic.schemas import Access, Error
from ..exceptions import AuthError


class AbstractUserTokenMixin(models.Model):
    def _save_user_token(self, token_id: str):
        raise NotImplementedError

    def _save_transaction_token(self, token_id: str):
        return

    def _get_user_token(self, token_id: str):
        raise NotImplementedError

    def validate_used_token(self, token: Access):
        try:
            return self._get_user_token(token.jti)

        except ObjectDoesNotExist as error:
            raise AuthError(detail=Error(code='invalid_user_token')) from error

    def _create_token(
        self,
        *,
        validity: timedelta,
        audiences: List[str] = [],
        include_critical: bool = False,
    ) -> Tuple[str, str]:
        time_now = timezone.now()
        token_id = get_random_string(128)

        claims = {
            'iss': settings.JWT_ISSUER,
            'iat': time_now,
            'nbf': time_now,
            'exp': time_now + validity,
            'sub': self.id,
            'ten': self.tenant.id,
            'crt': include_critical,
            'aud': audiences,
            'jti': token_id,
        }

        token = jwt.encode(
            claims=claims,
            key=settings.JWT_PRIVATE_KEY,
            algorithm='ES512',
        )

        return token, token_id

    class Meta:
        abstract = True


class AbstractUserRefreshTokenMixin(AbstractUserTokenMixin):
    class Meta:
        abstract = True


class AbstractUserTransactionTokenMixin(AbstractUserTokenMixin):
    def get_scopes(self, include_critical: bool = False) -> Set[str]:
        return []

    def create_transaction_token(self, include_critical: bool = False, used_token: Optional[Access] = None) -> str:
        audiences: List[str] = list(self.get_scopes(include_critical=include_critical))

        if used_token:
            self._get_user_token(used_token.jti)

        token, token_id = self._create_token(
            validity=timedelta(minutes=5),
            audiences=audiences,
            include_critical=include_critical,
        )

        self._save_transaction_token(token_id)

        return token

    def create_user_token(self) -> str:
        token, token_id = self._create_token(
            validity=timedelta(days=365),
            audiences=['djfapi.auth.obtain_transaction_token'],
        )

        self._save_user_token(token_id)

        return token

    class Meta:
        abstract = True
