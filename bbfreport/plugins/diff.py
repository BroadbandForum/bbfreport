"""Diffs transform plugin."""

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

import cProfile
import difflib
import pstats
import re
import sys
import time

from dataclasses import dataclass
from enum import Enum
from typing import Any, cast, Dict, List, Optional, Set, Union

from ..macro import Macro
from ..node import (Description, _HasContent, Model, _ModelItem, Node,
                    _ProfileItem, Root, _ValueFacet)
from ..path import relative_path

Diffs = Dict[Union[_ModelItem, _ValueFacet], List['Diff']]

# XXX need to optimize object_elems, which calls object_objects, which calls
#     objpath; object_elems is only needed to associate object addition and
#     deletion with the correct parent; everything is much better if
#     _path_split is cached
time_it = False


# XXX in general should make more use of Enums and dataclasses
class Entity(Enum):
    attr = 1
    elem = 2
    content = 3


class Operation(Enum):
    added = 1
    removed = 2
    changed = 3


# XXX in general should make more use of dataclasses
# XXX note that defining them as nested classes is VERY slow
# XXX there should also be a Diffs class
@dataclass
class Diff:
    old_node: Node
    new_node: Node
    entity: Entity
    operation: Operation
    # XXX python 3.10 _: KW_ONLY = None
    name: Optional[str] = None
    value: Optional[Any] = None
    value2: Optional[Any] = None
    elem: Optional[Node] = None
    is_whitespace: Optional[bool] = False

    @staticmethod
    def append(diffs: Diffs, old_node: Node, new_node: Node, entity: Entity,
               operation: Operation, *, name: Optional[str] = None,
               value: Optional[Any] = None, value2: Optional[Any] = None,
               elem: Optional[Node] = None,
               is_whitespace: bool = False) -> None:
        # we refer to it as a model item, but in fact it can be either a model
        # item (object, parameter, command, event, ...) or a value facet
        # (enumeration, pattern), all of which have descriptions
        model_item_node = \
            new_node.instance_in_path((_ModelItem, _ValueFacet)) or new_node
        diffs.setdefault(model_item_node, []).append(
                Diff(old_node, new_node, entity, operation, name=name,
                     value=value, value2=value2, elem=elem,
                     is_whitespace=is_whitespace))

    def __str__(self):
        name = self.name if self.name else self.elem.typename if self.elem \
            else self.entity.name
        text = '%s %s' % (self.operation.name, name)
        if self.is_whitespace:
            text += ' (W)'
        if self.entity == Entity.attr:
            text += ' %s' % self.value
            if self.operation == Operation.changed:
                text += ' -> %s' % self.value2
        elif self.entity == Entity.elem:
            if str(self.elem) != name:
                text += ' %s' % self.elem
        elif self.entity == Entity.content:
            # XXX heuristic conversion of a list of macro references and
            #     strings to a single string (it should be in macro.py)
            def as_string(c) -> str:
                s = ''.join(str(x) for x in c)
                r = re.sub(r'^{{div\|{{classes}}\|(.*)}}$', r'\1', s)
                r = r.replace('}}{{div|{{classes}}|', '\n\n')
                r = r.replace('{{nl}}', '\n')
                return r

            i1, i2, c1 = self.value
            j1, j2, c2 = self.value2
            if i2 > i1:
                text += ' %r' % as_string(c1)
            if i2 > i1 and j2 > j1:
                text += ' ->'
            if j2 > j1:
                text += ' %r' % as_string(c2)
        return text


# need two files on the command line
# XXX what if there are two models in a single file?
def _post_init_(args, logger) -> Optional[bool]:
    if len(args.file) != 2:
        logger.error('need two files (old and new) on the command line '
                     '(%d were supplied)' % len(args.file))
        return True

    # XXX should this be unconditional?
    logger.debug('auto-enabled --show')
    args.show = True


def visit(root: Root, args, logger) -> Optional[bool]:
    # get the models from the command-line documents
    models = []
    for xml_file in root.xml_files:
        dm_document = xml_file.dm_document
        for model in dm_document.models:
            models.append(model)

    if len(models) != 2 or models[0] is models[1]:
        logger.error('need two models to compute diffs')
        return True

    # enable profiling?
    profile = None
    if time_it:
        profile = cProfile.Profile()
        profile.enable()

    # we need to traverse the two models, comparing them
    # XXX this isn't yet comparing referenced items such as data types
    def key_str(mod: Model) -> str:
        return '{%s}%s' % mod.key

    logger.info('comparing %s and %s' % (
        key_str(models[0]), key_str(models[1])))
    start = time.time()
    diffs = node_diffs(models[0], models[1], logger=logger)
    logger.info('compared %s and %s in %d ms' % (
        key_str(models[0]), key_str(models[1]), (time.time() - start) * 1000))

    # disable profiling?
    if time_it:
        profile.disable()
        stats = pstats.Stats(profile, stream=sys.stderr)
        stats.strip_dirs()
        stats.sort_stats('time')
        stats.print_stats(50)
        # XXX it doesn't seem possible to control the caller/callee order?
        stats.print_callers(20)
        stats.print_callees(20)

    # hide the entire node tree
    root.hide()

    # {{diffs}} macro argument formatting helpers
    def emph_str(txt: str) -> str:
        return '*%s*' % txt if txt else '""'

    def elem_str(nod: Node) -> str:
        return relative_path(nod.objpath, new_node.objpath, scope='absolute') \
            if isinstance(nod, _ModelItem) else val if (val := str(nod)) \
            else ''

    def elem_ref(nod: Node) -> str:
        # XXX there should be a method/utility for this
        macro = nod.typename.replace('parameter', 'param')
        # noinspection PyProtectedMember
        return '{{%s|%s|object}}' % (macro, elem_str(nod)) \
            if isinstance(nod, _ModelItem) and macro in Macro._macros \
            else emph_nod(nod)

    def emph_nod(nod: Node) -> str:
        # note the trailing space
        return '*%s* ' % val if (val := elem_str(nod)) else ''

    # add {{diffs}} macros to the second model
    # XXX and content changes
    counts = {}
    for model_item, model_item_diffs in diffs.items():
        str_model_item = str(model_item)
        macro_args = []
        body = []
        new_node = None
        new_body = None
        j = 0
        any_attr_diff = any(d.entity == Entity.attr for d in model_item_diffs)
        any_elem_diff = any(d.entity == Entity.elem for d in model_item_diffs)
        any_cont_diff = any(d.entity == Entity.content
                            and not d.is_whitespace for d in model_item_diffs)
        for model_item_diff in model_item_diffs:
            # the node that changed
            old_node, new_node = \
                model_item_diff.old_node, model_item_diff.new_node
            str_new_node = str(new_node)

            # if the node matches --debugpath, log at the info level
            logger_func = logger.info if args.debugpath and re.search(
                    args.debugpath, new_node.debugpath) else logger.debug

            # ignore whitespace-only changes
            # XXX should be able to control this
            if not model_item_diff.is_whitespace:
                logger_func('%s %s %s' % (new_node.nicepath, new_node.typename,
                                          model_item_diff))

            # unhide the changed node and its ancestors (and their
            # description elements)
            if any_attr_diff or any_elem_diff or any_cont_diff:
                new_node.object_unhide(description=True, upwards=True)
                # logger.debug('%s %s (and up) unhidden' % (
                #     new_node.nicepath, new_node.typename))

            # provide some additional context if the model item node isn't the
            # new node (the node that changed); it will always be an ancestor
            context = ''
            if str_new_node != str_model_item:
                # don't include content (e.g, descriptions) in the context;
                # also don't include it if it essentially duplicates typename
                if not isinstance(new_node, _HasContent) and str_new_node != \
                        '' and new_node.typename not in str_new_node:
                    context += '*%s* ' % str_new_node
                context += '%s ' % new_node.typename

            if model_item_diff.entity == Entity.attr:
                operation, name, value, value2 = (
                    model_item_diff.operation, model_item_diff.name,
                    model_item_diff.value, model_item_diff.value2)
                macro_arg = '%s %sattribute %s = %s%s' % (
                    operation.name.capitalize(), context, emph_str(name),
                    emph_str(value), ' &rArr; %s' % emph_str(value2) if
                    value2 is not None else '')
                macro_args.append(macro_arg)

            elif model_item_diff.entity == Entity.elem:
                elem, typename = \
                    model_item_diff.elem, model_item_diff.elem.typename
                if model_item_diff.operation == Operation.added:
                    macro_args.append('Added %s%s %s' % (
                        context, elem_ref(elem), typename))
                    # unhide the new elem, its children and ancestors
                    elem.object_unhide(upwards=False)
                    elem.object_unhide(upwards=True)
                    # logger.debug('%s %s (and down and up) unhidden' % (
                    #     elem.nicepath, elem.typename))
                elif model_item_diff.operation == Operation.removed:
                    # we won't try to reference it; it's no longer there!
                    macro_args.append('Removed %s%s%s' % (
                        context, emph_nod(elem), typename))

            elif model_item_diff.entity == Entity.content:
                assert model_item_diff.operation == Operation.changed, \
                    'invalid operation %s' % model_item_diff.operation.name
                old_body = old_node.content.body_as_list
                new_body = new_node.content.body_as_list

                tag = model_item_diff.name
                i1, i2, _ = model_item_diff.value
                j1, j2, _ = model_item_diff.value2

                # XXX explain this and use better variable names
                if j1 > j:
                    body.extend(new_body[j:j1])

                # escape special characters in 'old'
                # XXX shouldn't use strings here?
                # XXX should have a method for this; cf re.escape()
                # XXX quoted '{' and '}' can cause problems with macro parsing;
                #     pending fixing these, use '\|' (in the right order! a
                #     regex would be better)
                old = ''.join(str(s)
                              .replace(r'|', r'\|')
                              .replace(r'{{', r'\|')
                              .replace(r'}}', r'\|') for s in old_body[i1:i2])
                new = ''.join(str(s) for s in new_body[j1:j2])
                if tag == 'replace':
                    # XXX this can cause problems when old closes a macro and
                    #     opens another one (same for new?); for example,
                    #     [close(param), ' ', 'and', open(param), 'B'] -> [];
                    #     this will happen with '{{param|A}} and {{param|B}}'
                    #     -> '{{param|A}}' (I thought that including a macro
                    #     nesting level might help, but I don't think it does)
                    body.append('{{replaced|%s|%s}}' % (old, new))
                    # body.append('{{removed|%s}}' % old)
                    # body.append('{{inserted|%s}}' % new)
                elif tag == 'delete':
                    body.append('{{removed|%s}}' % old)
                elif tag == 'insert':
                    body.append('{{inserted|%s}}' % new)

                j = j2

            counts.setdefault((model_item_diff.entity,
                               model_item_diff.operation), 0)
            counts[(model_item_diff.entity, model_item_diff.operation)] += 1

        if macro_args:
            if not model_item.description:
                # XXX it's necessary to create the content like this, or else
                #     to call merge(); you can't just do something like
                #     node.description.content = Content() because this ends
                #     up with two Content objects; such things should be
                #     detected
                model_item.description = Description(data=(('content', ()),))
            footer = '{{diffs|%s}}' % '|'.join(macro_args)
            model_item.description.content.footer = footer
            logger.debug('%s %s footer %r (%r)' % (
                model_item.nicepath, model_item.typename, footer,
                model_item.description.content.footer))

        if new_node:
            if new_body and 0 < j < len(new_body):
                body.extend(new_body[j:])
            if body:
                # XXX this is horrible; should be able to use Content / str
                #     methods directly
                # XXX what's more, it's wrong, because it includes the wrapping
                #     divs, which makes 'content_plus' wrong (adding content
                #     should be inline/block aware; cf pandoc!)
                # XXX could/should use args.debugpath-aware logger_func() but
                #     will defer this until the above problems have been fixed
                content = ''.join(str(s) for s in body)
                footer = model_item.description.content.footer
                model_item.description.content = content
                model_item.description.content.footer = footer
                logger.debug('%s %s content %r)' % (
                    model_item.nicepath, model_item.typename,
                    content.replace('\\', '')))

    logger.debug('appended {{diffs}} macro refs: %s' % ', '.join(
            '%s %s = %s' % (ent.name, op.name, val) for (ent, op), val in
            sorted(counts.items(), key=lambda i: [x.name for x in i[0]])))


# attr names and node typenames to ignore when comparing nodes
# XXX I'm not sure whether or not to include 'functional' here
# XXX profiles are complicated, so ignore them for now
ignored_attrnames = {'action', 'activeNotify', 'dmr_previousParameter',
                     'dmr_previousObject', 'dmr_previousCommand',
                     'dmr_previousEvent', 'dmr_previousProfile', 'dmr_version',
                     'functional', 'targetParent', 'version'}
ignored_typenames = {'componentRef', 'profile'}


# XXX this should be a _Node method and should use comparison operators, where
#     (a <= b, a == b, a > b) mean (b is a valid later version of a, b is the
#     same as a, b is an invalid extension of a); there should also be
#     functional versions of the comparison operators that return the diffs)
def node_diffs(old_node: Node, new_node: Node, *,
               diffs: Optional[Diffs] = None, logger, level: int = 0) -> Any:
    if diffs is None:
        diffs = {}

    # sanity check
    assert type(old_node) is type(new_node)

    # attributes have names, so it's easy to tell what's been added etc.
    attrs_changed = {name: (value, new_node.attrs[name]) for name, value in
                     old_node.attrs.items() if name not in ignored_attrnames
                     and name in new_node.attrs
                     and new_node.attrs[name] != value}
    attrs_removed = {name: value for name, value in old_node.attrs.items()
                     if name not in ignored_attrnames
                     and name not in new_node.attrs}
    attrs_added = {name: value for name, value in new_node.attrs.items()
                   if name not in ignored_attrnames
                   and name not in old_node.attrs}

    if attrs_changed:
        for name, (old_, new_) in attrs_changed.items():
            Diff.append(diffs, old_node, new_node, Entity.attr,
                        Operation.changed, name=name, value=old_, value2=new_)
    if attrs_removed:
        for name, value in attrs_removed.items():
            Diff.append(diffs, old_node, new_node, Entity.attr,
                        Operation.removed, name=name, value=value)
    if attrs_added:
        for name, value in attrs_added.items():
            Diff.append(diffs, old_node, new_node, Entity.attr,
                        Operation.added, name=name, value=value)

    # elements are a bit harder (it depends on whether they're keyed)
    elem2s_both = set()
    for elem1 in old_node.object_elems:
        # should this element be ignored?
        if elem1.typename in ignored_typenames:
            continue

        # XXX new_node won't contain an item with the same key; need to know
        #     how many components to ignore; for now, assume 1 (the name of
        #     the file that defined the model; see node.py Model._calckey())
        elem2s = [elem2 for elem2 in new_node.object_elems if
                  elem2.typename == elem1.typename and (
                          not elem2.key or elem2.key[1:] == elem1.key[1:])]
        if not elem2s:
            Diff.append(diffs, old_node, new_node, Entity.elem,
                        Operation.removed, elem=elem1)
            continue

        # if there are multiple matches, try str()
        # XXX could try this first, but str() might be expensive?
        if len(elem2s) > 1:
            elem2s_maybe = [elem2 for elem2 in new_node.object_elems if
                            elem2.typename == elem1.typename and
                            str(elem2) == str(elem1)]
            if elem2s_maybe:
                elem2s = elem2s_maybe

        # if there are multiple matches, try the 'value' attribute (this
        # will catch enumerations and patterns)
        # XXX perhaps should treat these as keyed?
        # XXX str() catches all these? no longer need this
        if False and len(elem2s) > 1:
            elem2s_maybe = [elem2 for elem2 in new_node.object_elems if
                            elem2.typename == elem1.typename and
                            hasattr(elem2, 'value') and
                            cast(_ValueFacet, elem2).value ==
                            cast(_ValueFacet, elem1).value]
            if elem2s_maybe:
                elem2s = elem2s_maybe

        # if there are multiple matches, try the 'ref' attribute (this
        # will catch profile references)
        # XXX perhaps should treat these as keyed?
        # XXX str() catches all these? no longer need this
        if False and len(elem2s) > 1:
            elem2s_maybe = [elem2 for elem2 in new_node.object_elems if
                            elem2.typename == elem1.typename and
                            hasattr(elem2, 'ref') and
                            cast(_ProfileItem, elem2).ref ==
                            cast(_ProfileItem, elem1).ref]
            if elem2s_maybe:
                elem2s = elem2s_maybe

        # if there are still multiple matches, try the child elems' 'ref'
        # attributes (this will catch unique keys)
        # XXX use _ProfileItem here because unique keys use ParameterRef
        # XXX perhaps should treat these as keyed?
        if False and len(elem2s) > 1:
            def child_refs(nod: Node) -> Set[str]:
                return {cast(_ProfileItem, ele).ref for ele in nod.object_elems
                        if hasattr(ele, 'ref')}

            elem2s_maybe = [elem2 for elem2 in new_node.object_elems if
                            elem2.typename == elem1.typename and child_refs(
                                    elem1) == child_refs(elem2)]
            if elem2s_maybe:
                elem2s = elem2s_maybe

        if len(elem2s) > 1:
            elem2s_for_report = [elem2.key or elem2 for elem2 in elem2s]
            logger.error('%s: multiple %s matches %s' % (
                old_node.nicepath, elem1.typename, elem2s_for_report))
            continue

        elem2 = elem2s[0]
        node_diffs(elem1, elem2,
                   diffs=diffs, logger=logger, level=level + 1)

        elem2s_both.add(elem2)

    # check for added elems
    elem2s_added = [elem2 for elem2 in new_node.object_elems if
                    elem2.typename not in ignored_typenames and
                    elem2 not in elem2s_both]
    for elem2 in elem2s_added:
        Diff.append(diffs, old_node, new_node, Entity.elem, Operation.added,
                    elem=elem2)

    # check for changed content
    # XXX should move the difflib logic to Content
    if isinstance(old_node, _HasContent):
        assert isinstance(new_node, _HasContent)
        cont1 = old_node.content
        cont2 = new_node.content
        if not cont1 or not cont2 or cont2 != cont1:
            body1 = cont1.body_as_list
            body2 = cont2.body_as_list
            matcher = difflib.SequenceMatcher(None, body1, body2)
            done_header = False
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                chunk1 = body1[i1:i2]
                chunk2 = body2[j1:j2]

                # whitespace-only changes are added here, but can be ignored
                # when rendering the diffs
                is_whitespace = False

                # ignore unchanged chunks
                if tag == 'equal':
                    continue

                # check for a whitespace-only change
                if all(isinstance(s, str) and (not s or s.isspace()) for s in
                       chunk1) and all(
                        isinstance(s, str) and (not s or s.isspace()) for s in
                        chunk2):
                    is_whitespace = True

                # this is a whitespace-only change, and is due to paragraph
                # wrapping
                # XXX this doesn't sound quite right; {{np}} should trigger
                #     a new {{div}}, but why {{np}}?
                # XXX for now, take the easy way out and compare them as
                #     strings (will redo this later)
                # XXX should generalize this to check for any 'close then
                #     open' within a chunk, because this is harder to handle
                if str(chunk1) == '[call(nl)]' and str(chunk2) == \
                        '[close(div), open(div), call(classes), argsep(|)]':
                    is_whitespace = True

                # this is another whitespace-only change, and is due to using
                # status="append" to append to a description
                # XXX see the XXX comments to the above case
                if str(chunk1) == \
                        '[close(div), open(div), call(classes), argsep(|)]' \
                        and str(chunk2) == '[call(np)]':
                    is_whitespace = True

                # debug: output header if not already done
                if not done_header:
                    logger.debug('%s' % new_node.nicepath)
                    logger.debug('  %d body1 %s' % (len(body1), body1))
                    logger.debug('  %d body2 %s' % (len(body2), body2))
                    done_header = True

                # debug: report chunk
                white = '(W)' if is_whitespace else '...'
                logger.debug('    %-7s value[%d:%d] -> value2[%d:%d] %s '
                             '%r -> %r' % (
                                 tag, i1, i2, j1, j2, white, chunk1, chunk2))

                # append the diff
                # XXX it would probably be better to add a single diff outside
                #     this loop (it would make the logic clearer)
                Diff.append(diffs, old_node, new_node, Entity.content,
                            Operation.changed, name=tag,
                            value=(i1, i2, chunk1), value2=(j1, j2, chunk2),
                            is_whitespace=is_whitespace)
    return diffs
