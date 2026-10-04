# Research

What existed before annals, and what was borrowed from it.

- **A page pushed over ssh.** The owner's session-watching tool already rendered a status page and rsynced it into a server-side data directory that a tiny web app served behind the platform login. That transport (a file write over ssh, no token) is annals's publish operation: proven, prompt-free, and it keeps the read side behind the login that already exists.
- **A PyPI package plus a thin server wrapper.** Other apps on the same host install their logic from PyPI and keep only a few lines of wiring on the server. annals follows it: the package holds the API and the page; the host keeps a few lines of wiring and a page shell.
- **claude.ai Artifacts.** A private page per published artifact, with a comment loop back to the agent. Good prior art for the "link the owner opens on a phone" experience; not usable from an unattended or server-side session, and it has no home with search, sort and a bin. A comment loop is on the roadmap.
- **Markdown rendering.** `marked` (MIT) renders in the browser, which makes the source toggle free (same text). Server-side rendering with a Python markdown library or PDF export is a declared replacement, not needed for v1.

Names were chosen from short English words free on PyPI. The first pick, `tray`, is reserved on PyPI (it shipped briefly as `intray`); the package was renamed `annals`, free on both PyPI and npm, before anything depended on it.
