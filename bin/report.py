#!/usr/bin/env python3

"""Broadband Forum (BBF) Data Model Report Tool.

The tool processes one or more Data Model (DM) XML files. In outline:

    Process the command line arguments.
    Create an empty node tree.

    For each DM file specified on the command line:
        Parse the file using the specified parser (default: expat).
            (this updates the node tree)

    For each specified transform (default: none):
        Transform the node tree.

    Output the specified format (default: null).
"""

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

import argparse
import cProfile
import logging
import os
import pstats
import sys
import time

# dicts are assumed to retain their insertion order (requires python 3.6 or
# 3.7), but the tool has been developed with python 3.10 and may make other
# assumptions, so require at least this version
# XXX for now only require python 3.9 to avoid need to re-build various Docker
#     images
# XXX should put this check in a library init function?
MIN_VERSION = (3, 9)

# noinspection PyStringFormat
assert sys.version_info[:2] >= MIN_VERSION, "You're using python %d.%d; you " \
                                            "must use at least python %d.%d"\
                                            % (sys.version_info[:2] +
                                               MIN_VERSION)

# if the bbfreport package is not installed, insert the current working
# directory into the search path, so we can directly execute the tool from
# the code
try:
    from bbfreport import BBFReportException, Format, Null, Parser, Plugin, \
        Root, Transform, Utility, version
except ModuleNotFoundError:
    sys.path.insert(0, os.getcwd())
    from bbfreport import BBFReportException, Format, Null, Parser, Plugin, \
        Root, Transform, Utility, version

nice_list = Utility.nice_list

# XXX want just the name part; need some utilities / rules / conventions
prog_basename = os.path.basename(__file__)
(prog_root, _) = os.path.splitext(prog_basename)
logger = logging.getLogger(prog_root)
logger.addFilter(
        lambda r: r.levelno > 20 or prog_root in Utility.logger_names)

# XXX should change everywhere to use list.append(item) rather than += [item]?

# XXX note that 'arg: Foo = None' is implicitly 'arg: Optional[Foo] = None';
#     you don't need the 'Optional'


# this is called without arguments when generating documentation
def get_argparser(argv=None, opts=None):
    if argv is None:
        argv = sys.argv

    # XXX 0, 1, 2 are temporarily supported for backwards compatibility
    deprecated_loglevels = ('0', '1', '2')
    loglevels = ('none', 'fatal', 'error', 'warning', 'info',
                 'debug') + deprecated_loglevels

    default_plugindir = []
    default_filter = []
    default_output = sys.stdout
    default_loglevel = 'warning'
    # warnings, errors and critical errors should always be output (this
    # assumes that individual modules use a recommended log filter)
    default_loggername = ['report']

    formatter_class = argparse.RawDescriptionHelpFormatter
    arg_parser = argparse.ArgumentParser(prog=prog_basename,
                                         description=__doc__,
                                         fromfile_prefix_chars='@',
                                         formatter_class=formatter_class,
                                         add_help=False)

    arg_parser.add_argument("-P", "--plugindir", type=str, action="append",
                            default=default_plugindir,
                            help="directories to search for plugins ("
                                 "parsers, transforms and formats)")
    arg_parser.add_argument("-I", "--include", type=str, action="append",
                            help="directories to search (recursively) for "
                                 "included/imported files (is also used for "
                                 "files specified on the command line)")
    arg_parser.add_argument("-C", "--nocurdir", action="store_true",
                            help="don't automatically search the current "
                                 "directory")
    arg_parser.add_argument("-F", "--filter", type=str, action="append",
                            default=default_filter,
                            help="filter specification, which is applied just "
                                 "after parsing; experts only! default: %r" %
                                 default_filter)
    # XXX temporarily also allow --outfile (which is the old option name)
    arg_parser.add_argument("-o", "--output", "--outfile",
                            type=argparse.FileType('w'),
                            default=default_output,
                            help="name of output file (--outfile is "
                                 "deprecated); default: %s" %
                                 default_output.name)
    arg_parser.add_argument("-l", "--loglevel", choices=loglevels,
                            default=default_loglevel,
                            help="logging level; default: %r" %
                                 default_loglevel)
    # XXX would like to be able to provide choices
    arg_parser.add_argument("-L", "--loggername", type=str, action="append",
                            default=default_loggername,
                            help="module names for which to enable logging, "
                                 "e.g. 'file', 'node' or 'expatParser'; "
                                 "default: %r" % default_loggername)

    arg_parser.add_argument("-T", "--thisonly", action="store_true",
                            help="only output definitions defined in the "
                                 "files on the command line, not those from "
                                 "imported files")
    arg_parser.add_argument("-A", "--all", action="store_true",
                            help="request the output format to report all "
                                 "nodes even if they're not used (only "
                                 "affects the output format; has no  effect "
                                 "on transforms)")
    arg_parser.add_argument("-S", "--show", action="store_true",
                            help="request the output format to highlight "
                                 "nodes that were added in the latest "
                                 "version (only affects the output format; "
                                 "has no  effect on transforms)")
    # XXX should use a different logger for this?
    arg_parser.add_argument("-D", "--debugpath", type=str,
                            help="path to debug (regular expression); if "
                                 "set, forces --loglevel=info")

    # the remaining options don't have short forms
    arg_parser.add_argument("--profile", action="store_true",
                            help="enable profiling; currently experimental "
                                 "with hard-coded settings")

    # XXX should we have an option to control recursive search?
    arg_parser.set_defaults(recursive=True)

    # parse known arguments (all but plugin- and help-related arguments)
    args, argv_remaining = arg_parser.parse_known_args(argv[1:])

    loglevel_map = {'none': 9999, 'fatal': logging.FATAL,
                    'error': logging.ERROR, 'warning': logging.WARNING,
                    'info': logging.INFO, 'debug': logging.DEBUG,
                    '0': logging.WARNING, '1': logging.INFO,
                    '2': logging.DEBUG}
    assert set(loglevel_map.keys()) >= set(loglevels), \
        'loglevel(s) %s are missing from loglevel map' % \
        (set(loglevels) - set(loglevel_map.keys()),)

    # note that logging levels increase from 'debug' through 'fatal'
    if args.debugpath:
        if loglevel_map[args.loglevel] > logging.INFO:
            args.loglevel = 'info'

    logging.basicConfig(level=loglevel_map[args.loglevel])

    # for logger names to be honored, modules should define loggers and
    # filters like this:
    #   logger_name = __name__.split('.')[-1]
    #   logger = logging.getLogger(logger_name)
    #   logger.addFilter(
    #         lambda r: r.levelno > 20 or logger_name in Utility.logger_names)
    Utility.logger_names = set(args.loggername)

    # XXX do we really need to deprecate them?
    if False and args.loglevel in deprecated_loglevels:
        logger.warning('--loglevel value %s is deprecated; replace with %r' % (
            args.loglevel,
            logging.getLevelName(loglevel_map[args.loglevel]).lower()))

    # import all plugins
    Plugin.import_all(plugindirs=args.plugindir)

    # give parsers, transforms and formats the opportunity to add arguments
    # XXX should catch exceptions here, e.g. if invalid arguments are added
    Parser.add_arguments(arg_parser)
    Transform.add_arguments(arg_parser)
    Format.add_arguments(arg_parser)

    # argparse assistants
    parser_names = sorted(p.name() for p in Parser.items(nohidden=True))
    transform_names = sorted(t.name() for t in Transform.items(
            nohidden=True, nobase=True)) + ['<transform>.py']
    format_names = sorted(f.name() for f in Format.items(
            nohidden=True, nobase=True)) + ['<format>.py']

    def raise_argument_type_error(name, choices):
        choices_ = nice_list(choices, style='argparse')
        raise argparse.ArgumentTypeError(
                'invalid choice: %r (choose from %s)' % (name, choices_))

    def parser_create(name):
        parser = Parser.create(name)
        if not parser:
            raise_argument_type_error(name, parser_names)
        return parser

    def transform_create(name, *, internal: bool = False) -> Transform:
        transform = Transform.create(name, plugindirs=args.plugindir,
                                     internal=internal, args=args)
        if not transform:
            raise_argument_type_error(name, transform_names)
        return transform

    def format_create(name, *, internal: bool = False) -> Format:
        format_ = Format.create(name, plugindirs=args.plugindir,
                                internal=internal, args=args)
        if not format_:
            raise_argument_type_error(name, format_names)
        return format_

    default_parser = 'expat'
    default_format = 'null'

    # XXX these assertions only work for sub-class plugins, not for .py plugins
    assert default_parser in parser_names
    # assert default_format in format_names
    assert default_loglevel in loglevels

    arg_parser.add_argument("-p", "--parser", type=parser_create,
                            default=default_parser,
                            help="XML parser to use; choices: {%s}; default: "
                                 "%r" % (
                                     ','.join(parser_names), default_parser))
    arg_parser.add_argument("-t", "--transform", type=transform_create,
                            action="append",
                            help="optional transforms to apply to node tree; "
                                 "choices: {%s}" % ','.join(transform_names))
    arg_parser.add_argument("-f", "--format", type=format_create,
                            default=default_format,
                            help="report format to generate; choices: {%s}; "
                                 "default: %r" % (
                                     ','.join(format_names), default_format))
    arg_parser.add_argument("-v", "--version", action="store_true",
                            help="show the version number and exit")
    arg_parser.add_argument("-h", "--help", action="help",
                            default=argparse.SUPPRESS,
                            help="show this help message and exit")
    arg_parser.add_argument("file", type=str, nargs="*",
                            help="DM files to process")

    # 'before' and 'after' transforms
    # XXX there should be a more general list of 'before' and 'after' xforms
    # XXX there should be a way of suppressing the 'used' and/or 'lint'
    #     transforms; or use the log level?
    transforms_before = []
    transforms_after = [transform_create('used', internal=True),
                        transform_create('lint', internal=True)]

    # set options for the caller
    if opts is not None:
        opts['transforms_before'] = transforms_before
        opts['transforms_after'] = transforms_after
        opts['argv_remaining'] = argv_remaining
        opts['namespace'] = args
    return arg_parser


def main(argv=None):
    if argv is None:
        argv = sys.argv

    # get argument parser
    opts = {}
    arg_parser = get_argparser(argv=argv, opts=opts)

    # parse remaining arguments
    argv_remaining = opts.get('argv_remaining', None)
    namespace = opts.get('namespace', None)
    args = arg_parser.parse_args(argv_remaining, namespace=namespace)

    # warn about deprecated arguments (use the minimum valid abbreviations)
    deprecated = [arg for dep in {'--outf'}
                  for arg in argv if arg[:len(dep)] == dep]
    if deprecated:
        logger.warning('these options are deprecated: %s' % ', '.join(
                deprecated))

    # handle --version
    if args.version:
        sys.stderr.write('%s\n' % version())

    # get the list of transforms
    transforms = opts.get('transforms_before', []) + \
        (args.transform or []) + opts.get('transforms_after', [])

    # rename a few arguments
    # XXX could use 'dest' but that shows up in the command line help
    args.dirs = args.include
    logger.debug('arguments %s' % args)
    # XXX need to provide arguments to control profiling; what to profile
    #     and how/where to report the results
    if args.profile:
        profile = cProfile.Profile()
        profile.enable()

    # some old, heavily-nested models can exceed the default recursion limit
    # XXX this is no longer needed (have avoided a lot of recursion levels)
    # XXX should have an option to control this
    # noinspection PyUnreachableCode
    if False:
        limit = sys.getrecursionlimit()
        sys.setrecursionlimit(int(limit * 1.5))
        logger.debug('recursion limit %r -> %r' % (limit,
                                                   sys.getrecursionlimit()))

    # the return value is the error count
    errors = 0

    # allow plugins to request an early exit by returning True (any plugins
    # that do this should output an explanatory message)
    if any(transform.post_init(args) for transform in transforms) or \
            args.format.post_init(args):
        logger.info('transform or format requested early exit')
        errors += 1
    else:
        root = Root(args=args)
        for file in args.file:
            # XXX may want an option to control re-raise
            try:
                # XXX should we search for files specified on the command line?
                logger.info("processing '%s'" % file)
                start = time.time()
                Root.parse(file, parent=root)
                logger.info("processed  '%s' in %d ms" % (
                    file, (time.time() - start) * 1000))
            except Exception as e:
                logger.error('%s: %s' % (type(e).__name__, e))
                errors += 1
                if isinstance(e, (
                        AssertionError, AttributeError, BBFReportException,
                        FileNotFoundError, KeyError, NameError, RecursionError,
                        TypeError, ValueError)):
                    raise
                else:
                    continue

        if root.xml_files:
            for transform in transforms:
                logger.info("performing '%s' transform" % transform)
                start = time.time()
                transform.visit(root)
                logger.info("performed  '%s' transform in %d ms" % (
                    transform, (time.time() - start) * 1000))

            logger.info("generating '%s' format" % args.format)
            start = time.time()
            args.format.visit(root, omit_if_unused=not args.all)
            logger.info("generated  '%s' format in %d ms" % (
                    args.format, (time.time() - start) * 1000))
            if str(args.format) != 'null' and args.output is not sys.stdout:
                logger.info("wrote '%s'" % args.output.name)

    if args.profile:
        profile.disable()
        stats = pstats.Stats(profile, stream=sys.stderr)
        stats.strip_dirs()
        stats.sort_stats('time')
        stats.print_stats(50)
        # XXX it doesn't seem possible to control the caller/callee order?
        stats.print_callers(20)
        stats.print_callees(20)

    return errors


if __name__ == "__main__":
    sys.exit(main())
