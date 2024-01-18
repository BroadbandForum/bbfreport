import csv

columns = {
    'Name': lambda item: item.name,
    'Type': lambda item: (item.syntax.primitive_inherited
                          if item.typename == 'parameter' else item.typename),
    'Write': lambda item: write_string(getattr(item, 'access', '')),
    'Description': lambda item: (
            item.description.content.markdown.strip() or ''),
    'Object Default': lambda item: (
        item.syntax.default.value if item.typename == 'parameter' and
        item.syntax.default.type == 'object' else ''),
    'Version': lambda item: item.version_inherited
}

writer = None


def write_string(access):
    assert access in {'', 'readOnly', 'readWrite'}
    return {'readOnly': 'R', 'readWrite': 'W'}.get(access, '')


def _begin_(_, args):
    global writer
    writer = csv.DictWriter(args.output, fieldnames=columns.keys())
    writer.writeheader()


# these are Model, Object, Parameter etc. instances
# noinspection PyUnresolvedReferences
def visit__model_item(item):
    assert writer is not None
    writer.writerow({key: func(item) for key, func in columns.items()})


# alternative; visit__model_item() will be called too (is this wrong?)
# noinspection PyUnresolvedReferences,PyUnusedLocal
def visit_parameter(param):
    # XXX this is temporarily disabled
    return
    # noinspection PyUnreachableCode
    assert writer is not None
    writer.writerow(
            {'Name': param.name,
             'Type': param.syntax.primitive_inherited,
             'Write': write_string(param.access),
             'Description': param.description.content.markdown.strip() or '',
             'Object Default': (param.syntax.default.value if
                                param.syntax.default.type == 'object' else ''),
             'Version': param.version_inherited})


# these are Input and Output, which aren't _ModelItem instances
# noinspection PyUnresolvedReferences
def visit__arguments(item):
    assert writer is not None
    writer.writerow({'Name': item.keylast, 'Type': item.typename,
                     'Description': '%s arguments.' % item.keylast,
                     'Version': item.version_inherited})
