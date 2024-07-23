"""File utilities."""

# Copyright (c) 2019-2023, Broadband Forum
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

import glob
import os
import os.path
import re

from typing import Optional

from .logging import Logging
from .utility import FileName, Spec, Utility

logger = Logging.get_logger(__name__)


class File:
    """File class, providing file utilities."""

    # regex used for searching for specs in XML files
    _re_xml_spec = re.compile(r'spec\s*=\s*[\'"](.*?)[\'"]')

    # cache (optimization)
    # XXX assumes that a given file is always searched for in the same way;
    #     could be cleverer...
    _cache = {}

    @classmethod
    def find(cls, path: str, *, dirs: Optional[list[str]] = None,
             nocurdir: bool = False, recursive: bool = False,
             spec: Optional[Spec] = None, ignore_spec: bool = False) \
            -> Optional[str]:
        """Find a file.

        Any ``~user`` or ``$variable`` strings in the file path and directory
        names will be expanded.

        Args:
            path: The file path.
            dirs: The directories to search (the current directory is
                inserted at the beginning of this list if not already there
                unless suppressed by ``nocurdir``).
            nocurdir: Whether not to insert the current directory into ``dirs``
                if not already there).
            recursive: Whether to search directories recursively (the
                current directory is never searched recursively).
            spec: The expected `Dm_document.spec`. If specified, only files
                with matching specs will be considered.
            ignore_spec: If ``True``, the spec is ignored (this allows other
                problems to be detected, e.g., when a local file spec has
                been changed but the referencing file spec hasn't been changed)

        Returns:
            The full path of the located file, or ``None`` if not found.
        """

        # check the cache
        # XXX this is flawed because the cache uses the supplied filenames,
        #     not the real paths
        if False and path in cls._cache:
            return cls._cache[path]

        drive, dir_, file = Utility.path_split_drive(path)

        # an explicit directory in the path overrides dirs
        dirs_ = [dir_] if dir_ else dirs[:] if dirs else []

        # expand ~user and $vars in file and dirs
        # XXX we quietly ignore any non-existent dirs; should detect this and
        #     warn about it earlier?
        file = os.path.expanduser(os.path.expandvars(file))
        dirs_ = [os.path.expanduser(os.path.expandvars(d)) for d in dirs_ if
                 os.path.exists(d)]

        # unless suppressed, prefix the current directory if not already there
        # and if the supplied path didn't have an explicit directory
        # XXX could always search the current file's directory first?
        if not nocurdir and not dir_ and not any(
                {os.path.samefile(d, os.curdir) for d in dirs_}):
            dirs_.insert(0, os.curdir)

        # find the file; this returns None or the real path
        realpath = cls.__findfile(file, dirs=dirs_, recursive=recursive,
                                  drive=drive, spec=spec,
                                  ignore_spec=ignore_spec)

        # if found, cache and return the real path
        if realpath:
            cls._cache[path] = realpath
        return realpath

    # noinspection GrazieInspection
    @classmethod
    def __findfile(cls, file: str, *, dirs: Optional[list[str]] = None,
                   recursive: bool = False, drive: Optional[str] = None,
                   spec: Optional[Spec] = None, ignore_spec: bool = False) \
            -> Optional[str]:
        logger.info(f'find {file!r} spec {spec!r}')

        # parse name into its component parts
        n = FileName(file)
        s = spec if spec else Spec()

        # if not specified in file, take i, a, c from spec
        if not n.i:
            n.i = s.i
        if not n.a:
            n.a = s.a
        if not n.c:
            n.c = s.c
        logger.debug(f'  file, spec -> {n!r}')

        # form glob patterns; always search for the actual file first
        patterns = [file]
        if n.is_valid:
            ip = f'-{n.i}' if n.i else '-[0-9]*'
            ap = f'-{n.a}' if n.a else '-[0-9]*'
            cp = f'-{n.c}' if n.c else '-[0-9]*'
            if not n.i:
                patterns += [f'{n.tr}-{n.nnn}{ip}{n.label}{n.ext}']
            elif not n.a:
                patterns += [f'{n.tr}-{n.nnn}{ip}{ap}{n.label}{n.ext}']
            else:
                patterns += [f'{n.tr}-{n.nnn}{ip}{ap}{cp}{n.label}{n.ext}']
        logger.debug(f'  patterns {patterns!r}')

        # expand the glob patterns in each directory
        # XXX never search the current directory recursively; should do if it
        #     was specified explicitly? (note that symlinks are followed)
        for dir_ in dirs:
            recursive_ = recursive and not os.path.samefile(dir_, os.curdir)
            for i, pattern in enumerate(patterns):
                path = drive + (os.path.join(dir_, '**',
                                             pattern) if recursive_ else
                                os.path.join(dir_, pattern))
                logger.debug(f'    trying {path!r}')
                matches = glob.glob(path, recursive=recursive)
                if matches:
                    # if the first pattern (actual file) matches:
                    # - if no spec was supplied (or ignoring the spec), always
                    #   return it (will typically ignore the spec when only a
                    #   single file was specified on the command line; in this
                    #   case want to open local files can detect when a
                    #   local file spec has been changed but the referencing
                    #   file spec hasn't been changed)
                    # - otherwise, always check the spec (will typically be the
                    #   case when multiple files were specified on the command
                    #   line; in this case, e.g., calculating diffs, ignoring
                    #   the spec would be very dangerous)
                    if i == 0 and (spec is None or ignore_spec):
                        logger.info(f'-> actual {matches[0]!r}')
                        return os.path.realpath(matches[0])

                    # find the latest matching file (may need to peek into it)
                    latest = cls.__latest(matches, n)
                    if latest is not None:
                        logger.info(f'-> latest {latest!r}')
                        return os.path.realpath(latest)

        # fail if no latest version was found
        return None

    # noinspection GrazieInspection
    @classmethod
    def __latest(cls, paths: list[str], orig: FileName) -> Optional[str]:
        assert paths
        latest = None
        for path in paths:
            logger.debug(f'      path {path!r}')
            *_, file = Utility.path_split_drive(path)

            # parse name into component parts
            this = FileName(file)

            # if the parse failed or the necessary fields don't match,
            # ignore this path
            if (not this.is_valid or this.tr != orig.tr or
                    this.nnn != orig.nnn or this.label != orig.label or
                    this.ext != orig.ext):
                logger.debug(f'        {this!r} !~ {orig!r}')
                continue

            # if i but not a is specified, we have to get it from the file
            # (i implies versioned, so this avoids opening support files)
            if this.i and not this.a:
                spec = cls.__peekspec(path)
                logger.debug(f'        peek {this!r} -> {spec!r}')
                if spec.a != orig.a:
                    logger.debug(f'        {spec!r} !~ {orig!r}')
                    continue

            # i, a and c are strings, so convert to ints for comparison
            # XXX ii originally defaulted to 0 but surely 1 is correct?
            ii = int(this.i) if this.i else 1
            ai = int(this.a) if this.a else 0
            ci = int(this.c) if this.c else 0

            # keep track of the latest
            if latest is None or (ii, ai, ci) > latest[1]:
                latest = path, (ii, ai, ci)

        return latest[0] if latest else None

    @classmethod
    def __peekspec(cls, path: str) -> Optional[Spec]:
        with open(path) as fd:
            for line in fd.readlines():
                if line.find('spec') >= 0:
                    match = cls._re_xml_spec.search(line)
                    if match:
                        return Spec(match.group(1))
        return None
