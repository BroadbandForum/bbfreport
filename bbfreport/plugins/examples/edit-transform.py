"""Edit transform."""

# Copyright (c) 2020, Broadband Forum
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

# note use of absolute paths; can only use relative paths for plugins that
# live one level down the hierarchy (because of the report.py import logic)

from ...node import ComponentRef, Import, Xml_file
from ...transform import Transform


class EditTransform(Transform):
    @staticmethod
    def visit_comment(comment, warning, info):
        warning('comment %s' % comment)

        retain = {'tr-181-2-wifi.xml'}
        trigger = 'The undersigned members have elected to grant the ' \
                  'copyright to'

        file = str(comment.instance_in_path(Xml_file))
        if file in retain:
            info('retained copyright')
            return

        lines = []
        state = 'initial'
        for line in comment.text.split('\n'):
            if state == 'initial':
                if line.find(trigger) >= 0:
                    state = 'ignore'
                else:
                    lines += [line]

            elif state == 'ignore':
                if line.strip() == '':
                    state = 'initial'

        comment.text = '\n'.join(lines)
        info('removed copyright')

    @staticmethod
    def visit_import(imp, warning):
        warning('import %s' % imp)

        # XXX or check whether it's the last one
        if imp.file != 'tr-106-types.xml':
            return

        dm_document = imp.parent

        # XXX need a nice callable way of doing this
        data = (('file', 'tr-181-2-root.xml'),
                ('spec', 'urn:broadband-forum-org:tr-181-2-14-root'),
                ('component', (('name', 'Root'),)))
        new = Import(parent=dm_document, data=data)

        # noinspection PyUnreachableCode
        if False:
            # XXX this isn't supported; how would it update elems?
            dm_document.imports.append(new)
        else:
            # XXX this works, but it deletes and appends _all_ the imports, and
            #     actually creates a new list; this is different from the usual
            #     list behavior and relates to an __iadd__() optimization!
            dm_document.imports += [new]

        logger.info('added import')

    @staticmethod
    def visit_model(model, warning):
        warning('model %s' % model)

        # XXX this logic only works with --thisonly
        if not model.args.thisonly:
            return

        model.description = None
        model.objects = None

        data = (('ref', 'Root'),)
        new = ComponentRef(parent=model, data=data)

        # noinspection PyUnreachableCode
        if False:
            # XXX this isn't supported; how would it update elems?
            model.components.insert(0, new)
        else:
            # XXX this works, but it deletes and appends _all_ the components
            model.components = [new] + model.components

        logger.info('updated model')
