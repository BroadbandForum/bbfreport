"""Path utilities. Further documentation is TBD."""

# Copyright (c) 2020-2023, Broadband Forum
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

from __future__ import annotations

import re

from typing import Any

from .logging import Logging
from .property import Null, NullType
from .utility import ScopeEnum

# we don't want to import .node, because it imports this module!
Node = Any

logger = Logging.get_logger(__name__)


# XXX the entity map doesn't really belong here:
#     - would like to use __nodes and keep it all generic
#     - but there are special cases to be handled

# this is node.objpath or something derived from it (a given node might be in
# the map several times with slightly different names)
ObjPath = str


class Path:
    entity_map: dict[Node, dict[ObjPath, Node]] = {}

    @classmethod
    def _add_to_entity_map_helper(cls, node: Node, *, model: Node,
                                  objpath: str) -> None:
        model_map = cls.entity_map.setdefault(model, {})

        model_map[objpath] = node
        if objpath.endswith('.'):
            model_map[objpath[:-1]] = node
        if objpath.endswith('.{i}.'):
            model_map[objpath[:-4]] = node
            model_map[objpath[:-5]] = node

    @classmethod
    def _add_to_entity_map(cls, node: Node, *, model: Node) -> None:
        objpath = node.objpath
        cls._add_to_entity_map_helper(node, model=model, objpath=objpath)

        # allow omission of 'Input.' and 'Output.' when referencing command
        # arguments
        for special in {'Input.', 'Output.'}:
            search, replace = '().%s' % special, '().'
            if objpath.find(search) >= 0:
                objpath_ = objpath.replace(search, replace)
                cls._add_to_entity_map_helper(
                        node, model=model, objpath=objpath_)

    @classmethod
    def set_entity_map(cls, model: Node) -> None:
        for p in model.parameters:
            cls._add_to_entity_map(p, model=model)
        for o in model.objects:
            cls._add_to_entity_map(o, model=model)
            for p in o.parameters:
                cls._add_to_entity_map(p, model=model)
            for c in o.commands:
                cls._add_to_entity_map(c, model=model)
                if c.input:
                    for cp in c.input.parameters:
                        cls._add_to_entity_map(cp, model=model)
                    for co in c.input.objects:
                        cls._add_to_entity_map(co, model=model)
                        for cp in co.parameters:
                            cls._add_to_entity_map(cp, model=model)
                if c.output:
                    for cp in c.output.parameters:
                        cls._add_to_entity_map(cp, model=model)
                    for co in c.output.objects:
                        cls._add_to_entity_map(co, model=model)
                        for cp in co.parameters:
                            cls._add_to_entity_map(cp, model=model)
            for e in o.events:
                cls._add_to_entity_map(e, model=model)
                for ep in e.parameters:
                    cls._add_to_entity_map(ep, model=model)
                for eo in e.objects:
                    cls._add_to_entity_map(eo, model=model)
                    for ep in eo.parameters:
                        cls._add_to_entity_map(ep, model=model)

    def __init__(self, path: str):
        # remove leading '#.', '##.' etc.
        # XXX do we need to add code to handle the '.' special case?
        rest = path
        self._uplevels = 0
        match = re.match(r'(#+)(\.?)(.*)', rest)
        if match:
            hashes, dot, rest = match.groups(0)
            self._uplevels = len(hashes)
            if hashes and not dot and rest:
                logger.warning('missing dot in relative path %s; should be '
                               '%s.%s' % (path, hashes, rest))

        # split on '.' but not if followed by '{' (multi-instance)
        # note that for objects the final component is empty
        # XXX should be flexible re command and event final periods?
        self._comps = re.split(r'\.(?!{)', rest)
        assert len(self._comps) > 0

    def absolute_path(self, objpath: 'Path', *,
                      scope: ScopeEnum | None = None) -> Path:
        assert isinstance(objpath, Path) and objpath.uplevels == 0

        # objpath can reference an object, parameter, command or event, but its
        # final component (which is empty for an object) is always ignored

        # if objpath is empty or refers to a top-level parameter then the Root
        # or Service Object isn't known and (if needed) will be set to an
        # empty string

        # unless overridden below, the returned path is a copy of this path
        # XXX or modify the constructor to allow a Path argument
        relpath = Path(str(self))

        if scope == 'absolute':
            pass

        # from TR-106 A.2.3.4 Reference Path Names:

        # if the path name scope is normal
        elif scope == 'normal':
            # if the path is empty, it MUST be regarded as referring to the
            # top of the naming hierarchy
            if self._isempty():
                pass

            # otherwise, if the path begins with a "Device." component,
            # it MUST be regarded as a full Path Name
            elif self._startswithdevice():
                pass

            # otherwise, if the path begins with a dot ("."), it MUST be
            # regarded as a path relative to the Root or Service Object
            elif self._startswithdot():
                # XXX if objpath is empty, this will be empty
                relpath._comps[0] = objpath._comps[0]

            # otherwise, it MUST be regarded as a path relative to the
            # current object; any leading hash characters ("#") cause it to
            # be relative to the parent of the current object (or the
            # parent’s parent, and so on)
            else:
                maxlevels = len(objpath._comps) - 1
                # XXX should warn if there are too many uplevels
                uplevels = min(self._uplevels, maxlevels)
                relpath._uplevels = 0
                relpath._comps = objpath._comps[
                                 :maxlevels - uplevels] + self._comps

        # if the path name scope is model
        elif scope == 'model':
            toplevel = objpath._toplevel()
            # if the top level is empty (unknown), can't do anything
            if toplevel == '':
                relpath._uplevels = 0

            # if the path is empty, it MUST be regarded as referring to the
            # Root or Service Object
            elif self._isempty():
                relpath._comps = [toplevel]

            # otherwise, it MUST be regarded as a path relative to the Root
            # or Service Object; any leading dot MUST be ignored. Leading
            # hash characters are not permitted
            else:
                first = 1 if self._startswithdot() else 0
                # XXX should warn if there are any uplevels
                relpath._uplevels = 0
                relpath._comps = [toplevel] + self._comps[first:]

        # if the path name scope is object
        else:
            # if the path is empty, it MUST be regarded as referring to the
            # current object
            if self._isempty():
                relpath._comps = objpath._comps[:-1]

            # otherwise, it MUST be regarded as a path relative to the
            # current object; any leading dot MUST be ignored. Leading hash
            # characters are not permitted
            else:
                # XXX should warn if there are any uplevels... but in fact
                #     process them, so should warn if there are too many
                maxlevels = len(objpath._comps) - 1
                uplevels = min(self._uplevels, maxlevels)
                first = 1 if self._startswithdot() else 0
                relpath._uplevels = 0
                relpath._comps = objpath._comps[
                                 :maxlevels - uplevels] + self._comps[first:]

        assert relpath._uplevels == 0
        return relpath

    def _isempty(self) -> bool:
        return self._uplevels == 0 and self._comps[0] == '' and len(
                self._comps) == 1

    def _startswithdot(self) -> bool:
        return self._uplevels == 0 and self._comps[0] == '' and len(
                self._comps) > 1

    # checks whether a path starts with 'Device.'; also checks for starting
    # with 'InternetGatewayDevice.'
    def _startswithdevice(self) -> bool:
        return self._uplevels == 0 and len(self._comps) > 1 and \
               self._comps[0] in {'InternetGatewayDevice', 'Device'}

    # return empty string if we can't determine top-level object from the path,
    # e.g. if there's only one component it's a top-level parameter
    def _toplevel(self, dot: bool = False) -> str:
        return '' if (self._uplevels > 0 or len(self._comps) == 1) else \
            (self._comps[0] + ('.' if dot else ''))

    def __str__(self) -> str:
        uplevels = (('#' * self._uplevels) + '.') if self._uplevels else ''
        return uplevels + '.'.join(self._comps)

    @property
    def uplevels(self) -> str:
        return self._uplevels

    @property
    def comps(self) -> list[str]:
        return self._comps[:]

    # alias
    split = comps


# utilities
def set_entity_map(node: Node) -> None:
    if (model := node.model_in_path) and model not in Path.entity_map:
        Path.set_entity_map(model)


# XXX this used to return None on failure, but Null makes more sense
def get_entity(objpath: str, model: Node) -> Node | NullType:
    return Null if model not in Path.entity_map else \
        Path.entity_map[model].get(objpath, Null)


def absolute_path(target: str, objpath: str, *,
                  scope: ScopeEnum | None = None) -> str:
    return str(Path(target).absolute_path(Path(objpath), scope=scope))


# relative path from objpath to target
# XXX this should be integrated into the Path class and could almost certainly
#     share more of its logic, e.g. command and event special cases
def relative_path(target: str, objpath: str, *,
                  scope: ScopeEnum | None = None, strip: int = 0):
    # target is probably absolute already, but this isn't required
    atarget = absolute_path(target, objpath, scope=scope)

    # create target and object Path objects
    atpath = Path(atarget)
    opath = Path(objpath)

    # XXX this seems to cause problems for commands and events, which behave
    #     like objects but need to behave like parameters here; also 'Input'
    #     and 'Output' don't contribute to the path
    def fix_comps(comps):
        new_comps = []
        is_command_or_event = False
        last_was_command = False
        for comp in comps:
            if not is_command_or_event:
                is_command_or_event = comp.endswith('()') or \
                                      comp.endswith('!')
            if is_command_or_event and (comp == '' or (
                    last_was_command and comp in {'Input', 'Output'})):
                pass
            else:
                new_comps.append(comp)
            last_was_command = comp.endswith('()')
        return new_comps

    atpath_comps = fix_comps(atpath.comps)
    opath_comps = fix_comps(opath.comps)

    # count the number of common leading components
    num_common = 0
    for i in range(min(len(atpath_comps), len(opath_comps))):
        if atpath_comps[i] == opath_comps[i]:
            num_common += 1
        else:
            break

    # starting with objpath, step up (len(opath_comps) - num_common - 1) comps,
    # and ignore the first num_common target comps; for example, with
    # - target  Device.MAP.Domain.{i}. (#comps = 4)
    # - objpath Device.QoS.Classification.{i}.Interface (#comps = 4)
    # num_common = 1, so step up 4 - 1 = 3 (###) and ignore 1 (Device) to
    # give ###.Map.Domain.{i}.
    # XXX can this ever be negative? should check
    num_steps_up = len(opath_comps) - num_common - 1
    prefix = num_steps_up * '#'
    suffix = '.'.join(atpath_comps[num_common:])
    result = prefix + ('.' if prefix and suffix else '') + suffix

    logger.info('target (%d) %r objpath (%d) %r num_common %d num_steps_up %r '
                'prefix %r suffix %r' % (
                    len(atpath_comps), atpath_comps, len(opath_comps),
                    opath_comps, num_common, num_steps_up, prefix, suffix))

    # if requested, strip trailing '{i}.' and/or '.'
    if strip > 0:
        result = re.sub(r'{i}\.$', r'', result)
    if strip > 1:
        result = re.sub(r'\.$', r'', result)

    logger.info('%s: %s -> %s' % (opath, atpath, result))
    return result


# pattern to match a command or event node's objpath
command_or_event_pattern = re.compile(r'(\(\)|!)$')


def follow_reference(node: Node,
                     target_or_targets: str | list[str] | None, *,
                     scope: ScopeEnum | None = None,
                     quiet: bool = False) -> Node | NullType:
    # protect against being called with a Null node
    if not node:
        return Null

    # XXX should handle this better
    set_entity_map(node)

    # pathRef might not have any targets
    if not target_or_targets:
        return Null

    # get the node's model
    model = node.model_in_path

    # get the node's object path
    objpath = node.objpath

    # commands and events are problematic because they are a bit like
    # both parameters (plain 'Param' is a sibling) and objects (plain 'Param'
    # is a child), so support both behaviors
    # XXX the object-like behavior takes precedence, so if 'Param' is an
    #     argument this will "beat" a 'Param' sibling (can use `##.Param' to
    #     force a sibling to be referenced)
    objpaths = ([objpath + '.'] if command_or_event_pattern.search(
            objpath) else []) + [objpath]

    # be forgiving of '#' references in command arguments (they may have been
    # written on the assumption that the 'Input.' and 'Output.' levels don't
    # count)
    targets = target_or_targets[:] if \
        isinstance(target_or_targets, list) else [target_or_targets]
    if re.search(r'\(\)\.(Input|Output)\.', objpath):
        for target in targets[:]:
            if target.startswith('#'):
                # note that the exception case is inserted at the start,
                # so it takes precedence over the normal case
                targets = ['#%s' % target] + targets

            else:
                # note that the exception case is appended, so it only
                # applies when the normal case fails
                # XXX this is a horrible hack that covers the case where a
                #     capability parameter has been moved from an object to
                #     its parent in a component that's used in both CWMP and
                #     USP data models, e.g., Device.IP.Diagnostics.
                #     IPLayerCapacityMetrics.NumberOfConnections ->
                #     IPLayerMaxConnections works for CWMP but for USP
                #     IPLayerCapacity().Input.NumberOfConnections needs to find
                #     it in Device.IP.Diagnostics. (up two levels)
                # XXX for consistency, should allow #.xxx and ##.xxx in both
                #     cases but it's not needed and all these exceptions
                #     increase the chances of undetected errors
                # XXX should be able to emit warnings when exceptions such as
                #     this are made use of; maybe optionally return a list,
                #     maybe as part of a more general "store log messages"
                #     mechanism
                targets += ['##.%s' % target]

    # for now, we care only that at least one of the targets exists
    # XXX this is controlled by a description template: later...
    target_node = None
    bad_refpaths = []
    for objpath_ in objpaths:
        for target in targets:
            # XXX ignore targets containing '.Services.' (apart from the
            #     Services object itself) because these will be referencing
            #     a different data model
            if target not in \
                    {'Device.Services.', 'InternetGatewayDevice.Services.'} \
                    and target.find('.Services.') >= 0:
                continue

            # - allow direct references between input and output arguments
            refpath = absolute_path(target, objpath_, scope=scope)
            refpaths = [refpath]
            if '().Input.' in refpath:
                refpaths += [refpath.replace('().Input.', '().Output.')]
            elif '().Output.' in refpath:
                refpaths += [refpath.replace('().Output.', '().Input.')]

            for refpath_ in refpaths:
                target_node = get_entity(refpath_, model=model)
                if target_node:
                    break

                bad_refpaths += ['%s + %s = %s' % (objpath_, target, refpath_)]

            if target_node:
                break

        if target_node:
            break

    # don't output an error if never checked any paths
    if not target_node and bad_refpaths and not quiet:
        logger.error('%s: reference to non-existent %s:' % (
            objpath, target_or_targets))
        for bad_refpath in bad_refpaths:
            logger.error('  %s' % bad_refpath)

    return target_node or Null
