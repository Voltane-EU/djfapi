from typing import List


def remove_none(d):
    if isinstance(d, dict):
        return {key: remove_none(value) for key, value in d.items() if value is not None}

    else:
        return d


def key_in_dict(keys: List[str], d: dict) -> bool:
    for key in keys:
        if key in d:
            return True

    return False
