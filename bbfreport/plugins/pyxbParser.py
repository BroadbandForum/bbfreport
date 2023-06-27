"""Pyxb XML parser plugin.

Note:
    This doesn't currently work. The (default) `ExpatParser` is recommended.
"""

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

import importlib
import logging
import re

# You will need to install PyXB, e.g. pip install pyxb
# * See http://pyxb.sourceforge.net and https://github.com/pabigot/pyxb
# * See the makefile for how to use pyxbgen to generate DM bindings
import pyxb
import pyxb.binding

from ..exception import ParserException
from ..parser import Data, Parser
from ..utility import Utility

logger_name = __name__.split('.')[-1]
logger = logging.getLogger(logger_name)
logger.addFilter(
        lambda r: r.levelno > 20 or logger_name in Utility.logger_names)


class PyxbParser(Parser):
    def _parse(self, path: str, *, warn_tabs: bool = False,
               smart_cdata: bool = False,
               expand_entities: bool = False) -> Data:
        # read the file and determine the DM version
        # XXX should search for file; do this in the caller and pass
        #  realpath?
        # XXX should generalize so it supports DM, DT etc
        xml = open(path).read()
        match = re.search(r'xmlns:(\w+)=.*cwmp:datamodel-(\d+-\d+)', xml)
        if not match:
            raise ParserException(
                "can't find 'xmlns:cwmp:datamodel-n-m'; file %r "
                "isn't a DM instance?" % path)
        dm_version = match.group(2).replace('-', '_')

        # import the PyXB bindings for the appropriate DM version
        # XXX need to decide how to run pyxbgen and where to put the
        #  results
        #     (should try to make this transparent)
        # XXX need to catch and sensibly handle exceptions here
        dm_module = importlib.import_module(
            'cwmp_datamodel_%s' % dm_version)

        # parse the file and create PyXB Document
        # (see http://pyxb.sourceforge.net/userref_validating.html)
        # XXX not ideal, because it will only detect the first error
        # XXX also the location is often None; sigh...
        # XXX it doesn't handle wildcards correctly; an invalid attribute
        #     from the current namespace matches #other
        pyxb_document = None
        try:
            pyxb.RequireValidWhenParsing(True)
            # XXX should check what location_base actually does!
            pyxb_document = dm_module.CreateFromDocument(xml,
                                                         location_base=path)
        except pyxb.ValidationError as e:
            logger.error('%s:' % e.location if e.location else
                         'validation error in unknown location')
            logger.error(e.details())
        if pyxb_document is None:
            pyxb.RequireValidWhenParsing(False)
            pyxb_document = dm_module.CreateFromDocument(xml,
                                                         location_base=path)

        # convert to the desired tuple
        # XXX now needs to return a xml_file tuple
        return ('dm_document', PyxbParser._node_to_tuple(pyxb_document)),

    @staticmethod
    def _node_to_tuple(node):
        if node is None:
            return None
        else:
            data = ()
            # XXX all attributes are included, even None-valued ones;
            #  should
            #     also generate output for possible but absent elements?
            # noinspection PyProtectedMember
            for name, attr_use in node._AttributeMap.items():
                attr = name.localName()
                attr_ = attr_use.id()
                value = getattr(node, attr_)
                data += ((attr, value),)
            # noinspection PyProtectedMember
            if node._IsSimpleTypeContent():
                value = node.xsdLiteral() if \
                    isinstance(node,
                               pyxb.binding.basis.simpleTypeDefinition) \
                    else \
                    node.value()
                data += (('atom', value),)
            elif node._ContentTypeTag != \
                    pyxb.binding.basis.complexTypeDefinition._CT_EMPTY:
                for item in node.orderedContent():
                    declaration = item.elementDeclaration
                    name = declaration.name()
                    attr = name.localName()
                    data += (
                        (attr, PyxbParser._node_to_tuple(item.value)),)
            # collapse if no attributes, and simple type content
            if len(data) == 1 and data[0][0] == 'atom':
                data = data[0][1]
            # no attributes and empty content simply returns empty tuple
            return data
