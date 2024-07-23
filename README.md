<!-- do not edit! this file was created from PROJECT.yaml by project-parser.py -->

# Broadband Forum (BBF) Data Model Report Tool

> **Note**: The v2+ version might suggest that the tool is mature, but the
v2 label is just to distinguish it from the earlier [report.pl] tool. APIs
are still liable to minor change, and will probably continue to do so
until v3.

The [BBF] Report Tool processes one or more [Data Model (DM) XML files][DM].
Having read the files, it always performs various "lint" checks, and then it
optionally generates an output format, e.g., "full" XML (a single file in
which all imports have been resolved) or markdown (which can be converted to
HTML by [pandoc]).

The tool requires at least [python] 3.9, and can be installed from [PyPI].
It replaces an earlier [report.pl] tool.

[BBF]: https://www.broadband-forum.org
[DM]: https://data-model-template.broadband-forum.org/#sec:executive-summary
[pandoc]: https://pandoc.org
[PyPI]: https://pypi.org/search/?q=bbfreport
[python]: https://www.python.org
[report.pl]: https://github.com/BroadbandForum/cwmp-xml-tools

## Quick start

Ensure you have at least python 3.9, and install the tool from PyPI.

    % python -m pip install bbfreport

The `report.py` command should now work.

    % report.py -v
    Broadband Forum bbfreport v2.0.1 (2023-06-27 version)

You'll probably want to download some data models.

    % git clone https://github.com/BroadbandForum/usp-data-models.git

(These are the [USP] data models. The [CWMP] data models are in the
`cwmp-data-models` repository.)

Now you can run the tool, e.g., here we're running it on the USP version of
the latest [TR-181 (Device:2)][Device:2] model.
* `-I` (`--include`) indicates where to look for DM XML files
* `-l` (`--loglevel`) is here used to suppress warnings (there are some
  warnings, because the tool has improved since the data model was published)
<!-- -->

    % report.py -I usp-data-models -l error tr-181-2-usp.xml

To generate output, give an output format.
* `-f` (`--format`) indicates the output format
* `-o` (`--output`) specifies the output file
<!-- -->

    % report.py -I usp-data-models -l error tr-181-2-usp.xml -f xml -o tr-181-2-usp-full.xml

> **Note**: Direct HTML generation isn't yet supported. It's currently
necessary to generate markdown and then run it through [pandoc] to
generate the HTML.

Unfortunately, `report.py -h` (`--help`) doesn't yet list all the available
formats (new-style formats aren't listed), e.g., it doesn't list the
`markdown` format.

## How it works

Here's an outline of what the tool does.

    Process the command line arguments.
    Create an empty node tree.

    For each DM file specified on the command line:
        Parse the file using the specified parser (default: expat).
            (this updates the node tree)

    For each specified transform (default: [used, lint]):
        Transform the node tree.

    Output the specified format (default: null).

The node tree (deliberately) has the same structure as the DM XML files,
e.g., `Xml_file` nodes have `Dm_document` children, which have
`Description`, `DataType`, `Component` and `Model` children; and `Model`
nodes have `Object`, `Parameter`, `Command`, `Event` and `Profile`
children; and so on.

The `used` transform traverses the node tree and determines which data
types, bibliographic references etc. are actually used. If they're not
used then, unless overridden by `-A` (`--all`), they're excluded from the
output.

The `lint` transform traverses the node tree and performs a large number of
"[lint]" checks that (as far as possible) check that the [TR-106] rules and
best practices are being followed.

Any transforms specified on the command-line via `-t` (`--transform`) are
run before the `used` and `lint` transforms.

## Searching for DM XML files

DM XML files (if they don't specify the directory) are always searched for
in the current directory (unless suppressed by `-C` / `--nocurdir`) and
(recursively) in the  directories listed via the `-I` (`--include`) option.

File names of the (conventional) form `tr-nnn-i-a-c-label.xml` can omit
`-c`, `-a-c` or `-i-a-c`, in which case the latest matching version will
be used.

> **Note:** `i`, `a` and `c` stand for `Issue`, `Amendment` and
`Corrigendum` respectively. You can think of them as major, minor and
patch versions.

Most files (all except for the files specified on the command-line) are
accessed via an `import` statement such as this one:

    <import file="tr-181-2-softwaremodules.xml"
            spec="urn:broadband-forum-org:tr-181-2-17-softwaremodules">
        <component name="SMDUNetworkConfig"/>
    </import>

If the `import` statement has a `spec` attribute then a file with a
matching `spec` will be searched for. Here the spec specifies `i` and `a`,
so they must match exactly, but it omits `c`, so the latest `c` will be
returned.

## Transforms and Formats

Transforms and formats are written in similar ways, but (as already
explained) they have different purposes.

There are two ways to write transforms and formats. The old way is to
write a class that derives from `Transform` or `Format`, and the new (much
easier) way is to write various "magic" functions whose names indicate the
type of node for which they are to be called.

Suppose you want to write a transform that checks whether any object,
parameter etc. names start with lower-case letters. You can create this
`lower.py` file.

    def visit__model_item(node, logger):
      if node.name[0].islower():
          logger.info('%s %s' % (node.version_inherited, node.nicepath))

There are several things to note here:
* You have to know something about the node class hierarchy, which is
  defined in [`node.py`](bbfreport/node.py), and how the class names map
  to `visit_xxx()` function names
* In this case, `_ModelItem` is a base class for `Model`, `Object`,
  `Parameter`, `Command`, `Event` and `Profile`
* To generate the function name, the `_ModelItem` class name has
  underscores inserted between lower/upper transitions, is converted to
  lowercase, and is prefixed with `visit_` to give `visit__model_item`
  (two underscores, because the class name starts with an underscore)
* The function's first argument is always the node, and other arguments are
  optional (but selected from a predefined set). Here, the `logger`
  argument is a ready-to-use [logger] instance. You could also (for
  example) have provided an `args` argument if you needed to access the
  command-line arguments
* You also have to know something about the node attributes. As already
  mentioned, they are very similar to the XML, so for example `node.name`
  is the name, and `node.version` is the version... but it's the _actual_
  `version` attribute, which might need to be inherited from the node's
  parent, so that's why we use `node.version_inherited`. We also use
  `node.nicepath`, and you couldn't have guessed this
* For more information you'll have to refer to the code or to the code
  documentation (once it's available)

You can then run the tool like this:

    % report.py -I usp-data-models tr-181-2-usp.xml -P . -t lower -l 1 -L lower

The options (some of which are new) are as follows:
* `-I` (`--include`) indicates where to look for DM XML files
* `-P` (`--plugindir`) indicates where to search for transforms and formats
* `-t` (`--transform`) says which transform to run (there could be several)
* `-l` (`--loglevel`) is the log level; `1` is the same as `info`
* `-L` (`--loggername`) is the logger name; only the top-level `report`
  logger is initially enabled
<!-- -->

Here's the output:

    INFO:report:processing 'tr-181-2-usp.xml'
    INFO:report:processed  'tr-181-2-usp.xml' in 5286 ms
    INFO:report:performing 'lower' transform
    INFO:lower:2.15 Device.WiFi.<omitted>.bSTAMACAddress
    INFO:lower:2.17 Device.WiFi.<omitted>.bSTAMLDMaxLinks
    INFO:lower:2.17 Device.WiFi.<omitted>.bSTAMACAddress
    INFO:report:performed  'lower' transform in 366 ms
    INFO:report:performing 'used' transform
    INFO:report:performed  'used' transform in 1327 ms
    INFO:report:performing 'lint' transform
    INFO:report:performed  'lint' transform in 3944 ms
    INFO:report:generating 'null' format
    INFO:report:generated  'null' format in 0 ms

## Log levels and loggers

The `-l` (`--loglevel`) option sets the log level to one of the
following.

| Value            | Description                                       |
|------------------|---------------------------------------------------|
| `none`           | No log messages are output                        |
| `fatal`          | Only fatal errors are output                      |
| `error`          | Only fatal and ordinary errors are output         |
| `warning` or `0` | All errors and warnings are output (**default**)  |
| `info` or `1`    | Errors and warnings and info messages are output  |
| `debug` or `2`   | As above plus debug messages                      |

As a rule of thumb, info messages should be of interest to all users of
the tool, but debug messages are likely to be only of interest to people
trying to work out what's gone wrong.

For info and debug messages, just setting the log level isn't enough. You
have to use the `-L` (`--loggername`) option to enable the loggers of
interest. Only the top-level `report` logger is always enabled.

The logger name is the python module name, e.g., the lint transform's
logger name is `lint. Here's an example.

    % report.py -I usp-data-models tr-140-1-usp.xml -l 1 -L lint -L used
    INFO:report:processing 'tr-140-1-usp.xml'
    INFO:report:processed  'tr-140-1-usp.xml' in 195 ms
    INFO:report:performing 'used' transform
    INFO:report:performed  'used' transform in 100 ms
    INFO:report:performing 'lint' transform
    INFO:lint:StorageService.{i}.StorageArray.{i}.:
         list-valued unique key parameter PhysicalMediumReference
    INFO:lint:StorageService.{i}.StorageArray.{i}.Alias:
         list-valued unique key parameter PhysicalMediumReference
    INFO:report:performed  'lint' transform in 115 ms
    INFO:report:generating 'null' format
    INFO:report:generated  'null' format in 0 ms

## Running pandoc

The report tool doesn't yet generate HTML directly. To generate HTML, use the
`markdown` format to generate markdown, and then run [pandoc] to generate HTML.

The `markdown` format generates an extended version of [commonmark]
(referred to as commonmark_x). To process it, you need to install the
following:

* pandoc 3.0 or later: This might already be installed, or you might
be able to install it using the OS package manager. If not, you can get it
from <https://github.com/jgm/pandoc/releases>

* list-table filter: Get this from
<https://github.com/pandoc-ext/list-table>

* logging library: Get this from
<https://github.com/pandoc-ext/logging>

* custom HTML writer: Get this from
<https://github.com/BroadbandForum/pandoc-html-writer>

Assuming that you've already installed pandoc, and that you want to process
`model.md`, you can do this:

% git clone https://github.com/pandoc-ext/list-table
Cloning into 'list-table'...
...
% ln -s list-table/list-table.lua

% git clone https://github.com/pandoc-ext/logging
Cloning into 'logging'...
...
% ln -s logging/logging.lua

% git clone https://github.com/BroadbandForum/pandoc-html-writer
Cloning into 'pandoc-html-writer'...
...
% ln -s pandoc-html-writer/html-writer.lua
% ln -s pandoc-html-writer/html-derived-writer.lua

% report.py model.xml --format markdown --output model.md

% pandoc model.md --standalone --from commonmark_x --lua-filter list-table.lua --to html-derived-writer.lua --output model.html

Refer to the pandoc documentation for more information, e.g., on how to
avoid the need for the soft links.

[commonmark]: https://commonmark.org
[pandoc]: https://pandoc.org

## Notes

* The distribution doesn't contain any sample DM instances, so you have to
  download some data models before you can usefully use the tool

[CWMP]: https://cwmp-data-models.broadband-forum.org
[Device:2]: https://device-data-model.broadband-forum.org
[lint]: https://en.wikipedia.org/wiki/Lint_(software)
[logger]: https://docs.python.org/3.10/library/logging.html?#logger-objects
[pandoc]: https://pandoc.org
[TR-106]: https://data-model-template.broadband-forum.org
[USP]: https://usp.technology
