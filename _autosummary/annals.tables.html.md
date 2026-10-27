# annals.tables

Scrolling, zooming tables for published html pages.

A published html page is served as written; this adds one inlined script (the page’s own
`ui/tables.js`) that wraps each data table in a horizontally scrollable, zoomable box,
and lifts a viewport meta that forbids pinch-zoom. Markdown documents get the same script
from the page itself, so both paths share one implementation.

### Functions

| [`add_table_tools`](#annals.tables.add_table_tools)(html)   | `html` with the table script injected, unless it has no table or opts out.                                          |
|--------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------|
| [`allow_zoom`](#annals.tables.allow_zoom)(html)        | `html` with pinch-zoom allowed: no `user-scalable=no` or scale limits in its viewport meta.                         |
| [`tables_version`](#annals.tables.tables_version)()        | A short hash of what [`add_table_tools()`](#annals.tables.add_table_tools) injects, for a page's ETag. |

### annals.tables.add_table_tools(html)

`html` with the table script injected, unless it has no table or opts out.

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### annals.tables.allow_zoom(html)

`html` with pinch-zoom allowed: no `user-scalable=no` or scale limits in its viewport meta.

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### annals.tables.tables_version()

A short hash of what [`add_table_tools()`](#annals.tables.add_table_tools) injects, for a page’s ETag.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
