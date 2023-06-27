"""Temporary macros used only for testing."""

from ..content import Content
from ..macro import Macro


def get_expand_func(ref: str):
    def func(**_kwargs):
        return Content('{{%s}}' % ref, preprocess=True)
    return func


Macro('aaa', macro_body=get_expand_func('bbb'))
Macro('bbb', macro_body=get_expand_func('ccc'))
Macro('ccc', macro_body=get_expand_func('aaa'))
