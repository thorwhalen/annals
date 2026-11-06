# annals.requirements

Optional dependencies, checked where they are needed and explained when they are missing.

annals installs light: a heavy library (WeasyPrint for PDFs, pypdf for joining them,
markdownify for html to markdown) is imported only when the conversion that needs it runs,
and a missing one is a [`MissingDependency`](#annals.requirements.MissingDependency) that says which conversion needed it and
the exact command that fixes it, never a bare `ImportError` from deep inside a library.

```pycon
>>> check_requirements("json", what="anything")        # present: returns quietly
>>> try:
...     check_requirements("no_such_module_xyz", what="Combining into PDF")
... except MissingDependency as e:
...     print(str(e).splitlines()[0])
Combining into PDF needs no_such_module_xyz, which is not installed.
```

The pip name and the hint for a module are in [`PACKAGES`](#annals.requirements.PACKAGES), so a new optional library is
one entry there.

### Module Attributes

| [`DFLT_EXTRA`](#annals.requirements.DFLT_EXTRA)   | the extra of annals that installs everything a conversion may need   |
|---------------------------------------------------------------|----------------------------------------------------------------------|
| [`PACKAGES`](#annals.requirements.PACKAGES)     | module name -> (pip name, system hint or `""`)                       |

### Functions

| [`check_requirements`](#annals.requirements.check_requirements)(\*modules, what[, extra])   | Raise [`MissingDependency`](#annals.requirements.MissingDependency) unless every one of `modules` is installed.             |
|-------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------|
| [`import_lazily`](#annals.requirements.import_lazily)(name, \*, what[, extra])         | The module `name`, imported now; a failure to import it is a [`MissingDependency`](#annals.requirements.MissingDependency). |
| [`missing_modules`](#annals.requirements.missing_modules)(modules)                       | The `modules` that cannot be imported, found without importing them.                                                             |

### Exceptions

| [`MissingDependency`](#annals.requirements.MissingDependency)(modules, \*, what[, extra])   | A library an operation needs is not installed (the message says how to install it).   |
|--------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|

### annals.requirements.DFLT_EXTRA *= 'pdf'*

the extra of annals that installs everything a conversion may need

### *exception* annals.requirements.MissingDependency(modules, , what, extra='pdf')

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

A library an operation needs is not installed (the message says how to install it).

### annals.requirements.PACKAGES *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]]* *= {'PIL': ('pillow', ''), 'markdown_it': ('markdown-it-py', ''), 'markdownify': ('markdownify', ''), 'pdfdol': ('pdfdol', ''), 'pypdf': ('pypdf', ''), 'weasyprint': ('weasyprint', 'It also needs the Pango library (Debian/Ubuntu: apt install libpango-1.0-0).')}*

module name -> (pip name, system hint or `""`)

### annals.requirements.check_requirements(\*modules, what, extra='pdf')

Raise [`MissingDependency`](#annals.requirements.MissingDependency) unless every one of `modules` is installed.

Cheap (nothing is imported), so a caller checks everything a job will use *before* it
starts, and fails at once instead of half way.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### annals.requirements.import_lazily(name, , what, extra='pdf')

The module `name`, imported now; a failure to import it is a [`MissingDependency`](#annals.requirements.MissingDependency).

A library that is installed but cannot load (WeasyPrint without Pango raises
`OSError`) is reported the same way.

### annals.requirements.missing_modules(modules)

The `modules` that cannot be imported, found without importing them.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
