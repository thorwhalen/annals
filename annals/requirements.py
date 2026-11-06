"""Optional dependencies, checked where they are needed and explained when they are missing.

annals installs light: a heavy library (WeasyPrint for PDFs, pypdf for joining them,
markdownify for html to markdown) is imported only when the conversion that needs it runs,
and a missing one is a :class:`MissingDependency` that says which conversion needed it and
the exact command that fixes it, never a bare ``ImportError`` from deep inside a library.

    >>> check_requirements("json", what="anything")        # present: returns quietly
    >>> try:
    ...     check_requirements("no_such_module_xyz", what="Combining into PDF")
    ... except MissingDependency as e:
    ...     print(str(e).splitlines()[0])
    Combining into PDF needs no_such_module_xyz, which is not installed.

The pip name and the hint for a module are in :data:`PACKAGES`, so a new optional library is
one entry there.
"""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Iterable

#: the extra of annals that installs everything a conversion may need
DFLT_EXTRA = "pdf"
#: module name -> (pip name, system hint or ``""``)
PACKAGES: dict[str, tuple[str, str]] = {
    "weasyprint": (
        "weasyprint",
        "It also needs the Pango library (Debian/Ubuntu: apt install libpango-1.0-0).",
    ),
    "markdown_it": ("markdown-it-py", ""),
    "pypdf": ("pypdf", ""),
    "pdfdol": ("pdfdol", ""),
    "markdownify": ("markdownify", ""),
    "PIL": ("pillow", ""),
}


class MissingDependency(RuntimeError):
    """A library an operation needs is not installed (the message says how to install it)."""

    def __init__(self, modules: Iterable[str], *, what: str, extra: str = DFLT_EXTRA):
        self.modules = tuple(modules)
        self.what = what
        pips = [PACKAGES.get(m, (m, ""))[0] for m in self.modules]
        hints = " ".join(h for m in self.modules if (h := PACKAGES.get(m, ("", ""))[1]))
        names = ", ".join(self.modules)
        message = (
            f"{what} needs {names}, which {'is' if len(self.modules) == 1 else 'are'} "
            f"not installed.\nInstall with: pip install 'annals[{extra}]'  "
            f"(or just: pip install {' '.join(pips)})"
        )
        if hints:
            message += f"\n{hints}"
        super().__init__(message)


def missing_modules(modules: Iterable[str]) -> list[str]:
    """The ``modules`` that cannot be imported, found without importing them."""
    out = []
    for name in modules:
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            out.append(name)
    return out


def check_requirements(*modules: str, what: str, extra: str = DFLT_EXTRA) -> None:
    """Raise :class:`MissingDependency` unless every one of ``modules`` is installed.

    Cheap (nothing is imported), so a caller checks everything a job will use *before* it
    starts, and fails at once instead of half way.
    """
    missing = missing_modules(modules)
    if missing:
        raise MissingDependency(missing, what=what, extra=extra)


def import_lazily(name: str, *, what: str, extra: str = DFLT_EXTRA):
    """The module ``name``, imported now; a failure to import it is a :class:`MissingDependency`.

    A library that is installed but cannot load (WeasyPrint without Pango raises
    ``OSError``) is reported the same way.
    """
    try:
        return importlib.import_module(name)
    except (ImportError, OSError) as e:
        error = MissingDependency([name.split(".")[0]], what=what, extra=extra)
        raise error from e
