<!-- do not edit! this file was created from PROJECT.yaml by project-parser.py -->

# BBF Report Tool Change Log

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

## 2024-01-18: v2.1.0

*Tag: [v2.1.0]*

* Added `difflint` transform with multimodel version checks
* Added basic CSV output format
* Improved readability of the `diff` transform's text output
* Improved file search logic and error reporting
* Improved version and profile lint checks
* Improved object insertion order logic
* Improved some macro-expansion-related error messages
* Replaced HTML soft hyphens (`&shy;`) with CSS (avoids problems when
  copying and pasting names)
* Fixed HTML command/event argument access (the read and write arrows
  were the wrong way round)
* Fixed various bugs relating to `{{object}}`, `{{parameter}}` etc.
  references
* Fixed list size text (it wasn't clear whether it referred to the
  list itself or to the item)
* Fixed some HTML presentation bugs, e.g., colors and missing links
* Fixed a few other bugs, e.g., missing `version()` import, component
  expansion bug, description append problem, inadvertent inclusion of
  `{{np}}` in generated XML
* Added CSS to support dark rendering mode according to user preference

## 2023-06-27: v2.0.1

*Tag: [v2.0.1]*

* Added `--version` option

## 2023-06-14: v2.0.0

*Tag: [v2.0.0]*

* Initial version

[v2.0.0]: https://github.com/BroadbandForum/bbfreport/releases/tag/v2.0.0
[v2.0.1]: https://github.com/BroadbandForum/bbfreport/releases/tag/v2.0.1
[v2.1.0]: https://github.com/BroadbandForum/bbfreport/releases/tag/v2.1.0
