# annals.share

Share links: one document (or a group) behind a public, unguessable, revocable link.

A share is a record under the data root, `shares/<token>.json`, written through the
same [`annals.target.Target`](annals.target.html.md#annals.target.Target) as the documents, so `annals share` works over ssh
exactly like `annals publish`. The record is the whole contract; the owner’s API, the
page’s Share button, the CLI and the public share server (`annals.share_api`) are
surfaces over it:

```default
{
 "token": "<22 url-safe chars, 128 random bits>",
 "title": "...", "created": "<iso>",
 "root": {"kind": "doc" | "group", "id": "<id>"},
 "docs": {"<doc id>": ["<file>", ...], ...},   # what the link may reach, and only that
 "expires": "<iso>" | null,
 "password": "scrypt$..." | null,               # a hash; the password is never stored
 "revoked": "<iso>" | null                       # a tombstone: a revoked link is a 404
}
```

`docs` is the scope. Every request of the public server is checked against it, never
against what the link was made from: a file not listed is a 404 even when it sits beside
the shared page, and a page or a link of the shared text that points outside the scope is
removed before the text leaves the server ([`filter_refs()`](#annals.share.filter_refs)), so the recipient sees
neither private ids nor private paths.

The link itself (the token, the password gate, expiry, revocation) is a
`caplinks.CapabilityLinks` over these records; what is annals’ own is the scope
and the filtering. The password is a gate on the link, not an account: anyone who knows
both may read. It is hashed (stdlib `scrypt` by default, the `hasher` seam takes
argon2), and a correct one earns an HMAC cookie keyed by that hash, so changing the
password or revoking the link ends every open session.

### Module Attributes

| [`ANNALS_ID`](#annals.share.ANNALS_ID)   | an annals id (doc or group) as [`annals.store.mk_id()`](annals.store.html.md#annals.store.mk_id) makes them   |
|--------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------|

### Functions

| [`dir_of`](#annals.share.dir_of)(rel)                                       | The directory part of a relative path, with its trailing slash (`""` at the top).   |
|----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| [`filter_refs`](#annals.share.filter_refs)(text, kind, \*, files, shared[, ...]) | `text` with every reference outside the share removed (or rewritten).               |
| [`references`](#annals.share.references)(text, kind, \*[, from_dir])            | What a page points at: files of its document, and annals pages (by id).             |
| [`resolve_rel`](#annals.share.resolve_rel)(url[, from_dir])                      | A relative url as a file path inside the document, or `None` if it is not one.      |
| [`share_url`](#annals.share.share_url)(base, token)                            | The link a recipient opens, or `None` when no share server is configured.           |

### Classes

| [`Shares`](#annals.share.Shares)(store, \*[, hasher, clock])   | Create, read, list and revoke shares of a `DocStore`'s documents.   |
|---------------------------------------------------------------------------------------|---------------------------------------------------------------------|

### annals.share.ANNALS_ID *= '\\\\d{8}-\\\\d{6}-[a-z0-9]+(?:-[a-z0-9]+)\*'*

an annals id (doc or group) as [`annals.store.mk_id()`](annals.store.html.md#annals.store.mk_id) makes them

### *class* annals.share.Shares(store, \*, hasher=None, clock=<function now_utc>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Create, read, list and revoke shares of a `DocStore`’s documents.

What a share reaches (its scope) is decided here; the link itself is `links`, a
`caplinks.CapabilityLinks` over the records under `shares/`. `hasher`
hashes link passwords (stdlib scrypt by default); `clock` returns the current UTC
`datetime` (tests pin it).

#### check_password(record, password)

Whether `password` opens `record`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### create(ref, , include=None, exclude=(), password=None, expires='7d', title=None)

Share a document or a group (`ref` is its id); return the record (no hash).

A document is shared with all its files unless `include` names some (the page
itself always goes); `include` may also name annals pages the document links
to, which then open inside the share. A group is shared with all its documents
unless `include` names some. `exclude` removes files (or a group’s documents).
A linked page goes with the files it shows. `expires` is anything
`parse_expires()` reads, 7 days by default (`"never"` for none); `password`
gates the link (at least `caplinks.MIN_PASSWORD_LEN` characters).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### list(, all=False)

Every share, newest first, without hashes; `all` adds revoked and expired.

* **Return type:**
  [`list`](#annals.share.Shares.list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### record(token)

The stored record (hash included), revoked or not; `None` if there is none.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### resources(doc_id)

What the Share dialog offers for a document: its files, and the pages it links.

`{"main", "files": [{"rel", "kind", "size", "referenced"}], "pages": [{"id",
"title", "kind"}]}`. `referenced` marks the files the page itself shows or
links; `pages` are the other annals documents its text links to.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### revoke(token)

End a link now (idempotent). The record stays, as a tombstone, for the list.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### status(token)

`("ok" | "expired" | "missing", record)`; a revoked link is `missing`.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict) | [`None`](https://docs.python.org/3/builtins/constants.html#None)]

#### unlock_value(record)

The cookie value a correct password earns.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### unlocked(record, value, , max_age_s)

Whether a cookie value is a live unlock of this record (no password: always).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### annals.share.dir_of(rel)

The directory part of a relative path, with its trailing slash (`""` at the top).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.share.filter_refs(text, kind, , files, shared, from_dir='', private_hosts=())

`text` with every reference outside the share removed (or rewritten).

`files` are the document’s files the share includes; `shared(id)` maps an annals
id to where the recipient opens it (in scope) or `None` (not shared). A markdown
image out of scope disappears, a link keeps its words; an html attribute goes; a bare
annals url becomes “(link not shared)” and a bare annals id “(not shared)”. The text
of the page itself is the owner’s: only references are touched. An absolute url on
one of `private_hosts` (the owner’s own) goes too, whatever its path. Every kind of
text is filtered (markdown, html, plain text, svg): only markdown syntax is markdown’s.
Best effort by design, and the second line of defence: the share server answers 404
for anything outside the share however the text names it.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.share.references(text, kind, , from_dir='')

What a page points at: files of its document, and annals pages (by id).

`{"files": [rel, ...], "ids": [annals id, ...]}`, each in first-seen order; it
feeds the Share dialog, which offers them to the owner.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### annals.share.resolve_rel(url, from_dir='')

A relative url as a file path inside the document, or `None` if it is not one.

```pycon
>>> resolve_rel("img/a.png?x=1#y", "notes/")
'notes/img/a.png'
>>> resolve_rel("../../etc/passwd") is None, resolve_rel("https://x.org/a") is None
(True, True)
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### annals.share.share_url(base, token)

The link a recipient opens, or `None` when no share server is configured.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)
