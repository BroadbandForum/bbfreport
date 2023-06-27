"""Utilities."""

# Copyright (c) 2019-2023, Broadband Forum
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

import functools
import logging
import re
import os.path
import textwrap
import xml.sax.saxutils as saxutils

from typing import Any, Callable, cast, Iterable, List, Optional, Tuple, Union

logger_name = __name__.split('.')[-1]
logger = logging.getLogger(logger_name)
logger.addFilter(
        lambda r: r.levelno > 20 or logger_name in Utility.logger_names)


# XXX Namespace, Version etc. classes should be moved to (new) types.py


class Namespace:
    """Represents an XML namespace."""

    # dictionary mapping namespace name, e.g.,
    # urn:broadband-forum-org:cwmp:datamodel-1-10, to Namespace instance
    namespaces_by_name = {}

    # dictionary mapping sanitized XML attribute name, e.g., 'xmlns_dm', to a
    # sorted list (oldest to newest) of the associated Namespace instances
    namespaces_by_attr = {}

    @classmethod
    def get(cls, name: str, *, attr: Optional[str] = None,
            location: Optional[str] = None) -> 'Namespace':
        if not (namespace := cls.namespaces_by_name.get(name, None)):
            namespace = Namespace(name, attr=attr, location=location)
        else:
            if attr is not None:
                namespace.attr = attr
            if location is not None:
                namespace.location = location
        return namespace

    def __init__(self, name: str, *, attr: Optional[str] = None,
                 location: Optional[str] = None):
        assert name not in self.namespaces_by_name
        self._name = name
        self._attr = None
        self._location = None
        self.namespaces_by_name[name] = self

        # these are property accessors
        if attr is not None:
            self.attr = attr  # this updates namespaces_by_attr
        if location is not None:
            self.location = location

    @property
    def name(self) -> str:
        return self._name

    @property
    def attr(self) -> Optional[str]:
        return self._attr

    # XXX there's no namespaces_by_attr cleanup if attr is changed
    @attr.setter
    def attr(self, value: str) -> None:
        assert value is not None
        self._attr = value
        self.namespaces_by_attr.setdefault(value, [])
        if self not in self.namespaces_by_attr[value]:
            # the sort key is formed by splitting on '-' and converting
            # all-numeric tokens to integers
            def key(ns: Namespace):
                comps = ns.name.split('-')
                comps = [int(comp) if comp.isdigit() else
                         comp for comp in comps]
                return comps

            self.namespaces_by_attr[value] = sorted(
                    self.namespaces_by_attr[value] + [self], key=key)

    @property
    def location(self) -> Optional[str]:
        return self._location

    @location.setter
    def location(self, value: str) -> None:
        assert value is not None
        self._location = value

    def __str__(self):
        return self._name

    __repr__ = __str__


@functools.total_ordering
class Status:
    # status-related constants; the values are assumed to be defined in
    # increasing 'deprecation order'
    default = 'current'
    names = (default, 'deprecated', 'obsoleted', 'deleted')
    level_names = {level: name for level, name in enumerate(names)}
    name_levels = {name: level for level, name in enumerate(names)}

    def __init__(self, name: Optional[str] = None):
        assert name is None or name in self.names
        self._name = name

    @property
    def defined(self) -> bool:
        return self._name is not None

    @property
    def name(self) -> str:
        return self._name or self.default

    @property
    def level(self) -> str:
        return self.name_levels[self.name]

    def __lt__(self, other: 'Status') -> bool:
        if not isinstance(other, Status):
            raise NotImplementedError
        return self.name_levels[self.name] < self.name_levels[other.name]

    def __eq__(self, other: 'Status') -> bool:
        if not isinstance(other, Status):
            raise NotImplementedError
        return self.name_levels[self.name] == self.name_levels[other.name]

    def __str__(self) -> str:
        return self.name

    __repr__ = __str__


@functools.total_ordering
class Version:
    """Represents an m.n[.p] version string."""

    def __init__(self, tuple_or_text: Union[Tuple[int, int, int], str], *,
                 levels: int = 2):
        assert levels in {2, 3}
        if isinstance(tuple_or_text, tuple):
            assert len(tuple_or_text) == 3
            self._comps = list(tuple_or_text)
        # XXX should check that the regex honors the levels argument
        elif not (match := re.match(r'^(\d+)\.(\d+)(?:\.(\d+))?$',
                                    tuple_or_text)):
            raise ValueError('%s is not m.n[.p]' % tuple_or_text)
        else:
            self._comps = [int(g) for g in match.groups('0')]

    # note that this returns a NEW instance
    def reset(self, what: Optional[Union[int, Tuple[int, ...]]] = None) -> \
            'Version':
        comps = self._comps[:]
        indices = (what,) if isinstance(what, int) else what if isinstance(
                what, tuple) else (0, 1, 2)
        assert len(indices) <= 3 and all(0 <= i <= 2 for i in indices)
        for index in indices:
            comps[index] = 0
        comps = cast(Tuple[int, int, int], tuple(comps))
        return Version(tuple(comps))

    def __eq__(self, other: 'Version') -> bool:
        if not isinstance(other, Version):
            raise NotImplementedError
        return self._comps == other._comps

    def __lt__(self, other: 'Version') -> bool:
        if not isinstance(other, Version):
            raise NotImplementedError
        return self._comps < other._comps

    def __add__(self, other: 'Version') -> 'Version':
        if not isinstance(other, Version):
            raise NotImplementedError
        comps = cast(Tuple[int, int, int],
                     tuple(sum(t) for t in zip(self._comps, other._comps)))
        return Version(comps)

    @property
    def name(self) -> str:
        return self.__str__()

    @property
    def comps(self) -> Tuple[int, int, int]:
        return cast(Tuple[int, int, int], tuple(self._comps))

    def __str__(self):
        last = 3 if self._comps[2] > 0 else 2
        return '.'.join(str(c) for c in self._comps[:last])

    __repr__ = __str__


class _SpecOrFileName:
    """Represents a spec or file attribute."""

    # regex used for matching file names and specs
    # XXX maybe shouldn't use the same pattern for both files and specs?
    _re_file_spec = re.compile(r'''
        ^                    # start of string
        (?P<p>.*?)           # spec prefix (empty for file)
        (?P<tr>\w+)          # type, e.g. 'tr'
        -(?P<nnn>\d+)        # hyphen then number, e.g. '069'
        (?:-(?P<i>\d+))?     # hyphen then issue, e.g. '1'
        (?:-(?P<a>\d+))?     # hyphen then amendment, e.g. '2'
        (?:-(?P<c>\d+))?     # hyphen then corrigendum, e.g. 3'
        (?P<label>-\D[^.]*)? # label (hyphen then non-digit etc.; no dots)
        (?P<ext>\..*)?       # file extension (starting with dot)
        $                    # end of string
    ''', re.VERBOSE)

    # This is based on the publish.pl parse_file_name function
    def __init__(self, name: str = ''):
        """Parse a name (file or spec) into its constituent parts.

        These are all strings:

        * ``p`` (spec prefix; empty for file)
        * ``tr`` (document type; typically ``tr``)
        * ``nnn`` (document number)
        * ``i`` (issue number; default empty)
        * ``a`` (amendment number; default empty)
        * ``c`` (corrigendum number; default empty)
        * ``label`` (if present, includes leading hyphen; default empty)
        * ``extension`` (if present, includes leading dot; default empty)

        Args:
            name:
        """

        self.name = name

        # these are all strings, and they all default to ''
        if not (match := self._re_file_spec.match(name) if name else None):
            self.p, self.tr, self.nnn, self.i, self.a, self.c, self.label, \
                self.ext = 8 * ('', )
        else:
            self.p, self.tr, self.nnn, self.i, self.a, self.c, self.label, \
                self.ext = (v or '' for v in match.groups())

        # these are integer versions of nnn, i, a and c, with suitable defaults
        # (these are used when comparing instances)
        self.nnn_int = int(self.nnn) if self.nnn != '' else 0
        self.i_int = int(self.i) if self.i != '' else 1
        self.a_int = int(self.a) if self.a != '' else 0
        self.c_int = int(self.c) if self.c != '' else 0

    @property
    def is_valid(self) -> bool:
        return self.tr != ''

    # this ignores 'prefix', 'tr' case, 'label' and 'extension'
    def matches(self, other: '_SpecOrFileName') -> bool:
        # can only compare objects of the same type
        if not isinstance(other, _SpecOrFileName):
            raise NotImplementedError

        # only versions of the same document can match
        if (self.tr.lower(), self.nnn_int) != \
                (other.tr.lower(), other.nnn_int):
            return False

        # otherwise (i, a, c)  must match
        other_i_int = other.i_int if other.i != '' else self.i_int
        other_a_int = other.a_int if other.a != '' else self.a_int
        other_c_int = other.c_int if other.c != '' else self.c_int
        return (self.i_int, self.a_int, self.c_int) == \
            (other_i_int, other_a_int, other_c_int)

    def __str__(self):
        return self.name

    # this is like __str__() but uses the parsed results and includes some '|'
    # separators
    def __repr__(self):
        return f'{self.p}{self.tr}|-{self.nnn}|-{self.i}|-{self.a}|' \
               f'-{self.c}|{self.label}|{self.ext}'


class Spec(_SpecOrFileName):
    pass


class FileName(_SpecOrFileName):
    pass


class Utility:
    """Utility class."""

    # XXX applications can update this
    # XXX should have a logging-specific module?
    logger_names = set()
    """Logger names."""

    @staticmethod
    def boolean(value: Union[bool, str, Any]) -> bool:
        """Convert the argument to a bool.

        Args:
            value: bool, string ``true`` or ``1`` (which are ``True``),
            string ``false`` or ``0`` (which are ``False``) or anything
            else, which will be converted using standard Python rules.

        Returns:
            Boolean value derived as described above.
        """

        if isinstance(value, bool):
            return value
        # these are the XML True values
        elif isinstance(value, str) and value in {'true', '1'}:
            return True
        # these are the XML False values
        elif isinstance(value, str) and value in {'false', '0'}:
            return False
        else:
            return bool(value)

    @staticmethod
    def lower_first(text: str) -> str:
        """Convert the first character to lower case.

        Args:
            text: Supplied string.

        Returns:
            String with the first character converted to lower case.
        """
        return text[:1].lower() + text[1:]

    @staticmethod
    def upper_first(text: str) -> str:
        """Convert the first character to upper case.

        Args:
            text: Supplied string.

        Returns:
            String with the first character converted to upper case.
        """
        return text[:1].upper() + text[1:]

    @staticmethod
    def clean_name(name: str) -> str:
        """Clean an attribute or element name, ensuring that it's a valid
        Python identifier.

        Currently, this just replaces colons with underscores,
        e.g. ``dm:document`` becomes ``dm_document``.

        Args:
            name: The supplied name.

        Returns:
            The clean name.
        """

        return name.replace(':', '_')

    @staticmethod
    def flatten_tuple(tup: Union[None, Tuple, Any]) -> Optional[Tuple]:
        """Flatten a possibly nested tuple.

        Args:
            tup: Supplied tuple. Can be ``None`` or a non-tuple, but if
            it's a tuple it can't be empty.

        Returns:
            ``None`` if given ``None`` or ``(str(input),)`` if not given a
            tuple, or the supplied tuple with its first element flattened
            (if the first element is a tuple).

        Note:
            1. Despite the name, this is not a general-purpose tuple
               flattener. It's primarily aimed at flattening node keys and
               makes various assumptions.
            2. It would be useful also to check that (if supplied a tuple)
               none of its items are ``None``. This would catch several
               possible `_Node.calckey()` errors.
        """

        if tup is None:
            return None
        elif not isinstance(tup, tuple):
            assert tup is not None
            return str(tup),
        else:
            assert len(tup) > 0
            assert tup[-1] is not None
            if not isinstance(tup[0], tuple):
                return tup
            else:
                return tup[0] + tup[1:]

    # note that this always returns a string
    @staticmethod
    def nice_none(value, none: Any = '') -> str:
        """Return the argument or a "nice" representation of ``None``.

        Args:
            value: The value.
            none: What to return if the value is ``None``.

        Returns:
            The value or the ``none`` value, converted a string.
        """

        return str(none if value is None else value)

    @staticmethod
    def collapse(value: str) -> str:
        """Format the supplied value as a collapsed string.

        Args:
            value: The supplied value.

        Returns:
            The value with all whitespace sequences replaced with a single
            space, and with leading and trailing whitespace stripped.
        """

        assert isinstance(value, str)
        return re.sub(r'\s+', r' ', value).strip()

    @staticmethod
    def pluralize(text: str) -> str:
        """Split words in lower-to-upper transitions."""

        # XXX maybe this shouldn't be unconditional
        text = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', text)

        # hack some names for which this doesn't work
        if re.match(r'^[A-Z]+Address', text):
            text = text.replace('Address', ' Address')

        # add the suffix
        suffix = 'es' if text.lower().endswith('s') else 's'
        text += suffix
        return text

    @staticmethod
    def xmlattrname(name: str) -> str:
        """Format the supplied name as an XML attribute name.

        Args:
            name: The supplied name.

        Returns:
            The name with underscores converted to colons.
        """

        assert isinstance(name, str)
        return name.replace('_', ':')

    @staticmethod
    def xmlattrescape(value: str) -> str:
        """Escape the supplied value ready for use in an XML attribute
        value.

        Args:
            value: The supplied value.

        Returns:
            The value with special characters escaped, but with named entity
            references left unchanged.
        """

        assert isinstance(value, str)
        value = saxutils.escape(value, {"'": '&apos;', '"': '&quot;'})
        # entity reference '&name;' becomes '&amp;name;', so change it back
        if value.find('&amp;') >= 0:
            value = re.sub(r'(&amp;)(\w+)(;)', r'&\g<2>\g<3>', value)
        return value

    @staticmethod
    def xmlattrvalue(value: str) -> str:
        """Format the supplied value as an XML attribute value.

        Args:
            value: The supplied value.

        Returns:
            The collapsed, escaped value surrounded by double quotes.
        """

        assert isinstance(value, str)
        value = Utility.collapse(value)
        value = Utility.xmlattrescape(value)
        return '"' + value + '"'

    @staticmethod
    def xmlelemescape(value: str) -> str:
        """Escape the supplied value ready for use in an XML element
        value.

        Args:
            value: The supplied value.

        Returns:
            The value with special characters escaped, but with comments left
            unchanged.
        """

        # XXX can there be entity references in element values?
        value = saxutils.escape(value)
        # comment '<!--text-->' becomes '&lt;!--text--&gt;', so change it back
        if value.find('&lt;!--') >= 0:
            value = re.sub(r'(&lt;)(!--.*?--)(&gt;)', r'<\g<2>>', value,
                           flags=re.DOTALL)
        return value

    @staticmethod
    def xmlelemvalue(value: str) -> str:
        """Format the supplied value as an XML element value.

        Args:
            value: The supplied value.

        Returns:
            The escaped value.
        """

        assert isinstance(value, str)
        value = Utility.xmlelemescape(value)
        return value

    @staticmethod
    def nice_dict(dct: dict, *, prefix: str = '', style: Optional[str] = None,
                  ignore: Optional[set] = None,
                  override: Optional[dict] = None) -> str:
        """Format a dictionary as a "nice" string.

        The style determines the following::

            ldelim : left delimiter (follows the prefix)
            isep   : item separator
            kfunc  : single-argument key mapping function
            kvsep  : (key, value) separator
            vfunc  : single-argument value mapping function
            rdelim : right delimiter (at the end of the returned string)

        These are the supported styles::

            bare    : ('',  ', ', str,         ' ',  collapse,     '' )
            csv     : ('',  ', ', str,         '=',  collapse,     '' )
            keys    : ('{', ', ', str,         '',   lambda v: '', '}')
            xml     : ('',  ' ',  xmlattrname, '=',  xmlattrvalue, '' )
            default : ('{', ', ', repr,        ': ', repr,         '}')

        If an invalid style name is given, the default style is used.

        Args:
            dct: The supplied dictionary.
            prefix: Text to insert at the beginning of the returned string.
            style: The output style name (see above).
            ignore: Keys to ignore.
            override: Maps keys to overridden values.

        Returns:
            The nicely formatted dictionary.
        """

        ignore = ignore or set()
        override = override or {}
        ldelim, isep, kfunc, kvsep, vfunc, rdelim = {
            'bare': ('', ', ', str, ' ', Utility.collapse, ''),
            'csv': ('', ', ', str, '=', Utility.collapse, ''),
            'keys': ('{', ', ', str, '', lambda v: '', '}'),
            'xml': ('', ' ', Utility.xmlattrname, '=', Utility.xmlattrvalue,
                    '')
        }.get(style, ('{', ', ', repr, ': ', repr, '}'))
        return prefix + ldelim + isep.join(
                [f'{kfunc(k)}{kvsep}{vfunc(override.get(k, v))}' for k, v in
                 dct.items() if k not in ignore]) + rdelim

    @staticmethod
    def nice_list(lst: Iterable, *, style: Optional[str] = None,
                  limit: Optional[int] = None) -> str:
        """Format a list as a "nice" string.

        The style determines the following::

            ldelim : left delimiter (at the beginning of the returned string)
            sep    : item separator
            func   : single-argument value mapping function
            rdelim : right delimiter (at the end of the returned string)

        These are the supported styles::

            argparse : ('',  ', ', repr, '')
            bare     : ('',  ', ', str,  '')
            compact  : ('[', ',',  str,  ']')
            repr     : ('[', ', ', repr, ']')
            default  : ('[', ', ', str,  ']')

        If an invalid style name is given, the default style is used.

        Args:
            lst: The supplied list.
            style: The output style name (see above).
            limit: The maximum number of items to return, or ``None``.

        Returns:
            The nicely formatted list, with ``...`` before the right delimiter
            if not all items are returned.
        """

        # it might be dict_keys or something like that
        if not isinstance(lst, list):
            lst = list(lst)
        ldelim, sep, func, rdelim = {
            'argparse': ('', ', ', repr, ''),
            'bare': ('', ', ', str, ''),
            'compact': ('[', ',', str, ']'),
            'repr': ('[', ', ', repr, ']')
        }.get(style, ('[', ', ', str, ']'))
        term = sep + '...' if limit is not None and len(lst) > limit else ''
        return ldelim + sep.join(
                [func(i) for i in lst[:limit]]) + term + rdelim

    # Convert list to string of the form 'a, b and c', optionally supplying
    # template that's either a string containing '\1' to be substituted for
    # each item or else a callable with an item argument that returns a string.
    # XXX could potentially combine this with nice_list()
    # XXX should use '%s' or similar rather than '\1'?
    @staticmethod
    def nicer_list(value: List[Any],
                   template: Optional[Union[str, Callable[[Any], str]]] = None,
                   exclude: Optional[List[str]] = None, *,
                   last: str = 'and') -> str:
        if template is None:
            template = r'\1'
        if exclude is None:
            exclude = []

        # 'last' normally has a space added before and after it, but no
        # leading space is added if it starts with a comma
        # XXX could extend this for checking for leading/trailing whitespace
        last = '%s%s ' % ('' if last.startswith(',') else ' ', last)

        text = ''
        for i, item in enumerate(value):
            if item not in exclude:
                if text != '':
                    text += ', ' if i < len(value) - 1 else last
                text += item if template is None else \
                    template.replace(r'\1', item) if \
                    isinstance(template, str) else \
                    cast(Callable, template)(item)
        return text

    @staticmethod
    def nice_string(value: Any, *, maxlen: int = 70,
                    truncateleft: bool = False) -> str:
        """Return value as a "nice" string.

        Args:
            value: The supplied value (it doesn't have to be a string).
            maxlen: Maximum string length to return untruncated.
            truncateleft: Whether to truncate (if necessary) on the left.

        Returns:
            ``str(value)`` if value isn't a string; otherwise a nicely
            formatted value, truncated if necessary, with spaces replaced
            with hyphens, and with truncation indicated by ``...``.
        """

        if not isinstance(value, str):
            return str(value)
        else:
            # XXX hyphens look bad; let's use spaces
            value_ = re.sub(r'\s+', ' ', value.strip())
            length = len(value_)
            if length == 0:
                value_ = repr(value)
            elif length > maxlen:
                if not truncateleft:
                    value_ = value_[:maxlen].strip() + '...'
                else:
                    value_ = '...' + value_[-maxlen:].strip()
            return value_

    @staticmethod
    def path_split_drive(path: str) -> Tuple[str, str, str]:
        """Split a file path into drive, directory and name.

        Args:
            path: The supplied path.

        Returns:
            Drive, directory and name.
        """

        drive, path_ = os.path.splitdrive(path)
        dir_, name = os.path.split(path_)
        return drive, dir_, name

    @staticmethod
    def whitespace(inval: Optional[str]) -> Optional[str]:
        """Perform standard whitespace processing on a string.

        This is similar to the old report tool's string preprocessing::

            Expand tabs (assuming 8-character tab stops).
            Remove leading whitespace up to and including the first line break.
            Remove trailing whitespace from each line.
            Remote all trailing whitespace (including line breaks).
            Remove the longest common whitespace prefix from each line.

        Note:
            Why not just remove all leading whitespace, i.e., treat it the
            same as trailing whitespace?

        Args:
            inval: The supplied string, or ``None``.

        Returns:
            ``None`` if ``None`` was supplied, or otherwise the processed
            string.
        """

        outval = inval
        if outval is not None:
            # there shouldn't be any tabs, but (arbitrarily) replace them with
            # eight spaces
            outval = outval.expandtabs(tabsize=8)

            # remove any leading whitespace up to and including the first line
            # break
            outval = re.sub(r'^ *\n', r'', outval)

            # remove any trailing whitespace from each line
            outval = re.sub(r' *\n', r'\n', outval)

            # remove any trailing whitespace (necessary to avoid polluting the
            # prefix length)
            # XXX I don't understand this comment
            outval = re.sub(r'\s*$', r'', outval)

            # remove common leading whitespace
            outval = textwrap.dedent(outval)
        return outval

    # XXX this was added, but was then never used
    @classmethod
    def _scandir(cls, dir_, *, pattern=None):
        paths = []
        for dirpath, dirnames, filenames in os.walk(dir_, followlinks=True):
            for filename in filenames:
                path = os.path.join(dirpath, filename)
                if pattern is None or re.search(pattern, path):
                    paths += [path]
        return paths

    # XXX this was added, but was then never used
    @classmethod
    def _scandirs(cls, dirs, *, pattern=None):
        paths = []
        for dir_ in dirs:
            print(dir_)
            paths += cls._scandir(dir_, pattern=pattern)
        return paths

    @staticmethod
    def class_hierarchy(root_or_roots: Union[type, Tuple[type, ...]],
                        *, title: str = 'Class hierarchy') -> str:
        """Format and return the class hierarchy.

        Args:
            root_or_roots: Root or roots of the class hierarchy.
            title: Title string. Will be inserted as a heading followed by
                a line of ``=`` characters.

        Returns:
            Sphinx ReStructured Text string.
        """

        roots = root_or_roots if isinstance(root_or_roots, tuple) else (
            root_or_roots,)

        lines = ['', '', title, len(title) * '=', '', '.. parsed-literal::',
                 '']

        def add_class(cls, visited, *, level=0):
            # regard all subclasses but this one and visited ones as mixins
            mixins = [node_class for node_class in cls.mro() if
                      node_class is not cls and node_class not in visited]

            # but never report both a mixin and one of its super-classes
            mixins = [mixin for mixin in mixins
                      if not any(mixin in m.mro()[1:] for m in mixins)]

            prefix = '    '
            indent = ' ' + level * '    '
            mixins_ = ' (%s)' % ', '.join('`%s`' % m.__name__ for m in
                                          mixins) if mixins else ''

            nonlocal lines
            lines += ['%s%d%s`%s`%s' % (prefix, level, indent, cls.__name__,
                                        mixins_)]
            for subclass in cls.__subclasses__():
                add_class(subclass, visited + [cls], level=level + 1)

        # treat the supplied class's super-classes as already visited
        for root in roots:
            add_class(root, root.mro())

        return '\n'.join(lines)
