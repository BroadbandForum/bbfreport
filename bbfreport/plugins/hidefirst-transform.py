"""Hide the first document."""

# Copyright (c) 2023-2024, Broadband Forum
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

from bbfreport.node import _Base, _Document, Root

from typing import cast, Optional


def get_documents(document: _Document, *,
                  documents: Optional[set[_Document]] = None) -> \
        set[_Document]:
    if documents is None:
        documents = set()
    # XXX _Document doesn't have imports, but both Dm_document and Dt_document
    #     do
    # noinspection PyUnresolvedReferences
    for import_ in document.imports:
        for xml_file in import_.xml_files:
            documents.add(xml_file.document)
            get_documents(xml_file.document, documents=documents)
    return documents


def visit(root: Root, logger) -> None:
    # get the un-hidden command-line documents
    documents = []
    for xml_file in root.xml_files:
        document = xml_file.document
        if document in documents:
            logger.info('already saw %s' % document.keylast)
        elif document.is_hidden:
            logger.info('ignored hidden %s' % document.keylast)
        else:
            documents.append(document)
            logger.info('added %s' % document.keylast)

    # if there are multiple documents, hide the first one (the expected use
    # case is that there are two; if necessary this transform can be applied
    # more than once)
    if len(documents) > 1:
        documents[0].hide()
        logger.info('hid %s' % documents[0].keylast)

        # also need to hide files that are imported (directly or indirectly)
        # by the first document but not any of the other documents
        documents_not_to_hide = set()
        for document in documents[1:]:
            get_documents(document, documents=documents_not_to_hide)
        documents_to_hide = get_documents(documents[0]) - documents_not_to_hide
        for document in documents_to_hide:
            # XXX this shouldn't be necessary, but _Document is currently a
            #     _Mixin, not a _Base
            document = cast(_Base, document)
            document.hide()
            logger.info('hid %s' % document.keylast)
