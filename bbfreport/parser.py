"""XML parser support."""

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

import argparse
import json
import pprint

from typing import Optional, Union

from .exception import ParserException
from .logging import Logging
from .plugin import Plugin
from .utility import Utility

# common type aliases
# this is more accurate but produces very confusing documentation
# Data = tuple[tuple[str, Union[str, 'Data']], ...]
# so use this
Data = tuple[tuple[str, Union[str, tuple]], ...]

logger = Logging.get_logger(__name__)


# XXX need at least one validating parser; pyxb validates but is slow, and
#     error messages are poor; lxml? xmlschema? maybe simply support
#     validation for the libraries that implement it?
class Parser(Plugin):
    """XML parser base class."""

    # see _Parser (below) for generic parser command-line arguments (can't put
    # them here because derived-class-specific arguments would override them)

    def parse(self, path: str, *,
              args: Optional[argparse.Namespace] = None) -> Data:
        """Parse the supplied file and return a nested tuple.

        This method calls `Parser._parse()` to do the work. Refer to it for
        details.

        Args:
            path: The path of the XML file to parse.
            args: Command-line arguments. These must be specified.

        Returns:
            The parsed data as a nested tuple.
        """

        mandatory = ['thisonly', 'parser_dump_json', 'parser_dump_tuple',
                     'parser_warn_tabs']
        assert args and all({hasattr(args, a) for a in mandatory}), \
            'missing mandatory arguments; one of more of %s' % mandatory

        # parse the file to a nested tuple
        data = self._parse(path, warn_tabs=args.parser_warn_tabs,
                           smart_cdata=not args.thisonly,
                           expand_entities=not args.thisonly)

        # XXX the parser needs to be responsible for ensuring 'dm_document'
        #     etc. even if the document uses a different namespace prefix

        # XXX should do some 'other' processing, e.g. to combine adjacent
        #     instances, and to discard whitespace past the last newline of
        #     a set of adjacent instances (this is primarily for efficiency,
        #     because there can be a lot of 'other' tokens)

        # optionally dump as JSON and/or tuple
        # XXX is it worth the complexity of dictionaries for attributes?
        *_, file = Utility.path_split_drive(path)
        if args.parser_dump_json:
            json.dump(data, open(file + '.json', 'w'), indent='  ')
        if args.parser_dump_tuple:
            pprint.pprint(data, open(file + '.tuple', 'w'))

        # check the returned tuple looks feasible
        valid = Parser._is_valid_tuple(data)
        if not valid:
            raise ParserException('%s parse returned invalid data' % path)

        # return the tuple
        return data

    # XXX need to describe the returned nested tuple in more detail
    def _parse(self, path: str, *, warn_tabs: bool = False,
               smart_cdata: bool = False, expand_entities: bool = False) \
            -> Data:
        # XXX note use of r"""""" because of '\n' characters
        r"""Parse the supplied file and return a nested tuple.

        Derived classes must implement this method.

        Args:
            path: The path of the XML file to parse.
            warn_tabs: Whether to warn of TAB characters. This is ``True``
                if the ``--parser-warn-tabs`` command-line option was
                specified, and ``False`` otherwise.
            smart_cdata: Whether to perform "smart cdata" processing,
                i.e. ignore "ignorable" whitespace and non-top-level comments.
                This is ``True`` if the ``--thisonly`` command-line option
                was *not* specified, and ``False`` otherwise.
            expand_entities: Whether to expand XML entities. This too is
                ``True`` if the ``--thisonly`` command-line option was *not*
                specified, and ``False`` otherwise.

        Returns:
            The parsed data as a nested tuple.

        The ``smart_cdata`` and ``expand_entities`` settings are designed to
        give efficient and sensible behavior in these two use cases.

        * When generating "full" XML (``--thisonly`` not specified), multiple
          files may be processed, and the generated XML is a combined view
          of all of them.

        * When generating "single file" XML (``--thisonly`` specified), only a
          single is read, and the generated XML should be as similar as
          possible to the input file.

        The nested tuple looks quite like the XML file. For example,
        this XML file::

            <?xml version="1.0" encoding="UTF-8"?>

            <!-- document comment -->
            <dm:document
                xmlns:dm="urn:broadband-forum-org:cwmp:datamodel-1-8"
                xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                xsi:schemaLocation="
                  urn:broadband-forum-org:cwmp:datamodel-1-8
                   https://www.broadband-forum.org/cwmp/cwmp-datamodel-1-8.xsd"
                spec="urn:example-com:simple"
                file="simple.xml">

              <model name="Simple:1.0">

                <parameter name="Aardvark" access="readOnly">
                  <description>
                    Description.
                  </description>
                  <syntax>
                    <unsignedInt/>
                  </syntax>
                </parameter>
              </model>
            </dm:document>

        ...gives this tuple with ``smart_cdata=True``::

            (('xml_decl', '<?xml version="1.0" encoding="UTF-8"?>'),
             ('other', '\n\n'),
             ('comment', '<!-- document comment -->'),
             ('other', '\n'),
             ('dm_document',
              (('xmlns_dm', 'urn:broadband-forum-org:cwmp:datamodel-1-8'),
               ('xmlns_xsi', 'http://www.w3.org/2001/XMLSchema-instance'),
               ('xsi_schemaLocation',
                '       urn:broadband-forum-org:cwmp:datamodel-1-8         '
                'https://www.broadband-forum.org/cwmp/cwmp-datamodel-1-8.xsd'),
               ('spec', 'urn:example-com:simple'),
               ('file', 'simple.xml'),
               ('model',
                (('name', 'Simple:1.0'),
                 ('parameter',
                  (('name', 'Aardvark'),
                   ('access', 'readOnly'),
                   ('description', (('cdata',
                                     '\n        Description.\n      '),)),
                   ('syntax', (('unsignedInt', ()),)))))))),
             ('other', '\n'))

        ...and gives this with ``smart_cdata=False``::

            (('xml_decl', '<?xml version="1.0" encoding="UTF-8"?>'),
             ('other', '\n\n'),
             ('comment', '<!-- document comment -->'),
             ('other', '\n'),
             ('dm_document',
              (('xmlns_dm', 'urn:broadband-forum-org:cwmp:datamodel-1-8'),
               ('xmlns_xsi', 'http://www.w3.org/2001/XMLSchema-instance'),
               ('xsi_schemaLocation',
                '       urn:broadband-forum-org:cwmp:datamodel-1-8         '
                'https://www.broadband-forum.org/cwmp/cwmp-datamodel-1-8.xsd'),
               ('spec', 'urn:example-com:simple'),
               ('file', 'simple.xml'),
               ('cdata', '\n\n  '),
               ('comment', '<!-- model comment -->'),
               ('cdata', '\n  '),
               ('model',
                (('name', 'Simple:1.0'),
                 ('cdata', '\n    '),
                 ('parameter',
                  (('name', 'Aardvark'),
                   ('access', 'readOnly'),
                   ('cdata', '\n      '),
                   ('description', (('cdata',
                                     '\n        Description.\n      '),)),
                   ('cdata', '\n      '),
                   ('syntax',
                    (('cdata', '\n        '), ('unsignedInt', ()),
                                              ('cdata', '\n      '))),
                   ('cdata', '\n    '))),
                 ('cdata', '\n  '))),
               ('cdata', '\n'))),
             ('other', '\n'))

        In both cases the outer tuple contains a sequence of ``(name, value)``
        tuples, where the value is either a string or a tuple with the same
        structure as the outer tuple.

        The difference between the two cases is that the second one (with
        ``smart_cdata=False``) contains all the whitespace and comment
        information. This is more verbose and results in a lot more nodes.

        These nested tuples are processed directly by `_Node._merge()`.

        Note:
            We could extend the two-tuples to include (optional) line number
            information.
        """

        raise NotImplementedError('unimplemented %s._parse()' % type(
                self).__name__)

    # XXX should put some utilities in a lower-level class that Node can use
    @staticmethod
    def _is_valid_tuple(data: Data) -> bool:
        """Check whether the supplied data looks like a valid _parse()
        result.

        Check that it's a tuple, each of its entries have two values,
        and the first value is a string. The check is not recursive.

        Args:
            data: The data to check.

        Returns:
            Whether it looks valid.
        """

        if not isinstance(data, tuple):
            return False
        for entry in data:
            if len(entry) != 2:
                return False
            if not isinstance(entry[0], str):
                return False
        return True


# this is just to add some generic parser arguments
# (its canonical name is 'parser-parser')
class ParserParser(Parser):
    @classmethod
    def _add_arguments(cls, arg_parser, **kwargs):
        arg_group = arg_parser.add_argument_group('generic parser arguments')
        arg_group.add_argument('--parser-dump-json', action='store_true',
                               help='dump parse results to JSON')
        arg_group.add_argument('--parser-dump-tuple', action='store_true',
                               help='dump parse results as tuple')
        arg_group.add_argument('--parser-warn-tabs', action='store_true',
                               help='warn of any TAB characters')
        return arg_group


# need explicit registration because this isn't in the plugins directory
ParserParser.register()
