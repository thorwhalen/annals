# A group's documents as separate notebook sources

Decision record, 2026-11-02. Request: the owner wants each markdown file of a group as its own source in a notebook (NotebookLM, which they reach from an iPad), so a studio output (an audio overview, an infographic) can be made from a chosen few. Until now the only path was Combine, which gives one source for the whole group.

## What the notebook accepts (researched 2026-11-02)

- NotebookLM was renamed Gemini Notebook on 2026-07-16, the same product with sources synced to the Gemini app's notebooks [1][2].
- **Website links**: each URL becomes its own source, and several URLs can be pasted at once, separated by spaces or new lines. Google documents this for the web and for the iPhone and iPad app [3][4][5]. Only "the text content of the given HTML webpage" is read; pages that need a login or JavaScript to show their text fail [3][6]. A link is fetched once, so later changes to the page do not reach the notebook [3].
- **Uploads**: PDF, txt, md, docx and others on the web [3]. The iOS app's help page lists fewer types (PDF, website, audio, YouTube, copied text) [4]. Multi-select in the file picker is reported by third parties but not documented by Google [7]. Either way the files must already be on the device.
- **Zip**: not accepted, and nothing unpacks it into sources. The only zip unpacker is a third-party Chrome extension [7].
- **Drive**: Docs, Slides, PDFs, multi-select in the picker, and Docs sync [3]. Getting annals files into Drive would need a Drive connection the server does not have.
- **Pasted text**: one source per paste [3], so N pastes for N documents.

## Decision: one public link per page, copied as one list

The fewest taps from an iPad, counted from the group page: Notebook, Make links, Copy, then in the notebook Add source, Website, paste, Insert. That is seven taps for any number of documents. Each alternative costs more:

| Option | Why not |
|---|---|
| A zip | The notebook does not unpack it [3][7]. |
| Download the files, then upload them | Safari asks once per file, and then the Files picker needs another multi-select whose iOS support is unconfirmed [4][7]. |
| Drive export | Needs OAuth to the owner's Drive on the server: a new credential, for a sync the owner did not ask for. |
| Paste the text of each document | N copy-and-paste rounds. |
| Raw `.md` links (the share's existing `/raw/`) | The notebook is documented to read HTML pages [3], and a markdown URL has no `<title>`, so every source would be named after its URL. That defeats the point, which is picking sources by name. |

So each link is a server-rendered, script-free HTML page (`annals.notebook.source_page`). Its `<title>` is the document's title, and its body is the markdown rendered with `markdown-it-py` (raw html shown as text, never run). If `markdown-it-py` is missing, the escaped text goes in a `<pre>`.

## Privacy

Every link belongs to a share (`annals.share`). A share has 128 random bits, covers only the ticked documents, expires (1 day by default, with 7 or 30 days on offer), can be revoked, and serves only filtered text: a link or id in a page that points outside the share is removed before the page leaves the server. Nothing becomes public until the owner taps Make links. The panel then says who can read the pages and until when, and offers **Turn these links off**. It also says that the notebook keeps its own copy, so turning the links off after the paste is safe. The links carry no password, because the notebook's fetcher cannot type one. Documents that are not pages (images, audio, PDFs) get no link at all.

## Kept

Combine is unchanged. The same panel adds **Combine these**, which makes one Markdown file of the ticked documents only (`GET /groups/<gid>/aggregate?doc=...`). This is what the owner asked of the Share button.

## Not done

- A Drive export, for sources that sync. It would need the owner's Drive credential on the server.
- Adding sources straight into a notebook from the server (`notebooklm-py` can do it), which would mean holding the owner's Google session on the server.

## References

1. Google. NotebookLM is now Gemini Notebook. 2026-07-16. [blog.google](https://blog.google/innovation-and-ai/products/gemini-notebook/notebooklm-gemini-notebook/)
2. Google. Create and use notebooks in Gemini Apps. Retrieved 2026-11-02. [support.google.com](https://support.google.com/gemini/answer/16972047)
3. Google. Add or discover new sources for your notebook. Retrieved 2026-11-02. [support.google.com](https://support.google.com/gemininotebook/answer/16215270?hl=en)
4. Google. Add sources (iPhone & iPad). Retrieved 2026-11-02. [support.google.com](https://support.google.com/gemininotebook/answer/16215270?co=GENIE.Platform%3DiOS&hl=en)
5. XDA. NotebookLM bulk URL feature. 2025-08-05. [xda-developers.com](https://www.xda-developers.com/notebooklm-bulk-url-feature/)
6. Android Authority. Gemini app notebook upgrades (APK teardown). 2026-07-30. [androidauthority.com](https://www.androidauthority.com/gemini-app-notebook-upgrades-apk-teardown-3693047/)
7. nlmtools. How to import sources into NotebookLM. Updated 2026-10-01. [nlmtools.com](https://www.nlmtools.com/blog/notebooklm-tips-3-import-sources)
