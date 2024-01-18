"""Markdown report format plugin."""

# Copyright (c) 2023, Broadband Forum
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
import re
import textwrap
import time

from io import TextIOBase
from typing import Callable, cast, List, Optional, Tuple, Union

from .. import __tool_name__, __version__, version
from ..macro import Macro, MacroArg, MacroException, MacroRef
from ..node import AbbreviationsItem, Command, CommandRef, DataTypeAccessor, \
    Event, EventRef, GlossaryItem, Input, Model, Node, Object, ObjectRef, \
    Output, Parameter, ParameterRef, Profile, Reference, Root
from ..path import Path
from ..utility import Status, Utility

# XXX could try to generate sensible output when --thisonly is specified

# XXX could try to generate sensible output when multiple files are specified

# XXX running pandoc to generate HTML from markdown will be too slow,
#     so it'll be necessary to generate HTML directly; the existing
#     markdown-generation structure can easily be adapted for HTML (plus
#     will need to convert content 'markdown' to HTML)


# XXX how to add arguments? would like --markdown-fragment (or similar)


def _post_init_(logger, args):
    # check that only one file was supplied on the command-line
    # XXX disabled, because this doesn't work with diffs
    if False and len(args.file) > 1:
        logger.error("can't generate %s when multiple files are "
                     "specified on the command-line" % logger.name)
        return True

    # redefine the 'classes' macro (if it was originally declared as non-final,
    # this won't output a warning)
    Macro('classes', default='', macro_body=ModelTableElem.expand_classes)


# visit the node tree
def visit(root: Root, args, *, logger, omit_if_unused) -> None:
    Report(root, args, omit_if_unused=omit_if_unused, logger=logger)


class Report:
    """Represents the complete report."""

    def __init__(self, root: Root, args, *, omit_if_unused, logger):
        self.root = root
        self.args = args
        self.omit_if_unused = omit_if_unused
        self.logger = logger
        self.toc = ToC(logger)

        self.output()

    def output(self) -> None:
        self.toc.init()
        self.output_metadata()
        self.output_begin()
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
        self.output_end()
        self.output_toc()

    # XXX would like to set header-includes in a separate block at the bottom,
    #     but commonmark seems to support only a single metadata block and it
    #     has to be at the top
    def output_metadata(self) -> None:
        # this assumes that keylast is the full path
        _, title = os.path.split(self.root.xml_files[-1].keylast)

        # indent styles and scripts 14 spaces to be indented 2 spaces past
        # 'header-includes:' in the YAML (see below)
        # XXX need to work out what we need from bbf.css!
        s_and_s = styles_and_scripts
        if self.root.args.show:
            s_and_s += '\n\n' + link_styles.strip()
        s_and_s = textwrap.indent(s_and_s, prefix=15 * ' ')

        # this is the first thing in the output file, so no initial newline
        # XXX if using the default pandoc HTML template, it's important NOT
        #     to define 'title' (it mucks up the flex layout)
        self.print('''\
            ---
            comment: |
              This is commonmark_x (extended commonmark). Here's an example
              pandoc command:
                LUA_PATH="install/pandoc/?.lua;;" pandoc-3.0
                    --standalone
                    --from commonmark_x
                    --data-dir install/pandoc
                    --resource-path install/pandoc
                    --lua-filter list-table.lua
                    --to html-derived-writer.lua
                    tr-135-1-4-2-cwmp.md
                    --output tr-135-1-4-2-cwmp.html
            title: ''
            pagetitle: %s
            lang: en-us
            document-css: false
            header-includes:
             - |
%s
            ---''' % (title, s_and_s), noescape=True)

    def output_begin(self) -> None:
        self.print('\n:::::: {#main}')

    def output_banner(self) -> None:
        # use the last file on the command line (usually there will be only
        # one, but if generating diffs there will be two)
        xml_file = self.root.xml_files[-1]

        # use the last model (usually there will be only one, but if
        # generating diffs of two models in the same file there will be two)
        dm_document = xml_file.dm_document
        model = dm_document.models[-1]

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
        if any(str(t) == 'diff' for t in (self.args.transform or [])):
            title += ' (changes)'

        # BBF and logo information
        bbf_url = 'https://www.broadband-forum.org'
        logo_url = '%s/images/logo-broadband-forum.gif' % bbf_url

        # relative path (only works with web server) and file name
        # XXX does the relative path need to be customizable?
        rel_path = './'
        file = dm_document.file_safe

        # style information
        classes = ['list-table', 'full-width']
        widths = [3, 22, 50, 25]
        header_rows = 0

        # output the table
        # XXX the Table class can't handle colspan and rowspan
        self.print('''
            {%s widths=%s header-rows=%d}
            - - []{colspan=2}[![Broadband Forum](%s){width=100%%}](%s)

              - []{.centered rowspan=2}

                # %s {.unnumbered .unlisted}

                # [%s](%s#%s) {.unnumbered .unlisted}

              - []{rowspan=2}

            - -
              - ### DATA MODEL DEFINITION {.unnumbered .unlisted}''' % (
            ' '.join('.%s' % cls for cls in classes),
            ','.join(str(wid) for wid in widths), header_rows, logo_url,
            bbf_url, title, file, rel_path, file))

    def output_summary(self) -> None:
        # disable this because any information in the top-level description
        # should now be in PROJECT.yaml
        if False and (summary := self.root.xml_files[
                -1].dm_document.description.content.markdown):
            self.output_header(1, 'Summary')
            self.print()
            self.print(summary.strip())

    def output_license(self) -> None:
        if comment := self.root.xml_files[-1].comments[0].text:
            assert comment.startswith('<!--') and comment.endswith('-->')
            lines = textwrap.dedent(comment[4:-3]).splitlines()
            # noinspection PyShadowingBuiltins
            license = []
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
                self.print(license, noescape=True)

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
                          logger=self.logger,
                          classes=['full-width', 'partial-border',
                                   'data-type-table'])

            # list lower-case (primitive) data types first; do this by
            # returning a (starts-with-upper-case, name) tuple
            def key(item):
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
                description = \
                    data_type.description_inherited.content.markdown or ''
                table.add_row(name, base, description)
            self.print(table.markdown)

    def output_glossary(self) -> None:
        items = GlossaryItem.findall(predicate=lambda i: self.include(i))
        if items:
            self.output_header(1, 'Glossary')
            table = Table('ID', 'Description', logger=self.logger,
                          classes=['middle-width', 'partial-border'])
            for item in cast(List[GlossaryItem],
                             sorted(items, key=lambda i: i.id.lower())):
                # XXX need to define an anchor
                table.add_row(item.id, item.description.content.markdown or '')
            self.print(table.markdown)

    def output_abbreviations(self) -> None:
        items = AbbreviationsItem.findall(predicate=lambda i: self.include(i))
        if items:
            self.output_header(1, 'Abbreviations')
            table = Table('ID', 'Description', logger=self.logger,
                          classes=['middle-width', 'partial-border'])
            for item in cast(List[AbbreviationsItem],
                             sorted(items, key=lambda i: i.id.lower())):
                # XXX need to define an anchor
                table.add_row(item.id, item.description.content.markdown or '')
            self.print(table.markdown)

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
        def get_hyperlinks(ref: Reference) -> List[str]:
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

        # if omit_if_unused is False but the (single) file name contains
        # 'types', only include 'used' references
        predicate = lambda i: self.include(i)
        if not self.omit_if_unused and len(self.args.file) == 1 \
                and 'types' in self.args.file[0]:
            predicate = lambda i: i.is_used
        items = Reference.findall(predicate=predicate)
        if items:
            self.output_header(1, 'References')
            table = Table(logger=self.logger)
            for item in cast(List[Reference],
                             sorted(items, key=lambda i: i.id.lower())):
                name = '[[%s]{#%s}]' % (item.id, item.anchor)
                if hyperlinks := get_hyperlinks(item):
                    name = '[%s](%s)' % (name, hyperlinks[0])
                    if len(hyperlinks) > 1:
                        secondary = ', '.join(h for h in hyperlinks[1:])
                        self.logger.warning('%s: ignored secondary '
                                            'hyperlinks %s' % (
                                                item.nicepath, secondary))
                text = item.name.text or ''
                if item.title:
                    text += ', *%s*' % item.title.text
                if item.organization:
                    text += ', %s' % item.organization.text
                if item.date:
                    text += ', %s' % item.date.text
                text += '.'
                table.add_row(name, text)
            self.print(table.markdown)

    # XXX the legend is hardly worth it for CWMP; should omit it?
    def output_legend(self) -> None:
        models = self.root.xml_files[-1].dm_document.models
        if models:
            usp = any(model.usp for model in
                      self.root.xml_files[-1].dm_document.models)
            self.output_header(1, 'Legend')
            table = Table(logger=self.logger,
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
            self.print(table.markdown)

    def output_models(self) -> None:
        for xml_file in self.root.xml_files:
            for model in xml_file.dm_document.models:
                if not model.is_hidden:
                    self.output_model(model)

    def output_model(self, model: Model) -> None:
        ModelTableElem.reset()

        # collect the description
        comps = [textwrap.dedent('''
            For a given implementation of this data model, the Agent MUST
            indicate support for the highest version number of any object
            or parameter that it supports. For example, even if the Agent
            supports only a single parameter that was introduced in version
            1.4, then it will indicate support for version 1.4. The version
            number associated with each object and parameter is shown in
            the **Version** column.''')]
        if model.description.content.markdown:
            comps.append(model.description.content.markdown)

        self.output_header(1, '%s Data Model' % model.name, show=3)
        self.print('\n\n'.join(comps))

        # output the main table (which doesn't contain profiles)
        table = Table('Name', 'Type', 'Write', 'Description', 'Object Default',
                      'Version', logger=self.logger,
                      classes=['full-width', 'partial-border',
                               'data-model-table'])
        for node in model.elems:
            if not node.is_hidden and node not in model.profiles:
                self.output_node(node, table)
        self.print(table.markdown)

        # output the 'Inform and Notification Requirements' tables
        self.output_notification_tables(model)

        # output the profile tables
        self.output_profiles(model.profiles)

    def output_notification_tables(self, model: Model) -> None:
        # determine whether this is a USP model
        usp = model.usp

        # collect all the parameters
        parameters = model.parameters + [param for obj in model.objects for
                                         param in obj.parameters]

        # output the header (different for USP)
        self.output_header(2, 'Notification Requirements' if usp else
                           'Inform and Notification Requirements')

        # output the first three tables (not for USP)
        if not usp:
            self.output_notification_table(
                    parameters, 'Forced Inform Parameters',
                    lambda p: p.forcedInform)
            self.output_notification_table(
                    parameters, 'Forced Active Notification Parameters',
                    lambda p: p.activeNotify == 'forceEnabled')
            self.output_notification_table(
                    parameters, 'Default Active Notification Parameters',
                    lambda p: p.activeNotify == 'forceDefaultEnabled')

        # output the last table (it lists objects and parameters separately
        title = 'Parameters for which %s Notification MAY be Denied' % (
            'Value Change' if usp else 'Active')
        self.output_notification_table(parameters, title,
                                       lambda p: p.activeNotify == 'canDeny',
                                       separate_objects=True)

    def output_notification_table(self, parameters: List[Parameter],
                                  title: str, predicate: Callable, *,
                                  separate_objects: bool = False) -> None:
        def node_class(node) -> str:
            status = node.status_inherited
            return '%s%s' % ('%s-' % status.name if status.name != 'current'
                             else '', node.typename)

        self.output_header(3, title)
        table = Table('Parameter', logger=self.logger,
                      classes=['middle-width', 'partial-border'])
        current_object = None
        for parameter in [param for param in parameters if predicate(param)]:
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

        self.print(table.markdown)

    def output_profiles(self, profiles: List[Profile]) -> None:
        visible_profiles = [prof for prof in profiles if not prof.is_hidden]

        if visible_profiles:
            self.output_header(2, 'Profile Definitions')
            self.output_header(3, 'Notation', sort=3)
            self.print()
            self.print('The following abbreviations are used to specify '
                       'profile requirements:')
            table = Table('Abbreviation', 'Description', logger=self.logger,
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
            self.print(table.markdown)

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
                           stat=profile.status.name)

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
                      classes=['middle-width', 'partial-border',
                               'profile-requirements-table'], widths=[90, 10])
        footnotes = []
        # the entire profile (including internal dependencies) is in the elems
        # list, so don't recurse (recursion would add duplicates)
        for node in elems:
            if not node.is_hidden:
                self.output_node(
                        node, table, norecurse=True, footnotes=footnotes)
        self.print(table.markdown)

        if footnotes:
            self.print()
            for num, note in enumerate(footnotes):
                term = '\\' if num < len(footnotes) - 1 else ''
                self.print('^%d^ %s%s' % (num + 1, note, term))

    def output_footer(self) -> None:
        # helper to format the args string
        interesting = {'all', 'include', 'nocurdir', 'file',  'filter',
                       'format', 'output', 'plugindir', 'thisonly',
                       'transform'}
        positional = {'file'}  # only supported for list-valued arguments

        def args_string():
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

        # use UTC dates and times
        now = time.gmtime()
        now_date = time.strftime('%Y-%m-%d', now)
        now_time = time.strftime('%H:%M:%S', now)

        # version numbers ending in '+' are later interim versions
        extra = ' (INTERIM VERSION)' if __version__.endswith('+') else ''

        self.print('''
            ---

            Generated by %s on %s at %s UTC%s.\\
            %s %s''' % (version(as_markdown=True), now_date, now_time, extra,
                        __tool_name__, args_string()))

    def output_header(self, level: int, text: str, anchor: str = '', *,
                      stat: str = 'current', notoc: bool = False,
                      **kwargs) -> None:
        stat_ = ' [%s]' % stat.upper() if stat != 'current' else ''
        target = ' {#%s}' % anchor if anchor else ''
        self.print('\n%s %s%s%s' % (level * '#', text, stat_, target))
        if not notoc:
            self.toc.entry(level, text, anchor, stat=stat, **kwargs)

    # utilities

    def output_node(self, node: Node, table: 'Table', *,
                    norecurse: bool = False,
                    footnotes: Optional[List[Tuple[str, str]]] = None) -> None:
        elem = Elem.create(node, toc=self.toc, logger=self.logger,
                           footnotes=footnotes)
        row = elem.row
        # Description elems (for example) have no rows
        if row is not None:
            if elem.need_separator:
                table.add_separator(classes=elem.section_classes, elem=elem)
            table.add_row(*row, classes=elem.row_classes, elem=elem)
            if not norecurse:
                for child in node.elems:
                    if not child.is_hidden:
                        self.output_node(child, table, footnotes=footnotes)

    def output_end(self) -> None:
        self.print('\n::::::')

    def output_toc(self) -> None:
        self.print('\n::: {#TOC}')
        self.output_header(1, 'Table of Contents', notoc=True)
        self.toc.output(print_func=self.print)
        self.print(':::')

    def include(self, node: Node) -> bool:
        return not self.omit_if_unused or node.is_used

    def print(self, text: Union[str, List[str]] = '', *, width: int = 0,
              nodedent: bool = False, noescape: bool = False) -> None:
        if isinstance(text, list):
            text = '\n'.join(text)

        if not nodedent:
            text = textwrap.dedent(text)

        # XXX this might be insufficient
        if not noescape:
            text = re.sub(r'([<>])', r'\\\1', text)

        # XXX experimental; needs more work; need to be careful with lists...
        if width > 0:
            lines = textwrap.wrap(text, width=width)
            for line in lines:
                self.args.output.write(line + '\n')
        else:
            self.args.output.write(text + '\n')


class ToC:
    """Table of contents."""

    def __init__(self, logger):
        self.logger = logger
        self.entries = None
        self.init()

    def init(self) -> None:
        self.entries = []

    def entry(self, level: int, text: str, target: str = '', *,
              split: bool = False, stat: str = 'current',
              show: int = 1, sort: int = 0) -> None:
        # split: text is object, command or event path name
        command_or_event = False
        if split and re.search(r'(\.|\(\)|!)$', text):
            # if it's a command or event, temporarily add a final dot
            # XXX perhaps should get Path() to worry about this? the problem
            #     is the chameleon-like behavior of commands and events
            if not text.endswith('.'):
                text += '.'
                command_or_event = True
            # e.g., 'Device.Capabilities.' -> ['Device', 'Capabilities', '']
            comps = Path(text).comps
            # e.g., 1
            prelen = len(comps) - 2
            # e.g., 'Capabilities.'
            final = '.'.join(comps[prelen:])
            # if it's a command or event, remove the temporary final dot
            if command_or_event:
                final = final[:-1]
            # this assumes that parent ToC entries are always created before
            # child entries (node.elems should guarantee this)
            self.entry(level + prelen, final, target,
                       stat=stat, show=show, sort=sort)

        # create entry
        else:
            self.entries.append((level, text, target, stat, show, sort))

    # XXX it would be more consistent with Table to return markdown
    # noinspection PyShadowingBuiltins
    def output(self, *, print_func) -> None:
        def indent(lv: int) -> str:
            return 2 * (lv - 1) * ' '

        plevel = 0
        ptarget = None
        # levels start at 1
        for i, (level, text, target, stat, show, sort) in enumerate(
                self.entries):
            # peek at the next entry to get its level
            if i < len(self.entries) - 1:
                next_level, *_ = self.entries[i+1]
            else:
                next_level = level

            # if level has increased, need to open div(s)
            # XXX don't put colons after the attributes, because pandoc's
            #     commonmark parser doesn't yet support them
            if level > plevel:
                # it should only have increased by 1 but don't assume this
                for lev in range(plevel + 1, level + 1):
                    classes = ['collapsed'] + (
                        ['expanded'] if lev <= show else []) + (
                        ['ordered'] if lev == sort else [])
                    attrs = '{%s}' % ' '.join('.%s' % cls for cls in classes)
                    print_func('\n%s%s' % (indent(lev), attrs), nodedent=True)
                    # if this isn't the last one, need to create a list item;
                    # otherwise the markdown will be invalid
                    # XXX currently hack this from the target, assuming that
                    #     it's '#PREFIX.MODEL.COMP1.COMP2...' (ending with '.')
                    # XXX the show and sort values are hard-coded
                    if lev < level:
                        comps = target.split('.', 4)
                        print_func('%s* [%s.]{.collapsible .expandable}' % (
                            indent(lev), '.'.join(comps[2:-2])), nodedent=True)

            # if level has decreased, need to close div(s)
            elif level < plevel:
                print_func()

            # if the previous entry was at the same level but has a different
            # initial path component, need to close the current list and open
            # a new one
            # XXX this should only happen with auto-models; it too is a hack
            # XXX the show and sort values are hard-coded
            if level == plevel and ptarget:
                pcomps = ptarget.split('.')
                comps = target.split('.')
                if len(pcomps) > 4 and len(comps) > 4 and \
                        comps[0] == 'D' and pcomps[2] != comps[2]:
                    print_func()
                    print_func('%s* [%s.]{.collapsible .expandable}' % (
                        indent(level - 1), '.'.join(comps[2:-2])),
                               nodedent=True)
                    print_func()
                    print_func('%s{.collapsed .expanded .ordered}' %
                               indent(level), nodedent=True)

            # convert the text to a link
            text = '[%s]' % text
            if target:
                text += '(#%s)' % target

            # append status (if it's not 'current')
            if stat != 'current':
                text += ' [%s]' % stat.upper()

            classes = [] + (
                ['collapsible'] if level < show else []) + (
                ['expandable'] if next_level > level else [])
            if not classes:
                print_func('%s* %s' % (indent(level), text), nodedent=True)
                pass
            else:
                attrs = '{%s}' % ' '.join('.%s' % cls for cls in classes)
                print_func('%s* [%s]%s' % (indent(level), text, attrs),
                           nodedent=True)

            plevel = level
            ptarget = target

        print_func()


class Table:
    def __init__(self, *labels, logger,
                 widths: Optional[List[int]] = None,
                 classes: Optional[List[str]] = None):
        self.labels = (labels, None, None)
        self.logger = logger
        self.widths = widths
        self.classes = classes
        self.rows = []

    # a separator is indicated by a row of None
    # XXX passing elem is temporary (just for reporting)
    def add_separator(self, *, classes: Optional[List[str]] = None,
                      elem=None) -> None:
        self.rows.append((None, classes, elem))

    def add_row(self, *row, classes: Optional[List[str]] = None,
                elem=None) -> None:
        self.rows.append((row, classes, elem))

    # the markdown always starts with an empty line, but is not terminated with
    # an empty line (the caller is responsible for that)
    @property
    def markdown(self) -> List[str]:
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
                classes = cast(List[str], classes)
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

    def __str__(self):
        return '%s (%d)' % (self.labels, len(self.rows))

    def __repr__(self):
        return '%s(%s)' % (type(self).__name__, self)


# XXX classes need to know what to put into table rows; messy...
class Elem:
    """Node wrapper (referred to as "element" to avoid confusion)."""

    # various constants
    # XXX could use things like '`&lArr;`{=html}' but this can confuse pandoc
    #     in some contexts, so use the plain HTML entity versions
    LARR = '&lArr;'
    RARR = '&rArr;'
    INFIN = '&infin;'

    # this is populated by Elem.init()
    _ctors = {}

    # should call Elem.init() after all subclasses have been defined
    # (if this isn't done, only Elem instances will be created)
    # XXX could do this lazily on first invocation
    @classmethod
    def init(cls):
        cls._ctors[cls.__name__] = cls
        for subclass in cls.__subclasses__():
            subclass.init()

    @classmethod
    def create(cls, node: Node, **kwargs):
        name = '%sElem' % type(node).__name__
        ctor = cls._ctors.get(name, Elem)
        return ctor(node, **kwargs)

    # XXX should allow toc and logger to be None
    def __init__(self, node: Node, *, toc, logger, footnotes=None, **kwargs):
        self.node = node
        self.toc = toc
        self.logger = logger
        self.footnotes = footnotes
        assert not kwargs, 'unexpected keyword arguments %s' % kwargs

    # this formats the node and then escapes some problematic characters, e.g.
    # '[' and ']' in '[0:1](:64)', which would otherwise be interpreted as a
    # link
    @staticmethod
    def format(node: Node, *, noescape: bool = False, **kwargs) -> str:
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
    def section_classes(self) -> List[str]:
        return []

    # subclasses can override this
    @property
    def row_classes(self) -> List[str]:
        return []

    # subclasses can override this
    @property
    def row(self) -> Optional[Tuple[str, ...]]:
        return None

    # XXX some of these helpers aren't type-safe; they should be further
    #     down the class hierarchy

    @property
    def status_prefix(self) -> str:
        status = self.node.object_status_inherited
        if status.name != 'current':
            return status.name + '-'
        else:
            return ''

    @property
    def arrow_prefix(self) -> str:
        if self.node.instance_in_path((Input, Event)):
            return self.RARR + ' '
        elif self.node.instance_in_path(Output):
            return self.LARR + ' '
        else:
            return ''

    @property
    def argument_prefix(self) -> str:
        if self.node.instance_in_path((Command, CommandRef, Event, EventRef)):
            return 'argument-'
        else:
            return ''

    access_map = {
        'readOnly': 'R',
        'readWrite': 'W',
        'writeOnceReadOnly': 'WO'
    }

    @property
    def access_string(self) -> str:
        node = self.node

        # commands and events don't have access attributes
        if node.instance_in_path(Input):
            return 'W'
        elif node.instance_in_path((Output, Event)):
            return 'R'

        # noinspection PyUnresolvedReferences
        access = node.access
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
        requirement = node.requirement
        if requirement not in self.requirement_map:
            self.logger.warning('%s: unsupported requirement %s' % (
                node.nicepath, requirement))
        return self.requirement_map.get(requirement, '?%s?' % requirement)

    @property
    def footref(self) -> str:
        return ''

    def __str__(self):
        return '%s (%s)' % (self.node, self.node.status)

    def __repr__(self):
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

    def __init__(self, node: Node, **kwargs):
        super().__init__(node, **kwargs)

        # expandable / contractable section properties
        self.need_showable_class = False
        self.need_showable2_class = False
        # XXX need to double-check use of these two
        self.need_hide_class = False
        self.hide_class = ''
        self._set_section_properties()

    def _toc_entry(self) -> None:
        node = self.node
        self.toc.entry(2, node.objpath, node.anchor, split=True,
                       stat=node.status.name, show=3, sort=3)

    # XXX it would be clearer not to use this, but instead always use node
    #     status directly as needed
    # XXX shouldn't use 'current'; should use Status.default
    def _set_section_properties(self) -> None:
        node = self.node

        # only non-current nodes can start new sections
        if node.object_status_inherited.name == 'current':
            pass

        # ensure that this isn't the root object (if it is, something else
        # has gone wrong
        elif not (object_parent := node.object_parent):
            pass

        # if the parent node is current, this is the root of a showable tree
        elif object_parent.object_status_inherited.name == 'current':
            # some old data models might not use {{deprecated}} etc. macros
            # noinspection PyUnresolvedReferences
            has_status_macro = any(
                    status in node.description.content.macro_refs for status in
                    Status.names)
            self.need_showable_class = has_status_macro

        # if this node is not current (in its own right), showable2 is set so
        # its description can be expanded and collapsed
        elif node.status.name != 'current':
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
    def section_classes(self) -> List[str]:
        classes = []
        if self.need_showable_class:
            classes.append('showable')
        return classes + super().section_classes

    @property
    def row_classes(self) -> List[str]:
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
                            node.parent.status.name for item in content.items)
                classes.append(elem.hide_class if not found else 'chevron')

            # if called from {{span}} and its caller is {{<status>}} (as above)
            elif len(stack) > 2 and stack[-3].name == node.parent.status.name:
                # add the hide class unless the content is empty, in which
                # case add 'click'
                classes.append(elem.hide_class if content.items else 'click')

        return ' '.join(classes)


class ObjectElem(ModelTableElem):
    @property
    def row_classes(self) -> List[str]:
        return [self.status_prefix + self.argument_prefix + 'object'] + \
               super().row_classes

    @property
    def row(self) -> Optional[Tuple[str, ...]]:
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
                node.description.content.markdown or '', r'\-',
                node.version_inherited.name)

    @property
    def type_string(self) -> str:
        text = super().type_string
        text = '[%s]{title=%s}' % (text.replace('unbounded', ''),
                                   text.replace('unbounded', self.INFIN))
        return text


class ParameterElem(ModelTableElem):
    @property
    def row_classes(self) -> List[str]:
        return [self.status_prefix + self.argument_prefix + 'parameter'] + \
               super().row_classes

    @property
    def row(self) -> Tuple[str, ...]:
        node = cast(Parameter, self.node)
        name = '[%s]{#%s}' % (node.name, node.anchor)
        return (self.arrow_prefix + name,
                self.type_string,
                self.access_string,
                node.description.content.markdown or '',
                (Utility.nice_string(node.syntax.default)
                 if node.syntax.default.type == 'object' else r'\-'),
                node.version_inherited.name)

    @property
    def type_string(self) -> str:
        node = cast(Parameter, self.node)
        text = super().type_string
        if node.syntax.dataType:
            text = '[%s]{title=%s}' % (
                Elem.format(node, typ=True, prim=True),
                Elem.format(node, typ=True, noescape=True))
        return text


class CommandElem(ModelTableElem):
    @property
    def row_classes(self) -> List[str]:
        return [self.status_prefix + 'command'] + super().row_classes

    @property
    def row(self) -> Tuple[str, ...]:
        node = cast(Command, self.node)

        self._toc_entry()

        name = '[%s]{#%s}' % (node.name, node.anchor)
        return (name, 'command', r'\-',
                node.description.content.markdown or '', r'\-',
                node.version_inherited.name)


class InputElem(ModelTableElem):
    @property
    def row_classes(self) -> List[str]:
        return [self.status_prefix + 'argument-container'] + \
               super().row_classes

    @property
    def row(self) -> Tuple[str, ...]:
        return (self.arrow_prefix + 'Input.', 'arguments', r'\-',
                'Input arguments.', r'\-', '')


class OutputElem(ModelTableElem):
    @property
    def row_classes(self) -> List[str]:
        return [self.status_prefix + 'argument-container'] + \
               super().row_classes

    @property
    def row(self) -> Tuple[str, ...]:
        return (self.arrow_prefix + 'Output.', 'arguments', r'\-',
                'Output arguments.', r'\-', '')


class EventElem(ModelTableElem):
    @property
    def row_classes(self) -> List[str]:
        return [self.status_prefix + 'event'] + super().row_classes

    @property
    def row(self) -> Tuple[str, ...]:
        node = cast(Event, self.node)

        self._toc_entry()

        name = '[%s]{#%s}' % (node.name, node.anchor)
        return (name, 'event', r'\-',
                node.description.content.markdown or '', r'\-',
                node.version_inherited.name)


class ProfileTableElem(Elem):
    @property
    def footref(self) -> str:
        node = self.node
        if self.footnotes is None or node.status.name == 'current':
            return ''
        else:
            self.footnotes.append('This %s is %s.' % (
                node.elemname, node.status.name.upper()))
            return '^%s^' % len(self.footnotes)


class ObjectRefElem(ProfileTableElem):
    @property
    def row_classes(self) -> List[str]:
        return [self.status_prefix + self.argument_prefix + 'object'] + \
               super().row_classes

    @property
    def row(self) -> Tuple[str, ...]:
        node = cast(ObjectRef, self.node)
        ref = '[%s](#%s)' % (node.ref, node.anchor)
        return ref, self.requirement_string + self.footref


class ParameterRefElem(ProfileTableElem):
    @property
    def row_classes(self) -> List[str]:
        return [self.status_prefix + self.argument_prefix + 'parameter'] + \
               super().row_classes

    @property
    def row(self) -> Tuple[str, ...]:
        node = cast(ParameterRef, self.node)
        ref = '[%s](#%s)' % (node.ref, node.anchor)
        return ref, self.requirement_string + self.footref


class CommandRefElem(ProfileTableElem):
    @property
    def row_classes(self) -> List[str]:
        return [self.status_prefix + 'command'] + super().row_classes

    @property
    def row(self) -> Tuple[str, ...]:
        node = cast(CommandRef, self.node)
        ref = '[%s](#%s)' % (node.ref, node.anchor)
        return ref, r'\-' + self.footref


class InputRefElem(ProfileTableElem):
    @property
    def row_classes(self) -> List[str]:
        return [self.status_prefix + 'argument-container'] + \
               super().row_classes

    @property
    def row(self) -> Tuple[str, ...]:
        return 'Input.', r'\-' + self.footref


class OutputRefElem(ProfileTableElem):
    @property
    def row_classes(self) -> List[str]:
        return [self.status_prefix + 'argument-container'] + \
               super().row_classes

    @property
    def row(self) -> Tuple[str, ...]:
        return 'Output.', r'\-' + self.footref


class EventRefElem(ProfileTableElem):
    @property
    def row_classes(self) -> List[str]:
        return [self.status_prefix + 'event'] + super().row_classes

    @property
    def row(self) -> Tuple[str, ...]:
        node = cast(EventRef, self.node)
        ref = '[%s](#%s)' % (node.ref, node.anchor)
        return ref, r'\-' + self.footref


Elem.init()


# the rest of the file defines CSS styles and JavaScript
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
}

.chevron::before {
    /* Single Right-Pointing Angle Quotation Mark */
    content: "\00203A ";
}

.chevron .click::after {
    content: " Click to show/hide...";
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
}

body, table {
    background-color: var(--background-color);
    color: var(--foreground-color);
    font-family: helvetica, arial, sans-serif;
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
td > p {
    margin-block-start: 0;
    margin-block-end: 1em;
}

td > div:last-of-type,
td > p:last-of-type {
    margin-block-end: 0;
}

.centered {
    text-align: center;
}

.inserted {
    color: blue;
}

.removed {
    color: red;
    text-decoration: line-through;
}

/* XXX this is a bad name */
.diffs {
    background-color: aliceblue;
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
