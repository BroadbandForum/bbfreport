"""Output the full paths of all data model items, one per line."""


def visit__model_item(node, args):
    if node.typename not in {'model', 'profile'}:
        args.output.write(f'{node.objpath}\n')
