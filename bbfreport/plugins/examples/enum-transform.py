"""Enumeration value transform plugin."""

# Copyright (c) 2021, Broadband Forum
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

from typing import Optional

from ...logging import Logging
from ...node import Enumeration, Root, Units
from ...transform import Transform

logger = Logging.get_logger(__name__)


class EnumTransform(Transform):
    """Enumeration value transform plugin.
    """

    all_units: dict[str, set[str]] = {}

    @staticmethod
    def _visit_enumeration(node: Enumeration) -> None:
        EnumTransform.__check_value(node.value, path=node.nicepath,
                                    checks={'whitespace'})

    @staticmethod
    def _visit_units(node: Units) -> None:
        value = node.value
        path = '%s.%s' % (node.nicepath, value)
        EnumTransform.__check_value(value, path=path,
                                    checks={'whitespace'})

        # collect all units strings, keyed by a common root
        key = re.sub(r'\s+', '', value).lower()
        for substring, replacement in {
            'bitspersecond': 'b/s',
            'bits/s': 'b/s',
            'bit/s': 'b/s',
            'bps': 'b/s',
            'bytes': 'byte',
            'kilo': 'k',
            'mega': 'm',
            'milli': 'm',
            'octets': 'byte',
            'octet': 'byte',
            'percentage': '%',
            'percent': '%',
            'seconds': 's',
            'zigbee': ''
        }.items():
            if substring in key:
                key = key.replace(substring, replacement)
        EnumTransform.all_units.setdefault(key, set())
        EnumTransform.all_units[key] |= {node.value.strip()}

    @staticmethod
    def __check_value(value: str, *, path: str = 'unknown',
                      checks: Optional[Set[str]] = None) -> None:
        if checks is None:
            checks = {}

        if 'whitespace' in checks and re.match(r'^\s|\s$', value):
            logger.warning('%s has leading or trailing whitespace' % path)

        if 'uppercase' in checks and re.match(r'^[a-z]', value):
            logger.warning('%s starts with a lower-case letter' % path)

        if 'lowercase' in checks and re.match(r'^[A-Z]', value):
            logger.warning('%s starts with an upper-case letter' % path)

        if 'internalspace' in checks and re.match(r'^\S+\s+\S+', value):
            logger.warning('%s contains internal whitespace' % path)

    def _visit_end(self, node: Root, **kwargs):
        for key, values in sorted(EnumTransform.all_units.items(),
                                  key=lambda i: i[0]):
            print('units key %r -> %r' % (key, sorted(list(values))))
