"""Diffs lint transform plugin."""

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

# XXX this currently only considers _ModelItems and _ValueFacets, and assumes
#     that key[1:] identifies the item (ignoring the defining file)

# XXX there should be more checks

from typing import List, Optional, Tuple

from bbfreport.node import _Base, Model, _ModelItem, _ValueFacet, Version


# need two files on the command line
# XXX what if there are two models in a single file?
def _post_init_(args, logger) -> Optional[bool]:
    if len(args.file) != 2:
        logger.error('need two files (old and new) on the command line '
                     '(%d were supplied)' % len(args.file))
        return True


# this is keyed by (key[0], key[1:]); entries are nodes
models = {}


# need to be able to supply the key because value facets aren't keyed
def save_node(node: _Base, *,
              key: Optional[Tuple[str, ...]] = None) -> None:
    if key is None:
        key = node.key
    assert key is not None and len(key) > 1

    key = (key[0], key[1:])

    models.setdefault(key[0], {})
    models[key[0]][key[1:]] = node


def visit__model_item(item: _ModelItem):
    save_node(item)


def visit__value_facet(value: _ValueFacet):
    # only consider value facets within parameter definitions (not data types)
    if parameter := value.parameter_in_path:
        key = parameter.key + (value.value,)
        save_node(value, key=key)


def _end_(_, logger):
    # permit dmr:version
    def version(nod: _Base) -> Optional[Version]:
        return nod.version or nod.dmr_version

    # note use of object_version_inherited; also, for USP Device:2, clamp the
    # version to 2.12 (this is necessary for pre-2.16 models that don't
    # clamp the version via component references)
    def version_inherited(nod: _Base) -> Version:
        inherited = nod.object_version_inherited
        assert inherited is not None
        if (model := nod.model_in_path) and model.usp and \
                model.keylast == 'Device:2' and \
                inherited.comps < (2, 12, 0):
            inherited = Version((2, 12, 0))
        return inherited

    # this returns the parent first; is this the best order? I think so
    # XXX this could be a standard method / property?
    def ancestors(nod: _Base) -> List[_Base]:
        return ([nod.parent] + ancestors(nod.parent)) if nod.parent else []

    # two models should have been collected
    assert len(models) == 2
    old, new = models.values()

    # determine the old and new model versions (actually old and new should
    # each contain only one model node)
    old_version = max(node.model_version for node in old.values() if
                      isinstance(node, Model))
    new_version = max(node.model_version for node in new.values() if
                      isinstance(node, Model))

    # XXX the logic's not quite right; corrigenda muck things up, so set the
    #     corrigendum number to 0
    new_version = Version((new_version.comps[0], new_version.comps[1], 0))

    # get keys that are present in both versions
    common_keys = set(old.keys()) & set(new.keys())

    # get nodes whose versions have changed in the new model
    # noinspection PyPep8Naming
    OLD, NEW = 0, 1
    changed = {key: (old[key], new[key]) for key in common_keys if
               version_inherited(new[key]) != version_inherited(old[key])}
    changed_sorted = {key: node for key, node in sorted(
            changed.items(), key=lambda item: item[0])}

    # determine invalid version changes
    # XXX aren't these all of them?
    changed_errors = {key: node for key, node in changed_sorted.items() if
                      version_inherited(node[NEW]) !=
                      version_inherited(node[OLD])}

    # get nodes that have been added in the new model
    added_keys = set(new.keys()) - set(old.keys())
    added = {key: new[key] for key in added_keys}
    added_sorted = {key: node for key, node in sorted(
            added.items(), key=lambda item: item[0])}

    # determine missing and invalid versions (this can give spurious results
    # if comparing non-adjacent versions)
    missing_errors = {key: node for key, node in added_sorted.items() if
                      version(node) is None and version_inherited(
                              node) < new_version}
    invalid_errors = {key: node for key, node in added_sorted.items() if
                      version(node) is not None and version(
                              node) < new_version}

    # if a node has an error, there's no point complaining about its children
    nodes_with_errors = set(changed_errors.values()) | set(
            missing_errors.values()) | set(invalid_errors.values())
    missing_errors = {key: node for key, node in missing_errors.items() if
                      not any(ancestor in nodes_with_errors for ancestor in
                              ancestors(node))}

    # report 'changed' errors
    for key, node in changed_errors.items():
        logger.warning('%s: invalid version change from %s (in %s) to %s (in '
                       '%s)' % (
                           node[NEW].nicepath, version_inherited(node[OLD]),
                           old_version, version_inherited(node[NEW]),
                           new_version,))

    # report 'missing' errors
    for key, node in missing_errors.items():
        logger.warning('%s: missing version (added in %s; inherited %s)' % (
            node.nicepath, new_version, version_inherited(node),))

    # report 'invalid' errors
    for key, node in invalid_errors.items():
        logger.warning('%s: invalid version %s (added in %s)' % (
            node.nicepath, version(node), new_version))
