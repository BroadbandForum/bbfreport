"""Node property (attribute and element) classes.

Every node attribute and element is modeled by a `Property` instance. The
node attribute or element value is the property value.

* For node attributes, the property value has a simple type such as ``bool``,
  ``int``, or ``str``. Less commonly, the type can also be ``dict`` or
  ``list``.

* For node elements, the property value is *always* a node or a list of nodes.

As explained under `PropDescr`, these `Property` instances are created on
demand (when a value needs to be set). A typical node supports a large
number of properties but only a few are explicitly set. It turns out that
this approach saves a lot of time and space.

Each `Property` instance is associated with a property `Holder`. A holder
maintains an ordered list of property values. Attributes are stored in an
`Attrs` holder, and elements are stored in an `Elems` holder.

Note:
    We're overloading terms here! Unless otherwise stated, ``property``
    refers to this module's `Property` and not to a python property. A
    similar problem exists with the term ``attribute``. We'll try to avoid
    confusion by being explicit when a term might be misinterpreted.
"""

# Copyright (c) 2019-2021, Broadband Forum
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

from typing import Any, Collection, Dict, List, Optional, Tuple, Type, \
    TYPE_CHECKING, Union

from .content import Content
from .utility import FileName, Namespace, Spec, Status, Utility, Version

# common type aliases
# XXX none yet

logger_name = __name__.split('.')[-1]
logger = logging.getLogger(logger_name)
logger.addFilter(
        lambda r: r.levelno > 20 or logger_name in Utility.logger_names)

class_hierarchy = Utility.class_hierarchy
upper_first = Utility.upper_first
whitespace = Utility.whitespace


# this module knows about Nodes, but only as a concept: it knows very little
# about the Node interface (such cases are usually noted)

# make type checking happy
# XXX it doesn't; I guess Sphinx doesn't set TYPE_CHECKING? maybe it can't;
#     is there a downside to allowing this definition?
# XXX to make this work cleanly, we'd need to refactor parts of node.py;
#     should create types.py that defines basic types
if True or TYPE_CHECKING:
    class _Node:
        args = None
        getprop = None
        key = None
        keylast = None
        debugpath = None
        props = None
        typename = None

    class _Base(_Node):
        action = None  # defined on Description
        atom = None
        content = None  # defined on _HasContent
        typeprop = None  # defined on Syntax
        value = None  # defined on _ValueFacet

    Node = Union[_Node, _Base]


class NullType:
    """Represents a non-existent `Elem` instance.

    This type should have a `Null` singleton instance, which will behave as
    follows.
    * Iteration returns no items.
    * Indexing by a slice returns an empty list.
    * Indexing by anything else returns `Null`.
    * Accessing any attribute returns `Null`.
    * Calling it returns `Null`.
    * Evaluating it as a boolean returns ``False``.
    * Converting it to a string returns "Null".
    """

    class _Iter:
        def __iter__(self):
            return self

        def __next__(self):
            raise StopIteration()

    def __iter__(self):
        return NullType._Iter()

    def __getitem__(self, item):
        return [] if isinstance(item, slice) else Null

    def __getattribute__(self, attr):
        if attr.startswith('__') and attr.endswith('__'):
            return super().__getattribute__(attr)
        else:
            return Null

    def __call__(self, *args, **kwargs):
        return Null

    def __bool__(self):
        return False

    def __str__(self):
        return 'Null'

    __repr__ = __str__


# XXX it should only be used for Elems, not for Attrs; need to check...
Null = NullType()
"""Singleton `NullType` instance to use for non-existent `Elem` instances.

It evaluates as Boolean ``False``, so this idiom will often be sufficient::

    value = <something-that-might-return-None-or-Null>
    if not value:
        <error-handling>

Use of `Null` gives behavior similar to other languages' "safe navigation" 
operator, e.g., in Groovy this operator is ``?.``. For example, if ``root`` is
the root node, then this::

    root.xml_files[0].dm_document.dataTypes[0].name

is the name of the first XML file's DM document's first data type. If this 
doesn't exist then, rather than crashing, the value will be `Null`.
"""


# XXX should move this to a logging module that also handles filtering
# XXX can probably make this more pythonic by using dynamically-created
#     functions, like lint.warning_func etc.
class Report:
    """Simple class that takes a node and efficiently determines whether it
    matches the ``--debugpath`` command-line option and therefore should be
    logged.

    ``bool()`` indicates whether reporting is enabled for this node. If
    enabled, ``str()`` returns the node's `debugpath`.
    """

    def __init__(self, node: Node):
        """Report constructor.

        Construction is very cheap unless ``node.args.debugpath`` is not
        ``None``.

        Args:
            node: The node on which potentially to report. ``node.debugpath``
                must exist and be a string, and ``node.args.debugpath`` must
                exist and (if not ``None``) be a valid regular expression.
        """
        self._node = node
        self._debugpath = None
        self._enabled = False
        if node.args.debugpath:
            self._debugpath = self._get_debugpath()
            self._enabled = bool(
                    self._debugpath is not None and
                    # XXX this is an optimization; need to check for 'node'
                    #  too?
                    Utility.logger_names & {logger_name, 'node'} and
                    re.search(node.args.debugpath, self._debugpath))

    # XXX it's a bit naughty to expose this
    @property
    def node(self) -> Node:
        return self._node

    @property
    def debugpath(self) -> Optional[str]:
        return self._debugpath

    def _get_debugpath(self) -> Optional[str]:
        return self._node.debugpath

    def __bool__(self) -> bool:
        return self._enabled

    def __str__(self) -> str:
        if self._debugpath is None:
            self._debugpath = self._get_debugpath()
        return self._debugpath or ''


class PropDescr:
    """`Property` descriptor. Allows `Property` instances to be created
    only when they need to be given an explicit (non-default) value.

    `PropDescr` uses the `python descriptor protocol
    <https://docs.python.org/3/howto/descriptor.html>`_ to handle set and get
    operations on behalf of node objects.

    To use the mechanism, create `PropDescr` instances as class attributes. For
    example (from `bbfreport.node._Base`)::

        class _Base(_Node):
            xmlns_dmr = PropDescr(StrAttr, doc='DMR namespace.')

            dmr_version = PropDescr(VersionStrAttr, levels=2,
                doc='DMR version.', deprecated='replaced by `version`')

            status = PropDescr(EnumStrAttr,
                values=('current', 'deprecated', 'obsoleted', 'deleted'),
                default='current', doc='Node status.')

            id = PropDescr(StrAttr,
                doc='Node ``id`` (mandatory for some node types).')

            atom = PropDescr(StrAttr, alias='text', default='', internal=True,
                doc='Text associated with this node.')

            version = PropDescr(VersionStrAttr, levels=3,
                doc='Node version (added in DM v1.7).')

            comments = PropDescr(ListElem, plural=True, doc="Comments.")

    Some of these examples are referred to in the descriptions below.
    """

    def __init__(self, prop_cls: Type['Property'], *,
                 name: Optional[str] = None, plural: bool = False,
                 alias: Optional[Union[str, Tuple[str, ...]]] = None,
                 mandatory: bool = False, deprecated: Union[bool, str] = False,
                 default: Optional[Any] = None, internal: bool = False,
                 doc: Optional[str] = None, **kwargs):
        """Property descriptor constructor.

        The constructor does very little (mostly it just copies its
        arguments to instance variables). Most of the work is done by
        ``__set_name__()``, which is called automatically when the classes are
        defined.

        Args:
            prop_cls: Underlying `Property` class. An instance of this class
                is created only if/when it's needed.
            name: Property name. This is nearly always set automatically via
                ``__set_name__()`` but needs to be supplied if it's different
                from the class attribute variable name. This is currently only
                necessary for ``async``, which is a python reserved word,
                so the class attribute variable name is ``async_``.
            plural: Whether this represents a plural property. If so,
                and if the property name ends with an ``s``, the associated
                private attribute name will have the ``s`` removed. For
                example, it causes the ``comments`` private attribute name
                to be ``_comment`` rather than ``_comments``.
            alias: Additional alias or (if a tuple) aliases. For example,
                ``text`` is an alias of ``atom``. If the property name is
                mixed case, an all-lower-case alias is added automatically,
                e.g. a ``datatype`` alias would automatically be added for a
                ``dataType`` property.
            mandatory: Whether the property is mandatory. This is currently
                only used for generating documentation.
            deprecated: Whether the property is deprecated. This is
                currently only used for generating documentation. If it's a
                string, the string is included in the documentation,
                and should be a fragment that makes sense as the ``XXX`` in
                ``This attribute is deprecated and is XXX.``. For example, see
                ``dmr_version``.
            default: Property default. If this is a class, it's invoked
                (with no arguments) to create the default. Otherwise, it's
                just assigned. For mutable defaults, it's important to use the
                first approach! The underlying ``prop_cls.default`` provides a
                fallback default.
            internal: Whether the property is internal. If so, it's not
                added to the `Property` `Holder` and therefore won't be
                included in reports.
            doc: Additional documentation. `getdoc()` uses this, together with
                the other supplied information, to generate the `PropDescr`'s
                docstring.
            **kwargs: Additional keyword arguments that are applicable only to
                some `Property` types and are passed to the ``prop_cls``
                constructor. `PropDescr` peeks at a couple of them (``values``
                and ``node_cls`` at the time of writing) in order to
                generate documentation.

        Note:
            1. ``plural`` is currently set if and only if `islist()` is
               ``True``, so perhaps it could be replaced with a requirement
               that all list-valued instances' class attribute variable
               names end with ``s``.
            2. ``alias`` is not currently used. It's almost certainly clearer
               (and better) to define aliases directly, e.g. `_Base` defines
               `_Base.text` as an alias of `_Base.atom`.
        """

        self._prop_cls = prop_cls
        # __set_name() sets _name and _aname
        self._name = None
        self._aname = None
        self._plural = plural
        self._alias = alias
        self._mandatory = mandatory
        self._deprecated = deprecated
        self._default = default
        self._internal = internal
        # values are only relevant to Attrs and are only used here for doc
        self._values = kwargs.get('values', None)
        # node_cls is only relevant to Elems and is only used here for doc
        self._node_cls = kwargs.get('node_cls', None)
        # __set_name__() calls getdoc() to derive __doc__ from doc etc.
        self._doc = doc
        # copying might not be necessary but seems sensible?
        self._kwargs = kwargs.copy()

        # name is usually only passed to the constructor if it's different
        # from the class variable name
        if name is not None:
            self.__set_name__(None, name)

    def __set_name__(self, owner: Optional[Type[Node]], name: str) -> None:
        """Called (for each `PropDescr`) when the owner class is created. Is
        also called from the constructor when a name was passed to it, with
        ``owner=None`` and ``name=name``.

        Firstly, the private attribute name is derived from ``name``. It's
        ``_name`` unless ``plural`` was set and ``name`` ends with an
        ``s``, in which case the trailing ``s`` is omitted.

        Then, if ``owner`` is not ``None``:

        * If the underlying `Property` is list-valued and the trailing ``s``
          was dropped as described above, a "singular" class attribute (with
          no trailing  ``s``) is defined. This attribute returns the first
          list item, or ``None`` / `Null` if it's empty.

        * If ``alias`` was set, "alias" class attributes are defined,
          including all-lower-case aliases where ``name`` is not all
          lower-case.

        * The docstring is defined, based on all the information that was
          passed to the `PropDescr` constructor.

        Args:
            owner: Owner (node) class, or ``None`` if called from the
                constructor.
            name: Variable name to which the `PropDescr` is being assigned.
        """

        # the associated private attribute name always starts with an
        # underscore, so we don't allow the class variable attribute name to
        # start with one
        assert name is not None and name[:1] != '_'

        # this happens if an attribute is pre-named, e.g. 'async' (in which
        # case this is called from the constructor), or has manually-defined
        # aliases, e.g. 'text = atom' (in which case it was already called
        # when 'atom' was constructed)
        if self._name is not None:
            pass

        # plural means that the name is plural but the attribute name is
        # singular (it naively removes trailing 's' if present)
        # XXX should warn if plural but no trailing 's'?
        else:
            sname = re.sub(r's$', '', name) if self._prop_cls.islist() and \
                                               self._plural else name
            self._name = name
            self._aname = '_' + sname

        # the remaining logic is only performed when there's an owner

        # alias can be None, single alias, or tuple of aliases; also
        # automatically add a 'lower-case' alias if the name isn't lower-case
        if owner is not None:
            class AliasWrapper:
                def __init__(self, propdescr):
                    self._propdescr = propdescr

                def __get__(self, node_, owner_=None):
                    if node_ is None:
                        return self
                    else:
                        return self._propdescr.__get__(node_, owner_)

                def __set__(self, node_, value_):
                    self._propdescr.__set__(node_, value_)

                def __repr__(self):
                    return '%s(%r)' % (type(self).__name__, self._propdescr)

            aliases = self._alias if isinstance(self._alias, tuple) else (
                self._alias,) if self._alias is not None else ()
            if self._name.lower() != self._name:
                aliases += (self._name.lower(),)

            # XXX disable aliases for now
            aliases = []
            for alias in aliases:
                assert alias != name, "%s alias %r can't be the same as " \
                                      "name %r" % (self, alias, name)
                setattr(owner, alias, AliasWrapper(self))
                logger.debug('created %r wrapper for %r' % (alias, self))

        # set the documentation string
        if owner is not None:
            self.__doc__ = self.getdoc()

    def __get__(self, node: Node, owner: Optional[Type[Node]] = None) -> Any:
        """Get the value of this `PropDescr`'s `Property` on the supplied node.

        If the underlying `Property` object doesn't exist, the default value is
        returned. This is either the `PropDescr` constructor default or the
        underlying `Property.default` class default. In both cases, the
        specified default is either a type (which is invoked with no
        arguments) or a value (which is used directly).

        Args:
            node: The node on which to get the `Property` value.
            owner: The owning node class, or ``None`` to return the
                `PropDescr`.

        Returns:
            The requested value.

        """
        if node is None:
            return self
        else:
            def get_default(default):
                return default() if isinstance(default, type) else default

            prop = getattr(node, self._aname, None)
            # XXX if self._default is set, should check that it's compatible
            #     with self._prop_cls.default (if set)
            value = prop.value if prop is not None else get_default(
                    self._default) if self._default is not None else \
                get_default(self._prop_cls.default)
        return value

    def __set__(self, node: Node, value: Any) -> None:
        """Set the value of this `PropDescr`'s `Property` on the supplied node.

        If the underlying `Property` object doesn't exist, it's created (it
        has to exist, because it will store the value!). Then
        `Property.merge()` is called to add or update the value.

        Args:
            node: The node on which to set the `Property` value.
            value: The new value, which must be acceptable to the underlying
                `Property` class.
        """

        prop = self.getprop(node)
        report = Report(node)
        # XXX this is only needed if transforms create objects and don't set
        #     the parent; it's probably a bad idea, and anyway it won't catch
        #     more complex cases
        if hasattr(value, '_parent') and value._parent is None:
            value._parent = node
        prop.merge(value, report=report)

    def getprop(self, node: Node) -> 'Property':
        """Get this `PropDescr`'s `Property` from the supplied node,
        creating and storing it (on the node) if it doesn't exist.

        Args:
            node: The node that owns (or will own) the `Property`.

        Returns:
            The `Property` object.

        Note:
            There's no check that the node is of the expected type. We could
            (and probably should) save the ``__set_name()`` ``owner`` (which
            is the node class). Then we could check the node type.
        """

        prop = getattr(node, self._aname, None)
        if prop is None:
            # use aname[1:] to account for plural, e.g. if name is 'comments',
            # aname is '_comment', so we pass 'comment'
            prop = self._prop_cls(name=self._aname[1:], default=self._default,
                                  internal=self._internal, holder=node,
                                  **self._kwargs)
            setattr(node, self._aname, prop)
        return prop

    def getdoc(self) -> str:
        """Format and return a documentation string."""

        lines = []

        # 'attribute', 'element' etc.
        # XXX this is barely used
        ptype = self._prop_cls.ptype

        # bool, int, str etc., or None for elements
        vtype = self._prop_cls.vtype

        # description components
        comps = []

        # aliases?
        aliases = self._alias if isinstance(self._alias, tuple) else (
            self._alias,) if self._alias is not None else ()
        if aliases:
            comps += [
                '(aka %s) ' % ', '.join('**%s**' % alias for alias in aliases)]

        # list start?
        # XXX hack not to indicate attribute lists, because their vtype will
        #     indicate this
        islist = self._prop_cls.islist() and ptype == 'element'
        if islist:
            comps += ['``List[`` ']

        # removal of 'typing.' is cosmetic
        vname = None if vtype is None else vtype.__name__ if isinstance(
                vtype, type) else str(vtype).replace('typing.', '')
        nname = None if self._node_cls is None else self._node_cls.__name__ \
            if isinstance(self._node_cls, type) else str(self._node_cls)
        # see getprop() for why we use self._aname[1:]
        tname = '%s<%s>' % (vname, self._prop_cls.__name__) if \
            vname else nname if nname else upper_first(self._aname[1:])
        # assume that all upper- or mixed-case types are documented
        quote = '`' if tname != tname.lower() else '``'
        comps += [quote, tname, quote]

        # list end?
        if islist:
            comps += [' ``]``']

        # values?
        if self._values is not None:
            comps += [' {%s}' % ', '.join(
                    '``%s``' % value for value in self._values)]

        # default?
        if self._default is not None:
            # note that you can't use `` with an empty string
            comps += [' [%s]' % (
                '``%s``' % self._default if str(self._default) else "''")]

        # other start?
        any_other = self._mandatory or self._deprecated or self._internal
        if any_other:
            comps += [' (']

        # mandatory?
        if self._mandatory:
            comps += [':term:`M<Mandatory property>`']

        # deprecated? (text is appended below)
        if self._deprecated:
            comps += [':term:`D<Deprecated property>`']

        # internal?
        if self._internal:
            comps += [':term:`I<Internal property>`']

        # other end?
        if any_other:
            comps += [')']

        # suffix
        comps += [' -- ']

        # append doc if provided, and add lines to output
        doc = ''.join(comps) + (self._doc or '')
        lines += doc.split('\n')

        # also add deprecated text
        if self._deprecated and isinstance(self._deprecated, str):
            lines += ['', "This %s is deprecated: it's %s." % (
                ptype, self._deprecated)]

        return '\n'.join(lines)

    @property
    def name(self):
        return self._name

    @property
    def prop_cls(self):
        return self._prop_cls

    # XXX there's a lot of information missing here
    def __str__(self):
        return "%s(%r, default=%r, %r)" % (
            self._prop_cls.__name__, self._name, self._default, self._kwargs)

    def __repr__(self):
        return '%s(%s)' % (type(self).__name__, self)


class Property:
    """Node property (attribute or element)."""

    ptype: str = 'unknown'
    """Property type as a user-oriented string, e.g. "attribute" or 
    "element". This string can be used in generated documentation."""

    vtype: Optional[type] = None
    """Property value type."""

    default: Optional[Any] = None
    """Property class default. If this is a class, it's invoked (with no 
    arguments) to create the default. Otherwise it's just assigned. For
    mutable defaults, it's important to use the first approach!"""

    @classmethod
    def islist(cls) -> bool:
        """Whether the property value is a list. This is determined by
        checking whether `Property.default` is a type derived from ``list``."""
        return isinstance(cls.default, type) and issubclass(cls.default, list)

    def __init__(self, *, name: Optional[str] = None,
                 default: Optional[Any] = None, internal: bool = False,
                 holder: Optional[Union[Node, 'Attrs', 'Elems']] = None,
                 **kwargs):
        """Property constructor.

        Args:
            name: Property name. Must be specified.
            default: Default value. If not specified, the default is the
                class default `Property.default`.
            internal: Whether the property is internal, i.e., is not added
                to the property holder.
            holder: Property holder. Must be specified. This is an `Attrs`
                (for attributes) or `Elems` (for elements) instance, or for
                convenience a node can be passed, and its ``_attrs`` or
                ``_elems`` will be used (as appropriate).
            **kwargs: Keyword arguments. Derived class constructors should
                have consumed all keyword arguments, so this must be empty
                (this is checked).
        """
        assert name is not None, 'property name must be defined on creation'
        assert holder is not None, 'property holder must be defined on ' \
                                   'creation'
        assert not kwargs, 'kwargs should all been consumed by derived class '\
                           'constructors'
        self._name = name
        self._value = None
        self._default = default
        self._internal = internal
        self._holder = None
        # XXX note this is the property accessor; should define a utility
        self.holder = holder

    @property
    def name(self) -> str:
        """Property name."""
        return self._name or ''

    @property
    def value(self) -> Any:
        """Get the property value.

        Depending on property type, the value might be a single value,
        a list, a dictionary etc...

        If no value has been set, the default value is returned. This is
        either the constructor default or the underlying `Property.default`
        class default. In both cases, the specified default is either a type
        (which is invoked with no arguments) or a value (which is used
        directly).
        """

        def get_default(default):
            return default() if isinstance(default, type) else default

        return self._value if self._value is not None else get_default(
                self._default) if self._default is not None else get_default(
                type(self).default)

    @property
    def value_as_string(self) -> str:
        """Get the property value as a string.

        Derived classes can override this method. The default implementation
        returns ``str(self.value)``.

        Returns:
            The property value as a string. The string value should be
            suitable for use in an XML instance.

        Note:
            It would be better not to depend on XML representations.
        """
        return str(self.value)  # note use of accessor (which honors defaults)

    @property
    def value_as_list(self) -> list:
        """Get the property value as a list.

        This returns ``[]``, ``[self.value]`` or ``self.value``.

        Returns:
            The property value as a list.
        """

        value = self.value  # note use of accessor (which honors defaults)
        return [] if value is None else [value] if \
            not isinstance(value, list) else value

    @property
    def holder(self) -> 'Holder':
        """Get the property holder."""
        return self._holder

    # holder can be the appropriate holder or else (for convenience) can be
    # a Node (assumed to have _attrs and _elems attributes)
    # XXX this is rather ugly; should move the logic up to PropDescr
    # the holder has to be set before properties can be stored
    # once set, the holder can't be changed
    @holder.setter
    def holder(self, holder: Union[Node, 'Attrs', 'Elems']):
        """Set the property holder.

        The holder should only be set at construction time, and this method
        will only allow it to be set if it's not already set or if it's
        being set to the same object that it's currently set to.

        Args:
            holder: `Attrs` (for attributes) or `Elems` (for elements)
                instance, or for convenience a node can be passed, and its
                ``_attrs`` or ``_elems`` will be used (as appropriate).
        """
        assert holder is not None
        if isinstance(self, Attr):
            holder_ = getattr(holder, '_attrs', holder)
        elif isinstance(self, Elem):
            holder_ = getattr(holder, '_elems', holder)
        else:
            holder_ = holder
        assert isinstance(holder_, Holder)
        assert self._holder is None or holder_ is self._holder
        self._holder = holder_

    def merge(self, value: Any, *, report: Optional[Report] = None) -> None:
        """Merge the supplied value into the property and its property holder.

        This is a very important method! It's called for every single XML
        item (attribute, element, comment, cdata, other).

        The actual merge is done by `Property._merge()`, and then (unless
        the property is internal) `Holder.merge()` updates the property holder.

        Args:
            value: The value to add or merge. ``None`` means "reset" and
                causes `Property.reset()` to be called.
            report: Whether to report.

        Note:
            A value of ``Null`` means "no action". This is experimental.
        """

        # a value of None means reset
        if value is None:
            self.reset(report=report)
            return

        # a value of Null means no action
        elif value is Null:
            return

        #  merge the value
        if report:
            logger.info('%s: prop %r merge value %r' % (report, self, value))
        replace = self._merge(value, report=report)
        if report:
            extra = ' (replace)' if replace else ''
            logger.info('%s:  -> %r%s' % (report, self, extra))

        # merge the merged value to the property holder
        if not self._internal:
            if not self._holder:
                logger.error(
                        "%s: can't merge %r to unknown node" % (report, self))
            else:
                self._holder.merge(self, replace=replace, report=report)

    def reset(self, *, report: Optional[Report] = None) -> None:
        """Reset a property and remove it from its property holder.

        This method is usually called by passing a ``None`` value to
        `Property.merge()`.

        First (unless the property is internal), `Holder.remove()` removes
        the property from the property holder. Then the property value is
        set to ``None``.

        Args:
            report: Whether to report.

        Note:
            Setting the property value to ``None`` resets it to its initial
            state. ``Property.value`` will return the default value (if any)
            and won't necessarily return ``None``.
        """

        # remove the property from the property holder
        if not self._internal:
            if not self._holder:
                logger.error(
                    "%s: can't remove %r from unknown node" % (report, self))
            else:
                self._holder.remove(self, report=report)

        # reset the value
        if report:
            logger.info('%s: prop %r reset' % (report, self))
        self._value = None
        if report:
            logger.info('%s:  -> %r' % (report, self))

    def isinternal(self) -> bool:
        """Whether the property is internal."""
        return self._internal

    def _merge(self, value: Any, *, report: Optional[Report] = None) -> bool:
        """Merge the supplied value into the property.

        Derived classes must implement this method.

        Args:
            value: value: The value to add or merge.
            report: Whether to report.

        Returns:
            Whether `Holder.merge()` should replace the property value.
        """

        raise NotImplementedError('%s: unimplemented %s._merge()' % (
            report, type(self).__name__))

    # XXX this can output too much, and what it outputs isn't always useful
    def __str__(self):
        name = '%s=' % self._name if self._name is not None else ''
        value = Utility.nice_list(self.value, style='repr', limit=10) if \
            isinstance(self._value, list) else repr(self._value)
        default = ':%r' % self._default if self._default else ''
        return '%s%s%s' % (name, value, default)

    def __repr__(self):
        return '%s(%s)' % (type(self).__name__, self)


class Attr(Property):
    """Attribute property. An attribute value is not a node."""

    def _merge(self, value: Any, *, report: Optional[Report] = None) -> bool:
        return super()._merge(value, report=report)

    ptype = 'attribute'


class BoolAttr(Attr):
    """Boolean attribute property."""

    vtype = bool

    __false_values = (0, 'false', False)
    __true_values = (1, 'true', True)

    def _merge(self, value: Union[int, bool, str], *,
               report: Optional[Report] = None) -> bool:
        """Check the supplied value is valid. Then set ``_value``."""
        # noinspection PyTypeChecker
        valid = self.__false_values + self.__true_values
        assert value in valid, '%s: invalid %r value %r' % (
            report, self.name, value)
        self._value = value in self.__true_values
        return False

    @property
    def value_as_string(self) -> str:
        """Return ``true`` or ``false``."""
        return 'true' if self._value else 'false'


class IntAttr(Attr):
    """Integer attribute property."""

    vtype = int

    def _merge(self, value: Union[int, str], *,
               report: Optional[Report] = None) -> bool:
        """Check the supplied value is (or looks like) an int. Then set
        ``_value``."""
        isint = isinstance(value, int) or re.match(r'-?\d+', value)
        assert isint, '%s: invalid %r value %r' % (report, self.name, value)
        self._value = int(value) if isint else value
        return False


class IntOrUnboundedAttr(Attr):
    """Integer (or ``unbounded``) attribute property."""

    vtype = Union[int, str]

    def _merge(self, value: Union[int, str], *,
               report: Optional[Report] = None) -> bool:
        """Check the supplied value is (or looks like) an int, or is
        ``unbounded``. Then set ``_value``."""
        isint = isinstance(value, int) or re.match(r'-?\d+', value)
        assert isint or value == 'unbounded', '%s: invalid %r value %r' % (
            report, self.name, value)
        self._value = int(value) if isint else value
        return False


class DecimalAttr(Attr):
    """Decimal attribute property.

    Note:
        The value is currently stored as a string rather than as a
        ``decimal.Decimal``. No validation or other processing is performed.
    """

    vtype = str

    def _merge(self, value: str, *, report: Optional[Report] = None) -> bool:
        """No validation. Just set ``_value``."""
        self._value = value
        return False


class StrAttr(Attr):
    """String attribute property."""

    vtype = str

    def _merge(self, value: str, *, report=None) -> bool:
        """Check the supplied value is a string. Then set ``_value``."""
        assert isinstance(value, str), '%s: invalid %r value %r' % (
            report, self.name, value)
        self._value = value
        return False


class EnumStrAttr(StrAttr):
    """Enumerated string attribute property."""

    def __init__(self, *, values: Optional[Tuple[str, ...]] = None, **kwargs):
        """Call the superclass constructor and save the valid values.

        Args:
            values: Valid values.
            **kwargs: Additional keyword arguments (passed to the superclass
                constructor).

        Note:
            The valid values are currently ignored (although `PropDescr`
            uses them when generating documentation). They should be used
            when setting the attribute value. `PropDescr` should also use
            them to check that the default (if supplied) is valid.
        """
        super().__init__(**kwargs)
        self._values = values or ()


class StatusEnumStrAttr(EnumStrAttr):
    """Node status enumerated string attribute property."""

    def __init__(self, *, default: Optional[Any] = None, **kwargs):
        """Call the superclass constructor.

        Args:
            values: Valid values.
            **kwargs: Additional keyword arguments (passed to the superclass
                constructor).
        """

        super().__init__(values=Status.names, default=default, **kwargs)

    def _merge(self, value: Union[str, Status], *,
               report: Optional[Report] = None) -> bool:
        """Convert the supplied value to a ``Status`` if necessary. Then
        set ``_value``."""

        if not isinstance(value, Status):
            value = Status(value)
        self._value = value
        return False


# this outputs a warning when things are redefined (it's intended to be used
# for the 'name' attribute)
# XXX it's not clever enough to detect apparent model redefinitions, which are
#     actually due to them being imported under a different name (ignored)
class RedefineCheckStrAttr(StrAttr):
    def _merge(self, value: str, *, report: Optional[Report] = None) -> bool:
        if self._value and value and report.node.typename != 'model':
            logger.error('%s: %s already defined' % (
                report, report.node.typename))
        return super()._merge(value, report=report)


class NamespaceStrAttr(StrAttr):
    """XML namespace string attribute property."""

    def _merge(self, value: Union[str, Namespace], *,
               report: Optional[Report] = None) -> bool:
        """Convert the supplied value to a ``Namespace`` if necessary.
        Then set ``_value``."""

        if not isinstance(value, Namespace):
            # self.name is 'xmlns_dm', 'xmlns_dmr' etc.
            value = Namespace.get(value, attr=self.name)
        elif value.attr is None:
            value.attr = self.name
        self._value = value
        return False


class VersionStrAttr(StrAttr):
    """Version string attribute property."""

    def __init__(self, *, levels: int = 2, **kwargs):
        """Call the superclass constructor and save the maximum number of
        levels.

        Args:
            levels: Maximum number of levels in a version string, e.g. ``2``
                (the default) permits versions like ``1.2``, but not ``1.2.3``.
            **kwargs: Additional keyword arguments (passed to the superclass
                constructor).
        """
        super().__init__(**kwargs)
        self._levels = levels

    def _merge(self, value: Union[str, Version], *,
               report: Optional[Report] = None) -> bool:
        """Convert the supplied value to a ``Version`` if necessary. Then
        set ``_value``."""

        if not isinstance(value, Version):
            value = Version(value, levels=self._levels)
        self._value = value
        return False


class FileNameStrAttr(StrAttr):
    def _merge(self, value: Union[str, FileName], *,
               report: Optional[Report] = None) -> bool:
        """Convert the supplied value to a ``FileName`` if necessary. Then
        set ``_value``."""

        if not isinstance(value, FileName):
            value = FileName(value)
        self._value = value
        return False


class SpecStrAttr(StrAttr):
    def _merge(self, value: Union[str, Spec], *,
               report: Optional[Report] = None) -> bool:
        """Convert the supplied value to a ``Spec`` if necessary. Then
        set ``_value``."""

        if not isinstance(value, Spec):
            value = Spec(value)
        self._value = value
        return False


class StrDictAttr(Attr):
    """String dictionary attribute property."""

    vtype = Dict[str, str]
    default = dict

    def _merge(self, value: str, *, report: Optional[Report] = None) -> bool:
        """Check the supplied value is a string and has an even number of
        space-separated components. Then, treating them as a list of
        ``(name, value)`` pairs, create a dictionary and store it in
        ``_value``.

        Note:
            1. Names and values can't contain whitespace, because whitespace is
               always treated as a separator. Some sort of escape mechanism
               should be supported.
            2. This method should also support ``dict`` arguments.
        """
        assert isinstance(value, str), '%s: invalid %r value %r' % (
            report, self.name, value)
        comps = value.split()
        assert len(comps) % 2 == 0, '%s: invalid %r value %r has an odd ' \
                                    'number of components' % (
                                        report, self.name, ' '.join(comps))
        value = {}
        for i in range(0, len(comps), 2):
            name_, value_ = comps[i], comps[i + 1]
            value[name_] = value_
        self._value = value
        return False

    @property
    def value_as_string(self) -> str:
        """Return a string consisting of space-separated dictionary keys and
        values, i.e., ``name1 value1 name2 value2...``."""
        return ' '.join(['%s %s' % (n, v) for n, v in self._value.items()])


class NamespaceStrDictAttr(StrDictAttr):
    """XML namespace string dictionary attribute property.

    Note:
        1. The stored value is not changed, so it's still the super-class's
           string dictionary.
    """

    def _merge(self, value: str, *,
               report: Optional[Report] = None) -> bool:
        """Invoke the super-class method to create the dictionary,
        then store it in the `Namespace` class."""

        retval = super()._merge(value, report=report)
        for name, location in self.value.items():
            Namespace.get(name, location=location)
        return retval


class StrListAttr(Attr):
    """String list attribute property."""

    vtype = List[str]
    default = list

    def _merge(self, value: Union[str, list, tuple], *,
               report: Optional[Report] = None) -> bool:
        """Check the supplied value is a list, tuple or string. Then, set
        ``_value`` to a copy of the supplied list or tuple, or to a list of
        whitespace-separated tokens.

        Note:
            1. Tokens can't contain whitespace, because whitespace is always
               treated as a separator. Some sort of escape mechanism should
               be supported.
            2. Values coming straight from XML will be strings, but values
               from existing properties will be lists.
        """
        assert isinstance(value,
                          (list, tuple, str)), '%s: invalid %r value %r' % (
            report, self.name, value)
        self._value = value.split() if isinstance(value, str) else value[:]
        return False

    @property
    def value_as_string(self):
        """Return a string consisting of space-separated values, i.e.,
        ``value1 value2...``."""
        return ' '.join(self._value)


class ContentAttr(Attr):
    """Content attribute property. This property type is currently only used
    by `_HasContent` nodes such as `Description`."""

    vtype = Content
    default = Content

    def _merge(self, value: Union[str, Tuple[Node, ...]], *,
               report: Optional[Report] = None) -> bool:
        """If the supplied value is a string, use it directly. Otherwise,
        it should be a tuple of nodes, from which the text is collected and
        processed as described below. Then set ``_value`` to the resulting
        string.

        The text is currently just concatenated and then passed to the
        `Utility.whitespace()` function.

        Note:
            1. We could permit any collection rather than requiring a tuple.
            2. We should store the content internally as wrapped paragraphs
               (as is done by the old report tool). Otherwise, we can't
               combine unwrapped and wrapped paragraphs, and plugins can't
               easily process content.
        """

        # if value is a string, it replaces the current text
        if isinstance(value, str):
            text = value

        # otherwise expect value to be a tuple of nodes
        else:
            assert isinstance(value, tuple), 'value must be a tuple'

            # the value is (for now) the concatenation of all the atoms
            atoms = [node.atom for node in value if node.atom is not None]

            # text is None if no children have atoms
            text = whitespace(''.join(atoms)) if atoms else None

        # always create a new Content object
        self._value = Content(text, preprocess=True)
        return False


class Elem(Property):
    """Element property. An element value is a node or a list of nodes."""

    ptype = 'element'
    default = Null

    # node_cls defaults to name
    def __init__(self, *, name: Optional[str] = None,
                 node_cls: Optional[Union[str, Type[Node]]] = None, **kwargs):
        """Call the superclass constructor and save the node class.

        Args:
            name: Property name.
            node_cls: Node class name or type object. Defaults to ``name``.
            **kwargs: Additional keyword arguments (passed to the superclass
                constructor).

        Note:
            The node class isn't used directly by this object, but it's made
            available via `Elem.node_cls`, which is used by `_Node._merge()`
            when it needs to create a node.
        """
        super().__init__(name=name, **kwargs)
        self._node_cls = node_cls or name

    def _merge(self, value: Any, *, report: Optional[Report] = None) -> bool:
        return super()._merge(value, report=report)

    @property
    def node_cls(self) -> Union[str, Type[Node]]:
        """Return the node class name or type object."""
        return self._node_cls


class SingleElem(Elem):
    """Single node element property."""

    def _merge(self, node: Node, *, report: Optional[Report] = None) -> bool:
        """This method is deceptively simple, but in fact it can merge an
        entire node tree.

        In outline::

            If the value has never been set, set it to the supplied node.
            Otherwise, for each of the supplied node's properties:
                Merge the property into the value node's corresponding
                property.
        """

        value_node = self._value
        if value_node is None:
            self._value = node
        elif node.key is not None:
            # actually this method should never be called with a keyed node
            # XXX disable this check, because it can fail with certain invalid
            #     data models
            # assert node.key is None
            # and if it _was_ called, it would be the same node
            assert node is value_node
        else:
            # it's not keyed, so a new instance will always have been created
            assert node is not value_node
            # and the new instance should always be of the same type
            assert type(node) is type(value_node)
            for node_prop in node.props:
                value_prop = value_node.getprop(node_prop.name)
                value_prop.merge(node_prop.value, report=report)
        return False


class DescriptionSingleElem(SingleElem):
    """Single node element property (specifically for `Description`)."""

    # XXX may want to issue "same as previous" and "invalid description action"
    #     warnings... but they should be deferred until all the merges have
    #     been performed
    def _merge(self, node: Node, *, report: Optional[Report] = None) -> bool:
        """Use the supplied node's `action` attribute to merge its `content`
        into the current content.

        Note:
            Both the current content and the supplied node are assumed to
            have `content` and `action` attributes, so they are effectively
            assumed to be `Description` instances.
        """

        # if not already defined, just set to the supplied value
        if self._value is None:
            self._value = node

        # otherwise merge the supplied value into the current value
        # XXX now that we're using {{np}} we could simplify this, because
        #     leading, trailing and duplicate {{np}} will be tidied
        else:
            curr = self._value
            curr_content = Utility.whitespace(curr.content.text) or ''
            node_content = Utility.whitespace(node.content.text) or ''
            separator = '{{np}}' if curr_content and node_content else ''
            # XXX should warn of unnecessary 'create' or omitted 'replace'?
            if node.action in {None, 'create', 'replace'}:
                curr.content = node_content
            elif node.action in {'prefix'}:
                curr.content = node_content + separator + curr_content
            elif node.action in {'append'}:
                curr.content = curr_content + separator + node_content
            else:
                logger.error('%s: invalid description action %r' % (
                    report, node.action))
                curr.content = node_content

            # reset the current value's action attribute; it's probably not
            # set, but it might have been explicitly set to 'create'
            curr.action = None
        return False


class SyntaxSingleElem(SingleElem):
    """Single node element property (specifically for `Syntax`)."""

    def _merge(self, node: Node, *, report: Optional[Report] = None) -> bool:
        """Currently just checks whether the data type has changed.

        Note:
            We need to complete the logic to check for things like invalid
            changes to facets. Syntax should provide a method to do this.
        """

        # XXX DataType._mergedone() will detect invalid facet inheritance,
        #     but it can't check for things like where an <unsignedInt/>
        #     parameter has its range illegally restricted; this need to
        #     call back into a suitable Node method
        if self._value is not None:
            old_type = self.value.typeprop()
            new_type = node.typeprop()
            if old_type and new_type and new_type is not old_type:
                # XXX this is a _Primitive or DataTypeRef; proposed_update()
                #     has to be defined in a mutual base class
                old_type.value.proposed_update(new_type.value)
                if new_type.name != old_type.name:
                    logger.warning('%s: type changed from %s to %s' % (
                        report, old_type.value_as_string,
                        new_type.value_as_string))
                    # XXX hide the old type so plugins can choose to ignore it
                    #     (visitor.py will do this automatically)
                    old_type.value.hide()
        return super()._merge(node, report=report)


class ListElem(Elem):
    """Node list element property."""

    class ListWrapper(list):
        """List class (derived from ``list``).

        `ListElem` stores its nodes in an instance of this class. It allows
        access by int, slice or key, and returns `Null` if not found.

        Note:
            1. It would be quite a lot of work to fully support collection
               operations. We should look at ``collections.abc.MutableMapping``
               (would need to call `Property.merge()` to perform holder
               operations); for this reason, `ListWrapper` is probably a bad
               idea.
            2. We could support string slices but is there a use case for this?
            3. We should check the type when adding elements, and note whether
               keyed or unkeyed. If keyed, could also support dict-like access?
        """

        # containment check by key; c.f. dict containment check
        def __contains__(self, item):
            if isinstance(item, str):
                matches = {node for node in self if
                           node.keylast and node.keylast == item}
                return len(matches) > 0
            else:
                return super().__contains__(item)

        def __getitem__(self, key):
            value = None
            if isinstance(key, int):
                if key >= len(self) or key < -len(self):
                    value = Null
            elif isinstance(key, slice):
                if key.stop is not None and not set(
                        range(key.start or 0, key.stop, key.step or 1)) & set(
                        range(len(self))):
                    value = Null
            elif isinstance(key, str):
                matches = {node for node in self if
                           node.keylast and node.keylast == key}
                value = matches.pop() if matches else Null

            return value if value is not None else super().__getitem__(key)

        def __setitem__(self, key, value):
            assert False, 'node __setitem__() is not supported in this context'

        def insert(self, index, value):
            assert False, 'node insert() is not supported in this context'

        def append(self, value):
            assert False, 'node append() is not supported in this context'

    default = ListWrapper

    def _merge(self, node_or_nodes: Union[Node, Collection[Node]], *,
               report: Optional[Report] = None) -> bool:
        """This can receive a single node or a list of one or more nodes. A
        single node shouldn't already be there and is added, whereas a list
        of nodes needs to be merged with the existing list."""

        if isinstance(node_or_nodes, list):
            return self._mergelist(node_or_nodes, report=report)

        node = node_or_nodes

        if self._value is None:
            self._value = ListElem.ListWrapper([node])
        elif node not in self._value:
            # XXX might want a hook here, e.g. for sizes might want to check
            #     for overlap (but would like all such logic in one place)
            self._value += [node]
        elif node.key is not None:
            # if keyed, there's nothing to do
            # XXX this seems to happen rather a lot; is something wrong?
            pass
        else:
            # if not keyed, we don't know how to merge it
            # XXX can this in fact happen?
            logger.error("%s: don't know how to merge %r value %r" % (
                report, self, node))
        return False

    # XXX the comment about facets isn't necessarily correct; surely status
    #     should be carried over, for example?
    def _mergelist(self, nodes: List[Node], *,
                   report: Optional[Report] = None) -> bool:
        """Merge a list of nodes into an existing list of nodes.

        The default behavior is just to replace the existing list of nodes
        with the new list of nodes. This works for all facets except values
        (which need to retain descriptions).

        Args:
            nodes: value: The nodes to add or merge.
            report: Whether to report.

        Returns:
            Whether `Holder.merge()` should replace the property value.
        """

        self._value = ListElem.ListWrapper(nodes)
        return True


# value nodes have unique-key 'value' attributes; the new list replaces the
# old one except that descriptions are carried over
# XXX everything except for the value itself is now carried over
class ValueListElem(ListElem):
    """Node list element property (specifically for `_ValueFacet`)."""

    def _mergelist(self, nodes: List[Node], *,
                   report: Optional[Report] = None) -> bool:
        """Copy the old values to the new values, merging descriptions."""

        old_values = {v.value: v for v in (self._value or [])}
        new_values = ListElem.ListWrapper()
        for node in nodes:
            if node.value not in old_values:
                new_values += [node]

            else:
                old_value = old_values[node.value]

                # merge all properties except for 'value'
                # XXX it would probably do no harm to carry over the value,
                #     but there's no need to do so
                for new_prop in node.props:
                    prop_name = new_prop.name
                    if prop_name != 'value':
                        old_prop = old_value.getprop(prop_name)
                        old_prop.merge(new_prop.value, report=report)

                new_values += [old_value]

        # update the property value and request replacement
        self._value = new_values
        return True


class Holder:
    """Node property holder (maintains an ordered list of attributes or
    elements)."""

    def merge(self, prop: Property, *, replace: bool = False,
              report: Optional[Report] = None) -> None:
        """Merge a property into this holder, optionally replacing any
        previous value.

        The actual merge is done by `Holder._merge()`.

        Args:
            prop: The property to add or merge.
            replace: Whether to replace the value.
            report: Whether to report.
        """

        if report:
            logger.info('%s: holder %r merge %r' % (report, self, prop))

        self._merge(prop, replace=replace, report=report)

        if report:
            logger.info('%s: holder -> %r' % (report, self))

    def remove(self, prop: Property, *,
               report: Optional[Report] = None) -> None:
        """Remove a property from a holder.

        The actual remove is done by `Holder._remove()`.

        Args:
            prop: The property to remove.
            report: Whether to report.
        """

        if report:
            logger.info('%s: holder %r remove %r' % (report, self, prop))

        self._remove(prop, report=report)

        if report:
            logger.info('%s: holder -> %r' % (report, self))

    def _merge(self, prop: Property, *, replace: bool = False,
               report: Optional[Report] = None) -> None:
        """Merge a property into this holder, optionally replacing any
        previous value.

        Derived classes must implement this method.

        Args:
            prop: The property to add or merge.
            replace: Whether to replace the value.
            report: Whether to report.
        """

        raise NotImplementedError('%s: unimplemented %s._merge()' % (
            report, type(self).__name__))

    def _remove(self, prop: Property, *,
                report: Optional[Report] = None) -> None:
        """Remove a property from a holder.

        Derived classes must implement this method.

        Args:
            prop: The property to remove.
            report: Whether to report.
        """

        raise NotImplementedError('%s: unimplemented %s._remove()' % (
            report, type(self).__name__))

    @property
    def props(self) -> Tuple[Property, ...]:
        """This holder's properties."""
        raise NotImplementedError('unimplemented %s.props' % type(
                self).__name__)

    @property
    def value(self) -> Any:
        """This holder's value."""
        raise NotImplementedError('unimplemented %s.value' % type(
                self).__name__)


class Attrs(Holder):
    """Node attributes."""

    def __init__(self):
        """Initialize the dictionary."""
        self._dict = {}

    def _merge(self, prop: Property, *, replace: bool = False,
               report: Optional[Report] = None) -> None:
        """Add or replace the property in the dictionary (``replace`` is
        ignored)."""
        name = prop.name
        assert name is not None, "%s: can't merge anonymous property %r" % (
            report, prop.value)
        self._dict[name] = prop

    def _remove(self, prop: Property, *,
                report: Optional[Report] = None) -> None:
        """Remove the property from the dictionary (nothing is done if the
        property isn't in the dictionary)."""
        name = prop.name
        assert name is not None, "%s: can't remove anonymous property %r" % (
            report, prop.value)
        if name in self._dict:
            del self._dict[name]

    def __str__(self):
        """The dictionary as a string."""
        return str(self._dict)

    def __repr__(self):
        return '%s(%s)' % (type(self).__name__, self)

    @property
    def props(self) -> Tuple[Attr, ...]:
        """A tuple of properties."""
        return tuple(self._dict.values())

    @property
    def value(self) -> Dict[str, str]:
        """A dictionary mapping property name to property value (as
        returned by `Property.value_as_string`)."""
        return {n: p.value_as_string for n, p in self._dict.items()}


class Elems(Holder):
    """Node elements."""

    def __init__(self):
        """Initialize dictionaries."""
        self._props = {}  # used as an ordered set (values are all True)
        self._node_to_prop = {}  # used as an ordered set (values are all True)
        self._prop_to_nodes = {}  # map from prop back to its nodes

    def _merge(self, prop: Property, *, replace: bool = False,
               report: Optional[Report] = None) -> None:
        """Add or replace the property."""

        # replace doesn't impact the properties
        if prop not in self._props:
            self._props[prop] = True

        # if replacing, remove any unwanted nodes
        if replace:
            for node in self._prop_to_nodes.get(prop, []):
                del self._node_to_prop[node]
            if prop in self._prop_to_nodes:
                del self._prop_to_nodes[prop]

        # append any new nodes
        for node in prop.value_as_list:
            if node not in self._node_to_prop:
                self._set_node_to_prop(node, report=report)
                self._prop_to_nodes.setdefault(prop, [])
                self._prop_to_nodes[prop] += [node]

    # XXX need to integrate this properly once it all works
    def _set_node_to_prop(self, node, *,
                          report: Optional[Report] = None) -> None:
        # maps typename to the appropriate dmr:previousXxx attribute names
        dmr_previous_parameter_etc = ['dmr_previousCommand',
                                      'dmr_previousEvent',
                                      'dmr_previousParameter']
        typename_map = {'object': ['dmr_previousObject'],
                        'parameter': dmr_previous_parameter_etc,
                        'command': dmr_previous_parameter_etc,
                        'event': dmr_previous_parameter_etc,
                        'profile': ['dmr_previousProfile']}
        typename = node.typename

        # if --thisonly is set, never try to reorder anything
        if node.args.thisonly:
            self._node_to_prop[node] = True

        # only these type names support dmr:previousXxx attributes and need
        # special treatment
        elif typename not in typename_map:
            self._node_to_prop[node] = True

        # handle dmr:previousXxx logic, and also ensure that object parents
        # are inserted before their children
        else:
            node_to_prop = {}
            # XXX see node._ModelItem._mergedone()
            previous = [getattr(node, attr) for attr in
                        typename_map[typename] + ['_previous_lexical'] if
                        getattr(node, attr, None) is not None]
            previous = previous[0] if previous else None
            # '' means "add as first child of parent" (for objects,
            # this requires additional logic)
            if previous == '' and typename == 'object' and \
                    (parent_objpath := node.object_parent.objpath) != '':
                if report:
                    logger.info("%s: previous %s -> %s" % (
                        report, Utility.nice_string(previous),
                        Utility.nice_string(parent_objpath)))
                previous = parent_objpath
            # XXX might also support 'A._.' for "add after last child", but
            #     this would really require too much knowledge for here
            insert_next = False
            node_parent_name = None
            for existing in self._node_to_prop:
                # has the node already been added?
                if node in node_to_prop:
                    pass
                # XXX should check that it's a _ModelItem, but instead do a
                #     bit of duck-typing
                elif not hasattr(existing, 'nameOrBase'):
                    pass
                # XXX this could in theory be None (for invalid XML)
                elif (existing_name := existing.nameOrBase) is None:
                    pass
                elif insert_next:
                    if report:
                        logger.info('%s: added after %s' % (report, previous))
                    node_to_prop[node] = True
                    insert_next = False
                # it'll only be '' if node is the root object (edge case)
                elif previous == '':
                    if report:
                        logger.info('%s: added at start' % report)
                    node_to_prop[node] = True
                    # insert_next = True
                # non-matching previous values will be silently ignored
                elif previous and existing_name == previous:
                    insert_next = True
                elif typename == 'object' and existing.typename == 'object':
                    # node is the parent of an existing child; insert it
                    # before the child
                    if node is existing.object_parent:
                        if report:
                            logger.info('%s: inserted before existing child %s'
                                        % (report, existing))
                        node_to_prop[node] = True
                    # node is the child of an existing parent; will insert it
                    # after the last descendant of this parent
                    elif existing is node.object_parent:
                        node_parent_name = existing_name
                    # insert it before the node after the last descendant
                    # XXX should use object_xxx() methods rather than doing
                    #     string processing on the node name
                    elif node_parent_name and not \
                            existing_name.startswith(node_parent_name):
                        if report:
                            logger.info('%s: inserted before non-parent %s' % (
                                report, existing))
                        node_to_prop[node] = True
                        node_parent_name = None
                node_to_prop[existing] = True

            if node not in node_to_prop:
                node_to_prop[node] = True

            self._node_to_prop = node_to_prop

    # nothing is done if the property doesn't exist
    def _remove(self, prop: Property, *,
                report: Optional[Report] = None) -> None:
        """Remove the property."""

        if prop in self._props:
            del self._props[prop]
        for node in self._prop_to_nodes.get(prop, []):
            del self._node_to_prop[node]
        if prop in self._prop_to_nodes:
            del self._prop_to_nodes[prop]

    def __str__(self):
        return Utility.nice_list(self._node_to_prop.keys(), style='repr',
                                 limit=10)

    def __repr__(self):
        return '%s(%s)' % (type(self).__name__, self)

    @property
    def props(self) -> Tuple[Elem, ...]:
        """A tuple of properties."""
        return tuple(self._props.keys())

    @property
    def value(self) -> Tuple[Node, ...]:
        """A tuple of nodes."""
        return tuple(self._node_to_prop.keys())


# add class hierarchy
__doc__ += class_hierarchy((PropDescr, Property, Holder, NullType))
