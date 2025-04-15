"""All macro definitions (could split up into multiple modules).

Expanded macros are BBF-flavor markdown (TBD) strings.

Note::

    * Expanded text uses markdown ``*text*`` rather than mediawiki
      ``''text''`` etc. (should convert mediawiki-style markup?)
"""

# Copyright (c) 2022-2025, Broadband Forum
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

import re

from typing import Any, cast, Union

from ..content import CLOSE_DIV, Content, OPEN_DIV
from ..exception import MacroException
from ..macro import Macro, MacroRef
from ..node import AbbreviationsItem, DataType, DataTypeAccessor, \
    EnumerationRef, GlossaryItem, _HasContent, InstanceRef, _Number, Object, \
    Parameter, PATH_QUIET, PathRef, Profile, Range, Reference, Syntax, \
    Template, typename, _ValueFacet
from ..path import follow_reference
from ..property import Null
from ..utility import ScopeEnum, StatusEnum, Utility


# can change this while debugging
MACROS_PATH_QUIET = PATH_QUIET

# XXX should decide whether to subclass; it's simpler not to...

# XXX should use libraries, e.g., for anchor/link names

# XXX should use a standard mechanism for indicating invalid links; CSS?

# XXX should try to make everything type-safe, e.g., avoid use of typename

# XXX if parameter.syntax etc. can be known to be a Syntax instance then
#     could avoid many explicit casts

# XXX the newline and start-of-sentence logic needs to be added.

# XXX should use f'' formatting more? but use it consistently

# XXX report.pl implements some additional undocumented macros, e.g.
#     {{div}}, {{span}}, {{sub}} and {{sup}}; do we want to (a) get rid of
#     them, (b) convert them to markdown or (c) leave them for later
#     language-specific processing?


# macro expansion functions:
# - on error, raise MacroException (preferred), return None (deprecated),
#   return str, or return Content if the expansion might contain macro
#   references and should be re-expanded

# core utilities are declared first

NodeType = type['Node']


# like cast() but raises MacroException if the node isn't of the specified type
# XXX this doesn't give the type safety that we'd like; need to use generics?
# XXX would like a tuple version of this for when the node can be of one of
#     several types? (but should use the class hierarchy for this)
def cast_node(node_type_or_types: Union[NodeType, tuple[NodeType, ...]],
              node: NodeType, *, prefix: str = '') -> NodeType:
    node_types = node_type_or_types \
        if isinstance(node_type_or_types, tuple) else (node_type_or_types,)
    if not isinstance(node, node_types):
        sep = ' ' if prefix else ''
        typenames = Utility.nicer_list([typename(nt).lstrip('_') for nt in
                                        node_types])
        raise MacroException('%s%sonly valid in %s (not in %s) descriptions'
                             % (prefix, sep, typenames, node.typename))
    return node


# find and then cast a node; raises MacroException if not found, or wrong type
def find_node(node_type: NodeType, *key, prefix: str = '') -> NodeType:
    assert len(key) > 0
    if not (node := node_type.find(node_type, *key)):
        raise MacroException('non-existent %s' % key[-1])
    return cast_node(node_type, node, prefix=prefix)


# there are cases where markdown might not have been generated, or might
# have been generated for the wrong node, e.g.
# - parameter descriptions are processed before their syntax elements, so
#   enumeration value description markdown won't yet have been generated
# - {{datatype|expand}} will have been expanded in the context of the data type
#   rather than in the context of the parameter
# XXX see also lint.visit__has_content(), which has similar logic; this
#     should be hidden in a utility (where?)
def get_markdown(content: Content, *, node, force: bool = False,
                 **kwargs) -> str:
    markdown = ''
    if content:
        markdown = content.markdown or ''
        if force or not markdown:
            markdown = Macro.expand(content, node=node, **kwargs)

    return markdown


def get_markdown_and_tidy(content: Content, **kwargs) -> str:
    markdown = get_markdown(content, **kwargs)

    # suppress tidy-up if the markdown ends with '\n:::' (a fenced div)
    # XXX also need the leading '\n\n'
    # XXX this is a hack; need a cleaner solution
    if markdown.endswith('\n:::'):
        markdown = '{{np}}' + markdown + '{{np}}'
    else:
        # replace newlines with single spaces
        markdown = re.sub(r'\n+', ' ', markdown)

        # remove trailing period (if present)
        markdown = re.sub(r'\.$', '', markdown)

    return markdown


# filter out known keyword arguments
def unknown_kwargs(**kwargs) -> dict[str, Any]:
    return {n: v for n, v in kwargs.items() if
            n not in {'macro', 'node', 'active', 'error', 'warning', 'info',
                      'debug'}}


# helpers are declared next

# the returned text can include a macro references, so the caller should
# return a Content object
def maybe_empty(text: str) -> str:
    return '{{empty}}' if text == '' else '*%s*' % text


def expand_itemref(ref, scope_or_status, *, node, stack, warning,
                   **_kwargs) -> str:
    def nameonly(nod) -> str:
        return nod.h_nameonly if isinstance(nod, Object) else nod.name

    macro = stack[-1]
    assert macro.name in {'command', 'event', 'param', 'object'}

    # map macro name to element name
    macro_to_elemname = {'param': 'parameter'}
    elemname = macro_to_elemname.get(macro.name, macro.name)

    # separate out scope and status
    # XXX should make better use of the ScopeEnum and StatusEnum classes
    scope = scope_or_status if scope_or_status in {
        'normal', 'model', 'object', 'absolute'} else 'normal'
    status = StatusEnum(scope_or_status if scope_or_status in StatusEnum.values
                        else node.status_inherited.value)

    # warn if the reference has leading and/or trailing whitespace
    if ref != ref.strip():
        warning('{{%s}}: argument %r has leading and/or trailing whitespace'
                % (macro.name, ref))
        ref = ref.strip()

    # if not within a model, don't attempt to follow the reference
    if not node.model_in_path:
        return "*%s*" % (ref or elemname,)

    # if there's no reference, it's a reference to the current item
    if ref == '':
        item = node.instance_in_path(elemname)
        if not item:
            raise MacroException('empty ref only valid in %s descriptions' %
                                 elemname)
        if item is node.parent:
            return "*%s*" % nameonly(item)
        else:
            return "[*%s*](#%s)" % (nameonly(item), item.anchor)

    # otherwise follow the reference
    ref_node = follow_reference(node, ref, scope=scope,
                                quiet=MACROS_PATH_QUIET)
    if not ref_node:
        raise MacroException('non-existent %s' % ref)
    elif ref_node.elemname != elemname:
        ref_node = follow_reference(node, ref, scope=scope,
                                    quiet=MACROS_PATH_QUIET)
        raise MacroException('referenced %s is %s, not %s' % (
            ref, ref_node.elemname, elemname))
    elif ref_node is node.parent:
        raise MacroException('argument unnecessary when referring to '
                             'current %s' % elemname)

    # check that the referenced item is not "more deprecated" than this node
    if ref_node.status_inherited > status:
        raise MacroException('reference to %s %s %s' % (
            ref_node.status_inherited, ref_node.typename,
            ref_node.objpath))

    # remove leading hashes and dots from the reference; if this gives an
    # empty string, e.g., {{object|#}}, use the actual name
    ref = re.sub(r'^#*\.*', '', ref)
    if ref == '':
        ref = nameonly(ref_node)
    return "[*%s*](#%s)" % (ref, ref_node.anchor)


# behavior depends on the arguments:
# - no arguments: call expand_values() to expand all the current data type's
#   or parameter's values (enumerations or patterns)
# - arguments: reference the specified value, belonging to this or another
#   parameter
def expand_value(value, param, scope_or_status, *, node, stack, args,
                 **kwargs) -> Union[str, Content]:
    macro = stack[-1]
    assert macro.name in {'enum', 'pattern'}
    cast(Any, args)

    # if the value argument is empty, the param argument must also be empty
    if value == '' and param != '':
        raise MacroException('empty value but non-empty param')

    # separate out scope and status
    # XXX should make better use of the ScopeEnum and StatusEnum classes
    scope = scope_or_status if scope_or_status in {
        'normal', 'model', 'object', 'absolute'} else 'normal'
    status = StatusEnum(scope_or_status if scope_or_status in StatusEnum.values
                        else node.status_inherited.value)

    # if not within a model, the node should be a data type description
    if not node.model_in_path:
        # the owner of the values is the DataType object
        owner = cast_node(DataType, node.parent)
        owner_type = 'data type'
        owner_name = owner.name

    # if within a model, find the current or referenced parameter
    else:
        if param == '':
            parameter = node.parameter_in_path
            if not parameter:
                raise MacroException('empty param arg only valid in parameter '
                                     'descriptions')
        else:
            parameter = follow_reference(node, param, scope=scope, quiet=True)
            if not parameter:
                raise MacroException('non-existent %s' % param)

        # if it's an enumerationRef, replace it with the referenced parameter
        if enumeration_ref := parameter.syntax.string.enumerationRef:
            if not enumeration_ref.targetParamNode:
                raise MacroException('non-existent enumerationRef parameter '
                                     '%s' % enumeration_ref.targetParam)
            parameter = enumeration_ref.targetParamNode

        # the owner of the values is the parameter's Syntax object
        owner = parameter.syntax
        owner_type = 'parameter'
        owner_name = parameter.name

    # check that it defines values
    if not (values := owner.values):
        raise MacroException(
            "%s %s doesn't define any values" % (owner_type, owner_name))

    # if the value argument is empty, list all the values
    if value == '':
        return expand_values(values, owner=owner, stack=stack, **kwargs)

    # otherwise, check that it defines the specified value, that it's not
    # "more deprecated" than this node, and reference it
    else:
        # XXX until content is normalized, there might be line breaks within
        #     values, so replace them with spaces
        value = value.replace('\n', ' ')
        if value not in values:
            raise MacroException("non-existent %s" % value)

        value_node = values[value]
        if value_node.status_inherited > status:
            raise MacroException('reference to %s %s %s.%s' % (
                value_node.status_inherited, value_node.typename,
                value_node.objpath, value))

        style = '*' if macro.name == 'enum' else '`'
        return "[%s%s%s](#%s)" % (style, value, style, values[value].anchor)


# this is called by expand_value()
def expand_values(values: dict[str, _ValueFacet], *, owner, stack, warning,
                  **kwargs) -> Content:
    macro = stack[-1]

    # this is only valid if this macro was called from {{div}}
    # XXX this test needs to be cleverer, because {{inserted}} can be in
    #     stack when reporting differences
    if len(stack) < 2 or (caller := stack[-2]).name != 'div':
        raise MacroException('only valid as {{div}} argument')

    # {{div}}'s second argument is its content; if it includes a {{li}}
    # (list item) macro then we need to insert a paragraph break; otherwise
    # insert just a space, or nothing if no text has been generated so far
    # XXX this is a heuristic. The idea is that if there's a list then this
    #     text must be in a new paragraph
    assert len(caller.args) > 1  # safe, because it calls this macro!
    content = caller.args[1]
    text = '{{np}}' if any(
            isinstance(item, MacroRef) and item.name == 'li' for item in
            content.items) else '{{ns}}'

    text += \
        ('Each list item is an enumeration of:' if owner.list else
         'Enumeration of:') if macro.name == 'enum' else \
        ('Each list item matches one of:' if owner.list else
         'Possible patterns:')
    text += '{{np}}'

    for key, value in values.items():
        # XXX this is tricky; the supplied warning is bound to node, so
        #     messages won't indicate the value; this prefixes the
        #     value (it would be nice to have a way of inserting it or
        #     (better?) overriding the node
        my_warning = lambda txt: warning('%s: %s' % (value.value, txt))

        # not value.description because the description may be inherited
        description = owner.value_description(value)
        content = description.content

        # empty key is reported as '<Empty>', with default '{{empty}}' content
        empty = '<Empty>'
        if key == '':
            key = empty
            if not content:
                content = Content('{{empty|nocapitalize}}')
        # enums are italicized with escaped angle brackets; patterns are
        # verbatim
        if macro.name != 'enum' and key != empty:
            style = '`'
        else:
            style = '*'
            key = re.sub(r'([<>])', r'\\\1', key)
        text += '* [%s%s%s]{#%s}' % (style, key, style, value.anchor)

        # process the description
        markdown = get_markdown_and_tidy(
                content, node=description, stack=stack,warning=my_warning,
                **kwargs)

        # items will be concatenated with comma separators
        items = [markdown] if markdown else []

        # read-only?
        if value.access == 'readOnly':
            items.append('READONLY')

        # optional?
        if value.optional:
            items.append('OPTIONAL')

        # deprecated etc.? (not included if the corresponding macro is present)
        status_value = value.status.value
        if status_value != 'current' and \
                status_value not in content.macro_refs:
            items.append(status_value.upper())

        # explicit version?
        if value.version:
            added = 'Added' if not items else 'added'
            items.append('%s in %s' % (added, value.version))

        # concatenate items to generate the final markdown
        markdown = ', '.join(items)

        # append the final markdown, if there is any
        text += ' (%s)' % markdown if markdown else ''
        text += '{{nl}}'

    return Content(text)


# the remainder are defined in alphabetical order for ease of reference

# noinspection PyShadowingBuiltins
def expand_abbref(id, *, node, **_kwargs) -> str:
    item = find_node(AbbreviationsItem, id) if id \
        else cast_node(AbbreviationsItem, node.parent)
    text = '*%s*' % item.id
    if item is not node.parent:
        text = '[%s](#%s)' % (text, item.anchor)
    return text


def expand_access(node, **_kwargs) -> str:
    parameter = cast_node(Parameter, node.parent)
    access = parameter.access
    if access == 'writeOnceReadOnly':
        return "Once it's been set, this parameter is immutable."
    else:
        return ''


# noinspection PyShadowingBuiltins
def expand_bibref(id, section, **_kwargs) -> str:
    # XXX unfortunately some IDs contain spaces, and so can get broken across
    #     two lines
    bibref = find_node(Reference, re.sub(r'\s+', ' ', id))
    section_ = ''
    if section:
        prefix = 'Section ' if re.match(r'\d', section) else ''
        section_ = '%s%s/' % (prefix, Utility.upper_first(section))
    return '[[%s%s](#%s)]' % (section_, bibref.id, bibref.anchor)


def expand_command(ref, scope_or_status, *, node, **_kwargs) -> \
        Union[str, Content]:
    # handle the legacy 'command parameter' case
    if ref == '' and isinstance(node.parent, Parameter) and \
            node.parent.syntax.command:
        return Content('The value of this parameter is not part of the '
                       'device configuration and is always {{null}} when '
                       'read.')

    return expand_itemref(ref, scope_or_status, node=node, **_kwargs)


# XXX what if the data type uses base? need a proper solution
def expand_datatype(arg, *, node: _HasContent, **kwargs) -> Content:
    parameter = cast_node(Parameter, node.parent)
    if not (data_type_ref := parameter.syntax.dataType):
        raise MacroException('parameter is not of a named data type')
    if not (name_and_data_type := DataTypeAccessor.entities.get(
            data_type_ref.base)):
        raise MacroException('non-existent %s' % data_type_ref)

    _, data_type = name_and_data_type
    data_type.mark_used()
    text = '[[%s](#%s)]' % (data_type.name_public, data_type.anchor)

    # XXX there might be other places where .description should be changed to
    #     .description_inherited; in this case it was needed for a data type
    #     that inherited its description from a base type
    description = data_type.description_inherited
    if arg == 'expand' and (markdown := get_markdown(
            description.content, node=parameter.description, force=True,
            noauto=True, **kwargs)):
        text += ' %s' % markdown

    return Content(text)


def expand_diffs(node, diffs, **_kwargs) -> Content:
    this_model = node.model_in_path
    all_models = [model for model in node.findall('model')
                  if str(model) == str(this_model)]
    first_model = all_models[0] if len(all_models) > 0 else None
    version = first_model.model_version \
        if first_model and first_model is not this_model else None

    # noinspection PyListCreation
    chunks = []
    chunks.append(OPEN_DIV)
    chunks.append('{{div|diffs|')
    chunks.append('**Changes since %s:**' % version if version else
                  '**Changes:**')
    for i, diff in enumerate(diffs):
        chunks.append('{{np}}' if i == 0 else '{{nl}}')
        chunks.append('* %s' % diff)
    chunks.append(CLOSE_DIV)
    chunks.append(CLOSE_DIV)
    return Content(''.join(chunks))


def expand_div(classes: str, text: str, stack: list[MacroRef],
               **_kwargs) -> Union[str, Content]:
    if not text:
        return ''
    elif not classes:
        return Content('{{np}}%s' % text)
    else:
        # XXX derive the number of colons from the div nesting depth to work
        #     around a markdown-it bug that requires outer divs to use more
        #     colons than nested than inner divs; also use nine colons for
        #     removed/inserted text: see removed_or_inserted()
        div_depth = len([entry for entry in stack if entry.name == 'div'])
        assert div_depth > 0
        colons = ':' * (9 - div_depth)
        class_lst = classes.split()
        class_str = class_lst[0] if len(class_lst) == 1 else \
            '{%s}' % ' '.join('.%s' % cls for cls in class_lst)
        return Content('{{np}}%s %s\n%s\n%s' % (
            colons, class_str, text, colons))


def expand_empty(style: str, chunks, **_kwargs) -> str:
    if style not in {'nocapitalize', 'capitalize', 'default'}:
        raise MacroException('invalid style %s' % style)

    if style == 'nocapitalize':
        capitalize = False
    elif style == 'capitalize':
        capitalize = True
    else:
        so_far = ''.join(chunk for lst in chunks for chunk in lst).strip()
        capitalize = so_far == '' or re.search(r'[.!?]$', so_far)

    initial = 'A' if capitalize else 'a'
    return '%sn empty string' % initial


def expand_entries(*, node, **_kwargs) -> str:
    obj = cast_node(Object, node.parent)
    is_multi, is_fixed, is_union = \
        obj.is_multi, obj.is_fixed, obj.is_union
    min_entries, max_entries = obj.minEntries, obj.maxEntries

    # union rules
    # XXX note that (minEntries, maxEntries) = (0, 1) is NOT regarded as
    #     "multi"; it's too hard to generate sensible text in this case so
    #     we don't try
    # XXX report.pl has a --showunion option
    if is_union:
        return 'This object is a member of a union, i.e., it is a member of ' \
               'a group of objects of which only one can exist at a given ' \
               'time.'

    # (minEntries, maxEntries) constraints
    label = lambda val: \
        'entries' if isinstance(val, str) or val > 1 else 'entry'
    if min_entries == 0 and max_entries == 'unbounded':
        # don't say anything in the common (0,unbounded) case
        text = ''
    elif is_fixed:
        text = 'This table MUST contain exactly %s %s.' % (
            min_entries, label(min_entries))
    elif max_entries == 'unbounded':
        text = 'This table MUST contain at least %s %s.' % (
            min_entries, label(min_entries))
    else:
        text = 'This table MUST contain at least %s and at most %s %s.' % (
            min_entries, max_entries, label(max_entries))

    # if this is a command or event argument table, indicate that the instance
    # numbers must be 1, 2, ...
    if obj.command_in_path or obj.event_in_path:
        if text != '':
            text += ' '
        text += "This table's Instance Numbers MUST be 1, 2, 3... " \
                "(assigned sequentially without gaps)."

    return text


def expand_factory(*, node, **_kwargs) -> Content:
    parameter = cast_node(Parameter, node.parent)
    if not parameter.syntax.default or \
            parameter.syntax.default.type != 'factory':
        raise MacroException('factory default not specified')
    return Content('The factory default value MUST be %s.' %
                   maybe_empty(parameter.syntax.default.value))


# noinspection PyShadowingBuiltins
def expand_gloref(id, *, node, **_kwargs) -> str:
    item = find_node(GlossaryItem, id) if id \
        else cast_node(GlossaryItem, node.parent)
    text = '*%s*' % item.id
    if item is not node.parent:
        text = '[%s](#%s)' % (text, item.anchor)
    return text


def expand_hidden(value, **_kwargs) -> Content:
    return Content('When read, this parameter returns %s, regardless of the '
                   'actual value.' % value)


def expand_impldef(*, node, **_kwargs) -> Content:
    parameter = cast_node(Parameter, node.parent)
    if not parameter.syntax.default or \
            parameter.syntax.default.type != 'implementation':
        raise MacroException('implementation default not specified')
    return Content('The default value SHOULD be %s.' %
                   maybe_empty(parameter.syntax.default.value))


def expand_inform(node, **_kwargs) -> str:
    parameter = cast_node(Parameter, node.parent)
    inform = parameter.forcedInform
    usp = parameter.model_in_path.usp
    return '' if usp or not inform else \
        'This parameter MUST always be included in Inform messages.'


def expand_issue(descr_or_opts: str, descr: None, **_kwargs) -> str:
    # XXX for now, return the unaltered input
    return '{{issue|%s|%s}}' % (descr_or_opts, descr)


# XXX this is a complex function and should be in a separate module
def expand_keys(node, warning, debug, **_kwargs) -> Content:
    # this can be used within an object that has unique keys...
    parameter = None
    if isinstance(node.parent, Object):
        obj = cast(Object, node.parent)
        unique_keys = obj.uniqueKeys

    # ...or within a parameter that's part of a unique key
    elif isinstance(node.parent, Parameter):
        parameter = cast(Parameter, node.parent)
        unique_keys = parameter.uniqueKeyNodes
        # the object is the parent of the unique key nodes (they should all
        # have the same parent; we don't check this)
        obj = cast(Object, unique_keys[0].parent) if unique_keys else None
    else:
        raise MacroException('only supported in object and parameter '
                             'descriptions')

    # the macro should only be used if there are unique keys
    if not unique_keys:
        raise MacroException('no unique keys are defined')

    # determine whether this is a USP model
    usp = obj.model_in_path.usp
    ignore_enable_parameter = usp
    values_supplied_on_create = usp
    immutable_non_functional_keys = usp

    # access and enable_parameter come from the object with the unique keys
    obj_access = obj.access
    enable_parameter = None if ignore_enable_parameter else \
        obj.enableParameter

    # collect information about the unique keys in a convenient form:
    # 1. collect key information, distinguishing non-functional keys (aren't
    #    affected by enable) and functional keys (are affected by enable)
    keys = [[], []]
    for unique_key in unique_keys:
        functional = unique_key.functional
        is_conditional = functional and enable_parameter is not None
        keys[is_conditional].append(unique_key)

    # 2. collect non-functional and non-defaulted unique key parameters
    num_key_params = 0  # total number of unique key parameters
    non_functional = []  # non-functional unique key parameter names
    non_defaulted = []  # non-defaulted unique key parameter names
    for unique_key in keys[0]:
        functional = unique_key.functional
        for param_ref in unique_key.parameters:
            if param_ref.refNode is None:
                continue
            param_ref_node = cast(Parameter, param_ref.refNode)

            if not functional:
                non_functional.append(param_ref.ref)

            defaulted = (param_ref_node.syntax.default.type == 'object' and
                         param_ref_node.syntax.default.status.value !=
                         'deleted')
            if not defaulted:
                non_defaulted.append(param_ref.ref)

            # XXX there's no check for parameters in multiple keys; is this
            #     permitted?
            num_key_params += 1

    # initialize the returned text
    text = ''

    # XXX some warnings are suppressed if the object has been deleted; this
    #     case should be handled generally and not piecemeal
    is_deleted = obj.status.value == 'deleted'

    # if requested, output parameter-specific info.name
    if parameter is not None:
        param_name = parameter.name
        param_access = parameter.access
        need_blank_line = False
        if obj_access != 'readOnly' and param_name in non_defaulted:
            if not values_supplied_on_create or param_access == 'readOnly':
                text += "The "
            else:
                text += "If the value isn't assigned by the Controller on " \
                        "creation, the "
            text += "Agent MUST choose an initial value that "
            if len(non_defaulted) > 1:
                text += "(together with %s) " % Utility.nicer_list(
                        non_defaulted, r'{{param|\1}}', [param_name])
            text += " doesn't conflict with any existing entries."
            need_blank_line = True

        # output immutable non-functional key parameter text
        if immutable_non_functional_keys and param_name in non_functional:
            if need_blank_line:
                text += '{{np}}'
            assigned = ' assigned by the Controller or' if \
                param_access != 'readOnly' else ''
            text += f"This is a non-functional key and its value " \
                    f"MUST NOT change once it's been{assigned} set " \
                    f"internally by the Agent."

        return Content(text)

    # the rest of the function applies only to objects (tables)
    undefined = []
    strong_refs = []
    for unique_key in unique_keys:
        for param_ref in unique_key.parameters:
            param_name = param_ref.ref
            if not param_ref.refNode:
                undefined.append(param_name)
            else:
                param_ref_node = cast(Parameter, param_ref.refNode)
                if (reference := param_ref_node.syntax.reference) and \
                        isinstance(reference, PathRef) and \
                        reference.refType == 'strong':
                    strong_refs.append(param_name)

    if undefined and not is_deleted:
        plural = 's' if len(undefined) > 1 else ''
        warning('undefined unique key parameter%s %s' % (
            plural, Utility.nicer_list(undefined)))

    # XXX strong-reference unique key parameters might be candidates for
    #     additional auto-text?
    if strong_refs and not is_deleted:
        plural = 's' if len(strong_refs) > 1 else ''
        debug('strong-reference unique key parameter%s %s' % (
            plural, Utility.nicer_list(strong_refs)))

    # if we have both unconditional and conditional keys, use separate paras
    sep_paras = len(keys[1]) > 0

    # element 0 of keys is the keys that are unconditionally unique; element
    # 1 is the keys that are conditionally unique (i.e. only for enabled
    # entries)
    for is_conditional in (False, True):
        if not keys[is_conditional]:
            continue

        enabled = ' enabled' if is_conditional else ''
        emphasis = ' (regardless of whether or not it is enabled)' if not \
            is_conditional and enable_parameter else ''
        text += f'At most one{enabled} entry in this table{emphasis} can ' \
                f'exist with '

        for i, unique_key in enumerate(keys[is_conditional]):
            param_names = [param.ref for param in unique_key.parameters]
            if i > 0:
                text += ', or with '
            if len(param_names) > 1:
                text += 'the same values '
            else:
                text += 'a given value '
            text += 'for '
            if len(param_names) == 2:
                text += 'both '
            elif len(param_names) > 2:
                text += 'all of '
            text += Utility.nicer_list(param_names, r'{{param|\1}}')
        text += '.'

        # if the unique key is unconditional and includes at least one
        # writable parameter, check whether to output additional text about
        # the Agent needing to choose unique initial values for
        # non-defaulted key parameters
        if not is_conditional and obj_access != 'readOnly':
            # XXX have suppressed this boiler plate (it should be stated once);
            #     note that it's CWMP-specific
            # noinspection PyUnreachableCode
            if False:
                text += ' If the Controller attempts to set the parameters ' \
                        'of an existing entry such that this requirement ' \
                        'would be violated, the Agent MUST reject the ' \
                        'request. In this case, the SetParameterValues ' \
                        'response MUST include a SetParameterValuesFault ' \
                        'element for each parameter in the corresponding ' \
                        'request whose modification would have resulted in ' \
                        'such a violation.'

            if num_key_params > 0 and len(non_defaulted) == 0 and not \
                    ignore_enable_parameter:
                warning('all unique key parameters are defaulted; need '
                        'enableParameter')

            if len(non_defaulted) > 0:
                text += ' On creation of a new table entry, the Agent MUST '
                if values_supplied_on_create:
                    text += '(if not supplied by the Controller on creation) '
                if len(non_defaulted) == 1:
                    text += 'choose an initial value for '
                else:
                    text += 'choose initial values for '
                text += Utility.nicer_list(non_defaulted, r'{{param|\1}}')
                text += ' such that the new entry does not conflict with ' \
                        'any existing entries.'

        if sep_paras:
            text += '\n'

    return Content(text)


def expand_list(arg, *, node: _HasContent, **_kwargs) -> str:
    parameter = cast_node(Parameter, node.parent)

    syntax = cast(Syntax, parameter.syntax)
    if not syntax.list:
        raise MacroException('parameter is not a list')

    human = syntax.format(human=True)
    arg = ', %s' % arg if arg else ''
    return '%s%s.' % (human, arg)


def expand_mount(*, node, **_kwargs) -> str:
    obj = cast_node(Object, node.parent)
    mount_type = obj.mountType
    return 'This object is a mount point, under which mountable objects ' \
           'can be mounted.' if mount_type == 'mountPoint' else ''


def expand_listitem(kind: str, **_kwargs) -> str:
    return '%s ' % kind


def expand_minval(node, **_kwargs) -> str:
    parameter = cast_node(Parameter, node.parent)
    syntax = parameter.syntax
    data_type = cast_node(_Number, syntax.type)
    value = data_type.minval
    if ranges := syntax.ranges_inherited:
        # this cleans overlapping ranges and sorts the ranges
        clean_ranges = cast(list[Range], Range.prange_clean(ranges))
        override = clean_ranges[0].minInclusive
        if override is not None:
            value = override
    return f'*{value}* (the minimum valid value)'


def expand_maxval(node, **_kwargs) -> str:
    parameter = cast_node(Parameter, node.parent)
    syntax = parameter.syntax
    data_type = cast_node(_Number, syntax.type)
    value = data_type.maxval
    if ranges := syntax.ranges_inherited:
        # this cleans overlapping ranges and sorts the ranges
        clean_ranges = cast(list[Range], Range.prange_clean(ranges))
        override = clean_ranges[-1].maxInclusive
        if override is not None:
            value = override
    return f'*{value}* (the maximum valid value)'


def expand_notify(node, **_kwargs) -> str:
    parameter = cast_node(Parameter, node.parent)
    notify = parameter.activeNotify
    usp = parameter.model_in_path.usp
    text = ''
    if notify == 'forceEnabled':
        text = '' if usp else 'Active Notification MUST always be ' \
                              'enabled for this parameter.'
    elif notify == 'forceDefaultEnabled':
        text = '' if usp else 'Active Notification MUST by default be ' \
                              'enabled for this parameter.'
    elif notify == 'canDeny':
        text = 'Value Change' if usp else 'Active'
        text += ' Notification requests for this parameter MAY be denied.'
    return text


def expand_null(name: str, scope: str, *, node: _HasContent,
                **_kwargs) -> Content:
    parameter = cast_node(Parameter, node.parent)

    # XXX name and scope aren't documented in TR-106
    target = parameter
    if name or scope:
        target = follow_reference(parameter, name, scope=ScopeEnum(scope),
                                  quiet=MACROS_PATH_QUIET)
        if not target:
            raise MacroException('non-existent %s' % name)
        if not isinstance(target, Parameter):
            raise MacroException('%s is not a parameter' % name)
        target = cast(Parameter, target)

    # get the primitive type, e.g. a String or UnsignedInt instance
    primitive = target.syntax.type.primitive_inherited

    # if its null value is None, this is a programming error
    null = primitive.null
    assert null is not None

    # if necessary, convert the null value to a macro reference
    if isinstance(null, bool):
        null = '{{true}}' if null else '{{false}}'
    elif isinstance(null, str) and null == '':
        null = '{{empty}}'
    else:
        # it might be int 0 (for example), so need to convert it to a string
        null = str(null)

    return Content(null)


def expand_numentries(*, node, args, **_kwargs) -> Union[str, Content]:
    parameter = cast_node(Parameter, node.parent)

    # find the table object that references it (this will have been set by
    # the 'used' transform)
    if not (table := parameter.tableObjectNode):
        # if we have run the 'diff' transform and the numentries parameter has
        # changed but its table hasn't changed, the 'used' transform won't have
        # visited it, so avoid an error in this case
        if any(str(t) == 'diff' for t in (args.transform or [])):
            return 'The number of entries in the associated table.'
        else:
            raise MacroException('not associated with a table')

    return Content('The number of entries in the {{object|%s}} table.' %
                   table.h_nameonly or table.h_baseonly)


def expand_paramdef(*, node, **_kwargs) -> Content:
    parameter = cast_node(Parameter, node.parent)
    if not parameter.syntax.default or \
            parameter.syntax.default.type != 'parameter':
        raise MacroException('parameter default not specified')
    return Content('The default value MUST be %s.' %
                   maybe_empty(parameter.syntax.default.value))


def expand_profdesc(*, node: _HasContent, **_kwargs) -> Content:
    profile = cast_node(Profile, node.parent)

    model = profile.model_in_path
    assert model is not None
    version = profile.version_inherited
    extends = profile.extends

    intro = "{{profile}} profile for the *%s* data model" % model
    if not extends:
        text = 'This table defines the %s. ' % intro
    else:
        text = 'The %s is defined as the union of the %s profile%s and the ' \
               'additional requirements defined in this table. ' % (
                intro, ', '.join('{{profile|%s}}' % prof for prof in extends),
                's' if len(extends) > 1 else '')
    text += 'The minimum REQUIRED version for this profile is %s:%s.' % \
            (re.sub(r':.*', '', model.name), version)

    return Content(text)


def expand_profile(ref: str, *, node: _HasContent, **_kwargs) -> str:
    # if not within a model, don't attempt to follow the reference
    if not (model := node.model_in_path):
        return "*%s*" % (ref or 'profile',)

    # an empty reference refers to the current profile
    if ref == '':
        profile = cast_node(Profile, node.parent, prefix='empty ref')
        return "*%s*" % profile.name

    # otherwise find the profile
    profile = find_node(Profile, *model.key, ref)
    return "[*%s*](#%s)" % (ref, profile.anchor)


def expand_range(*, index: str, node: _HasContent, **_kwargs) -> Content:
    parameter = cast_node(Parameter, node.parent)
    syntax = parameter.syntax
    ranges = syntax.ranges_inherited
    if not ranges:
        raise MacroException("parameter doesn't have any ranges")

    # if index is specified, it's the zero-based index of the range to be
    # reported
    if index:
        if not index.isdigit():
            raise MacroException(f"index {index} isn't a valid integer")
        if int(index) >= len(ranges):
            raise MacroException(f"index {index} is invalid (is "
                                 f"zero-based, so should be less than "
                                 f"{len(ranges)})")

    texts = []
    for i, rng in enumerate(ranges):
        if index and i != int(index):
            continue
        text = rng.format(human=True)
        # if there are units, insert them after all values; so '0 to 10'
        # becomes '0 {{units}} to 10 {{units}}'
        if syntax.units_inherited:
            text = re.sub(r'(-?\d+(?:\.\d*)?)', r'\1 {{units}}', text)
        # if there's a description, add it
        if description := rng.description:
            markdown = get_markdown_and_tidy(description.content,
                                             node=description, **_kwargs)
            text += f' ({markdown})'
        texts.append(text)
    return Content(Utility.nicer_list(texts, last=', or'))


# XXX this is a complex function and should be in a separate module
def expand_reference(arg, opts, *, node, warning, debug, **_kwargs):
    parameter = cast_node(Parameter, node.parent)
    reference = parameter.syntax.reference
    if not reference:
        raise MacroException('parameter is not a reference')

    # opts is a comma-separated list of keywords:
    # currently supported keywords are:
    # - delete : (delete if null) this reference can never be NULL, i.e. the
    #            referencing object and the referenced object have the same
    #            lifetime
    # - ignore : (ignore if non-existent) ignore any targetParents that do not
    #            exist (this allows a reference parameter to list targets that
    #            exist in only some data models in which it is to be used
    #            (e.g. to reference the Host table, which doesn't exist in
    #            Device:1)
    # - deprecated|obsoleted|deleted : (allow reference to deprecated item)
    #            pass this status as the {{object||scope}} argument ({{object}}
    #            overloads scope and status)
    # XXX should have a utility for parsing such options
    delete, ignore, status = False, False, ''
    for opt in (opts.split(',') if opts else []):
        if opt == 'delete':
            delete = True
        elif opt == 'ignore':
            ignore = True
        elif re.match('^(deprecated|obsoleted|deleted)$', opt):
            status = opt
        else:
            raise MacroException('invalid option %s' % opt)

    # determine whether this is a USP model and therefore has immutable
    # non-functional keys
    immutable_non_functional_keys = parameter.model_in_path.usp

    # it's assumed that this text will be generated after {{list}} (if present)
    # (this is guaranteed to be the case if they're auto-inserted)
    text = 'The value ' if not parameter.syntax.list else 'Each list item '

    # determine whether the parameter is part of a non-functional unique key
    unique_keys = parameter.uniqueKeyNodes
    non_functional_key = any(not unique_key.functional for unique_key in
                             unique_keys) if unique_keys else False

    # path references
    if isinstance(reference, PathRef):
        path_ref = cast(PathRef, reference)
        target_parents = path_ref.targetParents
        target_parents_nodes = path_ref.targetParentsNodes
        target_parent_scope = path_ref.targetParentScope
        target_type = path_ref.targetType.value
        target_data_type = path_ref.targetDataType.value

        # see earlier explanation of how status and scope interact
        scope = status or target_parent_scope

        # check for spurious trailing "{i}." when targetType is "row" (this is
        # a common error)
        if target_type == 'row' and \
                any(tp.endswith('{i}.') for tp in target_parents):
            warning('trailing "{i}." ignored in targetParent %s (targetType '
                    '"%s")' % (target_parents, target_type))

        # this is a tuple of (targetParent, node) tuples, with node=Null for
        # any non-existent nodes
        target_parents_tuple = tuple(zip(target_parents, target_parents_nodes))

        # report non-existent targetParents nodes (unless ignoring them), but
        # ignore all targets starting with '.Services.' because these are in
        # different data models
        target_parents_bad = [(target, parent) for target, parent in
                              target_parents_tuple if (
                                      parent is Null and not
                              target.startswith('.Services.'))]
        if not ignore and target_parents_bad:
            plural = 's' if len(target_parents_bad) > 1 else ''
            warning('non-existent targetParent%s %s' % (
                plural, Utility.nicer_list(
                        [target for target, _ in target_parents_bad])))

        # if some targetParents items were specified but none exist, this is
        # a special case and the parameter value always has to be empty
        # XXX should check that all target_parents_good are objects?
        target_parents_good = [(target, parent) for target, parent in
                               target_parents_tuple if parent is not Null]
        if target_parents and not target_parents_good:
            text = 'None of the possible target objects exist in this data ' \
                   'model, so the parameter value MUST be {{empty}}.'
            return Content(text)

        # determine whether the target parent is fixed; it's only regarded as
        # being fixed if all the good target parents are fixed objects
        target_parent_fixed = all(parent.dmr_fixedObject for _, parent in
                                  target_parents_good)

        # add the next section of text
        text += 'MUST be the Path Name of '

        if target_type == 'row':
            if arg:
                text += arg
            elif not target_parents_good:
                text += 'a table row'
            else:
                targets = [target for target, _ in target_parents_good]
                plural = 's' if len(target_parents_good) > 1 else ''
                text += 'a row in the %s table%s' % (
                    Utility.nicer_list(targets, r'{{object|\1|%s}}' % scope,
                                       last='or'), plural)

                # add logical interface logic for layer 3 interfaces
                target_parents_interfaces = []
                for _, target in target_parents_good:
                    if any(comp.ref.endswith('Layer3InterfaceParams') for
                           comp in target.components):
                        target_parents_interfaces.append(target)
                if target_parents_interfaces:
                    text += ', or the Path Name of an interface layered ' \
                            'above such a row, e.g., a row in the ' \
                            '{{object|.Logical.Interface.}} table'

        else:
            target_type = target_type.replace(
                    'single', 'single-instance object')
            target_type = target_type.replace('any', 'parameter or object')

            if arg:
                text += arg
            else:
                if target_data_type != 'any':
                    text += 'an ' if re.match(r'^[aeiou]',
                                              target_data_type) else 'a '
                    text += target_data_type
                else:
                    text += 'an ' if re.match(r'^[aeiou]',
                                              target_type) else 'a '
                    text += target_type

            if target_parents_good:
                targets = [target for target, _ in target_parents_good]
                text += ', which MUST be a child of %s' % \
                    Utility.nicer_list(targets, r'{{object|\1|%s}}' % scope,
                                       last='or')

        if path_ref.refType == 'strong':
            target_type = target_type.replace('row', 'object')
            target_type = re.sub(r'single.*', 'object', target_type)
            target_type = target_type.replace('parameter or object', 'item')
            if target_parent_fixed:
                if parameter.syntax.list:
                    text += ', or {{empty}}'
            elif not (path_ref.command_in_path or path_ref.event_in_path):
                text += '. If the referenced %s is deleted, ' % target_type
                if delete or \
                        (immutable_non_functional_keys and non_functional_key):
                    text += 'this instance MUST also be deleted (so the ' \
                            'parameter value will never be {{empty}})'
                else:
                    text += 'the '
                    if parameter.syntax.list:
                        text += 'corresponding item MUST be removed from ' \
                                'the list'
                    else:
                        text += 'parameter value MUST be set to {{empty}}'

        text += '.'

    # instance references
    # XXX these are no longer used? this code is untested
    elif isinstance(reference, InstanceRef):
        instance_ref = cast(InstanceRef, reference)
        target_parent = instance_ref.targetParent
        target_parent_scope = instance_ref.targetParentScope

        scope = status or target_parent_scope

        text += 'MUST be the instance number of a row in the ' \
                '{{object|%s|%s}} table' % (target_parent, scope)
        # XXX pathRef has no equivalent of the following text
        if not (delete or parameter.syntax.list):
            text += ', or else be {{null}} if no row is currently referenced'
        text += '.'

        if instance_ref.refType == 'strong':
            text += ' If the referenced row is deleted, '
            if delete or (
                    immutable_non_functional_keys and non_functional_key):
                text += 'this instance MUST also be deleted (so the ' \
                        'parameter value will never be {{null}}).'
            else:
                if parameter.syntax.list:
                    text += 'the corresponding item MUST be removed from ' \
                            'the list.'
                else:
                    text += 'the parameter value MUST be set to {{null}}.'

    # enumeration references
    elif isinstance(reference, EnumerationRef):
        enumeration_ref = cast(EnumerationRef, reference)
        target_param = enumeration_ref.targetParam
        target_param_scope = enumeration_ref.targetParamScope
        null_value = enumeration_ref.nullValue

        scope = status or target_param_scope

        # check that the target parameter exists
        if not enumeration_ref.targetParamNode:
            raise MacroException('non-existent targetParam %s' % target_param)

        # check that the target parameter defines enumerations (this is OK?)
        if not enumeration_ref.targetParamNode.syntax.values:
            debug("targetParam %s doesn't define any enumeration values" %
                  target_param)

        text += 'MUST be a member of the list reported by the ' \
                '{{param|%s|%s}} parameter' % (target_param, scope)

        if null_value is not None:
            if null_value == '':
                null_value = '{{empty}}'
            text += ', or else be %s' % null_value

        text += '.'

    # unexpected / unsupported reference type
    else:
        raise MacroException('unsupported reference type %s' %
                             reference.typename)

    return Content(text)


ignore_old_macros = {'object', 'param', 'command', 'event', 'enum', 'bibref',
                     'deprecated', 'obsoleted', 'deleted'}


def removed_or_inserted(what: str, text: str) -> str:
    # clean up by removing some macro references
    text = Macro.clean(text)

    # presence/absence of newlines determines whether to use a span or a div
    comps = text.split('\n')

    # leading and trailing '\n\n' are always passed through
    head, body, tail = '', '', ''
    if len(comps) > 2 and not comps[0] and not comps[1]:
        head = '\n\n'
        comps = comps[2:]
    if len(comps) > 2 and not comps[-2] and not comps[-1]:
        tail = '\n\n'
        comps = comps[:-2]

    # if there are no further newlines, it's a span (or empty)
    assert len(comps) > 0
    if len(comps) == 1:
        body = '[%s]{.%s}' % (comps[0], what) if comps[0] else ''

    # otherwise it's a div
    else:
        # in this case, head and tail should be defined, but we don't check
        head, tail = '\n\n', '\n\n'
        # XXX see expand_div() for why we use nine colons here
        # XXX should add '{{div}}' return Content; then it would all be
        #     handled by expand_div()
        colons = 9 * ':'
        body = '%s %s\n' % (colons, what) + '\n'.join(comps) + \
               '\n%s' % colons

    return head + body + tail


def expand_removed(text: str, info, stack, **_kwargs) -> str:
    # e.g., {{param|{{replaced|OLD|NEW}}}} becomes {{param|NEW}}
    if {ref.name for ref in stack} & ignore_old_macros:
        info('ignored removed text %r within macro argument' % text)
        return ''
    # XXX this used to pass Macro.unescape(text) but this dangerous, because
    #     nothing prevents it being passed to Content() further up the macro
    #     expansion stack; unescaping (if needed) should be done later
    return removed_or_inserted('removed', text)


def expand_inserted(text: str, info, stack, **_kwargs) -> str:
    # e.g., {{param|{{replaced|OLD|NEW}}}} becomes {{param|NEW}}
    # XXX this loses the 'inserted' style, but this is a small price to pay
    if {ref.name for ref in stack} & ignore_old_macros:
        info('forwarded inserted text %r within macro argument' % text)
        return text
    return removed_or_inserted('inserted', text)


# XXX could this give a more explicit indication of what changed?
def expand_replaced(old: str, new: str, info, stack, **_kwargs) -> str:
    # e.g., {{replaced|OLD|NEW}} becomes {{removed|OLD}}{{inserted|NEW}}
    return expand_removed(old, info, stack) + expand_inserted(new, info, stack)


def expand_secured(value, **_kwargs) -> Content:
    # XXX should support --nosecuredishidden or equivalent
    nosecuredishidden = False

    qualifier = ', unless the Controller' \
                'has a "secured" role' if nosecuredishidden else ''
    return Content('When read, this parameter returns %s, regardless of the '
                   'actual value%s.' % (value, qualifier))


def expand_showid(node: _HasContent, **_kwargs) -> str:
    if node.parent.id is None:
        raise MacroException('id is not defined')

    # XXX report.pl comment: would like to generate a link, but this fights
    #     with the auto-link logic; need to support a more markdown-like
    #     link syntax (note: should now read this as 'markdown-like')
    # XXX note use of pandoc [text]{.mark} for highlighting; this is the
    #     wrong sort of highlighting! need to use different classes
    return "[**[%s]**]{.mark}" % node.parent.id


def expand_size(*, index: str, node: _HasContent, **_kwargs) -> Content:
    parameter = cast_node(Parameter, node.parent)
    syntax = parameter.syntax
    sizes = syntax.sizes_inherited
    if not sizes:
        raise MacroException("parameter doesn't have any sizes")

    # if index is specified, it's the zero-based index of the range to be
    # reported
    if index:
        if not index.isdigit():
            raise MacroException(f"index {index} isn't a valid integer")
        if int(index) >= len(sizes):
            raise MacroException(f"index {index} is invalid (is "
                                 f"zero-based, so should be less than "
                                 f"{len(sizes)})")

    texts = []
    for i, size in enumerate(sizes):
        if index and i != int(index):
            continue
        text = size.format(human=True)
        # if there's a description, add it
        if description := size.description:
            markdown = get_markdown_and_tidy(description.content,
                                             node=description, **_kwargs)
            text += f' ({markdown})'
        texts.append(text)
    return Content(Utility.nicer_list(texts, last=', or'))


def expand_span(classes: str, text: str, **_kwargs) -> str:
    if not classes:
        return text
    else:
        return '[%s]{%s}' % (text,
                             ' '.join('.%s' % cls for cls in classes.split()))


def expand_status(version, reason, *, node, stack, info, warning,
                  **_kwargs) -> Content:
    macro = stack[-1]

    # warn if it isn't in its own paragraph; this is needed both for nice
    # formatting and for expand/contract logic (the check is that it's called
    # from {{div}} and is the only item in its second (content) argument)
    # XXX unfortunately, auto-appended macro references such as `{{enum}}`
    #     (which has no separator) make this harder... so currently only check
    #     for trailing text
    # XXX don't give all the trailing text, because it might include macro
    #     references, which would need to be expanded to render nicely
    if len(stack) > 1 and stack[-2].name == 'div' and len(stack[-2].args) > 1 \
            and (macro is not stack[-2].args[1].items[0] or
                 (len(stack[-2].args[1].items) > 1 and
                  isinstance(stack[-2].args[1].items[1], str))):
        if macro is not stack[-2].args[1].items[0]:
            warning('{{%s}} should be in its own paragraph but is preceded by '
                    '%r' % (macro.name, stack[-2].args[1].items[0]))
        else:
            # XXX surely it should be a string, but I saw something strange...
            trailing = str(stack[-2].args[1].items[1])
            if len(stack[-2].args[1].items) > 2:
                trailing += '...'
            warning('{{%s}} should be in its own paragraph but is followed by '
                    '%r' % (macro.name, trailing))

    # generate the text
    text = 'This %s was %s in %s' % (
        node.parent.elemname, macro.name.upper(), version)

    # append the reason, if supplied
    if reason:
        # the reason shouldn't end with a period (or exclamation mark or
        # question mark)
        if match := re.search(r'([.!?])$', reason):
            term = match.group(1)
            info('{{%s}} reason should be a fragment but ends with %r' % (
                macro.name, term))
            reason = reason[:-1]
        text += '{{span|{{classes}}| %s}}' % reason

    # terminate the sentence
    text += '.'

    # this is an empty span (it can be useful as a marker)
    text += '{{span|{{classes}}}}'

    return Content(text)


# noinspection PyShadowingBuiltins
def expand_template(id, **_kwargs) -> Content:
    template = find_node(Template, id)
    return Content(template.text)


# convert the TR-nnniiaacc form to tr-nnn-i-a-c (because it's documented)
def expand_trname(name, **_kwargs) -> str:
    text = name
    if match := re.match(
            r'^(TR)-(\d+)(?:i(\d+))?(?:a(\d+))?(?:c(\d+))?$', name):
        tr, nnn, i, a, c = match.groups()
        tr = tr.lower()
        nnn = int(nnn)
        i = 1 if i is None else int(i)
        a = 0 if a is None else int(a)
        c = 0 if c is None else int(c)
        text = f'{tr}-{nnn}-{i}-{a}-{c}'
    return text


def expand_union(node: _HasContent, **_kwargs) -> Content:
    # parameter: expect discriminated objects
    if isinstance(node.parent, Parameter):
        parameter = node.parent
        if not (objects := parameter.discriminatedObjectNodes):
            raise MacroException('only valid in discriminator parameters')
        # XXX should use Utility.nicer_list() but it needs to support \1 and \2
        #     (actually it would be better to use %s instead)
        object_refs = ', '.join(
                '{{object|%s|%s}}' % (obj.h_nameonly, obj.status) for obj
                in objects)
        text = 'This parameter discriminates between the %s union objects.' \
               % object_refs

    # object: expect discriminator parameter
    elif isinstance(node.parent, Object):
        obj = node.parent
        object_nameonly = obj.h_nameonly
        if not (parameter_name := obj.discriminatorParameter):
            raise MacroException('only valid in discriminated objects')
        text = 'This object MUST be present if, and only if, {{param|#.%s}} ' \
               'is {{enum|%s|#.%s}}.' % (parameter_name, object_nameonly,
                                         parameter_name)

    # invalid
    else:
        raise MacroException('only valid in parameter and object descriptions')

    return Content(text)


def expand_units(*, node, **_kwargs) -> str:
    owner = cast_node((DataType, Parameter), node.parent)

    # if the owner is a parameter, the units are on its syntax element
    if isinstance(owner, Parameter):
        owner = owner.syntax

    units = owner.units_inherited
    if not units:
        raise MacroException('missing units facet')

    if not units.value:
        raise MacroException('empty units string')

    return "*%s*" % units.value


# these macros only insert whitespace if the current string doesn't already
# end with the desired replacement text
def expand_whitespace(stack, chunks, **_kwargs) -> str:
    # desired replacement text for the various whitespace macros
    macro_text = {'ns': ' ', 'nl': '\n', 'np': '\n\n'}

    # check that the macro name is expected
    name = stack[-1].name
    assert name in macro_text, 'invalid whitespace macro name %s (not %s)' % (
        name, ', '.join(macro_text))

    # desired replacement text
    text = macro_text[name]

    # collect the text that's been added so far
    # XXX it would be nice to have a more direct way of doing this; maybe
    #     should maintain it in parallel with chunks
    so_far = ''.join(chunk for lst in chunks for chunk in lst)

    if so_far == '':
        # nothing there yet; don't add anything
        text = ''
    elif so_far.endswith('\n\n'):
        # already a new para; don't add anything
        text = ''
    elif so_far.endswith('\n'):
        # already a new line; add only a second newline (if needed)
        text = text[1:]
    else:
        # not already a new line; add the unchanged text
        pass

    return text


def expand_xmlref(ref: str, label: str, **_kwargs) -> str:
    # XXX for now, return the unaltered input
    return '{{xmlref|%s|%s}}' % (ref, label)


# macros that can potentially be auto-included before node content
# - node.auto_macro_criteria determine whether they'll be included
# - they are declared in the order that they should be included
Macro('profdesc', macro_auto='before', macro_body=expand_profdesc)
Macro('showid', macro_auto='before', macro_body=expand_showid)
Macro('mandatory', macro_auto='before', macro_body="**[MANDATORY]**")
Macro('async', macro_auto='before', macro_body="**[ASYNC]**")
Macro('datatype', arg=None, macro_auto='before', macro_body=expand_datatype)
Macro('list', arg=None, macro_auto='before', macro_body=expand_list)
Macro('reference', arg=None, opts=None, macro_auto='before',
      macro_body=expand_reference)

# macros that aren't auto-included
# - they are declared in alphabetical order
Macro('', macro_body='')  # can use {{}} as a separator
Macro('abbref', id=None, macro_body=expand_abbref)
Macro('bibref', id=str, section=None, macro_body=expand_bibref)
Macro('appdate', date=str, macro_body='')
# this isn't final, so can be overridden without generating a warning
Macro('classes', default='', macro_body='', macro_final=False)
Macro('deleted', version=str, reason=None, macro_body=expand_status)
Macro('deprecated', version=str, reason=str, macro_body=expand_status)
Macro('div', classes='', text='', macro_body=expand_div)
Macro('docname', name=str, macro_body='')
# XXX this needs to be sensitive to being at the start of the sentence
Macro('empty', style='default', macro_body=expand_empty)
Macro('event', ref=None, scope_or_status='normal',
      macro_body=expand_itemref)
Macro('false', macro_body="*false*")
Macro('gloref', id=None, macro_body=expand_gloref)
Macro('inserted', text=str, macro_body=expand_inserted)
Macro('issue', descr_or_opts=str, descr=None, macro_body=expand_issue)
Macro('li', kind=str, macro_body=expand_listitem)
Macro('minval', macro_body=expand_minval)
Macro('maxval', macro_body=expand_maxval)
Macro('nl', macro_body=expand_whitespace)
Macro('np', macro_body=expand_whitespace)
Macro('ns', macro_body=expand_whitespace)
Macro('null', name=None, scope=None, macro_body=expand_null)
Macro('numentries', macro_body=expand_numentries)
Macro('object', ref=None, scope_or_status='normal',
      macro_body=expand_itemref)
Macro('obsoleted', version=str, reason=None, macro_body=expand_status)
Macro('param', ref=None, scope_or_status='normal',
      macro_body=expand_itemref)
Macro('profile', ref=None, macro_body=expand_profile)
Macro('range', index=None, macro_body=expand_range)
Macro('removed', text=str, macro_body=expand_removed)
Macro('replaced', old=str, new=str, macro_body=expand_replaced)
Macro('section', category=None, macro_body='')
Macro('size', index=None, macro_body=expand_size)
Macro('span', classes='', text='', macro_body=expand_span)
# XXX {{templ}} is deprecated; its use should output a warning
Macro('templ', id=str, macro_body=expand_template)
Macro('template', id=str, macro_body=expand_template)
Macro('trname', name=str, macro_body=expand_trname)
Macro('true', macro_body="*true*")
Macro('units', macro_body=expand_units)
Macro('xmlref', ref=str, label=None, macro_body=expand_xmlref)

# macros that can potentially be auto-included after node content
# - node.auto_macro_criteria determine whether they'll be included
# - they are declared in the order that they should be included
Macro('enum', value=None, param=None, scope_or_status='normal',
      macro_auto='after', macro_body=expand_value)
Macro('pattern', value=None, param=None, scope_or_status='normal',
      macro_auto='after', macro_body=expand_value)
Macro('access', macro_auto='after', macro_body=expand_access)
Macro('hidden', value='{{null}}', macro_auto='after', macro_body=expand_hidden)
Macro('secured', value='{{null}}', macro_auto='after',
      macro_body=expand_secured)
Macro('command', ref=None, scope_or_status='normal', macro_auto='after',
      macro_body=expand_command)  # calls expand_itemref()
Macro('factory', macro_auto='after', macro_body=expand_factory)
Macro('impldef', macro_auto='after', macro_body=expand_impldef)
Macro('mount', macro_auto='after', macro_body=expand_mount)
Macro('paramdef', macro_auto='after', macro_body=expand_paramdef)
Macro('union', macro_auto='after', macro_body=expand_union)
Macro('entries', macro_auto='after', macro_body=expand_entries)
Macro('keys', macro_auto='after', macro_body=expand_keys)
Macro('inform', macro_auto='after', macro_body=expand_inform)
Macro('notify', macro_auto='after', macro_body=expand_notify)

# this is a special case
Macro('diffs', diffs=list, macro_body=expand_diffs)
