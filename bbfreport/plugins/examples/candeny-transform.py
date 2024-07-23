"""Candeny (can deny) transform plugin."""

# Copyright (c) 2022, Broadband Forum
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

from typing import Any

from ...logging import Logging
from ...node import Parameter
from ...transform import Transform

logger = Logging.get_logger(__name__)


class CandenyTransform(Transform):
    """Candeny (can deny) transform plugin."""

    data = {}

    def visit_parameter(self, node: Parameter) -> Any:
        if node.activeNotify == 'canDeny':
            name = node.name
            objpath = node.objpath
            category = \
                'alias' if name == 'Alias' else \
                'static' if re.search(
                        r'Name|Description|FirstUseDate|Possible', name) else \
                'static' if re.search(r'\.LocalDisplay\.', objpath) else \
                'time' if re.search(r'Last(Change|Update)', name) else \
                'time' if re.search(r'TimeRemaining', name) else \
                'time' if re.search(r'(CPU|CurrentLocal|Running|Up)Time',
                                    name) else \
                'capability' if re.search(r'Capabilit(y|ies)', objpath) else \
                'capability' if 'Max' in objpath else \
                'test' if '.TestParams.' in objpath else \
                'stats' if re.search(r'\.(|Flow|Queue|RMON)Stats\.', objpath) \
                else \
                'stats' if re.search(r'\.(Metric|UDPEchoConfig)\.', objpath) \
                else \
                'stats' if re.search(r'^(Rx|Tx)', name) else \
                'stats' if re.search(r'^Total', name) else \
                'stats' if re.search(r'('
                                     r'Bytes|Errors|Packets|Received|Stats)$',
                                     name) else \
                'daniel' if re.search(
                        r'\.Cellular.*Interface.*Status|'
                        r'\.ZigBee.*RoutingTable.*Status|'
                        r'\.WiFi.*AssociatedDevice.*MACAddress|'
                        r'\.WiFi.*AssociatedDevice.*AuthenticationState|'
                        r'\.PPP.*CurrentMRUSize', objpath) else \
                'misc'
            self.data.setdefault(category, [])
            self.data[category] += [objpath]

            if category in {'alias', 'capability', 'static', 'daniel'}:
                node.activeNotify = None

    def _visit_end(self, node, **kwargs):
        if node.args.thisonly:
            return

        total = 0
        for category, paths in sorted(self.data.items(),
                                      key=lambda i: -len(i[1])):
            print('%s (%d)' % (category, len(paths)))
            for path in paths:
                print('  %s' % path)
            total += len(paths)
        print('total (%d)' % total)
