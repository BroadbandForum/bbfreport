"""Text report format plugin."""

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

import textwrap

from typing import cast, Optional, Union

from ..format import Format
from ..logging import Logging
from ..node import _Base, CommandRef, Component, DataType, EventRef, \
    _HasContent, Model, Object, ObjectRef, Parameter, ParameterRef, \
    Profile, Reference, Root
from ..utility import Utility

logger = Logging.get_logger(__name__)

nice_dict = Utility.nice_dict
nice_string = Utility.nice_string


class TextFormat(Format):
    """Text report format plugin."""

    @classmethod
    def _add_arguments(cls, arg_parser, **kwargs):
        default_style = 'visit'

        arg_group = arg_parser.add_argument_group('text report format '
                                                  'arguments')
        arg_group.add_argument('--text-report-style',
                               choices=['report1', 'report2', 'visit'],
                               default=default_style,
                               help='report style (details TBD); default: %r'
                                    % default_style)
        arg_group.add_argument('--text-list-references', action='store_true',
                               help='whether to list bibliographic references')
        return arg_group

    def _visit_begin(self, root: Root, **kwargs) -> Optional[bool]:
        """Behavior is a function of ``root.args.text_report_style``, i.e.,
        the ``--text-report-style`` command-line argument.

        * ``visit``: return nothing, so `_visit_node()` will be called for
          each node.

        * ``report*``: report on the entire tree, and return ``True`` to
           suppress automatic node traversal:

          * ``report1``: call ``report_root()``, which uses the specific
            interface to report on the root node and some of its children.

          * ``report2``: call ``report_elem()``, which uses a similar
            mechanism to report on the root node and all of its children.
        """
        style = root.args.text_report_style
        if style != 'visit':
            logger.info('begin')
            if style == 'report1':
                self.report_root(root)
            else:
                self.report_elem(root)
            logger.info('end')
            return True

    # warning: this will be called for _all_ nodes; there can be a lot of them!
    def _visit_node(self, node: _Base, *, level: int = 0, name: str = '',
                    **kwargs) -> None:
        """Call ``report_generic()``, which uses the generic interface to
        report on the node.
        """
        self.report_generic(node, level=level, name=name)

    def report_root(self, root: Root, *, level: int = 0) -> None:
        datatypes = cast(list[DataType], DataType.findall())
        root.args.output.write(
            '%sdatatypes (%d)\n' % (self.indent(level), len(datatypes)))
        for datatype in sorted(datatypes, key=lambda d: str(d).lower()):
            self.report_datatype(datatype, level=level + 1)

        references = cast(list[Reference], Reference.findall())
        root.args.output.write(
            '%sreferences (%d)\n' % (self.indent(level), len(references)))
        if root.args.text_list_references:
            for reference in sorted(references, key=lambda r: str(r).lower()):
                self.report_reference(reference, level=level + 1)

        components = cast(list[Component], Component.findall())
        root.args.output.write(
            '%scomponents (%d)\n' % (self.indent(level), len(components)))
        for component in sorted(components, key=lambda c: str(c).lower()):
            self.report_component(component, level=level + 1)

        # these are all models; root.models are just models defined on the
        # command line
        models = cast(list[Model], Model.findall())
        root.args.output.write(
            '%smodels (%d)\n' % (self.indent(level), len(models)))
        for model in models:
            self.report_model(model, level=level + 1)

    def report_datatype(self, datatype: DataType, *, level: int = 0) -> None:
        datatype.args.output.write(
            '%s%s from %s\n' % (self.indent(level), datatype, datatype.parent))

    def report_reference(self, reference: Reference, *,
                         level: int = 0) -> None:
        reference.args.output.write(
            '%s%s = %s\n' % (self.indent(level), reference.id, reference.name))

    def report_component(self, component: Component, *,
                         level: int = 0) -> None:
        component.args.output.write('%s%s from %s\n' % (
        self.indent(level), component.name, component.parent))

    def report_model(self, model: Model, *, level: int = 0) -> None:
        base = f' : {model.base}' if model.base else ''
        # XXX these numbers aren't reliable because they only count the
        #     direct children, not children defined in components (which are
        #     down two levels per level of component)
        model.args.output.write('%s%s%s (#objects %d, #profiles %d)\n' % (
            self.indent(level), model.name, base, len(model.objects),
            len(model.profiles)))
        self.report_elems(model, level=level + 1)

    def report_elems(self, elems: _Base, *, level: int = 0) -> None:
        for elem in elems.elems:
            self.report_elem(elem, level=level)

    def report_elem(self, elem: _Base, *, level: int = 0) -> None:
        func_map = {
            'bibliography': self.report_stop,
            'command': self.report_generic,
            'commandRef': self.report_entity_ref,
            'componentRef': self.report_skip,
            'component': self.report_skip,
            'dataType': self.report_stop,
            'description': self.report_stop,
            'document': self.report_strvalue,
            'event': self.report_generic,
            'eventRef': self.report_entity_ref,
            'import': self.report_stop,
            'input': self.report_generic,
            'model': self.report_generic,
            'object': self.report_generic,
            'objectRef': self.report_entity_ref,
            'output': self.report_generic,
            'parameter': self.report_parameter,
            'parameterRef': self.report_entity_ref,
            'profile': self.report_profile,
            'root': self.report_strvalue,
            'syntax': self.report_stop,
            'uniqueKey': self.report_stop}
        func = func_map.get(elem.typename, self.report_unhandled)
        done = func(elem, level=level)

        if not done:
            levelstep = 0 if func == self.report_skip else 1
            for elem_ in elem.elems:
                self.report_elem(elem_, level=level + levelstep)

    def report_object(self, object_: Object, *, level: int = 0) -> bool:
        object_.args.output.write(
            '%sobject %s\n' % (self.indent(level), object_.name))
        return False

    def report_parameter(self, parameter: Parameter, *,
                         level: int = 0) -> bool:
        parameter.args.output.write('%s%s %s\n' % (
            self.indent(level), parameter.syntax or 'parameter',
            parameter.name or 'anon'))
        # ignore the parameter's children
        return True

    def report_profile(self, profile: Profile, *, level: int = 0) -> bool:
        base = f' base {profile.base}' if profile.base else ''
        extends = f' extends {profile.extends}' if profile.extends else ''
        extra = ''  # XXX f' key {profile.key}'
        profile.args.output.write('%sprofile %s%s%s%s\n' % (
            self.indent(level), profile.name, base, extends, extra))
        return False

    def report_entity_ref(self, ref: Union[CommandRef, EventRef, ObjectRef,
                                           ParameterRef], *,
                          level: int = 0) -> bool:
        attrs = ' ' + nice_dict(ref.attrs, style='csv') if ref.attrs else ''
        extra = ''  # XXX f' key {ref.key}'
        ref.args.output.write(
            '%s%s%s%s\n' % (self.indent(level), ref.typename, attrs, extra))
        return False

    def report_strvalue(self, elem: _Base, *, level=0) -> bool:
        return self.report_generic(elem, level=level, withvalue=True)

    def report_generic(self, elem: _Base, *, level: int = 0, name: str = '',
                       prefix: str = '', withvalue: bool = False) -> bool:
        override = {'name': name} if name else None
        value = ' ' + str(elem) if withvalue else ''
        attrs = ' ' + nice_dict(elem.attrs, override=override, style='csv') \
            if elem.attrs else ''
        text = ' %s' % nice_string(elem.text, maxlen=40) if elem.text else ''
        text += ' -> %s' % nice_string(
                elem.content.markdown or '', maxlen=256) \
            if isinstance(elem, _HasContent) else ''
        line = '%s%s%s%s%s%s' % (
            prefix, self.indent(level), elem.typename, value, attrs, text)
        lines = textwrap.wrap(line, subsequent_indent=' ' * len(
                prefix) + self.indent(level + 2))
        elem.args.output.write('%s\n' % '\n'.join(lines))
        return False

    # 'skip' means no report on this element but continue to its children
    # noinspection PyUnusedLocal
    @staticmethod
    def report_skip(elem: _Base, *, level: int = 0) -> bool:
        return False

    # 'stop' means no report on this element and ignore its children
    # noinspection PyUnusedLocal
    @staticmethod
    def report_stop(elem: _Base, *, level: int = 0) -> bool:
        return True

    def report_unhandled(self, elem: _Base, *, level: int = 0) -> bool:
        nicepath = ' %s' % elem.nicepath if elem.nicepath else ''
        elem.args.output.write(
            '%s%s%s [x]\n' % (self.indent(level), elem.typename, nicepath))
        return False

    @staticmethod
    def indent(level: int) -> str:
        return level * '  '
