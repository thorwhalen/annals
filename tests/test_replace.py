"""Living documents: ``publish(replace=<id>)`` keeps the id and the earlier versions.

Covers a file, a folder with assets, a group member, the outbox path (the replacement
travels as its own directory and is applied where it lands), concurrent appliers, the
version listing, ids that try to escape, and the API and CLI surfaces.
"""

import io
import os
import json
import shutil
import threading

import pytest
from fastapi.testclient import TestClient

from annals.__main__ import run
from annals.api import doctype_guard, mk_app
from annals.auth import no_auth
from annals.store import DocStore, VERSIONS
from annals.target import SshTarget


@pytest.fixture
def store(tmp_path):
    return DocStore(tmp_path / "data")


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_replace_a_file_keeps_the_id_and_the_old_version(store, tmp_path):
    first = store.publish(_write(tmp_path / "g.md", "# Guide\n\nv1 text"), tags=["guide"])
    doc_id = first["id"]
    second = store.publish(_write(tmp_path / "g2.md", "# Guide\n\nv2 text"), replace=doc_id)
    assert second["id"] == doc_id and second["version"] == 2
    assert second["created"] == first["created"] and second["updated"]
    assert second["tags"] == ["guide"]  # inherited when the replacement names none
    assert "replaces" not in second and "pending" not in second
    assert store.read_text(doc_id).endswith("v2 text")
    old = store.meta(f"{doc_id}@1")
    assert old["version_of"] == doc_id and old["version"] == 1
    assert store.read_text(f"{doc_id}@1").endswith("v1 text")
    assert [m["id"] for m in store.list()] == [doc_id]  # one document, not two
    root = store.target.root / "docs"
    assert sorted(p.name for p in root.iterdir()) == [doc_id]  # nothing pending, no claims


def test_replace_a_folder_and_list_versions(store, tmp_path):
    site = tmp_path / "site"
    _write(site / "index.html", "<title>Site</title>v1")
    _write(site / "old.css", "a{}")
    doc_id = store.publish(site)["id"]
    shutil.rmtree(site)
    _write(site / "index.html", "<title>Site</title>v2")
    _write(site / "img" / "new.css", "b{}")
    store.publish(site, replace=doc_id)
    _write(site / "index.html", "<title>Site</title>v3")
    meta = store.publish(site, replace=doc_id)
    assert meta["version"] == 3 and sorted(meta["files"]) == ["img/new.css", "index.html"]
    assert [v["n"] for v in store.versions(doc_id)] == [1, 2, 3]
    assert store.versions(doc_id)[-1]["current"] is True
    assert store.meta(f"{doc_id}@1")["files"] == ["index.html", "old.css"]
    assert store.read_text(f"{doc_id}@1", "old.css") == "a{}"
    assert store.read_text(f"{doc_id}@2").endswith("v2")
    on_disk = store.target.root / "docs" / doc_id / VERSIONS
    assert sorted(p.name for p in on_disk.iterdir()) == ["1", "2"]
    assert not (on_disk / "2" / VERSIONS).exists()  # versions never nest


def test_replace_a_group_member(store, tmp_path):
    a = store.publish(text="# A\n\none", title="A")
    b = store.publish(text="# B\n\ntwo", title="B")
    g = store.make_group("Pair", [a["id"], b["id"]])
    store.publish(text="# B again\n\nthree", replace=b["id"])
    assert store.group(g["id"])["docs"] == [a["id"], b["id"]]
    assert store.meta(b["id"])["title"] == "B again"


def test_outbox_replacement_travels_and_is_applied_where_it_lands(tmp_path):
    server = DocStore(tmp_path / "server")
    doc_id = server.publish(text="# Live\n\nv1", title="Live")["id"]
    outbox = DocStore(tmp_path / "outbox", settle=False)
    pending = outbox.publish(text="# Live\n\nv2", replace=doc_id)
    assert pending["pending"] is True and pending["id"] == doc_id
    assert outbox.pending() == [pending["pending_id"]]
    # the pull: every finished directory moves from the outbox into the server's docs/
    for d in (tmp_path / "outbox" / "docs").iterdir():
        shutil.move(str(d), str(tmp_path / "server" / "docs" / d.name))
    listed = server.list()
    assert [m["id"] for m in listed] == [doc_id] and listed[0]["version"] == 2
    assert server.read_text(doc_id).endswith("v2")


def test_a_replacement_whose_document_is_not_here_stays_visible(tmp_path):
    outbox = DocStore(tmp_path / "outbox", settle=False)
    pending = outbox.publish(text="# Orphan\n\nx", replace="20261020-010101-gone-ab12")
    reader = DocStore(tmp_path / "outbox")  # settles, but has nothing to apply it to
    listed = reader.list()
    assert [m["id"] for m in listed] == [pending["pending_id"]] and listed[0]["pending"]
    assert reader.meta(pending["pending_id"])["pending"] is True


def test_replace_on_a_settling_store_needs_the_document(store):
    with pytest.raises(KeyError):
        store.publish(text="x", replace="20261020-010101-nope-ab12")


def test_two_replacements_apply_in_order_and_concurrent_readers_apply_each_once(tmp_path):
    root = tmp_path / "data"
    doc_id = DocStore(root).publish(text="# D\n\nv1", title="D")["id"]
    outbox = DocStore(root, settle=False)
    for i in (2, 3, 4):
        outbox.publish(text=f"# D\n\nv{i}", replace=doc_id)
    readers = [DocStore(root) for _ in range(6)]
    threads = [threading.Thread(target=r.settle) for r in readers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    DocStore(root).settle()  # whatever a loser left for later
    store = DocStore(root)
    assert store.pending() == []
    assert store.meta(doc_id)["version"] == 4
    assert [store.read_text(f"{doc_id}@{n}")[-2:] for n in (1, 2, 3)] == ["v1", "v2", "v3"]
    assert store.read_text(doc_id).endswith("v4")
    assert sorted(p.name for p in (root / "docs").iterdir()) == [doc_id]


def test_trash_and_restore_keep_the_versions(store):
    doc_id = store.publish(text="# T\n\nv1", title="T")["id"]
    store.publish(text="# T\n\nv2", replace=doc_id)
    store.trash(doc_id)
    assert store.meta(f"{doc_id}@1")["in_trash"] is True
    with pytest.raises(ValueError):
        store.trash(f"{doc_id}@1")
    store.restore(doc_id)
    assert store.read_text(f"{doc_id}@1").endswith("v1")


@pytest.mark.parametrize(
    "bad", ["../x", "a/b", "x@0", "x@-1", "x@1/../../y", "x@..", ".claim-x", "x@1@2"]
)
def test_ids_that_try_to_escape_are_refused(store, bad):
    with pytest.raises(ValueError):
        store.meta(bad)


def test_replace_refuses_bad_ids_and_reserved_names(store, tmp_path):
    doc_id = store.publish(text="# R\n\nv1", title="R")["id"]
    with pytest.raises(ValueError):
        store.publish(text="x", replace="../../etc")
    d = tmp_path / "d"
    _write(d / "index.html", "<p>hi")
    _write(d / VERSIONS / "1" / "meta.json", "{}")
    with pytest.raises(ValueError):
        store.publish(d, replace=doc_id, exclude=())
    assert store.meta(doc_id).get("version", 1) == 1


def test_api_serves_versions_with_the_right_caching(store, tmp_path):
    doc_id = store.publish(_write(tmp_path / "p.html", "<p>one</p>"))["id"]
    store.publish(_write(tmp_path / "p.html", "<!doctype html><p>two</p>"), replace=doc_id)
    client = TestClient(mk_app(store=store, authorizer=no_auth))
    cur = client.get(f"/annals/api/docs/{doc_id}").json()
    assert cur["version"] == 2 and [v["n"] for v in cur["versions"]] == [1]
    old = client.get(f"/annals/api/docs/{doc_id}@1").json()
    assert old["version_of"] == doc_id and old["current_version"] == 2
    r_cur = client.get(f"/annals/api/raw/{doc_id}/p.html")
    r_old = client.get(f"/annals/api/raw/{doc_id}@1/p.html")
    assert "two" in r_cur.text and r_cur.headers["cache-control"] == "private, no-cache"
    assert "one" in r_old.text and "max-age" in r_old.headers["cache-control"]
    assert r_old.text.startswith("<!doctype html>")  # the guard
    assert "sandbox" in r_old.headers["content-security-policy"]
    listed = client.get("/annals/api/items").json()["data"]
    assert [i["id"] for i in listed] == [doc_id] and listed[0]["time"] == cur["updated"]


def test_doctype_guard():
    assert doctype_guard(b"<!DOCTYPE html><p>x") == b"<!DOCTYPE html><p>x"
    assert doctype_guard(b"\xef\xbb\xbf <!-- c --> <!doctype html>") .startswith(b"\xef\xbb\xbf")
    out = doctype_guard(b"<html><head><meta charset=latin1></head><p>x</p></html>")
    assert out.startswith(b"<!doctype html>\n") and out.count(b"charset") == 1
    assert b'name="viewport"' in out and out.endswith(b"</html>")
    assert doctype_guard(b"\xef\xbb\xbf<p>x").count(b"\xef\xbb\xbf") == 0


def test_cli_replace_prints_the_same_link(tmp_path, monkeypatch):
    monkeypatch.setenv("ANNALS_TARGET", str(tmp_path / "data"))
    monkeypatch.setenv("ANNALS_BASE_URL", "https://example.com/annals")
    monkeypatch.delenv("ANNALS_OUTBOX", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    src = _write(tmp_path / "r.md", "# Report\n\nv1")
    out = io.StringIO()
    assert run(["publish", str(src)], out=out, err=io.StringIO()) == 0
    url = out.getvalue().strip()
    _write(src, "# Report\n\nv2")
    out = io.StringIO()
    assert run(["publish", str(src), "--replace", url], out=out, err=io.StringIO()) == 0
    assert out.getvalue().strip() == url
    err = io.StringIO()
    assert run(["publish", str(src), str(src), "--replace", url], out=io.StringIO(), err=err) == 1
    assert "one path" in err.getvalue()


def test_configure_outbox_is_saved_and_makes_replacements_pending(tmp_path, monkeypatch):
    monkeypatch.delenv("ANNALS_TARGET", raising=False)
    monkeypatch.delenv("ANNALS_BASE_URL", raising=False)
    monkeypatch.delenv("ANNALS_OUTBOX", raising=False)
    monkeypatch.delenv("ANNALS_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    data = tmp_path / "outbox"
    args = ["configure", "--target", str(data), "--base-url", "https://x.example/annals"]
    assert run([*args, "--outbox"], out=io.StringIO(), err=io.StringIO()) == 0
    out = io.StringIO()
    run(["configure"], out=out, err=io.StringIO())
    assert json.loads(out.getvalue())["outbox"] is True
    out = io.StringIO()
    monkeypatch.setattr("sys.stdin", io.StringIO("# Far\n\nv2"))
    rc = run(["publish", "-", "--replace", "20261020-010101-far-ab12"], out=out, err=io.StringIO())
    assert rc == 0 and out.getvalue().strip() == "https://x.example/annals/d/20261020-010101-far-ab12"
    assert len(DocStore(data, settle=False).pending()) == 1


@pytest.fixture
def loopback_ssh(tmp_path, monkeypatch):
    """A fake ``ssh`` on PATH that runs the remote command here: real rsync, real shell."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "ssh"
    fake.write_text(
        '#!/bin/sh\nwhile [ "$1" = "-o" ]; do shift 2; done\nshift\nexec sh -c "$*"\n'
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")


@pytest.mark.skipif(not shutil.which("rsync"), reason="needs rsync")
def test_replace_over_ssh(tmp_path, loopback_ssh):
    remote = tmp_path / "remote"
    store = DocStore(SshTarget("loop", str(remote)))
    site = tmp_path / "site"
    _write(site / "index.html", "<title>S</title>v1")
    _write(site / "a.css", "a{}")
    doc_id = store.publish(site)["id"]
    _write(site / "index.html", "<title>S</title>v2")
    meta = store.publish(site, replace=doc_id)
    assert meta["version"] == 2 and meta["id"] == doc_id
    assert store.read_text(f"{doc_id}@1").endswith("v1")
    assert store.read_text(doc_id).endswith("v2")
    assert sorted(p.name for p in (remote / "docs").iterdir()) == [doc_id]
    assert [m["id"] for m in DocStore(remote).list()] == [doc_id]


# -- what the adversarial review found: failures mid-apply, partial pulls, re-pulls ----


def _queue(root, doc_id, text):
    """Publish a replacement on an outbox view of ``root``; return its directory."""
    meta = DocStore(root, settle=False).publish(text=text, replace=doc_id)
    return root / "docs" / meta["pending_id"]


def test_a_failure_mid_apply_leaves_the_document_readable(tmp_path, monkeypatch):
    root = tmp_path / "data"
    store = DocStore(root)
    doc_id = store.publish(text="# F\n\nv1", title="F")["id"]
    pend = _queue(root, doc_id, "# F\n\nv2")
    real = store.target.write_text

    def full_disk(rel, text):
        if rel.endswith(f"{doc_id}/meta.json"):
            raise OSError(28, "No space left on device")
        return real(rel, text)

    monkeypatch.setattr(store.target, "write_text", full_disk)
    assert store.settle() == []
    assert store.read_text(doc_id).endswith("v1") and pend.is_dir()
    monkeypatch.setattr(store.target, "write_text", real)
    assert store.settle() == [doc_id] and store.read_text(doc_id).endswith("v2")
    assert sorted(p.name for p in (root / "docs").iterdir()) == [doc_id]


def test_untrusted_history_does_not_break_the_document(tmp_path):
    root = tmp_path / "data"
    store = DocStore(root)
    doc_id = store.publish(text="# H\n\nv1", title="H")["id"]
    meta_path = root / "docs" / doc_id / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta_path.write_text(json.dumps({**meta, "versions": "not a list"}))
    _queue(root, doc_id, "# H\n\nv2")
    assert store.settle() == [] and store.read_text(doc_id).endswith("v1")


def test_a_half_arrived_or_broken_replacement_waits_visibly(tmp_path):
    root = tmp_path / "data"
    store = DocStore(root)
    doc_id = store.publish(text="# P\n\nv1", title="P")["id"]
    pend = _queue(root, doc_id, "# P\n\nv2 is longer")
    body = pend / "document.md"
    full = body.read_text()
    body.write_text(full[:5])  # the pull has not finished this file
    assert store.settle() == [] and store.read_text(doc_id).endswith("v1")
    assert pend.name in [m["id"] for m in store.list()]  # listed, not lost
    body.write_text(full)  # the next pull completes it
    assert store.settle() == [doc_id]
    broken = _queue(root, doc_id, "# P\n\nv3")
    (broken / "meta.json").write_text("{trunc")
    assert store.settle() == [] and broken.is_dir()
    assert store.meta(doc_id)["version"] == 2


def test_a_replacement_pulled_twice_is_applied_once(tmp_path):
    root = tmp_path / "data"
    store = DocStore(root)
    doc_id = store.publish(text="# R\n\nv1", title="R")["id"]
    pend = _queue(root, doc_id, "# R\n\nv2")
    copy = tmp_path / "copy"
    shutil.copytree(pend, copy)
    store.settle()
    shutil.copytree(copy, pend)  # a retried pull lands the same directory again
    store.settle()
    assert store.meta(doc_id)["version"] == 2 and store.pending() == []
    assert [p.name.startswith(pend.name) for p in (root / "trash").iterdir()] == [True]  # set aside
    (dup,) = [m["id"] for m in store.list(trash=True)]
    store.purge(dup)  # and it can be emptied from the bin
    assert list((root / "trash").iterdir()) == []


def test_a_stale_lock_left_by_a_crash_is_recovered(tmp_path, monkeypatch):
    import annals.store as st

    root = tmp_path / "data"
    store = DocStore(root)
    doc_id = store.publish(text="# C\n\nv1", title="C")["id"]
    pend = _queue(root, doc_id, "# C\n\nv2")
    # the crash: the replacement was claimed and the document moved aside, then nothing
    lock = root / "docs" / f".lock-{doc_id}"
    lock.mkdir()
    (lock / "lock.json").write_text(json.dumps({"since": 0, "pending": pend.name, "n": 1}))
    pend.rename(lock / "next")
    (root / "docs" / doc_id).rename(lock / "old")
    monkeypatch.setattr(st, "SWAP_WAIT_S", 0.05)
    assert store.settle() == [doc_id]  # recovered (put back), then applied
    assert store.read_text(doc_id).endswith("v2") and store.read_text(f"{doc_id}@1").endswith("v1")
    assert sorted(p.name for p in (root / "docs").iterdir()) == [doc_id]


def test_a_fresh_lock_is_respected_and_readers_wait_out_a_swap(tmp_path):
    root = tmp_path / "data"
    store = DocStore(root)
    doc_id = store.publish(text="# W\n\nv1", title="W")["id"]
    lock = root / "docs" / f".lock-{doc_id}"
    lock.mkdir()
    (lock / "lock.json").write_text(json.dumps({"since": 9e99}))
    (root / "docs" / doc_id).rename(lock / "old")  # mid-swap, in another process
    timer = threading.Timer(0.2, lambda: (lock / "old").rename(root / "docs" / doc_id))
    timer.start()
    assert DocStore(root).meta(doc_id)["title"] == "W"  # waited instead of a 404
    timer.join()
    _queue(root, doc_id, "# W\n\nv2")
    assert store.settle() == []  # the lock is someone else's
    lock.joinpath("lock.json").unlink()
    lock.rmdir()
    assert store.settle() == [doc_id]


def test_html_revalidates_with_an_etag(store, tmp_path):
    doc_id = store.publish(_write(tmp_path / "e.html", "<p>x</p>"))["id"]
    client = TestClient(mk_app(store=store, authorizer=no_auth))
    first = client.get(f"/annals/api/raw/{doc_id}/e.html")
    again = client.get(f"/annals/api/raw/{doc_id}/e.html", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304


def test_a_crash_after_going_live_but_before_the_meta_is_rolled_back(tmp_path):
    root = tmp_path / "data"
    store = DocStore(root)
    doc_id = store.publish(text="# L\n\nv1", title="L")["id"]
    pend = _queue(root, doc_id, "# L\n\nv2")
    lock = root / "docs" / f".lock-{doc_id}"
    lock.mkdir()
    (lock / "lock.json").write_text(json.dumps({"since": 0, "pending": pend.name, "n": 1}))
    (root / "docs" / doc_id).rename(lock / "old")
    pend.rename(root / "docs" / doc_id)  # live, still carrying the replacement's meta
    assert store.settle() == [doc_id]
    assert store.meta(doc_id)["version"] == 2 and store.read_text(f"{doc_id}@1").endswith("v1")


def test_locks_are_exclusive_and_block_trash_while_held(tmp_path):
    store = DocStore(tmp_path / "data")
    doc_id = store.publish(text="# X\n\nv1", title="X")["id"]
    lock = store._lock("docs", doc_id)
    assert lock and json.loads((tmp_path / "data" / lock / "lock.json").read_text())["pid"]
    assert store._lock("docs", doc_id) is None  # held by a live process: not stale
    with pytest.raises(RuntimeError):
        store.trash(doc_id)
    store._unlock(lock)
    assert store.trash(doc_id)["in_trash"] is True


@pytest.mark.skipif(not shutil.which("rsync"), reason="needs rsync")
def test_ssh_lock_is_created_with_its_note(tmp_path, loopback_ssh):
    t = SshTarget("loop", str(tmp_path / "remote"))
    t.make_lock("docs/.lock-a", '{"since": 1}')
    assert (tmp_path / "remote" / "docs" / ".lock-a" / "lock.json").read_text() == '{"since": 1}'
    with pytest.raises(RuntimeError):
        t.make_lock("docs/.lock-a", "{}")
    (tmp_path / "remote" / "docs" / "f").mkdir()
    (tmp_path / "remote" / "docs" / "f" / "a b.txt").write_text("hello")
    assert t.file_sizes("docs/f", ["a b.txt", "nope"]) == {"a b.txt": 5}
