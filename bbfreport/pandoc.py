"""Pandoc installation and usage instructions.

It's currently necessary to use pandoc to convert markdown (generated by the
markdown format) to HTML.

The instructions are included in generated markdown and in the package
README."""

# Copyright (c) 2024, Broadband Forum
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


# XXX for now, these instructions must be manually copied into PROJECT.yaml
#     (not really a problem, because use of pandoc is only temporary)
def instructions() -> str:
    return '''
The report tool doesn't yet generate HTML directly. To generate HTML, use the
`markdown` format to generate markdown, and then run [pandoc] to generate HTML.

The `markdown` format generates an extended version of [commonmark]
(referred to as commonmark_x). To process it, you need to install the 
following:

* pandoc 3.0 or later: This might already be installed, or you might 
be able to install it using the OS package manager. If not, you can get it 
from <https://github.com/jgm/pandoc/releases>

* list-table filter: Get this from 
<https://github.com/pandoc-ext/list-table>

* logging library: Get this from
<https://github.com/pandoc-ext/logging>

* custom HTML writer: Get this from
<https://github.com/BroadbandForum/pandoc-html-writer>

Assuming that you've already installed pandoc, and that you want to process
`model.md`, you can do this:

    % git clone https://github.com/pandoc-ext/list-table
    Cloning into 'list-table'...
    ...
    % ln -s list-table/list-table.lua

    % git clone https://github.com/pandoc-ext/logging
    Cloning into 'logging'...
    ...
    % ln -s logging/logging.lua 

    % git clone https://github.com/BroadbandForum/pandoc-html-writer
    Cloning into 'pandoc-html-writer'...
    ...
    % ln -s pandoc-html-writer/html-writer.lua
    % ln -s pandoc-html-writer/html-derived-writer.lua

    % report.py model.xml --format markdown --output model.md

    % pandoc model.md --standalone --from commonmark_x \\
        --lua-filter list-table.lua --to html-derived-writer.lua \\
        --output model.html

Refer to the pandoc documentation for more information, e.g., on how to
avoid the need for the soft links.
    
[commonmark]: https://commonmark.org
[pandoc]: https://pandoc.org
'''[1:-1]