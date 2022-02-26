from pydantic import Extra
from fastapi.openapi.models import Schema


# Since fastapi 0.66.0 the OpenAPI Schema includes fields extra attributes in the schema
# included with MR https://github.com/tiangolo/fastapi/pull/1429
# This prevents our orm_field field attributes to work properly, as it now causes an infinite recursion
# when creating the openapi json schema. To overcome that problem until it is fixed, set Schema's extra to ignore
# as it was before that change.
# https://github.com/tiangolo/fastapi/issues/3745
Schema.__config__.extra = Extra.ignore
