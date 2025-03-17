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

# Copyright (c) 2019-2025, Broadband Forum
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

from typing import Any, NoReturn

# minimum required python version
# XXX should put this check in a library init function?
CUR_VERSION = sys.version_info[:2]
MIN_VERSION = (3, 11)

# noinspection PyStringFormat
assert CUR_VERSION >= MIN_VERSION, "You're using python %d.%d; you " \
                                   "must use at least python %d.%d" % (
                                           CUR_VERSION + MIN_VERSION)

# if the bbfreport package is not installed, insert the current working
# directory into the search path, so we can directly execute the tool from
# the code
# XXX should reduce the duplication here
try:
    from bbfreport import Format, LayoutDoc, Logging, Parser, Plugin, Root, \
        Transform, Utility, version
    import bbfreport.exception
except ModuleNotFoundError:
    sys.path.insert(0, os.getcwd())
    from bbfreport import Format, LayoutDoc, Logging, Parser, Plugin, Root, \
        Transform, Utility, version
    import bbfreport.exception

logger = Logging.get_logger(__file__, ispath=True)

nice_list = Utility.nice_list

# XXX should change everywhere to use list.append(item) rather than += [item]?

# XXX note that 'arg: Foo = None' is implicitly 'arg: Optional[Foo] = None';
#     you don't need the 'Optional'

loglevel_map = {'none': 9999, 'fatal': logging.FATAL, 'error': logging.ERROR,
                'warning': logging.WARNING, 'info': logging.INFO,
                'debug': logging.DEBUG, '0': logging.WARNING,
                '1': logging.INFO, '2': logging.DEBUG}


# this is called without arguments when generating documentation
def get_argparser(argv: list[str] | None = None,
                  opts: dict[str, Any] | None = None) \
        -> argparse.ArgumentParser:
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
    arg_parser = argparse.ArgumentParser(prog='report.py',
                                         description=__doc__,
                                         fromfile_prefix_chars='@',
                                         formatter_class=formatter_class,
                                         add_help=False)

    arg_parser.add_argument("-P", "--plugindir", type=str, action="append",
                            default=default_plugindir,
                            help="directories to search for plugins ("
                                 "parsers, transforms and formats); the "
                                 "current directory is always searched "
                                 "unless suppressed via --nocurdir")
    arg_parser.add_argument("-I", "--include", type=str, action="append",
                            help="directories to search (recursively) for "
                                 "included/imported files (is also used for "
                                 "files specified on the command line); the "
                                 "current directory is always searched "
                                 "unless suppressed via --nocurdir")
    arg_parser.add_argument("-C", "--nocurdir", action="store_true",
                            help="don't automatically search the current "
                                 "directory for plugins and XML files")
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
                                 "affects the output format; has no effect "
                                 "on transforms)")
    arg_parser.add_argument("-H", "--hierarchical", action="store_true",
                            help="request the output format to generate a "
                                 "hierarchical report, with objects nested "
                                 "within their parents (typically only "
                                 "affects the output format and has no effect "
                                 "on transforms)")
    arg_parser.add_argument("-B", "--brief", action="store_true",
                            help="request the output format to generate a "
                                 "brief report (only affects the output "
                                 "format; has no  effect on transforms)")
    arg_parser.add_argument("-S", "--show", action="store_true",
                            help="request the output format to highlight "
                                 "nodes that were added in the latest "
                                 "version (typically only affects the "
                                 "output format and has no effect on "
                                 "transforms)")
    arg_parser.add_argument("-E", "--ignore-transform-errors",
                            action="store_true",
                            help="ignore errors from transforms when "
                                 "calculating the exit code")
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

    assert set(loglevel_map.keys()) >= set(loglevels), \
        'loglevel(s) %s are missing from loglevel map' % \
        (set(loglevels) -
         set(loglevel_map.keys()),)  # pyright: ignore [reportOperatorIssue]

    # note that logging levels increase from 'debug' through 'fatal'
    if args.debugpath:
        if loglevel_map[args.loglevel] > logging.INFO:
            args.loglevel = 'info'
        if 'node' not in args.loggername:
            args.loggername.append('node')

    logging.basicConfig(level=loglevel_map[args.loglevel])

    # for logger names to be honored, modules should define loggers like this:
    #   logger = Logging.get_logger(__name__)
    # XXX this should be a method, which should check that all the logger
    #     names are valid
    Logging.names = set(args.loggername)

    # XXX do we really need to deprecate them?
    if False and args.loglevel in deprecated_loglevels:
        level_name = logging.getLevelName(loglevel_map[args.loglevel]).lower()
        logger.warning('--loglevel value %s is deprecated; replace with %r' % (
            args.loglevel, level_name))  # pyright: ignore[reportUnreachable]

    # internal transforms are performed automatically and can't be selected
    # via the --transform argument
    internal_transforms = ['used', 'lint']

    # import all plugins
    Plugin.import_all(plugindirs=args.plugindir, nocurdir=args.nocurdir)

    # give parsers, transforms and formats the opportunity to add arguments
    # (the returned value is a dict mapping plugin name to a list of its
    # option strings)
    parser_options = Parser.add_arguments(arg_parser)
    transform_options = Transform.add_arguments(arg_parser)
    format_options = Format.add_arguments(arg_parser)

    # argparse assistants
    parser_names = Parser.items(exclude=['parser'])
    transform_names = Transform.items(exclude=internal_transforms)
    format_names = Format.items()

    def raise_argument_type_error(name: str,
                                  choices: tuple[str, ...]) -> NoReturn:
        choices_ = nice_list(choices, style='argparse')
        raise argparse.ArgumentTypeError(
                'invalid choice: %r (choose from %s)' % (name, choices_))

    def parser_create(name: str) -> Parser:
        parser = Parser.create(name)
        if not parser:
            raise_argument_type_error(name, parser_names)
        return parser

    def transform_create(name: str) -> Transform:
        transform = Transform.create(name, args=args)
        if not transform:
            raise_argument_type_error(name, transform_names)
        return transform

    def format_create(name) -> Format:
        # if the null format (whether defaulted or selected explicitly) and
        # there's an output file name, attempt to derive the format name from
        # its file extension
        if name == 'null' and (ext := os.path.splitext(args.output.name)[1]):
            # XXX it would be better if formats declared their supported exts
            format_to_exts = {
                'csv': ['.csv'],
                'difftext': ['.dif', '.diff', '.diffs'],
                'html': ['.htm', '.html'],
                'markdown': ['.md', '.markdown'],
                'text': ['.txt', '.text'],
                'xml': ['.xml']
            }
            ext_to_format = {ext: fmt for fmt, exts in
                             format_to_exts.items() for ext in exts}
            if ext not in ext_to_format:
                logger.warning('%r has an unknown file extension; need to '
                               'specify --format' % args.output.name)
            else:
                name = ext_to_format[ext]
                logger.info('auto-set format %r from %r' % (
                            name, args.output.name))
        format_ = Format.create(name, args=args)
        if not format_:
            raise_argument_type_error(name, format_names)
        return format_

    default_parser = 'expat'
    default_format = 'null'

    # XXX these assertions only work for sub-class plugins, not for .py plugins
    assert default_parser in parser_names
    assert default_format in format_names
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
    transforms_before = []
    transforms_after = [transform_create(name) for name in internal_transforms]

    # set options for the caller
    # (of parser_options, transform_options and format_options, only
    # transform_options is currently used)
    if opts is not None:
        opts['parser_options'] = parser_options
        opts['transform_options'] = transform_options
        opts['format_options'] = format_options
        opts['transforms_before'] = transforms_before
        opts['transforms_after'] = transforms_after
        opts['argv_remaining'] = argv_remaining
        opts['namespace'] = args
    return arg_parser


def main(argv: list[str] | None = None) -> int | None:
    if argv is None:
        argv = sys.argv

    # get argument parser
    opts: dict[str, Any] = {}
    try:
        arg_parser = get_argparser(argv=argv, opts=opts)
    except argparse.ArgumentError as e:
        logger.error('%s: %s' % (type(e).__name__, e.message))
        return 1
    except bbfreport.exception.PluginException as e:
        logger.error('%s: %s' % (type(e).__name__, e))
        return 1

    # parse remaining arguments
    argv_remaining = opts.get('argv_remaining', None)
    namespace = opts.get('namespace', None)
    args = arg_parser.parse_args(argv_remaining, namespace=namespace)

    # count errors for use as the exit code
    class ErrorHandler(logging.Handler):
        def __init__(self) -> None:
            super().__init__(logging.ERROR)
            self.enabled = True
            self.count = 0

        def emit(self, record: Any):
            if self.enabled:
                self.count += 1

    error_handler = ErrorHandler()
    logger.root.addHandler(error_handler)

    # warn about deprecated arguments (use the minimum valid abbreviations)
    deprecated = [arg for dep in {'--outf'}
                  for arg in argv if arg[:len(dep)] == dep]
    if deprecated:
        logger.warning('these options are deprecated: %s' % ', '.join(
                deprecated))

    # handle --version
    # noinspection PyTestUnpassedFixture
    if args.version:
        sys.stderr.write('%s\n' % version())

    # get the list of transforms (including auto-adding transforms for which
    # arguments have been provided)
    def auto_transforms(options: dict[str, list[str]]) -> list[Transform]:
        # options maps transform names to a list of their arguments, and revmap
        # maps arguments to their transform names
        revmap = {opt: tran
                  for tran, opts_ in options.items() for opt in opts_}
        trans_orig: list[Transform] = args.transform or []
        trans: list[Transform] = trans_orig[:]
        for arg in argv:
            for opt, tran_name in revmap.items():
                explicit = any(str(t) == tran_name for t in trans_orig)
                already = any(str(t) == tran_name for t in trans)
                if explicit or already:
                    pass

                # - will auto-add the transform if no transforms were listed
                #   explicitly (otherwise the order is impossible to deduce)
                # - will warn if an argument was specified but its transform
                #   wasn't listed explicitly or auto-added
                elif arg != opt[:len(arg)]:
                    pass
                elif not args.transform:
                    logger.info('auto-added %r transform because of %s'
                                % (tran_name, opt))
                    tran = Transform.create(tran_name)
                    if not tran:
                        logger.warning('failed to create transform %r' %
                                       tran_name)
                    else:
                        trans.append(tran)
                else:
                    logger.warning("transforms were specified, so can't "
                                   "auto-add %r transform: %s will be "
                                   "ignored" % (tran_name, opt))
        return trans

    # args.transform is updated to include the auto-transforms (and is
    # guaranteed to be a list, and not None)
    args.transform = auto_transforms(opts.get('transform_options', {}))
    transforms = opts.get('transforms_before', []) + args.transform + opts.get(
            'transforms_after', [])

    # XXX would like to auto-set the output format as a function of the
    #     output file extension; also check for any format arguments that
    #     belong to not-selected formats (they indicate a possible error);
    #     could argparse help here? (or with the above transform logic?)

    # rename a few arguments
    # XXX could use 'dest' but that shows up in the command line help
    # XXX so could also use 'metavar' to hide dest in the command line help!
    args.dirs = args.include
    # XXX this is temporary until HTML is generated directly (it prevents
    #     transform errors from aborting 'make' and preventing pandoc from
    #     being run)
    # noinspection PyProtectedMember
    if args.format._name == 'markdown':
        args.ignore_transform_errors = True
    logger.debug('arguments %s' % args)

    # XXX need to provide arguments to control profiling; what to profile
    #     and how/where to report the results
    profile = cProfile.Profile()
    if args.profile:
        profile.enable()

    # some old, heavily-nested models can exceed the default recursion limit
    # XXX this is no longer needed (have avoided a lot of recursion levels)
    # XXX should have an option to control this
    # noinspection PyUnreachableCode
    if False:
        limit = sys.getrecursionlimit()
        sys.setrecursionlimit(int(limit * 1.5))
        logger.debug('recursion limit %r -> %r' % (
            limit,
            sys.getrecursionlimit()))  # pyright: ignore[reportUnreachable]

    # allow plugins to request an early exit by returning True (any plugins
    # that do this should output a warning or error)
    if any(transform.post_init(args) for transform in transforms) or \
            args.format.post_init(args):
        logger.info('transform or format requested early exit')
    else:
        root = Root(args=args)
        for i, file in enumerate(args.file):
            # if we will perform a 'diff*' transform, temporarily reduce the
            # 'node' and 'property' loglevels to 'error' while parsing the
            # first file
            # XXX this is a hack pending a better solution, e.g. storing or
            #     deferring such messages; we don't want to see warnings
            #     from old data models
            loggers = []
            if i == 0 and loglevel_map[args.loglevel] < logging.ERROR and \
                    any(str(t).startswith('diff') for t in transforms):
                #
                names = ['node', 'property']
                loggers = [logging.getLogger(n) for n in names]
                for logger_ in loggers:
                    logger_.setLevel(logging.ERROR)
                logger.debug('temporarily set %s loglevel to ERROR' %
                             ', '.join(names))

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
                if isinstance(e, (
                        AssertionError, AttributeError, FileNotFoundError,
                        KeyError, IndexError, NameError, RecursionError,
                        TypeError, ValueError)):
                    raise
                else:
                    # XXX does this do anything? could remove it?
                    continue
            finally:
                # restore the loglevel(s)
                if loggers:
                    for logger_ in loggers:
                        logger_.setLevel(loglevel_map[args.loglevel])
                    logger.debug('restored loglevel')

        if root.xml_files:  # pyright: ignore [reportAttributeAccessIssue]
            # XXX this will presumably also ignore format errors? intended?
            if args.ignore_transform_errors:
                error_handler.enabled = False

            for transform in transforms:
                logger.info("performing '%s' transform" % transform)
                start = time.time()
                # XXX should catch some exceptions
                transform.visit(root)
                logger.info("performed  '%s' transform in %d ms" % (
                    transform, (time.time() - start) * 1000))

            logger.info("generating '%s' format" % args.format)
            start = time.time()
            # XXX should catch some exceptions
            result = args.format.visit(root, omit_if_unused=not args.all)
            logger.info("generated  '%s' format in %d ms" % (
                    args.format, (time.time() - start) * 1000))
            if isinstance(result, (LayoutDoc, str)):
                logger.info("rendering  '%s' format" % args.format)
                start = time.time()
                args.output.write(str(result))
                logger.info("rendered   '%s' format in %d ms" % (
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

    # some shells can't handle exit codes greater than 127
    logger.info('exit code %d' % min(error_handler.count, 127))
    return min(error_handler.count, 127)


if __name__ == "__main__":
    sys.exit(main())
