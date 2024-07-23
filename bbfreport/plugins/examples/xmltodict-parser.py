"""Xmltodict XML parser plugin.

Note:
    This works at some level, but is probably doomed to failure because it
    can't fully preserve order. The (default) `ExpatParser` is recommended.
"""

# Copyright (c) 2019, Broadband Forum
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

import xmltodict

from ...parser import Data, Parser
from ...utility import Utility

# XXX maybe shouldn't use this, because it doesn't preserve 'choice' order,
#     e.g. [component, parameter, component] will be collected by
#     element name

# XXX also, I think the default setting is to strip whitespace; can't do
#     this!


class XmltodictParser(Parser):
    @staticmethod
    def _parse(path: str, **_kwargs) -> Data:
        # parse the file to a dictionary
        # XXX should check that there are no attribute/element name
        #     conflicts; the '#' prefix might actually be good?
        # XXX note that we already need to deal with '#text',
        #     e.g. description
        # XXX need to process namespaces to ensure canonical prefixes
        data = xmltodict.parse(open(path, 'r+b'), attr_prefix='',
                               cdata_key='atom')

        # convert to the desired tuple
        return XmltodictParser._dict_to_tuple(data)

    @staticmethod
    def _dict_to_tuple(value):
        # XXX returning a tuple is less efficient (?) but easier to debug
        # XXX should define this function ONCE and ONCE ONLY
        def t(g):
            return tuple(g) if __debug__ else g

        def aslist(v_):
            return v_ if isinstance(v_, list) else [v_]

        if not isinstance(value, dict):
            # lists are handled below and so shouldn't occur here
            assert not isinstance(value, list)
            return value
        else:
            # expand lists up a level (undoing damage done by xmltodict!)
            return t((Utility.clean_name(n),
                      XmltodictParser._dict_to_tuple(i)) for n, v in
                     value.items() for i in aslist(v))
