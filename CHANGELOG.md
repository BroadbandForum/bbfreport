<!-- do not edit! this file was created from PROJECT.yaml by project-parser.py -->

# BBF Report Tool Change Log

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

## 2023-06-14: v2.0.0

*Tag: [v2.0.0]*

* Initial version

[v2.0.0]: https://github.com/BroadbandForum/bbfreport/releases/tag/v2.0.0
