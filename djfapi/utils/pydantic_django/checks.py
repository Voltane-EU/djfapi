from typing import List, Optional
from pydantic import BaseModel
from ...schemas import Access, Error
from ...exceptions import AccessError


def check_field_access(input: BaseModel, access: Access):
    """
    Check access to fields.

    To define scopes of a field, add a list of scopes to the Field defenition in the kwarg scopes.

    Example:
    ```python
    from pydantic import BaseModel, Field

    class AddressRequest(BaseModel):
        name: str = Field(scopes=['elysium.addresses.update.any',])
    ```
    """
    def check(model: BaseModel, input: dict, access: Access, loc: Optional[List[str]] = None):
        if not loc:
            loc = ['body',]

        for key, value in input.items():
            if isinstance(value, dict):
                try:
                    check(getattr(model, key), value, access, loc=loc + [key])

                except AttributeError:
                    pass

            elif key in model.__fields__:
                scopes = model.__fields__[key].field_info.extra.get('scopes')
                if scopes:
                    if not access.token.has_audience(scopes):
                        raise AccessError(detail=Error(
                            type='FieldAccessError',
                            code='access_error.field',
                            detail={
                                'loc': loc + [key],
                            },
                        ))

                elif model.__fields__[key].field_info.extra.get('is_critical'):
                    if not access.token.crt:
                        raise AccessError(detail=Error(
                            type='FieldAccessError',
                            code='access_error.field_is_critical',
                            detail={
                                'loc': loc + [key],
                            },
                        ))

    check(input, input.dict(exclude_unset=True), access)
