"""XML report format plugin."""

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

import logging
import re
import textwrap

from typing import Optional

from ..format import Format
from ..node import _Base, Dm_document, Root
from ..utility import Namespace, Utility

logger_name = __name__.split('.')[-1]
logger = logging.getLogger(logger_name)
logger.addFilter(
        lambda r: r.levelno > 20 or logger_name in Utility.logger_names)

# XXX should pull the wrap support into a utility

# XXX need to make it more obvious and easy to understand

# defaults
default_indent_step = 2
default_line_length = 79

# start-of-line indicators
verbatim_indicators = r' '
list_indicators = r'*#:'


# helper for determining description offset, and initial and subsequent indents
def indents(para):
    offset = 0
    indent = ''
    indent2 = ''

    # if verbatim, both indents are the same and are the verbatim indent
    # from the start of the paragraph
    match = re.match(r'([%s]+)' % verbatim_indicators, para)
    if match:
        offset = len(match.group(1))
        indent = match.group(1)
        indent2 = indent

    # if a list, initial indent is '' and subsequent indent is spaces matching
    # the indicator plus however many spaces followed it
    else:
        match = re.match(r'([%s]+\s*)' % list_indicators, para)
        if match:
            indent2 = len(match.group(1)) * ' '

    return offset, indent, indent2


# return props with xmlns_dmr immediately after xmlns_dm
# (assumes that xmlns_dmr, if present, is the last property)
def xmlns_props_order_func(props):
    # if xmlns_dmr isn't the last property, do nothing
    if not props or props[-1].name != 'xmlns_dmr':
        return props

    # otherwise insert it as indicated above
    props_ = []
    for prop in props[:-1]:
        props_ += [prop]
        if prop.name == 'xmlns_dm':
            props_ += [props[-1]]
    return props_


# can assume that Utility.whitespace() has been called
def wrap_attrs(props, *, ignore_attrs=None, override_attrs=None,
               props_order_func=None, level=0, offset=0,
               indent_step=default_indent_step,
               line_length=default_line_length):
    ignore_attrs = ignore_attrs or set()
    override_attrs = override_attrs or {}

    # XXX perhaps this function shouldn't be responsible for the initial space?
    #     (but it needs to know about it)
    initial_indent = ' '
    # XXX this was offset * ' '
    subsequent_indent = indent_step * (level + 2) * ' '
    # this is used for dict and list items
    extra_indent = indent_step * ' '

    # no wrapping if paragraphs haven't been split, e.g. by SplitTransform,
    # or if not wrapping text
    # XXX currently disabled; why would you ever not want to wrap attributes?
    # attrs_dict = {a.name: a.value_as_string for a in attrs}
    # attrs_str = Utility.nice_dict(attrs_dict, style='xml',
    #                               ignore=ignore_attrs,
    #                               override=override_attrs)
    # return [initial_indent + attrs_str]

    # offset is the offset to which attributes should be aligned
    # (this is reset to line_length for the second and subsequent lines)
    width = max(1, line_length - offset)

    # this is how it used to be done, when the supplied attrs had already been
    # converted (naively) to a string
    # XXX width was incorrect for the second and subsequent lines?
    # return textwrap.wrap(attrs, width=width, initial_indent=initial_indent,
    #                      subsequent_indent=subsequent_indent,
    #                      break_on_hyphens=False, break_long_words=False)

    # attrs is a tuple of Attr objects
    lines = []
    line = initial_indent

    # helper to add text to the current line, breaking if necessary
    def addtext(*, name=None, ext=None, val=None, term=False):
        nonlocal line
        buff = ''
        if name:
            prefix = '' if line.strip() == '' else ' '
            buff += '%s%s="' % (prefix, Utility.xmlattrname(name))
        if ext:
            buff += ext
        if val:
            prefix = '' if line.strip()[-1:] in {'', '"'} else ' '
            buff += '%s%s' % (prefix, Utility.xmlattrescape(val))
        if term:
            buff += '"'
        if len(line) + len(buff) > width:
            newline(force=True)
            buff = buff.lstrip()
        line += buff

    # helper to break the current line (if there's anything on it)
    def newline(*, force=False):
        nonlocal width, lines, line
        if force or line.strip() != '':
            lines += [line.rstrip()]
        width = line_length
        line = subsequent_indent

    # (cosmetic) check whether there are any dict or multivalued list
    # attributes; if so, put every attribute on a new line
    special = any([isinstance(a.value, dict) or (
            isinstance(a.value, list) and len(a.value) > 1) for a in props])

    props_ = props_order_func(props) if props_order_func else props
    for prop in props_:
        if prop.name in ignore_attrs:
            pass
        elif not isinstance(prop.value, (dict, list)) or not special:
            if special:
                newline(force=True)
            value = override_attrs.get(prop.name, prop.value_as_string)
            addtext(name=prop.name, val=value, term=True)
        elif isinstance(prop.value, dict):
            newline(force=True)
            addtext(name=prop.name)
            values = [item for pair in prop.value.items() for item in pair]
            for index, value in enumerate(values):
                newline()
                extra = extra_indent * (1 + index % 2)
                addtext(ext=extra, val=value)
            addtext(term=True)
        else:  # list
            newline(force=True)
            addtext(name=prop.name)
            for value in prop.value:
                newline()
                addtext(ext=extra_indent, val=value)
            addtext(term=True)

    newline()
    return lines


# can assume that Utility.whitespace() has been called
def wrap_text(text, *, have_split=False, level=0, no_wrap=False,
              indent_step=default_indent_step,
              line_length=default_line_length):
    # if paragraphs haven't been split, e.g. by SplitTransform, split by \n
    if not have_split:
        return text.split('\n')

    # split into paragraphs separated by \n followed by \n or a list
    # indicator
    # XXX the '#' list indicator is ambiguous (think #x0a) and so perhaps a
    #     space should be required after it? or (because it will almost never
    #     happen) just fix such cases if/when they occur
    # XXX similar things can happen with '*' (e.g. when used as a
    #     multiplication sign); basically prevent wrapping from putting
    #     special characters at the start of the line
    paras = re.split(r'\n(?:\n|(?=[%s]))' % list_indicators, text)

    # replace \n with space in each paragraph (ignore leading spaces in
    # second and subsequent lines
    paras = [re.sub(r'\n *', r' ', para) for para in paras]

    # replace non-leading multiple spaces with single spaces
    paras = [re.sub(r'(\S) +', r'\1 ', para) for para in paras]

    # calculate wrap width
    width = max(1, line_length - indent_step * (level + 1))

    # (re-)wrap paragraphs
    lines = []
    for para in paras:
        # add blank line between paragraphs
        # XXX this leaves blank lines between verbatim paragraphs and list
        #     items, even if they weren't there before (could remove some?)
        if lines:
            lines += ['']

        # wrap the paragraph; line length of 0 means no wrapping
        offset, initial_indent, subsequent_indent = indents(para)
        if no_wrap:
            lines += [initial_indent + para[offset:]]
        else:
            lines += textwrap.wrap(para[offset:], width=width,
                                   initial_indent=initial_indent,
                                   subsequent_indent=subsequent_indent,
                                   break_on_hyphens=False,
                                   break_long_words=False)
    return lines


class XMLFormat(Format):
    """XML report format.
    """

    # typenames before which to insert a newline
    # XXX I can't decide about componentRef
    _newline_typenames = ('import', 'dataType', 'glossary', 'abbreviations',
                          'bibliography', 'template', 'component', 'model',
                          'object', 'command', 'event', 'parameter', 'profile')

    @classmethod
    def _add_arguments(cls, arg_parser):
        arg_group = arg_parser.add_argument_group('xml report format '
                                                  'arguments')
        arg_group.add_argument('--xml-always-auto-newline',
                               action='store_true',
                               help='whether always to automatically handle '
                                    'newlines; usually only do this when '
                                    'generating \'full\' XML')
        arg_group.add_argument('--xml-always-auto-indent', action='store_true',
                               help='whether always to automatically handle '
                                    'indentation; usually only do this when '
                                    'generating \'full\' XML')
        arg_group.add_argument('--xml-indent-step', type=int,
                               default=default_indent_step,
                               help='indentation per level when '
                                    'auto-indenting; default: %r' %
                                    default_indent_step)
        arg_group.add_argument('--xml-line-length', type=int,
                               default=default_line_length,
                               help='maximum line length; default: %r' %
                                    default_line_length)
        arg_group.add_argument('--xml-no-wrap', action='store_true',
                               help="don't wrap text, e.g. descriptions")
        return arg_group

    def __init__(self, name: Optional[str] = None, **_kwargs):
        super().__init__(name)

        # whether paragraphs have been split; if so, can wrap them; this can be
        # overridden in __check_root()
        self._have_split = False

        # function to use when sorting attribute properties; this can be
        # overridden in __check_root()
        self._props_order_func = None

        # current manual indent based on 'other' and 'cdata' nodes; not used
        # when auto-indenting
        self._current_manual_indent = ''

    # check that only one file was supplied on the command-line
    def post_init(self, args) -> bool:
        if len(args.file) > 1:
            logger.error("can't generate XML when multiple files are "
                         "specified on the command-line")
            return True

    def _visit_begin(self, root: Root, **kwargs) -> None:
        self.__check_root(root)

    def _visit_node(self, node: _Base, *, level: int = 0,
                    name: Optional[str] = None, **kwargs) -> None:
        """Visit an individual node.
        """

        # manual indent comes from 'cdata' and 'other'
        if node.typename in {'cdata', 'other'}:
            match = re.search(r'( *)$', node.text)
            self._current_manual_indent = match.group(1)

        node.xml_done = self.__start_element(node, level=level, name=name)

    def _visit_post_elems(self, node: _Base, *, level: int = 0, **kwargs) -> \
            None:
        """All of a node's child nodes have been visited. If an XML element
        is still open (this is indicated by the ``xml_done`` attribute),
        close it."""

        # have to use hasattr() because xml_done won't be set for ignored nodes
        if hasattr(node, 'xml_done') and not node.xml_done:
            self.__end_element(node, level=level)
            node.xml_done = True

    def __check_root(self, root) -> None:
        assert len(root.xml_files) == 1
        dm_document = root.xml_files[0].dm_document

        # if SplitTransform has just split paragraphs, update the dmr
        # schema version and its schema location
        # XXX this check for 'split.py' isn't perfect; previously checked for
        #     SplitTransform, but it no longer exists
        if root.args.transform is not None and \
                any(str(t) == 'split.py' for t in root.args.transform):
            # add or update the dmr schema version
            xmlns_dmr_added = dm_document.xmlns_dmr is None
            dm_document.xmlns_dmr = dm_document.XMLNS_DMR_LATEST_URN

            # add or update its schema location
            xsi_schema_location = dm_document.xsi_schemaLocation
            if dm_document.XMLNS_DMR_ORIGINAL_URN in xsi_schema_location:
                del xsi_schema_location[dm_document.XMLNS_DMR_ORIGINAL_URN]
            xsi_schema_location[dm_document.XMLNS_DMR_LATEST_URN] = \
                dm_document.XMLNS_DMR_LATEST_LOCATION

            # if added the dmr schema version, use special key function when
            # sorting attribute properties
            if xmlns_dmr_added:
                self._props_order_func = xmlns_props_order_func

        # ensure use of the latest encountered namespaces
        for attr, namespaces in Namespace.namespaces_by_attr.items():
            # XXX need to integrate xmlns_dmr into the above logic
            if attr == 'xmlns_dmr':
                continue
            if len(namespaces) > 1:
                # XXX need to add the logic actually to use the latest
                logger.warning('would use the latest (of %d) %s namespace %s'
                               % (len(namespaces), attr, namespaces[-1]))

        # note whether paragraphs have been split
        self._have_split = \
            dm_document.xmlns_dmr_inherited and \
            dm_document.xmlns_dmr_inherited != \
            Dm_document.XMLNS_DMR_ORIGINAL_URN

    def __start_element(self, node: _Base, *, level: int = 0,
                        name: Optional[str] = None) -> bool:
        output = node.args.output
        typename = node.typename
        elemname = node.elemname
        auto_newline = \
            not node.args.thisonly or node.args.xml_always_auto_newline
        auto_indent = \
            not node.args.thisonly or node.args.xml_always_auto_indent
        indent_step = node.args.xml_indent_step
        line_length = node.args.xml_line_length
        no_wrap = node.args.xml_no_wrap

        indent = indent_step * level * ' ' if auto_indent else \
            self._current_manual_indent
        indent1 = indent + indent_step * ' '

        # the 'xml_version' attribute overrides version
        if hasattr(node, 'xml_version'):
            logger.info('%s: changed version %s to %s' % (
                node.objpath, node.version, node.xml_version))
            node.version = node.xml_version

        # determine which attributes are to be overridden
        attrs = node.attrs
        attrs_props = node.attrs_props
        override_attrs = {}
        if name and 'name' in attrs and name != attrs['name']:
            override_attrs['name'] = name

        # retain xmlns_dmr attributes only on dm_document
        # XXX hmm; in theory could use this on interior nodes
        ignore_attrs = set() if typename == 'dm_document' else {'xmlns_dmr'}

        # ignore base if both ref and base are present
        # XXX see node.py DataTypeRef._mergedone() ref to base copy logic
        if typename == 'dataTypeRef' and hasattr(node, 'ref') and hasattr(
                node, 'base') and node.ref and node.base:
            ignore_attrs.add('base')

        # special cases
        if typename == 'xml_decl':
            # no newline, because there will be a subsequent 'other'
            output.write('%s%s' % (indent, node.text))
        elif typename == 'comment':
            # always precede with newline unless at the top level
            newline = '\n' if level > 0 and auto_newline else ''
            prefix = indent if auto_indent else ''
            output.write('%s%s%s' % (newline, prefix, node.text))
        elif typename == 'cdata':
            # no newline, because it probably _is_ a newline
            # XXX this is rather hacky; could be simpler?
            text = node.text
            if auto_newline and auto_indent:
                text = text.rstrip()
            elif auto_indent:
                text = re.sub(r' *$', '', text)
            if text:
                output.write(text)
        elif typename == 'other':
            # no newline, because it probably _is_ a newline
            output.write(node.text)

        # normal case
        else:
            # no special newline handling when reporting on a single file
            if auto_newline:
                # always precede with newline unless at the top level
                # XXX could suppress this if the previous node was a comment?
                if level > 0:
                    output.write('\n')

                # add a blank line for the specified type names
                if typename in self._newline_typenames:
                    output.write('\n')

            # start the element and add the attributes
            prefix = indent if auto_indent else ''
            output.write(prefix + '<' + elemname)
            offset = len(indent) + 1 + len(elemname)
            if attrs_props:
                offset += 1  # for the space after the element name
                lines = wrap_attrs(attrs_props, override_attrs=override_attrs,
                                   ignore_attrs=ignore_attrs,
                                   props_order_func=self._props_order_func,
                                   level=level, offset=offset,
                                   line_length=line_length)
                if len(lines) > 0:
                    output.write('\n'.join(lines))
                    offset = len(lines[-1])

            # end the element if there's no text or element content
            # XXX this doesn't catch the case where some elems are ignored
            text = Utility.xmlelemvalue(node.text)
            if not text and not node.elems:
                output.write('/>')

            # otherwise terminate the start element
            else:
                output.write('>')
                offset += 1

                # add text, if any
                if text:
                    # expand the internal and undocumented {{np}} (new
                    # paragraph) macro
                    # XXX should really use a standard macro expansion function
                    #     for this, but providing all its context is too hard
                    if '{{np}}' in text:
                        text = text.replace('{{np}}', '\n\n')

                    # put it on the same line if possible and permitted
                    # XXX the 'permitted' criteria should be configurable
                    is_single_line = text.find('\n') < 0
                    allow_single_line = node.instance_in_path(
                            ('reference', 'enumeration', 'pattern'))
                    fits_on_line = no_wrap or offset + 2 + len(
                            elemname) + 1 + len(text) <= line_length
                    if is_single_line and allow_single_line and fits_on_line:
                        output.write(text)

                    # otherwise, wrap and put on multiple lines
                    else:
                        lines = wrap_text(text, have_split=self._have_split,
                                          level=level, no_wrap=no_wrap,
                                          indent_step=indent_step,
                                          line_length=line_length)
                        for line in lines:
                            indent1_ = indent1 if line else ''
                            output.write('\n' + indent1_ + line)
                        if not node.elems:
                            output.write('\n' + indent)

                # end the element if there's no element content
                if not node.elems:
                    output.write('</' + elemname + '>')

        # return value is 'done?'; if not done, __end_element() will be called
        return len(node.elems) == 0

    @staticmethod
    def __end_element(node: _Base, *, level: int = 0, **_kwargs) -> None:
        output = node.args.output
        auto_newline = \
            not node.args.thisonly or node.args.xml_always_auto_newline
        auto_indent =\
            not node.args.thisonly or node.args.xml_always_auto_indent
        newline = '\n' if auto_newline else ''
        prefix = node.args.xml_indent_step * level * ' ' if auto_indent else ''
        output.write('%s%s</%s>' % (newline, prefix, node.elemname))
