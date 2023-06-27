"""Visitor pattern support (for transforms and output formats)."""

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

import inspect
import logging
import os.path
import re

from typing import Any, Callable, cast, Dict, List, Optional, Tuple, Type, \
    Union

from .node import _Accessor, _Node, Node, NodeOrMixinType, Root, varname
from .plugin import Plugin
from .utility import Utility

logger_name = __name__.split('.')[-1]
logger = logging.getLogger(logger_name)
logger.addFilter(
        lambda r: r.levelno > 20 or logger_name in Utility.logger_names)

lower_first = Utility.lower_first


# XXX using lower-case typenames isn't enough because you can't write an
#     'object' method!; should allow actual typename and/or a leading
#     or trailing underscore, plus should implement a consistent naming policy

# XXX need to make this to do more useful stuff
# XXX defaults give backwards compatible behavior
# XXX should automatically insert 'description' at the start?
# XXX entries are typenames rather than elemnames; should be elemnames?
# XXX once in a group, the group doesn't change until hit a new element that's
#     explicitly in the new group; this is too subtle: should support a second
#     level of elements for which order is to be preserved
# XXX it currently seems to work, but more by luck than judgement
class Rules:
    """Rules class that controls node traversal order etc.."""

    default_globs = ('dataType', 'glossary', 'abbreviations',
                     'bibliography', 'template')
    """Default node typenames for which to generate global lists."""

    default_stop_single = ()
    """Default node typenames at which to stop traversal when processing a
    single file (``thisonly=True``)."""

    default_ignore_single = ('root', 'xml_file')
    """Default node typenames to ignore when processing a single file
    (``thisonly=True``)."""

    default_stop_full = ('import', 'component',
                         'componentRef') + default_globs
    """Default node typenames at which to stop when processing all files
    (``thisonly=False``)."""

    default_ignore_full = default_ignore_single + default_stop_full
    """Default node typenames to ignore when processing all files
    (``thisonly=False``)."""

    default_order = {
        # parameter, object, command and event aren't permitted by the schema
        # but can be present in test input
        'dm_document': ('description', 'import', 'dataType',
                        'glossary', 'abbreviations', 'bibliography',
                        'template', 'component', 'model', 'parameter',
                        'object', 'command', 'event'),
        'dataType': ('description',),
        'glossary': ('description',),
        'abbreviations': ('description',),
        'bibliography': ('description',),
        'reference': ('referenceName', 'referenceTitle',
                      'referenceOrganization', 'referenceCategory',
                      'referenceDate', 'referenceHyperlink'),
        'component': ('description',),
        'model': ('description', 'parameter', 'object', 'componentRef',
                  'profile'),
        'object': ('description', 'uniqueKey', 'parameter'),
        'syntax': ('list', 'string'),
        'profile': ('description', 'parameterRef', 'objectRef')
    }
    """Default node typename groups, determining the order in which nodes
    are traversed.

    Note:
        There are various problems with the current mechanism.

    :meta hide-value:"""
    # XXX :meta hide-value: (above) doesn't seem to be working?

    def __init__(self, *, globs: Optional[Tuple[str, ...]] = None,
                 ignore: Optional[Tuple[str, ...]] = None,
                 stop: Optional[Tuple[str, ...]] = None,
                 order: Optional[Dict[str, Tuple[str, ...]]] = None,
                 thisonly: bool = False):
        """Rules constructor.

        Args:
            globs: Node typenames for which to generate global lists.
                Defaults to `default_globs`.
            ignore: Node typenames to ignore. Defaults to
                `default_ignore_single` if ``thisonly`` or
                `default_ignore_full` otherwise.
            stop: Node typenames at which to stop. Defaults to
                `default_stop_single` if ``thisonly`` or `default_stop_full`
                otherwise.
            order: Node typename group definitions. Defaults to
                `default_order`.
            thisonly: Whether processing only a single file, in which case
                imports aren't processed. Corresponds to the ``--thisonly``
                command line option.
        """

        # typenames for which to generate global lists.
        self._globs = globs if globs is not None else self.default_globs

        # typenames to ignore
        self._ignore = ignore if ignore is not None else \
            self.default_ignore_single if thisonly else \
            self.default_ignore_full

        # typenames at which to stop
        self._stop = stop if stop is not None else self.default_stop_single \
            if thisonly else self.default_stop_full

        # dictionary mapping typename to typenames
        # XXX should merge more intelligently? no?
        self._order = order if order is not None else self.default_order

    @property
    def globs(self) -> Tuple[str, ...]:
        return self._globs

    @property
    def ignore(self) -> Tuple[str, ...]:
        """Typenames to ignore."""
        return self._ignore

    @property
    def stop(self) -> Tuple[str, ...]:
        """Typenames at which to stop."""
        return self._stop

    @property
    def order(self) -> Dict[str, Tuple[str, ...]]:
        """Dictionary mapping typename to typenames."""
        return self._order

    def __str__(self):
        return 'globs %r ignore %r stop %r' % (self._globs, self._ignore,
                                               self._stop)

    def __repr__(self):
        return '%s(%s)' % (type(self).__name__, self)


class Visitor(Plugin):
    """Visitor pattern class (for transforms and output formats).
    """

    def __init__(self, name: Optional[str] = None, *,
                 plugindirs: Optional[List[str]] = None,
                 internal: bool = False, **kwargs):
        """Visitor constructor.

        The primary purpose of the constructor is to populate a node class
        map that maps node classes to methods such as
        ``visit_parameter()``. This is only done if the plugin hasn't
        implemented its own version of `Visitor._visit_node()`.
        """

        super().__init__(name)

        # XXX this should be a reusable utility (note the different algorithm
        #     for deriving the logger name)
        # XXX should only create a logger for xxx.py loggers?
        logger_name_ = str(self).split('.')[0]
        self.logger = logging.getLogger(logger_name_)
        self.logger.addFilter(
            lambda r: r.levelno > 20 or logger_name_ in Utility.logger_names)

        # node type name to (method, arg_names, kwarg_names) map
        # (it's actually keyed by varname(node_class))
        # XXX will change this lower-case rule
        self._method_map: Dict[str, Tuple[Callable, List[str], List[str]]] = {}

        # node type to method vname list (in MRO order) map
        self._type_map: Dict[Type, List[str]] = {}

        # does the plugin implement _visit_node()? if so, there's no need to
        # populate the method map
        implements = self._visit_node.__func__ is not Visitor._visit_node
        if implements:
            pass

        # otherwise, there are two cases for populating the method map:
        # - if name is not specified, this is a subclass that implements
        #   visit_parameter() etc. methods
        elif name is None:
            self.__init_subclass()

        # - if name is specified, it's a python file that directly implements
        #   visit_parameter() etc. functions
        else:
            self.__init_pyfile(name, plugindirs=plugindirs, internal=internal)

        # finally, populate the type map, which is just an optimization to
        # avoid needing to use the MRO when visiting each node
        self.__init_type_map()

        # invoke the standalone _init_() function if defined
        self._invoke('_init_', **kwargs)

    def __init_subclass(self) -> None:
        self.__init_method_map(type(self).__dict__, subclass=True)

    def __init_pyfile(self, file: str, *,
                      plugindirs: Optional[List[str]] = None,
                      internal: bool = False) -> None:
        # the file must be a python source file
        # XXX shouldn't really call them plain xxx.py, but just calling them
        #     xxxTransform.py would interfere with automatic plugin scanning
        name, ext = os.path.splitext(file)
        if ext and ext != '.py':
            logger.error('%s file %s is not a python source file' % (
                type(self).__name__, file))
            return
        file = name + '.py'

        # import the file (as a module)
        _, sys_path_save = Plugin.push_plugindirs(plugindirs)
        module = Plugin.import_one(file)
        Plugin.pop_plugindirs(sys_path_save)
        if module is None:
            logger.error('failed to import %s from %s' % (file, plugindirs))
            return

        func = logger.debug if internal else logger.info
        func('imported %s from %s' % (module.__name__, module.__file__))

        # populate the method map
        self.__init_method_map(module.__dict__, subclass=False)

    def __init_method_map(self, dct: Dict[str, Any], *,
                          subclass: bool = False) -> None:
        # extra provides additional special functions to be searched for
        # (it's used for adding the visit() function)
        extra = {'visit'}

        # collect all special _xxx_() functions (they're not methods); the
        # dict value is the 'no_node_arg' flag
        special = {'_init_': True, '_post_init_': True, '_begin_': False,
                   '_pre_elems_': False, '_pre_group_': False, '_post_group_':
                       False, '_post_elems_': False, '_end_': False}
        methods = {n: v for n, v in dct.items() if
                   not (subclass and (re.match(r'^__\w+__$', n) or
                                      re.match(r'^_visit_', n))) and
                   (re.match(r'^_\w+_$', n) or n in extra) and
                   inspect.isroutine(v)}
        for method_name, method in methods.items():
            if method_name not in set(special) | extra:
                logger.warning("%s.%s() isn't one of the known special "
                               "methods %s" % (
                                   self, method_name, ', '.join(special)))
                continue

            arg_names, kwarg_names = self.__init_method_args(
                    method, no_node_arg=special.get(method_name, False))
            self._method_map[method_name] = (method, arg_names, kwarg_names)

        # collect all [_]visit_xxx() methods; use isroutine() rather than
        # ismethod() because ismethod() checks only for _bound_ methods
        # XXX if we don't look for _visit_xxx() methods, this could be simpler
        known = {'_visit_begin', '_visit_node', '_visit_pre_elems',
                 '_visit_pre_group', '_visit_post_group', '_visit_post_elems',
                 '_visit_end'}
        methods = {n: v for n, v in dct.items() if
                   re.match(r'_?visit_', n) and
                   inspect.isroutine(v) and n not in known}

        # check that they all correspond to known node or mixin classes
        for method_name, method in methods.items():
            typename = re.sub(r'^_?visit_', r'', method_name)
            node_class = _Node.typenamed(typename)
            if node_class is None:
                logger.warning("%s.%s() doesn't correspond to a node or "
                               "mixin class" % (self, method_name))
                continue

            # XXX can't have multiple methods with the same varname
            # XXX should use 'visit_<vname>' so the names are the same as
            #     the function names in the standalone case, e.g., lint.py
            #     ('_begin_' and '_base' look a bit similar)
            vname = varname(node_class)
            if vname in self._method_map:
                logger.warning("%s.%s() duplicates %s() and will be ignored"
                               % (self, method_name,
                                  self._method_map[vname][0].__name__))
                continue

            # XXX prefer visit_data_type() but allow visit_DataType() for now
            if typename != vname:
                # XXX more importantly, if multiple versions exist only the
                #     first will be called! should keep a list keyed by vname
                logger.warning("%s.%s() is deprecated; please rename it as "
                               "visit_%s()" % (self, method_name, vname))

            # XXX prefer visit_xxx() but allow _visit_xxx() for now
            if method_name.startswith('_'):
                logger.warning("%s.%s() method name is deprecated; please "
                               "rename it as %s()" % (self, method_name,
                                                      method_name[1:]))

            # allow static and class methods to be supported; see
            # https://stackoverflow.com/questions/41921255
            if not inspect.isfunction(method):
                method = method.__func__

            # get the method arg names
            arg_names, kwarg_names = self.__init_method_args(method)

            # update the method map
            self._method_map[vname] = (method, arg_names, kwarg_names)

    @staticmethod
    def __init_method_args(method: Callable, *, no_node_arg: bool = False) -> \
            Tuple[List[str], List[str]]:
        # known method argument names (assumes conventional use of 'cls' and
        # 'self' for class and instance arguments); the node argument is
        # assumed to be the first positional argument after 'cls' and 'self'
        # (if present); it can be called anything (other that 'cls' etc.)
        known_arg_names = ['cls', 'self', 'node']
        known_kwarg_names = ['level', 'state', 'rules', 'args', 'logger']

        seen_node = False
        arg_names = []
        kwarg_names = []
        parameters = inspect.signature(method).parameters
        for name, parameter in parameters.items():
            if no_node_arg:
                pass
            elif not seen_node and name not in known_arg_names:
                name = 'node'
            if name == 'node':
                seen_node = True

            kind = parameter.kind
            if kind in {parameter.POSITIONAL_ONLY,
                        parameter.POSITIONAL_OR_KEYWORD}:
                arg_names.append(name)
            elif kind == parameter.KEYWORD_ONLY:
                kwarg_names.append(name)
            elif kind == parameter.VAR_POSITIONAL:
                arg_names.extend([arg for arg in known_arg_names if arg not
                                  in arg_names])
            elif kind == parameter.VAR_KEYWORD:
                kwarg_names.extend([arg for arg in known_kwarg_names if arg
                                    not in known_arg_names])
            else:
                logger.error('unexpected parameter kind %s' % kind)

        return arg_names, kwarg_names

    def __init_type_map(self) -> None:
        for name, node_class in _Node.typedict().items():
            # noinspection PyArgumentList
            node_class_mro = node_class.mro()
            while node_class_mro and node_class_mro[0] is not object:
                base_class = cast(NodeOrMixinType, node_class_mro.pop(0))
                vname = varname(base_class)
                method, _, _ = self._method_map.get(vname, 3 * (None,))
                if method is not None:
                    self._type_map.setdefault(node_class, [])
                    if vname not in self._type_map[node_class]:
                        self._type_map[node_class].append(vname)

    # this is called after all arguments are available (the constructor is
    # called before the plugins and command-line files have been specified)
    # XXX need to specify that a True return will abort
    # XXX could this be called __post_init__() or would this be naughty?
    def post_init(self, args) -> bool:
        # invoke the standalone _post_init_() function if defined
        return self._invoke('_post_init_', args=args)

    def visit(self, node: Node, *, level: int = 0,
              rules: Optional[Rules] = None, state: Optional[Any] = None,
              omit_if_unused: bool = False, **kwargs) -> None:
        """Visit a node and its children.

        This is called for all nodes at all levels of the node tree. It
        contains all the node traversal logic.

        Outline::

            If node.parent is None:
                _visit_begin(node)

            _visit_node(node)

            for child in node.elems:
                visit(child)    # recursive call of this method!

            if node.parent is None:
                _visit_end(node)

        The outline mentions `Visitor._visit_begin()`, `Visitor._visit_node()`
        and `Visitor._visit_end()` but it doesn't mention
        `Visitor._visit_pre_elems()`, `Visitor._visit_pre_group()`,
        `Visitor._visit_post_group()` or `Visitor._visit_post_elems()`. It also
        doesn't mention how the rules affect the processing. Please refer to
        the individual method descriptions for further details.

        Args:
            node: The node to visit.
            level: The node nesting level (depth).
            rules: Node traversal rules. These are typically supplied by the
                caller but, if not, are constructed by creating a `Rules`
                instance with ``thisonly=node.args.thisonly``.
            state: Opaque state object.
            omit_if_unused: Whether to omit unused nodes.
            **kwargs: Additional keyword arguments. These are passed to all
                ``_visit_xxx()`` methods.
        """

        # XXX this was 'rules = rules or Rules()' but I have a feeling that's
        #     a no-no (can't quite see why at the moment)
        if rules is None:
            rules = Rules(thisonly=node.args.thisonly)

        # XXX need to review use of state; at one point it was per-node, and
        #     maybe this is correct and should be reinstated?
        # XXX this default constrains state to be a dict
        if state is None:
            state = {}

        # XXX many transforms and formats will be of the simple <xxx.py>
        #     style, and so won't implement _visit_begin(); need a better way
        #     for them to control things, e.g., so visit_root() can choose to
        #     abort node traversal

        # don't use level, because it can be zero if top-level node is ignored
        # XXX it might be better to call it only on Root objects
        if node.parent is None:
            root = cast(Root, node)

            # invoke the standalone visit() function if defined
            if 'visit' in self._method_map:
                return self._invoke('visit', node=root, args=root.args,
                                    omit_if_unused=omit_if_unused, **kwargs)

            # _visit_begin() can return True to suppress the report
            retval = self._visit_begin(root, rules=rules, state=state,
                                       omit_if_unused=omit_if_unused, **kwargs)
            if isinstance(retval, bool):
                if retval:
                    return
            # otherwise it can return rules
            elif isinstance(retval, Rules):
                rules = retval
            # XXX otherwise should be an error?

        # note that 'node.is_used is False' excludes 'node.is_used is None',
        # and that we don't check node.args.all here because it presumably
        # determined omit_if_unused in the first place
        # XXX do we need to provide control over whether this is called
        #     before or after its children?
        typename = node.typename
        is_hidden = node.is_hidden
        ignore = typename in rules.ignore or \
            (omit_if_unused and node.is_used is False)
        stop = typename in rules.stop
        retval = self._visit_node(node, level=level, rules=rules, state=state,
                                  omit_if_unused=omit_if_unused, **kwargs) \
            if not is_hidden and not ignore else None

        # backwards compatibility: if retval is a tuple, assume that it's
        # (ignore, stop, _)
        # XXX used to support state as the third item but this was error-prone
        #     because it replaced state with a new variable
        # XXX should also support just ignore, or ignore and stop?
        if isinstance(retval, tuple):
            assert len(retval) == 3
            ignore, stop, _ = retval
        elif retval is not None:
            # XXX will get rid of this once it's safe to do so
            assert False, '_visit_node() returned no-longer-supported %r' % \
                          retval

        # note that this is called even if stopping
        self._visit_pre_elems(node, level=level, rules=rules, state=state,
                              omit_if_unused=omit_if_unused, **kwargs)

        if not is_hidden and not stop:
            level1 = level + (0 if ignore else 1)

            groups = self.__groups(node, rules=rules)
            for groupname, group in groups.items():

                if groupname:
                    self._visit_pre_group(node, groupname, level=level1,
                                          rules=rules, state=state,
                                          omit_if_unused=omit_if_unused,
                                          **kwargs)

                for elem in group:
                    self.visit(elem, level=level1, rules=rules, state=state,
                               omit_if_unused=omit_if_unused, **kwargs)

                if groupname:
                    # this is the overrideable method
                    self._visit_post_group(node, groupname, level=level1,
                                           rules=rules, state=state,
                                           omit_if_unused=omit_if_unused,
                                           **kwargs)
                    # this is an internal method that contains accessor logic
                    self.__visit_post_group(node, groupname, level=level1,
                                            rules=rules, state=state,
                                            omit_if_unused=omit_if_unused,
                                            **kwargs)

        # note that this is called even if stopping
        self._visit_post_elems(node, level=level, rules=rules,
                               state=state, omit_if_unused=omit_if_unused,
                               **kwargs)

        # XXX see note to _visit_end(); should call only on Root?
        if node.parent is None:
            self._visit_end(cast(Root, node), rules=rules, state=state,
                            omit_if_unused=omit_if_unused, **kwargs)

    # XXX need to review these callbacks; right ones? too few? too many?

    def _visit_begin(self, root: Root, **kwargs) -> Union[bool, Rules]:
        """Visitor method called before node traversal.

        The default implementation returns ``False``.

        Args:
            root: The root node.
            **kwargs: Additional keyword arguments.

        Returns:
            Either a bool indicating whether to abort node traversal (in
            which case no other visitor methods will be called), or a `Rules`
            instance to be used for node traversal.
        """

        # invoke the standalone _begin_() function if defined
        retval = self._invoke('_begin_', node=root, args=root.args, **kwargs)
        if isinstance(retval, bool):
            return retval

        # don't return True by default because that would require all plugins
        # to implement this method
        return False

    # XXX the 'Returns' section is incorrect; need to sort out state
    def _visit_node(self, node: Node, *, level: int = 0,
                    rules: Optional[Rules] = None, state: Optional[Any] = None,
                    **kwargs) -> None:
        """Visitor method called to visit each node.

        The default implementation calls the most specific defined
        ``_visit_typename()`` method. This can be a static method, a class
        method or an instance method, and it expects a ``Node`` argument and
        (optionally) ``level``, ``rules`` and any other supplied keyword
        arguments.

        For example, suppose that a plugin defines the ``_visit_description()``
        and ``_visit_content()`` methods. ``_visit_description()`` will be
        called for a `Description` node, but the less-specific
        ``_visit_content()`` will be called for a `Template` node.

        Alternatively, a plugin can implement its own version of
        ``_visit_node()``, which will be called for every node.

        Args:
            node: The node.
            level: The node nesting level (depth).
            rules: The `Rules` instance.
            **kwargs: Additional keyword arguments.

        Returns:
            Opaque ``state`` object, which is called as the ``state``
            argument to subsequent visitor methods.

            Alternatively (for backwards compatibility), a three element
            ``(ignore, stop, state)`` tuple.
        """

        # _invoke() adds the 'cls', 'self' and 'logger' known args
        known_args = {'node': node, 'level': level, 'rules': rules,
                      'state': state, 'args': node.args} | kwargs

        retval = None
        for vname in self._type_map.get(type(node), []):
            retval = self._invoke(vname, **known_args)
        return retval

    def _visit_pre_elems(self, node: Node, *, level: int = 0,
                         rules: Optional[Rules] = None, state: Any = None,
                         **kwargs) -> None:
        """Visitor method called before visiting each node's child nodes.

        The default implementation does nothing.

        Args:
            node: The node.
            level: The node nesting level (depth).
            rules: The `Rules` instance.
            state: The opaque state returned from `Visitor._visit_node()`.
            **kwargs: Additional keyword arguments.
        """

        # invoke the standalone _pre_elems_() function if defined
        self._invoke('_pre_elems_', node, level=level, rules=rules,
                     state=state, args=node.args, **kwargs)

    def _visit_pre_group(self, node: Node, groupname: str, *, level: int = 0,
                         rules: Optional[Rules] = None, state: Any = None,
                         **kwargs) -> None:
        """Visitor method called before visiting each group's nodes.

        Each node's child nodes are split into groups based on the
        information in `Rules.order`. The default order should be a valid DM
        Schema order.

        The default implementation does nothing.

        Args:
            node: The node.
            groupname: The group name.
            level: The node nesting level (depth).
            rules: The `Rules` instance.
            state: The opaque state returned from `Visitor._visit_node()`.
            **kwargs: Additional keyword arguments.
        """

        # invoke the standalone _pre_group_() function if defined
        self._invoke('_pre_group_', node, groupname, level=level,
                     rules=rules, state=state, args=node.args, **kwargs)

    def _visit_post_group(self, node: Node, groupname: str, *, level: int = 0,
                          rules: Optional[Rules] = None, state: Any = None,
                          omit_if_unused: bool = False, **kwargs) -> None:
        """Visitor method called after visiting each group's nodes.

        Each node's child nodes are split into groups based on the
        information in `Rules.order`. The default order should be a valid DM
        Schema order.

        Args:
            node: The node.
            groupname: The group name.
            level: The node nesting level (depth).
            rules: The `Rules` instance.
            state: The opaque state returned from `Visitor._visit_node()`.
            **kwargs: Additional keyword arguments.
        """

        # invoke the standalone _post_group_() function if defined
        self._invoke('_post_group_', node, groupname, level=level, rules=rules,
                     state=state, omit_if_unused=omit_if_unused,
                     args=node.args, **kwargs)

    # internal version that's called just after the above; uses accessors to
    # visit global items
    # noinspection PyUnusedLocal
    def __visit_post_group(self, node: Node, groupname: str, *, level: int = 0,
                           rules: Optional[Rules] = None, state: Any = None,
                           omit_if_unused: bool = False, **kwargs) -> None:
        # ignore if this isn't one of the typenames for which to generate
        # global lists
        if groupname not in rules.default_globs:
            return

        # XXX experimental logic moved from xmlFormat.py; need explanation!
        from .format import Format
        rules = Rules(thisonly=True)
        omit_if_unused = not node.args.all and isinstance(self, Format)

        # try to find the corresponding accessor class
        # XXX this displays too much knowledge of the class names
        accessor = cast(_Accessor, node.typenamed('%sAccessor' % groupname))

        # if found, get entities from the accessor
        if accessor:
            entities = accessor.entities.values()
            for name, instance in entities:
                # XXX hack to avoid visiting primitive data types when
                #     generating XML (this isn't the right way to do it!)
                if groupname != 'dataType' or self.name() != 'xml' or  \
                        not re.match(r'^[a-z]', name):
                    self.visit(instance, level=level, rules=rules, state=state,
                               omit_if_unused=omit_if_unused, name=name,
                               **kwargs)

        # otherwise use all instances of the given type
        else:
            instances = node.findall(groupname)
            for instance in instances:
                self.visit(instance, level=level, rules=rules, state=state,
                           omit_if_unused=omit_if_unused, **kwargs)

    def _visit_post_elems(self, node, *, level=0, rules=None, state=None,
                          **kwargs) -> None:
        """Visitor method called after visiting each node's child nodes.

        The default implementation does nothing.

        Args:
            node: The node.
            level: The node nesting level (depth).
            rules: The `Rules` instance.
            state: The opaque state returned from `Visitor._visit_node()`.
            **kwargs: Additional keyword arguments.
        """

        # invoke the standalone _post_elems() function if defined
        self._invoke('_post_elems_', node, level=level, rules=rules,
                     state=state, args=node.args, **kwargs)

    def _visit_end(self, root: Root, **kwargs) -> None:
        """Visitor method called after node traversal.

        Note that this isn't called if `Visitor._visit_begin()` returned
        ``True``.

        The default implementation does nothing.

        Args:
            root: The root node.
            **kwargs: Additional keyword arguments.
        """

        # invoke the standalone _end_() function if defined
        self._invoke('_end_', root, args=root.args, **kwargs)

    # XXX should we attempt to define missing args argument as node.args?
    def _invoke(self, vname: str, *known_args, **known_kwargs) -> Any:
        retval = None

        known_arg_index = 0

        # XXX should move this outside the method?
        def next_known_arg():
            nonlocal known_arg_index
            if known_arg_index < len(known_args):
                known_arg = known_args[known_arg_index]
                known_arg_index += 1
            else:
                known_arg = None
            return known_arg

        if vname in self._method_map:
            known_kwargs_ = {'cls': type(self), 'self': self,
                             'logger': self.logger or logger} | known_kwargs
            method, arg_names, kwarg_names = self._method_map[vname]
            method_args = tuple(known_kwargs_.get(name) or next_known_arg() for
                                name in arg_names)
            method_kwargs = {name: known_kwargs_.get(name, None) for name in
                             kwarg_names if name not in arg_names}
            retval = method(*method_args, **method_kwargs)
            if 'state' in known_kwargs_ and retval is not None:
                known_kwargs_['state'] = retval
        return retval

    # XXX might want to assign trailing comment and other to the next group
    @classmethod
    def __groups(cls, node: Node, *, rules: Optional[Rules] = None) -> Dict[
            str, List[Node]]:
        assert rules is not None
        firstname = '_first'
        typename = node.typename
        order = rules.order
        elemtypes = order[typename] if order and typename in order else ()
        groups = dict((g, []) for g in (firstname,) + elemtypes)
        groupname = firstname
        for elem in node.elems:
            elemtype = elem.typename
            if elemtype in groups:
                groupname = elemtype
            groups.setdefault(groupname, [])
            groups[groupname] += [elem]
        return groups
