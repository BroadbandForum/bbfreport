"""Macro utilities."""

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

import numbers
import re
import string

from typing import Any, Callable, cast, Optional, Union

from .content import CLOSE_DIV, Content, MacroRef, MacroArg, OPEN_DIV
from .exception import MacroException
from .logging import Logging
from .node import _HasContent

logger = Logging.get_logger(__name__)


class Macro:
    _macros = {}

    _many_newlines = re.compile(r'\n{3,}')

    # note the use of macro_ prefixes to avoid conflict with argument names
    # XXX it would be better instead to use arg_ prefixes for arguments!
    # XXX should add a 'macro_doc' argument
    def __init__(self, macro_name: str, *, macro_body: Union[
        str, Content, string.Template, Callable] = None,
                 macro_auto: Optional[str] = None,
                 macro_final: bool = True, **args):
        # check for invalid 'auto' values
        # XXX this is a programming error; better just to raise an exception?
        if macro_auto not in {None, 'before', 'after'}:
            logger.error('invalid %s macro auto value %s' % macro_auto)

        # check for any unhandled macro_xxx arguments
        # XXX this is a programming error; better just to raise an exception?
        unhandled = [n for n in args.keys() if n.startswith('macro_')]
        if unhandled:
            logger.error('unhandled %s macro argument(s) %s' % (
                macro_name, ', '.join(unhandled)))

        self._name = macro_name
        self._body = macro_body
        self._auto = macro_auto
        self._final = macro_final
        self._args = {n: v for n, v in args.items()
                      if not n.startswith('macro_')}

        # if potentially auto-included, create a no-argument {{no<name>}}
        # macro that expands to an empty string (it suppresses auto-inclusion)
        if macro_auto:
            Macro('no%s' % macro_name, macro_body='')

        # XXX for testing, it's useful to allow macro definition override
        if self._name in self._macros and self._macros[self._name].final:
            logger.warning('{{%s}} macro was redefined' % self._name)
        self._macros[macro_name] = self

    @classmethod
    def expand(cls, content: Content, *, noauto: bool = False,
               node: Optional[_HasContent] = None, args=None,
               error=None, warning=None, info=None, debug=None,
               **kwargs) -> str:
        if args is None and node is not None:
            args = node.args
        content_plus = content if noauto else \
            cls._content_plus(content, node=node)

        # helper that's used below to ignore warnings
        def ignore(*_args, **_kwargs):
            pass

        # ignore warnings here because the 'used' transform will already
        # have reported them for the original content
        body = content_plus.get_body(error=error, warning=ignore,
                                     info=info, debug=debug)

        # don't ignore warnings here
        text = cls._expand_arg(body, node=node, args=args, error=error,
                               warning=warning, info=info, debug=debug,
                               **kwargs)

        # ensure that there are no leading newlines
        # XXX there shouldn't be any; but should remove trailing whitespace?
        if text[:1].isspace() or text[-1:].isspace() or \
                text[:2] == '{{' or text[-2:] == '}}':
            logger.debug('#### whitespace: %s: %r' % (node.nicepath, text))
        if text.startswith('\n'):
            text = re.sub(r'^\n+', '', text)
            assert not text.startswith('\n'), repr(text)
        return text

    # self._body functions should raise MacroException on error
    def _expand_ref(self, macro_ref: MacroRef,
                    active: Optional[dict[Any, int]] = None,
                    **kwargs) -> Optional[str]:
        if active is None:
            active = {}

        # get the arguments
        args = self._get_args(macro_ref)

        # create/update the macro reference stack (note use of tuples)
        # XXX how expensive is this? maybe should only do it for some macros?
        # XXX maybe it should be handled separately from the arguments, like
        #     active?
        kwargs.setdefault('stack', ())
        kwargs['stack'] = kwargs['stack'] + (macro_ref,)

        # expand the arguments
        cls = type(self)
        args_expanded = {}
        for name, arg in args.items():
            if not isinstance(arg, list):
                args_expanded[name] = cls._expand_arg(arg, **kwargs)
            else:
                args_expanded[name] = [cls._expand_arg(a, **kwargs)
                                       for a in arg]

        # add additional keyword arguments
        # XXX name overlaps between macro arguments and keyword arguments will
        #     cause problems (the latter will win)
        args_expanded_plus = args_expanded | kwargs | {'active': active}

        # XXX for the callable() case, should examine the actual arguments and
        #     only pass those that are declared; cf the 'visit' logic
        expansion = self._body if isinstance(self._body, (str, Content)) else \
            self._body.substitute(args_expanded) if \
            isinstance(self._body, string.Template) else \
            self._body(**args_expanded_plus) if callable(self._body) else \
            self._expand_body(**args_expanded_plus)

        # XXX could/should allow this to return a tuple, in which case each
        #     element will be further expanded (if need be) and then all the
        #     results concatenated; this would allow things like {{replaced}}
        #     in {{param|{{replaced|A|B}}}}' to return ({{deleted|A}},

        # if the expansion is a Content instance, it needs to be re-expanded
        if isinstance(expansion, Content):
            # if this macro is already active, its expansion referenced it
            # XXX this key is over-complicated; str() is necessary to cope
            #     with the case where an argument is a list
            key = (self, tuple(str(v) for v in args_expanded.values()))
            if key in active:
                callers = ' -> '.join('{{%s}}' % m.name for m, _ in active)
                raise MacroException('recursive: %s -> {{%s}}' % (
                    callers, self.name))

            # note that it's active
            active.setdefault(key, 0)
            active[key] += 1

            # expand it until it's no longer a Content instance
            while isinstance(expansion, Content):
                expansion = Macro._expand_arg(expansion.body, active=active,
                                              **kwargs)

            # note that it's no longer active (and tidy up 'active')
            active[key] -= 1
            if active[key] == 0:
                del active[key]

        # the return value is either None (deprecated) or a string
        return expansion

    # subclasses MUST override this if they don't define self._body
    def _expand_body(self, **args) -> Optional[Union[str, Content]]:
        raise NotImplementedError

    @classmethod
    def _content_plus(cls, content: Content, *, node=None) -> Content:
        # the node/parent should only be None when testing
        if not node or not node.parent:
            return content

        # note that it's the parent node that's consulted about whether a
        # given macro is valid, e.g., Description -> Object
        parent = node.parent
        before, after = [], []
        for name, func in parent.auto_macro_criteria.items():
            macro = Macro._macros.get(name, None)

            # assertion failure indicates a programming error (a mismatch
            # between macro definitions and auto_macro_criteria)
            # XXX but formats can declare/override macros, so this shouldn't
            #     be an assertion
            assert macro and macro.auto in {'before', 'after'}, \
                "invalid 'auto-macro' %s" % name

            # check whether the macro should be added, and the separator
            # (the function can either return a value that's evaluated as
            # a Boolean, or a tuple with this same value and a separator)
            default_separators = {'before': ' ', 'after': '{{np}}'}
            addit, separator = False, default_separators[macro.auto]
            retval = func(parent)
            if not isinstance(retval, tuple):
                addit = bool(retval)
            else:
                if len(retval) > 0:
                    addit = bool(retval[0])
                if len(retval) > 1:
                    separator = retval[1]
            if not addit:
                continue

            # content is probably node.content, but this isn't assumed
            # XXX this is tricky, because (for example) existence of {{enum|A}}
            #     shouldn't prevent addition of {{enum}}, but existence of
            #     {{reference||obsoleted}} _should_ prevent addition of
            #     {{reference}}
            # XXX for now, make {{enum}} and {{pattern}} be a special case, but
            #     this should really be a Macro attribute
            if name in {'enum', 'pattern'}:
                if (name, 0) in content.macro_refs:
                    continue
            else:
                if name in content.macro_refs:
                    continue
            if 'no%s' % name in content.macro_refs:
                continue

            # for before/after macros, the separator goes after/before
            if macro.auto == 'before':
                before.extend(['{{%s}}' % name, separator])
            else:
                after.extend([separator, '%s{{%s}}%s' % (
                    OPEN_DIV, name, CLOSE_DIV)])

        # this is used for the {{diffs}} macro
        if content.footer:
            after.extend(['{{np}}', content.footer])

        if not before and not after:
            # the original object would be returned anyway in this case,
            # but this makes it more obvious
            content_ = content
        elif not content:
            # remove the first 'after' separator; this is to address the
            # case where 'before' and 'content' are both empty
            content_ = ''.join(before) + content + ''.join(after[1:])
        else:
            content_ = ''.join(before) + content + ''.join(after)

        # XXX temporary additional debug output
        # logger.debug('#### content   : %s: %r' % (node.nicepath, content))
        # logger.debug('#### content+  : %s: %r' % (node.nicepath, content_))
        return content_

    @classmethod
    def _expand_arg(cls, arg: Optional[MacroArg] = None, *, error=None,
                    warning=None, info=None, debug=None, **kwargs) -> str:
        if error is None:
            error = logger.error
        if warning is None:
            warning = logger.warning
        if info is None:
            info = logger.info
        if debug is None:
            debug = logger.debug

        chunks = []

        # create/update the macro expansion chunks (note use of tuples)
        # XXX as an experiment, include a tuple of chunks lists in keyword
        #     arguments for use by individual Macro instances (this might
        #     not be needed; the stack might provide sufficient information)
        # XXX how expensive is this? maybe should only do it for some macros?
        # XXX maybe it should be handled separately from the arguments, like
        #     active?
        kwargs.setdefault('chunks', ())
        kwargs['chunks'] = kwargs['chunks'] + (chunks,)

        for item in (arg.items if arg else []):
            assert isinstance(item, (str, MacroRef))
            if isinstance(item, str):
                chunk = item
            else:
                macro_ref = cast(MacroRef, item)
                macro_name = macro_ref.name
                if macro_name.strip() != macro_name:
                    warning('{{%s}}: macro name has leading and/or trailing '
                            'whitespace' % macro_name)
                macro = Macro._macros.get(macro_name.strip(), None)
                if macro is None:
                    # this indicates a non-existent macro
                    non_existent = 'non-existent'

                    # XXX if the macro argument is non_existent, we've already
                    #     been here, so don't output the message (need a better
                    #     way of marking and checking for this situation)
                    already = len(macro_ref.args) == 1 and macro_ref.args[
                        0].is_simple and macro_ref.args[0].text == non_existent
                    if not already:
                        error('{{%s}}: %s macro' % (macro_name, non_existent))
                    chunk = '{{%s|%s}}' % (macro_name, non_existent)
                else:
                    macro = cast(Macro, macro)
                    try:
                        chunk = macro._expand_ref(macro_ref, error=error,
                                                  warning=warning, info=info,
                                                  debug=debug, **kwargs)
                        if chunk is None:
                            warning('{{%s}}: returned no result' % macro.name)
                            chunk = '{{%s:returned-no-result}}' % macro.name
                    except MacroException as e:
                        str_e = str(e) or type(e).__name__
                        warning('{{%s}}: %s' % (macro.name, str_e))
                        # on error, protect the macro against re-expansion
                        # XXX perhaps it would be better just to retain the
                        #     original macro invocation? but it's nice to
                        #     indicate an error (will anyone see?)
                        chunk = r'**\{\{%s: %s}}**' % (macro.name, str_e)

            chunks.append(chunk)
        return ''.join(chunks)

    def _get_args(self, ref: MacroRef) -> \
            dict[str, Union[MacroArg, list[MacroArg]]]:
        args = {}
        exp_args = len(self.args)
        act_args = len(ref.args)
        open_list = None
        for index, (arg_name, arg_spec) in enumerate(self.args.items()):
            mandatory = self._arg_is_mandatory(arg_spec)
            if index < act_args:
                # if the arg_spec is list , this arg will be a list
                # XXX the constructor should probably check that only the final
                #     argument is a list
                if arg_spec is not list:
                    args[arg_name] = ref.args[index]
                else:
                    open_list = args.setdefault(arg_name, [])
                    open_list.append(ref.args[index])
            elif not mandatory:
                args[arg_name] = MacroArg(self._arg_default(arg_spec))
            else:
                raise MacroException('missing %s argument' % arg_name)

        # the last list argument (if any) will collect any excess arguments
        if open_list is not None:
            cast(list, open_list).extend(ref.args[exp_args:])

        # otherwise issue a warning
        # XXX have included the good args to help in diagnosing cases like
        #     'this {bibref|XYZ}} has a missing opening curly brace'
        # XXX the messages can still be quite difficult to interpret,
        #     because it's hard to represent macro args as strings in the
        #     general case
        elif act_args > exp_args:
            good_args = ref.args[:exp_args]
            bad_args = ref.args[exp_args:]
            bad_plural = 's' if len(bad_args) > 1 else ''
            good_text = ', '.join(str(arg) for arg in good_args)
            bad_text = ', '.join(str(arg) for arg in bad_args)
            raise MacroException('unexpected argument%s %s after: %s' %
                                 (bad_plural, bad_text, good_text))
        return args

    @staticmethod
    def _arg_is_mandatory(arg_spec: Any) -> bool:
        # XXX for now, it's mandatory iff it's a type, e.g., str
        return isinstance(arg_spec, type)

    @staticmethod
    def _arg_default(arg_spec: Any) -> Optional[str]:
        # XXX for now, the default is str(arg_spec) if it's a string or
        #     numeric (Booleans are numbers), and None otherwise
        # XXX _expand_arg() will change None to '' anyway
        return str(arg_spec) if isinstance(arg_spec, (str, numbers.Number)) \
            else arg_spec() if isinstance(arg_spec, type) else None

    # escape macro references, e.g., in deleted text
    @classmethod
    def escape(cls, text: str) -> str:
        if not ('{' in text or '|' in text or '}' in text):
            return text
        else:
            return re.sub(r'([{|}])', r'\\\1', text)

    # unescape previously-escaped macro references
    @classmethod
    def unescape(cls, text: str) -> str:
        if not ('{' in text or '|' in text or '}' in text):
            return text
        else:
            return re.sub(r'\\([{|}])', r'\1', text)

    # clean up by removing some macro references
    # XXX this is heuristic, and has knowledge of some macros; should get
    #     all this info from content.py (these methods should be there?)
    @classmethod
    def clean(cls, text: str) -> str:
        if text.startswith(OPEN_DIV) and text.endswith(CLOSE_DIV):
            text = text[len(OPEN_DIV):-len(CLOSE_DIV)]
        text = text.replace(CLOSE_DIV + OPEN_DIV, '\n\n')
        text = text.replace('{{np}}', '\n\n')
        text = text.replace('{{nl}}', ' ')
        return text

    @property
    def name(self) -> str:
        return self._name

    # XXX should specify a tighter return type
    @property
    def body(self) -> Any:
        return self._body

    @property
    def auto(self) -> Optional[str]:
        return self._auto

    @property
    def final(self) -> bool:
        return self._final

    @property
    def args(self) -> dict[str, Any]:
        return self._args

    def __str__(self):
        left_man, right_man = ('[', ''), (']', '')
        def_str = lambda s: '%s%s' % (
            '=' if self._arg_default(s) is not None else '',
            self._arg_default(s) or '')
        args = ['%s%s%s%s' % (
            left_man[self._arg_is_mandatory(spec)], name, def_str(spec),
            right_man[self._arg_is_mandatory(spec)]) for name, spec in
                self._args.items()]
        return '%s(%s)' % (self._name, ', '.join(args))

    __repr__ = __str__
