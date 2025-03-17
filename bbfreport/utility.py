"""Utilities."""

# Copyright (c) 2019-2024, Broadband Forum
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

from __future__ import annotations

import functools
import re
import os.path
import textwrap
import xml.sax.saxutils as saxutils

from collections.abc import Iterable
from typing import Any, Callable, cast

from .logging import Logging

logger = Logging.get_logger(__name__)


# XXX Namespace, Version etc. classes should be moved to (new) types.py
class Namespace:
    """Represents an XML namespace."""

    # dictionary mapping namespace name, e.g.,
    # urn:broadband-forum-org:cwmp:datamodel-1-10, to Namespace instance
    namespaces_by_name: dict[str, Namespace] = {}

    # dictionary mapping sanitized XML attribute name, e.g., 'xmlns_dm', to a
    # sorted list (oldest to newest) of the associated Namespace instances
    namespaces_by_attr: dict[str, list[Namespace]] = {}

    @classmethod
    def get(cls, name: str, *, attr: str | None = None,
            location: str | None = None) -> 'Namespace':
        if not (namespace := cls.namespaces_by_name.get(name, None)):
            namespace = Namespace(name, attr=attr, location=location)
        else:
            if attr is not None:
                namespace.attr = attr
            if location is not None:
                namespace.location = location
        return namespace

    def __init__(self, name: str, *, attr: str | None = None,
                 location: str | None = None):
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
    def attr(self) -> str | None:
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
    def location(self) -> str | None:
        return self._location

    @location.setter
    def location(self, value: str) -> None:
        assert value is not None
        self._location = value

    def __str__(self) -> str:
        return self._name

    __repr__ = __str__


# XXX this isn't really specific to strings; could look into generics, but this
#     might require python3.12
# XXX might this be partly reinventing the standard enum module?
# XXX note that invalid values are silently permitted but will have an index
#     of -1 and therefore are "less than" all other values
# XXX 'level' is a bad name; but is 'index' any better?
# XXX comparisons with strings are supported; is this good or bad?
# XXX perhaps comparison with None should work too, with None being the same
#     as the default value, if there is one, or -1 (see above) otherwise
# XXX should check everywhere (not just im this module) for incorrect usage of
#     NotImplemented / NotImplementedError
@functools.total_ordering
class StrEnum:
    """String enumeration base class."""

    values: tuple[str, ...] = ()

    default: str | None = None

    # instances of different StrEnum subclasses can be compared if they have
    # the same levels (values should be a subset of levels)
    levels: dict[str | None, int] = {}

    @classmethod
    def check(cls, owner: str, name: str) -> None:
        # this is called at module load time so the logging subsystem hasn't
        # yet been configured and error messages won't be prefixed with the
        # logger name and the message severity
        prefix = 'ERROR:%s:' % logger.name

        # check that the default is one of the values
        if cls.default is not None and cls.default not in cls.values:
            logger.error('%s%s: invalid %r default %r' % (
                prefix, owner, name, cls.default))

        # if there are explicit levels, check that the values are a subset
        if cls.levels:
            excess = ', '.join(sorted(set(cls.values) - set(cls.levels)))
            if excess:
                logger.error('%s%s: excess %r value(s) %r (missing from '
                             'levels)' % (prefix, owner, name, excess))

    # argument-less constructor means "default"
    def __init__(self, value: str | None = None):
        self._value = value

    @property
    def defined(self) -> bool:
        return self._value is not None

    @property
    def value(self) -> str | None:
        cls = type(self)
        return self._value or cls.default

    @property
    def levels_(self) -> dict[str | None, int]:
        cls = type(self)
        return cls.levels or \
            {name: level for level, name in enumerate(cls.values)}

    @property
    def level(self) -> int:
        # note use of the 'value' property
        return self.levels_.get(self.value, -1)

    def __lt__(self, other: Any) -> bool:
        cls = type(self)
        if isinstance(other, str):
            other = cls(other)
        elif not isinstance(other, StrEnum) or other.levels_ != self.levels_:
            return NotImplemented
        return self.level < other.level

    def __eq__(self, other: Any) -> bool:
        cls = type(self)
        if isinstance(other, str):
            other = cls(other)
        elif not isinstance(other, StrEnum) or other.levels_ != self.levels_:
            return NotImplemented
        return self.level == other.level

    def __str__(self) -> str:
        # note use of the 'value' property, and fallback to ''
        return self.value or ''

    def __repr__(self) -> str:
        return repr(str(self))


# XXX these classes should be defined elsewhere; some could be local classes
#     in node.py, but others, e.g. Status, need to be globally available

# XXX StatusEnum doesn't really have a default, but with no default the value
#     could be None, so we deal with it; can use .defined when necessary
class StatusEnum(StrEnum):
    values = ('current', 'deprecated', 'obsoleted', 'deleted')
    default = 'current'


class ActionEnum(StrEnum):
    values = ('create', 'prefix', 'append', 'replace')
    default = 'create'


# all Access and Requirement classes share the same levels, so their
# instances can be compared
class _AccessOrRequirementEnum(StrEnum):
    levels = {None: 0, 'notSpecified': 1, 'present': 2, 'readOnly': 2,
              'writeOnceReadOnly': 3, 'create': 4, 'delete': 5,
              'createDelete': 6, 'readWrite': 6}


class ObjectAccessEnum(_AccessOrRequirementEnum):
    values = ('readOnly', 'readWrite')
    default = 'readOnly'


# noinspection PyPep8Naming
class Dt_objectAccessEnum(_AccessOrRequirementEnum):
    values = ('readOnly', 'create', 'delete', 'createDelete')
    default = 'readOnly'


class ParameterAccessEnum(_AccessOrRequirementEnum):
    values = ('readOnly', 'readWrite', 'writeOnceReadOnly')
    default = 'readOnly'


class FacetAccessEnum(_AccessOrRequirementEnum):
    values = ('readOnly', 'readWrite')
    default = 'readWrite'


class ObjectRequirementEnum(_AccessOrRequirementEnum):
    values = ('notSpecified', 'present', 'create', 'delete', 'createDelete')


class ParameterRequirementEnum(_AccessOrRequirementEnum):
    values = ('readOnly', 'readWrite', 'writeOnceReadOnly')


# XXX `none` and `mountable` are deprecated
class MountTypeEnum(StrEnum):
    values = ('none', 'mountable', 'mountPoint')


class ActiveNotifyEnum(StrEnum):
    values = ('normal', 'forceEnabled', 'forceDefaultEnabled', 'canDeny')
    default = 'normal'


# noinspection PyPep8Naming
class Dt_activeNotifyEnum(StrEnum):
    values = ('normal', 'forceEnabled', 'forceDefaultEnabled', 'canDeny',
              'willDeny')
    default = 'normal'


class DefaultTypeEnum(StrEnum):
    values = ('factory', 'object', 'implementation', 'parameter')


# XXX 'absolute' is a non-standard extension
class ScopeEnum(StrEnum):
    values = ('normal', 'model', 'object', 'absolute')
    default = 'normal'


class ReferenceTypeEnum(StrEnum):
    values = ('weak', 'strong')


class NestedBracketsEnum(StrEnum):
    values = ('legacy', 'permitted', 'required')
    default = 'legacy'


# XXX the final value should be a pattern matching user-defined type names
class TargetTypeEnum(StrEnum):
    values = ('any', 'parameter', 'object', 'single', 'table', 'row')
    default = 'any'


class TargetDataTypeEnum(StrEnum):
    values = ('any', 'base64', 'boolean', 'dateTime', 'decimal', 'hexBinary',
              'integer', 'int', 'long', 'string', 'unsignedInt',
              'unsignedLong', 'dataType')
    default = 'any'


@functools.total_ordering
class Version:
    """Represents an m.n[.p] version string."""

    _two_ints = tuple[int, int]
    _three_ints = tuple[int, int, int]

    # a supplied string can be a model name, e.g. Device:2.12 (the prefix,
    # which can actually be anything, is made available in .prefix)
    def __init__(self, tuple_or_text: _two_ints | _three_ints | str, *,
                 prefix: str = ''):
        if isinstance(tuple_or_text, tuple):
            if not (2 <= len(tuple_or_text) <= 3):
                raise ValueError('version %s must have 2 or 3 levels' %
                                 (tuple_or_text,))
            self._prefix = prefix
            self._comps = tuple_or_text + (
                (0,) if len(tuple_or_text) == 2 else ())
        elif not (match := re.match(r'^(.*?)(\d+)\.(\d+)(?:\.(\d+))?$',
                                    tuple_or_text)):
            raise ValueError('version %s is invalid' % tuple_or_text)
        else:
            prefix_, *comps = match.groups()
            self._prefix = prefix_ or prefix
            self._comps = tuple(int(c or '0') for c in comps)

    # note that this returns a NEW instance
    # XXX could return self for out-of-range index
    def reset(self, index: int) -> 'Version':
        comps = list(self._comps)
        if index in range(3):
            comps[index] = 0
        return Version(cast(self._three_ints, tuple(comps)),
                       prefix=self.prefix)

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._comps == other._comps

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._comps < other._comps

    def __add__(self, other: Any) -> 'Version':
        if not isinstance(other, Version):
            return NotImplemented
        comps = cast(self._three_ints,
                     tuple(sum(t) for t in zip(self._comps, other._comps)))
        return Version(comps)

    @property
    def name(self) -> str:
        return self.__str__()

    @property
    def prefix(self) -> str:
        return self._prefix or ''

    @property
    def comps(self) -> _three_ints:
        return cast(self._three_ints, self._comps)

    # the string form doesn't include the prefix (if any), and it omits a zero
    # final component (in accordance with convention)
    def __str__(self) -> str:
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
        # noinspection GrazieInspection
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

    # this ignores 'prefix', 'tr' case, 'label' and 'extension'
    def matches(self, other: Any) -> bool:
        # can only compare objects of the same type
        if not isinstance(other, _SpecOrFileName):
            return NotImplemented

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

    @property
    def is_valid(self) -> bool:
        return self.tr != ''

    @property
    def version(self) -> Version | None:
        return Version((self.i_int, self.a_int, self.c_int)) \
            if self.i != '' else None

    def __str__(self) -> str:
        return self.name

    # this is like __str__() but uses the parsed results and includes some '|'
    # separators
    def __repr__(self) -> str:
        return f'{self.p}{self.tr}|-{self.nnn}|-{self.i}|-{self.a}|' \
               f'-{self.c}|{self.label}|{self.ext}'


class Spec(_SpecOrFileName):
    pass


class FileName(_SpecOrFileName):
    pass


class Utility:
    """Utility class."""

    @staticmethod
    def boolean(value: Any) -> bool:
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
    def flatten_tuple(tup: tuple[Any, ...] | Iterable[Any] | None) -> \
            tuple[Any, ...] | None:
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
    def nice_none(value: Any, none: Any = '') -> str:
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
    def nice_dict(dct: dict, *, prefix: str = '', style: str | None = None,
                  ignore: set | None = None,
                  override: dict | None = None) -> str:
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
    def nice_list(lst: Iterable, *, style: str | None = None,
                  limit: int | None = None) -> str:
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
    def nicer_list(value: list[Any],
                   template: str | Callable[[Any], str] | None = None,
                   exclude: list[str] | None = None, *,
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
                text += template.replace(r'\1', item) if \
                    isinstance(template, str) else template(item)
        return text

    @staticmethod
    def nice_string(value: Any, *, maxlen: int = 70,
                    empty: str | None = None,
                    truncateleft: bool = False, escape: bool = False) -> str:
        """Return value as a "nice" string.

        Args:
            value: The supplied value (it doesn't have to be a string).
            maxlen: Maximum string length to return untruncated.
            empty: Value to use if the string is empty or consists only of
                whitespace (default: the original string in single quotes).
            truncateleft: Whether to truncate (if necessary) on the left.
            escape: Whether to backslash-escape special characters
            (currently only hyphens).

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
                value_ = empty if empty is not None else repr(value)
            elif length > maxlen:
                if not truncateleft:
                    value_ = value_[:maxlen].strip() + '...'
                else:
                    value_ = '...' + value_[-maxlen:].strip()
            if escape:
                value_ = re.sub(r'-', r'\-', value_)
            return value_

    @staticmethod
    def path_split_drive(path: str) -> tuple[str, str, str]:
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
    def path_nameonly(path: str) -> str:
        """Split a file path, returning only the name part without an
        extension.

        Args:
            path: The supplied path.

        Returns:
            Name part without an extension.
        """

        *_, file = Utility.path_split_drive(path)
        file, _ = os.path.splitext(file)
        return file

    @staticmethod
    def whitespace(inval: str | None) -> str | None:
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

            # replace >= 2 newlines with 2 newlines
            outval = re.sub(r'\n{2,}', r'\n\n', outval)

            # remove any trailing whitespace (necessary to avoid polluting the
            # common leading whitespace length)
            outval = re.sub(r'\s*$', r'', outval)

            # remove common leading whitespace
            outval = textwrap.dedent(outval)
        return outval

    # XXX this was added, but was then never used
    @classmethod
    def _scandir(cls, dir_: str, *,
                 pattern: re.Pattern[str] | None = None) -> list[str]:
        paths: list[str] = []
        for dirpath, _, filenames in os.walk(dir_, followlinks=True):
            for filename in filenames:
                path = os.path.join(dirpath, filename)
                # noinspection PyTypeChecker
                if pattern is None or re.search(pattern, path):
                    paths += [path]
        return paths

    # XXX this was added, but was then never used
    @classmethod
    def _scandirs(cls, dirs: list[str], *,
                  pattern: re.Pattern[str] | None = None) -> list[str]:
        paths = []
        for dir_ in dirs:
            print(dir_)
            paths += cls._scandir(dir_, pattern=pattern)
        return paths

    @staticmethod
    def class_hierarchy(root_or_roots: type | tuple[type, ...],
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

        def add_class(cls: type, visited: list[type], *,
                      level: int = 0) -> None:
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
