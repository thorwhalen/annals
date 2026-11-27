"""The search strategies (annals.search), the catalog's ``search`` seam, and the page's ranking.

The bug this pins (2026-11-27): "Search all text" sat on "Searching…" for minutes. Every
query scanned every item and re-read the full text of each one whose title lacked a word;
the text cache (512) was smaller than the corpus (~1400 documents), so nothing stayed
cached, and each debounced keystroke started another such scan beside the last. Replayed
on the live data, one typed query answered after 35 s, before any network. The guard is
:func:`test_a_corpus_larger_than_the_text_cache_is_read_once`: an index reads an item's
text once per change, never once per query.
"""

import os
import sqlite3
import threading
import time

import pytest
from fastapi.testclient import TestClient

from annals.api import mk_api
from annals.catalog import Catalog, mk_catalog
from annals.search import IndexedSearch, fts_query, scan_search
from annals.sources import FolderSource, PublishedSource
from annals.store import DocStore


def _row(key, title="", text="", *, time="2026-01-01", size=None, **kw):
    source, _, item_id = key.partition(":")
    row = dict(key=key, source=source, id=item_id, title=title, time=time, **kw)
    row["size"] = len(text) if size is None else size
    row["_text"] = text
    return row


def _text_of(row):
    return row["_text"]


ROWS = [
    _row("p:a", "Quarterly plan", "Budget and headcount for the quarter.", time="2026-01-03"),
    _row("p:b", "Train timetable", "Fares and rates: trains leave every ten minutes from platform two.", time="2026-01-02"),
    _row("p:c", "Notes", "A separate generated thing, nothing about money.", time="2026-01-01"),
]


@pytest.fixture(params=["indexed", "scan"])
def strategy(request):
    return IndexedSearch() if request.param == "indexed" else scan_search


# -- what every strategy promises ---------------------------------------------------------


def test_every_word_is_required_and_found_in_the_full_text(strategy):
    assert [r["key"] for r in strategy("trains minute", ROWS, _text_of)] == ["p:b"]
    assert strategy("trains nowhere-at-all", ROWS, _text_of) == []
    hit = strategy("headcount", ROWS, _text_of)[0]
    assert hit["key"] == "p:a" and "headcount" in hit["snippet"].lower()


def test_an_empty_query_is_every_row_as_given(strategy):
    assert strategy("   ", ROWS, _text_of) == ROWS


# -- the index ---------------------------------------------------------------------------


def test_the_index_ranks_a_title_match_above_a_passing_mention():
    rows = [
        _row("p:mention", "Weekly notes", "In passing: the train times looked fine.", time="2026-02-01"),
        _row("p:title", "Train times per platform", "A table.", time="2026-01-01"),
    ] + [_row(f"p:other{i}", f"Other {i}", "Unrelated words.") for i in range(8)]  # so BM25's IDF is not ~0
    hits = IndexedSearch()("train times", rows, _text_of)
    assert [r["key"] for r in hits] == ["p:title", "p:mention"]
    assert hits[0]["score"] > hits[1]["score"]


def test_the_index_matches_word_prefixes_and_stems_not_inner_substrings():
    search = IndexedSearch()
    assert [r["key"] for r in search("rate", ROWS, _text_of)] == ["p:b"]  # "rates", not "separate"
    assert [r["key"] for r in search("minu", ROWS, _text_of)] == ["p:b"]  # as it is being typed
    assert [r["key"] for r in search("quarters", ROWS, _text_of)] == ["p:a"]  # stemmed


def test_typed_query_syntax_is_searched_as_words_never_run():
    assert fts_query('data NOT "x" AND -y col:z') == (
        '"data"* "not"* """x"""* "and"* "-y"* "col:z"*'
    )
    for q in ['"', "AND", "a OR", "*", "(", "NEAR(a b)", "col:x", "\x00", "ab\x00c", "-", "..."]:
        IndexedSearch()(q, ROWS, _text_of)  # no sqlite3.OperationalError
    assert IndexedSearch()("... -", ROWS, _text_of) == ROWS  # only punctuation: no query


def test_the_index_answers_only_with_the_rows_it_is_given():
    search = IndexedSearch()
    search("trains", ROWS, _text_of)  # indexes all three
    shown = [r for r in ROWS if r["key"] != "p:b"]  # p:b in the bin, or hidden
    assert search("trains", shown, _text_of) == []
    assert [r["key"] for r in search("trains", ROWS, _text_of)] == ["p:b"]  # still indexed


def test_a_changed_item_is_reindexed_and_a_forgotten_one_is_gone():
    search = IndexedSearch()
    search("budget", ROWS, _text_of)
    changed = [dict(r) for r in ROWS]
    changed[0].update(_text="Now about zanzibar.", time="2026-01-09")
    assert [r["key"] for r in search("zanzibar", changed, _text_of)] == ["p:a"]
    assert search("budget", changed, _text_of) == []
    search.forget("p:a")
    assert search.sync([], _text_of) == 0
    assert dict(search._connect().execute("SELECT key, stamp FROM stamps")).keys() == {"p:b", "p:c"}


def test_the_index_persists_so_a_restart_reads_no_text(tmp_path):
    path = tmp_path / "idx" / "index.sqlite"
    IndexedSearch(path)("trains", ROWS, _text_of)
    reads = []
    hits = IndexedSearch(path)("trains", ROWS, lambda r: reads.append(r) or _text_of(r))
    assert [r["key"] for r in hits] == ["p:b"] and reads == []


def test_queries_during_a_first_build_wait_for_it_instead_of_redoing_it(tmp_path):
    rows = [_row(f"p:{i}", f"doc {i}", f"text number {i} about data") for i in range(300)]
    reads, lock = [], threading.Lock()

    def slow_text_of(row):
        with lock:
            reads.append(row["key"])
        return _text_of(row)

    search = IndexedSearch(tmp_path / "index.sqlite")
    answers = []
    threads = [
        threading.Thread(target=lambda: answers.append(len(search("data", rows, slow_text_of))))
        for _ in range(5)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(reads) == len(rows)  # each text read once, not once per query
    assert answers == [300] * 5


def test_the_best_rows_get_a_snippet_the_rest_a_window_and_results_are_capped():
    rows = [_row(f"p:{i}", f"doc {i}", f"some data here {i}") for i in range(30)]
    hits = IndexedSearch(snippet_rows=5, max_results=20)("data", rows, _text_of)
    assert len(hits) == 20
    assert all("data" in r["snippet"] for r in hits)  # past the 5th: the cheap window


def test_an_unreadable_item_fails_no_search_and_is_tried_again():
    tries = []

    def flaky(row):
        if row["key"] == "p:b" and len(tries) < 1:
            tries.append(row["key"])
            raise PermissionError("not now")
        return _text_of(row)

    search = IndexedSearch()
    assert [r["key"] for r in search("budget", ROWS, flaky)] == ["p:a"]  # no 500
    assert [r["key"] for r in search("minute", ROWS, flaky)] == ["p:b"]  # read again, found


def test_another_worker_indexing_the_same_item_meanwhile_is_no_error(tmp_path):
    path = tmp_path / "index.sqlite"
    mine, other = IndexedSearch(path), IndexedSearch(path)
    mine._connect()  # the schema exists
    db = sqlite3.connect(path, isolation_level=None, timeout=30)
    db.execute("BEGIN IMMEDIATE")  # the other worker, mid-write, has p:b already
    db.execute("INSERT INTO stamps (key, stamp) VALUES ('p:b', 'old')")
    threading.Timer(0.3, lambda: db.execute("COMMIT")).start()
    assert [r["key"] for r in mine("minute", ROWS, _text_of)] == ["p:b"]
    assert [r["key"] for r in other("minute", ROWS, _text_of)] == ["p:b"]


def test_a_ledger_rewritten_within_the_same_second_and_size_is_reindexed(tmp_path):
    root = tmp_path / "ledgers"
    root.mkdir()
    f = root / "s.md"
    f.write_text("# S\n\nstatus: busy\n")
    t = f.stat().st_mtime
    cat = Catalog({"ledgers": FolderSource(root, name="ledgers")}, tags={}, search=IndexedSearch())
    assert [r["id"] for r in cat.rows("busy")] == ["s.md"]
    f.write_text("# S\n\nstatus: idle\n")  # same size
    os.utime(f, (t, t))  # and the same mtime, as a sync that keeps mtimes leaves it
    assert [r["id"] for r in cat.rows("idle")] == ["s.md"] and cat.rows("busy") == []


def test_two_views_of_one_item_keep_their_own_fields():
    search = IndexedSearch()
    full = [_row("p:a", "Plan", "text", session="secret-session")]
    bare = [_row("p:a", "Plan", "text")]  # a room shows no session
    assert search("secret", full, _text_of)
    assert search("secret", bare, _text_of) == []


def test_weights_are_one_per_column():
    with pytest.raises(ValueError):
        IndexedSearch(weights=(1, 2))


# -- through the catalog, the store and the API -------------------------------------------


@pytest.fixture
def store(tmp_path):
    s = DocStore(tmp_path / "data")
    for i in range(6):
        s.publish(text=f"# Note {i}\n\nRoutine words, number {i}.", filename=f"n{i}.md")
    s.publish(
        text="# Bread recipe\n\nKnead the dough, then let it rise for an hour before baking.",
        filename="bread.md",
    )
    return s


def test_mk_catalog_keeps_its_index_under_the_data_root(store):
    cat = mk_catalog(store, sources={}, tags={})
    assert isinstance(cat.search, IndexedSearch)
    assert cat.search.path == str(store.target.local_path(".") / "cache/search/index.sqlite")
    assert [r["title"] for r in cat.rows("dough rise hour")] == ["Bread recipe"]


def test_a_corpus_larger_than_the_text_cache_is_read_once(store, monkeypatch):
    """The hang's cause: a text cache smaller than the corpus re-read every text per query."""
    reads = []
    real = store.read_text
    monkeypatch.setattr(store, "read_text", lambda *a, **k: reads.append(a) or real(*a, **k))
    cat = Catalog(
        {"published": PublishedSource(store, max_cached_texts=2)},
        tags={},
        search=IndexedSearch(),
    )
    cat.rows("rise")
    first = len(reads)
    for q in ("d", "do", "dough", "dough rise", "dough rise hour"):
        cat.rows(q)
    assert first == 7 and len(reads) == first  # every text once, then never again


def test_a_purged_document_leaves_the_index(store):
    cat = mk_catalog(store, sources={}, tags={})
    doc = next(m for m in store.list() if m["title"] == "Bread recipe")
    assert cat.rows("dough")
    store.trash(doc["id"])
    assert cat.rows("dough") == []  # the bin is not listed
    assert [r["id"] for r in cat.rows("dough", trash=True)] == [doc["id"]]
    from annals.catalog import purge_document

    purge_document(store, cat, doc["id"])
    keys = dict(cat.search._connect().execute("SELECT key, stamp FROM stamps"))
    assert f"published:{doc['id']}" not in keys


def test_the_api_answers_best_first_with_a_score(store):
    client = TestClient(mk_api(store=store, sources={}, tags={}, listening=False))
    body = client.get("/items", params={"q": "dough rise"}).json()
    assert body["total"] == 1 and body["data"][0]["title"] == "Bread recipe"
    assert body["data"][0]["score"] > 0 and "rise" in body["data"][0]["snippet"]


def test_the_strategy_is_a_keyword(store):
    calls = []

    def mine(q, rows, text_of):
        calls.append(q)
        return rows[:1]

    client = TestClient(mk_api(store=store, sources={}, tags={}, search=mine, listening=False))
    assert client.get("/items", params={"q": "anything"}).json()["total"] == 1
    assert calls == ["anything"]


# -- the page: a search is shown best match first ----------------------------------------


@pytest.fixture(scope="module")
def site(tmp_path_factory, serve):
    from unittest.mock import patch

    store = DocStore(tmp_path_factory.mktemp("best") / "data")
    with patch("annals.store.now_iso", return_value="2026-01-01T10:00:00+00:00"):
        store.publish(text="# Bus times for the harbour\n\nThe table.", title="Bus times for the harbour", filename="t.md")
    for i in range(8):  # unrelated, so a word in a few documents ranks (BM25's IDF)
        store.publish(text=f"# Other {i}\n\nUnrelated words.", title=f"Other {i}", filename=f"o{i}.md")
    for i in range(3):  # newer, and only mention it in passing
        store.publish(text=f"# Log {i}\n\nIn passing, the bus times were fine.", title=f"Log {i}", filename=f"l{i}.md")
    return {"base": serve(store)}


@pytest.fixture
def phone(chromium):
    ctx = chromium.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    yield ctx.new_page()
    ctx.close()


def test_a_search_lists_the_best_match_first_and_clearing_it_restores_newest(phone, site):
    phone.goto(site["base"] + "/")
    phone.locator("input[type=search]").fill("bus times")
    phone.wait_for_function("document.querySelector('.list .card .title')?.textContent === 'Bus times for the harbour'")
    assert phone.locator("select[aria-label=Sort]").input_value() == "best"
    phone.locator("input[type=search]").fill("")
    # newest first again: the old document that matched best goes to the bottom
    phone.wait_for_function(
        "[...document.querySelectorAll('.list .card .title')].slice(-1)[0]?.textContent === 'Bus times for the harbour'"
        " && document.querySelectorAll('.list .card').length === 12"
    )
    assert phone.locator("select[aria-label=Sort]").input_value() == "newest"
