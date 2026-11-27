"""The routes a page's highlights widget talks to, for any FastAPI host.

:mod:`annals.highlights` is what a highlight may be and where each reader's are kept; this
is the wire `manicules <https://github.com/thorwhalen/manicules>`_' ``httpStore`` speaks,
relative to where the router is mounted::

    GET    /highlights?q=&source=&tag=   {data, total}, newest first
    POST   /highlights                   keep one (an ``id`` and ``created`` it sends are kept)
    GET    /highlights/settings          {color, showOthers}
    PUT    /highlights/settings          change them
    GET    /highlights/{id}              one
    PATCH  /highlights/{id}              name, comment, tags, color
    DELETE /highlights/{id}              answers the highlight, so the page can put it back

A refused value is a 422 with the reason, an unknown id a 404, and with no store
(``for_reader=None``) every route is a 404. The host says who is asking (``reader``) and
what guards a write (``write_dependencies``, e.g. its same-origin check); this module
knows neither.
"""

# extraction candidate: with annals.highlights, the Python side of manicules for a FastAPI host.

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

from annals import highlights as hl


def mk_router(
    for_reader: hl.ForReader | None,
    *,
    reader: Callable[[Request], str],
    write_dependencies: Sequence[Any] = (),
    router: Any = None,
) -> Any:
    """The seven highlight routes over ``for_reader``, each answering for ``reader(request)``.

    They are added to ``router`` (your app, or a router of yours) and it is returned; with
    none, a new ``APIRouter`` to include. A host that walks its own route table (annals
    gates a room route by route) passes its app, so the routes sit in that table one by one.
    """
    router = APIRouter() if router is None else router
    guarded = list(write_dependencies)

    def mine(request: Request) -> hl.ReaderHighlights:
        if for_reader is None:
            raise HTTPException(404, "highlights are not kept here")
        try:
            return for_reader(reader(request))
        except ValueError as e:
            raise HTTPException(400, str(e))

    def with_href(record: dict) -> dict:
        """A highlight with ``href``: its page under the page's base, opened on it."""
        link = hl.href(record)
        if link:
            record["href"] = link
        return record

    @router.get("/highlights")
    def list_highlights(
        request: Request, q: str = "", source: str = "", tag: str = ""
    ) -> dict:
        """This reader's highlights, newest first: every word of ``q`` must appear in the
        name, the passage, the note, the tags or the page's title; ``source`` keeps one
        page's, ``tag`` one tag's. Each row has ``href``, its page (relative to the page's
        base) opened on the highlight."""
        rows = hl.search(
            mine(request).records.snapshot(), q, source=source or None, tag=tag or None
        )
        return {"data": [with_href(r) for r in rows], "total": len(rows)}

    @router.get("/highlights/settings")
    def get_highlight_settings(request: Request) -> dict:
        """This reader's highlight settings, over the defaults."""
        return hl.settings_of(mine(request).settings.snapshot())

    @router.put("/highlights/settings", dependencies=guarded)
    def set_highlight_settings(request: Request, body: dict = Body(...)) -> dict:
        """Change settings: ``{"color": "green"}``, ``{"showOthers": false}``."""
        settings = mine(request).settings
        try:
            for key, value in hl.clean_settings(body).items():
                settings[key] = value
        except ValueError as e:
            raise HTTPException(422, str(e))
        return hl.settings_of(settings.snapshot())

    @router.post("/highlights", dependencies=guarded)
    def add_highlight(request: Request, body: dict = Body(...)) -> dict:
        """Keep a highlight: ``{"target": {"source": {"id", "title", "url"}, "part",
        "quote": {"exact", "prefix", "suffix"}, "position": {"start", "end"}}}`` plus,
        optionally, ``name``, ``comment``, ``tags``, ``color`` and an ``id``."""
        try:
            return with_href(hl.add(mine(request).records, body))
        except ValueError as e:
            raise HTTPException(422, str(e))

    @router.get("/highlights/{hid}")
    def get_highlight(hid: str, request: Request) -> dict:
        """One of this reader's highlights."""
        record = mine(request).records.get(hid)
        if record is None:
            raise HTTPException(404, "no such highlight")
        return with_href(record)

    @router.patch("/highlights/{hid}", dependencies=guarded)
    def edit_highlight(hid: str, request: Request, body: dict = Body(...)) -> dict:
        """Change a highlight's ``name``, ``comment``, ``tags`` or ``color`` (``null``: the
        default colour again). Its passage never changes."""
        try:
            return with_href(hl.edit(mine(request).records, hid, body))
        except KeyError:
            raise HTTPException(404, "no such highlight")
        except ValueError as e:
            raise HTTPException(422, str(e))

    @router.delete("/highlights/{hid}", dependencies=guarded)
    def remove_highlight(hid: str, request: Request) -> dict:
        """Delete a highlight; the answer is the highlight, so the page can put it back."""
        try:
            return hl.remove(mine(request).records, hid)
        except KeyError:
            raise HTTPException(404, "no such highlight")

    return router
