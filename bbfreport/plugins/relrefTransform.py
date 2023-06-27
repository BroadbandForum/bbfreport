"""Relative reference (relref) transform plugin."""

# Copyright (c) 2021, Broadband Forum
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

import json
import logging
import re

from typing import Any

from ..node import Description, PathRef, Root
from ..path import follow_reference, relative_path
from ..transform import Transform
from ..utility import Utility

logger_name = __name__.split('.')[-1]
logger = logging.getLogger(logger_name)
logger.addFilter(
        lambda r: r.levelno > 20 or logger_name in Utility.logger_names)


# noinspection PyShadowingNames
class RelrefTransform(Transform):
    """Relative reference (relref) transform plugin.

    Replaces absolute references with relative references.
    """

    @classmethod
    def _add_arguments(cls, arg_parser):
        default_mappings_file = 'relref-mappings.json'
        arg_group = arg_parser.add_argument_group("relref transform "
                                                  "arguments")
        arg_group.add_argument("--relref-mappings-file",
                               default=default_mappings_file,
                               help="JSON mapping file; default: %r" %
                                    default_mappings_file)
        arg_group.add_argument("--relref-update-mappings", action='store_true',
                               help="Whether to update mappings in an "
                                    "existing file")
        arg_group.add_argument("--relref-apply-mappings", action='store_true',
                               help="Whether to apply mappings (if so, the "
                                    "file is read; if not, it's created or "
                                    "updated)")
        return arg_group

    # absolute reference pattern (there has to be at least one character
    # after the '.' to avoid matching plain '.', which isn't absolute)
    abs_pattern = re.compile(r'(InternetGateway)?(Device)?\..')

    # mappings
    mappings = {}

    def _visit_begin(self, root: Root, **kwargs) -> None:
        self._init_mappings(root)

    # this handles pathRefs
    def _visit_pathref(self, node: PathRef) -> Any:
        cls = type(self)
        refs = node.targetParents
        scp = node.targetParentScope
        new_refs = []
        for ref in refs:
            new_ref = ref
            if cls.abs_pattern.match(ref):
                if not node.args.relref_apply_mappings:
                    item = follow_reference(node, ref, scope=(scp or None))
                    if item:
                        self._add_mapping(node, ref, item)
                else:
                    new_ref = self._get_mapping(node, ref)
                    if new_ref is None:
                        new_ref = ref
            new_refs.append(new_ref)
        # without this new_refs check, None would become []
        if node.args.relref_apply_mappings and new_refs:
            node.targetParents = new_refs

    # this handles {{object}} etc. references
    def _visit_description(self, node: Description) -> Any:
        cls = type(self)

        # {{object}}, {{param}} etc. template pattern
        ref_pattern = re.compile(r'''
            (?P<prefix>{{)
            (?P<name>(object|param|command|event|enum|pattern))
            (?P<separator>\|)
            (?P<args>.*?)
            (?P<suffix>}})
        ''', re.VERBOSE)

        # process {{object|.TopLevel}}, {{object|Device.TopLevel}} etc.
        # references
        # XXX should extract the common match + args logic
        if not node.args.relref_apply_mappings:
            for match in ref_pattern.finditer(node.text):
                tmp = match.group(0)
                dct = match.groupdict()
                name = dct['name']
                args = dct['args'].split('|')
                ref_index = int(name in {'enum', 'pattern'})
                scp_index = ref_index + 1
                ref = args[ref_index] if len(args) > ref_index else None
                scp = args[scp_index] if len(args) > scp_index else None
                if ref and cls.abs_pattern.match(ref):
                    item = follow_reference(node, ref, scope=(scp or None))
                    if item:
                        self._add_mapping(node, ref, item, template=tmp)

        else:
            def sub(match):
                tmp = match.group(0)
                dct = match.groupdict()
                name = dct['name']
                args = dct['args'].split('|')
                ref_index = int(name in {'enum', 'pattern'})
                ref = args[ref_index] if len(args) > ref_index else None
                if ref and cls.abs_pattern.match(ref):
                    new_ref = self._get_mapping(node, ref, template=tmp)
                    if new_ref is not None:
                        return new_ref
                return tmp

            # XXX this needs to be updated; use .content?
            node.text = ref_pattern.sub(sub, node.text)

    def _visit_end(self, root: Root, **kwargs) -> None:
        self._save_mappings(root)

    def _init_mappings(self, node):
        cls = type(self)
        if not node.args.relref_update_mappings and not \
                node.args.relref_apply_mappings:
            cls.mappings = {}
        else:
            file = node.args.relref_mappings_file
            cls.mappings = json.load(open(file))
            logger.info('read mappings from %s' % file)

    # only _add_mapping() and _get_mapping() know the structure of the
    # mapping file
    def _add_mapping(self, node, ref, item, *, template=''):
        cls = type(self)
        logger.debug('%s %s -> %s %s' % (node.objpath, ref, item.objpath,
                                         template))
        cls.mappings.setdefault(node.objpath, [])
        cls.mappings[node.objpath].append([ref, item.objpath, template])

    # only _add_mapping() and _get_mapping() know the structure of the
    # mapping file
    def _get_mapping(self, node, ref, *, template=''):
        cls = type(self)
        node_mappings = cls.mappings.get(node.objpath, [])
        for objref, objpath, objtemplate in node_mappings:
            logger.debug('%s: ref %s template %s objref %s objpath %s '
                         'objtemplate %s' % (
                             node.objpath, ref, template, objref, objpath,
                             objtemplate))
            if not template:
                if objref == ref:
                    objpath = relative_path(objpath, node.objpath, strip=1)
                    # empty string means 'current object' but there's no syntax
                    # for this; invent '.' (OK in the schema, but needs a
                    # minor report tool fix)
                    if objpath == '':
                        objpath = '.'
                    logger.info('%s: %s -> %s' % (node.objpath, ref, objpath))
                    return objpath
            else:
                if objtemplate == template:
                    assert objref in objtemplate
                    objpath = relative_path(objpath, node.objpath, strip=2)
                    objtemplate = objtemplate.replace(objref, objpath)
                    # this could result in something like {{object|}}; this
                    # is valid but confusing (so fix it)
                    objtemplate = re.sub(r'\|}}$', r'}}', objtemplate)
                    logger.info('%s: %s -> %s' % (node.objpath, template,
                                                  objtemplate))
                    return objtemplate

        # this is probably because it's in a component definition
        logger.warning(
                "can't resolve %s -> %s %s" % (node.nicepath, ref, template))
        return None

    def _save_mappings(self, node):
        cls = type(self)
        if not node.args.relref_apply_mappings:
            file = node.args.relref_mappings_file
            open(file, 'w').write('%s\n' % json.dumps(cls.mappings,
                                                      indent='  '))
            logger.info('wrote mappings to %s' % file)
