from typing import Any, Optional, List, Set, Type
from datetime import datetime
from pydantic import BaseModel, Field, validator


class AccessScopes(set):
    pass


class Access(BaseModel):
    token: 'AccessToken'
    scope: Optional['AccessScope'] = None
    scopes: Optional[Set['AccessScope']] = None

    user: Optional[Any] = None

    @property
    def user_id(self) -> str:
        return self.token.sub

    @property
    def tenant_id(self) -> str:
        return self.token.ten


class AccessToken(BaseModel):
    iss: str = Field(title='Issuer')
    iat: datetime = Field(title='Issued At')
    nbf: datetime = Field(title='Not Before')
    exp: datetime = Field(title='Expire At')
    sub: str = Field(title='Subject (User)')
    ten: str = Field(title='Tenant')
    aud: List[str] = Field(default=[], title='Audiences')
    rls: List[str] = Field(default=[], title='Roles')
    jti: str = Field(title='JWT ID')
    crt: bool = Field(False, title='Critical')

    def has_audience(self, audiences: List[str]) -> Optional[str]:
        for audience in audiences:
            if audience in self.aud:
                return audience

        return

    def has_audiences(self, audiences: List[str]) -> List[str]:
        return [audience for audience in audiences if audience in self.aud]

    def get_scopes(self):
        audiences = [AccessScope.from_str(audience) for audience in self.aud]
        return audiences

    def __contains__(self, item):
        if isinstance(item, AccessScope):
            return str(item) in self.aud

        if isinstance(item, str):
            return item in self.aud

        raise NotImplementedError


class AccessScope(BaseModel):
    service: str
    resource: str
    action: str
    selector: Optional[str] = None

    @classmethod
    def from_str(cls, scope: str):
        scopes = scope.split('.') + [None]
        return cls(
            service=scopes[0],
            resource=scopes[1],
            action=scopes[2],
            selector=scopes[3],
        )

    def __str__(self):
        return '.'.join(filter(lambda s: s, [self.service, self.resource, self.action, self.selector,]))

    def __hash__(self) -> int:
        return hash(self.__str__())


Access.update_forward_refs()
AccessToken.update_forward_refs()
