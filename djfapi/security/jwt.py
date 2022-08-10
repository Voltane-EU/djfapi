from typing import Optional
from jose import jwt
from fastapi import HTTPException
from fastapi.security import SecurityScopes
from fastapi.security.api_key import APIKeyHeader
from starlette.requests import Request
from djdantic import context
from djdantic.schemas import Error, Access, AccessToken, AccessScope
from sentry_tools import set_user, set_extra
from ..exceptions import AuthError


class JWTToken(APIKeyHeader):
    def __init__(
        self, *, name: str = 'Authorization', scheme_name: Optional[str] = None, auto_error: bool = True, key: str, algorithm: str, issuer: Optional[str] = None,
    ):
        self.key = key
        self.algorithms = [algorithm]
        self.issuer = issuer

        super().__init__(name=name, scheme_name=scheme_name, auto_error=auto_error)

    def decode_token(self, token, audience=None):
        return jwt.decode(
            token=token,
            key=self.key,
            algorithms=self.algorithms,
            issuer=self.issuer,
            audience=audience,
            options={
                'verify_aud': bool(audience),
            },
        )

    async def __call__(self, request: Request, scopes: SecurityScopes = None) -> Optional[Access]:
        try:
            token = await super().__call__(request)

        except HTTPException as error:
            if error.status_code == 403:
                raise AuthError from error

            raise

        if not token:
            return

        current_access = Access(
            token=AccessToken(**self.decode_token(token)),
        )
        set_extra('access.token.aud', current_access.token.aud)

        set_user({
            'id': current_access.user_id,
            'tenant_id': current_access.tenant_id,
        })

        if scopes and scopes.scopes:
            audiences = current_access.token.has_audiences(scopes.scopes)
            if not audiences:
                raise HTTPException(status_code=403, detail=Error(
                    type='JWTClaimsError',
                    code='required_audience_missing',
                    message='The required scope is not included in the given token.',
                    detail=scopes.scopes,
                ))

            aud_scopes = [AccessScope.from_str(audience) for audience in audiences]
            current_access.scopes = aud_scopes
            current_access.scope = aud_scopes[0]
            set_extra('access.scopes', aud_scopes)

        context.access.set(current_access)

        return current_access
