# Roadmap

Things deliberately left out of v1, each at a seam that already exists.

- **http ingest** (seam 1): an endpoint with a bearer token so an agent with no ssh route to the host can still publish. Needs a secret in the host's environment and a public route; the read side stays behind the login.
- **comments back to the agent**: the owner leaves a note on a document and the publishing session is told. The source recorded in `meta.json` (session name) is the hook.
- **full-text search** on the server (today: title, tags, excerpt, source; the page also searches what it has loaded).
- **retention** for the bin (auto-purge after N days), as a `tray serve` option.
- **a second tray** in one page (several targets, several base urls) if the owner ever runs more than one host.
