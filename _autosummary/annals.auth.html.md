# annals.auth

The auth seam: who may read the annals.

A annals is private by construction, so the server asks every request who is calling. The
answer comes from one of three `Authorizer` callables, chosen by [`authorizer_from_env()`](#annals.auth.authorizer_from_env)
(or passed to `annals.api.mk_app()`):

* [`no_auth()`](#annals.auth.no_auth): everyone is the owner. Right for `annals serve` bound to `127.0.0.1`,
  wrong anywhere else.
* [`CookieWhoami`](#annals.auth.CookieWhoami): forward the request’s cookies to an identity endpoint that answers
  `{"email": ...}` (enlace_auth’s `/auth/whoami`), and allow the listed emails. This is
  how a annals sits behind an existing login without owning passwords: the login page, the
  session cookie and the logout belong to the platform; the annals only checks the allowlist.
  Env: `ANNALS_WHOAMI_URL`, `ANNALS_ALLOWED_USERS` (comma separated), `ANNALS_LOGIN_URL`.
* [`BasicAuth`](#annals.auth.BasicAuth): one username and password (HTTP Basic). For a annals with no platform
  login in front of it. Env: `ANNALS_BASIC_USER`, `ANNALS_BASIC_PASSWORD`.

An authorizer returns the caller’s identity (a string) or `None`. The API turns `None`
into a 303 to the login page for a browser GET, and a 401 for anything else, mirroring
what enlace_auth does so the two are indistinguishable from the phone.

### Functions

| [`authorizer_from_env`](#annals.auth.authorizer_from_env)([env])   | Pick the authorizer the environment describes; see the module docstring.   |
|-------------------------------------------------------------------------------|----------------------------------------------------------------------------|
| [`no_auth`](#annals.auth.no_auth)(request)             | Everyone is `owner`.                                                       |

### Classes

| [`BasicAuth`](#annals.auth.BasicAuth)(username, password)                      | HTTP Basic with one username and password, compared in constant time.           |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`CookieWhoami`](#annals.auth.CookieWhoami)(whoami_url, allowed_users, \*[, ...]) | Ask an identity endpoint who holds this request's cookies; allow listed emails. |
| [`RequestLike`](#annals.auth.RequestLike)(\*args, \*\*kwargs)                    | The two things an authorizer reads from a request.                              |

### *class* annals.auth.BasicAuth(username, password)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

HTTP Basic with one username and password, compared in constant time.

### *class* annals.auth.CookieWhoami(whoami_url, allowed_users, , login_url='/auth/login')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Ask an identity endpoint who holds this request’s cookies; allow listed emails.

### *class* annals.auth.RequestLike(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

The two things an authorizer reads from a request.

### annals.auth.authorizer_from_env(env=None)

Pick the authorizer the environment describes; see the module docstring.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`RequestLike`](#annals.auth.RequestLike)], [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### annals.auth.no_auth(request)

Everyone is `owner`. Only for a server that listens on localhost.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
