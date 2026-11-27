"""The search strategies (annals.search), the catalog's ``search`` seam, and the page's ranking.

The bug this pins (2026-11-27): "Search all text" sat on "Searching…" for minutes. Every
query scanned every item and re-read the full text of each one whose title lacked a word;
the text cache (512) was smaller than the corpus (~1400 documents), so nothing stayed
cached, and each debounced keystroke started another such scan beside the last. Replayed
on the live data, one typed query answered after 35 s, before any network. The guard is
:func:`test_a_corpus_larger_than_the_text_cache_is_read_once`: an index reads an item's
text once per change, never once per query.
"""

import threading

import pytest
from fastapi.testclient import TestClient

from annals.api import mk_api
from annals.catalog import Catalog, mk_catalog
from annals.search import IndexedSearch, fts_query, scan_search
from annals.sources import PublishedSource
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
    _row("p:b", "Feature vectors", "How much data a player makes: data rates per minute.", time="2026-01-02"),
    _row("p:c", "Notes", "A separate generated thing, nothing about money.", time="2026-01-01"),
]


@pytest.fixture(params=["indexed", "scan"])
def strategy(request):
    return IndexedSearch() if request.param == "indexed" else scan_search


# -- what every strategy promises ---------------------------------------------------------


def test_every_word_is_required_and_found_in_the_full_text(strategy):
    assert [r["key"] for r in strategy("data minute", ROWS, _text_of)] == ["p:b"]
    assert strategy("data nowhere-at-all", ROWS, _text_of) == []
    hit = strategy("headcount", ROWS, _text_of)[0]
    assert hit["key"] == "p:a" and "headcount" in hit["snippet"].lower()


def test_an_empty_query_is_every_row_as_given(strategy):
    assert strategy("   ", ROWS, _text_of) == ROWS


# -- the index ---------------------------------------------------------------------------


def test_the_index_ranks_a_title_match_above_a_passing_mention():
    rows = [
        _row("p:mention", "Weekly notes", "In passing: the data rates looked fine.", time="2026-02-01"),
        _row("p:title", "Data rates per minute", "A table.", time="2026-01-01"),
    ] + [_row(f"p:other{i}", f"Other {i}", "Unrelated words.") for i in range(8)]  # so BM25's IDF is not ~0
    hits = IndexedSearch()("data rates", rows, _text_of)
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
    for q in ['"', "AND", "a OR", "*", "(", "NEAR(a b)", "col:x"]:
        IndexedSearch()(q, ROWS, _text_of)  # no sqlite3.OperationalError


def test_the_index_answers_only_with_the_rows_it_is_given():
    search = IndexedSearch()
    search("data", ROWS, _text_of)  # indexes all three
    shown = [r for r in ROWS if r["key"] != "p:b"]  # p:b in the bin, or hidden
    assert search("data", shown, _text_of) == []
    assert [r["key"] for r in search("data", ROWS, _text_of)] == ["p:b"]  # still indexed


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
    IndexedSearch(path)("data", ROWS, _text_of)
    reads = []
    hits = IndexedSearch(path)("data", ROWS, lambda r: reads.append(r) or _text_of(r))
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


def test_snippets_only_for_the_best_rows_and_results_capped():
    rows = [_row(f"p:{i}", f"doc {i}", f"some data here {i}") for i in range(30)]
    hits = IndexedSearch(snippet_rows=5, max_results=20)("data", rows, _text_of)
    assert len(hits) == 20
    assert sum("snippet" in r for r in hits) == 5


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
        text="# Feature vectors\n\nMeasured: the data rates per minute of a player.",
        filename="rates.md",
    )
    return s


def test_mk_catalog_keeps_its_index_under_the_data_root(store):
    cat = mk_catalog(store, sources={}, tags={})
    assert isinstance(cat.search, IndexedSearch)
    assert cat.search.path.startswith(str(store.target.local_path(".")))
    assert [r["title"] for r in cat.rows("data rates per minute")] == ["Feature vectors"]


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
    cat.rows("minute")
    first = len(reads)
    for q in ("d", "da", "data", "data rates", "data rates per minute"):
        cat.rows(q)
    assert first == 7 and len(reads) == first  # every text once, then never again


def test_a_purged_document_leaves_the_index(store):
    cat = mk_catalog(store, sources={}, tags={})
    doc = next(m for m in store.list() if m["title"] == "Feature vectors")
    assert cat.rows("rates")
    store.trash(doc["id"])
    assert cat.rows("rates") == []  # the bin is not listed
    assert [r["id"] for r in cat.rows("rates", trash=True)] == [doc["id"]]
    from annals.catalog import purge_document

    purge_document(store, cat, doc["id"])
    keys = dict(cat.search._connect().execute("SELECT key, stamp FROM stamps"))
    assert f"published:{doc['id']}" not in keys


def test_the_api_answers_best_first_with_a_score(store):
    client = TestClient(mk_api(store=store, sources={}, tags={}, listening=False))
    body = client.get("/items", params={"q": "data rates"}).json()
    assert body["total"] == 1 and body["data"][0]["title"] == "Feature vectors"
    assert body["data"][0]["score"] > 0 and "rates" in body["data"][0]["snippet"]


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
        store.publish(text="# Data rates per minute\n\nThe table.", title="Data rates per minute", filename="t.md")
    for i in range(8):  # unrelated, so a word in a few documents ranks (BM25's IDF)
        store.publish(text=f"# Other {i}\n\nUnrelated words.", title=f"Other {i}", filename=f"o{i}.md")
    for i in range(3):  # newer, and only mention it in passing
        store.publish(text=f"# Log {i}\n\nIn passing, data rates were fine.", title=f"Log {i}", filename=f"l{i}.md")
    return {"base": serve(store)}


@pytest.fixture
def phone(chromium):
    ctx = chromium.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    yield ctx.new_page()
    ctx.close()


def test_a_search_lists_the_best_match_first_and_clearing_it_restores_newest(phone, site):
    phone.goto(site["base"] + "/")
    phone.locator("input[type=search]").fill("data rates")
    phone.wait_for_function("document.querySelector('.list .card .title')?.textContent === 'Data rates per minute'")
    assert phone.locator("select[aria-label=Sort]").input_value() == "best"
    phone.locator("input[type=search]").fill("")
    # newest first again: the old document that matched best goes to the bottom
    phone.wait_for_function(
        "[...document.querySelectorAll('.list .card .title')].slice(-1)[0]?.textContent === 'Data rates per minute'"
        " && document.querySelectorAll('.list .card').length === 12"
    )
    assert phone.locator("select[aria-label=Sort]").input_value() == "newest"
