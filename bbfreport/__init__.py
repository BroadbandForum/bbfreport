"""The ``bbfreport`` package."""

# Copyright (c) 2022-2023, Broadband Forum
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

# XXX should add more info here, but avoid duplication with setup.py
# XXX is it OK to invent new dunder names such as __tool_name__?
__tool_name__ = 'report.py'
__version__ = '2.0.1'  # trailing '+' means 'interim version'
__version_date__ = '2023-06-27'


# use this when reporting the version
def version(*, as_markdown: bool = False) -> str:
    # derive the PyPI package name and URL
    pypi_package = __package__.split('.')[0]
    pypi_url = 'https://pypi.org/project/%s' % pypi_package

    # if requested, convert to markdown
    bbf, package = 'Broadband Forum', pypi_package
    if as_markdown:
        bbf = '[%s](https://www.broadband-forum.org)' % bbf
        package = '[%s](%s)' % (pypi_package, pypi_url)

    return '%s %s v%s (%s version)' % (bbf, package,
                                       __version__, __version_date__)


from .content import Content
from .exception import BBFReportException
from .format import Format
from .macro import Macro
from .macros import DummyMacros
# XXX it's hard to know which node types to import; perhaps the main "public"
#     elements, and others as needed (can always get them from bbfreport.node)
from .node import DataType, DataTypeAccessor, Dm_document, Root, Xml_file
from .parser import Parser
from .plugin import Plugin
from .property import Null
from .transform import Transform
# XXX should import more? or just import directly from bbfreport.utility
from .utility import Utility, Version
