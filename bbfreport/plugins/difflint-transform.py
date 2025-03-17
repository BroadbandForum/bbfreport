"""Diffs lint transform plugin."""

# Copyright (c) 2023-2024, Broadband Forum
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

from bbfreport.node import _Base, Command, CommandRef, Key, Model, \
    _ModelItem, _Object, _Parameter, ParameterRef, ObjectRef, Profile, \
    _ProfileItem, _ValueFacet, Version

# the first data model versions that supported USP
FIRST_USP_VERSIONS = {
    'Device:2': Version((2, 12, 0)),
    'FAPService:2': Version((2, 1, 1)),
    'StorageService:1': Version((1, 3, 1)),
    'STBService:1': Version((1, 4, 1)),
    'VoiceService:2': Version((2, 0, 1))
}

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


# profiles are expanded to include internal profile contents
def save_profile(prof: Profile) -> None:
    # if profile item's key[2] (the profile name) starts with an underscore,
    # return a modified key without the underscore
    # XXX this assumes too much knowledge about key structure
    # XXX it also assumes that the public profile has the same name sans
    #     the underscore
    def fix_key(nod: _Base) -> Key:
        ky = nod.key
        if not ky or len(ky) < 3 or not ky[2].startswith('_'):
            return None
        else:
            return ky[0:2] + (ky[2][1:],) + ky[3:]

    # XXX this will also be done by visit__model_item()
    save_node(prof)

    for node in prof.profile_expand(base=True, extends=True):
        if isinstance(node, _ProfileItem):
            save_node(node, key=fix_key(node))


def visit__model_item(item: _ModelItem):
    if not item.name.startswith('_'):
        save_node(item)


def visit_profile(prof: Profile):
    if not prof.name.startswith('_'):
        save_profile(prof)


def visit__value_facet(value: _ValueFacet):
    # only consider value facets within parameter definitions (not data types)
    if parameter := value.parameter_in_path:
        key = parameter.key + (value.value,)
        save_node(value, key=key)


def _end_(_, logger):
    def clamp(nod: _Base, ver: Optional[Version]) -> Optional[Version]:
        if (model := nod.model_in_path) and model.usp and ver is not None:
            first_usp_version = FIRST_USP_VERSIONS.get(model.keylast, None)
            if first_usp_version is not None and ver < first_usp_version:
                ver = first_usp_version
        return ver

    # permit dmr:version
    def version(nod: _Base) -> Optional[Version]:
        return clamp(nod, nod.version or nod.dmr_version)

    # note use of h_version_inherited
    def version_inherited(nod: _Base) -> Version:
        inherited = nod.h_version_inherited
        assert inherited is not None, '%s: no inherited version' % nod.nicepath
        return clamp(nod, inherited)

    # this returns the parent first; is this the best order? I think so
    # XXX this could be a standard method / property?
    def ancestors(nod: _Base) -> list[_Base]:
        return ([nod.parent] + ancestors(nod.parent)) if nod.parent else []

    # this determines whether a parameter or object should be ignored because
    # it's been replaced with a command
    def ignore_item(nod: _Base) -> bool:
        # helper for returning objpath without the profile name, which would
        # normally be included for profile items, and without a trailing dot
        def objpath(n: _Base) -> str:
            return n.fullpath(style='object+notprofile').rstrip('.')

        if isinstance(nod, (_Parameter, ParameterRef, _Object, ObjectRef)):
            # this will be an invalid path for multi-instance objects, but it
            # doesn't really matter (just slightly inefficient)
            cmd_objpath = objpath(nod) + '()'
            for cmd in nod.findall(Command) + nod.findall(CommandRef):
                if cmd.objpath == cmd_objpath:
                    logger.info('%s: ignored %s -> %s %s change' % (
                        nod.nicepath, nod.typename, cmd.typename, cmd_objpath))
                    return True
        return False

    # two models should have been collected
    if len(models) != 2:
        logger.error('need 2 models to compare, but found only %d' %
                     len(models))
        return
    old, new = models.values()

    # determine the old and new model versions (actually old and new should
    # each contain only one model node)
    old_version = max(node.model_version for node in old.values() if
                      isinstance(node, Model))
    new_version = max(node.model_version for node in new.values() if
                      isinstance(node, Model))
    assert old_version <= new_version, "first model (%s) is newer than " \
                                       "second model (%s)" % (
                                           old_version, new_version)

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

    # if a node was removed, there's no point complaining about its children
    removed_pruned = {key: node for key, node in removed.items() if not any(
            ancestor in removed.values() for ancestor in ancestors(node))}

    # special case: if a parameter or object was removed, but a corresponding
    # command was added, this was a transition to separate USP and CWMP data
    # models, so don't complain
    removed_pruned = {key: node for key, node in removed_pruned.items()
                      if not ignore_item(node)}

    # report 'removed' errors
    removed_sorted = {key: node for key, node in sorted(
            removed_pruned.items(), key=lambda item: item[0])}
    for key, node in removed_sorted.items():
        context_node = node.instance_in_path((_ModelItem, _ProfileItem))
        node_value = ' %s' % node.value if isinstance(node,
                                                      _ValueFacet) else ''
        logger.warning('%s: %s%s removed; should instead mark as '
                       'deprecated' % (
                           context_node.nicepath, node.elemname, node_value))

    # determine missing and invalid versions (we need both the old_version
    # and new_version checks because old_version can be equal to new_version)
    missing_errors = {key: node for key, node in added_sorted.items() if
                      version(node) is None and
                      version_inherited(node) <= old_version and
                      version_inherited(node) < new_version}
    invalid_errors = {key: node for key, node in added_sorted.items() if
                      version(node) is not None and
                      version(node) <= old_version and
                      version(node) < new_version}

    # if a node has an error, there's no point complaining about its children
    # (we ignore increased_errors here; they're not reported as warnings)
    nodes_with_errors = set(decreased_errors.values()) | set(
            missing_errors.values()) | set(invalid_errors.values())
    missing_errors = {key: node for key, node in missing_errors.items() if
                      not any(ancestor in nodes_with_errors for ancestor in
                              ancestors(node))}

    # report 'decreased' and 'increased' errors
    for key, node in decreased_errors.items():
        logger.warning('%s: version decreased from %s (in %s) to %s '
                       '(in %s)' % (
                           node[NEW].nicepath, version_inherited(node[OLD]),
                           old_version, version_inherited(node[NEW]),
                           new_version))
    for key, node in increased_errors.items():
        logger.warning('%s: version increased from %s (in %s) to %s '
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
                      version_inherited(node) <= old_version and
                      version_inherited(node) < new_version}
    for key, node in profile_errors.items():
        logger.warning(
                "%s: can't add %s to existing profile (defined in %s)" % (
                    node.nicepath, node.elemname, version_inherited(node)))

    # report changed profile requirements
    profile_keys = {key for key in common_keys if
                    isinstance(new[key], _ProfileItem) and new[
                        key].requirement != old[key].requirement}

    # special case: reducing the requirement from 'readWrite' to
    # 'writeOnceReadOnly' is OK and so shouldn't be reported
    profile_keys_pruned = {key for key in profile_keys if not (
            old[key].requirement == 'readWrite' and
            new[key].requirement == 'writeOnceReadOnly')}

    # special case: reducing the requirement to 'present' (e.g. from
    # 'createDelete') is fixing a problem and so shouldn't be reported
    profile_keys_pruned = {key for key in profile_keys_pruned if not (
            new[key].requirement == 'present' and
            new[key].requirement < old[key].requirement)}

    # special case: don't report where the only change is leading or trailing
    # whitespace
    profile_keys_pruned = {key for key in profile_keys_pruned if not (
            new[key].requirement.value.strip() ==
            old[key].requirement.value.strip())}

    for key in sorted(profile_keys_pruned):
        old_node, new_node = old[key], new[key]
        logger.warning("%s: can't change profile requirement from %s (defined "
                       "in %s) to %s" % (
                           new_node.nicepath, old_node.requirement,
                           version_inherited(old_node), new_node.requirement))

    # hide the first (old) model (this means that the hidefirst transform
    # is no longer needed)
    for node in old.values():
        node.hide()
