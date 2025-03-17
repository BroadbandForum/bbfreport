"""Output diffs in a convenient text format.

The diff transform should have already been invoked."""

# XXX the content module and the diff transform should provide more
#     convenient raw material, and allow this to be less heuristic

import re

from typing import Union

from bbfreport.content import Content
from bbfreport.logging import Logging
from bbfreport.macro import Macro, MacroArg, MacroRef
# noinspection PyProtectedMember
from bbfreport.node import _HasContent

logger = Logging.get_logger(__name__)

# this is used for separating macros and their arguments
# XXX might need to do something cleverer for nested macros?
SEP = '§'


def ref_comps(ref: MacroRef, comps=None) -> list[str]:
    if comps is None:
        comps = []

    # check for special cases
    if ref.name in {'nl', 'np'}:
        comps.append(' ')
    elif ref.name in {'command', 'enum', 'event', 'object', 'param',
                      'pattern'}:
        # {{macro|value}} -> value
        if not ref.args:
            comps.append(ref.name)
        else:
            arg_comps(ref.args[0], comps)
    elif ref.name in {'bibref',  'units', 'deprecated', 'obsoleted',
                      'deleted'}:
        comps.append('{{%s' % ref.name)
        for arg in ref.args:
            comps.append('|')
            arg_comps(arg, comps)
        comps.append('}}')
    elif ref.name in {'div', 'span'}:
        # {{macro|{{classes}}|body}} -> body
        if len(ref.args) < 2:
            # XXX how can this happen?
            logger.warning('%s has too few args' % ref)
        else:
            arg_comps(ref.args[1], comps)
    elif not ref.args:
        comps.append(ref.name)
    else:
        for i, arg in enumerate(ref.args):
            if i > 0:
                comps.append(SEP)
            arg_comps(arg, comps)
    return comps


def arg_comps(arg: MacroArg, comps=None) -> list[str]:
    if comps is None:
        comps = []
    for i, item in enumerate(arg.items):
        item_comps(item, comps)
    return comps


def item_comps(item: Union[str, MacroRef], comps=None) -> list[str]:
    if comps is None:
        comps = []
    if isinstance(item, str):
        str_comps(item, comps)
    else:
        ref_comps(item, comps)
    return comps


def str_comps(text: str, comps=None) -> list[str]:
    if comps is None:
        comps = []

    # entity -> ASCII
    text = text.replace('&rArr;', '->')

    # '*word*' -> 'word'
    text = re.sub(r'(^|\s)\*([^*]+)\*(\s|$)', r"\1'\2'\3", text)

    # 'a  b ' -> 'a b'
    text = re.sub(r'\s+', ' ', text)

    comps.append(text)
    return comps


def visit__has_content(node: _HasContent, args):
    nicepath = node.nicepath
    content = node.content
    for mname in {'inserted', 'removed', 'replaced'}:
        for ref in content.macro_refs.get(mname, []):
            comps = ''.join(ref_comps(ref))
            comps = comps.split(SEP)

            # unescape macro references in deleted text
            comps = [Macro.unescape(comp) for comp in comps]

            # clean up by removing some macro references
            comps = [Macro.clean(comp) for comp in comps]

            # ignore whitespace-only changes
            # XXX should add an option for this
            if not all(comp.strip() == '' for comp in comps):

                # generate "'text'" or "'old' -> 'new'"
                text = ' -> '.join(repr(comp) for comp in comps)

                # output text
                args.output.write('%s: %s %s\n' % (nicepath, mname, text))

    if content.footer:
        footer = Content(content.footer)
        for ref in footer.macro_refs.get('diffs', []):
            comps = ''.join(ref_comps(ref)).split(SEP)
            for comp in comps:
                comp = comp[:1].lower() + comp[1:]
                args.output.write('%s: %s\n' % (nicepath, comp))
