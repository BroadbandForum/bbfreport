"""Text layout support.

This is based on some ideas from the pandoc.layout library.
* https://pandoc.org/lua-filters.html#module-pandoc.layout
"""

# Copyright (c) 2024, Broadband Forum
#
# Redistribution and use in source and binary forms, with or
# without modification, are permitted provided that the following
# conditions are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials
#    provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products
#    derived from this software without specific prior written
#    permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND
# CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
# INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
# NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
# ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# The above license is used as a license under copyright only.
# Please reference the Forum IPR Policy for patent licensing terms
# <https://www.broadband-forum.org/ipr-policy>.
#
# Any moral rights which are necessary to exercise under the above
# license grant are also deemed granted under this license.

from numbers import Number
from typing import Optional, Sequence, Union

from .logging import Logging

logger = Logging.get_logger(__name__)

__all__ = ['blankline', 'cr', 'Doc', 'empty', 'Hang', 'Nest', 'space', 'Wrap']

# XXX some of the names are bad, e.g., Doc doesn't make sense out of context

# XXX this uses too many call stack levels; need to break out the recursion;
#     but can we still use yield? it would be nice (maybe need to insert
#     directives into the stream then process the stream sequentially, simply
#     following the instructions)


class Token:
    _value = ''
    _instances = {}

    def __init__(self):
        name = type(self).__name__
        assert name not in self._instances, f'duplicate {name} token instance'
        self._instances[name] = self

    def __len__(self):
        return len(self._value)

    def __str__(self):
        return self._value

    def __repr__(self):
        return type(self).__name__


class BlankLine(Token):
    _value = '\n\n'


class CR(Token):
    _value = '\n'


class Space(Token):
    _value = ' '


# these are singletons
blankline = BlankLine()
cr = CR()
space = Space()

ActiveType = Optional[set['Base']]
ItemType = Union[str, Number, Token, Sequence, 'Base']
RenderResult = list[ItemType]


class Base:
    def __init__(self, *items: ItemType, frozen: bool = False):
        self._items = []
        self._frozen = False
        self.append(*items)
        self._frozen = frozen

    def append(self, *items: ItemType) -> 'Base':
        assert not self._frozen, 'attempt to modify frozen layout'
        for item in items:
            if item is not None:
                self._items.append(item)
        return self

    def clear(self) -> None:
        self._items = []

    def render(self, *, prev: Optional[ItemType] = None, raw: bool = False,
               active: ActiveType = None, **kwargs) -> RenderResult:
        assert not kwargs, 'unexpected keyword arguments %s' % kwargs

        if active is None:
            active = set()

        assert self not in active, 'self-referential Doc'
        active.add(self)

        for item in self._items:
            if not isinstance(item, Base):
                # str is a Sequence, so need to check for it explicitly
                if isinstance(item, str) or not isinstance(item, Sequence):
                    yield item
                    prev = item
                else:
                    for it in item:
                        yield it
                        prev = it
            elif raw:
                for it in Base.render(item, prev=prev, raw=raw,
                                      active=active, **kwargs):
                    yield it
                    prev = it
            else:
                for it in item.render(prev=prev, raw=raw,
                                      active=active, **kwargs):
                    yield it
                    prev = it

        active.remove(self)

    # this is for debugging (it uses the Base class to render the value)
    def raw(self) -> list[str]:
        return list(Base.render(self, raw=True))

    # self + str is converted to a string
    def __add__(self, other: str) -> str:
        if isinstance(other, str):
            return str(self) + other
        return NotImplemented

    # str + self is converted to a string
    def __radd__(self, other: str) -> str:
        if isinstance(other, str):
            return other + str(self)
        return NotImplemented

    # self += item modifies self
    def __iadd__(self, *other: ItemType) -> 'Base':
        return self.append(*other)

    # note that this doesn't check whether it renders to an empty string,
    # e.g. Doc('') is not empty because it contains items
    @property
    def is_empty(self) -> bool:
        return len(self._items) == 0

    @property
    def items(self) -> list[ItemType]:
        return self._items

    @property
    def frozen(self) -> bool:
        return self._frozen

    def __str__(self):
        return ''.join(str(item) for item in self.render())

    def __repr__(self):
        return repr(list(self.render()))


class Splitter(Base):
    def render(self, **kwargs) -> RenderResult:
        for item in super().render(**kwargs):
            if not isinstance(item, str):
                yield item
            else:
                pending_chars = []
                pending_newline = False

                for char in item:
                    # XXX what about tab characters?
                    if char == '\n':
                        if not pending_newline:
                            pending_newline = True
                        else:
                            # XXX should work out how to do this in a function
                            if pending_chars:
                                yield ''.join(pending_chars)
                                pending_chars.clear()
                            yield blankline
                            pending_newline = False
                    else:
                        if pending_newline:
                            if pending_chars:
                                yield ''.join(pending_chars)
                                pending_chars.clear()
                            yield cr
                            pending_newline = False
                        if char == ' ':
                            if pending_chars:
                                yield ''.join(pending_chars)
                                pending_chars.clear()
                            yield space
                        else:
                            pending_chars.append(char)

                if pending_chars:
                    yield ''.join(pending_chars)
                    pending_chars.clear()
                if pending_newline:
                    yield cr


class Collapser(Splitter):
    def render(self, *, prev: Optional[ItemType] = None, **kwargs) \
            -> RenderResult:
        for item in super().render(prev=prev, **kwargs):
            ignore = False
            if prev is None and item in {blankline, cr}:
                ignore = True
            # XXX this allows (cr, blankline)
            elif prev in {blankline, cr} and item is cr:
                ignore = True
            elif prev is blankline and item in {blankline, cr}:
                ignore = True
            if not ignore:
                yield item

            # update prev even if ignored the item
            prev = item


class Doc(Collapser):
    pass


empty = Doc(frozen=True)


class Nest(Doc):
    def __init__(self, *items: ItemType, indent: int = 2):
        self._indent = indent
        super().__init__(*items)

    def render(self, *, prev: Optional[ItemType] = None, **kwargs) \
            -> RenderResult:
        at_start = prev is None or prev in {cr, blankline}
        for item in super().render(prev=prev, **kwargs):
            if item in {cr, blankline}:
                at_start = True
            elif at_start:
                # XXX should use an 'indent' token?
                yield self._indent * ' '
                at_start = False
            yield item

    @property
    def indent(self) -> int:
        return self._indent


class Hang(Nest):
    def __init__(self, *items: ItemType, indent: int = 2,
                 start: Optional[ItemType] = None):
        self._start = start if isinstance(start, Doc) else Doc(start)
        super().__init__(*items, indent=indent)

    def render(self, *, prev: Optional[ItemType] = None, **kwargs) \
            -> RenderResult:
        for item in self._start.render(prev=prev, **kwargs):
            yield item
            prev = item
        yield from super().render(prev=prev, **kwargs)

    @property
    def start(self) -> Doc:
        return self._start


# XXX column width has to be adjusted for outer nesting levels; how to do this?
class Wrap(Doc):
    def __init__(self, *items: ItemType, colwidth: Optional[int] = None):
        self._colwidth = colwidth
        super().__init__(*items)

    def render(self, **kwargs) -> RenderResult:
        colwidth = self._colwidth
        if colwidth is None:
            yield from super().render(**kwargs)

        else:
            offset = 0
            for item in super().render(**kwargs):
                item_len = len(str(item))
                if item in {blankline, cr}:
                    yield item
                    offset = 0
                elif offset + item_len > colwidth:
                    if item is not space:
                        yield cr
                        yield item
                        offset = item_len
                else:
                    yield item
                    offset += item_len

                # for debugging
                # yield '(%s%d)' % (repr(str(item)), offset)

    @property
    def colwidth(self) -> Optional[int]:
        return self._colwidth
