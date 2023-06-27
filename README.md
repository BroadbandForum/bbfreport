<!-- do not edit! this file was created from PROJECT.yaml by project-parser.py -->

# Broadband Forum (BBF) Data Model Report Tool

The BBF Report Tool processes one or more Data Model (DM) XML files. Having
read the files, it always performs various "lint" checks and then it
optionally generates an output format, e.g., "full" XML (a single file in
which all imports have been resolved) or markdown (which can be converted to
HTML by [pandoc]).

The tool requires at least python 3.9, and can be installed from [PyPI]. It
replaces an earlier [report.pl] tool.

[pandoc]: https://pandoc.org
[PyPI]: https://pypi.org/search/?q=bbfreport
[report.pl]: https://github.com/BroadbandForum/cwmp-xml-tools

Detailed documentation will be added in a future release. In the meantime,
see below for command-line help.

Note that the command-line help doesn't yet show help for `<transform>.py`
and `<format>.py` plugins. You can also (for example) supply:

* `-t diff` (with two DM files) to generate diffs, or

* `-f markdown` to generate [pandoc](https://pandoc.org) `commonmark_x`
  markdown that can then be converted to HTML. Direct HTML generation will
  be added in a future release

```shell
usage: report.py [-P PLUGINDIR] [-I INCLUDE] [-C] [-F FILTER] [-o OUTPUT]
                 [-l {none,fatal,error,warning,info,debug,0,1,2}]
                 [-L LOGGERNAME] [-T] [-A] [-S] [-D DEBUGPATH] [--profile]
                 [--parser-dump-json] [--parser-dump-tuple]
                 [--parser-warn-tabs]
                 [--relref-mappings-file RELREF_MAPPINGS_FILE]
                 [--relref-update-mappings] [--relref-apply-mappings]
                 [--version-initial VERSION_INITIAL]
                 [--text-report-style {report1,report2,visit}]
                 [--text-list-references] [--xml-always-auto-newline]
                 [--xml-always-auto-indent]
                 [--xml-indent-step XML_INDENT_STEP]
                 [--xml-line-length XML_LINE_LENGTH] [--xml-no-wrap]
                 [-p PARSER] [-t TRANSFORM] [-f FORMAT] [-h]
                 [file ...]

Broadband Forum (BBF) Data Model Report Tool.

The tool processes one or more Data Model (DM) XML files. In outline:

    Process the command line arguments.
    Create an empty node tree.

    For each DM file specified on the command line:
        Parse the file using the specified parser (default: expat).
            (this updates the node tree)

    For each specified transform (default: none):
        Transform the node tree.

    Output the specified format (default: null).

positional arguments:
  file                  DM files to process

options:
  -P PLUGINDIR, --plugindir PLUGINDIR
                        directories to search for plugins (parsers, transforms
                        and formats)
  -I INCLUDE, --include INCLUDE
                        directories to search (recursively) for
                        included/imported files (is also used for files
                        specified on the command line)
  -C, --nocurdir        don't automatically search the current directory
  -F FILTER, --filter FILTER
                        filter specification, which is applied just after
                        parsing; experts only! default: []
  -o OUTPUT, --output OUTPUT, --outfile OUTPUT
                        name of output file; default: <stdout>
  -l {none,fatal,error,warning,info,debug,0,1,2}, --loglevel {none,fatal,error,warning,info,debug,0,1,2}
                        logging level; default: 'warning'
  -L LOGGERNAME, --loggername LOGGERNAME
                        module names for which to enable logging, e.g. 'file',
                        'node' or 'expatParser'; default: ['report']
  -T, --thisonly        only output definitions defined in the files on the
                        command line, not those from imported files
  -A, --all             request the output format to report all nodes even if
                        they're not used (only affects the output format; has
                        no effect on transforms)
  -S, --show            request the output format to highlight nodes that were
                        added in the latest version (only affects the output
                        format; has no effect on transforms)
  -D DEBUGPATH, --debugpath DEBUGPATH
                        path to debug (regular expression); if set, forces
                        --loglevel=info
  --profile             enable profiling; currently experimental with hard-
                        coded settings
  -p PARSER, --parser PARSER
                        XML parser to use; choices: {expat}; default: 'expat'
  -t TRANSFORM, --transform TRANSFORM
                        optional transforms to apply to node tree; choices:
                        {enum,relref,status,version,<transform>.py}
  -f FORMAT, --format FORMAT
                        report format to generate; choices:
                        {text,xml,<format>.py}; default: 'null'
  -h, --help            show this help message and exit

generic parser arguments:
  --parser-dump-json    dump parse results to JSON
  --parser-dump-tuple   dump parse results as tuple
  --parser-warn-tabs    warn of any TAB characters

relref transform arguments:
  --relref-mappings-file RELREF_MAPPINGS_FILE
                        JSON mapping file; default: 'relref-mappings.json'
  --relref-update-mappings
                        Whether to update mappings in an existing file
  --relref-apply-mappings
                        Whether to apply mappings (if so, the file is read; if
                        not, it's created or updated)

version transform arguments:
  --version-initial VERSION_INITIAL
                        initial version of this data model; default: model
                        version

text report format arguments:
  --text-report-style {report1,report2,visit}
                        report style (details TBD); default: 'visit'
  --text-list-references
                        whether to list bibliographic references

xml report format arguments:
  --xml-always-auto-newline
                        whether always to automatically handle newlines;
                        usually only do this when generating 'full' XML
  --xml-always-auto-indent
                        whether always to automatically handle indentation;
                        usually only do this when generating 'full' XML
  --xml-indent-step XML_INDENT_STEP
                        indentation per level when auto-indenting; default: 2
  --xml-line-length XML_LINE_LENGTH
                        maximum line length; default: 79
  --xml-no-wrap         don't wrap text, e.g. descriptions
```
