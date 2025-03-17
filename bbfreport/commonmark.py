"""Experimental (and limited) CommonMark https://spec.commonmark.org parser.

Follows https://spec.commonmark.org/0.30/#appendix-a-parsing-strategy.
"""

from __future__ import annotations

# XXX should always use f'' formatting

import enum
import math
import re

from functools import cache
from typing import Any, Callable, cast, final, overload

from .logging import Logging

logger = Logging.get_logger(__name__)


# XXX it might be better to list them in lexical definition order? or ensure
#     that definition order doesn't matter (better?)
def get_subclasses(cls: type[Node]) -> list[type[Node]]:
    subclasses = cls.__subclasses__()
    for subclass in subclasses[:]:
        for subclass_ in get_subclasses(subclass):
            if subclass_ not in subclasses:
                subclasses.append(subclass_)
    return subclasses


# token type
class Type(enum.Enum):
    UNDEFINED = enum.auto()
    ALPHANUMERIC = enum.auto()
    WHITESPACE = enum.auto()
    PUNCTUATION = enum.auto()
    LITERAL = enum.auto()
    OTHER = enum.auto()

    def __str__(self) -> str:
        return self.name[0].lower()

    __repr__ = __str__


# either a line (str) or a token
class Atom:
    __slots__ = ('_value',)

    def __init__(self, value: str = ''):
        self._value = value

    @property
    def value(self) -> str:
        return self._value

    @value.setter
    def value(self, value: str) -> None:
        self._value = value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __len__(self) -> int:
        return len(self._value)

    # note use of .value, which might have been overridden by a subclass
    def __str__(self) -> str:
        return self.value

    # note use of .value, which might have been overridden by a subclass
    def __repr__(self) -> str:
        return repr(self.value)


class Line(Atom):
    _tabsize = 4

    __slots__ = ('_previous', '_expanded', '_offset')

    def __init__(self, value: str = ''):
        super().__init__(value)
        self._previous = self._expanded = value.expandtabs(self._tabsize)
        self._offset = 0

    def match(self, pattern: re.Pattern[str], *, previous: bool = False,
              rstrip: bool = False) -> re.Match[str] | None:
        value = self._previous if previous else self._expanded[self._offset:]
        if rstrip:
            value = value.rstrip()
        return pattern.match(value)

    def lstrip(self) -> None:
        match = re.match(r'^( +)', self._expanded)
        if match:
            # note use of .offset for its ._previous logic
            self.offset += len(match.group(1))

    # XXX should review the name and whether to make it an instance method
    @classmethod
    def eat(cls, s: str, n: int) -> str:
        """Return a string with the first n characters removed, with TAB
        characters treated as 4-char tabs.

        The return value is similar to s.expandtabs(4)[n:], but only tabs
        that have to be expanded are expanded, and some spaces might need to
        be inserted at the start."""

        # XXX should avoid this special case
        if n == 0:
            return s

        tabsize = cls._tabsize

        i = j = 0
        for c in s:
            i = tabsize * (int(i / tabsize) + 1) if c == '\t' else i + 1
            j = j + 1
            if i >= n:
                break

        r = (i - n) * ' ' + s[j:]
        return r

    # all-whitespace lines are regarded as being empty
    @property
    def is_empty(self) -> bool:
        return len(self._expanded[self._offset:].rstrip()) == 0

    @property
    def offset(self) -> int:
        return self._offset

    @offset.setter
    def offset(self, offset: int) -> None:
        self._previous = self._expanded[self._offset:]
        self._offset = offset

    # XXX should probably use a different property name for this
    @property
    def value(self) -> str:
        return self.eat(self._value, self._offset)

    # XXX should probably use a different property name for this
    @value.setter
    def value(self, value: str) -> None:
        self._previous = self._expanded[self._offset:]
        self._value = value
        self._expanded = value.expandtabs(self._tabsize)
        self._offset = 0


class Token(Atom):
    __slots__ = ('_type',)

    def __init__(self, value: str = ''):
        super().__init__(value)
        self._type = self.ctype(value)

    def reset(self) -> None:
        self.value = ''
        self._type = self.ctype('')

    # XXX rename as add_char() or add_string()?
    def add(self, value: str, typ: Type | None = None) -> None:
        if typ is not None:
            self._type = typ
        elif self._type == Type.UNDEFINED:
            self._type = self.ctype(value)
        self.value += value

    @staticmethod
    def ctype(value: str) -> Type:
        if not value:
            return Type.UNDEFINED
        elif value.isalnum():
            return Type.ALPHANUMERIC
        elif value.isspace():
            return Type.WHITESPACE
        elif value.isascii():
            # XXX this doesn't catch all punctuation
            return Type.PUNCTUATION
        else:
            # XXX so for now, treat everything else as punctuation
            # return Type.OTHER
            return Type.PUNCTUATION

    @property
    def is_literal(self) -> bool:
        return self._type == Type.LITERAL

    @property
    def is_punctuation(self) -> bool:
        return self._type == Type.PUNCTUATION

    @property
    def is_whitespace(self) -> bool:
        return self._type == Type.WHITESPACE

    @property
    def is_escape(self) -> bool:
        return self._type == Type.PUNCTUATION and self.value == '\\'

    @property
    def starts_image(self) -> bool:
        # this works both before and after '!' and '[' have been joined
        return self._type == Type.PUNCTUATION and self.value in {'!', '!['}

    @property
    def starts_link(self) -> bool:
        return self._type == Type.PUNCTUATION and self.value == '['

    @property
    def ends_link(self) -> bool:
        return self._type == Type.PUNCTUATION and self.value == ']'

    @property
    def starts_url(self) -> bool:
        return self._type == Type.PUNCTUATION and self.value == '('

    @property
    def ends_url(self) -> bool:
        return self._type == Type.PUNCTUATION and self.value == ')'

    @property
    def is_backticks(self) -> bool:
        return self._type == Type.PUNCTUATION and self.value[-1:] == '`'

    @property
    def is_heading(self) -> bool:
        return self._type == Type.PUNCTUATION and self.value[-1:] == '#'

    @property
    def is_link_or_image(self) -> bool:
        return self._type == Type.PUNCTUATION and self.value[-1:] == '['

    @property
    def is_quote(self) -> bool:
        return self._type == Type.PUNCTUATION and \
            self.value[-1:] in {"'", '"'}

    @property
    def is_brace(self) -> bool:
        return self._type == Type.PUNCTUATION and \
            self.value[-1:] in {'{', '}'}

    @property
    def type_(self) -> Type:
        return self._type

    # XXX can we assume that literal values are single characters? messy...
    @property
    def raw_value(self) -> str:
        literal = "\\" if self._type == Type.LITERAL else ''
        return f'{literal}{self.value}'

    def __hash__(self) -> int:
        return hash((self.type_, self.value))

    def __eq__(self, other: Any) -> bool:
        assert isinstance(other, Token), "can't compare %s with %s" % \
                (type(self).__name__, type(other).__name__)
        return hash(self) == hash(other)

    def __str__(self) -> str:
        return '%s%r' % (self._type, self.value)

    __repr__ = __str__


class Attr:
    """See https://pandoc.org/lua-filters.html#type-attr. This
    is a pandoc extension."""

    def __init__(self, value: str):
        self._identifier, self._classes, self._attributes = self._parse(value)

    # XXX this should support things like x="y z"; also, is there a precedent
    #     for regarding plain x as being x=True?
    @staticmethod
    def _parse(value: str) -> tuple[str, list[str], dict[str, bool | str]]:
        identifier = ''
        classes = []
        attributes = {}

        # if the value isn't enclosed in braces, it should be a single word and
        # will be interpreted as a class name
        if not re.match(r'^{.*?}$', value):
            words = value.split()
            if words:
                classes.append(words[0])
                if len(words) > 1:
                    logger.warning(f'unexpected multi-word Attr value '
                                   f'{value}')

        # otherwise, it's a list of #identifier, .class and name=value items
        else:
            items = value[1:-1].split()
            for item in items:
                if item.startswith('#'):
                    if identifier:
                        logger.warning(f'duplicate identifier {item} ignored '
                                       f'in Attr value {value}')
                    else:
                        identifier = item[1:]
                elif item.startswith('.'):
                    classes.append(item[1:])
                elif '=' in item:
                    nam, val = item.split('=', 1)
                    if nam in attributes:
                        logger.warning(f'duplicate attribute {item} ignored '
                                       f'in Attr value {value}')
                    else:
                        attributes[nam] = val
                else:
                    if item in attributes:
                        logger.warning(f'duplicate attribute {item} ignored '
                                       f'in Attr value {value}')
                    else:
                        attributes[item] = True

        return identifier, classes, attributes

    @property
    def identifier(self) -> str:
        return self._identifier

    @property
    def classes(self) -> list[str]:
        return self._classes

    @property
    def attributes(self) -> dict[str, bool | str]:
        return self._attributes

    # XXX note that (in non-empty) this has a leading space (is this correct?)
    def __str__(self) -> str:
        comps: list[str] = []
        if self._identifier:
            comps.append(f' id="{self._identifier}"')
        if self._classes:
            classes = ' '.join(self._classes)
            comps.append(f' class="{classes}"')
        if self._attributes:
            for nam, val in self._attributes.items():
                # XXX should quote val if needed
                val = f'="{val}"' if isinstance(val, str) else ''
                comps.append(f' {nam}{val}')
        return ''.join(comps)

    __repr__ = __str__


# XXX need consistent policy on whether to use ._xxx or .xxx in methods
class Node:
    # precedence
    # - to allow a node to be nested within a node of the same precedence,
    #   set its precedence to a fraction, e.g. 3.5
    # XXX should invert the precedence numbers, so 1 is low and 5 is high, or
    #     (better) use enums
    # XXX should work out a way of abstracting precedence as much as possible

    # this default precedence is expected to be overridden via
    # Inline.set_precedence() or Block.set_precedence()
    precedence: float = 0

    @classmethod
    def set_precedence(cls) -> None:
        pass

    # XXX this should be handled via the class hierarchy and should control
    #     whether it has tokens or children
    # XXX need separate concept for Blocks and Inlines?
    is_container = True

    __slots__ = ('_parent', '_children', '_hidden', '_removed', '_children_')

    @classmethod
    def is_new_start(cls, atom: Atom, *, last_matched: Node,
                     last_matched_container: Node | None = None,
                     **kwargs: Any) -> bool:
        return False

    def __init__(self, parent: Node | None):
        self._parent = parent
        self._children: list[Node] = []
        self._hidden = False
        self._removed = False
        if parent is not None:
            parent.add_child(self)

        self._children_ = None
        self._refresh_()

    # this must be called whenever anything that affects cached properties
    # has changed
    def _refresh_(self) -> None:
        self._children_ = [child for child in self._children
                           if child.parent is self and not child.removed]

    def can_remain_open(self, atom: Atom, *, last_matched: Node,
                        last_matched_container: Node, **kwargs: Any) -> bool:
        return True

    def add_child(self, node: Node, *,
                  after: Node | None = None) -> None:
        # this might re-parent it (this is OK)
        node.parent = self

        # determine where to insert the child, and insert it
        index = len(self._children) if after is None else \
            self._children.index(after) + 1
        self._children.insert(index, node)

        self._refresh_()

        # notify interested parties
        self.child_added(node)

    def child_added(self, node: Node) -> None:
        """This is called just after a child has been added to a node."""
        pass

    # XXX this should use other primitives
    def replace(self, old: tuple[Node, ...], new: Node) -> None:
        for node in old:
            node.removed = True
        index = self._children.index(old[0])
        self._children.insert(index, new)

        # use of .parent means that the previous parent is refreshed
        new.parent = self

        # this has to be done last (after the re-parenting)
        self._refresh_()

    def visit(self, func: Callable[..., Any], *, level: int = 0,
              after: bool = False, result: Any = None, **kwargs: Any) -> Any:

        if not after:
            retval = func(self, level=level, result=result, **kwargs)
            if retval is not None:
                result = retval

        for child in self.children:
            # XXX removed nodes aren't in children but might have been removed
            #     during the traversal
            if not child.removed and not child.hidden:
                retval = child.visit(func, level=level+1, result=result,
                                     after=after, **kwargs)
                if retval is not None:
                    result = retval

        if after:
            retval = func(self, level=level, result=result, **kwargs)
            if retval is not None:
                result = retval

        return result

    @property
    def context(self) -> Context | None:
        return cast(Context, self) if isinstance(self, Context) \
                else self.parent.context if self.parent is not None else None

    # XXX should this start with self, or would self.parent be better?
    @property
    def container(self) -> Node | None:
        return self if self.is_container else self.parent.container if \
            self.parent is not None else None

    @property
    def is_empty(self) -> bool:
        raise NotImplemented

    @property
    def open_inlines(self) -> list[Inline]:
        inlines: list[Inline] = []
        if self.is_open and isinstance(self, Inline):
            inlines.append(self)
        if last_child := self.last_child:
            inlines.extend(last_child.open_inlines)
        return inlines

    @property
    def last_open_inline(self) -> Inline | None:
        open_inlines = self.open_inlines
        return open_inlines[-1] if open_inlines else None

    # SPEC: says last child is open, but I think it means the last child of an
    #       open node
    @property
    def is_open(self) -> bool:
        return self.parent.is_open and self is self.parent.last_child \
            if self.parent else True

    @property
    def parent(self) -> Node | None:
        return self._parent

    @parent.setter
    def parent(self, parent: Node | None) -> None:
        if parent is not self._parent:
            previous_parent = self._parent
            self._parent = parent
            if previous_parent is not None:
                previous_parent._refresh_()

    # note that if a child is re-parented then it remains in _children but
    # is not included in children
    # XXX should look into using yield (or another technique) that allows this
    #     to work if entries are added while iterating
    @property
    def children(self) -> list[Node]:
        return self._children_ or []
        # return [child for child in self._children
        #         if child.parent is self and not child.removed]

    @property
    def first_child(self) -> Node | None:
        children = self.children
        return children[0] if children else None

    @property
    def last_child(self) -> Node | None:
        children = self.children
        return children[-1] if children else None

    @property
    def previous_sibling(self) -> Node | None:
        parent = self.parent
        if parent is None:
            return None

        siblings = parent.children
        assert self in siblings

        index = siblings.index(self)
        return siblings[index - 1] if index > 0 else None

    @property
    def next_sibling(self) -> Node | None:
        parent = self.parent
        if parent is None:
            return None

        siblings = parent.children
        assert self in siblings

        index = siblings.index(self)
        return siblings[index + 1] if index < len(siblings) - 1 else None

    @property
    def hidden(self) -> bool:
        return self._hidden

    @hidden.setter
    def hidden(self, value: bool) -> None:
        self._hidden = value

    @property
    def removed(self) -> bool:
        return self._removed

    @removed.setter
    def removed(self, value: bool) -> None:
        self._removed = value
        if self._parent is not None:
            self._parent._refresh_()

    @property
    def text(self) -> str:
        raise NotImplemented

    @property
    def raw_text(self) -> str:
        raise NotImplemented

    @classmethod
    @cache
    def class_name(cls) -> str:
        # XXX will replace lower -> upper transitions with '_'
        return re.sub(r'(?<=[a-z])(?=[A-Z])', '_', cls.__name__).lower()

    def __str__(self) -> str:
        left, right = ('[', ']') if self._removed else ('', '')
        # XXX is_open isn't very useful?
        is_open = ''  # ' (*)' if self.is_open else ''
        return f'{left}{type(self).class_name()}{right}{is_open}'

    __repr__ = __str__


# XXX this holds cross-document context, e.g., link references
class Context(Node):
    def __init__(self) -> None:
        super().__init__(None)
        self._references = {}

    # XXX these are accessed directly; should access them via a Context method
    @property
    def references(self) -> dict[str, 'LinkReference']:
        return self._references


# XXX need to integrate this better into the class hierarchy; will need
#     a _HasChildren base class
class _HasInlineChildren:
    """See https://spec.commonmark.org/0.30/#phase-2-inline-structure. This
    more-or-less implements its process_emphasis() function."""

    __slots__ = ()

    def process_emphasis(self) -> None:
        delimiter_stack = [child for child in
                           cast(Node, cast(object, self)).children if
                           isinstance(child, DelimiterRun)]
        current_position = 0

        def get_closer() -> DelimiterRun | None:
            nonlocal current_position
            while current_position < len(delimiter_stack):
                closer_ = delimiter_stack[current_position]
                if not closer_.removed and not closer_.marked and \
                        closer_.can_close_emphasis:
                    logger.debug(f'  closer {current_position} {closer_} '
                                 f'{delimiter_stack}')
                    return closer_
                current_position += 1
            return None

        def get_opener() -> DelimiterRun | None:
            opener_range = range(current_position - 1, -1, -1)
            for opener_position in opener_range:
                opener_ = delimiter_stack[opener_position]
                closer_ = cast(DelimiterRun, closer)
                if not opener_.removed and not opener_.marked and \
                        opener_.can_open_emphasis and opener_.matches(closer_):
                    logger.debug(f'  opener {opener_position} {opener_} '
                                 f'{delimiter_stack}')
                    return opener_
            return None

        logger.debug(f'process_emphasis {self}')
        while closer := get_closer():
            if opener := get_opener():
                opener.create(closer)

                if closer.removed:
                    current_position += 1

            else:
                # XXX this can cause initial openers to be ignored...
                # openers_bottom[closer.delim] = current_position - 1

                if not closer.can_open_emphasis:
                    delimiter_stack.remove(closer)

                else:
                    current_position += 1


# XXX it might be useful to have Inlines and Blocks types
class Inline(Node, _HasInlineChildren):
    __slots__ = ('_tokens',)

    # this must be called after the last Inline has been defined
    @classmethod
    @final
    def set_precedence(cls) -> None:
        """The following requirements are guaranteed by the parsing strategy:

        * Backtick code spans, auto-links, and raw HTML tags bind more
          tightly than the brackets in link text.

        * The brackets in link text bind more tightly than markers for
          emphasis and strong emphasis.

        * Inline code spans, links, images, and HTML tags group more tightly
          than emphasis.

        Other requirements are handled via precedence."""

        # - Code span backticks have higher precedence than any other inline
        #   constructs except HTML tags and auto-links
        # - Code spans, HTML tags, and auto-links have the same precedence
        CodeSpan.precedence = 1
        Angled.precedence = 1

        DelimiterRun.precedence = 2

        # default precedence
        Inline.precedence = 3

        # so they can be nested, e.g., to support "[[a](b)]"
        Braced.precedence = 3.5
        Bracketed.precedence = 3.5
        Parenthesized.precedence = 3.5
        MacroRef.precedence = 3.5

        Text.precedence = 5

    def __init__(self, parent: Node | None,
                 token: Token | None = None, **kwargs: Any):
        super().__init__(parent)
        self._tokens: list[Token] = []
        if token is not None:
            self.add_token(token)

    def add_token(self, token: Token) -> None:
        # XXX currently only ever added to Text, and only ever a single one
        # XXX no longer...
        # assert isinstance(self, Text) and len(self._tokens) == 0
        assert len(self._tokens) == 0
        self._tokens.append(token)
        if isinstance(self.parent, Inline):
            self.parent.token_added(token)

    def token_added(self, token: Token) -> None:
        """This is called just after a token has been added to a child."""
        pass

    @property
    def is_open(self) -> bool:
        # some nodes, e.g. Link nodes, have no parents when created, because
        # they are positioned manually; assume that such nodes aren't open
        if self.parent is None:
            return False
        # XXX this is messy; from the point of the view of Inlines, all their
        #     parent Blocks are still open
        elif not isinstance(self.parent, Inline):
            return True
        else:
            return self.parent.is_open and self is self.parent.last_child

    @property
    @overload
    def children(self) -> list[Inline]:  # pyright: ignore[reportRedeclaration]
        pass

    @property
    def children(self) -> list[Any]:
        return super().children

    @property
    def is_empty(self) -> bool:
        return len(self._tokens) == 0

    @property
    def tokens(self) -> list[Token]:
        return self._tokens

    # XXX this first/last token stuff is messy; we should be clearer when
    #     inlines can and can't have more than one token
    @property
    def first_token(self) -> Token | None:
        if self._tokens:
            return self._tokens[0]
        elif first_child := cast(Inline, self.first_child):
            return first_child.first_token
        else:
            return None

    @property
    def last_token(self) -> Token | None:
        if self._tokens:
            return self._tokens[-1]
        elif last_child := cast(Inline, self.last_child):
            return last_child.last_token
        else:
            return None

    @property
    def text(self) -> str:
        if self.tokens:
            return ''.join(token.value for token in self.tokens)
        else:
            return ''.join(child.text for child in self.children)

    @property
    def raw_text(self) -> str:
        if self.tokens:
            return ''.join(token.raw_value for token in self.tokens)
        else:
            return ''.join(child.raw_text for child in self.children)

    def __str__(self) -> str:
        text = str(self.first_token) if len(self.tokens) == 1 \
            else repr(self.text)
        return f'{super().__str__()} {text}'

    __repr__ = __str__


# XXX maybe should support tuple left/right, e.g. ("'", '"') ... complicated
class _Delimited(Inline):
    """A left delimiter, followed by zero or more characters, terminated by
    the first occurrence of a right delimiter. The delimiters can contain
    multiple characters, and they can both be the same."""

    # subclasses must set these to matching left and right delimiters, or both
    # to the same character
    left = ''
    right = ''

    @classmethod
    def is_new_start(cls, atom: Atom, *, last_matched: Node | None = None,
                     last_matched_container: Node | None = None,
                     **kwargs: Any) -> bool:
        token = cast(Token, atom)
        # if the left and right delimiters are the same, they can't be nested
        is_same_class = \
            isinstance(last_matched, cls) if cls.left == cls.right else False
        is_new_start = (not is_same_class and token.is_punctuation and
                        token.value == cls.left)
        return is_new_start

    @property
    def is_closed(self) -> bool:
        first_token, last_token = self.first_token, self.last_token
        is_closed = (last_token and last_token is not first_token and
                     last_token.is_punctuation and
                     last_token.value == self.right)
        return bool(is_closed)

    def can_remain_open(self, atom: Atom, **kwargs: Any) -> bool:
        return not self.is_closed

    # XXX should maintain several slices, e.g., aslice (all), dslice
    #     (sans delimiters), cslice (used for text and raw_text; aslice or
    #     dslice, depending on _DiscardDelimited)
    @property
    def cslice(self) -> slice:
        return slice(None, None)

    @property
    def text(self) -> str:
        start, stop = self.cslice.start, self.cslice.stop
        return ''.join(child.text for child in self.children[start:stop])


class _BalanceDelimited(_Delimited):
    """Variant that allows balanced delimiters to occur within the body.
    This obviously doesn't make sense when the delimiters are equal."""

    def __init__(self, parent: Node | None, token: Token | None = None,
                 **kwargs: Any):
        super().__init__(parent, token, **kwargs)
        self._level = 0

    def token_added(self, token: Token) -> None:
        if token.is_punctuation:
            if token.value == self.left:
                self._level += 1
            elif token.value == self.right:
                self._level -= 1
        # the level has been adjusted first so that .is_closed will be correct
        super().token_added(token)

    @property
    def is_closed(self) -> bool:
        return False if self._level > 0 else super().is_closed

    @property
    def level(self) -> int:
        return self._level

    def __str__(self) -> str:
        return f'{super().__str__()} ({self.level})'


# XXX it's not very obvious when or how to use this; the rough idea is that it
#     should show the text as it'll be shown in the final document
class _DiscardDelimited(_Delimited):
    """Variant in which the left and right (if present) delimiters aren't
    included in the text value."""

    # XXX this is probably OK, but is not very nice
    # XXX I fear that I am abusing slices
    def token_added(self, token: Token) -> None:
        super().token_added(token)
        start, stop = self.cslice.start, self.cslice.stop
        if start is not None:
            self.children[start-1].hidden = True
        if stop is not None:
            self.children[stop].hidden = True

    @property
    def cslice(self) -> slice:
        return slice(1, -1 if self.is_closed else None)


class _LiteralDelimited(_Delimited):
    """See https://spec.commonmark.org/0.30/#backslash-escapes. Backslash
    escapes do not work in code blocks, code spans, auto-links, or raw HTML."""

    @property
    def text(self) -> str:
        start, stop = self.cslice.start, self.cslice.stop
        return ''.join(child.raw_text for child in self.children[start:stop])


class CodeSpan(_DiscardDelimited, _LiteralDelimited):
    """See https://spec.commonmark.org/0.30/#code-spans."""
    left = right = '`'

    @property
    def text(self) -> str:
        text = super().text.replace('\n', ' ')
        if (text[:1] == ' ' and text[-1:] == ' ' and not text.isspace() and
                len(text) > 2):
            text = text[1:-1]
        return text


class Angled(_LiteralDelimited):
    """See https://spec.commonmark.org/0.30/#autolinks and
    https://spec.commonmark.org/0.30/#raw-html. They're both the same at
    this level."""
    left = '<'
    right = '>'


# XXX should remove _BalanceDelimited (although it does no harm)
class Bracketed(_BalanceDelimited, _LiteralDelimited):
    """See https://spec.commonmark.org/0.30/#link-destination."""
    left = '['
    right = ']'


class ShriekBracketed(_BalanceDelimited, _LiteralDelimited):
    """See https://spec.commonmark.org/0.30/#link-destination."""
    left = '!['
    right = ']'


class Parenthesized(_BalanceDelimited, _LiteralDelimited):
    """See https://spec.commonmark.org/0.30/#link-destination."""
    left = '('
    right = ')'


class Braced(_BalanceDelimited, _LiteralDelimited):
    left = '{'
    right = '}'


# ideally, we might use a single Quoted class for both quote types, and would
# set left = right = ('"', "'"),  but it doesn't really matter
class DoubleQuoted(_DiscardDelimited):
    left = right = '"'


# XXX this is disabled because "'" characters are currently processed as
#     delimiter runs; could post-process to convert suitable unused
#     delimiter runs to SingleQuoted instances
class _SingleQuoted(_DiscardDelimited):
    left = right = "'"


class Superscript(_DiscardDelimited):
    """See https://pandoc.org/MANUAL.html#extension-superscript-subscript. This
    is a pandoc extension."""

    left = right = '^'


class Subscript(_DiscardDelimited):
    """See https://pandoc.org/MANUAL.html#extension-superscript-subscript. This
    is a pandoc extension."""

    left = right = '~'


# XXX experimental and non-standard; probably a bad idea
# XXX needs to support arg separators; would be better to use a custom class?
class MacroRef(_BalanceDelimited):
    left = '{{'
    right = '}}'


class DelimiterRun(Inline):
    """See https://spec.commonmark.org/0.30/#emphasis-and-strong-emphasis and
    https://spec.commonmark.org/0.30/#delimiter-run. This models a "delimiter
    run"."""

    # values are #chars for emph, #chars for strong, and whether to impose
    # additional constraints (such as requiring surrounding whitespace)
    # XXX "'" is supported so we can also use mediawiki-style emphasis
    _config = {
        '*': (1, 2, False),
        '_': (1, 2, True),
        "'": (2, 3, False)
    }

    __slots__ = ('_marked',)

    @classmethod
    def is_new_start(cls, atom: Atom, **kwargs: Any) -> bool:
        token = cast(Token, atom)
        return cls.is_delim(token)

    def __init__(self, parent: Node | None,
                 token: Token | None = None, **kwargs: Any):
        super().__init__(parent, token, **kwargs)
        self._marked = False

    def can_remain_open(self, atom: Atom, **kwargs: Any) -> bool:
        token = cast(Token, atom)
        is_same_delim = self.is_delim(token) and token.value == self.delim
        return is_same_delim

    @classmethod
    def is_delim(cls, token: Token) -> bool:
        return token.is_punctuation and token.value in cls._config

    def matches(self, closer: 'DelimiterRun') -> bool:
        """Whether the opener (this object) matches the closer.

        The closer must use the same character (_ or *) as the opener.

        The opener and closer must belong to separate delimiter runs (this
        is guaranteed by the tokenization process, but it's still checked).

        If one of the delimiters can both open and close emphasis, then the
        sum of the lengths of the delimiter runs containing the opening and
        closing delimiters must not be a multiple of 3 unless both lengths are
        multiples of 3."""

        if self.delim != closer.delim:
            return False
        elif self is closer:
            return False
        elif (self.can_open_emphasis and self.can_close_emphasis) or (
              closer.can_open_emphasis and closer.can_close_emphasis):
            esl = self.emph_length + self.strong_length
            if (self.length + closer.length) % esl == 0 and not (
                    self.length % esl == 0 and closer.length % esl == 0):
                return False
        return True

    # XXX this is a bad name; it doesn't describe what it really does
    def create(self, closer: 'DelimiterRun') -> None:
        """Create an `Emph` or `Strong` node as a sibling of the opener
        (this object) and move all the siblings between the opener and the
        closer to the newly-created node."""

        # determine which of Emph and Strong to create
        el, sl = self.emph_length, self.strong_length
        emph = Strong if self.length >= sl and closer.length >= sl else Emph

        # the new node is initially orphaned because we need to control
        # its location
        node = emph(None)

        # collect the siblings between the opener (this object) and the closer
        siblings: list[Node] = []
        sibling = self
        while True:
            sibling = sibling.next_sibling
            if sibling is None or sibling is closer:
                break
            siblings.append(sibling)

        # move them to the new node (add_child() will re-parent them)
        for sibling in siblings:
            node.add_child(sibling)

        # mark any delimiters between the opener and closer (they'll be
        # ignored)
        for sibling in siblings:
            if isinstance(sibling, DelimiterRun):
                sibling.marked = True

        # insert the new node after the opener (this object); this sets its
        # parent
        if self.parent:
            self.parent.add_child(node, after=self)

        # remove the relevant number (1 or 2) of delimiters from both the
        # opener and the closer
        for node in (self, closer):
            for _ in range(sl if emph is Strong else el):
                # XXX this is tricky; children() is re-evaluated each time and
                #     so gets shorter and shorter; alternatively could do this
                #     in reverse order or (better) use a copy?
                # XXX something's gone wrong if this check is needed
                if node.children:
                    node.children[0].removed = True

                # if now empty, remove the opener / closer
                if len(node.children) == 0:
                    node.removed = True

    @property
    def delim(self) -> str:
        assert self.first_token is not None
        return self.first_token.value[0]

    @property
    def emph_length(self) -> int:
        return self._config[self.delim][0]

    @property
    def strong_length(self) -> int:
        return self._config[self.delim][1]

    @property
    def is_constrained(self) -> bool:
        return self._config[self.delim][2]

    @property
    def length(self) -> int:
        return len(self.children)

    @property
    def is_left_flanking(self) -> bool:
        """See https://spec.commonmark.org/0.30/#left-flanking-delimiter-run.

        A left-flanking delimiter run is a delimiter run that is:

        (1) not followed by Unicode whitespace, and either

        (2a) not followed by a Unicode punctuation character, or
        (2b) followed by a Unicode punctuation character and preceded by
        Unicode whitespace or a Unicode punctuation character.

        For purposes of this definition, the beginning and the end of the
        line count as Unicode whitespace."""

        previous_token = self.previous_token
        next_token = self.next_token
        return (not next_token.is_whitespace) and (
                    not next_token.is_punctuation or (
                        next_token.is_punctuation and (
                            previous_token.is_whitespace or
                            previous_token.is_punctuation)))

    @property
    def is_right_flanking(self) -> bool:
        """See https://spec.commonmark.org/0.30/#right-flanking-delimiter-run.

        A right-flanking delimiter run is a delimiter run that is

        (1) not preceded by Unicode whitespace, and either

        (2a) not preceded by a Unicode punctuation character, or

        (2b) preceded by a Unicode punctuation character and followed by
        Unicode whitespace or a Unicode punctuation character.

        For purposes of this definition, the beginning and the end of the
        line count as Unicode whitespace."""

        previous_token = self.previous_token
        next_token = self.next_token
        return (not previous_token.is_whitespace) and (
                    not previous_token.is_punctuation or (
                        previous_token.is_punctuation and (
                            next_token.is_whitespace or
                            next_token.is_punctuation)))

    @property
    def can_open_emphasis(self) -> bool:
        """See https://spec.commonmark.org/0.30/#can-open-emphasis (the term
        "potential opener" is also used).

        A single (double) * character can open (strong) emphasis iff it is
        part of a left-flanking delimiter run.

        A single (double) _ character can open (strong) emphasis iff it is
        part of a left-flanking delimiter run and either

        (a) not part of a right-flanking delimiter run or

        (b) part of a right-flanking delimiter run preceded by a Unicode
        punctuation character."""

        if self.length < min(self.emph_length, self.strong_length):
            return False
        elif not self.is_constrained:
            return self.is_left_flanking
        else:
            return self.is_left_flanking and (
                    not self.is_right_flanking or
                    self.previous_token.is_punctuation)

    @property
    def can_close_emphasis(self) -> bool:
        """See https://spec.commonmark.org/0.30/#can-close-emphasis (the
        term "potential closer" is also used).

        A single (double) * character can close (strong) emphasis iff it is
        part of a right-flanking delimiter run.

        A single (double) _ character can close (strong) emphasis iff it is
        part of a right-flanking delimiter run and either

        (a) not part of a left-flanking delimiter run or

        (b) part of a left-flanking delimiter run followed by a Unicode
        punctuation character."""

        if self.length < min(self.emph_length, self.strong_length):
            return False
        elif not self.is_constrained:
            return self.is_right_flanking
        else:
            return self.is_right_flanking and (
                not self.is_left_flanking or
                self.next_token.is_punctuation)

    @property
    def previous_token(self) -> Token:
        previous_sibling = self.previous_sibling
        return previous_sibling.first_token if \
            previous_sibling and previous_sibling.first_token else Token(' ')

    @property
    def next_token(self) -> Token:
        next_sibling = self.next_sibling
        return next_sibling.first_token if \
            next_sibling and next_sibling.first_token else Token(' ')

    @property
    def marked(self) -> bool:
        return self._marked

    @marked.setter
    def marked(self, marked: bool) -> None:
        self._marked = marked

    def __str__(self) -> str:
        left, right = ('{', '}') if self._marked else ('', '')
        return f'{left}{super().__str__()} ({self.length}){right}'

    __repr__ = __str__


class SoftBreak(Inline):
    @classmethod
    def is_new_start(cls, atom: Atom, *, last_matched: Node,
                     last_matched_container: Node | None = None,
                     **kwargs: Any) -> bool:
        token = cast(Token, atom)
        return token.is_whitespace and token.value == '\n'

    def can_remain_open(self, atom: Atom, *, last_matched: Node,
                        last_matched_container: Node, **kwargs: Any) -> bool:
        return False

    def child_added(self, node: Node) -> None:
        self.last_child.hidden = True


class HardBreak(Inline):
    @classmethod
    def is_new_start(cls, atom: Atom, *, last_matched: Node,
                     last_matched_container: Node | None = None,
                     **kwargs: Any) -> bool:
        token = cast(Token, atom)
        return (token.is_literal and token.value == '\n') or \
            (token.is_whitespace and re.match(r'^ {2,}\n$', token.value))

    def can_remain_open(self, atom: Atom, *, last_matched: Node,
                        last_matched_container: Node, **kwargs: Any) -> bool:
        return False

    def child_added(self, node: Node) -> None:
        self.last_child.hidden = True


# XXX as currently written, each Text node contains only a single token (I
#     had trouble combining them); maybe should review this and/or combine
#     the tokens in a later phase
class Text(Inline):
    is_container = False

    @classmethod
    def is_new_start(cls, atom: Atom, *, last_matched: Node | None = None,
                     last_matched_container: Node | None = None,
                     **kwargs: Any) -> bool:
        return True

    def can_remain_open(self, atom: Atom, **kwargs: Any) -> bool:
        return False


class _ManualInline(Inline):
    """Inline that's never created while parsing, only manually."""


class Link(_ManualInline):
    """See <https://spec.commonmark.org/0.30/#links>. A link contains LINK
    TEXT (the visible text), a LINK DESTINATION (the URI that is the link
    destination), and optionally a LINK TITLE.

    A LINK TEXT consists of a sequence of zero or more inline elements
    enclosed by square brackets. Various additional rules apply.

    A LINK LABEL begins with a left square bracket and ends with the first
    right square bracket that is not backslash-escaped. Various additional
    rules apply. LINK LABELS are parsed as inlines to form LINK TEXTS.

    * An INLINE LINK is LINK TEXT followed immediately by a left parenthesis,
      an optional LINK DESTINATION, an optional LINK TITLE, and a right
      parenthesis. These four components may be separated by spaces, tabs,
      and up to one line ending. If both LINK DESTINATION and LINK TITLE are
      present, they must be separated by spaces, tabs, and up to one line
      ending

    * There are three kinds of REFERENCE LINKS: FULL, COLLAPSED, and SHORTCUT:

      * A FULL REFERENCE LINK consists of a LINK TEXT immediately followed by
        a LINK LABEL that matches a LINK REFERENCE DEFINITION elsewhere in
        the document

      * A COLLAPSED REFERENCE LINK consists of a LINK LABEL that matches a
        LINK REFERENCE DEFINITION elsewhere in the document, followed by the
        string "[]"

      * A SHORTCUT REFERENCE LINK consists of a LINK LABEL that matches a
        LINK REFERENCE DEFINITION elsewhere in the document and is not
        followed by "[]" or a LINK LABEL
    """

    __slots__ = ('_dest', '_title')

    @classmethod
    def is_valid(cls, inline: Inline) -> \
            tuple[Bracketed | None,
                  Parenthesized | Bracketed | None,
                  str | None,
                  str | None]:
        context = inline.context

        # all links start with a Bracketed instance, which is the link text
        if not isinstance(inline, Bracketed):
            return None, None, None, None

        # there are no particular rules for the link text content
        link_text = inline

        # for it to be a valid link, the link text is immediately followed
        # by one of the nodes described below
        next_sibling = link_text.next_sibling

        # a Parenthesized instance that defines a valid link destination
        # (and optionally a link title)
        if isinstance(next_sibling, Parenthesized):
            # XXX yet another case where we need intelligent slices
            inlines = next_sibling.children[1:-1]
            link_dest, link_title, _ = \
                LinkReference.parse_link_dest_and_title(inlines)
            # XXX could/should check that all the inlines have been consumed,
            #     although trailing whitespace is OK
            if link_dest:
                return link_text, next_sibling, link_dest, link_title

        # another Bracketed instance, a link label that references a valid
        # link destination (and optionally a link title)
        elif isinstance(next_sibling, Bracketed):
            link_ref = LinkReference.get(context, next_sibling.raw_text)
            if link_ref:
                return link_text, next_sibling, link_ref.dest, link_ref.title

        # something else (or nothing), in which case the link text is
        # interpreted as a link label that references a valid link
        # destination (and optionally a link title)
        else:
            link_ref = LinkReference.get(context, link_text.raw_text)
            if link_ref:
                return link_text, None, link_ref.dest, link_ref.title

        # fall through; not a link
        return None, None, None, None

    def __init__(self, link_text: Bracketed):
        super().__init__(None, None)

        # is_valid() should already have been called, and have succeeded
        # XXX this is a nasty interface!
        link_text_node, link_dest_node, link_dest, link_title = \
            self.is_valid(link_text)
        assert link_text_node is link_text
        assert link_dest_node is None or \
               isinstance(link_dest_node, (Bracketed, Parenthesized))

        # add the link text as children (sans brackets)
        # XXX should use dslice (once it's been added)
        # start, stop = link_text.cslice.start, link_text.cslice.stop
        for child in link_text.children[1:-1]:
            self.add_child(child)

        self._dest = link_dest
        self._title = link_title

    @property
    def dest(self) -> str:
        return self._dest or ''

    @property
    def title(self) -> str:
        return self._title or ''

    def __str__(self) -> str:
        return f'{super().__str__()} dest {self._dest!r} title {self._title!r}'


class BracketedSpan(_ManualInline):
    """See https://pandoc.org/MANUAL.html#extension-bracketed_spans. This
    is a pandoc extension."""

    @classmethod
    def is_valid(cls, inline: Inline) -> tuple[
            Bracketed | None, Braced | None]:
        bracketed = inline
        braced = inline.next_sibling
        if isinstance(bracketed, Bracketed) and isinstance(braced, Braced):
            return bracketed, braced
        else:
            return None, None

    def __init__(self, span_text: Bracketed):
        super().__init__(None, None)

        # is_valid() should already have been called, and have succeeded
        span_text_node, span_attr = self.is_valid(span_text)
        assert span_text_node is span_text and span_attr

        # add the span text as children (sans brackets)
        # XXX should use dslice (once it's been added)
        for child in span_text.children[1:-1]:
            self.add_child(child)

        # XXX should parse them
        self._attr = Attr(span_attr.text)

    @property
    def attr(self) -> Attr:
        return self._attr

    def __str__(self) -> str:
        return f'{super().__str__()}{self._attr}'


class Emph(_ManualInline):
    pass


class Strong(_ManualInline):
    pass


# XXX should the entity name be checked?
class Entity(_ManualInline):
    def __init__(self, name: str):
        super().__init__(None, None)
        self._name = name

    @property
    def name(self) -> str:
        return self._name


# this must be after the last Inline definition
Inline.set_precedence()


class Block(Node):
    __slots__ = ('_lines',)

    # this must be called after the last Inline has been defined
    # XXX need to explain why they must be higher than all Inline precedences
    # XXX all Block types can nest; don't need fractional precedences
    @classmethod
    @final
    def set_precedence(cls) -> None:
        """TBD."""

        FencedDiv.precedence = 10

        # - If a line of dashes that meets the above conditions for being a
        #   thematic break could also be interpreted as the underline of a
        #   setext heading, the interpretation as a setext heading takes
        #   precedence
        # - If a line containing a single '-' can be interpreted as an empty
        #   list item, it should be interpreted this way and not as a setext
        #   heading underline (THIS IS HANDLED BY SPECIAL CODE)
        SetextHeading.precedence = 11

        # - When both a thematic break and a list item are possible
        #   interpretations of a line, the thematic break takes precedence
        ThematicBreak.precedence = 12

        # - If there is any ambiguity between an interpretation of indentation
        #   as a code block and as indicating that material belongs to a list
        #   item, the list item interpretation takes precedence
        ItemList.precedence = ListItem.precedence = 13

        # IndentedCodeBlock.precedence = FencedCodeBlock.precedence = 14

        # AtxHeading.precedence = 15

        # default precedence
        Block.precedence = 15

        # XXX I don't think this matters
        # Paragraph.precedence = 23

        # XXX I don't think this matters
        # Document.precedence = 25

    def __init__(self, parent: Node | None, **kwargs: Any):
        super().__init__(parent)
        self._lines = []

    def add_line(self, line: Line) -> None:
        self._lines.append(line)

    @overload
    @property
    def children(self: 'Block') -> list['Block']:
        pass

    @overload
    @property
    def children(self: 'Paragraph') -> list[Inline]:
        pass

    @property
    def children(self) -> list[Any]:
        return super().children

    # XXX if parent's specified, all inlines will be flattened under it; I
    #     think this is OK for the link definition use case
    # XXX should use Node.visit()
    def parse_inlines(self, *, parent: Block | None = None) -> None:
        if self.text:
            self._parse_text(parent=parent)
        for child in self.children:
            if isinstance(child, Block):
                child.parse_inlines(parent=parent)

    def _parse_text(self, *, parent: Block | None = None) -> None:
        if parent is None:
            parent = self

        text = self.text

        # split into tokens
        # XXX should move this to a method
        tokens: list[Token] = []
        token = Token()

        def new(c: str) -> bool:
            if not token:
                return True

            t = Token(c)
            if t.type_ != token.type_:
                return True
            elif token.type_ not in {Type.ALPHANUMERIC, Type.WHITESPACE}:
                return True
            else:
                return False

        def add(c: str) -> None:
            token.add(c)

        def close() -> None:
            nonlocal token
            if token:
                tokens.append(token)
                token = Token()

        for char in text.rstrip():
            if new(char):
                close()
            add(char)
        close()

        # re-process so runs of # and `, and ![ are single tokens
        # XXX should move this to a method
        new_tokens: list[Token] = []
        new_token = Token()

        def new_add(c: Token, t: Type | None = None) -> None:
            new_token.add(c.value, t)

        def new_close() -> None:
            nonlocal new_token
            if new_token:
                new_tokens.append(new_token)
                new_token = Token()

        for token in tokens:
            if new_token.is_escape and \
                    (token.is_punctuation or token.is_whitespace):
                new_token.reset()
                new_add(token, Type.LITERAL)
            elif token.is_heading or token.is_backticks:
                if new_token.type_ != token.type_ or \
                        new_token.value[-1:] != token.value:
                    new_close()
                new_add(token)
            elif token.is_brace:
                if new_token.type_ != token.type_ or len(new_token.value) > 1 \
                        or new_token.value[-1:] != token.value:
                    new_close()
                new_add(token)
            elif new_token.starts_image and token.starts_link:
                new_add(token)
                new_close()
            else:
                new_close()
                new_add(token)
        new_close()

        # delete trailing escape; there's nothing for it to escape
        # XXX is this correct? it gives correct behavior for this doc: "a\"
        if new_tokens and new_tokens[-1].is_escape:
            del new_tokens[-1]

        tokens = new_tokens
        del new_token, new_tokens
        logger.debug(f'btext {text!r} -> tokens {tokens}')

        inline_types = sorted([typ for typ in get_subclasses(Inline)
                               if typ is not type(self)
                               and not issubclass(typ, _ManualInline)
                               and not typ.__name__.startswith('_')],
                              key=lambda c: (c.precedence, c.__name__))

        for num, token in enumerate(tokens):
            logger.debug(f'- {num:02d} {token!r}')

            last_matched = parent
            # XXX should this be parent.container? no...
            last_matched_container = parent
            for inline in parent.open_inlines:
                can_remain_open = inline.can_remain_open(
                        token, last_matched=last_matched,
                        last_matched_container=last_matched_container)
                if can_remain_open:
                    if True or not isinstance(inline, Text):
                        logger.debug('- - can remain open %s' % inline)
                    last_matched = inline
                    if inline.is_container:
                        last_matched_container = inline

            inline_types_pruned = [typ for typ in inline_types if (
                    typ.precedence < math.ceil(last_matched.precedence))]
            if Text not in inline_types_pruned:
                inline_types_pruned.append(Text)

            for inline_type in inline_types_pruned:
                is_new_start = inline_type.is_new_start(
                        token, last_matched=last_matched,
                        last_matched_container=last_matched_container)
                if not is_new_start:
                    logger.debug("- - can't be new %s %r" % (
                        inline_type.class_name(), token))
                else:
                    logger.debug('- - is new %s %r' % (
                        inline_type.class_name(), token))
                    last_matched = inline_type(last_matched_container)
                    if last_matched.is_container:
                        last_matched_container = last_matched

            # XXX the new logic will always add the token to the Text node
            # last_matched.add_token(token)
            parent.last_open_inline.add_token(token)
            logger.debug(f'- - -> %s' % last_matched)

    # XXX should this consider children?
    @property
    def is_empty(self) -> bool:
        return len(self.text.strip()) == 0

    @property
    def open_blocks(self) -> list['Block']:
        blocks = []
        if self.is_open:
            blocks.append(self)
        if last_child := self.last_child:
            blocks.extend(last_child.open_blocks)
        return blocks

    @property
    def last_open_block(self) -> Block | None:
        open_blocks = self.open_blocks
        return open_blocks[-1] if open_blocks else None

    # XXX whitespace logic needs to be conditional
    @property
    def text(self) -> str:
        text = ''.join(line.value for line in self._lines)
        if True:  # isinstance(self, Paragraph):
            text = re.sub(r'\n[ \t]+', '\n', text)
            text = text.rstrip()
        return text

    @property
    def raw_text(self) -> str:
        return self.text

    @property
    def lines(self) -> list[Line]:
        return self._lines

    @lines.setter
    def lines(self, value: list[Line]) -> None:
        pass

    # XXX this should give a better overview of the current block content
    def __str__(self) -> str:
        return f'{super().__str__()} {self.text!r}'


# XXX need also to handle Inline attributes; see the spec
# XXX no; should allow it to be parsed as inlines (Braced)
# XXX the pattern is too permissive
class Attributes(Block):
    """See https://pandoc.org/MANUAL.html#extension-attributes. This is a
    pandoc extension."""

    is_container = False

    _line_pattern = re.compile(r'''
        ^
        (?P<attr>{[^}]+})
        $
    ''', flags=re.VERBOSE)

    @classmethod
    def is_new_start(cls, atom: Atom, *, last_matched: Node,
                     last_matched_container: Node | None = None,
                     **kwargs: Any) -> bool:
        line = cast(Line, atom)
        match = line.match(cls._line_pattern)
        if match:
            line.value = ''
        return bool(match)

    def __init__(self, parent: Node | None, *, line: Line):
        super().__init__(parent)

        # this will match, because is_new_start() must have returned True
        match = line.match(self._line_pattern, previous=True)
        assert match is not None
        self._attr = Attr(match['attr'])

        # Attributes nodes generate no output
        self.hidden = True

    def can_remain_open(self, line: Line, **kwargs: Any) -> bool:
        return False

    @property
    def attr(self) -> Attr:
        return self._attr

    def __str__(self) -> str:
        return f'{super().__str__()}{self._attr}'


class ThematicBreak(Block):
    """See https://spec.commonmark.org/0.30/#thematic-breaks."""

    is_container = False

    _line_pattern = re.compile(r'''
        ^
        \ {0,3}
        (?P<dash>[-_*])
        \ *
        (?:
            (?P=dash)
            \ *
        ){2,}
        $
    ''', flags=re.VERBOSE)

    @classmethod
    def is_new_start(cls, atom: Atom, *, last_matched: Node,
                     last_matched_container: Node | None = None,
                     **kwargs: Any) -> bool:
        line = cast(Line, atom)
        match = line.match(cls._line_pattern)
        if match:
            line.value = ''
        return bool(match)

    def can_remain_open(self, atom: Atom, **kwargs: Any) -> bool:
        return False


class _Heading:
    """Heading utilities (not a node)."""

    @staticmethod
    def slugify(title: str) -> str:
        """See https://pandoc.org/MANUAL.html#extension-header_attributes. This
        is a pandoc extension."""

        # this is stolen from mdit_py_plugins.anchors.anchors_plugin.index
        return re.sub(r'[^\w\u4e00-\u9fff\- ]', '',
                      title.strip().lower().replace(' ', '-'))


class AtxHeading(Block, _HasInlineChildren):
    """See https://spec.commonmark.org/0.30/#atx-headings."""

    is_container = False

    __slots__ = ('_level', '_identifier')

    _line_pattern = re.compile(r'''
        ^
        (?P<before>\ {0,3})
        (?P<opening>\#{1,6})
        (?:
            (?P<after1>\ +)
            (?P<content>.+?)
        )??
        (?:
            (?P<after2>\ +)
            (?P<closing>\#+)
        )?
        (?P<after3>\ *)
        $
    ''', flags=re.VERBOSE)

    @classmethod
    def is_new_start(cls, atom: Atom, **kwargs) -> bool:
        line = cast(Line, atom)
        match = line.match(cls._line_pattern)
        if match:
            line.value = match['content'] or ''
        return bool(match)

    def __init__(self, parent: Node | None, *, line: Line):
        super().__init__(parent)

        # this will match, because is_new_start() must have returned True
        match = line.match(self._line_pattern, previous=True)
        assert match is not None
        self._level = len(match['opening'])
        self._identifier = _Heading.slugify(line.value)

    def can_remain_open(self, line: Line, **kwargs) -> bool:
        return False

    @property
    def level(self) -> int:
        return self._level

    @property
    def identifier(self) -> str:
        return self._identifier

    def __str__(self) -> str:
        return f'{super().__str__()} ({self._level})'


# XXX we have to treat this as a container, since otherwise all the other
#     container block types would get first dibs
class SetextHeading(Block, _HasInlineChildren):
    """See https://spec.commonmark.org/0.30/#setext-headings."""

    is_container = False

    __slots__ = ('_level', '_identifier')

    _line_pattern = re.compile(r'''
        ^
        (?P<before>\ {0,3})
        (?P<underline>[=-]+)
        (?P<after>\ *)
        $
    ''', flags=re.VERBOSE)

    @classmethod
    def is_new_start(cls, atom: Atom, *, last_matched: Node,
                     last_matched_container: Node | None = None,
                     **kwargs: Any) -> bool:
        line = cast(Line, atom)
        if isinstance(last_matched, Paragraph) and \
                not last_matched.is_empty and \
                (match := line.match(cls._line_pattern)):
            # if a line containing a single '-' can be interpreted as an empty
            # list item, it should be interpreted this way and not as a setext
            # heading underline
            # XXX it might be better just to check directly
            if match['underline'][0] == '-' and \
                    ListItem.is_new_start(line, last_matched=last_matched,
                                          nochange=True, **kwargs):
                return False

            # give the preceding paragraph text to the setext heading
            line.value = last_matched.text
            last_matched.removed = True
            return True
        else:
            return False

    def __init__(self, parent: Block, *, line: Line):
        super().__init__(parent)

        # this will match, because is_new_start() must have returned True
        match = line.match(self._line_pattern, previous=True)
        assert match is not None
        self._level = 1 if match['underline'][0] == '=' else 2
        self._identifier = _Heading.slugify(line.value)

    def can_remain_open(self, line: Line, **kwargs) -> bool:
        return False

    @property
    def level(self) -> int:
        return self._level

    @property
    def identifier(self) -> str:
        return self._identifier

    def __str__(self) -> str:
        return f'{super().__str__()} ({self._level})'


class BlockQuote(Block):
    _indent_pattern = re.compile(r'(^ {0,3}> ?)')

    @classmethod
    def is_new_start(cls, atom: Atom, **kwargs) -> bool:
        line = cast(Line, atom)
        match = line.match(cls._indent_pattern)
        if match:
            line.offset += len(match.group(0))
        return bool(match)

    def can_remain_open(self, atom: Atom, **kwargs: Any) -> bool:
        line = cast(Line, atom)
        return self.is_new_start(line)


class ItemList(Block):
    """`ItemList`s work in tandem with `ListItem`s. The `ItemList` methods
    parse the line prefix so `ItemList` can determine the list type, but they
    don't remove the prefix; this is done by `ListItem`."""

    # XXX should change this to use the group dict
    # XXX there may be other places where need need non-greedy <SPACE>{a,b}?
    _indent_pattern = re.compile(r'''
        ^
        (\ {0,3})
        (
            [-+*]
        |
            [0-9]{1,9}[.)]
        )
        (?:
            (\ {1,4}?)
        |
            $
        )
    ''', flags=re.VERBOSE)

    __slots__ = ('_type', '_delim', '_indent', '_start')

    @classmethod
    def is_new_start(cls, atom: Atom, *, last_matched: Node,
                     last_matched_container: Node | None = None,
                     **kwargs: Any) -> bool:
        line = cast(Line, atom)
        match = line.match(cls._indent_pattern)
        # if last matched container is a list, the current list can continue
        is_new_start = match and not isinstance(last_matched_container,
                                                ItemList)
        return is_new_start

    def __init__(self, parent: Node | None, *, line: Line):
        super().__init__(parent)

        # this will match, because is_new_start() must have returned True
        match = line.match(self._indent_pattern)
        assert match is not None
        before, marker, after = match.groups()

        self._type = 'ordered' if marker[0].isdigit() else 'bulleted'
        self._delim = marker[-1]
        self._indent = len(before) + len(marker) + len(after or '')
        self._start = int(marker[:-1]) if marker[0].isdigit() else None

    def can_remain_open(self, line: Line, *, last_matched_container: Block,
                        **kwargs) -> bool:
        if line.is_empty:
            return True
        elif line.value.expandtabs(4).startswith(self._indent * ' '):
            # XXX should have a method for the above
            return True
        elif match := line.match(self._indent_pattern):
            # XXX need this to cover the case where a previous list item can't
            #     continue; where should it be placed? ref. is_new_start()
            # XXX there's a problem here wrt thematic breaks; needs thought
            # XXX it also breaks when the last matched container is Document
            if isinstance(last_matched_container, ItemList):
                return False

            before, marker, after = match.groups()
            delim = marker[-1] if marker[0].isdigit() else marker
            return delim == self._delim
        else:
            return False

    @property
    def is_tight(self) -> bool:
        is_empties = []
        for item in self.children:
            # XXX maybe can get other things, e.g., thematic breaks?
            if isinstance(item, ListItem):
                for child in item.children:
                    is_empties.append(child.is_empty)
        is_tight = all(not is_empty for is_empty in is_empties[:-1])
        return is_tight

    @property
    def type_(self) -> str:
        return self._type

    @property
    def delim(self) -> str:
        return self._delim

    @property
    def indent(self) -> int:
        return self._indent

    @property
    def start(self) -> int | None:
        return self._start

    def __str__(self) -> str:
        start = str(self._start) if self._start is not None else ''
        tight = 't' if self.is_tight else 'l'
        return f'{super().__str__()} ({self._indent}) {start}{self._delim}' \
               f' {tight} '


class ListItem(Block):
    """TBD."""

    @classmethod
    def is_new_start(cls, atom: Atom, *, last_matched: Node,
                     last_matched_container: Node | None = None,
                     nochange: bool = False, **kwargs: Any) -> bool:
        line = cast(Line, atom)
        # noinspection PyProtectedMember
        match = line.match(ItemList._indent_pattern)
        if match and not nochange:
            line.offset += len(match.group(0))
        return bool(match)

    def can_remain_open(self, line: Line, **kwargs) -> bool:
        lst = cast(ItemList, self.parent)
        if line.is_empty:
            return True
        elif line.value.expandtabs(4).startswith(lst.indent * ' '):
            # XXX should have a method for the above
            line.offset += lst.indent
            return True
        else:
            return False


class IndentedCodeBlock(Block):
    """See https://spec.commonmark.org/0.30/#indented-code-blocks."""

    is_container = False

    _indent_pattern = re.compile(r'^( {4})')

    @classmethod
    def is_new_start(cls, atom: Atom, *, last_matched: Node,
                     last_matched_container: Node | None = None,
                     **kwargs: Any) -> bool:
        line = cast(Line, atom)
        # use of .rstrip() means that all-whitespace lines don't match
        match = line.match(cls._indent_pattern, rstrip=True)
        last_matched_is_empty = not isinstance(last_matched, Paragraph) or \
            last_matched.is_empty
        is_new_start = match and last_matched_is_empty
        if is_new_start:
            line.offset += len(match.group(0))
        return is_new_start

    def can_remain_open(self, line: Line, **kwargs) -> bool:
        # use of .rstrip() means that all-whitespace lines don't match
        match = line.match(self._indent_pattern, rstrip=True)
        can_remain_open = match or line.is_empty
        if match:
            line.offset += len(match.group(0))
        return can_remain_open


class FencedCodeBlock(Block):
    """See https://spec.commonmark.org/0.30/#fenced-code-block."""

    is_container = False

    _fence_pattern = re.compile(r'''
        ^
        (?P<indent>\ {0,3})
        (?P<fence1>[`~])
        (?P<fence2>(?P=fence1){2,})
        \ *
        (?P<info>.*?)
        \ *
        $
    ''', flags=re.VERBOSE)

    __slots__ = ('_indent', '_fence', '_info')

    @classmethod
    def is_new_start(cls, atom: Atom, *, last_matched: Node,
                     last_matched_container: Node | None = None,
                     **kwargs: Any) -> bool:
        line = cast(Line, atom)
        # use of .rstrip() means that all-whitespace lines don't match
        match = line.match(cls._fence_pattern, rstrip=True)
        last_matched_is_empty = not isinstance(last_matched, Paragraph) or \
            last_matched.is_empty
        is_new_start = match and last_matched_is_empty
        if is_new_start:
            line.value = ''
        return is_new_start

    def __init__(self, parent: Node | None, *, line: Line):
        super().__init__(parent)

        # this will match, because is_new_start() must have returned True
        match = line.match(self._fence_pattern, previous=True)
        assert match is not None

        self._indent = len(match['indent'])
        self._fence = match['fence1'] + match['fence2']
        self._info = match['info']
        pass

    def can_remain_open(self, line: Line, **kwargs) -> bool:
        # use of .rstrip() means that all-whitespace lines don't match
        match = line.match(self._fence_pattern, rstrip=True)
        if not match or match['fence1'] != self._fence[0] or \
                len(match['fence1']) + len(match['fence2']) < \
                len(self._fence) or match['info']:
            return True
        else:
            line.value = ''
            return False

    @property
    def indent(self) -> int:
        return self._indent

    @property
    def fence(self) -> str:
        return self._fence

    @property
    def info(self) -> str:
        return self._info


class FencedDiv(Block):
    """See https://pandoc.org/MANUAL.html#extension-fenced_divs. This
    is a pandoc extension."""

    _fence_pattern = re.compile(r'''
        ^
        (?P<fence>:{3,})
        \ *
        (?:
            (?P<class>\w+)
        |
            (?P<attr>{.*})
        )?
        (?:
            \ *
            :+
        )?
        \ *
        $
    ''', flags=re.VERBOSE)

    __slots__ = ('_attr', '_closed')

    @classmethod
    def is_new_start(cls, atom: Atom, **kwargs: Any) -> bool:
        line = cast(Line, atom)
        match = line.match(cls._fence_pattern)
        is_new_start = match and (match['class'] or match['attr'])
        if is_new_start:
            line.value = ''
        return is_new_start

    def __init__(self, parent: Node | None, *, line: Line):
        super().__init__(parent)

        # this will match, because is_new_start() must have returned True
        match = line.match(self._fence_pattern, previous=True)
        assert match is not None

        self._attr = Attr(match['class'] or match['attr'])
        self._closed = False

    def can_remain_open(self, line: Line, **kwargs) -> bool:
        match = line.match(self._fence_pattern)
        if not match:
            return True
        elif match['class'] or match['attr']:
            return True
        else:
            def func(block: Block, *, result: int, **_kwargs):
                if isinstance(block, FencedDiv) and not block.closed:
                    return result + 1
            depth = self.visit(func, result=0)
            if depth > 1:
                return True
            else:
                line.value = ''
                self._closed = True
                return False

    @property
    def attr(self) -> Attr:
        return self._attr

    @property
    def closed(self) -> bool:
        return self._closed

    def __str__(self) -> str:
        return f'{super().__str__()}{self._attr}'


# XXX have I done all the leading and trailing whitespace removal correctly?
class Paragraph(Block, _HasInlineChildren):
    """See https://spec.commonmark.org/0.30/#paragraphs. "The paragraph’s raw
    content is formed by concatenating the lines and removing initial and
    final spaces or tabs."."""

    is_container = False

    @classmethod
    def is_new_start(cls, atom: Atom, *, last_matched: Node,
                     last_matched_container: Node | None = None,
                     **kwargs: Any) -> bool:
        is_new_start = last_matched.is_container
        return is_new_start

    def can_remain_open(self, line: Atom, **kwargs: Any) -> bool:
        line = cast(Line, line)
        can_remain_open = not self.is_empty and not line.is_empty
        return can_remain_open


class Document(Block):
    def __init__(self, context: Context, markdown: str | list[str]):
        super().__init__(context)

        # parse the markdown lines into blocks
        self.parse_blocks(markdown)

        # visit paragraphs to filter out link references
        def filter_paragraphs(block: Block, *, preparse: bool,  **_kwargs):
            if isinstance(block, Paragraph):
                LinkReference.filter(block, preparse=preparse)

        self.visit(filter_paragraphs, preparse=True)

        # parse the blocks into inlines (recursively)
        self.parse_inlines()

        # visit paragraphs to remove the link reference definitions (and any
        # paragraphs that, as a result, are empty)
        self.visit(filter_paragraphs, preparse=False)

        # convert things like "[a](b)" (Bracketed, Parenthesized) to links
        # XXX brackets that aren’t part of links do not take precedence, so
        #     remaining Bracketed instances should be unwrapped
        # XXX should check that Full and compact references take precedence
        #     over shortcut references, and that inline links also take
        #     precedence
        self.process_links()

        # convert things like "[a]{.b}" (Bracketed, Braced) to spans
        self.process_spans()

        # process emphasis
        self.process_emphasis()

        # process entities
        self.process_entities()

    # XXX should probably move this, or some of it, to Block?
    # XXX or move it to Node so Block and Inline have common logic
    # XXX is there any need to include Paragraph?
    def parse_blocks(self, markdown: str | list[str]) -> None:
        block_types = sorted([typ for typ in get_subclasses(Block) if
                              typ is not type(self) and
                              not typ.__name__.startswith('_')],
                             key=lambda c: (c.precedence, c.__name__))
        # noinspection PyUnreachableCode
        if False:
            logger.debug('types ' + ', '.join(
                    f'{typ.__name__}({typ.precedence})' for typ in
                    block_types))

        lines_ = markdown.splitlines(keepends=True) \
            if isinstance(markdown, str) else markdown
        lines = [Line(line) for line in lines_]

        for num, line in enumerate(lines):
            logger.debug(f'{num:03d} {len(line):03d} {line!r}')

            last_matched = self
            last_matched_container = self.container
            for block in self.open_blocks:
                can_remain_open = block.can_remain_open(
                        line, last_matched=last_matched,
                        last_matched_container=last_matched_container)
                if not can_remain_open:
                    logger.debug("- can't remain open %s %r" % (block, line))
                else:
                    logger.debug('- can remain open %s %r' % (block, line))
                    last_matched = block
                    if last_matched.is_container:
                        last_matched_container = last_matched

            # block_types_pruned = [typ for typ in block_types if (
            #         typ.precedence < math.ceil(last_matched.precedence))]
            # XXX the above won't contain Paragraph (because it's the lowest
            #     priority Block and doesn't have a fractional precedence);
            #     and we don't add it because it the special case below
            # if Paragraph not in block_types_pruned:
            #     block_types_pruned.append(Paragraph)

            # XXX this pruning doesn't serve any purpose for Blocks, only for
            #     Inlines?
            block_types_pruned = block_types[:]
            block_types_pruned.remove(Paragraph)

            # noinspection PyUnreachableCode
            if False:
                logger.debug('pruned ' + ', '.join(
                        f'{typ.__name__}({typ.precedence})' for typ in
                        block_types_pruned))

            while True:
                any_is_new_start = False
                for block_type in block_types_pruned:
                    is_new_start = block_type.is_new_start(
                            line, last_matched=last_matched,
                            last_matched_container=last_matched_container)
                    if not is_new_start:
                        logger.debug("- can't be new %s %r" % (
                            block_type.class_name(), line.value))
                    else:
                        logger.debug('- is new %s %r' % (
                            block_type.class_name(), line.value))
                        last_matched = \
                            block_type(last_matched_container, line=line)
                        if last_matched.is_container:
                            last_matched_container = last_matched
                            any_is_new_start = True

                        if not last_matched.is_container or line.is_empty:
                            any_is_new_start = False
                            break

                if not any_is_new_start:
                    break

            # XXX I guess Paragraph really is special?
            if last_matched.is_container:
                Paragraph(last_matched, line=line)

            self.last_open_block.add_line(line)

    def process_links(self) -> None:
        def func(inline: Inline, **_kwargs):
            link_text, link_dest, _, _ = Link.is_valid(inline)
            if link_text:
                link = Link(link_text)
                inlines = (link_text,) + ((link_dest,) if link_dest else ())
                inline.parent.replace(inlines, link)

        self.visit(func, after=True)

    def process_spans(self) -> None:
        def func(inline: Inline, **_kwargs):
            span_text, span_attr = BracketedSpan.is_valid(inline)
            if span_text and span_attr:
                span = BracketedSpan(span_text)
                inlines = (span_text, span_attr)
                inline.parent.replace(inlines, span)

        self.visit(func, after=True)

    def process_emphasis(self) -> None:
        def func(node: Node, **_kwargs):
            # XXX the child check is unnecessary; it's just an optimization
            if isinstance(node, _HasInlineChildren) and any(
                    isinstance(child, DelimiterRun)
                    for child in cast(Node, node).children):
                node.process_emphasis()

        self.visit(func, after=True)

    def process_entities(self) -> None:
        def func(node: Node, **_kwargs):
            if isinstance(node, Paragraph):
                children = cast(list[Inline], node.children)
                index = 0
                while index + 2 < len(children):
                    amp, name, term = children[index:index + 3]
                    if isinstance(amp, Text) and amp.first_token and \
                            amp.first_token.is_punctuation \
                            and amp.first_token.value == '&' and \
                        isinstance(name, Text) and \
                        isinstance(term, Text) and term.first_token and \
                        term.first_token.is_punctuation and \
                        term.first_token.value == ';':
                        entity = Entity(name.raw_text)
                        # XXX it would be more elegant to make these three
                        #     nodes be Entity children
                        node.replace((amp, name, term), entity)
                    index += 1

        self.visit(func, after=True)


# this must be after the last Block definition
Block.set_precedence()


# XXX where should this be in the file?
class LinkReference:
    """See https://spec.commonmark.org/0.30/#link-reference-definition."""

    @classmethod
    def get(cls, node: Node, label: str) -> LinkReference | None:
        label_normalized = cls._normalize_label(label)
        return node.context.references.get(label_normalized, None)

    def __init__(self, node: Node, label: str, dest: str,
                 title: str | None = None):
        self._label = label
        self._dest = dest
        self._title = title

        # - If there are several matching definitions, the first one takes
        #   precedence
        label_normalized = self._normalize_label(label)
        references = node.context.references
        if label_normalized not in references:
            references[label_normalized] = self
        elif dest != references[label_normalized].dest:
            logger.warning(f'link reference {label} already defined with '
                           f'{references[label_normalized].dest}; not '
                           f'changed to {dest}')

    @classmethod
    def filter(cls, paragraph: Paragraph, *, preparse: bool = False) -> None:
        """Filter out link references from a paragraph, removing the
        filtered-out inlines and, if the resulting paragraph is empty,
        the paragraph itself.

        A LINK REFERENCE definition consists of a LINK LABEL, optionally
        preceded by up to three spaces of indentation, followed by a colon,
        optional spaces or tabs (including up to one line ending), a
        LINK DESTINATION, optional spaces or tabs (including up to one line
        ending), and an optional LINK TITLE, which, if it is present, must be
        separated from the LINK DESTINATION by spaces or tabs. No further
        character may occur."""

        # if this is pre-parse, the inlines haven't been parsed yet, and we
        # need to parse and define the link reference definitions; we use a
        # temporary paragraph so as not to disturb the original
        if not preparse:
            para = paragraph
        else:
            para = Paragraph(None)
            paragraph.parse_inlines(parent=para)
        inlines = para.children

        # check whether the inlines contain link definitions
        index = 0

        def not_done() -> bool:
            return index < len(inlines)

        def current() -> Node | None:
            return inlines[index] if not_done() else None

        def have(types: type[Node] | tuple[type[Node], ...],
                 pred: Callable[..., bool] | None = None) -> bool:
            return not_done() and isinstance(current(), types) \
                and (not pred or pred(current()))

        def consume() -> None:
            nonlocal index
            index += 1

        def skip() -> None:
            while have(Inline, lambda i: '\n' not in i.text):
                consume()
            if not_done():
                consume()

        any_removed = False
        while not_done():
            index_saved = index

            # optional up to three leading spaces
            if have(Text, lambda i: re.match(r'^ {0,3}$', i.text)):
                consume()

            # required link label
            if have(Bracketed):
                label = current().text
                consume()
            else:
                skip()
                continue

            # required colon
            if have(Text, lambda i: i.text == ':'):
                consume()
            else:
                skip()
                continue

            # required dest and optional title (dest of None indicates invalid)
            dest, title, index = cls.parse_link_dest_and_title(inlines, index)
            if dest is None:
                pass

            # if pre-parse, create and store the link reference
            # XXX should use the proposed special slices here (but NOT for
            #     label, because it should retain its '[]'
            # XXX it's necessary to remove parens if title is in them!
            elif preparse:
                LinkReference(paragraph, label, dest, title)

            # if not pre-parse, remove the consumed inlines
            else:
                for ind in range(index_saved, index):
                    inlines[ind].removed = True
                    any_removed = True

        # if not pre-parse, remove the paragraph if it's now empty
        # (only do this if any link references were removed; don't remove
        # already-empty paragraphs)
        if not preparse and any_removed and not paragraph.children:
            paragraph.removed = True

    @staticmethod
    def parse_link_dest_and_title(inlines: list[Inline], index: int = 0) \
            -> tuple[str | None, str | None, int]:
        # XXX these helpers are copied from filter(); should define them once
        #     (they'd need more context)
        def not_done() -> bool:
            return index < len(inlines)

        def current() -> Node | None:
            return inlines[index] if not_done() else None

        def have(types: type[Node] | tuple[type[Node], ...],
                 pred: Callable[..., bool] | None = None) -> bool:
            return not_done() and isinstance(current(), types) \
                and (not pred or pred(current()))

        def consume() -> None:
            nonlocal index
            index += 1

        def skip() -> None:
            while not_done() and not have((SoftBreak, HardBreak)):
                consume()

        # XXX could support a stack, but not needed here
        def push() -> None:
            nonlocal index_saved
            index_saved = index

        def pop() -> None:
            nonlocal index
            assert index_saved is not None
            index = index_saved

        index_saved = None
        dest, title = None, None
        while not_done():
            # optional whitespace
            while have(Text, lambda i: i.text.isspace()) or \
                    have((SoftBreak, HardBreak)):
                consume()

            # required link destination
            if have((Parenthesized, Angled)):
                # XXX should use the proposed special slices here
                dest = current().text[1:-1]
                consume()
            else:
                comps = []
                while have(Inline, lambda i: not i.text.isspace()) and \
                        not have((SoftBreak, HardBreak)):
                    comps.append(current().text)
                    consume()
                if comps:
                    dest = ''.join(comps)
                else:
                    skip()
                    continue

            # optional whitespace
            push()
            while have(Text, lambda i: i.text.isspace()) or \
                    have((SoftBreak, HardBreak)):
                consume()

            # optional title (if not there, step back over above whitespace)
            if have((_SingleQuoted, DoubleQuoted, Parenthesized)):
                title = current().text
                consume()
            else:
                pop()

            # must now be out of tokens or at end of line
            if have((SoftBreak, HardBreak)):
                consume()
            elif not_done():
                dest = None
                skip()
                break

            # done; leave the rest for the caller
            break

        return dest, title, index

    @staticmethod
    def _normalize_label(label: str) -> str:
        """See https://spec.commonmark.org/0.30/#link-label. "To normalize a
        label, strip off the opening and closing brackets, perform the Unicode
        case fold, strip leading and trailing spaces, tabs, and line endings,
        and collapse consecutive internal spaces, tabs, and line endings to a
        single space"."""

        # strip off the opening and closing brackets
        # XXX can't currently assume that the trailing one is there
        if label.startswith('['):
            label = label[1:]
        if label.endswith(']'):
            label = label[:-1]

        # perform the Unicode case fold
        # XXX is this sufficient?
        label = label.lower()

        # strip leading and trailing spaces, tabs, and line endings
        label = label.strip()

        # collapse consecutive internal spaces, tabs, and line endings
        label = re.sub(r'\s+', ' ', label)
        return label

    @property
    def label(self) -> str:
        return self._label

    @property
    def dest(self) -> str:
        return self._dest

    @property
    def title(self) -> str | None:
        return self._title

    def __str__(self) -> str:
        title = f' "{self._title}"' if self._title else ''
        return f'{self._dest}{title}'

    __repr__ = __str__


class Writer:
    # XXX want a simple equivalent of
    #     https://pandoc.org/lua-filters.html#module-pandoc.layout
    CR = '\n'

    @staticmethod
    def indent(level: int = 0) -> str:
        return level * '  '

    def write(self, document: Document, **kwargs: Any) -> Any:
        pass

    def visit(self, node: Node, *, level: int = 0, **kwargs: Any) -> Any:
        pass


class TextWriter(Writer):
    def visit(self, node: Node, *, level: int = 0, **kwargs: Any) -> Any:
        logger.info(f'{self.indent(level)}{node}')


# XXX report.py output formats should support this style; could handle this
#     via _begin_() returning Rules(depth_first=True), which would cause the
#     visit_xxx() functions to be called just before _post_elems_(); would
#     also need to handle the return value
# XXX should define a ListStr type that's like a mixture of a List[str] and a
#     str and that supports efficient in-place updates with '+', '+=' etc.
# XXX need to apply leading/trailing newline policy
# XXX need to do regular HTML &lt; etc. escaping
class HtmlWriter(Writer):
    reported = set()

    # XXX should improve this
    @staticmethod
    def escape(t: str) -> str:
        return t.replace('&', '&amp;').\
            replace('<', '&lt;').replace('>', '&gt;')

    def write(self, document: Document, *,
              result: list[str] | None = None, **kwargs: Any) -> list[str]:
        return self.expand(document, result)

    def expand(self, node: Node, result: list[str] | None = None) -> \
            list[str]:
        if result is None:
            result = []

        result_ = []
        for child in node.children:
            if not child.hidden:
                result_.extend(self.expand(child, result))

        # XXX it would be better to use inspect here
        func_name = f'{type(node).class_name()}'
        if not (func := getattr(self, func_name, None)):
            if func_name not in self.reported:
                logger.error(f'non-existent {type(self).__name__}.'
                             f'{func_name}()')
                self.reported.add(func_name)
            func = self.fallback

        return func(node, result_)

    @classmethod
    def document(cls, _: Document, result: list[str]) -> list[str]:
        # XXX for now, generate a fragment, so there's no <html> tag
        # return ['<html>'] + result + ['</html>']
        return result + [cls.CR]

    @classmethod
    def indented_code_block(cls, block: IndentedCodeBlock,
                            _: list[str]) -> list[str]:
        return [cls.CR, '<pre><code>'] + [cls.escape(block.raw_text)] + \
            [cls.CR, '</code></pre>', cls.CR]

    @classmethod
    def fenced_code_block(cls, block: FencedCodeBlock,
                          _: list[str]) -> list[str]:
        language = f' class="language-{block.info.split()[0]}"' if block.info \
            else ''
        return [cls.CR, f'<pre><code{language}>'] + \
            [cls.escape(block.raw_text)] + [cls.CR, '</code></pre>', cls.CR]

    @classmethod
    def fenced_div(cls, node: FencedDiv,
                   result: list[str]) -> list[str]:
        if not node.attr:
            return result
        else:
            return [cls.CR, f'<div{node.attr}>', cls.CR] + result + \
                [cls.CR, '</div>', cls.CR]

    @classmethod
    def paragraph(cls, paragraph: Paragraph, result: list[str]) -> \
            list[str]:
        def get_item_list(node: Node) -> ItemList | None:
            return node if isinstance(node, ItemList) else get_item_list(
                    node.parent) if node.parent is not None else None

        def get_fenced_div(node: Node) -> FencedDiv | None:
            return node if isinstance(node, FencedDiv) else get_fenced_div(
                    node.parent) if node.parent is not None else None

        # handle tight/loose lists
        if (lst := get_item_list(paragraph)) and lst.is_tight:
            opener, closer = [], []
        else:
            opener, closer = [cls.CR, '<p>'], ['</p>']

        # XXX implement html-derived-writer.lua logic (partial; needs rewrite
        #     and to be conditional and not to be done here)
        # XXX no longer needed? have worked around it using CSS
        # if False and (div := get_fenced_div(paragraph)):
        #     non_empty_children = [child for child in div.children
        #                           if not child.is_empty]
        #     if len(non_empty_children) == 1 and \
        #             non_empty_children[0] is paragraph:
        #         opener, closer = [], []

        # XXX should weed out and strip empty paragraphs earlier
        text = ''.join(result).strip()
        return opener + [text] + closer if text else []

    @classmethod
    def thematic_break(cls, _: ThematicBreak, result: list[str]) \
            -> list[str]:
        assert not result
        return [cls.CR, '<hr />', cls.CR]

    @classmethod
    def atx_heading(cls, heading: AtxHeading, result: list[str]) \
            -> list[str]:
        level = heading.level
        identifier = heading.identifier

        # look for attributes
        # XXX should have a utility for this
        # XXX this isn't how the pandoc attributes extension works; it uses
        #     trailing attributes (inlines) at the end of the header line
        attr = heading.previous_sibling.attr if isinstance(
                heading.previous_sibling, Attributes) else Attr('')

        # we prefer an explicit identifier to an implicit identifier
        # XXX should have the same logic for classes and attributes
        identifier = attr.identifier or identifier
        identifier = f' id="{identifier}"' if identifier else ''

        return [cls.CR, f'<h{level}{identifier}>'] + result + [f'</h{level}>']

    # XXX oops; this should be declared as SetextHeading! there should be a
    #     common base class
    @classmethod
    def setext_heading(cls, heading: AtxHeading, result: list[str]) \
            -> list[str]:
        return cls.atx_heading(heading, result)

    @classmethod
    def block_quote(cls, _: BlockQuote, result: list[str]) \
            -> list[str]:
        return [cls.CR, '<blockquote>', cls.CR] + result + \
            [cls.CR, '</blockquote>', cls.CR]

    @classmethod
    def item_list(cls, lst: ItemList, result: list[str]) -> list[str]:
        # XXX need to do this generically for all blocks (and inlines), and
        #     also combine multiple Attributes nodes
        attr = cast(Attributes, lst.previous_sibling).attr \
            if isinstance(lst.previous_sibling, Attributes) else ''
        elem = 'ol' if lst.type_ == 'ordered' else 'ul'
        start = f' start="{lst.start}"' if lst.start not in {None, 1} else ''
        return [cls.CR, f'<{elem}{start}{attr}>', cls.CR] + result + \
            [cls.CR, f'</{elem}>', cls.CR]

    @classmethod
    def list_item(cls, _: BlockQuote, result: list[str]) -> list[str]:
        return [cls.CR, '<li>'] + result + ['</li>', cls.CR]

    # XXX should make the rest class methods too?
    @staticmethod
    def code_span(_: Text, result: list[str]) -> list[str]:
        return ['<code>'] + result + ['</code>']

    @staticmethod
    def bracketed(_: Link, result: list[str]) -> list[str]:
        return result

    @staticmethod
    def shriek_bracketed(_: Link, result: list[str]) -> list[str]:
        # XXX what should this return?
        return ['<b>', 'SHRIEK '] + result + ['</b>']

    @staticmethod
    def parenthesized(_: Link, result: list[str]) -> list[str]:
        return result

    @staticmethod
    def angled(_: Link, result: list[str]) -> list[str]:
        return result

    @staticmethod
    def macro_ref(_: MacroRef, result: list[str]) -> list[str]:
        return result

    @staticmethod
    def superscript(_: Superscript, result: list[str]) -> list[str]:
        return ['<sup>'] + result + ['</sup>']

    @staticmethod
    def subscript(_: Subscript, result: list[str]) -> list[str]:
        return ['<sub>'] + result + ['</sub>']

    @staticmethod
    def link(node: Link, result: list[str]) -> list[str]:
        title = f' title="{node.title}"' if node.title else ''
        return [f'<a href="{node.dest}"{title}>'] + result + ['</a>']

    @staticmethod
    def bracketed_span(node: BracketedSpan,
                       result: list[str]) -> list[str]:
        if not node.attr:
            return result
        else:
            return [f'<span{node.attr}>'] + result + ['</span>']

    # XXX this is only called for _excess_ delimiter runs
    @staticmethod
    def delimiter_run(_: DelimiterRun, result: list[str]) -> list[str]:
        return result

    # XXX this is only called for unprocessed attributes nodes
    @staticmethod
    def braced(_: Braced, result: list[str]) -> list[str]:
        return result

    @staticmethod
    def emph(_: Link, result: list[str]) -> list[str]:
        return ['<em>'] + result + ['</em>']

    @staticmethod
    def strong(_: Link, result: list[str]) -> list[str]:
        return ['<strong>'] + result + ['</strong>']

    @staticmethod
    def double_quoted(_: Link, result: list[str]) -> list[str]:
        return ['&quot;'] + result + ['&quot;']

    @staticmethod
    def single_quoted(_: Link, result: list[str]) -> list[str]:
        return ['&apos;'] + result + ['&apos;']

    @classmethod
    def soft_break(cls, node: Text, result: list[str]) -> list[str]:
        return result + ['\n']

    @classmethod
    def hard_break(cls, node: Text, result: list[str]) -> list[str]:
        return result + ['<br />']

    @classmethod
    def text(cls, node: Text, result: list[str]) -> list[str]:
        return result + [cls.escape(node.text)]

    @classmethod
    def entity(cls, node: Entity, result: list[str]) -> list[str]:
        assert not result
        return [f'&{node.name};']

    @staticmethod
    def fallback(node: Node, result: list[str]) -> list[str]:
        name = type(node).class_name()
        if isinstance(node, Inline) and node.tokens:
            result.append(node.text)
        elif not result:
            result.insert(0, f'<{name} />')
        else:
            result.insert(0, f'<{name}>')
            if isinstance(node, Block):
                result.insert(0, '\n')
            result.append(f'</{name}>')
        return result
