"""Lint transform plugin."""

# Copyright (c) 2022-2023, Broadband Forum
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

# XXX the term 'macro' (rather than 'template') is always used

# XXX unlike report.pl, all lint messages are warnings (none are errors)

# XXX be consistent with regard to %r versus %s and wording style

import re

from typing import cast, List, Optional

from ..content import MacroRef
from ..macro import Macro
from ..node import _Base, Command, DataType, DataTypeRef, Default, Event, \
    _HasContent, _HasDescription, _HasRefType, Object, ObjectRef, Parameter, \
    ParameterRef, PathRef, Profile, _ProfileItem, Syntax, Template, UniqueKey
from ..property import Null
from ..utility import Status, Version

# expected status 'from' to 'to' version deltas
deprecated_to_obsoleted_delta, obsoleted_to_deleted_delta = 2, 1

# node status escalations, in the order that they will be checked
node_status_escalations = [
    ('obsoleted', 'deleted', obsoleted_to_deleted_delta),
    ('deprecated', 'obsoleted', deprecated_to_obsoleted_delta),
    ('deprecated', 'deleted',
     deprecated_to_obsoleted_delta + obsoleted_to_deleted_delta)
]


class VersionRange:
    """Parse a deprecated / obsoleted / deleted macro reference's version
    attribute.

    The value should be an m.n[.p] version or a range such as 2.15-2.17.
    """

    def __init__(self, spec: str):
        self.vers = [Version(comp) for comp in spec.split('-', 1)]

        # check that versions in the range are increasing
        if self.vers != sorted(self.vers):
            raise ValueError("range isn't increasing")

    def __str__(self):
        return str(self.vers)

    __repr__ = __str__


# factory methods that returns info() etc. functions that will call
# logger.info(node.objpath + ': ' + msg) etc.
# XXX note that node.objpath is not called until the function is called
# XXX info, warning, error, debug etc. should be supplied as visit_xxx()
#  arguments
def report_func(node, func):
    return lambda text: func('%s: %s' % (
        node.fullpath(style='object+item+component+value'), text))


error_func = lambda node, logger: report_func(node, logger.error)
warning_func = lambda node, logger: report_func(node, logger.warning)
info_func = lambda node, logger: report_func(node, logger.info)
debug_func = lambda node, logger: report_func(node, logger.debug)


# do nothing if --thisonly was specified
def _begin_(_, args) -> bool:
    return args.thisonly


def status_macro_helper(node: _HasDescription, macro_ref: MacroRef, *,
                        transitions, logger) -> None:
    warning = warning_func(node, logger)

    # XXX it would be better to raise ValueError and let the caller report?
    transition = macro_ref.name
    errors = 0

    # check it has at least one argument (the version)
    if (num_args := len(macro_ref.args)) == 0:
        warning('{{%s}} version is empty' % transition)
        errors += 1

    # get the version (it should be a simple string)
    if not macro_ref.args[0].is_simple:
        warning("%s version %s isn't a simple string" % (
            transition, macro_ref.args[0]))
        errors += 1

    # parse the version (it can specify a range)
    else:
        version_spec = macro_ref.args[0].text
        version = None
        try:
            version = VersionRange(version_spec)
        except (AttributeError, ValueError) as e:
            warning('invalid {{%s}} version %r: %s' % (
                transition, version_spec, e))
            errors += 1

    # warn if this transition is invalid
    if Status(transition) > node.status:
        warning('is %s, so {{%s}} is invalid' % (node.status, transition))
        errors += 1

    # if there were no errors, update the transitions argument
    if errors == 0 and transitions is not None:
        transitions[transition] = version

    # check that {{deprecated}} has a second argument (the reason)
    if transition == 'deprecated' and num_args == 1:
        warning('no reason for deprecation is given')


def visit__base(node: _Base, logger):
    warning = warning_func(node, logger)
    info = info_func(node, logger)

    def all_versions(nod: _Base,
                     vers: Optional[List[Version]] = None) -> List[Version]:
        if vers is None:
            vers = []
        if nod.version is not None:
            # it might already be there, but this doesn't matter
            vers.append(nod.version)
        if isinstance(nod.object_parent, _Base):
            all_versions(nod.object_parent, vers)
        return vers

    if node.version is not None:
        versions = all_versions(node)
        # XXX this is wrong but I guess it's a stronger check; needs thought
        #     it was: if sorted(versions, reverse=True) != versions:
        if node.version < max(versions):
            warning('version %s < inherited %s' % (
                node.version, max(versions)))

        # don't warn for objects and profiles, because version is mandatory
        # XXX this is flawed, because we'll want to do this with --thisonly,
        #     but we don't do lint checks with --thisonly!; will need to
        #     create an interim file? (for now, report at info level)
        if not isinstance(node, (Object, Profile)):
            parent_version = node.object_parent.object_version_inherited
            if parent_version is not None and node.version == parent_version:
                info('version %s is unnecessary' % node.version)

            # mark the node so the XML format can omit the unnecessary version
            node.xml_version = None


# this was visit__has_status(); everything now has status
# XXX if a node has no description element, node.description will be Null and
#     there'll be no Description object, and so no Content object to auto-add
#     macro-references to; maybe elements should be more like attributes, and
#     should be instantiated on reference? or just require a description
#     element (and sometimes allow it to be empty)
def visit__has_description(node: _HasDescription, logger):
    warning = warning_func(node, logger)

    ####################
    # description checks

    # types that must have descriptions
    must = (DataType, Object, Parameter, Command, Event)
    need_not = (Syntax, DataTypeRef)
    # XXX should Profile be included? if so, there are lots of warnings

    if isinstance(node, must) and not isinstance(node, need_not) and \
            node.description_inherited is Null:
        warning('missing description')

    ###############
    # status checks

    # get the model version
    model_version = node.model_in_path.model_version if \
        node.model_in_path else None

    # allow profiles and their children not to have descriptions
    content = node.description.content
    if node.profile_in_path and not content:
        return

    # check the status-related macro references that are present in the
    # description
    # XXX no, here we should just collect the transitions; macro-level
    #     warnings should be output by macro expansion
    transitions = {}
    for status in Status.names:
        if status in content.macro_refs:
            macro_refs = content.macro_refs[status]
            if (num_macro_refs := len(macro_refs)) > 1:
                warning('has %d {{%s}} macro references' % (
                    num_macro_refs, status))
            else:
                status_macro_helper(node, macro_refs[0],
                                    transitions=transitions, logger=logger)

    # check that the appropriate status macro reference is present (we only
    # require the current status's macro, e.g., we wouldn't require
    # {{deprecated}} for an obsoleted node; also, profiles are exempt)
    if not node.profile_in_path and node.status.name != Status.default and \
            node.status.name not in transitions:
        warning('is %s but has no {{%s}} macro' % (
            node.status, node.status))

    # check for late (overdue) or too-early transitions
    warnings = 0
    for from_status, to_status, delta_minor in node_status_escalations:
        delta_ver = Version((0, delta_minor, 0))
        # if there's no transition from 'from', can't check this escalation
        if from_status not in transitions:
            continue

        # the first 'from' version is when the transition occurred
        from_ver_first = transitions[from_status].vers[0]

        # the last 'from' version (which might the same as the first one) is
        # used for 'next transition' warnings (reset the corrigendum number)
        from_ver_last = transitions[from_status].vers[-1]
        expected_ver = from_ver_last.reset(2) + delta_ver

        # don't warn more than once
        if warnings > 0:
            pass

        # or if the model version isn't known, e.g., in a data type definition
        elif model_version is None:
            pass

        # check for a too-early transition
        elif node.status.name == to_status and model_version < expected_ver:
            warning("was %s at %s and shouldn't be %s until %s" % (
                 from_status, from_ver_first, to_status, expected_ver))
            warnings += 1

        # check for a late (overdue) transition
        elif node.status.name == from_status and model_version >= expected_ver:
            be = 'have been' if expected_ver < model_version else 'be'
            warning("was %s at %s and should %s %s at %s" % (
                 from_status, from_ver_first, be, to_status, expected_ver))
            warnings += 1


# XXX this check would be better on Parameter?
def visit__has_ref_type(has_ref_type: _HasRefType, logger):
    node = cast(_Base, has_ref_type)  # _HasRefType is a mixin class
    if has_ref_type.refType == 'weak' and not node.command_in_path and not \
            node.event_in_path and node.parameter_in_path.access == 'readOnly':
        logger.warning('weak reference parameter is not writable')


# note that we can assume that visit__has_status() has been called before this
# is called, e.g., for a parameter (which 'has status') visit_has_status() will
# be called and then its children will be visited, one of which is its
# description (which 'has content')
def visit__has_content(node: _HasContent, args, logger):
    if (args.all or node.is_used is not False) \
            and node.content.markdown is None:
        error = error_func(node, logger)
        warning = warning_func(node, logger)
        info = info_func(node, logger)
        debug = debug_func(node, logger)
        # XXX it's possible that the content was already expanded; see
        #     macros.expand_value()
        # XXX this can be a problem for {{template}}, which may contain
        #     context-dependent macros such as {{enum}}; for now, simply don't
        #     expand them here (they'll be expanded when referenced)
        # XXX more generally, this expands everything, even things that might
        #     not be used
        if not isinstance(node, Template):
            node.content.markdown = Macro.expand(
                    node.content, node=node, error=error, warning=warning,
                    info=info, debug=debug)


def visit_data_type(data_type: DataType, logger):
    warning = warning_func(data_type, logger)

    # check for missing {{units}} macros, which are only required on base types
    if (units := data_type.units_inherited) and not data_type.baseNode:
        # the description is on the containing parameter, or the data type
        owner = data_type.parameter_in_path or cast(DataType, data_type)
        if not owner.dmr_noUnitsTemplate and \
                ('units', 0) not in owner.description.content.macro_refs:
            warning('units %s but no {{units}} macro' % units.value)


def visit_object(obj: Object, logger) -> None:
    warning = warning_func(obj, logger)

    # determine whether this is a USP model
    usp = obj.model_in_path.usp
    ignore_enable_parameter = usp

    # don't check anything for deleted objects
    if obj.status.name == 'deleted':
        return

    # various object attributes
    # XXX need to add DT support
    is_dt, is_writable, is_multi, is_fixed, is_union = \
        False, obj.is_writable, obj.is_multi, obj.is_fixed, obj.is_union

    # find the containing command or event (if any)
    command_or_event = obj.command_in_path or obj.event_in_path

    # simple checks
    if is_writable and obj.maxEntries == 1:
        warning('object is writable but is not a table')

    if is_writable and is_multi and is_fixed:
        warning('fixed size table is writable')

    if is_multi and not obj.objpath.endswith('.{i}.'):
        warning('object is a table but name doesn\'t end with ".{i}."')

    if not is_dt and not is_multi and obj.objpath.endswith('.{i}.'):
        warning('object is not a table but name ends with ".{i}.')

    if not is_multi and obj.uniqueKeys:
        warning('object is not a table but has a unique key')

    if not is_dt and not (is_writable and is_multi) and obj.enableParameter:
        warning('object is not writable and multi-instance but has '
                'enableParameter')

    if obj.enableParameter and not obj.enableParameterNode:
        warning("enableParameter %s doesn't exist" % obj.enableParameter)

    # numEntries parameter checks
    # XXX report.pl logic included 'hidden' (hidden node, not syntax/@hidden)
    #     and has a 'questionable use of "hidden" (TR-196?)' comment
    # XXX report.pl has a --nowarnnumentries command-line option
    if not is_dt and is_multi and not is_fixed and not command_or_event and \
            not (obj.numEntriesParameter and obj.numEntriesParameterNode):
        warning('missing or invalid numEntriesParameter %s' %
                (obj.numEntriesParameter or '',))

    if obj.numEntriesParameterNode:
        num_entries_parameter = obj.numEntriesParameterNode
        name_or_base = obj.object_name or obj.object_base
        expected = name_or_base.replace('.{i}.', '') + 'NumberOfEntries'
        if num_entries_parameter.name != expected and not \
                num_entries_parameter.dmr_customNumEntriesParameter:
            warning('numEntriesParameter %s should be named %s' % (
                num_entries_parameter.name, expected))

        if num_entries_parameter.is_writable:
            warning('numEntriesParameter %s is writable' %
                    num_entries_parameter.name)

        if num_entries_parameter.syntax.default:
            warning('numEntriesParameter %s has a default' %
                    num_entries_parameter.name)

    # discriminator parameter checks:
    # (a) has no discriminator parameter
    if not obj.discriminatorParameter:
        # check that the object is not a union object
        if is_union and not obj.dmr_noDiscriminatorParameter:
            warning('is a union object but has no discriminatorParameter')

    # (b) has a discriminator parameter
    else:
        # check that the object is a union object
        if not is_union:
            warning("isn't a union object but has discriminatorParameter %s" %
                    obj.discriminatorParameter)

        # check that the discriminator parameter exists
        if not obj.discriminatorParameterNode:
            warning("discriminatorParameter %s doesn't exist" %
                    obj.discriminatorParameter)

        # XXX report.pl populates the discriminatedObjects list, and relies
        #     on a {{union}} macro reference to generate {{param}} and {{enum}}
        #     references and (therefore) report invalid references; also to
        #     report unreferenced discriminator parameter enumeration values

    # unique key checks:
    # XXX could be cleverer re checking for read-only / writable unique keys
    # (a) has no unique keys
    if not obj.uniqueKeys:
        # XXX report.pl has a --nowarnuniquekeys command-line option
        if is_multi and not command_or_event and not obj.dmr_noUniqueKeys:
            warning('object is a table but has no unique keys')

    # (b) has unique keys
    else:
        if not is_multi:
            warning('object is not a table but has unique keys')

        any_functional, any_writable = False, False
        for unique_key in obj.uniqueKeys:
            unique_key = cast(UniqueKey, unique_key)
            if unique_key.functional:
                any_functional = True
            for param_ref in unique_key.parameters:
                param_ref = cast(ParameterRef, param_ref)
                param_ref_node = param_ref.refNode
                if param_ref_node is Null:
                    # XXX should review the text of all these messages
                    warning("uniqueKey parameter %s doesn't exist" %
                            param_ref.ref)
                else:
                    assert isinstance(param_ref_node, Parameter)
                    param_ref_node = cast(Parameter, param_ref_node)
                    if param_ref_node.is_writable:
                        any_writable = True

                    # XXX report.pl populates unique key parameters'  #
                    #  uniqueKeyDefs lists

        if is_writable and is_multi and any_functional and any_writable and \
                not obj.enableParameter and not ignore_enable_parameter:
            warning('writable table has no enable parameter')

    # mount type object checks
    if obj.mountType in {'none', 'mountable'}:
        warning('deprecated mount type %s' % obj.mountType)


def visit_parameter(param: Parameter, logger) -> None:
    warning = warning_func(param, logger)
    syntax = param.syntax

    # XXX report.pl has a 'writable parameter in read-only table' warning, but
    #     this isn't necessarily a problem and is output at level 2

    if not syntax.type:
        warning('untyped parameter')

    if syntax.command and not param.is_writable:
        warning('read-only command parameter')

    if syntax.hidden and syntax.secured:
        warning('parameter has both hidden and secured attributes set '
                '(secured takes precedence)')

    # XXX report.pl outputs this at level 1
    if syntax.hidden and syntax.command:
        warning('parameter has both hidden and command attributes set')

    # this is safe, because any undefined elements will be returned as Null
    if syntax.list and syntax.string.enumerations and \
            '' in {enum.value for enum in syntax.string.enumerations}:
        warning('useless empty enumeration value for list-valued parameter')

    if syntax.reference and syntax.string.enumerations:
        warning('%s has enumerated values' % syntax.reference.typename)


# XXX doesn't complain about defaults in read-only objects or tables; this is
#     because they are quietly ignored (this is part of allowing them in
#     components that can be included in multiple environments)
# XXX the above comment was from report.pl; could we now check such things?
def visit_default(node: Default, logger):
    info = info_func(node, logger)
    warning = warning_func(node, logger)
    debug = debug_func(node, logger)
    syntax = cast(Syntax, node.parent)
    param = cast(Parameter, syntax.parent)

    # 'mandatory' implies that the parameter is a command/event argument
    # XXX this is an INFO message for now, pending discussion
    if param.mandatory and syntax.default:
        info('mandatory argument parameter has a default')

    # 'parameter' defaults can only be used with command/event arguments
    if node.type == 'parameter' and \
            not node.command_in_path and not node.event_in_path:
        warning('parameter defaults can only be used in commands and events')

    # XXX should check that syntax.type is defined; if the XML is invalid, it
    #     might not be

    # list-valued parameters have comma-separated list defaults
    # XXX maybe should allow the list to be in '[]' brackets?
    # XXX may need to strip quotes from string values?
    if not syntax.list:
        values = [node.value]
    elif node.value == '':
        values = []
    else:
        # as specified in TR-106 Section 3.2.2, ignore whitespace before and
        # after commas, and also allow the value to be in square brackets,
        # e.g. '[ a , b ]' becomes ['a', 'b']
        value = re.sub(r'^\s*\[?\s*(.*?)\s*]?\s*$', r'\1', node.value)
        values = re.split(r'\s*,\s*', value)

    # each value has to be valid for its data type
    debug('%s : %s : %s default %r' % (syntax, syntax.format(human=True),
                                       node.type, node.value))
    for value in values:
        errors = []
        if not syntax.type.is_valid_value(value, errors=errors):
            # XXX it would be nice to indicate this in reports; how?
            warning('invalid %s default %s (%s)' % (
                node.type, value or r'<Empty>', ', '.join(errors)))
        elif re.search(r'<Empty>', value, re.IGNORECASE):
            warning('inappropriate %s default %s (should be an empty string)'
                    % (node.type, value))

        # XXX need to add 'is dynamic' logic, and review use of 'static'
        is_dynamic = False
        if is_dynamic and node.type == 'object':
            warning('parameter within static object has an object default')


def visit_enumeration_ref(enum_ref, logger):
    warning = warning_func(enum_ref, logger)

    # XXX need to improve the wording
    if not enum_ref.targetParamNode:
        warning('enumeration ref -> non-existent %r' % enum_ref.targetParam)


def visit_path_ref(path_ref: PathRef, logger) -> None:
    warning = warning_func(path_ref, logger)

    # XXX need to improve the wording
    if path_ref.targetParents and not path_ref.targetParentsNode:
        # XXX for now (pending a better solution) suppress the message if
        #     all the target parents start '.Services.' (this affects
        #     TR-135, which has some references to the TR-140 model)
        if not all(target.startswith('.Services.') for target in
                   path_ref.targetParents):
            warning('path ref -> non-existent %s' %
                    ', '.join(path_ref.targetParents))


def visit_profile(profile: Profile, logger) -> None:
    warning = warning_func(profile, logger)

    # check that the base profile exists
    if profile.base and not profile.baseNode:
        warning("profile base %s doesn't exist" % profile.base)

    # check that the extends profiles exist
    for i, extend_node in enumerate(profile.extendsNodes):
        if not extend_node:
            warning("profile extends %s doesn't exist" % profile.extends[i])

    # check for a mismatch between the profile status and item statuses
    # ('items_only' excludes, for example, profile descriptions)
    profile_status = profile.status_inherited
    items = [profile.baseNode] + profile.extendsNodes + \
            [item.refNode for item in profile.profile_expand(items_only=True)]
    # any Null or None items will have been reported elsewhere
    # XXX there shouldn't be any None items, but there can be
    bad_items = [item for item in items if item and
                 item.status_inherited > profile_status]
    if bad_items:
        max_status = max(item.status_inherited for item in bad_items)
        bad_paths = [item.objpath for item in bad_items]
        warning('is %s but should be %s because of %s' % (
            profile_status, max_status, ', '.join(bad_paths)))

    # check that this profile doesn't reduce the base profile's requirements
    # (use .baseNodeImplicit to include implicit base profiles)
    if base_profile := profile.baseNodeImplicit:
        # expand the base profile's and this profile's items
        # XXX arguably we shouldn't expand 'extends' but that would make things
        #     more complicated (will address this if/when needed)
        base_items = base_profile.profile_expand(
                base=True, extends=True, items_only=True)
        profile_items = profile.profile_expand(
                base=True, extends=True, items_only=True)

        # this maps referenced nodes to profile items; it's used for
        # associating the base profile's items with this profile's items
        ref_map = {ref_node: item for item in profile_items
                   if (ref_node := item.refNode)}

        # this is needed because .status_inherited inherits from the profile
        # XXX this probably doesn't cover all cases
        def item_status(item_: _ProfileItem) -> Status:
            return min(item_.status, item_.status_inherited)

        # XXX should use a Requirement class that supports comparison
        def reduced_requirement(old_req: Optional[str],
                                new_req: Optional[str]) -> bool:
            # note that command and event arguments have 'None' requirements
            req_map = {None: 1, 'notSpecified': 0, 'readOnly': 1, 'present': 1,
                       'readWrite': 2, 'create': 2, 'delete': 3,
                       'createDelete': 4}
            assert old_req in req_map and new_req in req_map, \
                '%s and/or %s not in %s' % (
                    old_req, new_req, list(req_map.keys()))
            return req_map[new_req] < req_map[old_req]

        # report missing and/or invalid items
        for base_item in base_items:
            # if the base profile is implicit, this profile only needs to
            # include items that are not "more deprecated" than the base
            # profile
            if not profile.base and item_status(base_item) > profile_status:
                pass

            # ignore non-existent referenced nodes
            elif not (ref_node := base_item.refNode):
                pass

            # check that this profile also references the base node
            elif not (item := ref_map.get(ref_node)):
                extra = ' (%s)' % base_item.requirement if \
                    base_item.requirement else ''
                warning('needs to reference %s%s' % (base_item, extra))

            # only ObjectRef and ParameterRef have requirements
            elif not isinstance(item, (ObjectRef, ParameterRef)):
                pass

            # check that the requirement hasn't been reduced
            elif reduced_requirement(base_item.requirement, item.requirement):
                warning('has reduced requirement (%s) for %s (%s)' % (
                    item.requirement, base_item, base_item.requirement))


def visit__profile_item(item: _ProfileItem, logger) -> None:
    warning = warning_func(item, logger)
    profile = item.profile_in_path

    # XXX ParameterRef is a profile item but is also used in unique keys, so
    #     return quietly if not within a profile
    if not profile:
        return

    # status defaults to 'current'; this tests for an explicit value
    item_status = item.status if item.status.defined \
        else item.status_inherited
    # XXX or perhaps we shouldn't test for an explicit value; see DMR-288,
    #     which might result in enabling this commented-out logic
    # item_status = item.status

    # check whether the item references a non-existent node
    if not (ref_node := item.refNode):
        warning("%s doesn't exist" % item.typename)

    # check for mismatch between item status and referenced node status
    # (it's OK for the profile item to be 'more deprecated')
    elif item_status < ref_node.status_inherited:
        # XXX python 3.9 doesn't permit this in an ':=' assignment expression
        #     so have to calculate it again
        ref_status = ref_node.status_inherited
        warning('is %s but should be %s' % (item_status, ref_status))
