# djfapi

A utility library to integrate and use fastapi with the django orm.

<small>djfapi is based on [olympus](https://github.com/LaVita-GmbH/olympus).</small>

Provides optional integration with `sentry-sdk`.

## Features

### pydantic to django Data Schema Conversion

- `djfapi.utils.pydantic_django.DjangoORMBaseModel`  
  Provides `from_orm` method on pydantic schema
- `djfapi.utils.pydantic_django.transfer_from_orm`
- `djfapi.utils.pydantic_django.transfer_to_orm`

If [automatic route generation](#automatic-route-generation) is used, it is not neccessary to use the `transfer_*` methods manually.

#### Options for pydantic's `Field`

For mapping pydantic schemas to django models, it is required to add at least one of the following extra arguments to each field defined in a pydantic schema.

- `orm_field`: `django.db.models.Field` *(required)*  
  Pointer (reference) to the corresponding model field, e. g. `myapp.models.MyModel.id`
- `orm_method`: `Optional[Callable[[Self], Any] | Callable[[Self, Any], None]]`  
  Pointer to a orm model method, which is called when the object is loaded from the orm into a pydantic model or written into the orm from a pydantic model, e. g. `myapp.models.MyModel.get_calculated_value`
- `scopes`: `Optional[List[str]]`  
  Limit access to specific fields based on jwt token scopes. For read operations, only scopes with the action `read` are taken into account, for write all other scopes are taken into account.
- `is_critical`: `Optional[bool]`  
  Limit **write** access to the field based on the presence of the `crt` flag in the jwt token.
- `sync_matching`: `Optional[List[Tuple[str, django.db.models.Field]]]`  
  Used for performing a `transfer_to_orm` with action `TransferAction.SYNC` for included sub-records (in a list), used when no `id` field is present on the object. Mapping from pydantic field (dot notation for nested fields can be used) to the corresponding django model field.

#### Example for Schemas

```python
from pydantic import Field, BaseModel
from djfapi.utils.pydantic_django import DjangoORMBaseModel
from ... import models


class User(DjangoORMBaseModel):
    email: str = Field(orm_field=models.User.email)
    is_password_usable: bool = Field(orm_method=models.User.has_usable_password)
    is_superuser: bool = Field(scopes=['access.users.update.any'], is_critical=True, orm_field=models.User.is_superuser)


class UserUpdate(BaseModel):
    password: Optional[SecretStr] = Field(orm_method=models.User.set_password, is_critical=True)


class OrderUpdate(BaseModel):
    items: Optional[List['OrderItemUpdate']] = Field(
        orm_field=models.Order.items,
        sync_matching=[
            ('product', models.OrderItem.product),
        ],
    )
```

### Automatic Route Generation

Declare routes without having to write routes using the `djfapi.routing.django.DjangoRouterSchema`.

The `DjangoRouterSchema` will supply a router, which just has to be included in the FastAPI app.

#### Example for Routes

```python
from djfapi.routing.django import DjangoRouterSchema, SecurityScopes


transaction_token = JWTToken(scheme_name="Transaction Token")


def company_objects_filter(access: Access) -> Q:
    q = Q(tenant_id=access.tenant_id)
    if access.scope.selector != 'any':
        q &= Q(employees__user_id=access.user_id, employees__type__in=[models.Employee.EmployeeType.OWNER, models.Employee.EmployeeType.ADMIN])

    return q


router = DjangoRouterSchema(
    name='companies',
    model=models.Company,
    get=schemas.response.Company,
    create=schemas.request.CompanyCreate,
    update=schemas.request.CompanyUpdate,
    security=transaction_token,
    security_scopes=SecurityScopes(
        get=['business.companies.read.any', 'business.companies.read.own',],
        post=['business.companies.create',],
        patch=['business.companies.update.any', 'business.companies.update.own',],
        put=['business.companies.update.any', 'business.companies.update.own',],
        delete=['business.companies.delete.any', 'business.companies.delete.own',],
    ),
    objects_filter=company_objects_filter,
    children=[
        DjangoRouterSchema(
            name='departments',
            model=models.CompanyDepartment,
            get=schemas.response.CompanyDepartment,
            create=schemas.request.CompanyDepartmentCreate,
            update=schemas.request.CompanyDepartmentUpdate,
            children=[
                DjangoRouterSchema(
                    name='teams',
                    model=models.CompanyDepartmentTeam,
                    get=schemas.response.CompanyDepartmentTeam,
                    create=schemas.request.CompanyDepartmentTeamCreate,
                    update=schemas.request.CompanyDepartmentTeamUpdate,
                ),
            ]
        ),
        DjangoRouterSchema(
            name='costcenters',
            model=models.CompanyCostcenter,
            get=schemas.response.CompanyCostcenter,
            create=schemas.request.CompanyCostcenterCreate,
            update=schemas.request.CompanyCostcenterUpdate,
        ),
    ]
)
```
