from pydantic import BaseModel, Field, Extra
from fastapi import Body
from fastapi.routing import APIRouter
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser
from ..models.user import AbstractUserRefreshTokenMixin
from ..routing.registry import register_router


class RefreshTokenSchema(BaseModel, arbitrary_types_allowed=True, extra=Extra.allow):
    class AuthorizeResponse(BaseModel):
        pass  # TODO

    class AuthorizeRequest(BaseModel):
        pass  # TODO

    class RefreshResponse(BaseModel):
        pass  # TODO

    class RefreshRequest(BaseModel):
        pass  # TODO

    user_model: AbstractUser = Field(default_factory=get_user_model)
    router: APIRouter = Field(default_factory=APIRouter)
    route_prefix: str = '/auth'

    def __init__(self, *args, **kwargs):
        super().__init__()

        if not issubclass(self.user_model, AbstractUserRefreshTokenMixin):
            raise TypeError("The active user model must inherit from djfapi.models.user.AbstractUserRefreshTokenMixin")

        self._init_routes()

    def authorize(self, data: AuthorizeRequest = Body(...)):
        pass

    def refresh(self, data: RefreshRequest = Body(...)):
        pass

    def _init_routes(self):
        self.router.add_api_route('/authorize', self.authorize, response_model=self.AuthorizeResponse, methods=['POST'])
        self.router.add_api_route('/refresh', self.refresh, response_model=self.RefreshResponse, methods=['POST'])

        register_router(self.router, prefix=self.route_prefix, tags=['auth'])


class TransactionTokenSchema(BaseModel, arbitrary_types_allowed=True, extra=Extra.allow):
    class AuthorizeResponse(BaseModel):
        pass  # TODO

    class AuthorizeRequest(BaseModel):
        pass  # TODO

    class RefreshResponse(BaseModel):
        pass  # TODO

    class RefreshRequest(BaseModel):
        pass  # TODO

    user_model: AbstractUser = Field(default_factory=get_user_model)
    router: APIRouter = Field(default_factory=APIRouter)
    route_prefix: str = '/auth'

    def __init__(self, *args, **kwargs):
        super().__init__()

        if not issubclass(self.user_model, AbstractUserRefreshTokenMixin):
            raise TypeError("The active user model must inherit from djfapi.models.user.AbstractUserRefreshTokenMixin")

        self._init_routes()

    def authorize(self, data: AuthorizeRequest = Body(...)):
        pass

    def refresh(self, data: RefreshRequest = Body(...)):
        pass

    def _init_routes(self):
        self.router.add_api_route('/authorize', self.authorize, response_model=self.AuthorizeResponse, methods=['POST'])
        self.router.add_api_route('/refresh', self.refresh, response_model=self.RefreshResponse, methods=['POST'])

        register_router(self.router, prefix=self.route_prefix, tags=['auth'])
