from django.db import models


def dict_resolve_obj_to_id(input):
    if isinstance(input, models.Model):
        return input.pk

    if not isinstance(input, dict):
        return input

    for key, value in input.items():
        input[key] = dict_resolve_obj_to_id(value)

    return input
