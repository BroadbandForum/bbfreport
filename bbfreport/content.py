"""Content utilities."""

# Copyright (c) 2022-2024, Broadband Forum
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

import re

from functools import cache
from typing import Any, Optional, Union

from .logging import Logging

logger = Logging.get_logger(__name__)

# Note that description templates such as {{param}} are always referred to as
# macros, to avoid any confusion with <template> XML elements

# the opening of the standard {{div}} macro that is used for each paragraph
# XXX these would be better as functions supporting optional additional classes
OPEN_DIV = '{{div|{{classes}}|'
CLOSE_DIV = '}}'


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
                 chunks: list[Union[str, '_MacroRefArgSep', 'MacroRef']]):
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
                assert arg is not None, 'missing }'
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
    def args(self) -> tuple['MacroArg', ...]:
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
    def items(self) -> list[Union[str, MacroRef]]:
        return self._items

    # XXX should extend this to work for complex args too; it should
    #     always return the original text from the macro reference
    @property
    def text(self) -> Optional[str]:
        return self._items[0] if self.is_simple and self._items else None

    # XXX but until the above has been done, fall back on
    def __str__(self):
        return self.text or str(self._items)

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
        (?P<sep>\s*)
        (?P<rst>.*)
        $
        ''', flags=re.VERBOSE)

    _indent_re = re.compile(r'^(\s+)')

    # this URL regex is essentially copied from report.pl
    _url_last = r'\w\d\:\~\/\?\&\=\-\%\#'
    _url_not_last = _url_last + r'\.'
    _url_re = re.compile(r'[a-z]+://[' + _url_not_last + r']*[' +
                         _url_last + r']')
    del _url_last, _url_not_last

    # the supplied text may contain mediawiki markup as defined in TR-106a13
    # and earlier, e.g.
    # (https://data-model-template.broadband-forum.org/index.htm#sec:markup);
    # this is quite similar (but not identical) to markdown, so convert to
    # something more markdown-like
    # XXX it also wraps paragraphs in {{div}} macro references
    @classmethod
    def _preprocess_text(cls, text: Optional[str], *, warning, info, debug,
                         **_kwargs) -> Optional[str]:
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
            debug('escape: %r -> %r' % (orig, text))

        # XXX Content + str etc. use '{{np}}' as a separator, but this mucks
        #     up the {{div}} logic below, so (temporarily) replace it
        if '{{np}}' in text:
            text = text.replace('{{np}}', '\n\n')

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
                # XXX mediawiki allows things like '#:' to continue a level 1
                #     item, but this will be treated the same as '##'
                typ, sep, rst = match['typ'], match['sep'], match['rst']
                if len(typ) == 0:
                    pass
                # ignore '*' and '#' lines with no separators; the '*'
                # might indicate emphasis and the '#' might be part of
                # a path reference
                elif typ[0] in {'*', '#'} and sep == '':
                    pass
                else:
                    # even though '*' and '#' are similar (':' is different),
                    # it's clearer to handle each one separately
                    typ0 = typ[0]
                    np = ''
                    if typ0 == '*':
                        # replace '** ' with '  * ' etc.
                        typ = '%s%s' % ('  ' * (len(typ) - 1), typ0)
                    elif typ0 == '#':
                        # replace '# ', '## ' with '1. ', '   1. ' etc.
                        # XXX use '1. '; '#. ' doesn't work with commonmark_x
                        typ0 = '1.'
                        typ = '%s%s' % ('   ' * (len(typ) - 1), typ0)
                    else:
                        assert typ0 == ':'
                        np = '{{np}}'
                        typ = '>' * len(typ)
                        msg += ' indented -> block quote'
                    if len(typ) > 1:
                        msg += ' nested list'

                    # update the line
                    # XXX could put more info into the {{li}} macro, e.g. depth
                    line = '%s{{li|%s}}%s' % (np, typ, rst)

            # warn of insufficiently (or erroneously) indented text
            # (don't try to fix it; there are too many cases to consider)
            if match := cls._indent_re.match(line):
                # there shouldn't be any tabs, but if there are, expand them
                # (the tab size defaults to 8)
                indent = match.group(1).expandtabs()
                if len(indent) < 4:
                    func = info if block_active else warning
                    func('increase indent %d to 4 (or remove it): %r' % (
                        len(indent), line))

            # replace ''' with ** (strong) and '' with * (emphasis)
            if "'''" in line:
                line = line.replace("'''", "**")
                msg += ' strong'
            if "''" in line:
                line = line.replace("''", "*")
                msg += ' emphasis'

            # identify URLs and enclose them in <> characters
            line = cls._url_re.sub(r'<\g<0>>', line)

            # report changed lines
            if line != orig:
                debug('%s: %r -> %r' % (msg, orig, line))

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
                text += OPEN_DIV
            if line:
                text += line + '{{nl}}'
        # XXX this isn't 100% safe, but it's OK if {{nl}} is never documented
        text = text.replace('{{nl}}}}', '}}')
        return text

    def _parse(self, *, error, warning, info, debug, **_kwargs) -> None:
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
        # XXX the check for OPEN_DIV is rather a hack; it's to prevent multiple
        #     levels of wrapping in divs, which causes problems with diffs
        preprocess = self._preprocess and not (
                self._text and self._text.startswith(OPEN_DIV))
        self._mrkdwn = self._preprocess_text(self._text, error=error,
                                             warning=warning, info=info,
                                             debug=debug) if \
            preprocess else self._text

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
            # noinspection GrazieInspection
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
        assert len(stack) == 1 and len(stack[0]) == 1, 'corrupt stack'
        macro_ref = stack[-1][0]
        assert isinstance(macro_ref, MacroRef), 'corrupt stack'

        # furthermore, the macro reference has a single argument
        assert len(macro_ref.args) == 1, 'corrupt stack'

        # the content body is this argument
        self._body = macro_ref.args[0]
        self._parsed = True

    @property
    def text(self) -> str:
        return self._text or ''

    @property
    def preprocess(self) -> bool:
        return self._preprocess

    # this supports passing logging functions
    def get_body(self, *, error=None, warning=None, info=None, debug=None) \
            -> MacroArg:
        if error is None:
            error = logger.error
        if warning is None:
            warning = logger.warning
        if info is None:
            info = logger.info
        if debug is None:
            debug = logger.debug
        try:
            self._parse(error=error, warning=warning, info=info, debug=debug)
        except AssertionError as e:
            error('%s in %s' % (e, str(self).replace('\n', r'\n')))
        return self._body

    @property
    def body(self) -> MacroArg:
        return self.get_body()

    # split on whitespace
    # XXX it's tempting to add some punctuation characters such as '.', but
    #     there are unintended consequences, such as splitting paths and
    #     versions; either don't bother or else make the regex more complex
    _split_pattern = re.compile(r'(\s+)')

    # this is intended for use when comparing content
    # this supports collapsing whitespace etc. and passing logging functions
    @cache
    def get_body_as_list(self, *, collapse: bool = False, error=None,
                         warning=None, info=None, debug=None) -> list[Any]:
        if error is None:
            error = logger.error
        if warning is None:
            warning = logger.warning
        if info is None:
            info = logger.info
        if debug is None:
            debug = logger.debug

        def walk(body: MacroArg, *, items: Optional[Any] = None,
                 level: Optional[int] = 0) -> list[Any]:
            if items is None:
                items = []

            for i, item in enumerate(body.items):
                if not isinstance(item, MacroRef):
                    assert isinstance(item, str)
                    # split on whitespace, capturing the whitespace but
                    # discarding any leading or trailing empty strings
                    words = self._split_pattern.split(item)
                    start = 1 if words and not words[0] else None
                    end = -1 if words and not words[-1] else None
                    items.extend(words[start:end])
                elif collapse and item.name == 'nl':
                    if i > 0:
                        # {{nl}} is a soft newline
                        items.append(' ')
                elif collapse and item.name == 'np':
                    if i > 0:
                        # {{np}} is a paragraph separator
                        items.append('\n\n')
                elif not item.args:
                    items.append(_MacroRefCall(item.name))
                else:
                    items.append(_MacroRefOpen(item.name, level=level))
                    for j, arg in enumerate(item.args):
                        if j > 0:
                            items.append(_MacroRefArgSep())
                        walk(arg, items=items, level=level+1)
                    items.append(_MacroRefClose(item.name, level=level))

            # if collapsing, combine adjacent space items
            if collapse:
                new_items = []
                space = ''
                for item in items:
                    if isinstance(item, str) and re.match(r' +', item):
                        space = ' '
                        continue

                    # special case: always put '\n\n' before list items
                    # (this matches what the xml format currently does)
                    if str(item) == 'open(li)':
                        space = '\n\n'

                    if space:
                        new_items.append(space)
                        space = ''

                    new_items.append(item)

                items = new_items

            return items

        self._parse(error=error, warning=warning, info=info, debug=debug)
        return walk(self._body)

    # this is intended for use when comparing content
    @property
    def body_as_list(self) -> list[Any]:
        return self.get_body_as_list()

    # this supports passing logging functions
    @cache
    def get_macro_refs(self, *, error=None, warning=None, info=None,
                       debug=None) -> \
            dict[Union[str, tuple[str, int]], MacroRef]:
        if error is None:
            error = logger.error
        if warning is None:
            warning = logger.warning
        if info is None:
            info = logger.info
        if debug is None:
            debug = logger.debug
        try:
            self._parse(error=error, warning=warning, info=info, debug=debug)
        except AssertionError as e:
            error('%s in %s' % (e, str(self).replace('\n', r'\n')))
        return self._macro_refs

    @property
    def macro_refs(self) -> dict[Union[str, tuple[str, int]], MacroRef]:
        return self.get_macro_refs()

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
                           footer=self.footer + other.footer,
                           preprocess=True)
        else:
            raise NotImplementedError

    # this is to support str + Content
    # XXX if content starts with OPEN_DIV, then str is inserted after it (this
    #     is rather tricky)
    def __radd__(self, other: Union[None, str]) -> 'Content':
        if not other:  # None, '', or any other False objects
            return self
        elif isinstance(other, str):
            if not self.text.startswith(OPEN_DIV):
                text = other + self.text
            else:
                text = OPEN_DIV + other + self.text[len(OPEN_DIV):]
            return Content(text, footer=self._footer, preprocess=True)
        else:
            raise NotImplementedError

    def __bool__(self) -> bool:
        return len(str(self)) > 0

    def __str__(self) -> str:
        # XXX is this the correct way to handle the footer?
        return (self.text + self.footer) or ''

    def __repr__(self) -> str:
        return repr(str(self))
