"""Dump the node tree (or a subset thereof)."""

# XXX should provide more controls, e.g. dump destination


# XXX could remove this, or add more documentation
def _add_arguments_(arg_parser):
    arg_group = arg_parser.add_argument_group('dump transform arguments')
    arg_group.add_argument('--dump', action='store_true',
                           help='run the dump transform')
    return arg_group


def _begin_(_, args):
    return {'hierarchical': args.hierarchical}


def helper(node, level, args):
    indent = level * '  '
    typename = node.typename
    name = node.format(brief=args.hierarchical)
    print('%s%s %s' % (indent, typename, name))


def visit__document(node, level, args):
    helper(node, level, args)


def visit__model_item(node, level, args):
    helper(node, level, args)


def visit__arguments(node, level, args):
    helper(node, level, args)
