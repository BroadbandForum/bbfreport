"""Shared markdown and HTML support.

The markdown and HTML report formats are very similar, because conceptually
markdown is always generated and then (when generating HTML) the markdown is
converted to HTML.
"""

# Copyright (c) 2023-2025, Broadband Forum
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

# pyright: reportAttributeAccessIssue=false
# pyright: reportPrivateUsage=false

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import textwrap
import time

from io import TextIOBase
from typing import Any, Callable, cast, Self

from ... import version
from ...commonmark import Context, Document, _Heading, HtmlWriter, TextWriter
from ...exception import NodeException
from ...logging import Logging
from ...macro import MacroArg, MacroException, MacroRef
from ...macros.macros import get_markdown as macros_get_markdown
from ...node import AbbreviationsItem, _Command, Command, CommandRef, \
    DataType, DataTypeAccessor, Dt_document, _Event, Event, EventRef, \
    GlossaryItem, _HasContent, Input, Model, Node, Object, ObjectRef, \
    Output, Parameter, ParameterRef, Profile, Reference, Root
from ...pandoc import instructions as pandoc_instructions
from ...path import Path
from ...transform import Transform
from ...utility import StatusEnum, Utility
from ...visitor import Rules, Visitor

# XXX 'markdown' is a bad name for this module

# XXX need to replace 'if html' logic with class hierarchy (Report and ToC)

# XXX should update to use error, warning etc. rather than logger

# XXX could try to generate sensible output when --thisonly is specified

# XXX could try to generate sensible output when multiple files are specified


# whether this is an HTML report
# XXX should add this back as a Report method?
def is_html(args: argparse.Namespace) -> bool:
    return str(args.format) == 'html'


# whether the markdown is a full report, i.e. the 'diff' transform wasn't run
# XXX should make this generally available as a utility function
def is_full(args: argparse.Namespace) -> bool:
    transforms: list[Transform] = args.transform or []
    return not any(str(t) == 'diff' for t in transforms)


# XXX see macros.get_markdown() for why content markdown might not have been
#     generated; the reason most likely here is that it's a DT instance, so
#     markdown won't have been generated for referenced DM model items
def get_markdown(node: _HasContent, *, logger: logging.Logger) -> str:
    error = Logging.error_func(node, logger)
    warning = Logging.warning_func(node, logger)
    info = Logging.info_func(node, logger)
    debug = Logging.debug_func(node, logger)
    return macros_get_markdown(node.content, node=node, error=error,
                               warning=warning, info=info, debug=debug)


class Report:
    """Represents the complete report."""

    def __init__(self, root: Root, args: argparse.Namespace, *,
                 omit_if_unused: bool, rules: Rules, logger: logging.Logger):
        self.root = root
        self.args = args
        self.omit_if_unused = omit_if_unused
        self.rules = rules
        self.logger = logger

        # get the markdown renderer
        self.renderer = self.get_renderer(args)

        # initialize the ToC
        self.toc = ToC(logger, self.renderer)

        # output the report
        self.output()

    # XXX the renderer classes should be in a separate module
    def get_renderer(self, args: argparse.Namespace) -> Renderer:
        # this is always available and is used when specifically requested via
        # --html-use-commonmark or if markdown-it is unavailable
        class CommonmarkRenderer(Renderer):
            def __init__(self) -> None:
                super().__init__()
                self._context = Context()

            def slugify(self, title: str) -> str:
                return _Heading.slugify(title)

            def process(self, text: str | list[str], *,
                        as_list: bool = False) -> str | list[str]:
                document = Document(self._context, text)
                # this generates info-level logging output
                document.visit(TextWriter().visit)
                result = HtmlWriter().write(document)
                if not as_list:
                    result = ''.join(result)
                return result

        if str(args.format) == 'html' and not args.html_use_commonmark:
            try:
                from markdown_it import MarkdownIt

                # from mdit_py_plugins.admon import admon_plugin
                # from mdit_py_plugins.anchors import anchors_plugin
                from mdit_py_plugins.anchors import index as \
                    anchors_plugin_index
                from mdit_py_plugins.attrs import attrs_plugin
                from mdit_py_plugins.attrs import attrs_block_plugin
                from mdit_py_plugins.container import container_plugin
                # from mdit_py_plugins.deflist import deflist_plugin
                # from mdit_py_plugins.field_list import fieldlist_plugin
                # from mdit_py_plugins.footnote import footnote_plugin
                # from mdit_py_plugins.front_matter import front_matter_plugin
                # from mdit_py_plugins.tasklists import tasklists_plugin
                # from mdit_py_plugins.wordcount import wordcount_plugin

                class MarkdownItRenderer(Renderer):
                    # these characters need to be valid in identifiers, but
                    # also be very unlikely to occur in real life
                    MARKER = ':-:-:-:'

                    def __init__(self) -> None:
                        super().__init__()
                        # XXX can't use the anchors plugin because it
                        #     the overrides the attrs_block plugin
                        self._parser = MarkdownIt() \
                            .use(attrs_plugin, spans=True) \
                            .use(attrs_block_plugin)

                        # XXX it's annoying to have to list the container
                        #     plugin names (classes)
                        for name in {'chevron', 'diffs', 'hide', 'inserted',
                                     'removed'}:
                            self._parser.use(container_plugin, name=name)

                    def slugify(self, title: str) -> str:
                        return anchors_plugin_index.slugify(title)

                    def process(self, text: str | list[str], *,
                                as_list: bool = False) -> str | list[str]:
                        text = self._preprocess(text)
                        if isinstance(text, list):
                            text = ''.join(text)
                        result = self._parser.render(text)
                        result = self._postprocess(result)
                        if as_list:
                            result = result.splitlines()
                        return result

                    def _preprocess(self, text: str | list[str]) -> str:
                        """Pre-process markdown text to work around some
                        markdown-it deficiencies."""

                        lines: list[str] = []
                        for line in (text.splitlines()
                                     if isinstance(text, str) else text):
                            # markdown-it-py doesn't permit '.' in anchors
                            # (it's correct, but it should allow '\.')
                            if '{#' in line and '}' in line:
                                def func(m: re.Match[str]) -> str:
                                    return m[0].replace('.', self.MARKER)
                                line = re.sub(r'{#.+?}', func, line)
                            lines.append(line)
                        return '\n'.join(lines)

                    def _postprocess(self, text: str) -> str:
                        """Post-process HTML text to undo preprocessing and
                        handle some other markdown-it deficiencies."""

                        lines: list[str] = []
                        for line in text.splitlines():
                            # undo preprocessing
                            if self.MARKER in line:
                                line = line.replace(self.MARKER, '.')

                            # poor man's superscript
                            if '^' in line:
                                line = re.sub(r'\^(\d+)\^', r'<sup>\1</sup>',
                                              line)
                            lines.append(line)
                        return '\n'.join(lines)

                self.logger.info("using markdown-it parser")
                return MarkdownItRenderer()

            except (ModuleNotFoundError, ImportError) as e:
                self.logger.warning(e.msg)
                self.logger.warning('will use the (currently rather slow) '
                                    'built-in commonmark parser')
                return CommonmarkRenderer()

        else:
            self.logger.info("using (currently) slow commonmark parser")
            return CommonmarkRenderer()

    def output(self) -> None:
        if self.args.brief:
            self.output_models()
            self.output_toc()
        else:
            self.output_metadata()
            self.output_beginbody()
            self.output_beginmain()
            self.output_banner()
            self.output_license()
            self.output_summary()
            self.output_data_types()
            self.output_glossary()
            self.output_abbreviations()
            self.output_references()
            self.output_legend()
            self.output_models()
            self.output_footer()
            self.output_endmain()
            self.output_toc()
            self.output_endbody()

    # XXX would like to set header-includes in a separate block at the bottom,
    #     but commonmark seems to support only a single metadata block and it
    #     has to be at the top
    def output_metadata(self) -> None:
        # this assumes that keylast is the full path
        _, title = os.path.split(self.root.xml_files[-1].keylast)

        # YAML indentation in the print() calls below
        #
        prefix = 16 * ' '

        # pandoc instructions (not needed in HTML output)
        instructions = textwrap.indent(pandoc_instructions(),
                                       prefix=prefix + '  ')


        # HTML <head> info; it's only added when generating HTML, because the
        # markdown-to-HTML processor, e.g., pandoc, is respomsible for this
        h_h_i = textwrap.indent(html_head_info[1:] % title, prefix=prefix)

        # styles and scripts
        # XXX need to work out what we need from bbf.css!
        s_and_s = styles_and_scripts
        if self.root.args.show:
            s_and_s += '\n\n' + link_styles.strip()
        s_and_s = textwrap.indent(s_and_s, prefix=prefix + '    ')

        # handle markdown and HTML separately because it would be too messy to
        # do this in self.print()
        if not is_html(self.args):
            # this is the first thing in the output file, so no initial newline
            # XXX if using the default pandoc HTML template, it's important NOT
            #     to define 'title' (it mucks up the flex layout)
            self.print('''\
                ---
                comment: |
%s
                title: ''
                pagetitle: %s
                lang: en-us
                document-css: false
                header-includes:
                  - |
%s
                ---''' % (instructions, title, s_and_s), noescape=True)

        else:
            # XXX need title and other meta-information
            self.print('''\
%s
%s
                </head>
            ''' % (h_h_i, s_and_s), literal=True)

    def output_beginbody(self) -> None:
        if is_html(self.args):
            self.print('<body>', literal=True)

    def output_beginmain(self) -> None:
        if not is_html(self.args):
            self.print('\n:::::: {#main}')
        else:
            self.print('<div id="main">', literal=True)

    def output_banner(self) -> None:
        # use the last file on the command line (usually there will be only
        # one, but if generating diffs there will be two)
        xml_file = self.root.xml_files[-1]

        # use the last model (usually there will be only one, but if
        # generating diffs of two models in the same file there will be two)
        document = xml_file.document
        model = document.models[-1]

        # try to get the title from the first comment's first line
        title = ''
        if comment := xml_file.comments[0].text:
            assert comment.startswith('<!--') and comment.endswith('-->')
            lines = textwrap.dedent(comment[4:-3]).splitlines()
            lines = [line.strip() for line in lines if line.strip() != '']
            if len(lines) > 0 and not lines[0].startswith('Copyright'):
                title = lines[0]

        # failing that, get it from the data model information
        if title == '':
            if model:
                title = ('USP ' if model.usp else 'CWMP ') + (
                            '%s ' % model.name) + (
                            'Service ' if model.isService else 'Root ')
            title += 'Object definition'

        # add a 'changes' indicator
        if not is_full(self.args):
            title += ' (changes)'

        # add any additional file info
        # XXX the presentation needs to be improved
        info = ''
        if file_info := document.file_info:
            info = ', '.join('%s: %s' % (name, value) for name, value in
                             file_info.items() if value)
            if info:
                if not is_html(self.args):
                    info = '## %s' % info
                else:
                    info = '<h2>%s</h2>' % info

        # BBF and logo information
        bbf_url = 'https://www.broadband-forum.org'
        logo_url = '%s/images/logo-broadband-forum.gif' % bbf_url

        # relative path (only works with web server) and file name
        # XXX does the relative path need to be customizable?
        rel_path = './'
        file = document.file_safe

        # style information
        classes = ['list-table', 'full-width']
        widths = [3, 22, 50, 25]
        header_rows = 0

        # output the table
        # XXX the Table class can't handle colspan and rowspan
        if not is_html(self.args):
            self.print('''
                {%s widths=%s header-rows=%d}
                - - []{colspan=2}[![Broadband Forum](%s){width=100%%}](%s)
    
                  - []{.centered rowspan=2}
    
                    # %s {.unnumbered .unlisted}
    
                    %s
    
                    # [%s](%s#%s) {.unnumbered .unlisted}
    
                  - []{rowspan=2}
    
                - -
                  - ### DATA MODEL DEFINITION {.unnumbered .unlisted}''' % (
                ' '.join('.%s' % cls for cls in classes),
                ','.join(str(wid) for wid in widths), header_rows, logo_url,
                bbf_url, title, info, file, rel_path, file))

        else:
            # noinspection PyListCreation
            lines = []
            lines.append('<table class="%s">' % ' '.join(
                    cls for cls in classes if cls != 'list-table'))
            lines.append('<colgroup>')
            for width in widths:
                lines.append('<col style="width: %d%%;">' % width)
            lines.append('</colgroup>')
            lines.append('<tbody>')
            lines.append(
                    '<tr><td colspan="2"><a href="%s"><img width="100%%" '
                    'alt="Broadband Forum" src="%s"></a></td>'
                    '<td class="centered" rowspan="1"><p></p>'
                    '<h1 class="unnumbered unlisted">%s</h1>'
                    '%s'
                    '<h1 class="unnumbered unlisted"><a '
                    'href="%s#%s">%s</a></h1></td><td rowspan="1"></td></tr>' %
                    (bbf_url, logo_url, title, info, rel_path, file, file))
            lines.append(
                    '<tr><td></td><td><h3 id="data-model-definition" '
                    'class="unnumbered unlisted">DATA MODEL DEFINITION</h3>'
                    '</td></tr>')
            lines.append('</tbody>')
            lines.append('</table>')
            self.print(lines, literal=True)

    def output_summary(self) -> None:
        document = self.root.xml_files[-1].document
        sections = []

        # disable this because any information in the top-level description
        # should now be in PROJECT.yaml
        if False and (section := get_markdown(document.description,
                                              logger=self.logger)):
            sections.append(section)

        # but do output top-level DT annotation
        # XXX need to extend annotation support to all node types
        if isinstance(document, Dt_document) and (section := get_markdown(
                document.annotation, logger=self.logger)):
            sections.append(section)

        # output the summary
        if sections:
            self.output_header(1, 'Summary')
            self.print()
            self.print('\n\n'.join(section.strip() for section in sections))

    def output_license(self) -> None:
        if comment := self.root.xml_files[-1].comments[0].text:
            assert comment.startswith('<!--') and comment.endswith('-->')
            lines = textwrap.dedent(comment[4:-3]).splitlines()
            # noinspection PyShadowingBuiltins
            license: list[str] = []
            seen_start = False
            seen_end = False
            for line in lines:
                if not seen_start:
                    if line.lstrip().startswith('Copyright'):
                        seen_start = True
                if seen_start:
                    # ensure that any additional copyrights are on their own
                    # lines and indented
                    if len(license) > 0 and \
                            line.lstrip().startswith('Copyright'):
                        license[-1] += '\\'
                        line = 4 * '&nbsp;' + line.lstrip()
                    # assume that the first blank line after the 'Any moral
                    # rights' line marks the end of the license
                    if line.lstrip().startswith('Any moral rights'):
                        seen_end = True
                    if seen_end and line.strip() == '':
                        break
                    license.append(line)
            if license:
                self.output_header(1, 'License', notoc=True)
                self.print()
                self.print('\n'.join(license), noescape=True)

    # XXX need to handle primitive data types (do this at the node.py level?)
    def output_data_types(self) -> None:
        # if omit_if_unused is False but the (single) file name contains
        # 'biblio', don't output any data types
        if not self.omit_if_unused and len(self.args.file) == 1 \
                and 'biblio' in self.args.file[0]:
            return

        # XXX need an Accessor API for this; visitor.py should use the same API
        data_types_dict = {name: data_type for name, data_type in
                           DataTypeAccessor.entities.values()}
        data_types_used = {name: data_type for name, data_type in
                           data_types_dict.items() if not
                           name.startswith('_') and self.include(data_type)}

        if data_types_used:
            self.output_header(1, 'Data Types')

            # macros have already been expanded; we could expand the
            # boilerplate, but it's simpler to handle this manually
            soap = 'SOAP1.1'
            bibref = self.root.find(Reference, soap)
            if bibref:
                soap = '[%s](#%s)' % (bibref.id, bibref.anchor)
                bibref.is_used = True  # so it'll be included in the report

            # output the boilerplate
            self.print('''
                The Parameters defined in this specification make use of a
                limited subset of the default SOAP data types [%s]. These data
                types and the named data types used by this specification
                are described below.

                Note: A Parameter that is defined to be one of the named data
                types is reported as such at the beginning of the Parameter's
                description via a reference back to the associated data type
                definition (e.g. *[MACAddress]*). However, such parameters
                still indicate their SOAP data types.''' % soap)

            table = Table('Data Type', 'Base Type', 'Description',
                          logger=self.logger, renderer=self.renderer,
                          classes=['full-width', 'partial-border',
                                   'data-type-table'])

            # list lower-case (primitive) data types first; do this by
            # returning a (starts-with-upper-case, name) tuple
            def key(item: tuple[str, DataType]) -> tuple[bool, str]:
                nam = item[0]
                upp = bool(re.match(r'[A-Z]', nam))
                return upp, nam

            for name, data_type in sorted(data_types_used.items(), key=key):
                name = '[%s]{#%s}' % (name, data_type.anchor)
                base = r'\-'
                base_type = None  # XXX this should really be Null
                if data_type.base and not data_type.base.startswith('_'):
                    base = data_type.base
                    base_type = data_type.baseNode
                # primitive types' self.primitive is self
                elif (prim_type := data_type.primitive_inherited.data_type) \
                        and prim_type is not data_type:
                    base = prim_type.name
                    base_type = prim_type
                if base_type:
                    # XXX this omits the list facet, which is on the data
                    #     type itself; this isn't quite right yet...
                    facets = Elem.format(data_type.primitive_inherited,
                                         facetsonly=True)
                    if data_type.list:
                        facets += Elem.format(data_type.list)
                    base = '[%s](#%s)%s' % (base, base_type.anchor, facets)
                description = get_markdown(data_type.description_inherited,
                                           logger=self.logger)
                table.add_row(name, base, description)
            self.print(table)

    def output_glossary(self) -> None:
        items = GlossaryItem.findall(predicate=lambda i: self.include(i))
        if items:
            self.output_header(1, 'Glossary')
            table = Table('ID', 'Description', logger=self.logger,
                          renderer=self.renderer,
                          classes=['middle-width', 'partial-border'])
            for item in cast(list[GlossaryItem],
                             sorted(items, key=lambda i: i.id.lower())):
                # XXX need to define an anchor
                table.add_row(item.id, get_markdown(item.description,
                                                    logger=self.logger))
            self.print(table)

    def output_abbreviations(self) -> None:
        items = AbbreviationsItem.findall(predicate=lambda i: self.include(i))
        if items:
            self.output_header(1, 'Abbreviations')
            table = Table('ID', 'Description', logger=self.logger,
                          renderer=self.renderer,
                          classes=['middle-width', 'partial-border'])
            for item in cast(list[AbbreviationsItem],
                             sorted(items, key=lambda i: i.id.lower())):
                # XXX need to define an anchor
                table.add_row(item.id, get_markdown(item.description,
                                                    logger=self.logger))
            self.print(table)

    def output_references(self) -> None:
        # IETF RFC and BBF specification patterns
        ietf_pattern = re.compile(r'''
            RFC                 # type (has to be 'RFC')
            -?                  # optional hyphen (shouldn't really be there)
            (?P<nnn>\d+)        # number
        ''', re.VERBOSE)
        bbf_pattern = re.compile(r'''
            (?P<tr>\w+)         # type, e.g. 'TR'
            -                   # hyphen
            (?P<nnn>\d+)        # number, e.g. '069'
            (?:i(?P<i>\d+))?    # optional issue number
            (?:a(?P<a>\d+))?    # optional amendment number
            (?:c(?P<c>\d+))?    # optional corrigendum number
        ''', re.VERBOSE)

        # helper to define missing hyperlinks for known document types
        def get_hyperlinks(ref: Reference) -> list[str]:
            if ref.hyperlinks:
                return [h.text for h in ref.hyperlinks]
            elif ref.organization.text in {'IETF'} and \
                    (match := re.fullmatch(ietf_pattern, ref.id)):
                link = 'https://www.rfc-editor.org/rfc/rfc%s' % match['nnn']
                self.logger.info('generated %s hyperlink %s' % (ref.id, link))
                return [link]
            elif ref.organization.text in {'Broadband Forum', 'BBF'} and \
                    (match := re.fullmatch(bbf_pattern, ref.id)):
                tr, nnn, i, a, c = match['tr'], match['nnn'], \
                    match['i'], match['a'], match['c']
                i = '' if i is None else '_Issue-%s' % i
                a = '' if a is None else '_Amendment-%s' % a
                c = '' if c is None else '_Corrigendum-%s' % c
                link = 'https://www.broadband-forum.org/download/%s-%s%s%s' \
                       '%s.pdf' % (tr, nnn, i, a, c)
                self.logger.info('generated %s hyperlink %s' % (ref.id, link))
                return [link]
            else:
                return []

        # if omit_if_unused is False but the (single) file name is not
        # 'tr-069-biblio', only include 'used' references
        predicate = lambda i: self.include(i)
        if not self.omit_if_unused and len(
                self.args.file) == 1 and Utility.path_nameonly(
                self.args.file[0]) != 'tr-069-biblio':
            predicate = lambda i: i.is_used
        items = Reference.findall(predicate=predicate)
        if items:
            self.output_header(1, 'References')
            table = Table(logger=self.logger, renderer=self.renderer)
            for item in cast(list[Reference],
                             sorted(items, key=lambda i: i.id.lower())):
                # XXX markdown-it fails to parse '[[[id]{#anchor}]](url)',
                #     because by default it processes links first (could set
                #     span_after?), so invert as '[[[id](url)]{#anchor}]'
                # name = '[[%s]{#%s}]' % (item.id, item.anchor)
                name = item.id
                if hyperlinks := get_hyperlinks(item):
                    name = '[%s](%s)' % (name, hyperlinks[0])
                    if len(set(hyperlinks)) > 1:
                        secondary = ', '.join(h for h in hyperlinks[1:])
                        self.logger.warning('%s: ignored secondary '
                                            'hyperlinks %s' % (
                                                item.nicepath, secondary))
                name = '[[%s]{#%s}]' % (name, item.anchor)
                text = item.name.text or ''
                if item.title:
                    text += ', *%s*' % item.title.text
                if item.organization:
                    text += ', %s' % item.organization.text
                if item.date:
                    text += ', %s' % item.date.text
                text += '.'
                table.add_row(name, text)
            self.print(table)

    # XXX the legend is hardly worth it for CWMP; should omit it?
    def output_legend(self) -> None:
        models = self.root.xml_files[-1].document.models
        if models:
            usp = any(model.usp for model in
                      self.root.xml_files[-1].document.models)
            self.output_header(1, 'Legend')
            table = Table(logger=self.logger, renderer=self.renderer,
                          classes=['middle-width', 'partial-border'])
            for row, classes, cwmp in (
                    (['Object definition.'], ['object'], True),
                    (['Mount point definition.'],
                     ['mountpoint-object'], False),
                    (['Parameter definition.'], ['parameter'], True),
                    (['Command or Event definition.'], ['command'], False),
                    (['Command Input / Output Arguments container.'],
                     ['argument-container'], False),
                    (['Command or Event Object Input / Output Argument '
                      'definition.'], ['argument-object'], False),
                    (['Command or Event Parameter Input / Output Argument '
                      'definition.'], ['argument-parameter'], False)):
                if cwmp or usp:
                    table.add_row(*row, classes=classes)
            self.print(table)

    def output_models(self) -> None:
        for xml_file in self.root.xml_files:
            for model in xml_file.document.models:
                if not model.is_hidden:
                    self.output_model(model)

    def output_model(self, model: Model) -> None:
        ModelTableElem.reset()

        # collect the description
        # XXX we don't really want the initial newline, but it does no harm
        comps = [textwrap.dedent('''
            For a given implementation of this data model, the Agent MUST
            indicate support for the highest version number of any object
            or parameter that it supports. For example, even if the Agent
            supports only a single parameter that was introduced in version
            1.4, then it will indicate support for version 1.4. The version
            number associated with each object and parameter is shown in
            the **Version** column.''')]
        if markdown := get_markdown(model.description, logger=self.logger):
            comps.append(markdown)

        self.output_header(1, '%s Data Model' % model.name, show=3)
        self.print('\n\n'.join(comps))

        # output the main table (which doesn't contain profiles)
        table = Table('Name', 'Type', 'Write', 'Description', 'Object Default',
                      'Version', logger=self.logger,
                      renderer=self.renderer,
                      classes=['full-width', 'partial-border',
                               'data-model-table'])
        # XXX strictly should use Visitor group-ordering logic,
        #     like .output_node()
        for node in model.elems:
            if not node.is_hidden and node not in model.profiles:
                self.output_node(node, table)
        self.print(table)

        if is_full(self.args) and not self.args.brief:
            self.output_notification_tables(model)
            self.output_profiles(model.profiles)

    def output_notification_tables(self, model: Model) -> None:
        # determine whether this is a USP model
        usp = model.usp

        # collect all the parameters
        parameters = model.parameters + [param for obj in model.objects for
                                         param in obj.parameters]

        # header (different for USP) is output lazily
        text = 'Notification Requirements' if usp else \
            'Inform and Notification Requirements'
        header = {'done': False, 'text': text}

        # output the first three tables (not for USP)
        if not usp:
            self.output_notification_table(
                    parameters, 'Forced Inform Parameters',
                    lambda p: p.forcedInform, header=header)
            self.output_notification_table(
                    parameters, 'Forced Active Notification Parameters',
                    lambda p: p.activeNotify == 'forceEnabled', header=header)
            self.output_notification_table(
                    parameters, 'Default Active Notification Parameters',
                    lambda p: p.activeNotify == 'forceDefaultEnabled',
                    header=header)

        # output the last table (it lists objects and parameters separately
        title = 'Parameters for which %s Notification MAY be Denied' % (
            'Value Change' if usp else 'Active')
        self.output_notification_table(parameters, title,
                                       lambda p: p.activeNotify == 'canDeny',
                                       header=header, separate_objects=True)

    def output_notification_table(self, parameters: list[Parameter],
                                  title: str, predicate: Callable, *,
                                  header: dict[str, Any] | None = None,
                                  separate_objects: bool = False) -> None:
        def node_class(node) -> str:
            status = node.status_inherited
            return '%s%s' % ('%s-' % status.value if status.value != 'current'
                             else '', node.typename)

        # ignore NodeException when testing the predicate
        def matches(p: Parameter) -> bool:
            try:
                return predicate(p)
            except NodeException:
                return False

        # do nothing if there's nothing to output
        parameters_ = [param for param in parameters if matches(param)]
        if not parameters_:
            return

        # output the level 2 header if not already done
        if header is not None and not header['done']:
            self.output_header(2, header['text'])
            header['done'] = True

        self.output_header(3, title)
        table = Table('Parameter', logger=self.logger,
                      renderer=self.renderer,
                      classes=['middle-width', 'partial-border'])
        current_object = None
        for parameter in parameters_:
            # (a) each row is the full parameter path
            if not separate_objects:
                table.add_row(
                    '[%s](#%s)' % (parameter.objpath, parameter.anchor),
                    classes=[node_class(parameter)])

            # (b) objects have their own rows, parameters have just names
            else:
                # parent will be Null if it's a top-level parameter
                parent = parameter.object_in_path
                if parent and parent is not current_object:
                    table.add_row(
                            '[%s](#%s)' % (parent.objpath, parent.anchor),
                            classes=[node_class(parent)])
                    current_object = parent
                table.add_row('[%s](#%s)' % (parameter.name, parameter.anchor),
                              classes=[node_class(parameter)])

        self.print(table)

    def output_profiles(self, profiles: list[Profile]) -> None:
        visible_profiles = [prof for prof in profiles if not prof.is_hidden]

        if visible_profiles:
            self.output_header(2, 'Profile Definitions', sort=3)
            self.output_header(3, 'Notation')
            self.print()
            self.print('The following abbreviations are used to specify '
                       'profile requirements:')
            table = Table('Abbreviation', 'Description', logger=self.logger,
                          renderer=self.renderer,
                          classes=['middle-width', 'partial-border',
                                   'profile-notation-table'])
            # XXX should use CSS to center the first column
            table.add_row('R', 'Read support is REQUIRED.')
            table.add_row('W', 'Both Read and Write support is REQUIRED. This '
                               'MUST NOT be specified for a parameter that is '
                               'defined as read-only.')
            table.add_row('P', 'The object is REQUIRED to be present.')
            table.add_row('C', 'Creation and deletion of instances of the '
                               'object is REQUIRED.')
            table.add_row('A', 'Creation of instances of the object is '
                               'REQUIRED, but deletion is not REQUIRED.')
            table.add_row('D', 'Deletion of instances of the object is '
                               'REQUIRED, but creation is not REQUIRED.')
            self.print(table)

            for profile in visible_profiles:
                self.output_profile(profile)

    def output_profile(self, profile: Profile) -> None:
        # if its name begins with an underscore it's internal, and will be
        # expanded by profiles that reference it via base or extends
        if profile.name.startswith('_'):
            return

        # model.keylast includes only the major version number
        model = profile.model_in_path
        model_name_major = model.keylast
        model_name_only = re.sub(r':\d+$', '', model_name_major)

        # expand internal profiles (see the note above)
        elems = profile.profile_expand(base=True, extends=True,
                                       internal_only=True)

        self.output_header(3, '%s Profile' % profile.name, profile.anchor,
                           status=profile.status.value)

        # get a list of its non-internal referenced base and extends profiles
        refs = [profile.baseNode] + profile.extendsNodes
        refs = [ref for ref in refs if ref and not ref.name.startswith('_')]
        if not refs:
            self.print('\nThis table defines the *%s* profile for the *%s* '
                       'data model.' % (profile.name, model_name_major))
        else:
            extra = Utility.nicer_list(refs,
                                       lambda p: '*[%s](#%s)*' % (
                                           p.name, p.anchor))
            plural = 's' if len(refs) > 1 else ''
            self.print('\nThe *%s* profile for the *%s* data model is defined '
                       'as the union of the %s profile%s and the additional '
                       'requirements defined in this table.' % (
                        profile.name, model_name_major, extra, plural))

        # XXX strictly this should use model.minVersions, but this has never
        #     and will never be used
        self.print('The minimum REQUIRED version for this profile is %s:%s.'
                   % (model_name_only, profile.version_inherited))

        table = Table('Name', 'Requirement', logger=self.logger,
                      renderer=self.renderer,
                      classes=['middle-width', 'partial-border',
                               'profile-requirements-table'], widths=[90, 10])
        footnotes = []
        # the entire profile (including internal dependencies) is in the elems
        # list, so don't recurse (recursion would add duplicates)
        for node in elems:
            if not node.is_hidden:
                self.output_node(
                        node, table, norecurse=True, footnotes=footnotes)
        self.print(table)

        if footnotes:
            # noinspection PyListCreation
            lines: list[str] = []
            lines.append('')
            for num, note in enumerate(footnotes):
                term = '\\' if num < len(footnotes) - 1 else ''
                lines.append('^%d^ %s%s' % (num + 1, note, term))
            self.print(lines)

    def output_footer(self) -> None:
        # helper to format the args string
        interesting = {'all', 'include', 'nocurdir', 'file',  'filter',
                       'format', 'output', 'plugindir', 'show', 'thisonly',
                       'transform'}
        positional = {'file'}  # only supported for list-valued arguments

        def args_string() -> str:
            args = []
            for name, value in vars(self.root.args).items():
                if name in interesting:
                    if isinstance(value, bool):
                        if value:
                            args.append('--%s' % name)
                    elif not isinstance(value, list):
                        if value:
                            if isinstance(value, TextIOBase):
                                # noinspection PyUnresolvedReferences
                                value = value.name
                            args.append('--%s %s' % (name, value))
                    else:
                        for val in value:
                            prefix = '--%s ' % name if name not in positional \
                                else ''
                            args.append('%s%s' % (prefix, val))

            return ' '.join(args)

        def tool_name() -> str:
            return os.path.basename(sys.argv[0])

        # use UTC dates and times
        now = time.gmtime()
        now_date = time.strftime('%Y-%m-%d', now)
        now_time = time.strftime('%H:%M:%S', now)

        self.print('''
            ---

            Generated by %s on %s at %s UTC.\\
            %s %s''' % (version(as_markdown=True), now_date, now_time,
                        tool_name(), args_string()))

    def output_header(self, level: int, text: str, anchor: str = '', *,
                      status: str = 'current', notoc: bool = False,
                      **kwargs: Any) -> None:
        # noinspection PyListCreation
        lines: list[str] = []
        lines.append('')
        # XXX can't assume support for auto-identifiers but can assume support
        #     for block attributes
        lines.append('{#%s}' % (anchor or self.renderer.slugify(text)))
        status_ = ' [%s]' % status.upper() if status != 'current' else ''
        lines.append('%s %s%s' % (level * '#', text, status_))
        self.print(lines)
        if not notoc:
            self.toc.entry(level, text, target=anchor, status=status, **kwargs)

    # utilities

    def output_node(self, node: Node, table: 'Table', *,
                    norecurse: bool = False,
                    footnotes: list[tuple[str, str]] | None = None) -> None:
        if self.omit_if_unused and node.is_used is False:
            return

        elem = Elem.create(node, toc=self.toc, logger=self.logger,
                           footnotes=footnotes)
        row = elem.row
        # Description elems (for example) have no rows
        if row is not None:
            if elem.need_separator:
                table.add_separator(classes=elem.section_classes, elem=elem)
            table.add_row(*row, classes=elem.row_classes, elem=elem)
            if not norecurse:
                # XXX this uses the Visitor element-ordering logic, which
                #     should be made easier to use
                groups = Visitor.get_groups(node, rules=self.rules)
                for groupname, group in groups.items():
                    for child in group:
                        if not child.is_hidden:
                            self.output_node(child, table, footnotes=footnotes)

    def output_endmain(self) -> None:
        if not is_html(self.args):
            self.print('\n::::::')
        else:
            self.print('</div>', literal=True)

    def output_toc(self) -> None:
        if not is_html(self.args):
            self.print('\n::: {#TOC}')
            self.output_header(1, 'Table of Contents', notoc=True)
            self.print(self.toc.markdown, literal=True)
            self.print(':::')
        else:
            self.print('<div id="TOC">', literal=True)
            self.print('<h1>Table of Contents</h1>', literal=True)
            self.print(self.toc.html, literal=True)
            self.print('</div>', literal=True)

    def output_endbody(self) -> None:
        if is_html(self.args):
            self.print('</body>', literal=True)

    def include(self, node: Node) -> bool:
        # ignore self.omit_is_unused for primitive data types
        omit_if_unused = True if isinstance(node, DataType) and re.match(
                r'^[a-z]', node.name) else self.omit_if_unused
        return not omit_if_unused or node.is_used

    def print(self, text: str | list[str] | Table = '', *,
              width: int = 0, literal: bool = False, nodedent: bool = False,
              noescape: bool = False) -> None:
        if not is_html(self.args):
            if isinstance(text, Table):
                text = text.markdown
        elif literal:
            noescape = True
        else:
            if isinstance(text, Table):
                text = text.html
                noescape = True
            else:
                if isinstance(text, str) and not nodedent:
                    text = textwrap.dedent(text)
                    nodedent = True
                text = self.renderer.process(text)
                noescape = True

        if isinstance(text, list):
            text = '\n'.join(text)

        if not nodedent:
            text = textwrap.dedent(text)

        # XXX it's not necessary to escape '<' and '>' characters, because we
        #     assume that the pandoc raw_html extension will be disabled
        # XXX but we're no longer using pandoc...
        if not noescape:
            # text = re.sub(r'([<>])', r'\\\1', text)
            # XXX GitHub-flavored markdown (GFM) emoji will be parsed; should
            #     do a more general check for them, or else disable them, but
            #     for now just handle ':100:', which renders as 💯(U+1F4AF)
            # XXX should move this somewhere more sensible
            if ':100:' in text:
                text = text.replace(':100:', r'\:100:')

        # XXX experimental; needs more work; need to be careful with lists...
        if width > 0:
            lines = textwrap.wrap(text, width=width)
            for line in lines:
                self.args.output.write(line + '\n')
        else:
            self.args.output.write(text + '\n')


class Renderer:
    """Markdown parser + renderer base class."""

    def __init__(self) -> None:
        pass

    def slugify(self, title: str) -> str:
        raise NotImplementedError

    def process(self, text: str | list[str], *,
                as_list: bool = False) -> str | list[str]:
        raise NotImplementedError


class ToCEntry:
    """ToC entry."""

    @classmethod
    def get(cls, toc: ToC, parent: Self | None, text: str,
            **kwargs: Any) -> Self | None:
        if parent is not None:
            for child in parent.children:
                # XXX ignore trailing dot (see ToC.entry()); messy...
                if child.text in {text, text + '.'}:
                    return child
        return cls(toc, parent, text, **kwargs)

    def __init__(self, toc: ToC, parent: Self | None, text: str, *,
                 target: str = '', status: str = 'current', show: int = 1,
                 sort: int = 0):
        self.toc = toc
        self.parent = parent
        self.text = text
        self.target = target
        self.status = status
        self.show = show
        self.sort = sort
        self.children: list[Self] = []

        if parent:
            parent.children.append(self)

        toc.update(self)

    def render(self, renderer: ToCRenderer, *, level: int = 1,
               lines: list[str] | None = None) -> list[str]:
        if lines is None:
            lines = []

        childless = not self.children

        # we don't want the top-level (root) list item
        if level > 1:
            classes = self._item_classes(level - 1)
            lines.extend(
                    renderer.open_item(self.text, self.target, level=level - 1,
                                       status=self.status, classes=classes,
                                       also_close=childless))

        if not childless:
            classes = self._list_classes(level)
            lines.extend(renderer.open_list(level=level, classes=classes))

            for child in self.children:
                child.render(renderer, level=level + 1, lines=lines)

            lines.extend(renderer.close_list(level=level))

        if level > 1 and not childless:
            lines.extend(renderer.close_item(level=level - 1))

        return lines

    def _list_classes(self, level: int) -> list[str]:
        classes = []
        if self.children:
            classes.append('collapsed')
            if level <= self.show:
                classes.append('expanded')
            if level == self.sort:
                classes.append('ordered')
        return classes

    def _item_classes(self, level: int) -> list[str]:
        classes = []
        if self.children:
            if level < self.show:
                classes.append('collapsible')
            if self.children:
                classes.append('expandable')
        return classes

    def __str__(self) -> str:
        return f'{self.text}[{len(self.children)}]'

    __repr__ = __str__


class ToCRenderer:
    """ToC entry renderer. Handles markdown / HTML differences. The default
    implementation is just for testing."""

    def __init__(self, markdown_renderer: Renderer):
        self.markdown_renderer = markdown_renderer

    def open_list(self, *, level: int = 1,
                  classes: list[str] | None = None) -> list[str]:
        indent = self._indent(level)
        return ['', f'{indent}open list {classes}']

    def close_list(self, *, level: int = 1) -> list[str]:
        indent = self._indent(level)
        return [f'{indent}close list']

    def open_item(self, value: str, target: str | None = None, *,
                  level: int = 1, status: str = 'current',
                  classes: list[str] | None = None,
                  also_close: bool = False) -> list[str]:
        indent = self._indent(level)
        return [f'{indent}add item {value} {classes}']

    def close_item(self, *, level: int = 1) -> list[str]:
        indent = self._indent(level)
        return [f'{indent}close item']

    @staticmethod
    def _indent(level: int, *, is_item: bool = False) -> str:
        # level is 1-based
        return 2 * (level - 1) * ' '


class ToC:
    """Table of contents."""

    def __init__(self, logger: logging.Logger, markdown_renderer: Renderer):
        self.logger = logger
        self.markdown_renderer = markdown_renderer

        root = ToCEntry(self, None, 'Root')
        self.tree: ToCEntry = root
        self.latest: list[ToCEntry] = [root]

    def find(self, level: int, text: str) -> ToCEntry | None:
        if len(self.latest) >= level:
            parent = self.latest[level - 1]
            for child in parent.children:
                if child.text == text:
                    return child
        return None

    def update(self, child: ToCEntry) -> None:
        latest = []
        entry = child
        while entry is not None:
            latest.insert(0, entry)
            entry = entry.parent
        self.latest = latest

    def entry(self, level: int, text: str, *, split: bool = False,
              **kwargs: Any) -> None:
        self.logger.debug(f'ToC.entry:{level} {text=}')

        # default parent (might be modified below)
        parent = self.latest[min(level, len(self.latest)) - 1]

        # split: text is object, command or event path name
        if split and re.search(r'(\.|\(\)|!)$', text):
            # if it's a command or event, temporarily add a final dot
            # XXX perhaps should get Path() to worry about this? the problem
            #     is the chameleon-like behavior of commands and events
            command_or_event = False
            if not text.endswith('.'):
                text += '.'
                command_or_event = True
            # e.g., 'Device.Capabilities.' -> ['Device', 'Capabilities', '']
            comps = Path(text).comps
            # e.g., 1
            prelen = len(comps) - 2
            # e.g., 'Capabilities.'
            text = '.'.join(comps[prelen:])
            # if it's a command or event, remove the temporary final dot
            if command_or_event:
                text = text[:-1]

            # get (find or create) intervening entries
            for i, comp in enumerate(comps[:prelen]):
                lev = level + i
                parent = ToCEntry.get(self, parent, comp, **kwargs)
                self.logger.debug(f'ToC.entry:  {lev} {comp=!r} '
                                  f'{self.latest=}')

        # create the entry
        _ = ToCEntry(self, parent, text, **kwargs)
        self.logger.debug(f'ToC.entry:  -> {text=!r} {self.latest=}')

    @property
    def markdown(self) -> list[str]:
        class MarkdownToCRenderer(ToCRenderer):
            def open_list(self, *, level: int = 1,
                          classes: list[str] | None = None) -> list[str]:
                indent = self._indent(level)
                lines: list[str] = ['']
                if classes:
                    attrs = '{%s}' % ' '.join('.%s' % cls for cls in classes)
                    lines.append(f'{indent}{attrs}')
                return lines

            def close_list(self, *, level: int = 1) -> list[str]:
                return ['']

            def open_item(self, value: str, target: str | None = None, *,
                          level: int = 1, status: str = 'current',
                          classes: list[str] | None = None,
                          also_close: bool = False) -> list[str]:
                indent = self._indent(level)
                value = f'[{value}]'
                if target:
                    value += f'(#{target})'
                if classes:
                    attrs = '{%s}' % ' '.join('.%s' % cls for cls in classes)
                    value = f'[{value}]{attrs}'
                if status != 'current':
                    value += ' [%s]' % status.upper()
                return [f'{indent}* {value}']

            def close_item(self, *, level: int = 1) -> list[str]:
                return []

        return self.tree.render(MarkdownToCRenderer(self.markdown_renderer))

    @property
    def html(self) -> list[str]:
        class HTMLToCRenderer(ToCRenderer):
            def open_list(self, *, level: int = 1,
                          classes: list[str] | None = None) -> list[str]:
                indent = self._indent(level)
                attrs = ' class="%s"' % ' '.join(classes) if classes else ''
                return [f'{indent}<ul{attrs}>']

            def close_list(self, *, level: int = 1) -> list[str]:
                indent = self._indent(level)
                return [f'{indent}</ul>']

            def open_item(self, value: str, target: str | None = None, *,
                          level: int = 1, status: str = 'current',
                          classes: list[str] | None = None,
                          also_close: bool = False) -> list[str]:
                indent = self._indent(level, is_item=True)
                slash_li = '</li>' if also_close else ''
                if not target:
                    target = self.markdown_renderer.slugify(value)
                value = f'<a href="#{target}">{value}</a>'
                if classes:
                    attrs = ' class="%s"' % ' '.join(classes)
                    value = f'<span{attrs}>{value}</span>'
                if status != 'current':
                    value += ' [%s]' % status.upper()
                return [f'{indent}<li>{value}{slash_li}']

            def close_item(self, *, level: int = 1) -> list[str]:
                indent = self._indent(level, is_item=True)
                return [f'{indent}</li>']

            def _indent(self, level: int, *, is_item: bool = False) -> str:
                # the base class only indents once per list
                return (2 * (level - 1) + int(is_item)) * '  '

        return self.tree.render(HTMLToCRenderer(self.markdown_renderer))


class Table:
    def __init__(self, *labels: str, logger: logging.Logger,
                 renderer: Renderer, widths: list[int] | None = None,
                 classes: list[str] | None = None):
        self.labels = (labels, None, None)
        self.logger = logger
        self.renderer = renderer
        self.widths = widths
        self.classes = classes
        self.rows = []

    # a separator is indicated by a row of None
    # XXX passing elem is temporary (just for reporting)
    def add_separator(self, *, classes: list[str] | None = None,
                      elem=None) -> None:
        self.rows.append((None, classes, elem))

    def add_row(self, *row, classes: list[str] | None = None,
                elem=None) -> None:
        self.rows.append((row, classes, elem))

    # the markdown always starts with an empty line, but is not terminated with
    # an empty line (the caller is responsible for that)
    @property
    def markdown(self) -> list[str]:
        classes = '' if not self.classes else \
            ' %s' % ' '.join('.%s' % cls for cls in self.classes)
        headers = '' if self.labels[0] else ' header-rows=0'
        widths = '' if not self.widths else \
            ' widths=%s' % ','.join(str(w) for w in self.widths)
        attrs = '{.list-table%s%s%s}' % (classes, headers, widths)

        # noinspection PyListCreation
        lines = []
        lines.append('')
        lines.append('%s' % attrs)
        indented = False
        all_rows = ([self.labels] if self.labels[0] else []) + self.rows
        for row_num, (row, classes, elem) in enumerate(all_rows):
            # convert classes to a string
            classes_str = ''
            if classes:
                classes = cast(list[str], classes)
                classes_str = ' '.join('.%s' % cls for cls in classes)

            # a row of None indicates a separator, which opens (if there are
            # classes) or closes a table body
            if row is None:
                sep = ' ' if classes_str else ''
                lines.append('- {.list-table-body%s%s}' % (sep, classes_str))
                indented = True
                continue

            indent = '  ' if indented else ''

            outer = '-'
            if classes:
                lines.append('%s%s []{%s}' % (indent, outer, classes_str))
                outer = ' '
            for cell in row:
                # the cell data should already be a string, but don't assume...
                cell = str(cell)
                inner = '-'
                space = ''
                for line in cell.split('\n'):
                    lines.append('%s%s %s %s%s' % (
                        indent, outer, inner, space, line))
                    # XXX leading space on the first line causes problems, so
                    #     insert such space on all lines
                    # XXX should ignore more than four spaces, because they
                    #     would indicate a code block?
                    # XXX lint should catch and fix this
                    if inner == '-':
                        if line.startswith(' ') and line.strip() != '':
                            space = re.sub(r'^(\s*).*?$', r'\1', line)
                            self.logger.warning('invalid leading whitespace '
                                                'in %r...' % cell[:40])
                    outer = ' '
                    inner = ' '
            if row_num < len(all_rows) - 1:
                lines.append('')
        return lines

    # the HTML always starts with an empty line, but is not terminated with
    # an empty line (the caller is responsible for that)
    # XXX it might be nice (optionally?) to indent the output
    @property
    def html(self) -> list[str]:
        # noinspection PyListCreation
        lines = []
        lines.append('')

        # table
        classes_str = ' class="%s"' % ' '.join(self.classes) \
            if self.classes else ''
        lines.append('<table%s>' % classes_str)

        # columns
        if self.widths:
            lines.append('<colgroup>')
            total = sum(self.widths)
            pass
            for width in self.widths:
                percent = 100 * width / total
                lines.append('<col style="width: %.1f%%;">' % percent)
            lines.append('</colgroup>')

        # headers
        if self.labels[0]:
            lines.append('<thead>')
            lines.append('<tr>')
            for label in self.labels[0]:
                lines.append('<th>%s</th>' % label)
            lines.append('</tr>')
            lines.append('</thead>')

        # body
        lines.append('<tbody>')
        for row_num, (row, classes, elem) in enumerate(self.rows):
            # XXX should omit class="" when there are no classes
            classes_str = ' class="%s"' % ' '.join(classes) if classes else ''

            # a row of None indicates a separator, which opens (if there are
            # classes) or closes a table body
            if row is None:
                lines.append('</tbody>')
                lines.append('<tbody%s>' % classes_str)
                continue

            lines.append('<tr%s>' % classes_str)
            for cell in row:
                lines.append('<td>')
                # the cell data should already be a string, but don't assume...
                # XXX this actually appends a single line that can contain
                #     newlines (returning as multiple lines would be wrong
                #     because the caller would insert additional newlines)
                lines.append(self.renderer.process(str(cell)))
                lines.append('</td>')
            lines.append('</tr>')
        lines.append('</tbody>')
        lines.append('</table>')
        return lines

    def __str__(self) -> str:
        return '%s (%d)' % (self.labels, len(self.rows))

    def __repr__(self) -> str:
        return '%s(%s)' % (type(self).__name__, self)


# XXX classes need to know what to put into table rows; messy...
class Elem:
    """Node wrapper (referred to as "element" to avoid confusion)."""

    # various constants
    # XXX could use things like '`&lArr;`{=html}' but this can confuse pandoc
    #     in some contexts, so use the plain HTML entity versions
    LARR = '&lArr;'
    RARR = '&rArr;'
    # XXX use the actual character here, because markdown-it doesn't seem to
    #     support entities in attribute values
    INFIN = '∞'  # '&infin;'

    # this is populated by Elem.init()
    _ctors = {}

    # should call Elem.init() after all subclasses have been defined
    # (if this isn't done, only Elem instances will be created)
    # XXX could do this lazily on first invocation
    @classmethod
    def init(cls) -> None:
        cls._ctors[cls.__name__] = cls
        for subclass in cls.__subclasses__():
            subclass.init()

    @classmethod
    def create(cls, node: Node, **kwargs: Any):
        name = type(node).__name__
        name = name.replace('Dt_', '')
        name = name[:1].upper() + name[1:]
        name = '%sElem' % name
        ctor = cls._ctors.get(name, Elem)
        return ctor(node, **kwargs)

    def __init__(self, node: Node, *,
                 toc: ToC | None, logger: logging.Logger | None,
                 footnotes: list[str] | None = None,
                 **kwargs: Any):
        self.node = node
        self.toc = toc
        self.logger = logger
        self.footnotes = footnotes
        assert not kwargs, 'unexpected keyword arguments %s' % kwargs

    # this formats the node and then escapes some problematic characters, e.g.
    # '[' and ']' in '[0:1](:64)', which would otherwise be interpreted as a
    # link
    @staticmethod
    def format(node: Node, *, noescape: bool = False, **kwargs: Any) -> str:
        text = node.format(**kwargs)
        if not noescape:
            text = re.sub(r'([\[\]])', r'\\\1', text)
        return text

    # subclasses can override this
    @property
    def need_separator(self) -> bool:
        return False

    # subclasses can override this
    @property
    def section_classes(self) -> list[str]:
        return []

    # subclasses can override this
    @property
    def row_classes(self) -> list[str]:
        return []

    # subclasses can override this
    @property
    def row(self) -> tuple[str, ...] | None:
        return None

    # XXX some of these helpers aren't type-safe; they should be further
    #     down the class hierarchy

    @property
    def status_prefix(self) -> str:
        status = self.node.h_status_inherited
        if status.value != 'current':
            return status.value + '-'
        else:
            return ''

    @property
    def arrow_prefix(self) -> str:
        if self.node.instance_in_path((Input, _Event)):
            return self.RARR + ' '
        elif self.node.instance_in_path(Output):
            return self.LARR + ' '
        else:
            return ''

    @property
    def argument_prefix(self) -> str:
        if self.node.instance_in_path((_Command, CommandRef, _Event,
                                       EventRef)):
            return 'argument-'
        else:
            return ''

    # XXX DT instances can use 'createDelete'
    access_map = {
        'readOnly': 'R',
        'readWrite': 'W',
        'writeOnceReadOnly': 'WO',
        'createDelete': 'C'
    }

    @property
    def access_string(self) -> str:
        node = self.node

        # commands and events don't have access attributes
        if node.instance_in_path(Input):
            return 'W'
        elif node.instance_in_path((Output, _Event)):
            return 'R'

        # noinspection PyUnresolvedReferences
        access = node.access.value
        if access not in self.access_map:
            # need to update access_map
            self.logger.warning('%s: unsupported access %s' % (
                node.nicepath, access))
        return self.access_map.get(access, '?%s?' % access)

    @property
    def type_string(self) -> str:
        return Elem.format(self.node, typ=True)

    requirement_map = access_map | {
        'notSpecified': r'\-',
        'present': 'P',
        'create': 'A',
        'delete': 'D',
        'createDelete': 'C'
    }

    @property
    def requirement_string(self) -> str:
        node = self.node

        # command refs and event refs don't have requirement attributes
        if node.instance_in_path((CommandRef, EventRef)):
            return r'\-'

        # noinspection PyUnresolvedReferences
        requirement = node.requirement.value
        if requirement not in self.requirement_map:
            self.logger.warning('%s: unsupported requirement %s' % (
                node.nicepath, requirement))
        return self.requirement_map.get(requirement, '?%s?' % requirement)

    @property
    def default_string(self) -> str:
        return r'\-'

    @property
    def footref(self) -> str:
        return ''

    def __str__(self) -> str:
        return '%s (%s)' % (self.node, self.node.status)

    def __repr__(self) -> str:
        return '%s(%s)' % (type(self).__name__, self)


class ModelTableElem(Elem):
    """Base class for elements that can occur in the model table.

    The main value-add is support for deprecated etc. elements.
    """
    section_active = False

    @classmethod
    def reset(cls) -> None:
        """Reset internal state before outputting a new model table."""
        cls.section_active = False

    def __init__(self, node: Node, **kwargs: Any):
        super().__init__(node, **kwargs)

        # expandable / contractable section properties
        self.need_showable_class = False
        self.need_showable2_class = False
        # XXX need to double-check use of these two
        self.need_hide_class = False
        self.hide_class = ''
        self._set_section_properties()

    def _toc_entry(self) -> None:
        if self.toc is not None:
            node = self.node
            # XXX we shouldn't have to cast it; something isn't quite right
            status = cast(str, node.status.value)
            self.toc.entry(2, node.objpath, target=node.anchor, split=True,
                           status=status, show=3, sort=3)

    # XXX it would be clearer not to use this, but instead always use node
    #     status directly as needed
    def _set_section_properties(self) -> None:
        node = self.node

        # only non-current nodes can start new sections
        if node.h_status_inherited.value == StatusEnum.default:
            pass

        # ensure that this isn't the root object (if it is, something else
        # has gone wrong
        elif not (h_parent := node.h_parent):
            pass

        # if the parent node is current, this is the root of a showable tree
        elif h_parent.h_status_inherited.value == 'current':
            # some old data models might not use {{deprecated}} etc. macros
            # noinspection PyUnresolvedReferences
            has_status_macro = any(
                    status in node.description.content.macro_refs for status in
                    StatusEnum.values)
            self.need_showable_class = has_status_macro

        # if this node is not current (in its own right), showable2 is set so
        # its description can be expanded and collapsed
        elif node.status.value != 'current':
            self.need_showable2_class = True
            self.need_hide_class = True

        # everything within a showable tree (but not its root) needs the
        # hide class
        else:
            self.need_hide_class = True

        # only descriptions at the root of showable trees need the hide class
        # on their hidden-by-default parts (other nodes are hidden/shown at
        # the row level)
        if self.need_showable_class or self.need_showable2_class:
            self.hide_class = 'hide'

    @property
    def need_separator(self) -> bool:
        """Determine whether this element needs a section separator."""
        cls = type(self)
        retval = False
        if self.need_showable_class:
            cls.section_active = True
            retval = True
        elif self.section_active and not self.need_hide_class:
            cls.section_active = False
            retval = True
        return retval

    @property
    def section_classes(self) -> list[str]:
        classes = []
        if self.need_showable_class:
            classes.append('showable')
        return classes + super().section_classes

    @property
    def row_classes(self) -> list[str]:
        classes = []

        # the node version can be greater than the model version if it was
        # added in a corrigendum
        # XXX should use the diff-determined additions rather than relying on
        #     the version attribute (although errors should have been caught)
        if self.node.args.show and self.node.version_inherited >= \
                self.node.model_in_path.model_version:
            classes.append('inserted')
        if self.need_showable2_class:
            classes.append('showable2')
        if self.need_hide_class:
            classes.append('hide')
        # 'show2' means that when the showable block is expanded, the showable2
        # item is collapsed
        if self.need_showable2_class:
            classes.append('show2')
        return classes + super().row_classes

    # XXX this is called a lot; should try to make it as efficient as possible
    @staticmethod
    def expand_classes(default: str, *, node, stack, **_kwargs) -> str:
        # this is only valid as a {{div}} or {{span}} argument
        if len(stack) < 2 or (caller := stack[-2]).name not in {'div', 'span'}:
            raise MacroException('only valid as {{div}} or {{span}} argument')

        # {{div}} and {{span}} optional second argument is content (have to
        # check explicitly for missing argument)
        content = caller.args[1] if len(caller.args) > 1 else MacroArg()

        # returned classes are the supplied defaults, potentially altered below
        classes = default.split()

        elem = Elem.create(node.parent, toc=None, logger=None)
        if isinstance(elem, ModelTableElem) and elem.hide_class:
            # if called from {{div}}
            if caller.name == 'div':
                # add the hide class unless the div content contains a
                # {{<status>}} macro reference (where <status> is the parent
                # node status), in which case add 'chevron'
                found = any(isinstance(item, MacroRef) and item.name ==
                            node.parent.status.value for item in content.items)
                classes.append(elem.hide_class if not found else 'chevron')

            # if called from {{span}} and its caller is {{<status>}} (as above)
            elif len(stack) > 2 and stack[-3].name == node.parent.status.value:
                # add the hide class unless the content is empty, in which
                # case add 'click'
                classes.append(elem.hide_class if content.items else 'click')

        return ' '.join(classes)


class ObjectElem(ModelTableElem):
    @property
    def row_classes(self) -> list[str]:
        return [self.status_prefix + self.argument_prefix + 'object'] + \
               super().row_classes

    @property
    def row(self) -> tuple[str, ...]:
        node = cast(Object, self.node)
        # unnamed objects are omitted
        # XXX should extend this check to other node types?
        if not node.name:
            return None
        # argument objects aren't included in the ToC
        if not node.command_in_path and not node.event_in_path:
            self._toc_entry()
        name = '[%s]{#%s}' % (node.name, node.anchor)
        return (self.arrow_prefix + name,
                self.type_string,
                self.access_string,
                get_markdown(node.description, logger=self.logger), r'\-',
                node.version_inherited.name)

    @property
    def type_string(self) -> str:
        text = super().type_string
        text = '[%s]{title="%s"}' % (text.replace('unbounded', ''),
                                     text.replace('unbounded', self.INFIN))
        return text


class ParameterElem(ModelTableElem):
    @property
    def row_classes(self) -> list[str]:
        return [self.status_prefix + self.argument_prefix + 'parameter'] + \
               super().row_classes

    @property
    def row(self) -> tuple[str, ...]:
        node = cast(Parameter, self.node)
        name = '[%s]{#%s}' % (node.name, node.anchor)
        return (self.arrow_prefix + name,
                self.type_string,
                self.access_string,
                get_markdown(node.description, logger=self.logger),
                self.default_string,
                node.version_inherited.name)

    @property
    def type_string(self) -> str:
        node = cast(Parameter, self.node)
        text = super().type_string
        if node.syntax.dataType:
            text = '[%s]{title="%s"}' % (
                Elem.format(node, typ=True, prim=True),
                Elem.format(node, typ=True, noescape=True))
        return text

    @property
    def default_string(self) -> str:
        node = cast(Parameter, self.node)
        if not (default := node.syntax.default) or default.type != 'object':
            return super().default_string

        value = default.value
        if node.syntax.list and \
                (bracketed := re.match(r'^\s*\[\s*(.*?)\s*]\s*$', value)):
            value = bracketed[1]
        return Utility.nice_string(value, empty=r'*\<Empty\>*', escape=True)


class CommandElem(ModelTableElem):
    @property
    def row_classes(self) -> list[str]:
        return [self.status_prefix + 'command'] + super().row_classes

    @property
    def row(self) -> tuple[str, ...]:
        node = cast(Command, self.node)

        self._toc_entry()

        name = '[%s]{#%s}' % (node.name, node.anchor)
        return (name, 'command', r'\-',
                get_markdown(node.description, logger=self.logger), r'\-',
                node.version_inherited.name)


class InputElem(ModelTableElem):
    @property
    def row_classes(self) -> list[str]:
        return [self.status_prefix + 'argument-container'] + \
               super().row_classes

    @property
    def row(self) -> tuple[str, ...]:
        return (self.arrow_prefix + 'Input.', 'arguments', r'\-',
                'Input arguments.', r'\-', '')


class OutputElem(ModelTableElem):
    @property
    def row_classes(self) -> list[str]:
        return [self.status_prefix + 'argument-container'] + \
               super().row_classes

    @property
    def row(self) -> tuple[str, ...]:
        return (self.arrow_prefix + 'Output.', 'arguments', r'\-',
                'Output arguments.', r'\-', '')


class EventElem(ModelTableElem):
    @property
    def row_classes(self) -> list[str]:
        return [self.status_prefix + 'event'] + super().row_classes

    @property
    def row(self) -> tuple[str, ...]:
        node = cast(Event, self.node)

        self._toc_entry()

        name = '[%s]{#%s}' % (node.name, node.anchor)
        return (name, 'event', r'\-',
                get_markdown(node.description, logger=self.logger), r'\-',
                node.version_inherited.name)


class ProfileTableElem(Elem):
    @property
    def footref(self) -> str:
        node = self.node
        if self.footnotes is None or node.status.value == 'current':
            return ''
        else:
            self.footnotes.append('This %s is %s.' % (
                node.elemname, node.status.value.upper()))
            return '^%s^' % len(self.footnotes)


class ObjectRefElem(ProfileTableElem):
    @property
    def row_classes(self) -> list[str]:
        return [self.status_prefix + self.argument_prefix + 'object'] + \
               super().row_classes

    @property
    def row(self) -> tuple[str, ...]:
        node = cast(ObjectRef, self.node)
        ref = '[%s](#%s)' % (node.ref, node.anchor)
        return ref, self.requirement_string + self.footref


class ParameterRefElem(ProfileTableElem):
    @property
    def row_classes(self) -> list[str]:
        return [self.status_prefix + self.argument_prefix + 'parameter'] + \
               super().row_classes

    @property
    def row(self) -> tuple[str, ...]:
        node = cast(ParameterRef, self.node)
        ref = '[%s](#%s)' % (node.ref, node.anchor)
        return ref, self.requirement_string + self.footref


class CommandRefElem(ProfileTableElem):
    @property
    def row_classes(self) -> list[str]:
        return [self.status_prefix + 'command'] + super().row_classes

    @property
    def row(self) -> tuple[str, ...]:
        node = cast(CommandRef, self.node)
        ref = '[%s](#%s)' % (node.ref, node.anchor)
        return ref, r'\-' + self.footref


class InputRefElem(ProfileTableElem):
    @property
    def row_classes(self) -> list[str]:
        return [self.status_prefix + 'argument-container'] + \
               super().row_classes

    @property
    def row(self) -> tuple[str, ...]:
        return 'Input.', r'\-' + self.footref


class OutputRefElem(ProfileTableElem):
    @property
    def row_classes(self) -> list[str]:
        return [self.status_prefix + 'argument-container'] + \
               super().row_classes

    @property
    def row(self) -> tuple[str, ...]:
        return 'Output.', r'\-' + self.footref


class EventRefElem(ProfileTableElem):
    @property
    def row_classes(self) -> list[str]:
        return [self.status_prefix + 'event'] + super().row_classes

    @property
    def row(self) -> tuple[str, ...]:
        node = cast(EventRef, self.node)
        ref = '[%s](#%s)' % (node.ref, node.anchor)
        return ref, r'\-' + self.footref


Elem.init()


# the rest of the file defines HTML <head> info, CSS styles and JavaScript

# this is taken from the pandoc default HTML template; note "%s" for the title
html_head_info = r'''
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="en-us" xml:lang="en-us">
<head>
    <meta charset="utf-8" />
    <meta name="generator" content="pandoc" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0,
          user-scalable=yes" />
    <title>%s</title>
    <style>
        code{white-space: pre-wrap;}
        span.smallcaps{font-variant: small-caps;}
        div.columns{display: flex; gap: min(4vw, 1.5em);}
        div.column{flex: auto; overflow-x: auto;}
        div.hanging-indent{margin-left: 1.5em; text-indent: -1.5em;}
        /* The extra [class] is a hack that increases specificity enough to
           override a similar rule in reveal.js */
        ul.task-list[class]{list-style: none;}
        ul.task-list li input[type="checkbox"] {
            font-size: inherit;
            width: 0.8em;
            margin: 0 0.8em 0.2em -1.6em;
            vertical-align: middle;
        }
    </style>
'''

toc_sidebar_styles = r'''
<!-- Sidebar ToC styles -->
<style>
@media screen and (min-width: 60em) {
    body {
        display: flex;
        align-items: stretch;
        margin: 0px;
        /* XXX this is experimental; may need to insert zero-width spaces */
        overflow-wrap: break-word;
    }

    #main {
        flex: 4 2 auto;
        overflow: auto;
        order: 2;
        padding: 5px;
    }

    #TOC {
        position: sticky;
        order: 1;
        flex: 1 0 auto;
        margin: 0 0;
        top: 0px;
        left: 0px;
        height: 100vh;
        line-height: 1.4;
        resize: horizontal;
        font-size: larger;
        overflow: auto;
        border-right: 1px solid #73AD21;
        padding: 5px;
        max-width: 20%;
    }

    #TOC ul {
        margin: 0.35em 0;
        padding: 0 0 0 1em;
        list-style-type: none;
    }

    #TOC ul ul {
        margin: 0.25em 0;
    }

    #TOC ul ul ul {
        margin: 0.15em 0;
    }

    #TOC {
        z-index: 1;
    }
}
</style>
'''

toc_expand_script = r'''
<!-- ToC expansion and contraction script -->
<script>
window.addEventListener('DOMContentLoaded', function() {
    var expandables = document.getElementsByClassName('expandable');
    for (i = 0; i < expandables.length; i++) {
        expandables[i].addEventListener('click', function() {
            this.parentElement.querySelector('.collapsed').classList
                .toggle('expanded');
            this.classList.toggle('collapsible');
        });
    }
});
</script>
'''

toc_expand_styles = r'''
<!-- ToC expansion and contraction styles -->
<style>
.expandable {
    cursor: pointer;
    user-select: none;
    display: list-item;
    /* Circled Plus + non-breakable space */
    list-style-type: "\2295\A0";
}

.collapsible {
    /* Circled Minus + non-breakable space */
    list-style-type: "\2296\A0";
}

.collapsed {
    display: none;
}

.expanded {
    display: grid; /* needed by the 'order' property */
}
</style>
'''

toc_sort_script = r'''
<!-- ToC sorting script (works for object names and profile headers) -->
<script>
window.addEventListener('DOMContentLoaded', function() {
    /* 'A.B.' -> {prefix: '', name: 'A.B.', 'version': ''}
       '_Baseline:1' -> {prefix: '_', name: 'Baseline', version: '1'} */
    var regex = /^(?<prefix>_?)(?<name>[^:]*)(:?)(?<version>\d*)/;
    var lists = document.getElementsByClassName('ordered');
    for (var i = 0; i < lists.length; i++) {
        var items = lists[i].children;
        var temp = [];
        for (var j = 0; j < items.length; j++) {
            /* this assumes that the first child contains the text */
            temp.push([j, items[j].children[0].innerText]);
        }
        temp.sort((a, b) => {
            /* 'Notation' (which is used for profiles) must come first */
            var a1 = a[1] == 'Notation' ? ' Notation' : a[1];
            var b1 = b[1] == 'Notation' ? ' Notation' : b[1];
            var a1_groups = a1.match(regex).groups;
            var b1_groups = b1.match(regex).groups;
            var a1_tuple =  [
                a1_groups.name.toLowerCase() + (a1_groups.prefix || '~'),
                parseInt(a1_groups.version || 0)];
            var b1_tuple =  [
                b1_groups.name.toLowerCase() + (b1_groups.prefix || '~'),
                parseInt(b1_groups.version || 0)];
            return a1_tuple < b1_tuple ? -1 : a1_tuple > b1_tuple ? 1 : 0;
        });
        temp.forEach((order_text, j) => {
            var k = order_text[0];
            items[k].style.order = j;
        });
    }
});
</script>
'''

autotitle_script = r'''
<!-- Automatic title generation (from anchor ids) script
     XXX only works for non-deprecated object parameters and doesn't
         show correct full paths; should get rid of it? -->
<script>
window.addEventListener('DOMContentLoaded', function() {
    var pars = document.getElementsByClassName('parameter');
    var regex = /\w\.\w+:[0-9.]+\./;
    for (var i = 0; i < pars.length; i++) {
        if (pars[i].firstElementChild && pars[i].firstElementChild.
                firstElementChild) {
            pars[i].firstElementChild.title =
                pars[i].firstElementChild.firstElementChild.id.
                replace(regex, '');
        }
    }
});
</script>
'''

hoverlink_script = r'''
<!-- Automatic on-hover link generation script -->
<script>
window.addEventListener('DOMContentLoaded', function() {
    var hoverlink = null;

    var anchors = document.querySelectorAll('td span[id]:not(:empty)');
    for (var i = 0; i < anchors.length; i++) {
      var cell = anchors[i].parentElement;

      cell.addEventListener('mouseenter', event => {
        var target = event.target;
        var anchor = target.querySelector('span[id]:not(:empty)');

        /* derive the item type from the row's first class item,
         * which might have a leading 'deprecated-' etc. and
         * might also contain additional hyphens */
        var itemType = (target.parentElement.classList.item(0) || 'item').
            replace(/^\w+-/, '').replace(/-/g, ' ');

        if (hoverlink) {
          hoverlink.remove();
          hoverlink = null;
        }

        hoverlink = document.createElement('a');
        hoverlink.href = '#' + anchor.id;
        hoverlink.className = 'hoverlink';
        hoverlink.title = 'Permalink to this ' + itemType;
        target.appendChild(hoverlink);
      });

      cell.addEventListener('mouseleave', () => {
        if (hoverlink) {
          hoverlink.remove();
          hoverlink = null;
        }
      });
    }
});
</script>
'''

# this is https://usp.technology/specification/permalink.png
# (line breaks are removed)
# noinspection SpellCheckingInspection
hoverlink_image_base64 = '''
iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAAAXNSR0IArs4c6QAAAIRlWElmTU0AKg
AAAAgABQESAAMAAAABAAEAAAEaAAUAAAABAAAASgEbAAUAAAABAAAAUgEoAAMAAAABAAIAAIdpAAQA
AAABAAAAWgAAAAAAAABIAAAAAQAAAEgAAAABAAOgAQADAAAAAQABAACgAgAEAAAAAQAAAECgAwAEAA
AAAQAAAEAAAAAAtWsvswAAAAlwSFlzAAALEwAACxMBAJqcGAAAAVlpVFh0WE1MOmNvbS5hZG9iZS54
bXAAAAAAADx4OnhtcG1ldGEgeG1sbnM6eD0iYWRvYmU6bnM6bWV0YS8iIHg6eG1wdGs9IlhNUCBDb3
JlIDUuNC4wIj4KICAgPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAy
LzIyLXJkZi1zeW50YXgtbnMjIj4KICAgICAgPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIKIC
AgICAgICAgICAgeG1sbnM6dGlmZj0iaHR0cDovL25zLmFkb2JlLmNvbS90aWZmLzEuMC8iPgogICAg
ICAgICA8dGlmZjpPcmllbnRhdGlvbj4xPC90aWZmOk9yaWVudGF0aW9uPgogICAgICA8L3JkZjpEZX
NjcmlwdGlvbj4KICAgPC9yZGY6UkRGPgo8L3g6eG1wbWV0YT4KTMInWQAACn9JREFUeAHNW9luHMcV
7ekZkuIicuiI0BJDUARDIiBISKwHQRZg6SEWwCyIk4DxbtgP9g94i9/8D16+JY4XwMljHFmmGNkJ8p
4gj7a8aMv4nDv3NKuHNb3NDDkNtKpZU9u5y6lbt1tJgmtzc7ONosXbn/e7jsua4T+4FtM0fRflf3F/
22q1/oLyMm5ebDPKmvvgr1y50uFAKA9w1M3NM7Pnz5+3wfe6ztdi4LvdpAvA27h7WFYPgsjK2dnZZ7
jWS5cuHWTZcM3E3de8gBK4g0/2qc4Wtbq6ugLgN9PUwH8P8P/HWiGE1h2v6y0uLj5HAFjvQsM10+p3
NB+Cv3jx4rwPnglkD+ocfBKCv72j+RYFQCu43273reHAgQPPcp24ZmIKi63Z25nLy9cpxb0EmkQWVh
W8XOE+heECeaovg8QwyBoic+TmhSBsztB/cg2qDjSGdnXBG3CAvw/gvXa7TaswIWAtCxRGGXhyBtuZ
BYwBQOmEBXM0BS9CNCHQEuQOFy5cWCY2zlkwbyILMF9wvyjtVCbZogkjfeuAJwmGZi9XoDVYPX6PEm
NkXoLnjrevJFgHfKZlgL1HoFWJsQR8a79IsA54B9xiEPRPB3+3X2YkKIGEFlJKjHKBvSbBJuBJdL8G
6LTT6dxw8NgeBwMkE0glYtwvEmwK/nGAlrXOw/yvO/hYjEBryFymiBhlAXtFgiOB95DXxjh9+jTD32
seDJklRKyhkBj3mgRHAh9uawGprVAIBI77Np7FA/zbbtQVRYx7FgmmvV6v5QcbxfbDTFeER583sw/B
a4uF9pYALqEl0B0IHtZwh2UAXgIZSoxygUmSYGtjY2MOC5sFg3/GxeG5Cvjfol0SAy8LUIlm8yDGLZ
QEb+7Qf9bJMU6M586dW0S7yUaCOqpCS284eJ7qPILLzJSaCjVfCj6I8Dq0LsAgMX5eIuCQGO0ofeLE
CTv+T5IEmWhJoKGPUOSA+mJzdTD7HHhq2TXdlsYD8IkTWVNifJZr45UlQsLBYxPWrfMFco4/OWPfI/
Ai8G41bfk7O/uV0p1UH64leCYxfsYECuZwTthlcRkxou1l7a0TOQNoYfPz83/EZFwUXCALXnaZfbjV
OXf8/ODBhZfQ9xHculIJNlQY6kJi9GBpx7WCeemCdygk3Eyv5dJJo5zqYn1Fgh2Y96e+CGR0dgIVmb
2Dt1TY2lr3p1jWTSU9uFi0+xh1q56zTEPwErRKtEvR/t8oKfQsHhD/uIVQEN+YBcTMahx1rqkUEyUg
nC6KLQdli8Iif8ffQvCHDq08jKqvvB3TX3dxmznPzHQohGRj46G5M2f653mBdoFYLmBlZekPaPadA/
VUWs4VrA6/M9E6PCc4MLhpp0md+pw9e3YV823REgDe9vkI+K8D8BlfoM6E0O0uPcpF48oRo7a15eVF
HoJo3qZ9PkvznJc36rQbvY3nkUiw5QDa1LYDjZKqt0uOHDlyYm5u7hec2P3WBOuaF3hqXYsVAKubmZ
l5gX01HjVfE7zikK3Dhw8vjkKCxspcTHg5eUV9lELq9fpJiKtXLRCpCp7CMOLCXI/5fLZT1AR/x61r
e339xz/K1h3k1GNEFqtTADIL83oD+zx9832cvN5EmXMVmb/7KH9Lm4JvtZIvNB45YAzg201I0AIPj+
0V3jIW9wgvvXb8+HH6es5MRaq0AgmpgtlT83fpz+hz69ixtZ9xXI4xBvAdvQWrEwnGTnUkFO7pDHK0
z9+Ahh7QYscB/ujRo+c5Hi0A4xnbg/CeRlUZ4cXMvuOKIPbKJBgDL0IxwiJxYTxNeAMk8xOOj1vBSx
2fzzQv8AQ+ZvCVc4JVwZOxeeiwfR5s/0s8Jw18fhd4mvwYwVvkCyswXOCB7GVolPAIYnW19HUVwYfh
re3z0wq+ak6wjuZD8Haqg4QZn49k9pPQPCzJ1iQLGEaCI4EviPBiQU6O7UOf17Y3BsLLHfjKSHAqwP
sik+XlpSdhSaOw/TDwURLcd/A0e4Hvdrs8MBE8t1nP6ijmyMJl7TxhhKetLgdeFkU3kAuEJDgV4N1H
07feMpZ+EOS67VtsbNu9HQlvS8HnSNAl0RR8eKqzMepGePJ5JzwRFCNGS6mdPHmSmR4dpRls0RpIut
83AT9Ighinz9RNtzrP3tpiPZmh83xlwgvBh2aq5/X1dR5e/kZL8NBY4fffT506dYggcJVqPgBPAVsk
aBIf+CYnZmrRfd7B8wjc8ZPgF64V+5bHTZd9/aywE9tL81jUgvu8Isac3+I3S3exDQ5er2Hh76P8AO
Ur7IuSVxPwJoBk1JcW0hIW8dgI4BP3eTvmSlMam8KlkA1q8I9SZC7AnODUl2MNjse/Nd4iTKqIZAY1
/xvOH7600ERIYL6Mn2xPr6J5mr36gu3JJQ9ybNWpDABUTsBE+mbjcryMBGGa77lPKU1EAHb3weQSmL
vAu2TN/9H+EsdCf0tfBWavZMYtmb37fJjDQ7902wkvgXbM7APwOQA+70h1soD/OVBPHubAq+5b5PB+
hXbRM75L25KfaGcvQeAKFAJJsBB8EOQoe7vlhIfkZ/w9wJjAZyT4XaCpUPMkLVsUtPolnlP3t05MK0
6AaJasevbWxqJFIJPzpZIZ6BscaXdFeApoPqVQXUOtMnOuKxCMK/CtBAv8KxZtZhvxW9bbIQesewPt
7ONJLUhlIBAJCcS69CgSmC+iz1W1Y0kBoK4ovLWkCuZ7ne3C5GddoJo3WF/OZeQCl2kBDh4az7Yr1a
HUq+f0un+ckKDzLh91ySJZ+hDfCOcu/lYBPOe8R6tB5z/7ANFdYRioqkLKSJCT+IfHCizM7CPWgNjA
FnYNkzAyM2nGJvSXFm3XXjufwNxl9hSwYgQTAIbuwQI+5BwuOItVyjQaW0tRHca2bdUGx4fHz3Nigs
Q97NChuPuaLAF9SgMQMj7B4I3NE5yDGi6YQ+Htq+wj0CoJqAhU1XYULIa3QEh7a8IPilzLWODO9hfU
UVNmCfj9Op7n/f18lBi50JrgMwGj74KT7mRJUKlhTghAvJ7CViaT1NZEgaiO2rNvcmCmn6P9UGKsCV
47wHYQ20dD46paLmsnFwiPw+YOFAK17pqPEqPv8xRMlBgbgv9H8Mam1LVGcYWMBGkBAwOZEPz7uqbE
qAivis9L83sGXnhlASSCwReaBqAhMRqxVCS8/QS/Q4LOiLmTlA47VYmxz+zpFoSZAvzvUZax/TSAj+
YEs62nJjHaAQjE+C+A54fN5BCLIgcIlGS6b+BDYpQLhCQYgtd+W5kYAdQAl+zzUwG+iARzruASq0OM
3Dr9FJnbOqdG81VI0ACH5iJ38P+qZlskgA6LGLk9hnFDCP5msM9PdKsT0AEchs15rx8Jxkgw1qkmMU
pI0wy+lATFAyE31IkYpw58qNiqJBiCl0CqEqNi+6kw+xC8n1jzH0vHXKGgLkaMlv5yElSOEeCPFebt
C+bIEfIE2tlxOIwEWyQObRE+4dA6xfsiRt/+nPyMBHGw2QV+6HhV5x2lnTQvbIhJLOlASUgQJhU0qF
SHL0AZUvK6DAF8gvIWyv+gfGdtbc2yRnhu62iLZ3uJgjKpOscE2yU/ABJADkcmdn30AAAAAElFTkSu
QmCC'''.replace('\n', '')

hoverlink_styles = r'''
<!-- Hoverlink styles -->
<style>
:root {
    --hoverlink-size: 0.9em;
}

.hoverlink {
    text-decoration: none;
}

.hoverlink::after {
    position: absolute;
    display: inline-block;
    content: "";
    width: var(--hoverlink-size);
    height: var(--hoverlink-size);
    background-size: var(--hoverlink-size) var(--hoverlink-size);
    background-image: url(data:image/png;base64,%s);
}
</style>
''' % hoverlink_image_base64

tbody_expand_script = r'''
<!-- Table body expansion and contraction script -->
<script>
window.addEventListener('DOMContentLoaded', function() {
    var showables = document.getElementsByClassName('showable');
    for (var i = 0; i < showables.length; i++) {
        var showable = showables[i];
        showable.addEventListener('click', function() {
            this.classList.toggle('show');
        });
    }

    showables = document.getElementsByClassName('showable2');
    for (var i = 0; i < showables.length; i++) {
        var showable = showables[i];
        showable.addEventListener('click', function(event) {
            this.classList.toggle('show2');
            event.stopPropagation();
        });
    }
});
</script>
'''

tbody_expand_styles = r'''
<!-- Table body expansion and contraction styles -->
<style>
.chevron {
    color: var(--link-color);
    cursor: pointer;
    margin-block-end: 0;
}

.chevron::before {
    /* Single Right-Pointing Angle Quotation Mark */
    content: "\00203A ";
}

.chevron .click::after {
    content: " Click to show/hide...";
}

.chevron p {
    display: inline;
}

.hide {
    display: none;
}

.show tr {
    display: table-row;
}

.show td div, .show ul, .show ol {
    display: block;
}

.show td span {
    display: inline;
}

.show2 *.hide {
    display: none;
}

</style>
'''

global_styles = r'''
<!-- Global styles (that affect the entire document) -->
<style>
/* light mode support */
@media (prefers-color-scheme: light) {
  :root {
    --background-color: white;
    --foreground-color: black;
    --diff-background-color: aliceblue;
    --link-color: blue;
    --parameter-color: white;
    --object-color: #ffff99;
    --command-color: #66cdaa;
    --event-color: #66cdaa;
    --argument-container-color: silver;
    --argument-object-color: pink;
    --argument-parameter-color: #ffe4e1;
    --mountable-object-color: #b3e0ff;
    --mountpoint-object-color: #4db8ff;
    --stripe-direction: 90deg;
    --stripe-stop-point-1: 1%;
    --stripe-stop-point-2: 2%;
    --stripe-color-deprecated: #eeeeee;
    --stripe-color-obsoleted: #dddddd;
    --stripe-color-deleted: #cccccc;
  }
}

/* dark mode support */
@media (prefers-color-scheme: dark) {
  :root {
    --background-color: black;
    --foreground-color: white;
    --diff-background-color: #0f0700;
    --link-color: lightblue;
    --parameter-color: black;
    --object-color: #bbbb44;
    --command-color: #56bd9a;
    --event-color: #56bd9a;
    --argument-container-color: #777777;
    --argument-object-color: #dfa0ab;
    --argument-parameter-color: #bfa4a1;
    --mountable-object-color: #b3e0ff;
    --mountpoint-object-color: #3da8ef;
    --stripe-color-deprecated: #555555;
    --stripe-color-obsoleted: #444444;
    --stripe-color-deleted: #333333;
  }
  .hoverlink {
    filter: invert(1);
  }
}

body, table {
    background-color: var(--background-color);
    color: var(--foreground-color);
    font-family: sans-serif;
    font-size: 9pt;
}

h1 {
    font-size: 14pt;
}

h2 {
    font-size: 12pt;
}

h3 {
    font-size: 10pt;
}

a:link, a:visited {
    color: var(--link-color);
}

sup {
    vertical-align: super;
}

table {
    text-align: left;
    vertical-align: top;
}

td, th {
    padding: 2px;
    text-align: left;
    vertical-align: top;
}

/* this is intended for hoverlinks */
td span {
    padding-right: 2px;
}

table.middle-width {
    width: 60%;
}

table.full-width {
    width: 100%;
}

thead th {
    background-color: #999999;
}

table.partial-border {
    border-left-style: hidden;
    border-right-style: hidden;
    border-collapse: collapse;
}

table.partial-border th,
table.partial-border td {
    border-style: solid;
    border-width: 1px;
    border-color: lightgray;
}

td > div,
td > div:not(.diffs) > p,
td > p {
    margin-block-start: 0;
    margin-block-end: 1em;
}

td > div:last-of-type,
td > div:last-of-type > p:last-of-type,
td > div:last-of-type > div:last-of-type > p:last-of-type,
td > p:last-of-type {
    margin-block-end: 0;
}

.centered {
    text-align: center;
}

.inserted {
    color: blue;
    margin-block-end: 0;
}

.removed {
    color: red;
    text-decoration: line-through;
    margin-block-end: 0;
}

/* XXX this is a bad name */
.diffs {
    background-color: var(--diff-background-color);
    opacity: 0.8;
}

.parameter {
    background-color: var(--parameter-color);
}

.deprecated-parameter {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--parameter-color),
        var(--parameter-color) var(--stripe-stop-point-1),
        var(--stripe-color-deprecated) var(--stripe-stop-point-1),
        var(--stripe-color-deprecated) var(--stripe-stop-point-2));
}

.obsoleted-parameter {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--parameter-color),
        var(--parameter-color) var(--stripe-stop-point-1),
        var(--stripe-color-obsoleted) var(--stripe-stop-point-1),
        var(--stripe-color-obsoleted) var(--stripe-stop-point-2));
}

.deleted-parameter {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--parameter-color),
        var(--parameter-color) var(--stripe-stop-point-1),
        var(--stripe-color-deleted) var(--stripe-stop-point-1),
        var(--stripe-color-deleted) var(--stripe-stop-point-2));
}

.object {
    background-color: var(--object-color);
}

.deprecated-object {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--object-color),
        var(--object-color) var(--stripe-stop-point-1),
        var(--stripe-color-deprecated) var(--stripe-stop-point-1),
        var(--stripe-color-deprecated) var(--stripe-stop-point-2));
}

.obsoleted-object {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--object-color),
        var(--object-color) var(--stripe-stop-point-1),
        var(--stripe-color-obsoleted) var(--stripe-stop-point-1),
        var(--stripe-color-obsoleted) var(--stripe-stop-point-2));
}

.deleted-object {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--object-color),
        var(--object-color) var(--stripe-stop-point-1),
        var(--stripe-color-deleted) var(--stripe-stop-point-1),
        var(--stripe-color-deleted) var(--stripe-stop-point-2));
}

.command {
    background-color: var(--command-color);
}

.deprecated-command {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--command-color),
        var(--command-color) var(--stripe-stop-point-1),
        var(--stripe-color-deprecated) var(--stripe-stop-point-1),
        var(--stripe-color-deprecated) var(--stripe-stop-point-2));
}

.obsoleted-command {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--command-color),
        var(--command-color) var(--stripe-stop-point-1),
        var(--stripe-color-obsoleted) var(--stripe-stop-point-1),
        var(--stripe-color-obsoleted) var(--stripe-stop-point-2));
}

.deleted-command {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--command-color),
        var(--command-color) var(--stripe-stop-point-1),
        var(--stripe-color-deleted) var(--stripe-stop-point-1),
        var(--stripe-color-deleted) var(--stripe-stop-point-2));
}

.event {
    background-color: var(--event-color);
}

.deprecated-event {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--event-color),
        var(--event-color) var(--stripe-stop-point-1),
        var(--stripe-color-deprecated) var(--stripe-stop-point-1),
        var(--stripe-color-deprecated) var(--stripe-stop-point-2));
}

.obsoleted-event {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--event-color),
        var(--event-color) var(--stripe-stop-point-1),
        var(--stripe-color-obsoleted) var(--stripe-stop-point-1),
        var(--stripe-color-obsoleted) var(--stripe-stop-point-2));
}

.deleted-event {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--event-color),
        var(--event-color) var(--stripe-stop-point-1),
        var(--stripe-color-deleted) var(--stripe-stop-point-1),
        var(--stripe-color-deleted) var(--stripe-stop-point-2));
}

.argument-container {
    background-color: var(--argument-container-color);
}

.deprecated-argument-container {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--argument-container-color),
        var(--argument-container-color) var(--stripe-stop-point-1),
        var(--stripe-color-deprecated) var(--stripe-stop-point-1),
        var(--stripe-color-deprecated) var(--stripe-stop-point-2));
}

.obsoleted-argument-container {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--argument-container-color),
        var(--argument-container-color) var(--stripe-stop-point-1),
        var(--stripe-color-obsoleted) var(--stripe-stop-point-1),
        var(--stripe-color-obsoleted) var(--stripe-stop-point-2));
}

.deleted-argument-container {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--argument-container-color),
        var(--argument-container-color) var(--stripe-stop-point-1),
        var(--stripe-color-deleted) var(--stripe-stop-point-1),
        var(--stripe-color-deleted) var(--stripe-stop-point-2));
}

.argument-parameter {
    background-color: var(--argument-parameter-color);
}

.deprecated-argument-parameter {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--argument-parameter-color),
        var(--argument-parameter-color) var(--stripe-stop-point-1),
        var(--stripe-color-deprecated) var(--stripe-stop-point-1),
        var(--stripe-color-deprecated) var(--stripe-stop-point-2));
}

.obsoleted-argument-parameter {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--argument-parameter-color),
        var(--argument-parameter-color) var(--stripe-stop-point-1),
        var(--stripe-color-obsoleted) var(--stripe-stop-point-1),
        var(--stripe-color-obsoleted) var(--stripe-stop-point-2));
}

.deleted-argument-parameter {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--argument-parameter-color),
        var(--argument-parameter-color) var(--stripe-stop-point-1),
        var(--stripe-color-deleted) var(--stripe-stop-point-1),
        var(--stripe-color-deleted) var(--stripe-stop-point-2));
}

.argument-object {
    background-color: var(--argument-object-color);
}

.deprecated-argument-object {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--argument-object-color),
        var(--argument-object-color) var(--stripe-stop-point-1),
        var(--stripe-color-deprecated) var(--stripe-stop-point-1),
        var(--stripe-color-deprecated) var(--stripe-stop-point-2));
}

.obsoleted-argument-object {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--argument-object-color),
        var(--argument-object-color) var(--stripe-stop-point-1),
        var(--stripe-color-obsoleted) var(--stripe-stop-point-1),
        var(--stripe-color-obsoleted) var(--stripe-stop-point-2));
}

.deleted-argument-object {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--argument-object-color),
        var(--argument-object-color) var(--stripe-stop-point-1),
        var(--stripe-color-deleted) var(--stripe-stop-point-1),
        var(--stripe-color-deleted) var(--stripe-stop-point-2));
}

.mountable-object {
    background-color: var(--mountable-object-color);
}

.deprecated-mountable-object {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--mountable-object-color),
        var(--mountable-object-color) var(--stripe-stop-point-1),
        var(--stripe-color-deprecated) var(--stripe-stop-point-1),
        var(--stripe-color-deprecated) var(--stripe-stop-point-2));
}

.obsoleted-mountable-object {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--mountable-object-color),
        var(--mountable-object-color) var(--stripe-stop-point-1),
        var(--stripe-color-obsoleted) var(--stripe-stop-point-1),
        var(--stripe-color-obsoleted) var(--stripe-stop-point-2));
}

.deleted-mountable-object {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--mountable-object-color),
        var(--mountable-object-color) var(--stripe-stop-point-1),
        var(--stripe-color-deleted) var(--stripe-stop-point-1),
        var(--stripe-color-deleted) var(--stripe-stop-point-2));
}

.mountpoint-object {
    background-color: var(--mountpoint-object-color);
}

.deprecated-mountpoint-object {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--mountpoint-object-color),
        var(--mountpoint-object-color) var(--stripe-stop-point-1),
        var(--stripe-color-deprecated) var(--stripe-stop-point-1),
        var(--stripe-color-deprecated) var(--stripe-stop-point-2));
}

.obsoleted-mountpoint-object {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--mountpoint-object-color),
        var(--mountpoint-object-color) var(--stripe-stop-point-1),
        var(--stripe-color-obsoleted) var(--stripe-stop-point-1),
        var(--stripe-color-obsoleted) var(--stripe-stop-point-2));
}

.deleted-mountpoint-object {
    background-image: repeating-linear-gradient(
        var(--stripe-direction),
        var(--mountpoint-object-color),
        var(--mountpoint-object-color) var(--stripe-stop-point-1),
        var(--stripe-color-deleted) var(--stripe-stop-point-1),
        var(--stripe-color-deleted) var(--stripe-stop-point-2));
}
</style>
'''

# XXX there's not much point defining these separately
local_styles = r'''
<!-- Local styles (that affect only data model tables) -->
<style>
/* center column 2 (Base Type) */
.data-type-table th:nth-child(2),
.data-type-table td:nth-child(2) {
    text-align: center;
}

/* center columns 3 (Write), 5 (Object Default), 6 (Version) */
.data-model-table th:nth-child(3),
.data-model-table td:nth-child(3),
.data-model-table th:nth-child(5),
.data-model-table td:nth-child(5),
.data-model-table th:nth-child(6),
.data-model-table td:nth-child(6)
{
    text-align: center;
}

.data-model-table th,
.data-model-table td {
    hyphenate-character: "";
}

/* word wrap/break column 1 (Name) */
.data-model-table td:first-child {
    word-wrap: break-word;
    word-break: break-all;
    min-width: 27ch;
}

/* word wrap/break column 2 (Base Type) */
.data-model-table td:nth-child(2) {
    word-wrap: break-word;
    word-break: break-all;
    min-width: 12ch;
}

/* word wrap/break column 3 (Write) */
.data-model-table td:nth-child(3) {
    min-width: 1ch;
}

/* word wrap/break column 5 (Object Default) */
.data-model-table td:nth-child(5) {
    word-wrap: break-word;
    word-break: break-all;
    min-width: 12ch;
}

/* word wrap/break column 6 (Version) */
.data-model-table td:nth-child(6) {
    min-width: 6ch;
}

/* center column 1 (Abbreviation) */
.profile-notation-table th:nth-child(1),
.profile-notation-table td:nth-child(1) {
    text-align: center;
}

/* center column 2 (Requirement) */
.profile-requirements-table th:nth-child(2),
.profile-requirements-table td:nth-child(2) {
    text-align: center;
}
</style>
'''

# conditional styles
link_styles = r'''
<style>
/* enabled if the --show option was specified (to avoid confusion between
   links and inserted text) */
a:link, a:visited, a:hover, a:active {
    color: inherit;
}
</style>
'''

# all styles and scripts (but not conditional ones)
styles_and_scripts = ''.join([
    toc_sidebar_styles,
    toc_expand_script, toc_expand_styles,
    toc_sort_script,
    autotitle_script,
    hoverlink_script, hoverlink_styles,
    tbody_expand_script, tbody_expand_styles,
    global_styles, local_styles
]).strip()
