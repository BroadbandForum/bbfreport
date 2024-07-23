"""Exceptions.
"""

# Copyright (c) 2019-2022, Broadband Forum
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

from typing import Optional


class BBFReportException(Exception):
    """Base ``bbfreport`` exception."""

    def __init__(self, text: str):
        """Store the supplied text."""
        self._text = text

    def __str__(self):
        """Return the supplied text."""
        return self._text


# XXX provide this for backwards compatibility (note that this module used to
#     be called 'exceptions')
GeneralException = BBFReportException


class FormatException(BBFReportException):
    """Format exception."""


class MacroException(BBFReportException):
    """Macro expansion exception."""


# XXX should make this more specific?
class NodeException(BBFReportException):
    """Node tree traversal exception."""

    def __init__(self, text: str, name: Optional[str] = None):
        """``name`` should be the name of the affected node, e.g., for use
        in error messages."""

        super().__init__(text)
        self._name = name

    @property
    def name(self) -> Optional[str]:
        return self._name


class ParserException(BBFReportException):
    """DM Instance parser exception."""


class PluginException(BBFReportException):
    """Plugin instantiation exception."""
