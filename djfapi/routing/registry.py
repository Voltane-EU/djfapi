from starlette.applications import Starlette
from starlette.routing import Router


routers: dict[int, tuple[Router, list, dict]] = {}


def register_router(router: Router, *args, **kwargs):
    if id(router) in routers:
        raise ValueError(f"Router {router} already registered")

    routers[id(router)] = (router, args, kwargs)


def include_routers(app: Starlette):
    for router, args, kwargs in routers.values():
        app.include_router(router, *args, **kwargs)
