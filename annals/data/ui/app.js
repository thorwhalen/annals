/* annals: the page. One file, no build. Routes by path under BASE (window.ANNALS.base):
   BASE/               home: search + sort, newest first
   BASE/d/<id>         one document: markdown (rendered, with a source toggle), html (framed),
                       image, video, audio, pdf (inline), or a folder (gallery + file list)
   BASE/d/<id>?f=<p>   one file of a document, shown by its kind, with prev/next
   BASE/g/<gid>        a group: one URL for a set of documents
   BASE/trash          the recycle bin: restore, or delete forever
   The API lives at window.ANNALS.api (standalone: BASE/api; on enlace: /api/<app>).    */
(function () {
  "use strict";
  var CFG = window.ANNALS || {};
  var BASE = (CFG.base || "/" + (location.pathname.split("/")[1] || "annals")).replace(/\/$/, "");
  var API = (CFG.api || BASE + "/api").replace(/\/$/, "");
  var NAME = CFG.title || "annals";
  var app = document.getElementById("app");
  var toastEl;
  var MEDIA_SLOW_MS = 3000;
  var GALLERY_PAGE = 120;

  /* -------- helpers ------------------------------------------------------------- */
  function h(tag, attrs, children) {
    var el = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === "class") el.className = attrs[k];
      else if (k === "html") el.innerHTML = attrs[k];
      else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] !== null && attrs[k] !== undefined && attrs[k] !== false) el.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) {
      if (c === null || c === undefined) return;
      el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return el;
  }
  function api(path, opts) {
    return fetch(API + path, Object.assign({ credentials: "same-origin" }, opts || {})).then(function (r) {
      if (r.status === 401) { location.href = "/auth/login?login_required=1&next=" + encodeURIComponent(location.pathname + location.search); throw new Error("login"); }
      if (!r.ok) return r.json().catch(function () { return {}; }).then(function (b) { throw new Error(b.detail || r.statusText); });
      return r.json();
    });
  }
  function encPath(rel) { return rel.split("/").map(encodeURIComponent).join("/"); }
  function rawUrl(id, rel) { return API + "/raw/" + id + "/" + encPath(rel); }
  function thumbUrl(id, rel, w) { return API + "/thumb/" + id + "/" + encPath(rel) + "?w=" + w; }
  function fileUrl(id, rel) { return BASE + "/d/" + id + "?f=" + encodeURIComponent(rel); }
  /* Going somewhere is a new history entry; refining the current view replaces it. */
  function go(path, replace) {
    if (path === location.pathname + location.search) return route();
    history[replace ? "replaceState" : "pushState"]({ from: location.pathname + location.search }, "", path);
    route();
  }
  function link(path, text, cls) {
    return h("a", { href: path, class: cls || null, onclick: function (e) { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); go(path); } }, [text]);
  }
  function when(iso) {
    if (!iso) return "";
    var d = new Date(iso), now = new Date(), diff = (now - d) / 1000;
    var hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    if (diff < 60) return "just now";
    if (diff < 3600) return Math.round(diff / 60) + " min ago";
    if (d.toDateString() === now.toDateString()) return "today " + hm;
    var y = new Date(now); y.setDate(now.getDate() - 1);
    if (d.toDateString() === y.toDateString()) return "yesterday " + hm;
    return d.toLocaleDateString([], { month: "short", day: "numeric" }) + (d.getFullYear() !== now.getFullYear() ? " " + d.getFullYear() : "") + " " + hm;
  }
  function size(n) { return n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(0) + " KB" : (n / 1048576).toFixed(1) + " MB"; }
  function toast(msg) {
    if (!toastEl) { toastEl = h("div", { class: "toast" }); document.body.appendChild(toastEl); }
    toastEl.textContent = msg; toastEl.classList.add("show");
    clearTimeout(toastEl._t); toastEl._t = setTimeout(function () { toastEl.classList.remove("show"); }, 1600);
  }
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text).then(function () { toast("Copied"); });
    var ta = h("textarea", null, [text]); document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); toast("Copied"); } finally { ta.remove(); }
    return Promise.resolve();
  }
  function kindBadge(kind) { return h("span", { class: "kind " + kind }, [kind]); }
  function sourceText(src) { return src ? [src.session, src.host].filter(Boolean).join(" @ ") : ""; }
  function basename(rel) { return rel.split("/").pop(); }
  function dirname(rel) { var i = rel.lastIndexOf("/"); return i < 0 ? "" : rel.slice(0, i + 1); }

  /* The markdown renderer loads on first use, from the API like every other asset. */
  var markedReady;
  function withMarked() {
    if (window.marked) return Promise.resolve(window.marked);
    markedReady = markedReady || new Promise(function (ok, ko) {
      var s = h("script", { src: API + "/ui/marked.min.js" });
      s.onload = function () { ok(window.marked); }; s.onerror = function () { ko(new Error("could not load the markdown renderer")); };
      document.head.appendChild(s);
    });
    return markedReady;
  }

  /* -------- media: reserved box, distinct loading / slow / failed states ------------ */
  function mediaBox(kind, src, opts) {
    opts = opts || {};
    var box = h("div", { class: "media " + kind + (opts.cls ? " " + opts.cls : "") + " loading" });
    var status = h("div", { class: "media-status" }, [h("span", { class: "spinner" })]);
    var slowTimer = setTimeout(function () { if (box.classList.contains("loading")) status.lastChild.textContent = "Still loading…"; }, MEDIA_SLOW_MS);
    status.appendChild(h("span", { class: "media-msg" }, [""]));
    function done() { clearTimeout(slowTimer); box.classList.remove("loading"); }
    function fail() {
      clearTimeout(slowTimer); box.classList.remove("loading"); box.classList.add("failed");
      status.innerHTML = "";
      status.appendChild(h("span", { class: "media-msg" }, ["Could not load " + basename(opts.name || src)]));
      status.appendChild(h("button", { class: "btn", onclick: function (e) { e.preventDefault(); e.stopPropagation(); box.replaceWith(mediaBox(kind, src, opts)); } }, ["Retry"]));
    }
    var el;
    if (kind === "image") {
      el = h("img", { src: src, alt: opts.name ? basename(opts.name) : "", loading: opts.lazy ? "lazy" : null, decoding: "async" });
      el.addEventListener("load", done); el.addEventListener("error", fail);
    } else if (kind === "video") {
      el = h("video", { src: src, controls: "", preload: "metadata", playsinline: "" });
      el.addEventListener("loadedmetadata", done); el.addEventListener("error", fail);
    } else if (kind === "audio") {
      el = h("audio", { src: src, controls: "", preload: "metadata" });
      el.addEventListener("loadedmetadata", done); el.addEventListener("error", fail);
    } else if (kind === "pdf") {
      el = h("iframe", { src: src, title: opts.name || "pdf" });
      el.addEventListener("load", done);
    }
    box.appendChild(el); box.appendChild(status);
    return box;
  }

  /* -------- layout -------------------------------------------------------------- */
  function page(title, nav, body) {
    app.innerHTML = "";
    document.title = title ? title + " · " + NAME : NAME;
    var wrap = h("div", { class: "wrap" });
    wrap.appendChild(h("header", { class: "bar" }, [h("div", { class: "row" }, [
      h("h1", { class: "grow" }, [link(BASE + "/", NAME)]),
      h("nav", null, nav || [])
    ])]));
    body.forEach(function (b) { if (b) wrap.appendChild(b); });
    app.appendChild(wrap);
    window.scrollTo(0, 0);
  }
  function thumbFor(m) {
    if (!m.thumb) return null;
    return h("div", { class: "thumb" }, [mediaBox("image", thumbUrl(m.id, m.thumb, 160), { lazy: true, name: m.thumb, cls: "fill" })]);
  }
  function card(m, extra) {
    var href = BASE + "/d/" + m.id;
    var meta = h("div", { class: "meta" }, [
      kindBadge(m.kind),
      h("span", null, [when(m.created)]),
      m.size ? h("span", null, [size(m.size)]) : null,
      m.n_files > 1 ? h("span", null, [m.n_files + " files"]) : null,
      sourceText(m.source) ? h("span", null, [sourceText(m.source)]) : null
    ].concat((m.tags || []).map(function (t) { return h("span", { class: "tag" }, [t]); })));
    var c = h("a", { class: "card" + (m.thumb ? " has-thumb" : ""), href: href, onclick: function (e) { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); go(href); } }, [
      thumbFor(m),
      h("div", { class: "card-body" }, [h("p", { class: "title" }, [m.title || m.id]), meta, m.excerpt ? h("p", { class: "excerpt" }, [m.excerpt]) : null])
    ]);
    return extra ? h("div", null, [c, extra]) : c;
  }
  function groupCard(g) {
    var href = BASE + "/g/" + g.id;
    return h("a", { class: "card", href: href, onclick: function (e) { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); go(href); } }, [
      h("div", { class: "card-body" }, [h("p", { class: "title" }, [g.title || g.id]),
        h("div", { class: "meta" }, [h("span", { class: "kind group" }, ["group"]), h("span", null, [g.docs.length + " documents"]), h("span", null, [when(g.created)])])])
    ]);
  }

  /* -------- sort + search over the loaded list ---------------------------------- */
  var SORTS = {
    newest: { label: "Newest first", fn: function (a, b) { return (b.created || "").localeCompare(a.created || ""); } },
    oldest: { label: "Oldest first", fn: function (a, b) { return (a.created || "").localeCompare(b.created || ""); } },
    title: { label: "Title A–Z", fn: function (a, b) { return (a.title || "").localeCompare(b.title || ""); } },
    kind: { label: "Kind", fn: function (a, b) { return (a.kind || "").localeCompare(b.kind || "") || (b.created || "").localeCompare(a.created || ""); } },
    size: { label: "Largest first", fn: function (a, b) { return (b.size || 0) - (a.size || 0); } }
  };
  function matches(m, q) {
    if (!q) return true;
    var hay = [m.title, (m.tags || []).join(" "), m.excerpt, m.kind, m.id, JSON.stringify(m.source || {})].join(" ").toLowerCase();
    return q.toLowerCase().split(/\s+/).filter(Boolean).every(function (w) { return hay.indexOf(w) >= 0; });
  }
  function readPref(k, d) { try { return localStorage.getItem(NAME + ":" + k) || d; } catch (e) { return d; } }
  function writePref(k, v) { try { localStorage.setItem(NAME + ":" + k, v); } catch (e) { /* private mode */ } }

  function listView(opts) {
    var params = new URLSearchParams(location.search);
    var state = { q: params.get("q") || "", sort: readPref("sort", "newest") };
    var listEl = h("div", { class: "list" });
    var countEl = h("span", { class: "count" });
    var all = [], groups = [];

    function render() {
      listEl.innerHTML = "";
      var rows = all.filter(function (m) { return matches(m, state.q); }).sort(SORTS[state.sort].fn);
      var gs = opts.trash ? [] : groups.filter(function (g) { return !state.q || matches({ title: g.title, id: g.id, kind: "group" }, state.q); });
      countEl.textContent = rows.length + (rows.length === 1 ? " document" : " documents") + (gs.length ? ", " + gs.length + (gs.length === 1 ? " group" : " groups") : "");
      if (!rows.length && !gs.length) {
        listEl.appendChild(opts.trash
          ? h("div", { class: "empty" }, ["The recycle bin is empty."])
          : h("div", { class: "empty" }, [state.q ? "Nothing matches." : "Nothing here yet. An agent publishes with ", state.q ? null : h("code", null, ["annals publish report.md"]), state.q ? null : "."]));
        return;
      }
      if (state.sort === "newest" || state.sort === "oldest") gs.forEach(function (g) { listEl.appendChild(groupCard(g)); });
      rows.forEach(function (m) { listEl.appendChild(opts.trash ? card(m, trashActions(m)) : card(m)); });
    }
    function trashActions(m) {
      return h("div", { class: "toolbar" }, [
        h("button", { class: "btn", onclick: function () { api("/docs/" + m.id + "/restore", { method: "POST" }).then(function () { toast("Restored"); load(); }); } }, ["Restore"]),
        h("button", { class: "btn danger", onclick: function () {
          if (!window.confirm("Delete “" + (m.title || m.id) + "” forever?")) return;
          api("/docs/" + m.id, { method: "DELETE" }).then(function () { toast("Deleted"); load(); });
        } }, ["Delete forever"])
      ]);
    }
    function load() {
      listEl.innerHTML = ""; listEl.appendChild(h("p", { class: "muted" }, ["Loading…"]));
      var reqs = [api("/docs?trash=" + (opts.trash ? "1" : "0"))];
      if (!opts.trash) reqs.push(api("/groups"));
      Promise.all(reqs).then(function (res) {
        all = res[0].docs || []; groups = res[1] ? (res[1].groups || []) : []; render();
      }).catch(function (e) { listEl.innerHTML = ""; listEl.appendChild(h("p", { class: "err" }, [String(e.message || e)])); });
    }
    var search = h("input", { type: "search", placeholder: opts.trash ? "Search the bin" : "Search titles, tags, text", value: state.q, autocomplete: "off",
      oninput: function (e) { state.q = e.target.value; var u = new URL(location.href); if (state.q) u.searchParams.set("q", state.q); else u.searchParams.delete("q"); history.replaceState(history.state, "", u); render(); } });
    var sortSel = h("select", { "aria-label": "Sort", onchange: function (e) { state.sort = e.target.value; writePref("sort", state.sort); render(); } },
      Object.keys(SORTS).map(function (k) { var o = h("option", { value: k }, [SORTS[k].label]); if (k === state.sort) o.selected = true; return o; }));
    page(opts.trash ? "Recycle bin" : "", opts.trash ? [link(BASE + "/", "Documents")] : [link(BASE + "/trash", "Recycle bin")], [
      opts.trash ? h("div", { class: "notice" }, ["Documents here stay until you delete them forever."]) : null,
      h("div", { class: "controls" }, [search, sortSel]),
      h("div", { class: "row", style: "margin-bottom:8px" }, [countEl]),
      listEl
    ]);
    load();
  }

  /* -------- rendering one file by its kind ---------------------------------------- */
  /* Relative links in a markdown document point at its own files: images load from the
     raw endpoint, links to its other pages open them here. */
  function rebase(article, m, fromRel) {
    var dir = dirname(fromRel), files = m.files || [];
    function resolve(u) {
      if (!u || /^([a-z][a-z0-9+.-]*:|\/\/|\/|#)/i.test(u)) return null;
      var parts = (dir + u.split("#")[0].split("?")[0]).split("/"), out = [];
      parts.forEach(function (p) { if (p === "..") out.pop(); else if (p && p !== ".") out.push(p); });
      var rel = decodeURIComponent(out.join("/"));
      return files.indexOf(rel) >= 0 ? rel : null;
    }
    article.querySelectorAll("img[src], video[src], audio[src], source[src]").forEach(function (el) {
      var rel = resolve(el.getAttribute("src")); if (rel) el.setAttribute("src", rawUrl(m.id, rel));
    });
    article.querySelectorAll("a[href]").forEach(function (a) {
      var rel = resolve(a.getAttribute("href")); if (!rel) return;
      var k = (m.file_kinds || {})[rel];
      if (k === "file") { a.setAttribute("href", rawUrl(m.id, rel)); return; }
      var to = fileUrl(m.id, rel); a.setAttribute("href", to);
      a.addEventListener("click", function (e) { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); go(to); });
    });
  }

  function textOf(m, rel) {
    if (rel === m.main && typeof m.text === "string") return Promise.resolve(m.text);
    return fetch(rawUrl(m.id, rel), { credentials: "same-origin" }).then(function (r) { if (!r.ok) throw new Error(r.statusText); return r.text(); });
  }

  /* Renders `rel` of document `m` into a container; returns tools for the toolbar. */
  function renderFile(m, rel, kind, container) {
    var tools = [];
    if (kind === "md") {
      var mode = readPref("mdmode", "rendered"), text = "";
      var seg = h("div", { class: "seg" }, ["rendered", "source"].map(function (v) {
        return h("button", { class: "btn", "aria-pressed": String(mode === v), onclick: function () { mode = v; writePref("mdmode", v); draw(); } }, [v === "rendered" ? "Rendered" : "Source"]);
      }));
      function draw() {
        seg.children[0].setAttribute("aria-pressed", String(mode === "rendered"));
        seg.children[1].setAttribute("aria-pressed", String(mode === "source"));
        container.innerHTML = "";
        if (mode === "source") { container.appendChild(h("pre", { class: "source" }, [text])); return; }
        withMarked().then(function (mk) {
          var art = h("article", { class: "rendered", html: mk.parse(text, { gfm: true, breaks: false }) });
          rebase(art, m, rel); container.innerHTML = ""; container.appendChild(art);
        }).catch(function (e) { container.appendChild(h("p", { class: "err" }, [String(e.message || e)])); });
      }
      container.appendChild(h("p", { class: "muted" }, ["Loading…"]));
      textOf(m, rel).then(function (t) { text = t; draw(); }).catch(function (e) { container.innerHTML = ""; container.appendChild(h("p", { class: "err" }, [String(e.message || e)])); });
      tools.push(seg, h("button", { class: "btn", onclick: function () { copyText(text); } }, ["Copy source"]));
    } else if (kind === "text") {
      var pre = h("pre", { class: "source" }, ["Loading…"]), t2 = "";
      container.appendChild(pre);
      textOf(m, rel).then(function (t) { t2 = t; pre.textContent = t; }).catch(function (e) { pre.textContent = String(e.message || e); });
      tools.push(h("button", { class: "btn", onclick: function () { copyText(t2); } }, ["Copy"]));
    } else if (kind === "html") {
      container.appendChild(h("iframe", { class: "frame", src: rawUrl(m.id, rel), sandbox: "allow-scripts allow-popups allow-forms allow-modals allow-downloads", title: m.title }));
    } else if (kind === "image" || kind === "video" || kind === "audio" || kind === "pdf") {
      container.appendChild(mediaBox(kind, rawUrl(m.id, rel), { name: rel, cls: "full" }));
    } else {
      container.appendChild(h("div", { class: "empty" }, [h("a", { class: "btn primary", href: rawUrl(m.id, rel), download: basename(rel) }, ["Download " + basename(rel)]),
        (m.sizes || {})[rel] ? h("p", { class: "muted" }, [size(m.sizes[rel])]) : null]));
    }
    tools.push(h("a", { class: "btn", href: rawUrl(m.id, rel), target: "_blank", rel: "noopener" }, [kind === "html" ? "Open full page" : "Open raw"]));
    return tools;
  }

  /* -------- the files of a multi-file document: gallery, players, list ------------- */
  function filesPanel(m, opts) {
    var kinds = m.file_kinds || {}, sizes = m.sizes || {};
    var files = (m.files || []).filter(function (f) { return !(opts && opts.skip === f); });
    var images = files.filter(function (f) { return kinds[f] === "image"; });
    var videos = files.filter(function (f) { return kinds[f] === "video"; });
    var audios = files.filter(function (f) { return kinds[f] === "audio"; });
    var others = files.filter(function (f) { return ["image", "video", "audio"].indexOf(kinds[f]) < 0; });
    var out = h("div", { class: "files" });
    if (images.length) {
      /* a folder of renders can hold thousands: thumbnails, a page at a time */
      var grid = h("div", { class: "gallery" }), shown = 0;
      var more = h("button", { class: "btn more", onclick: function () { addTiles(); } }, [""]);
      function addTiles() {
        images.slice(shown, shown + GALLERY_PAGE).forEach(function (f) {
          var to = fileUrl(m.id, f);
          grid.appendChild(h("a", { class: "tile", href: to, title: f, onclick: function (e) { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); go(to); } },
            [mediaBox("image", thumbUrl(m.id, f, 320), { lazy: true, name: f, cls: "fill" }), h("span", { class: "tile-name" }, [basename(f)])]));
        });
        shown = Math.min(images.length, shown + GALLERY_PAGE);
        more.textContent = "Show " + Math.min(GALLERY_PAGE, images.length - shown) + " more of " + (images.length - shown);
        more.style.display = shown < images.length ? "" : "none";
      }
      addTiles();
      out.appendChild(h("section", null, [h("h3", null, [images.length + (images.length === 1 ? " image" : " images")]), grid, more]));
    }
    if (videos.length) out.appendChild(h("section", null, [h("h3", null, [videos.length + (videos.length === 1 ? " video" : " videos")])].concat(videos.map(function (f) {
      return h("figure", { class: "player" }, [mediaBox("video", rawUrl(m.id, f), { name: f }), h("figcaption", null, [link(fileUrl(m.id, f), f), sizes[f] ? " · " + size(sizes[f]) : ""])]);
    }))));
    if (audios.length) out.appendChild(h("section", null, [h("h3", null, [audios.length + " audio"])].concat(audios.map(function (f) {
      return h("figure", { class: "player audio-row" }, [h("figcaption", null, [link(fileUrl(m.id, f), basename(f)), sizes[f] ? " · " + size(sizes[f]) : ""]), mediaBox("audio", rawUrl(m.id, f), { name: f })]);
    }))));
    if (others.length) out.appendChild(h("section", null, [h("h3", null, [others.length + (others.length === 1 ? " other file" : " other files")]),
      h("ul", { class: "filelist" }, others.map(function (f) {
        return h("li", null, [kindBadge(kinds[f] || "file"), " ", kinds[f] === "file" ? h("a", { href: rawUrl(m.id, f), download: basename(f) }, [f]) : link(fileUrl(m.id, f), f),
          sizes[f] ? h("span", { class: "muted" }, [" " + size(sizes[f])]) : null]);
      }))]));
    return out;
  }

  /* -------- one document, or one file of it --------------------------------------- */
  function docView(id, rel) {
    page("Document", [link(BASE + "/", "Documents")], [h("p", { class: "muted" }, ["Loading…"])]);
    api("/docs/" + id).then(function (m) {
      var kinds = m.file_kinds || {};
      if (rel && (m.files || []).indexOf(rel) < 0) rel = null;
      var showRel = rel || (m.kind === "folder" ? null : m.main);
      var body = h("div", { class: "doc-body" });
      var tools = [];
      if (showRel) tools = renderFile(m, showRel, rel ? kinds[rel] : m.kind, body);

      var fileNav = null;
      if (rel) {  /* prev / next inside an open viewer replace the entry; Back returns to the document */
        /* step through files of the same kind (images among images), as the gallery shows them */
        var k = kinds[rel], same = m.files.filter(function (f) { return kinds[f] === k; });
        var files = ["image", "video", "audio", "pdf"].indexOf(k) >= 0 ? same : m.files, i = files.indexOf(rel);
        var prev = files[i - 1], next = files[i + 1];
        fileNav = h("div", { class: "toolbar filenav" }, [
          link(BASE + "/d/" + m.id, "← " + (m.title || "Document"), "btn"),
          h("span", { class: "grow muted" }, [(i + 1) + " / " + files.length + " · " + rel]),
          h("button", { class: "btn", disabled: prev ? null : "", onclick: function () { go(fileUrl(m.id, prev), true); } }, ["Prev"]),
          h("button", { class: "btn", disabled: next ? null : "", onclick: function () { go(fileUrl(m.id, next), true); } }, ["Next"])
        ]);
      }
      var docTools = h("div", { class: "toolbar" }, tools.concat([
        h("button", { class: "btn", onclick: function () { copyText(location.href); } }, ["Copy link"]),
        rel ? null : (m.in_trash
          ? h("button", { class: "btn", onclick: function () { api("/docs/" + m.id + "/restore", { method: "POST" }).then(function () { toast("Restored"); docView(m.id); }); } }, ["Restore"])
          : h("button", { class: "btn danger", onclick: function () { api("/docs/" + m.id + "/trash", { method: "POST" }).then(function () { toast("Moved to the bin"); go(BASE + "/"); }); } }, ["Move to bin"]))
      ]));
      var meta = h("div", { class: "meta" }, [
        kindBadge(m.kind), h("span", null, [when(m.created)]), m.size ? h("span", null, [size(m.size)]) : null,
        sourceText(m.source) ? h("span", null, [sourceText(m.source)]) : null,
        m.files && m.files.length > 1 ? h("span", null, [m.files.length + " files"]) : null
      ].concat((m.tags || []).map(function (t) { return link(BASE + "/?q=" + encodeURIComponent(t), t, "tag"); })));
      var showFiles = !rel && m.files && m.files.length > 1;
      page(rel ? basename(rel) : m.title, [link(BASE + "/", "Documents"), link(BASE + "/trash", "Bin")], [
        m.in_trash ? h("div", { class: "notice" }, ["This document is in the recycle bin."]) : null,
        h("div", { class: "doc-head" }, [h("h2", null, [m.title || m.id]), meta]),
        fileNav, docTools, body,
        showFiles ? (m.kind === "folder" ? filesPanel(m) : h("details", { class: "more-files", open: (m.files || []).some(function (f) { return f !== m.main && ["image", "video", "audio"].indexOf(kinds[f]) >= 0; }) ? "" : null }, [h("summary", null, ["All " + m.files.length + " files"]), filesPanel(m, { skip: m.main })])) : null
      ]);
    }).catch(function (e) { page("Not found", [link(BASE + "/", "Documents")], [h("div", { class: "empty" }, [String(e.message || e)])]); });
  }

  /* -------- a group ----------------------------------------------------------------- */
  function groupView(gid) {
    page("Group", [link(BASE + "/", "Documents")], [h("p", { class: "muted" }, ["Loading…"])]);
    api("/groups/" + gid).then(function (g) {
      var items = (g.items || []).filter(function (m) { return !m.in_trash; });
      page(g.title, [link(BASE + "/", "Documents")], [
        h("div", { class: "doc-head" }, [h("h2", null, [g.title || g.id]), h("div", { class: "meta" }, [h("span", { class: "kind group" }, ["group"]), h("span", null, [items.length + " documents"]), h("span", null, [when(g.created)])])]),
        h("div", { class: "toolbar" }, [h("button", { class: "btn", onclick: function () { copyText(location.href); } }, ["Copy link"])]),
        h("div", { class: "list" }, items.length ? items.map(function (m) { return card(m); }) : [h("div", { class: "empty" }, ["This group has no documents (they may be in the bin)."])])
      ]);
    }).catch(function (e) { page("Not found", [link(BASE + "/", "Documents")], [h("div", { class: "empty" }, [String(e.message || e)])]); });
  }

  /* -------- router ------------------------------------------------------------------ */
  function route() {
    var path = location.pathname.indexOf(BASE) === 0 ? location.pathname.slice(BASE.length) : location.pathname;
    var parts = path.split("/").filter(Boolean).map(decodeURIComponent); // ["d", id]
    var kind = parts[0], arg = parts[1];
    if (kind === "d" && arg) return docView(arg, new URLSearchParams(location.search).get("f"));
    if (kind === "g" && arg) return groupView(arg);
    if (kind === "trash") return listView({ trash: true });
    return listView({ trash: false });
  }
  window.addEventListener("popstate", route);
  route();
})();
