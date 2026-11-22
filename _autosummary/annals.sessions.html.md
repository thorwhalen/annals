# annals.sessions

The sessions that made a document: each one’s name and the link that opens it.

A document’s meta carries them as `sessions`, a list of `{"name": ..., "url": ...}`
in the order they first worked on it: the session that published it, then each session
that published a new version (`annals publish --replace`). A group shows the sessions of
its documents. The link is a claude.ai link (`https://claude.ai/code/<bridge session id>`),
which only the owner can open; it is provenance, like `source` and `artifact`, so it is
never part of the document’s own content and leaves with the meta: a share or a room shows
an allowlist of meta fields that does not name it.

```pycon
>>> sessions_of({"source": {"session": "b2", "session_url": "https://claude.ai/code/session_01X"}})
[{'name': 'b2', 'url': 'https://claude.ai/code/session_01X'}]
>>> merged_sessions([{"name": "a", "url": ""}], [{"name": "a", "url": "https://claude.ai/code/s"}, {"name": "b", "url": ""}])
[{'name': 'a', 'url': 'https://claude.ai/code/s'}, {'name': 'b', 'url': ''}]
```

### Module Attributes

| [`SESSION_URL_TEMPLATE`](#annals.sessions.SESSION_URL_TEMPLATE)   | the claude.ai link of a session, from its Remote Control (bridge) session id                                           |
|-------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------|
| [`BRIDGE_ENV_VAR`](#annals.sessions.BRIDGE_ENV_VAR)         | its Remote Control session id                                                                                          |
| [`MAX_SESSIONS`](#annals.sessions.MAX_SESSIONS)           | the first, and the latest ones (a living page republished by a new session every day would otherwise grow without end) |
| [`MAX_READ`](#annals.sessions.MAX_READ)               | the most entries read from a meta written elsewhere, before merging                                                    |

### Functions

| [`checked_sessions`](#annals.sessions.checked_sessions)(sessions, check_url)      | `sessions` with each link `check_url` refuses (it raises `ValueError`) emptied: a meta written by another publisher is checked again before a page shows its links.   |
|---------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`merged_sessions`](#annals.sessions.merged_sessions)(\*lists[, limit])          | The sessions of `lists` in order, one entry each: the same link, or the same name when one of the two has no link, is the same session (the link is kept).            |
| [`session_names`](#annals.sessions.session_names)(meta)                        | The names of the sessions that made `meta`'s document (for `ls --session`).                                                                                           |
| [`session_url_from_env`](#annals.sessions.session_url_from_env)([env, var, template]) | The claude.ai link of the Claude Code session this process runs in, or `""`.                                                                                          |
| [`sessions_of`](#annals.sessions.sessions_of)(meta)                          | The sessions that made the document `meta` describes (see the module doc).                                                                                            |

### annals.sessions.BRIDGE_ENV_VAR *= 'CLAUDE_CODE_BRIDGE_SESSION_ID'*

its Remote Control session id

* **Type:**
  the variable Claude Code sets in a session’s shell

### annals.sessions.MAX_READ *= 200*

the most entries read from a meta written elsewhere, before merging

### annals.sessions.MAX_SESSIONS *= 12*

the first, and the latest ones (a living page
republished by a new session every day would otherwise grow without end)

* **Type:**
  the most sessions a document keeps

### annals.sessions.SESSION_URL_TEMPLATE *= 'https://claude.ai/code/{bridge_id}'*

the claude.ai link of a session, from its Remote Control (bridge) session id

### annals.sessions.checked_sessions(sessions, check_url)

`sessions` with each link `check_url` refuses (it raises `ValueError`) emptied:
a meta written by another publisher is checked again before a page shows its links.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### annals.sessions.merged_sessions(\*lists, limit=12)

The sessions of `lists` in order, one entry each: the same link, or the same name
when one of the two has no link, is the same session (the link is kept). At most
`limit`: the first session and the latest ones.

```pycon
>>> [s["name"] for s in merged_sessions([{"name": str(i), "url": ""} for i in range(20)], limit=4)]
['0', '17', '18', '19']
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### annals.sessions.session_names(meta)

The names of the sessions that made `meta`’s document (for `ls --session`).

* **Return type:**
  [`set`](https://docs.python.org/3/builtins/stdtypes.html#set)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### annals.sessions.session_url_from_env(env=None, , var='CLAUDE_CODE_BRIDGE_SESSION_ID', template='https://claude.ai/code/{bridge_id}')

The claude.ai link of the Claude Code session this process runs in, or `""`.

```pycon
>>> session_url_from_env({"CLAUDE_CODE_BRIDGE_SESSION_ID": "session_01X"})
'https://claude.ai/code/session_01X'
>>> session_url_from_env({})
''
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### annals.sessions.sessions_of(meta)

The sessions that made the document `meta` describes (see the module doc).

A meta written before `sessions` existed names its one session in `source`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
