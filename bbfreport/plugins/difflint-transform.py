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

from typing import Optional

from bbfreport.node import _Base, Model, _ModelItem, _ProfileItem, \
    _ValueFacet, Version

FIRST_USP_VERSION = Version((2, 12, 0))
FIRST_COMPONENT_CLAMP_VERSION = Version((2, 16, 0))


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
              key: Optional[tuple[str, ...]] = None) -> None:
    if key is None:
        key = node.key

    # for example, uniqueKey parameterRef is unkeyed
    if key is None or len(key) < 2:
        return

    key = (key[0], key[1:])

    models.setdefault(key[0], {})
    models[key[0]][key[1:]] = node


def visit__model_item(item: _ModelItem):
    save_node(item)


def visit__profile_item(item: _ProfileItem):
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

    # note use of h_version_inherited; also, for USP Device:2, clamp the
    # version to 2.12 (this is necessary for pre-2.16 models that don't
    # clamp the version via component references)
    # XXX it might no longer be necessary because, from 2.18, component
    #     references default the clamp version to the current version
    def version_inherited(nod: _Base) -> Version:
        inherited = nod.h_version_inherited
        assert inherited is not None, '%s: no inherited version' % nod.nicepath
        if (model := nod.model_in_path) and model.usp and \
                model.keylast == 'Device:2' and \
                model.model_version < FIRST_COMPONENT_CLAMP_VERSION and \
                inherited < FIRST_USP_VERSION:
            inherited = FIRST_USP_VERSION
        return inherited

    # this returns the parent first; is this the best order? I think so
    # XXX this could be a standard method / property?
    def ancestors(nod: _Base) -> list[_Base]:
        return ([nod.parent] + ancestors(nod.parent)) if nod.parent else []

    # two models should have been collected
    assert len(models) == 2, '%d model supplied (need 2)' % len(models)
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

    # determine version changes (decreased and increased versions are
    # reported separately)
    decreased_errors = {key: node for key, node in changed_sorted.items() if
                        version_inherited(node[NEW]) <
                        version_inherited(node[OLD])}
    increased_errors = {key: node for key, node in changed_sorted.items() if
                        version_inherited(node[NEW]) >
                        version_inherited(node[OLD])}

    # get nodes that have been added in the new model
    added_keys = set(new.keys()) - set(old.keys())
    added = {key: new[key] for key in added_keys}
    added_sorted = {key: node for key, node in sorted(
            added.items(), key=lambda item: item[0])}

    # get nodes that have been removed in the new model
    removed_keys = set(old.keys()) - set(new.keys())
    removed = {key: old[key] for key in removed_keys}
    removed_sorted = {key: node for key, node in sorted(
            removed.items(), key=lambda item: item[0])}

    # report 'removed' errors
    for key, node in removed_sorted.items():
        context_node = node.instance_in_path((_ModelItem, _ProfileItem))
        node_value = ' %s' % node.value if isinstance(node,
                                                      _ValueFacet) else ''
        logger.warning('%s: %s%s removed; should instead mark as '
                       'deprecated' % (
                           context_node.nicepath, node.elemname, node_value))

    # determine missing and invalid versions (this can give spurious results
    # if comparing non-adjacent versions)
    missing_errors = {key: node for key, node in added_sorted.items() if
                      not isinstance(node, _ProfileItem) and
                      version(node) is None and version_inherited(
                              node) < new_version}
    invalid_errors = {key: node for key, node in added_sorted.items() if
                      not isinstance(node, _ProfileItem) and
                      version(node) is not None and version(
                              node) < new_version}

    # if a node has an error, there's no point complaining about its children
    # (we ignore increased_errors here; they're not reported as warnings)
    nodes_with_errors = set(decreased_errors.values()) | set(
            missing_errors.values()) | set(invalid_errors.values())
    missing_errors = {key: node for key, node in missing_errors.items() if
                      not any(ancestor in nodes_with_errors for ancestor in
                              ancestors(node))}

    # report 'decreased' and 'increased' errors (we always report cases where
    # the version decreased, e.g., to catch missing clamp versions, but not
    # where it increased, which is assumed to be to fix a previous error)
    for key, node in decreased_errors.items():
        logger.warning('%s: version decreased from %s (in %s) to %s '
                       '(in %s)' % (
                           node[NEW].nicepath, version_inherited(node[OLD]),
                           old_version, version_inherited(node[NEW]),
                           new_version))
    for key, node in increased_errors.items():
        logger.info('%s: version increased from %s (in %s) to %s '
                    '(in %s)' % (
                        node[NEW].nicepath, version_inherited(node[OLD]),
                        old_version, version_inherited(node[NEW]),
                        new_version))

    # report 'missing' errors
    for key, node in missing_errors.items():
        logger.warning('%s: missing version (added in %s; inherited %s)' % (
            node.nicepath, new_version, version_inherited(node),))

    # report 'invalid' errors
    for key, node in invalid_errors.items():
        logger.warning('%s: invalid version %s (added in %s)' % (
            node.nicepath, version(node), new_version))

    # report invalid profile items (items added to existing profiles)
    profile_errors = {key: node for key, node in added_sorted.items() if
                      isinstance(node, _ProfileItem) and
                      version_inherited(node) < new_version}
    for key, node in profile_errors.items():
        logger.warning(
                "%s: can't add %s to existing profile (defined in %s)" % (
                    node.nicepath, node.elemname, version_inherited(node)))

    # report changed profile requirements
    profile_keys = {key for key in common_keys if
                    isinstance(new[key], _ProfileItem) and new[
                        key].requirement != old[key].requirement}
    for key in sorted(profile_keys):
        old_node, new_node = old[key], new[key]
        logger.warning("%s: can't change profile requirement from %s (defined "
                       "in %s) to %s" % (
                           new_node.nicepath, old_node.requirement,
                           version_inherited(old_node), new_node.requirement))
