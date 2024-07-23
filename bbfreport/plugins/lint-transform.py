"""Lint transform plugin."""

# Copyright (c) 2022-2024, Broadband Forum
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

from typing import cast, Optional, Union

from ..content import MacroRef
from ..macro import Macro
from ..node import _Base, Command, Component, DataType, DataTypeRef, Default, \
    _Dt_item, Enumeration, Event, _HasContent, _HasDescription, _HasRefType, \
    Model, _ModelItem, _Object, Object, Parameter, ParameterRef, PathRef, \
    Profile, _ProfileItem, Range, Root, _SignedNumber, Syntax, Template, \
    UniqueKey, Xml_file
from ..property import Null
from ..utility import StatusEnum, Utility, Version

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


# do nothing if --thisonly was specified
def _begin_(_, args) -> bool:
    return args.thisonly


def status_macro_helper(node: _HasDescription, macro_ref: MacroRef, *,
                        transitions, warning) -> None:

    # XXX it would be better to raise ValueError and let the caller report?
    transition = macro_ref.name
    errors = 0

    # check it has at least one argument (the version)
    if (num_args := len(macro_ref.args)) == 0:
        warning('{{%s}} version is empty' % transition)
        errors += 1

    # get the version (it should be a simple string)
    version = None
    if not macro_ref.args[0].is_simple:
        warning("%s version %s isn't a simple string" % (
            transition, macro_ref.args[0]))
        errors += 1

    # parse the version (it can specify a range)
    else:
        version_spec = macro_ref.args[0].text
        try:
            version = VersionRange(version_spec)
        except (AttributeError, ValueError) as e:
            warning('invalid {{%s}} version %r: %s' % (
                transition, version_spec, e))
            errors += 1

    # warn if this transition is invalid
    if transition > node.status:
        warning('is %s, so {{%s}} is invalid' % (node.status, transition))
        errors += 1

    # if there were no errors, update the transitions argument
    # XXX version could be None here; is this OK?
    if errors == 0 and transitions is not None:
        transitions[transition] = version

    # check that {{deprecated}} has a second argument (the reason)
    if transition == 'deprecated' and num_args == 1:
        warning('no reason for deprecation is given')


# TR-106 3.3 (Vendor-Specific Elements) and C.3.1 (Data Model Item Names)
# checks
# XXX should also apply these checks to enumeration values
def name_check_helper(node: Union[DataType, Component, Enumeration,
                                  _ModelItem], error, warning, *,
                      name_attr: str = 'name',
                      no_check_underscore: bool = False) -> None:
    # 3.3: the name of a vendor-specific parameter, object, command,
    # or event that is not contained within another vendor-specific object
    # MUST have the form: X_<VENDOR>_VendorSpecificName
    vendor_pattern = re.compile(r'''
        ^
        (?P<prefix>                             # prefix
            X_                                  # - initial
            (?:
                [0-9A-F]{6}                     # - upper-case OUI
            |                                   #   or
                [A-Za-z0-9]+(-[A-Za-z0-9]+)+    # - domain name with '.' -> '-'
            )
            _                                   # - terminator
        )
        (?P<rest>
            .*                                   # rest
        )
        $
    ''', re.VERBOSE)

    # C.3.1: all data model item names MUST start with an upper-case letter
    # (or an underscore for an internal data type, component, model or
    # profile)...
    # XXX TR-106 doesn't mention that this applies to command and event names
    # XXX TR-106 isn't clear that these rules apply after removing the prefix
    name_pattern_initial = re.compile(r'''
        ^
        [A-Z_]                      # initial character
    ''', re.VERBOSE)

    # ...and MUST NOT contain hyphens or non-initial underscores
    name_pattern_underscore = re.compile(r'''
        ^
        .                           # initial character (already checked)
        [^_-]*                      # no non-initial hyphen or underscore
        $
    ''', re.VERBOSE)

    # the dmr:noNameCheck attribute suppresses item name checks
    if node.dmr_noNameCheck:
        return

    # reported name attr omits leading 'h_' if present
    name_attr_reported = re.sub(r'^h_', '', name_attr)

    # item name; it's modified below if it's vendor-specific
    name = getattr(node, name_attr, None)
    if name is None:
        error('undefined %s attribute (perhaps the %s was never defined?)'
              % (name_attr_reported, node.typename))
        return

    # check the vendor-specific prefix
    if name.startswith('X_'):
        if not (match := vendor_pattern.match(name)):
            warning('%s has invalid vendor prefix' % name_attr_reported)
            return

        # extract the prefix and the rest of the name
        prefix = match['prefix']
        name = match['rest']

        # check for an unnecessary prefix
        # XXX should use a less simple-minded test
        if prefix in node.parent.objpath:
            warning('%s has unnecessary vendor prefix' % name_attr_reported)

    # check the name (but only if the name attr is 'name' or 'h_name';
    # enumeration values don't have to start with upper-case letters)
    if name_attr_reported == 'name':
        if not name_pattern_initial.match(name):
            warning("%s doesn't start with an upper-case letter" %
                    name_attr_reported)
        elif not no_check_underscore and \
                not name_pattern_underscore.match(name):
            warning("%s contains a hyphen or underscore" % name_attr_reported)


def visit__base(node: _Base, warning, info):
    def all_versions(nod: _Base,
                     vers: Optional[list[Version]] = None) -> list[Version]:
        if vers is None:
            vers = []
        if nod.version is not None:
            # it might already be there, but this doesn't matter
            vers.append(nod.version)
        if isinstance(nod.h_parent, _Base):
            all_versions(nod.h_parent, vers)
        return vers

    model = node.model_in_path
    if node.version is not None:
        versions = all_versions(node)
        # XXX this is wrong but I guess it's a stronger check; needs thought
        #     it was: if sorted(versions, reverse=True) != versions:
        if node.version < max(versions):
            warning('version %s < inherited %s' % (
                node.version, max(versions)))

        if model and node.version > model.model_version:
            warning("version %s > model version %s" % (
                node.version, model.model_version))

        # XXX the earlier node.version < max(versions) check is more general
        #     than this one, so will demote this to info() pending deletion
        parent_version = node.h_parent.h_version_inherited
        if parent_version and node.version < parent_version:
            info('version %s < parent version %s' % (
                node.version, parent_version))

        # don't warn for objects and profiles, because version is mandatory
        # XXX this is flawed, because we'll want to do this with --thisonly,
        #     but we don't do lint checks with --thisonly!; will need to
        #     create an interim file? (for now, report at info level)
        if parent_version and not isinstance(node, (Object, Profile)):
            if node.version == parent_version:
                info('version %s is unnecessary' % node.version)


# this was visit__has_status(); everything now has status
# XXX if a node has no description element, node.description will be Null and
#     there'll be no Description object, and so no Content object to auto-add
#     macro-references to; maybe elements should be more like attributes, and
#     should be instantiated on reference? or just require a description
#     element (and sometimes allow it to be empty)
def visit__has_description(node: _HasDescription, warning):
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

    # some vendor models use versions such as to 2.1601 to indicate that
    # they're derived from 2.16, so convert such versions to the original
    # for the checks below
    if model_version is not None:
        major, minor, *patch = model_version.comps
        if minor >= 1000:
            model_version = Version((major, minor // 100, *patch))

    # allow profiles and their children not to have descriptions
    content = node.description.content
    if node.profile_in_path and not content:
        return

    # check the status-related macro references that are present in the
    # description
    # XXX no, here we should just collect the transitions; macro-level
    #     warnings should be output by macro expansion
    transitions = {}
    for status in StatusEnum.values:
        if status in content.macro_refs:
            macro_refs = content.macro_refs[status]
            if (num_macro_refs := len(macro_refs)) > 1:
                warning('has %d {{%s}} macro references' % (
                    num_macro_refs, status))
            else:
                status_macro_helper(node, macro_refs[0],
                                    transitions=transitions, warning=warning)

    # check that the appropriate status macro reference is present (we only
    # require the current status's macro, e.g., we wouldn't require
    # {{deprecated}} for an obsoleted node; also, profiles are exempt)
    if not node.profile_in_path and node.status.value != StatusEnum.default \
            and node.status.value not in transitions:
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
        elif node.status.value == to_status and model_version < expected_ver:
            warning("was %s at %s and shouldn't be %s until %s" % (
                 from_status, from_ver_first, to_status, expected_ver))
            warnings += 1

        # check for a late (overdue) transition
        elif node.status.value == from_status and \
                model_version >= expected_ver:
            be = 'have been' if expected_ver < model_version else 'be'
            warning("was %s at %s and should %s %s at %s" % (
                 from_status, from_ver_first, be, to_status, expected_ver))
            warnings += 1

    # check for newly-added nodes that have already been deprecated
    if model_version is not None and node.version_inherited >= \
            model_version and node.status > StatusEnum.default:
        warning("is new (added in %s) so it shouldn't be %s" % (
            node.version_inherited, node.status))


# XXX this check would be better on Parameter?
def visit__has_ref_type(has_ref_type: _HasRefType, warning):
    node = cast(_Base, has_ref_type)  # _HasRefType is a mixin class
    if has_ref_type.refType == 'weak' and not node.command_in_path and not \
            node.event_in_path and node.parameter_in_path.access == 'readOnly':
        warning('weak reference parameter is not writable')


# note that we can assume that visit__has_status() has been called before this
# is called, e.g., for a parameter (which 'has status') visit_has_status() will
# be called and then its children will be visited, one of which is its
# description (which 'has content')
def visit__has_content(node: _HasContent, args, error, warning, info, debug):
    if (args.all or node.is_used is not False) \
            and node.content.markdown is None:
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


def visit_data_type(data_type: DataType, error, warning):
    # name checks are only done for non-primitive named data types
    if data_type.name is not None and \
            data_type.name not in data_type.primitive_types:
        # some data type names include underscores
        name_check_helper(data_type, error, warning, no_check_underscore=True)

    # check for signed types that could be unsigned
    if data_type.name is not None and isinstance(data_type.primitive_inherited,
                                                 _SignedNumber) and (
            ranges := data_type.ranges_inherited):
        # .ranges_inherited can also return DecimalRange instances
        if all(isinstance(rng, Range) for rng in ranges):
            # this cleans overlapping ranges and sorts the ranges
            clean_ranges = cast(list[Range], Range.prange_clean(ranges))
            minval = clean_ranges[0].minInclusive
            if minval is not None and minval >= 0:
                warning('minimum value is %d, so it could be unsigned' %
                        minval)

    # check for missing {{units}} macros, which are only required on base types
    if (units := data_type.units_inherited) and not data_type.baseNode:
        # the description is on the containing parameter, or the data type
        owner = data_type.parameter_in_path or cast(DataType, data_type)
        if not owner.dmr_noUnitsTemplate and \
                ('units', 0) not in owner.description.content.macro_refs:
            warning('units %s but no {{units}} macro' % units.value)


def visit_component(component: Component, error, warning) -> None:
    name_check_helper(component, error, warning)


# this is currently only called for DM models
def visit_model(model: Model, error) -> None:
    # first check the XML file name
    # noinspection PyTypeChecker
    xml_file = model.instance_in_path(
            Xml_file, predicate=lambda n: isinstance(n.parent, Root))
    cwmp_file = str(xml_file).endswith('-cwmp')

    # next check for commands and events
    commands_and_events = model.findall(Command) + model.findall(Event)

    # CWMP file with commands and events is an error
    if cwmp_file and commands_and_events:
        error('CWMP model defines commands and/or events %s' %
              Utility.nicer_list([n.objpath for n in commands_and_events]))


def visit__model_item(node: _ModelItem, error, warning) -> None:
    # for objects, only check the final name component
    name_attr = 'h_name' if isinstance(node, _Object) else 'name'
    # some profile names include underscores
    no_check_underscore = isinstance(node, Profile)
    name_check_helper(node, error, warning, name_attr=name_attr,
                      no_check_underscore=no_check_underscore)


def visit_object(obj: Object, warning) -> None:
    # determine whether this is a USP model
    usp = obj.model_in_path.usp
    ignore_enable_parameter = usp

    # don't check anything for deleted objects
    if obj.status.value == 'deleted':
        return

    # various object attributes
    is_writable, is_multi, is_fixed, is_union = \
        obj.is_writable, obj.is_multi, obj.is_fixed, obj.is_union

    # find the containing command or event (if any)
    command_or_event = obj.command_in_path or obj.event_in_path

    # simple checks
    if is_writable and obj.maxEntries == 1:
        warning('object is writable but is not a table')

    if is_writable and is_multi and is_fixed:
        warning('fixed size table is writable')

    if is_multi and not obj.objpath.endswith('.{i}.'):
        warning('object is a table but name doesn\'t end with ".{i}."')

    if not is_multi and obj.objpath.endswith('.{i}.'):
        warning('object is not a table but name ends with ".{i}."')

    if not is_multi and obj.uniqueKeys:
        warning('object is not a table but has a unique key')

    if not (is_writable and is_multi) and obj.enableParameter:
        warning('object is not writable and multi-instance but has '
                'enableParameter')

    if obj.enableParameter and not obj.enableParameterNode:
        warning("enableParameter %s doesn't exist" % obj.enableParameter)

    # numEntries parameter checks:
    if not obj.numEntriesParameter:
        if is_multi and not is_fixed and not command_or_event:
            warning('missing numEntriesParameter')
    elif not is_multi:
        warning('object is not multi-instance but has numEntriesParameter '
                '%s' % obj.numEntriesParameter)
    elif not (num_entries_parameter := obj.numEntriesParameterNode):
        warning('non-existent numEntriesParameter %s' %
                obj.numEntriesParameter)
    else:
        name_or_base = obj.h_name or obj.h_base
        expected = name_or_base.replace('.{i}.', '') + 'NumberOfEntries'
        if num_entries_parameter.name != expected and not \
                num_entries_parameter.dmr_customNumEntriesParameter:
            warning('numEntriesParameter %s should be named %s' % (
                num_entries_parameter.name, expected))

        if num_entries_parameter.is_writable:
            warning('numEntriesParameter %s is writable' %
                    num_entries_parameter.name)

        if num_entries_parameter.version_inherited != \
                obj.version_inherited:
            warning('version is %s but %s version is %s' %
                    (obj.version_inherited, num_entries_parameter.name,
                     num_entries_parameter.version_inherited))

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

        if obj.dmr_noUniqueKeys:
            warning('object has unique keys, so dmr:noUniqueKeys is '
                    'inappropriate')

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
    if obj.mountType and obj.mountType.value in {'none', 'mountable'}:
        warning('deprecated mount type %s' % obj.mountType)


def visit__dt_item(item: _Dt_item, error):
    if item.refNode is Null:
        error("doesn't exist and will be ignored")
        item.mark_unused()


def visit_parameter(param: Parameter, warning) -> None:
    syntax = param.syntax

    # XXX report.pl has a 'writable parameter in read-only table' warning, but
    #     this isn't necessarily a problem and is output at level 2

    # don't warn about Alias parameters if they're deprecated
    if param.status.value == StatusEnum.default and \
            param.name == 'Alias' and isinstance(param.parent, _Object):
        obj = cast(Object, param.parent)
        if not obj.is_multi:
            warning('Alias parameter in single-instance object')
        elif not param.uniqueKeyNodes:
            warning('Alias parameter is not a unique key')

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

    # check for signed types that could be unsigned (but only for parameters
    # added in the current model version)
    if param.version_inherited < param.model_in_path.model_version:
        pass
    elif not isinstance(syntax.type, _SignedNumber):
        pass
    elif ranges := syntax.ranges_inherited:
        # .ranges_inherited can also return DecimalRange instances
        if all(isinstance(rng, Range) for rng in ranges):
            # this cleans overlapping ranges and sorts the ranges
            clean_ranges = cast(list[Range], Range.prange_clean(ranges))
            minval = clean_ranges[0].minInclusive
            if minval is not None and minval >= 0:
                warning('minimum value is %d, so it could be unsigned' %
                        minval)


def visit_enumeration(enumeration: Enumeration, error, warning):
    name_check_helper(enumeration, error, warning, name_attr='value')


# XXX doesn't complain about defaults in read-only objects or tables; this is
#     because they are quietly ignored (this is part of allowing them in
#     components that can be included in multiple environments)
# XXX the above comment was from report.pl; could we now check such things?
def visit_default(node: Default, warning, info, debug):
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
    debug('%s : %s : %s default %r' % (syntax, syntax.format(human=True),
                                       node.type, node.value))

    # list-valued parameters' defaults must be in '[]' brackets, and non
    # list-valued parameters' defaults shouldn't be in '[]' brackets
    # XXX a string parameter should be able to have a default of '[value]';
    #     this can be added as an exception later on if need be
    value = node.value
    bracketed = re.match(r'^\s*\[\s*(.*?)\s*]\s*$', value)
    if bool(bracketed) != bool(syntax.list):
        extra = "lists must be bracketed" if syntax.list else \
            "scalars mustn't be bracketed"
        warning('invalid %s default %s (%s)' % (
            node.type, Utility.nice_string(value), extra))

    # if bracketed, discard the brackets
    if bracketed:
        value = bracketed[1]

    # list-valued parameters have comma-separated list defaults
    # XXX maybe should allow the list to be in '[]' brackets?
    # XXX may need to strip quotes from string values?
    if not syntax.list:
        values = [value]
    elif value == '':
        values = []
    else:
        # as specified in TR-106 Section 3.2.2, ignore whitespace before and
        # after commas
        values = re.split(r'\s*,\s*', value)

    # each value has to be valid for its data type
    for value in values:
        errors = []
        if not syntax.type.is_valid_value(value, errors=errors):
            # XXX it would be nice to indicate this in reports; how?
            warning('invalid %s default %s (%s)' % (
                node.type, Utility.nice_string(value), ', '.join(errors)))
        elif re.search(r'<Empty>', value, re.IGNORECASE):
            warning('inappropriate %s default %s (should be an empty string)'
                    % (node.type, Utility.nice_string(value)))

    if node.type == 'object':
        # noinspection PyTypeChecker
        multi_ancestor = node.instance_in_path(_Object,
                                               lambda obj: obj.is_multi,
                                               hierarchical=True)
        if not multi_ancestor:
            warning('parameter within static object has an object default')
        elif multi_ancestor.access == 'readOnly':
            warning('parameter within read-only object has an object default')


def visit_enumeration_ref(enum_ref, warning):
    # XXX need to improve the wording
    if not enum_ref.targetParamNode:
        warning('enumeration ref -> non-existent %r' % enum_ref.targetParam)


def visit_path_ref(path_ref: PathRef, warning) -> None:
    # XXX need to improve the wording
    if path_ref.targetParents and not path_ref.targetParentsNode:
        # XXX for now (pending a better solution) suppress the message if
        #     all the target parents start '.Services.' (this affects
        #     TR-135, which has some references to the TR-140 model)
        if not all(target.startswith('.Services.') for target in
                   path_ref.targetParents):
            warning('path ref -> non-existent %s' %
                    ', '.join(path_ref.targetParents))


def visit_profile(profile: Profile, warning) -> None:
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
        def item_status(item_: _ProfileItem) -> StatusEnum:
            return min(item_.status, item_.status_inherited)

        # XXX should use a Requirement class that supports comparison
        # report missing and/or invalid items
        for base_item in base_items:
            # ignore non-existent referenced nodes
            # XXX this is checked elsewhere, yes? should verify this
            if not (ref_node := base_item.refNode):
                pass

            # if the base profile is implicit, this profile only needs to
            # include items that are not "more deprecated" than the base
            # profile
            elif not profile.base and (
                    item_status(base_item) > profile_status or
                    ref_node.status_inherited > profile_status):
                pass

            # check that this profile also references the base node
            elif not (item := ref_map.get(ref_node)):
                extra = ' (%s)' % base_item.requirement if \
                    base_item.requirement else ''
                warning('needs to reference %s%s' % (ref_node.objpath, extra))

            # check that the requirement hasn't been reduced
            elif base_item.requirement and item.requirement and \
                    item.requirement < base_item.requirement:
                warning('has reduced requirement (%s) for %s (%s)' % (
                    item.requirement, ref_node.objpath, base_item.requirement))


def visit__profile_item(item: _ProfileItem, warning) -> None:
    profile = item.profile_in_path

    # XXX ParameterRef is a profile item but is also used in unique keys, so
    #     return quietly if not within a profile
    if not profile:
        return

    # check whether the item references a non-existent node
    if not (ref_node := item.refNode):
        warning("%s doesn't exist" % item.typename)
        return

    # check for mismatch between item access and referenced node access
    # (it's OK for the profile item to have a 'lower access')
    # (some node types have access == None or requirement == None)
    # XXX difflint should also check for valid access and requirement
    #     transitions
    if item.requirement and ref_node.access and \
            item.requirement > ref_node.access:
        warning('requirement %s exceeds %s' % (
            item.requirement, ref_node.access))

    # check for mismatch between item status and referenced node status
    # (it's OK for the profile item to be 'more deprecated')
    # XXX arguably .status_inherited should include the .defined check
    item_status = item.status if item.status.defined \
        else item.status_inherited
    ref_status = ref_node.status if ref_node.status.defined \
        else ref_node.status_inherited
    if item_status < ref_status:
        warning('status is %s but should be %s' % (
            item_status, ref_status))
