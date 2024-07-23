"""Logging support."""

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

import logging
import os
import re


class Logging:
    names = set()
    """Logger names. This is set to the value of the multi-valued ``-L``
    (``--loggername) command-line option."""

    # logger name pattern; intended for __name__ or python file name
    name_pattern = re.compile(r'''
        ^
        (?P<name>.*?)
        (?P<sep>-?)
        (?P<type>
            [pP]arser
        |
            [tT]ransform
        |
            [fF]ormat
        )
        (?P<ext>\.py)?
        $
    ''', re.VERBOSE)

    @classmethod
    def get_logger(cls, name: str, *, ispath: bool = False) -> logging.Logger:
        """Create a new logger with a name derived from the supplied name,
        and add a filter that will only output info and debug messages if
        the logger name is in `Logging.names`.

        The supplied name is, by default, assumed to be the module name
        (``__name__``), and the logger name is its last component. If the
        supplied name is a path, the logger name is the filename part of the
        path.

        Args:
            name: A name from which to derive the logger name.
            ispath: Whether ``name`` is a path and therefore should have its
                directory and file extension removed.

        Returns:
            A `logging.Logger` instance.
        """

        # if not a path, it's a module name, so select its final component
        if not ispath:
            name = name.split('.')[-1]

        # otherwise, select the filename part of the path
        else:
            (name, _) = os.path.splitext(os.path.basename(name))

        # if it matches the logger name pattern, replace with the name part
        match = cls.name_pattern.match(name)
        if match:
            name = match['name']

        # create the logger
        # XXX what if there are naming conflicts?
        logger = logging.getLogger(name)

        # add the filter
        logger.addFilter(
                lambda r: r.levelno > logging.INFO or name in cls.names)

        # return the logger
        return logger

    # factory methods that return info() etc. functions that will call
    # logger.info(node.objpath + ': ' + msg) etc.
    # (note that node.fullpath() is not called until the function is called)
    @staticmethod
    def report_func(node, func):
        return lambda text='': func('%s: %s' % (node.nicepath, text))

    @staticmethod
    def error_func(node, logger):
        return Logging.report_func(node, logger.error)

    @staticmethod
    def warning_func(node, logger):
        return Logging.report_func(node, logger.warning)

    @staticmethod
    def info_func(node, logger):
        return Logging.report_func(node, logger.info)

    @staticmethod
    def debug_func(node, logger):
        return Logging.report_func(node, logger.debug)
