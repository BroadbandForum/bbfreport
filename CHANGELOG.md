<!-- do not edit! this file was created from PROJECT.yaml by project-parser.py -->

# BBF Report Tool Change Log

> **Note**: The v2+ version might suggest that the tool is mature, but the
v2 label is just to distinguish it from the earlier [report.pl] tool. APIs
are still liable to minor change, and will probably continue to do so
until v3.

The [BBF] Report Tool processes one or more [Data Model (DM)][DM] or
[Device Type (DT)][DT] XML files. Having parsed the files, it always
performs various "lint" checks, and then it optionally generates an
output format, e.g., HTML or "full" XML (a single file in which all
imports have been resolved).

The tool requires at least [python] 3.11, and can be installed from [PyPI].
It replaces an earlier [report.pl] tool.

[BBF]: https://www.broadband-forum.org
[DM]: https://data-model-template.broadband-forum.org/#sec:executive-summary
[DT]: https://data-model-template.broadband-forum.org/#sec:executive-summary
[PyPI]: https://pypi.org/search/?q=bbfreport
[python]: https://www.python.org
[report.pl]: https://github.com/BroadbandForum/cwmp-xml-tools

## 2025-03-17: v2.3.0

*Tag: [v2.3.0]*

* Supported direct HTML generation, meaning that it's no longer necessary
  to run [pandoc] (this currently uses the external [markdown-it-py]
  package)
* Added `{{minval}}`, `{{maxval}}`, `{{range}}` and `{{size}}` macros
* Reported "version increased" as a warning (it was previously reported
  as an info message)
* Relaxed derived model naming rules (useful when defining vendor models
  based on standard models)
* Improved read-only unique key parameters' auto-text
* Improved `diffs` logic to reduce the chance of invalid macro references
* Changed the HTML font family to sans-serif
* Fixed various bugs, and improved code quality (this is ongoing)

[markdown-it-py]: https://pypi.org/project/markdown-it-py
[pandoc]: https://pandoc.org

## 2024-07-23: v2.2.0

*Tag: [v2.2.0]*

* Added a `spec` attribute version check (checks that `version`
  attributes are less than or equal to the file's `spec` attribute)
* Added a TR-106 naming rule check, including rules for vendor extensions
* Added a check for CWMP models that define commands or events
* Added a table / num-entries parameter version check (they should always
  have the same version) plus warn if non-tables have num-entries
  parameters
* Added checks for `Alias` parameters that aren't in tables or aren't
  unique keys
* Added checks for list-valued defaults (they must be in square
  brackets, and scalar defaults must not be in square brackets)
* Added an "object default" validity check
* Added a check for signed types that could be unsigned
* Added `difflint` checks for illegally-removed model or profile items
* Supported DT (Device Type) instances
* Improved the `diff` transform's handling of deleted attributes and
  elements
* Allowed component references to inherit their version attributes,
  which means that the version can usually be omitted
* Added some more output formats, e.g. a `difftext` format that outputs
  an easily-searchable list of differences, and a `path` format that
  outputs the path names for all objects, parameters etc.
* Added auto-generated HTML text for `writeOnceReadOnly` and
  `activeNotify="canDeny"` parameters
* Fixed a command and event argument ordering bug that caused confusing
  placement of top-level argument parameters in HTML
* Fixed `{{datatype}}` expansion problem that could include information
  about the parent object rather than about the data type
* Fixed bug in the XML output format, which could wrongly omit `version`
  attributes from generated XML
* Added logic to the XML output format to use the latest encountered
  DM Schema version in generated XML files
* Fixed HTML formatting problems affecting patterns and defaults
  containing special characters
* Fixed dark-mode hover-link and background colors
* Avoided some tool crashes, e.g., when an object has been defined before
  its parent
* Fixed the handling of the non-standard "absolute" path scope (it was
  being ignored)
* Improved MediaWiki markup compatibility (MediaWiki markup will continue
  to supported, but markdown is preferred)
* Documented the `decimal` data type (it was already supported, but the
  documentation said "TBD")
* Exit code is now the number of reported errors (useful in scripts)
* Various internal improvements that are only visible to plugin authors
  (the plugin interface has not yet been officially documented)
* Improved the documentation on running pandoc to convert markdown to
  HTML
* Fixed the file name in XML Schema validation error messages

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
[v2.2.0]: https://github.com/BroadbandForum/bbfreport/releases/tag/v2.2.0
[v2.3.0]: https://github.com/BroadbandForum/bbfreport/releases/tag/v2.3.0
