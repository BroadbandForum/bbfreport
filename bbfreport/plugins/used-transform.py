"""Used transform plugin. This is invoked automatically.

It currently just visits the following types of node.

* `DataTypeRef`, to keep track of which `data types<DataType>` are used.

* `_HasContent`, to keep track of which `abbref<AbbreviationsItem>`,
  `bibref<Reference>`, `gloref<GlossaryItem>` and `template<Template>`
  items are referenced.
"""

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

from ..node import _HasContent, DataTypeRef, Dt_object, Object, Syntax

# XXX this does more things, e.g. it points #entries parameters back to their
#     tables; it should probably be renamed; 'fixup'?

# XXX this needs to be cleverer; it will currently mark as used anything
#     referenced from any abbreviation (say), but it should only consider
#     things referenced (directly or indirectly) from visited parameters etc.

# XXX similarly it may (for example) mark as a used a bibref that is
#     referenced by a data type that ends up not being used

# XXX may need to do more with DT support


# do nothing if --thisonly was specified
def _begin_(_, args) -> bool:
    return args.thisonly


def visit_syntax(syntax: Syntax):
    syntax.primitive_inherited.data_type.mark_used()


def visit_data_type_ref(data_type: DataTypeRef) -> None:
    data_type.primitive_inherited.mark_used()
    while data_type:
        data_type.mark_used()
        data_type = data_type.baseNode


# this is a description (or other description-like content) anywhere
# noinspection PyShadowingBuiltins
def visit__has_content(node: _HasContent, error, warning, info, debug) -> None:
    typename_map = {'abbref': 'abbreviationsItem', 'bibref': 'reference',
                    'gloref': 'glossaryItem', 'template': 'template'}

    # (name, id) tuples for {{bibref}} etc. references with at least one
    # simple argument
    refs = [(ref.name, ref.args[0].text) for key, refs in
            node.content.get_macro_refs(error=error, warning=warning,
                                        info=info, debug=debug).items() for ref
            in refs if key in typename_map and len(ref.args) > 0 and ref.args[
                0].is_simple]
    for name, id in refs:
        if item := node.find(typename_map[name], id):
            item.mark_used()


def visit_object(node: Object, logger) -> None:
    if parameter := node.numEntriesParameterNode:
        if parameter.tableObjectNode:
            logger.warning('%s: numEntriesParameter %s already used by %s' % (
                node.objpath, parameter.name,
                parameter.tableObjectNode.objpath))
        parameter.tableObjectNode = node

    # XXX would like to be able to write:
    #     parameter.discriminatedObjectNodes.append(node) or
    #     parameter.discriminatedObjectNodes += [node]
    if parameter := node.discriminatorParameterNode:
        parameter.getprop('discriminatedObjectNodes').merge(node)

    for unique_key in node.uniqueKeys:
        for parameter_ref in unique_key.parameters:
            # assume that the lint transform will output any warnings
            if parameter := parameter_ref.refNode:
                parameter.getprop('uniqueKeyNodes').merge(unique_key)


# this is necessary because, when processing a DT instance, the DM objects
# aren't visited
def visit_dt_object(node: Dt_object, logger):
    if ref_node := node.refNode:
        visit_object(ref_node, logger)
