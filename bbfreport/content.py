"""Content utilities."""

# Copyright (c) 2022, Broadband Forum
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

import logging
import re

from functools import cache
from typing import Any, Dict, List, Optional, Tuple, Union

from .utility import Utility

logger_name = __name__.split('.')[-1]
logger = logging.getLogger(logger_name)
logger.addFilter(
        lambda r: r.levelno > 20 or logger_name in Utility.logger_names)

# Note that description templates such as {{param}} are always referred to as
# macros, to avoid any confusion with <template> XML elements


# macro reference components (these are only used internally)
class _MacroRefItem:
    def __init__(self, name: str, *, level: int = 0):
        self._name = name
        self._level = level

    def __hash__(self):
        return hash((type(self), hash(self._name), hash(self._level)))

    def __eq__(self, other):
        if isinstance(other, _MacroRefItem):
            return (self._name, self._level) == (other._name, other._level)
        elif isinstance(other, str):
            return False
        else:
            raise NotImplementedError("can't compare %s (%s) with %s" % (
                type(self).__name__, self, type(other).__name__))

    @property
    def name(self) -> str:
        return self._name

    @property
    def level(self) -> int:
        return self._level

    def __str__(self):
        return self._name

    def __repr__(self):
        typename = type(self).__name__.replace('_MacroRef', '').lower()
        # XXX I was thinking that including the level would help to improve
        #     diffs detection, but it doesn't help?
        # level = ',%d' % self._level if self._level > 0 else ''
        level = ''
        return '%s(%s%s)' % (typename, self._name, level)


class _MacroRefCall(_MacroRefItem):
    whitespace_macros = {'nl'}

    __hash__ = _MacroRefItem.__hash__

    def __eq__(self, other):
        if isinstance(other, str) and self._name in self.whitespace_macros:
            # XXX this returns False if it's an empty string
            return other.isspace()
        else:
            return super().__eq__(other)

    def __str__(self):
        return '{{%s}}' % self._name


class _MacroRefOpen(_MacroRefItem):
    # level is mandatory
    def __init__(self, name: str, *, level: int):
        super().__init__(name, level=level)

    def __str__(self):
        return '{{%s|' % self._name


class _MacroRefClose(_MacroRefItem):
    # level is mandatory
    def __init__(self, name: str, *, level: int):
        super().__init__(name, level=level)

    def __str__(self):
        return '}}'


class _MacroRefArgSep(_MacroRefItem):
    def __init__(self):
        super().__init__('|')


class MacroRef:
    """Macro reference such as ``{{param|Alias}}``."""

    _macro_ref_counts = {}

    def __init__(self,
                 chunks: List[Union[str, '_MacroRefArgSep', 'MacroRef']]):
        # - chunks will be empty for empty macro references: {{}}
        # - first chunk will be arg-separator in this case: {{|arg}}
        if len(chunks) == 0 or not isinstance(chunks[0], str):
            self._name = ''
            next_chunk = 0
        else:
            self._name = chunks[0]
            next_chunk = 1

        # each arg will be a list of strings and/or macro references
        args = []
        arg = None
        for chunk in chunks[next_chunk:]:
            if isinstance(chunk, _MacroRefArgSep):
                if arg is not None:
                    args.append(arg)
                arg = MacroArg()
            else:
                assert arg is not None
                arg.append(chunk)

        if arg is not None:
            args.append(arg)

        # convert args to tuples
        self._args = tuple(arg for arg in args)

        # update statistics
        self._macro_ref_counts.setdefault(self._name, 0)
        self._macro_ref_counts[self._name] += 1

    @property
    def name(self) -> str:
        return self._name

    @property
    def args(self) -> Tuple['MacroArg', ...]:
        return self._args

    def __str__(self):
        name = repr(self._name) if ' ' in self._name else self._name
        return '%s(%s)' % (name,
                           ', '.join(str(arg) for arg in self._args))

    __repr__ = __str__


class MacroArg:
    """Macro argument, which consists of a list of strings and macro
    references.

    This is exactly the same as content body.
    """

    # it's created empty or with a single item; append() can add more items
    def __init__(self, item: Optional[Union[str, MacroRef]] = None):
        self._items = []
        if item is not None:
            self.append(item)

    def append(self, item: Union[str, MacroRef]) -> None:
        assert isinstance(item, (str, MacroRef))
        self._items.append(item)

    @property
    def is_simple(self) -> bool:
        return len(self._items) == 0 or (
            len(self._items) == 1 and isinstance(self._items[0], str))

    @property
    def items(self) -> List[Union[str, MacroRef]]:
        return self._items

    # XXX should extend this to work for complex args too; it should
    #     always return the original text from the macro reference
    @property
    def text(self) -> Optional[str]:
        return self._items[0] if self.is_simple and self._items else None

    # XXX maybe this just return self.text or ''?
    def __str__(self):
        return str(self._items)

    __repr__ = __str__


class Content:
    # XXX this has problems; I think that to do a proper job we need to match
    #     braces and therefore can't use a regex
    _token_regex = re.compile(r'''
        (?<!\\)             # not preceded by backslash
        (
            {{ (?!{[^{])    # {{ but not followed by { + not-{
        |
            (?<!{[^}]) }}   # }} but not preceded by { + not-}
                            # XXX this is a hack for {i}}}
        |
            \|              # | (literal)
        )
    ''', flags=re.VERBOSE)

    def __init__(self, text: Optional[str] = None, *,
                 footer: Optional[str] = None,
                 preprocess: bool = False) -> None:
        self._text = text
        self._footer = footer
        self._preprocess = preprocess
        self._body = None
        self._macro_refs = {}
        self._parsed = False

        # this is calculated externally by Macro.expand(content, node=node)
        # and then set as a property
        self._markdown = None

    _list_re = re.compile(r'''
        ^
        (?P<typ>[*#:]+)
        (?P<cnt>:*)
        (?P<sep>\s*)
        (?P<rst>.*)
        $
        ''', flags=re.VERBOSE)

    # the supplied text may contain mediawiki markup as defined in TR-106
    # (https://data-model-template.broadband-forum.org/index.htm#sec:markup);
    # this is quite similar (but not identical) to markdown, so convert to
    # something more markdown-like
    # XXX it also wraps paragraphs in {{div}} macro references
    @classmethod
    def _preprocess_text(cls, text: Optional[str]) -> Optional[str]:
        # the supplied text can be None
        if text is None:
            return None

        # paragraphs are wrapped in {{div}} macro references, so have to
        # escape any outer-level (and unescaped) '|' characters, e.g. r'a|b'
        # becomes r'a\|b' and then r'{{div|...|a\|b}}'
        orig = text
        chars = []
        level = 0
        escaped = False
        for char in text:
            if char == '\\':
                escaped = True
            elif escaped:
                escaped = False
            elif char == '{':
                level += 1
            elif char == '}' and level > 0:
                level -= 1
            elif char == '|' and level == 0:
                chars.append('\\')
            chars.append(char)
        text = ''.join(chars)
        if text != orig:
            logger.debug('escape: %r -> %r' % (orig, text))

        # process line by line
        block_active = False
        tuples = []
        for line in text.splitlines():
            orig = line
            msg = 'converted'

            # an empty line always terminates the current block (see below
            # for why we don't have to worry about trailing spaces)
            # XXX is this wrong if currently within indented text?
            if line == '':
                block_active = False

            # look for lists
            if match := cls._list_re.match(line):
                dct = match.groupdict()
                typ, cnt, sep, rst = \
                    dct['typ'], dct['cnt'], dct['sep'], dct['rst']
                if len(typ) == 0:
                    pass
                # ignore '*' and '#' lines with no separators; the '*'
                # might indicate emphasis and the '#' might be part of
                # a path reference
                elif typ[0] in {'*', '#'} and sep == '':
                    pass
                else:
                    # leading ':' is an indented list, but there's no markdown
                    # equivalent so (temporarily) convert to a bulleted list
                    if typ.startswith(':'):
                        typ = '*' * len(typ)
                        msg += ' indented -> bulleted'

                    # replace '**' with '  *' etc. ('#' needs to be '#.')
                    # XXX '#.' doesn't work with commonmark_x, so just use '1.'
                    typ0 = '1.' if typ[0] == '#' else typ[0]
                    typ = '%s%s' % ('  ' * (len(typ) - 1), typ0)
                    if len(typ) > 1:
                        msg += ' nested list'

                    # XXX not yet handling cnt (continue)
                    # XXX content can be parsed more than once, e.g. by both
                    #     'used' and 'lint', in which case warnings can be
                    #     output more than once; should avoid this
                    if cnt:
                        logger.warning('unhandled list continuation: %r' %
                                       line)

                    # update the line
                    # XXX could put more info into the {{li}} macro, e.g. depth
                    line = '{{li|%s}}%s' % (typ, rst)

            # warn of insufficiently (or erroneously) indented text
            # (don't try to fix it; there are too many cases to consider)
            if match := re.match(r'^(\s+)', line):
                # there shouldn't be any tabs, but if there are, expand them
                # (the tab size defaults to 8)
                indent = match.group(1).expandtabs()
                if not block_active and len(indent) < 4:
                    logger.info('increase indent %d to 4 for preformatted '
                                'text (or remove indent): %r' % (
                                    len(indent), line))

            # replace ''' with ** (strong) and '' with * (emphasis)
            if "'''" in line:
                line = line.replace("'''", "**")
                msg += ' strong'
            if "''" in line:
                line = line.replace("''", "*")
                msg += ' emphasis'

            # report changed lines
            if line != orig:
                logger.debug('%s: %r -> %r' % (msg, orig, line))

            # paragraph processing; Utility.whitespace() will have removed
            # any trailing spaces, so empty lines will always be ''
            open_div = close_div = line == ''
            tuples.append((open_div, close_div, line))

            # note that a block is active
            if line != '':
                block_active = True

        text = ''
        for open_div, close_div, line in \
                [(True, False, '')] + tuples + [(False, True, '')]:
            if close_div:
                text += '}}'
            if open_div:
                text += '{{div|{{classes}}|'
            if line:
                text += line + '{{nl}}'
        # XXX this isn't 100% safe, but it's OK if {{nl}} is never documented
        text = text.replace('{{nl}}}}', '}}')
        return text

    def _parse(self) -> None:
        if self._parsed:
            return

        def push() -> None:
            stack.append([])

        def argsep(force: bool = False) -> None:
            # '|' isn't special in the {{content}} argument (unless forced)
            if len(stack) > 2 or force:
                stack[-1].append(_MacroRefArgSep())
            else:
                append()

        # noinspection GrazieInspection
        def pop(force: bool = False) -> None:
            # '}}' isn't special in the {{content}} argument (unless forced)
            if len(stack) > 2 or force:
                chunks = stack.pop()
                # noinspection PyShadowingNames
                macro_ref = MacroRef(chunks)
                stack[-1].append(macro_ref)
                if not force:
                    # create two entries:
                    # - one keyed by name
                    self._macro_refs.setdefault(macro_ref.name, [])
                    self._macro_refs[macro_ref.name].append(macro_ref)
                    # - and the other keyed by (name, #args)
                    key = (macro_ref.name, len(macro_ref.args))
                    self._macro_refs.setdefault(key, [])
                    self._macro_refs[key].append(macro_ref)
            else:
                append()

        def append() -> None:
            stack[-1].append(token)

        # pre-process the supplied text to remove mediawiki-specifics
        # (the 'mrkdwn' term is borrowed from Slack and is intended to
        # suggest a markdown-like language that isn't actual markdown)
        # (pre-processing is typically suppressed when macro expansions
        # return content)
        self._mrkdwn = self._preprocess_text(self._text) if self._preprocess \
            else self._text

        # the stack starts off with an empty item...
        stack = []
        push()

        # ...followed by (effectively) '{{content|', so the text is all treated
        # as the {{content}} macro's single argument
        push()
        token = 'content'
        append()
        argsep(True)

        for token in self._token_regex.split(self._mrkdwn or ''):
            if token == '{{':
                push()
            elif token == '|':
                argsep()
            elif token == '}}':
                # this protects against mismatched '}}'
                pop()
            elif token != '':
                append()

        # close any unterminated macro references
        while len(stack) > 1:
            pop(True)

        # the stack now contains a single item, with a single chunk, which is
        # a macro reference
        assert len(stack) == 1 and len(stack[0]) == 1
        macro_ref = stack[-1][0]
        assert isinstance(macro_ref, MacroRef)

        # furthermore, the macro reference has a single argument
        assert len(macro_ref.args) == 1

        # the content body is this argument
        self._body = macro_ref.args[0]
        self._parsed = True

    @property
    def text(self) -> str:
        return self._text or ''

    @property
    def preprocess(self) -> bool:
        return self._preprocess

    @property
    def body(self) -> MacroArg:
        self._parse()
        return self._body

    # split on whitespace
    # XXX it's tempting to add some punctuation characters such as '.', but
    #     there are unintended consequences, such as splitting paths and
    #     versions; either don't bother or else make the regex more complex
    _split_pattern = re.compile(r'(\s+)')

    # this is intended for use when comparing content
    @property
    @cache
    def body_as_list(self) -> List[Any]:
        def walk(body: MacroArg, *, items: Optional[Any] = None,
                 level: Optional[int] = 0) -> List[Any]:
            if items is None:
                items = []

            for item in body.items:
                if not isinstance(item, MacroRef):
                    assert isinstance(item, str)
                    # split on whitespace, capturing the whitespace but
                    # discarding any leading or trailing empty strings
                    words = self._split_pattern.split(item)
                    start = 1 if words and not words[0] else None
                    end = -1 if words and not words[-1] else None
                    items.extend(words[start:end])
                elif not item.args:
                    items.append(_MacroRefCall(item.name))
                else:
                    items.append(_MacroRefOpen(item.name, level=level))
                    for i, arg in enumerate(item.args):
                        if i > 0:
                            items.append(_MacroRefArgSep())
                        walk(arg, items=items, level=level+1)
                    items.append(_MacroRefClose(item.name, level=level))

            return items

        self._parse()
        return walk(self._body)

    @property
    def macro_refs(self) -> Dict[Union[str, Tuple[str, int]], MacroRef]:
        self._parse()
        return self._macro_refs

    @property
    def footer(self) -> str:
        return self._footer or ''

    @footer.setter
    def footer(self, value: str):
        self._footer = value

    @property
    def markdown(self) -> Optional[str]:
        return self._markdown

    @markdown.setter
    def markdown(self, value: str):
        self._markdown = value

    def __hash__(self) -> int:
        return hash((self.text, self.footer))

    def __eq__(self, other: Union[None, str, 'Content']) -> bool:
        if not self or not other:  # None, '', or any other False object
            return bool(self)
        elif isinstance(other, str):
            # XXX this doesn't (and can't) consider the footer
            return self.text == other
        elif isinstance(other, Content):
            return (self.text, self.footer) == (other.text, other.footer)
        else:
            raise NotImplementedError

    # this creates a new instance unless it can return 'self' unmodified
    def __add__(self, other: Union[None, str, 'Content']) -> 'Content':
        if not other:  # None, '', or any other False object
            return self
        elif isinstance(other, str):
            # XXX this doesn't consider the footer
            return Content(self.text + other, preprocess=True)
        elif isinstance(other, Content):
            # XXX is this the correct way to handle the footer?
            return Content(self.text + other.text,
                           footer = self.footer + other.footer,
                           preprocess=True)
        else:
            raise NotImplementedError

    # this is to support str + Content
    def __radd__(self, other: Union[None, str]) -> 'Content':
        if not other:  # None, '', or any other False objects
            return self
        elif isinstance(other, str):
            return Content(other + self.text, footer=self._footer,
                           preprocess=True)
        else:
            raise NotImplementedError

    def __bool__(self) -> bool:
        return len(str(self)) > 0

    def __str__(self) -> str:
        # XXX is this the correct way to handle the footer?
        return (self.text + self.footer) or ''

    def __repr__(self) -> str:
        return repr(str(self))
