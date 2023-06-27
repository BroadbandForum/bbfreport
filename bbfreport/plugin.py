"""Plugin support."""

# Copyright (c) 2019, Broadband Forum
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

import argparse
import importlib
import inspect
import logging
import os
import re
import sys

from typing import Any, Dict, List, Optional, Tuple, Type

from .exception import PluginException
from .utility import Utility

logger_name = __name__.split('.')[-1]
logger = logging.getLogger(logger_name)
logger.addFilter(
        lambda r: r.levelno > 20 or logger_name in Utility.logger_names)


class Plugin:
    """Plugin base class.

    Note:
        All plugins (parsers, transforms and formats) are in a single
        namespace. The plugin name omits its class name's trailing ``Parser``,
        ``Transform`` or ``Format``).
    """

    # registered plugins
    __plugins: Dict[str, Type['Plugin']] = {}

    # imported modules
    # XXX how to refer to a module object?
    __imported: Dict[str, Any] = {}

    # XXX should we support an os.pathsep-separated path?
    # XXX should the current directory be searched automatically?
    # XXX should directories be searched recursively? note that python doesn't
    #     search sys.path directories recursively (example plugins are in
    #     plugins/examples)
    @classmethod
    def import_all(cls, *, plugindirs: Optional[List[str]] = None,
                   quiet: Optional[bool] = None) -> None:
        """Import all plugins from the supplied plugin directories (if any)
        and ``sys.path``.

        Args:
            plugindirs: The plugin directories.
            quiet: Whether to report import failures at the debug rather
                than info level.
        """

        dirs, sys_path_save = cls.push_plugindirs(plugindirs)

        for dir_ in dirs:
            logger.debug('scanning %s for plugins' % dir_)
            try:
                files = sorted(os.listdir(dir_))
            except OSError:
                continue
            for file in files:
                if not file.startswith('.') and \
                        re.search(r'(Parser|Transform|Format)\.py$', file):
                    path = os.path.join(dir_, file)
                    quiet_ = quiet if quiet is not None else \
                        path.endswith('Parser.py')
                    if module := cls.import_one(file, path=path, quiet=quiet_):
                        logger.debug('imported %s from %s' % (
                            module.__name__, module.__file__))

        cls.pop_plugindirs(sys_path_save)

    # XXX I think that this is questionable
    @classmethod
    def push_plugindirs(cls, plugindirs: Optional[List[str]] = None) -> \
            Tuple[List[str], List[str]]:
        plugindirs = plugindirs or []
        sys_path_save = sys.path[:]
        dirs = plugindirs + [os.path.join(dir_, 'bbfreport', 'plugins') for
                             dir_ in sys_path_save if
                             not dir_.endswith('.zip')]
        sys.path = dirs + sys_path_save
        return dirs, sys_path_save

    # XXX it's not really necessary to restore the path; could just modify it
    #     once at startup?
    @classmethod
    def pop_plugindirs(cls, sys_path_save: List[str]) -> List[str]:
        sys.path = sys_path_save[:]
        return sys.path

    # XXX what should the returned type be?
    @classmethod
    def import_one(cls, file: str, *, path: Optional[str] = None,
                   quiet: bool = False) -> Any:
        assert file.endswith('.py')
        name = file[:-3]
        path = path or file
        logger.debug('importing %s from %s' % (name, path))

        # check whether the module has already been imported
        if file in cls.__imported:
            path, module = cls.__imported[file]
            logger.debug('already imported %s from %s' % (name, path))
            return module

        # try to import it
        try:
            # this only works for built-in plugins
            # XXX for external plugin PLUGIN it says No module named
            #     bbfreport.plugins.PLUGIN (need to create it?)
            module = importlib.import_module('.%s' % name,
                                             'bbfreport.plugins')
        except ModuleNotFoundError as e:
            # this is needed for external, e.g. WT-473, plugins; it creates
            # top-level modules whose names could in theory conflict with
            # other top-level modules
            logger.debug('failed to import %s from %s: %s (will try importing '
                         'as top-level module)' % (name, path, e))
            try:
                module = importlib.import_module(name)
            except ModuleNotFoundError as e:
                func = logger.debug if quiet else logger.warning
                func('failed to import %s from %s: %s' % (name, path, e))
                module = None

        # auto-register the plugin(s) and note that the file's been imported
        # XXX there's too high a chance that an arbitrary file will be
        #     imported; shouldn't search for plugins in PYTHONPATH?
        if module is not None:
            def isplugin(obj):
                return inspect.isclass(obj) and issubclass(obj, Plugin)

            classes = inspect.getmembers(module, isplugin)
            for _, class_ in classes:
                if class_.name(no_fallback=True) != '':
                    class_.register()

            cls.__imported[file] = (path, module)
        return module

    @classmethod
    def register(cls) -> None:
        """Register this plugin."""

        name = cls.name()
        assert name not in cls.__plugins or cls.__plugins[name] == cls, \
            'the %r plugin has already been registered' % name
        cls.__plugins[name] = cls
        logger.debug('registered plugin %r = %s' % (name, cls.__name__))

    @classmethod
    def add_arguments(cls, arg_parser: argparse.ArgumentParser) -> None:
        """Add plugin-specific arguments to the supplied argument parser."""

        errors = {}
        # note this iterates over the derived classes of the cls argument
        for plugin_cls in cls.items():
            name = plugin_cls.name().lower()
            prefix = f'--{name}-'
            arg_group = plugin_cls._add_arguments(arg_parser)
            if arg_group is not None:
                # XXX is there a public interface to list group actions?
                # noinspection PyProtectedMember
                for action in arg_group._group_actions:
                    options = action.option_strings or [action.dest]
                    invalid = [opt for opt in options if
                               not opt.startswith(prefix)]
                    if invalid:
                        errors.setdefault(name, [])
                        errors[name] += invalid
        if errors:
            # XXX should format the errors; they're rather cryptic
            raise PluginException("Please ask plugin author(s) to fix "
                                  "these invalid options; option names need "
                                  "to begin '--<plugin>-': %r" % errors)

    # XXX returns argparse._ArgumentGroup but this definition isn't exported
    @classmethod
    def _add_arguments(cls, arg_parser: argparse.ArgumentParser) -> \
            Optional[Any]:
        """Add plugin-specific arguments, by calling the arg_parser
        add_argument_group() method.

        Derived classes that wish to add arguments should override this method.

        All new argument names must start with the lower-case plugin name
        followed by a hyphen, e.g. the ``text`` format might add a
        ``--text-book`` argument.
        """
        return None

    @classmethod
    def create(cls, name: str, **kwargs) -> Optional['Plugin']:
        """Create an instance of the specified plugin.

        Args:
            name: Plugin name, e.g. ``xml``.

        Returns:
            The plugin instance, or ``None`` if no plugin with this name has
            been registered.
        """

        # if a plugin with this name has been registered, use the registered
        # constructor and don't pass name
        if ctor := cls.__plugins.get(name):
            return ctor(**kwargs)

        # otherwise if the class has been registered, use the class
        # constructor and pass name (which is likely to be a file name)
        elif ctor := cls.__plugins.get(cls.__name__):
            return ctor(name, **kwargs)

        # otherwise fail
        else:
            return None

    # XXX all this class name logic may be a bad idea?
    @classmethod
    def name(cls, *, no_fallback: bool = False) -> str:
        """Get the plugin's name, e.g. ``xml``."""

        # split class name into plugin name and plugin type
        name = cls.__name__
        match = re.match(r'^_?(.*)([A-Z][a-z]+)$', name)
        assert match, f"invalid plugin class name {name!r}; must be of the " \
                      f"form 'fooGooSmasher', where 'fooGoo' is the plugin " \
                      f"name and 'Smasher' is the plugin type"
        name_, type_ = match.groups()

        # if the name is empty this is the plugin base type, so return the
        # class name (sans leading underscore)
        return name_.lower() or (type_ if not no_fallback else '')

    @classmethod
    def items(cls, types=None, *, nobase=None, nohidden=False):
        """Get a tuple of plugin class objects of the specified type or
        types (by default of the type of the class on which the method was
        invoked)."""

        types = types or cls
        return tuple(p for p in cls.__plugins.values() if
                     issubclass(p, types) and (
                         (not nobase or p.__name__ != cls.__name__) and
                         (not nohidden or p.__name__[:1] != '_')))

    # XXX should warn if there are any keyword arguments?
    def __init__(self, name: Optional[str] = None, **kwargs):
        self._name = name

    def __str__(self):
        """Return the plugin name, e.g. ``xml``."""
        return self._name or self.name()

    def __repr__(self):
        return "%s('%s')" % (type(self).__name__, self)
