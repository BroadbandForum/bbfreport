"""Expat XML parser plugin."""

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

import os
import xml.parsers.expat

from typing import Optional

from ..exception import ParserException
from ..logging import Logging
from ..parser import Data, Parser
from ..utility import Utility

logger = Logging.get_logger(__name__)


class ExpatParser(Parser):
    """Expat XML parser plugin."""

    def __init__(self, name: Optional[str] = None, **kwargs):
        super().__init__(name, **kwargs)
        self._path = None
        self._parser = None
        self._entities = None
        self._item = None
        self._stack = None

    # parse the file to a tree
    def _parse(self, path: str, *, warn_tabs: bool = False,
               smart_cdata: bool = False,
               expand_entities: bool = False) -> Data:
        """Parse the supplied file and return a nested tuple.

        Further details are TBD.
        """

        self._path = path
        self._warn_tabs = warn_tabs
        self._smart_cdata = smart_cdata
        self._expand_entities = expand_entities
        self._parser = xml.parsers.expat.ParserCreate()
        # this reduces the need for __append_text(), but not completely,
        # because it also handles entity declarations
        self._parser.buffer_text = True
        self._parser.XmlDeclHandler = self.__xml_decl
        self._parser.CommentHandler = self.__comment
        self._parser.EntityDeclHandler = self.__entity_decl
        self._parser.StartElementHandler = self.__start_element
        self._parser.CharacterDataHandler = self.__character_data
        self._parser.EndElementHandler = self.__end_element
        self._parser.DefaultHandler = self.__default
        self._entities = {}
        self._item = []
        self._stack = []
        try:
            self._parser.Parse(open(path, 'r+b').read())
        except xml.parsers.expat.ExpatError as error:
            # add the filename
            raise ParserException('%s: %s' % (os.path.basename(path), error))
        assert len(self._stack) == 0

        # return the parse tree
        return tuple(self._item)

    def __xml_decl(self, version, encoding, standalone):
        logger.info('xmldecl %r %r %r' % (version, encoding, standalone))
        self._item += [('xml_decl', '<?xml version="%s" encoding="%s"?>' % (
            version, encoding))]

    # the comment data includes the 'open' and 'close' strings
    def __comment(self, data):
        logger.info('comment %r' % data)
        self.__report_tabs(data)
        self._item += [('comment', '<!--%s-->' % data)]

    def __entity_decl(self, name, param, value, base, sysid, pubid, notname):
        assert param == 0 and base is None and sysid is None and pubid is \
               None and notname is None
        assert '"' not in value
        logger.info('entity  %r = %r' % (name, value))
        self.__append_text('other', self._item,
                           '<!ENTITY %s "%s">' % (name, value))
        # XXX arbitrarily only store entities with values longer than one
        #     character; this avoids things like changing all colons to
        #     &colon; (note that we never see unexpanded attribute values)
        if len(value) > 1:
            self._entities[value] = '&%s;' % name
            # sort from longest to shortest value
            self._entities = {v: n for v, n in sorted(self._entities.items(),
                                                      key=lambda i: -len(
                                                              i[0]))}

    def __start_element(self, name, attrs):
        logger.info('start   %r' % name)
        self._stack.append(self._item)
        self._item = [(Utility.clean_name(n), self.__unexpand_entities(v))
                      for n, v in attrs.items()]

    def __character_data(self, data):
        logger.info('cdata   %r' % data)
        self.__report_tabs(data)
        self.__append_text('cdata', self._item, data)

    def __end_element(self, name):
        logger.info('end     %r' % name)
        item = self.__smart_cdata(self._item)
        self._item = self._stack.pop()
        self._item += [(Utility.clean_name(name), tuple(item))]

    # entity references, whitespace and other text
    def __default(self, data):
        logger.info('other   %r' % data)
        self.__report_tabs(data)
        self.__append_text('other', self._item, data)

    def __report_tabs(self, text):
        if self._warn_tabs and '\t' in text:
            logger.warning('%s:replace tab(s) with spaces in %r' % (
                    self.__location(), text))

    def __location(self):
        *_, name = Utility.path_split_drive(self._path)
        return '%s:%d:%d' % (name, self._parser.CurrentLineNumber,
                             self._parser.CurrentColumnNumber + 1)

    # XXX this is potentially inefficient (but only if there are lots of
    #     entities); could we have to do more to handle inter-dependencies?
    def __unexpand_entities(self, value):
        # if expanding entities, just return the input
        if self._expand_entities:
            return value

        for ent_val, ent_name in self._entities.items():
            if value.find(ent_val) >= 0:
                value = value.replace(ent_val, ent_name)
        return value

    def __smart_cdata(self, atoms):
        # if not doing 'smart cdata' processing, just return the input
        if not self._smart_cdata:
            return atoms

        # if there are only 'cdata' and 'comment' atoms, remove all 'comment'
        # atoms and return the concatenated 'cdata' atoms as a single 'cdata'
        if all(a[0] in {'cdata', 'comment'} for a in atoms):
            text = ''.join(a[1] for a in atoms if a[0] != 'comment')
            return [('cdata', text)] if text else []

        # otherwise remove all whitespace-only 'cdata' atoms, and all
        # 'comment' atoms
        else:
            return [a for a in atoms if not (
                    (a[0] == 'cdata' and a[1].strip() == '') or
                    a[0] == 'comment')]

    @staticmethod
    def __append_text(field, item, data):
        # concatenate with current value if it's the same field type
        if len(item) > 0 and item[-1][0] == field:
            item[-1] = (field, item[-1][1] + data)
        else:
            item += [(field, data)]
