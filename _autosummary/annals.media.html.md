# annals.media

The media relay for published html pages: what a framed page plays, told to the page around it.

A spoken overview is an html page shown in a sandboxed frame, so the annals page cannot see
its audio. This adds one inlined script (the page’s own `ui/media-progress.js`) to any
html page that may play audio or video; the script posts what is played to the parent
page, which records what the reader heard ([`annals.listening`](annals.listening.html.md#module-annals.listening)), and takes a “start at”
from it. Opened on its own (no parent), the script does nothing.

### Functions

| [`add_media_relay`](#annals.media.add_media_relay)(html)   | `html` with the media relay injected, unless it plays nothing or opts out.                                          |
|--------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------|
| [`media_version`](#annals.media.media_version)()         | A short hash of what [`add_media_relay()`](#annals.media.add_media_relay) injects, for a page's ETag. |

### annals.media.add_media_relay(html)

`html` with the media relay injected, unless it plays nothing or opts out.

```pycon
>>> add_media_relay(b"<p>no media</p>") == b"<p>no media</p>"
True
>>> b"annalsMedia" in add_media_relay(b"<body><audio src=a.mp3></audio></body>")
True
>>> add_media_relay(b"<p>an audio overview</p>") == b"<p>an audio overview</p>"
True
```

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### annals.media.media_version()

A short hash of what [`add_media_relay()`](#annals.media.add_media_relay) injects, for a page’s ETag.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
