# XXX add license and description

from ..node import Root


def visit(root: Root, logger):
    # check whether there are any top-level models
    models = [model for xml_file in root.xml_files
              for model in xml_file.dm_document.models]
    if models:
        return

    # if there are no models, check whether there are any component imports
    # and definitions (ignoring internal and Diffs components)
    ignore = lambda comp: comp.name.startswith('_') or \
                          comp.name.endswith('Diffs')
    components = [component for xml_file in root.xml_files for imp in
                  xml_file.dm_document.imports for component in imp.components
                  if not ignore(component)] + [component for xml_file in
                                               root.xml_files for component in
                                               xml_file.dm_document.components
                                               if not ignore(component)]
    if not components:
        return

    # if there are components, use the final file on the command line
    xml_file = root.xml_files[-1]
    dm_document = xml_file.dm_document
    assert dm_document

    # derive the model name from the DM document spec
    spec = dm_document.spec
    name = '%s-%s:%s.%s' % (spec.tr.upper(), spec.nnn, spec.i, spec.a) if \
        spec.is_valid else 'TR-999:1.0'

    # create the model
    component_refs = tuple(('component', (('ref', component.name),),)
                           for component in components)
    data = (('model', (('name', name),) + component_refs),)
    model = dm_document.merge(data=data, stack=(xml_file,))

    # XXX this is needed to perform any deferred merges; it should be done
    #     automatically by the (public) merge() method
    model.merge(stack=(xml_file, dm_document))
