from typing import Optional
from langcodes import Language


def format_language(value: Optional[str]):
    lang = Language.get(value)

    if not lang.is_valid():
        raise ValueError('language_invalid')

    return lang.simplify_script().to_tag()
