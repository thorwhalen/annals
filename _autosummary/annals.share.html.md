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

The password is a gate on the link, not an account: anyone who knows both may read. It
is hashed with stdlib `scrypt` (the `hasher` seam takes argon2 or anything with
`hash`/`verify`), and a correct one earns an HMAC cookie keyed by that hash, so
changing the password or revoking the link ends every open session.

Tokens come from [`secrets.token_urlsafe()`](https://docs.python.org/3/library/secrets.html#secrets.token_urlsafe) with 128 bits, as heed’s review pages do.

### Module Attributes

| [`ANNALS_ID`](#annals.share.ANNALS_ID)        | an annals id (doc or group) as [`annals.store.mk_id()`](annals.store.html.md#annals.store.mk_id) makes them   |
|-------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| [`DFLT_EXPIRES`](#annals.share.DFLT_EXPIRES)     | a share lasts this long unless told otherwise (`"never"` for no expiry)                                                              |
| [`MIN_PASSWORD_LEN`](#annals.share.MIN_PASSWORD_LEN) | the shortest link password accepted (a gate tried from anywhere must not be guessable)                                               |

### Functions

| [`check_token`](#annals.share.check_token)(token)                                | Raise `ValueError` on anything that could not be a token (a path, a dot, ...).      |
|----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| [`dir_of`](#annals.share.dir_of)(rel)                                       | The directory part of a relative path, with its trailing slash (`""` at the top).   |
| [`filter_refs`](#annals.share.filter_refs)(text, kind, \*, files, shared[, ...]) | `text` with every reference outside the share removed (or rewritten).               |
| [`is_expired`](#annals.share.is_expired)(record, \*[, now])                     | True when the record has an expiry and it is reached (a bad one counts as reached). |
| [`new_token`](#annals.share.new_token)()                                       | A fresh link token: 128 random bits, url-safe.                                      |
| [`now_utc`](#annals.share.now_utc)()                                         | The current time, UTC, second precision (the clock every default reads).            |
| [`parse_expires`](#annals.share.parse_expires)(value, \*[, now])                   | An expiry as an ISO UTC timestamp, or `None` for never.                             |
| [`public_record`](#annals.share.public_record)(record)                             | A record without its password hash (`protected` says whether it has one).           |
| [`references`](#annals.share.references)(text, kind, \*[, from_dir])            | What a page points at: files of its document, and annals pages (by id).             |
| [`resolve_rel`](#annals.share.resolve_rel)(url[, from_dir])                      | A relative url as a file path inside the document, or `None` if it is not one.      |
| [`share_url`](#annals.share.share_url)(base, token)                            | The link a recipient opens, or `None` when no share server is configured.           |

### Classes

| [`PasswordHasher`](#annals.share.PasswordHasher)(\*args, \*\*kwargs)         | What a share needs to gate a link on a password.                      |
|---------------------------------------------------------------------------------------------|-----------------------------------------------------------------------|
| [`ScryptHasher`](#annals.share.ScryptHasher)([n, r, p, salt_bytes, dklen]) | Stdlib `hashlib.scrypt`, stored as `scrypt$n$r$p$salt$hash` (base64). |
| [`Shares`](#annals.share.Shares)(store, \*[, hasher, clock])         | Create, read, list and revoke shares of a `DocStore`'s documents.     |

### annals.share.ANNALS_ID *= '\\\\d{8}-\\\\d{6}-[a-z0-9]+(?:-[a-z0-9]+)\*'*

an annals id (doc or group) as [`annals.store.mk_id()`](annals.store.html.md#annals.store.mk_id) makes them

### annals.share.DFLT_EXPIRES *= '7d'*

a share lasts this long unless told otherwise (`"never"` for no expiry)

### annals.share.MIN_PASSWORD_LEN *= 8*

the shortest link password accepted (a gate tried from anywhere must not be guessable)

### *class* annals.share.PasswordHasher(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

What a share needs to gate a link on a password.

### *class* annals.share.ScryptHasher(n=16384, r=8, p=1, salt_bytes=16, dklen=32)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Stdlib `hashlib.scrypt`, stored as `scrypt$n$r$p$salt$hash` (base64).

The default needs no dependency; `n=2**14, r=8` costs ~16 MB and tens of ms per
check, which the attempt limit of the share server bounds.

### *class* annals.share.Shares(store, \*, hasher=None, clock=<function now_utc>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Create, read, list and revoke shares of a `DocStore`’s documents.

`hasher` hashes link passwords (stdlib scrypt by default); `clock` returns the
current UTC `datetime` (tests pin it).

#### check_password(record, password)

Whether `password` opens `record` (constant time inside the hasher).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### create(ref, , include=None, exclude=(), password=None, expires='7d', title=None)

Share a document or a group (`ref` is its id); return the record (no hash).

A document is shared with all its files unless `include` names some (the page
itself always goes); `include` may also name annals pages the document links
to, which then open inside the share. A group is shared with all its documents
unless `include` names some. `exclude` removes files (or a group’s documents).
A linked page goes with the files it shows. `expires` is anything
[`parse_expires()`](#annals.share.parse_expires) reads, 7 days by default (`"never"` for none); `password`
gates the link (at least `MIN_PASSWORD_LEN` characters).

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

The cookie value a correct password earns: `<issued epoch>.<hmac>`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### unlocked(record, value, , max_age_s)

Whether a cookie value is a live unlock of this record (no password: always).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### annals.share.check_token(token)

Raise `ValueError` on anything that could not be a token (a path, a dot, …).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

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

### annals.share.is_expired(record, , now=None)

True when the record has an expiry and it is reached (a bad one counts as reached).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### annals.share.new_token()

A fresh link token: 128 random bits, url-safe.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.share.now_utc()

The current time, UTC, second precision (the clock every default reads).

* **Return type:**
  [`datetime`](https://docs.python.org/3/library/datetime.html#datetime.datetime)

### annals.share.parse_expires(value, , now=None)

An expiry as an ISO UTC timestamp, or `None` for never.

`None`, `""` and `"never"` mean never. Accepts a duration (`30m`, `12h`, `7d`, `2w`), a date (`2026-11-01`: the
END of that day, UTC, so the link works through the day named), an ISO timestamp (a
naive one is UTC), or a `datetime`. A moment already past is refused.

```pycon
>>> parse_expires("2d", now=datetime(2026, 1, 1, tzinfo=timezone.utc))
'2026-01-03T00:00:00+00:00'
>>> parse_expires("2026-01-05", now=datetime(2026, 1, 1, tzinfo=timezone.utc))
'2026-01-05T23:59:59+00:00'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### annals.share.public_record(record)

A record without its password hash (`protected` says whether it has one).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

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
