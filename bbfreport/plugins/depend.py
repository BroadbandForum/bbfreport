"""Dependencies report format plugin."""

# Copyright (c) 2023, Broadband Forum
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

import os.path

from typing import cast, Optional

from ..node import Xml_file

# this is written to the output file
HEADER = '''
# makefiles should define a callable DEPENDENCIES variable that expects two
# arguments:
#
#   $(1) - the base name (with no file extension) of the supplied XML file
#   $(2) - a space-separated list of relative paths for all the XML files on
#          which the supplied XML file depends (starting with the supplied
#          XML file)
#
# For example (direct dependencies):
#
# EXTS = .html -full.xml
#
# define DEPENDENCIES
#   $(eval $(EXTS:%=$(1)%): $(2))
# endef
#
# or (copying the dependent files to the current directory):
#
# define DEPENDENCIES
#   $(eval $(EXTS:%=$(1)%): $(notdir $(2)))
#   $(foreach PATH, $(2),
#     $(eval $(notdir $(PATH)): $(PATH); @install -Cv -m 0644 $$< $$@)
#   )
# endef

'''[1:]  # ignore the first character, which is a newline


def _post_init_(args, logger) -> Optional[bool]:
    if len(args.file) > 1:
        logger.error('can only generate dependencies for a single file')
        return True

    if len(args.filter) == 0:
        args.filter = ['xml_file', 'dm_document', 'import', 'file', 'spec']


def _begin_(root, args):
    # we already checked that there's only one command-line file
    if len(root.xml_files) == 1:
        supplied_file = root.xml_files[0].keylast

        # use a dict to simulate an ordered set
        dependencies = {}

        for xml_file in root.findall(Xml_file):
            xml_file = cast(Xml_file, xml_file)
            dependencies[os.path.relpath(xml_file.keylast)] = True

            for import_ in xml_file.dm_document.imports:
                assert len(import_.xml_files) == 1
                dependencies[
                    os.path.relpath(import_.xml_files[0].keylast)] = True

        args.output.write(HEADER)

        supplied_file_name, _ = \
            os.path.splitext(os.path.basename(supplied_file))
        args.output.write('$(call DEPENDENCIES,%s,%s)\n' % (
            supplied_file_name, ' '.join(list(dependencies))))
