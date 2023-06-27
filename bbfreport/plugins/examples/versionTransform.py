"""Version transform plugin."""

# Copyright (c) 2019-2021, Broadband Forum
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

import logging
import re

from typing import Any, cast, Optional, Tuple

from ..node import _Base, ComponentRef, Model, Object
from ..transform import Transform
from ..utility import Utility

logger_name = __name__.split('.')[-1]
logger = logging.getLogger(logger_name)
logger.addFilter(
        lambda r: r.levelno > 20 or logger_name in Utility.logger_names)


# XXX should generalize this to check/fix versions regardless of dmr:version
class VersionTransform(Transform):
    """Version transform plugin.

    Further details are TBD.
    """

    _default_initial_version: str = '1.0'

    @classmethod
    def _add_arguments(cls, arg_parser):
        arg_group = arg_parser.add_argument_group("version transform "
                                                  "arguments")
        arg_group.add_argument("--version-initial",
                               help="initial version of this data model; "
                                    "default: model version")
        return arg_group

    def __init__(self, name: Optional[str] = None):
        super().__init__(name)
        self._initial_version = self._default_initial_version

    # XXX we need a better way of telling whether it's a top-level object
    @staticmethod
    def _is_toplevel_object(node):
        assert node.typename == 'object'

        # XXX command/event object names are relative to their
        #     commands/events; we have to ignore these
        if node.command_in_path or node.event_in_path:
            return False

        # otherwise count the dots in name (if defined) or base (otherwise)
        name_base = node.name or node.base
        comps = name_base.split('.')
        return len(comps) == 2

    # if no --version-initial, default version is the model version
    def _visit_model(self, node: Model) -> Any:
        logger.debug('%s name %s version-initial %s' % (
            node.nicepath, node.name, node.args.version_initial))
        if node.args.version_initial:
            self._initial_version = node.args.version_initial
        else:
            match = re.search(r':(\d+)\.(\d+)$', node.name)
            assert match is not None
            # XXX or should it default to 'major'.0, which is usually the
            #     initial version of a model?
            self._initial_version = '%s.%s' % (match.group(1), match.group(2))

    # special case for top-level object; it should always have a version
    def _visit_object(self, node: Object) -> Any:
        if self._is_toplevel_object(node) and not node.dmr_version and not \
                node.version:
            node.version = self._initial_version
        else:
            self._visit__base(node)

    # special case for componentRef; simply rename dmr:version as version
    # (componentRef version has different semantics)
    # XXX but should still check for unnecessary version here, e.g. it's
    #     unnecessary here:
    #
    #     <object name="Device.CWMPManagementServer." access="readOnly"
    #             minEntries="1" maxEntries="1" version="2.15">
    #       <component ref="ManagementServerCommon" version="2.15"/>
    #     </object>
    #
    # note that this is only visited when --thisonly is set
    @staticmethod
    def _visit_componentref(node: ComponentRef) -> Any:
        if node.dmr_version:
            if not node.version:
                node.version, node.dmr_version = node.dmr_version, None
            elif node.version != node.dmr_version:
                logger.warning('%s: mismatched dmr:version %s and version '
                               '%s attributes (dmr:version retained)' % (
                                   node.nicepath, node.dmr_version,
                                   node.version))

    # the dmr_version and version attributes are defined on _Base
    def _visit__base(self, node: _Base) -> Any:
        # if still has dmr:version, clear it and set version if needed
        if node.dmr_version:
            if not node.version:
                inherited = node.version_inherited or self._initial_version
                if node.dmr_version == inherited:
                    logger.debug('%s: version %s cleared because it '
                                 'matches inherited version' % (
                                     node.nicepath, node.dmr_version))
                else:
                    node.version = node.dmr_version
                node.dmr_version = None
            elif node.version != node.dmr_version:
                logger.warning('%s: mismatched dmr:version %s and version '
                               '%s attributes (dmr:version retained)' % (
                                   node.nicepath, node.dmr_version,
                                   node.version))

        # otherwise if it has a version, warn if it's not needed or invalid
        elif node.version and node.parent.version_inherited:
            initial_version = self._initial_version
            parent_version = node.parent.version_inherited
            node_version = node.version

            initial_version_ = self._version_components(initial_version)
            parent_version_ = self._version_components(parent_version)
            node_version_ = self._version_components(node_version)

            node_version_clamped_ = max(node_version_, initial_version_)

            # XXX this can give some spurious messages for USP, due to clamped
            #     versions; the suppressed check avoids these but
            #      suppresses some problems; need a better solution
            if (True or node_version_ > initial_version_) and \
                    node_version_ == parent_version_:
                logger.info('%s: version %s same as parent version %s ('
                            'unnecessary)' % (
                                node.nicepath, node_version, parent_version))

            if node_version_clamped_ < parent_version_:
                logger.warning('%s: version %s less than parent version %s' % (
                    node.nicepath, node_version, parent_version))

    # this supports up to three-level versions (any additional levels are
    # ignored)
    @staticmethod
    def _version_components(version: str) -> Tuple[int, int, int]:
        components = [int(i) for i in version.split('.')]
        if len(components) < 3:
            components += (3 - len(components)) * [0]
        components = tuple(components[:3])
        components = cast(Tuple[int, int, int], components)
        return components
