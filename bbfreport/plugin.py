"""Plugin support."""

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

import argparse
import importlib
import inspect
import os
import re
import sys

from types import ModuleType

from typing import Any, cast, Self

from .exception import PluginException
from .logging import Logging

logger = Logging.get_logger(__name__)


class Plugin:
    """Plugin base class."""

    # only .register() and .filter() access the plugin registry
    __plugins: dict[tuple[str, str], tuple[type[Plugin],
                                           ModuleType | None]] = {}

    @classmethod
    def is_known_method_name(cls, name: str) -> bool:
        return name in {'_add_arguments_'}

    @classmethod
    def import_all(cls, *, plugindirs: list[str] | None = None,
                   nocurdir: bool = False) -> None:
        """Import all plugins from the current directory (unless suppressed
        via ``nocurdir``) and the supplied plugin directories.

        Args:
            plugindirs: The plugin directories.
            nocurdir: Whether not to search the current directory.
        """

        dirs, sys_path_save = cls.push_plugindirs(
                plugindirs=plugindirs, nocurdir=nocurdir)

        for dir_, quiet in dirs:
            logger.info('scanning %s%s' % (
                dir_, ' (quiet}' if quiet else ''))

            try:
                files = sorted(os.listdir(dir_))
            except OSError as e:
                logger.error("can't scan %s: %s" % (dir_, e))
                continue

            for file in files:
                if cls.file_matches(file, quiet=quiet):
                    path = os.path.join(dir_, file)
                    if module := cls.import_one(file, path=path):
                        logger.debug('imported %s from %s' % (
                            module.__name__, module.__file__))

        cls.pop_plugindirs(sys_path_save)

    # each returned dir is a (dir: str, quiet: bool) tuple
    @classmethod
    def push_plugindirs(cls, *, plugindirs: list[str] | None = None,
                        nocurdir: bool = False) -> \
            tuple[list[tuple[str, bool]], list[str]]:

        # package and plugins directories
        package_dir = os.path.dirname(__file__)
        plugins_subdir = cls.__module__.split('.')[-1] + 's'

        # will search the current directory (not warning of non-matching
        # files) unless suppressed
        dirs = [(os.curdir, True)] if not nocurdir else []

        # will search the supplied plugin dirs
        if plugindirs:
            dirs.extend((dir_, False) for dir_ in plugindirs)

        # will search the package plugins dir
        dirs.append((os.path.join(package_dir, plugins_subdir), False))

        # save sys.path and prefix it with the plugin search directories
        sys_path_save = sys.path[:]
        sys.path = [dir_ for dir_, _ in dirs] + sys_path_save

        return dirs, sys_path_save

    # XXX it's not really necessary to restore the path?
    @classmethod
    def pop_plugindirs(cls, sys_path_save: list[str]) -> list[str]:
        sys.path = sys_path_save[:]
        return sys.path

    @classmethod
    def file_matches(cls, file: str, *, quiet: bool = False) -> bool:
        # ignore hidden files
        if file.startswith('.'):
            return False

        # ignore __init__.py
        elif file == '__init__.py':
            return False

        # non python files never match
        elif not file.endswith('.py'):
            return False

        # other file names have to match the pattern
        else:
            match = Logging.name_pattern.match(file)
            if not quiet:
                if not match:
                    logger.warning('unexpected non-matching file name %s' %
                                   file)
                elif file != cls.get_canonical_name(file, is_file=True):
                    logger.warning('deprecated old-style file name %s' % file)
            return bool(match)

    @classmethod
    def import_one(cls, file: str, *, path: str | None = None,
                   quiet: bool = False) -> ModuleType | None:
        assert file.endswith('.py')
        name = file[:-3]
        path = path or file
        logger.debug('importing %s from %s (in module hierarchy)' % (
            name, path))

        # helper for formatting an exception
        def exc_str(exc: Exception) -> str:
            text = type(exc).__name__
            if str(exc):
                text += ': %s' % exc
            return text

        # try to import the module
        logger_func = logger.debug if quiet else logger.warning
        # noinspection PyBroadException
        try:
            # this only works for built-in plugins
            package = cls.__module__ + 's'
            try:
                module = importlib.import_module('.%s' % name, package)
            except ModuleNotFoundError:
                module = importlib.import_module('.%s' % name,
                                                 package + '.examples')

        except ModuleNotFoundError as e:
            logger.debug('%s: importing %s from %s (as top-level module)' % (
                exc_str(e), name, path))

            # this is needed for external plugins
            # XXX it creates top-level modules whose names could in theory
            #     conflict with other top-level modules
            try:
                module = importlib.import_module(name)
            except Exception as e:
                logger_func('%s: failed to import %s from %s' % (
                    exc_str(e), name, path))
                return None

        except Exception as e:
            logger_func('%s: failed to import %s from %s' % (
                exc_str(e), name, path))
            return None

        # the module has now been imported
        assert module is not None

        # register plugin classes (the module name check distinguishes
        # imported classes from classes defined within the module)
        def is_plugin_class(obj: Any) -> bool:
            return inspect.isclass(obj) and issubclass(obj, Plugin) and \
                obj.__module__ == module.__name__
        plugin_classes = inspect.getmembers(module, is_plugin_class)
        if plugin_classes:
            for plugin_name, plugin_class in plugin_classes:
                fallback_type = plugin_class.__bases__[0].__name__
                name_and_type = \
                    cls.get_name_and_type(cls.get_canonical_name(
                            plugin_name, fallback_type=fallback_type))
                # plugin_class is XMLFormat etc.; module is None
                cls.register(name_and_type, plugin_class, None)

        # register plugin modules (defined via top-level functions)
        else:
            name_and_type = cls.get_name_and_type(cls.get_canonical_name(name))
            plugin_name, plugin_type = name_and_type
            plugin_class = cls.get_plugin_class(plugin_type)
            # the plugin class will exist, because we never get here if the
            # file name doesn't match the pattern
            assert plugin_class is not None, \
                "unsupported plugin type %s, so can't look up its plugin " \
                "class" % plugin_type
            # plugin_class is Format etc.; module is not None
            cls.register(name_and_type, plugin_class, module)

        # return the module
        return module

    # only .register() and .filter() access the plugin registry
    @classmethod
    def register(cls, name_and_type: tuple[str, str] | None = None,
                 plugin_class: type[Plugin] | None = None,
                 module: Any | None = None) -> None:
        """Register this plugin."""

        # all arguments are optional, in order to accommodate auto-
        # registrations such as parser.py ParserParser.register()
        if plugin_class is None:
            plugin_class = cls

        if name_and_type is None:
            name_and_type = cls.get_name_and_type(
                    cls.get_canonical_name(plugin_class.__name__))

        if name_and_type in cls.__plugins:
            logger.warning('duplicate plugin; ignoring already-registered '
                           '%s %s' % name_and_type)

        cls.__plugins[name_and_type] = (plugin_class, module)

        plugin_name, plugin_type = name_and_type
        extra = ' (%s)' % module if module is not None else ''
        logger.info('registered %s %s = %s%s' % (
            plugin_name, plugin_type, plugin_class, extra))

    # only .register() and .filter() access the plugin registry
    @classmethod
    def filter(cls, name: str | None = None) -> \
            list[tuple[str, type[Plugin], ModuleType | None]]:
        result = []

        for (plugin_name, plugin_type), (plugin_class, module) \
                in cls.__plugins.items():
            # discard if the type doesn't match the class, e.g., 'format'
            # or 'transform'
            if plugin_type != cls.__name__.lower():
                continue

            # discard if filtering on name, and the name doesn't match
            if name is not None and plugin_name != name:
                continue

            # add a (name, class, module) tuple to the return value
            result.append((plugin_name, plugin_class, module))

        return result

    @classmethod
    def add_arguments(cls, arg_parser: argparse.ArgumentParser) -> \
            dict[str, list[str]]:
        """Add plugin-specific arguments to the supplied argument parser."""

        option_strings: dict[str, list[str]] = {}
        errors: dict[str, list[str]] = {}
        for name, class_, module in cls.filter():
            # option strings must match this pattern
            prefix = re.compile(rf'--{re.escape(name)}')
            # noinspection PyProtectedMember
            arg_group = class_._add_arguments(arg_parser, module=module)

            if arg_group is not None:
                # XXX there's no public interface for listing group actions
                # noinspection PyProtectedMember
                for action in arg_group._group_actions:
                    # update the plugin name to option string map
                    # (this is used for auto-enabling plugins)
                    option_strings.setdefault(name, [])
                    for option_string in action.option_strings:
                        option_string = cast(str, option_string)
                        option_strings[name].append(option_string)

                    options = action.option_strings or [action.dest]
                    options = cast(list[str], options)
                    invalid = [opt for opt in options if
                               not prefix.match(opt)]
                    if invalid:
                        errors.setdefault(name, [])
                        errors[name].extend(invalid)
        if errors:
            errors_ = '; '.join(
                    '%s: %s' % (key, ', '.join(val)) for key, val in
                    errors.items())
            raise PluginException('invalid plugin argument names (must begin '
                                  'with --<plugin>) %s' % errors_)
        return option_strings

    # return type is argparse._ArgumentGroup but this definition isn't
    # exported and so can't be declared
    @classmethod
    def _add_arguments(cls, arg_parser: argparse.ArgumentParser, *,
                       module: ModuleType | None = None, **kwargs: Any) \
            -> Any | None:
        """Add plugin-specific arguments, by calling the arg_parser
        add_argument_group() method.

        Derived classes that wish to add arguments should override this method.

        All new argument names must start with the lower-case plugin name,
        e.g. the ``text`` format might add a ``--text-book`` argument.
        """

        routines = {n: v for n, v in
                    inspect.getmembers(module, inspect.isroutine)}
        return routines['_add_arguments_'](arg_parser) if \
            '_add_arguments_' in routines else None

    @classmethod
    def create(cls, name: str, **kwargs: Any) -> Self | None:
        """Create an instance of the named plugin of the type of the class on
        which the method was invoked.

        For example, ``Format.create('xml')``.

        Args:
            name: Plugin name, e.g. ``xml``.

        Returns:
            The plugin instance, or ``None`` if no plugin with this name has
            been registered.
        """

        # filter plugins with cls's type and the specified name
        result = cls.filter(name)
        if len(result) != 1:
            return None

        # extract the constructor and module (which might be None)
        _, ctor, module = result[-1]

        # create the instance
        return cast(cls, ctor(module=module, **kwargs))

    @classmethod
    def items(cls, *, exclude: list[str] | None = None) -> tuple[str, ...]:
        """Get a tuple of names of plugins of the type of the class on which
        the method was invoked.

        For example, ``Transform.items()``.
        """

        if exclude is None:
            exclude = []

        return tuple(sorted(name for name, _, _ in cls.filter()
                            if name not in exclude))

    @classmethod
    def get_plugin_class(cls, plugin_type: str) -> type[Plugin] | None:
        # helper for (recursively) getting a class and all of its subclasses
        def get_subclasses(plugin_class: type) -> dict[str, type[Plugin]]:
            result = {plugin_class.__name__: plugin_class}
            for subclass in plugin_class.__subclasses__():
                result |= get_subclasses(subclass)
            return result

        subclasses = get_subclasses(cls)
        plugin_class_name = plugin_type.capitalize()
        return subclasses.get(plugin_class_name, None)

    @classmethod
    def get_canonical_name(cls, name: str, *, is_file: bool = False,
                           fallback_type: str = 'Plugin') -> str:
        """Convert a module name, class name or file name to an all lower-case
        ``name-type`` canonical name, e.g., ``expat-parser``."""

        # if the name is an a.b.c module name, extract just the last component
        if not is_file:
            name, ext = name.split('.')[-1], ''
        else:
            name, ext = os.path.splitext(name)

        # if this doesn't match the name pattern, use the fallback type
        if not (match := Logging.name_pattern.match(name)):
            name_part, type_part = name, fallback_type
        else:
            name_part, type_part = match['name'], match['type']

        # the canonical name is 'name-type[.ext]', converted to lower-case
        return '%s-%s%s' % (name_part.lower(), type_part.lower(), ext)

    @classmethod
    def get_name_and_type(cls, canonical_name: str) -> tuple[str, str]:
        assert '-' in canonical_name, \
            'invalid canonical plugin name %s; did you get it from ' \
            '%s.get_canonical_name()?' % (canonical_name, cls.__name__)
        plugin_name, plugin_type = canonical_name.rsplit('-', 1)
        return plugin_name, plugin_type

    @classmethod
    def name(cls) -> str:
        """Get the plugin's name, e.g. ``xml``."""

        return cls.get_name_and_type(cls.get_canonical_name(cls.__name__))[0]

    def __init__(self, name: str | None = None, *, module: Any | None = None,
                 args: Any | None = None, **kwargs: Any):
        self._name = name
        cast(Any, module)
        cast(Any, args)
        assert not kwargs, 'unexpected keyword arguments: %s' % kwargs

    # there's no name accessor, because of the .name() class method; however
    # __str__() returns ._name if it's defined

    def __str__(self) -> str:
        """Return the plugin name, e.g. ``xml``."""
        return self._name or self.name()

    def __repr__(self) -> str:
        return "%s(%s)" % (type(self).__name__, self)
