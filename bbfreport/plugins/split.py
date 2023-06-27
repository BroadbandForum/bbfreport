"""Split transform plugin."""

# Copyright (c) 2020-2022, Broadband Forum
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

from bbfreport.node import _HasContent, Dm_document


# note:
# - splitting is only relevant for text nodes, i.e. descriptions etc.
# - could consider also splitting comments?
# - any multiple blank lines will be replaced with a single blank line
# - can assume that Utility.whitespace() has been called
def split(text: str) -> str:
    """Split newline-separated paragraphs into two-newline-separated
    paragraphs.

    Args:
        text: The text to split.

    Returns:
        The split text.
    """

    return re.sub(r'\n+', r'\n\n', text)


visited = set()


def visit__has_content(node: _HasContent, logger) -> Any:
    """Split `_HasContent` node paragraphs unless already split."""

    # ignore if already split
    # XXX should have a better API to xmlns_dmr etc.
    if node.xmlns_dmr_inherited and node.xmlns_dmr_inherited != \
            Dm_document.XMLNS_DMR_ORIGINAL_URN:
        pass

    # XXX in complex cases (when?) nodes can potentially be visited
    #     more than once; Visitor should prevent this?
    # XXX this can also happen if the transform is specified multiple
    #     times on the command line
    elif (node_id := id(node)) in visited:
        logger.warning_func('%s: already visited' % node.nicepath)

    # otherwise, split paragraphs and note that it's been visited
    else:
        old = node.text
        new = split(old)
        if new != old:
            node.text = new
        visited.add(node_id)
