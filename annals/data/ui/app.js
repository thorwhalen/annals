/* annals: the page. One file, no build. Routes by path under BASE (window.ANNALS.base):
   BASE/               the published documents: full-text search, facets, sort, newest first
   BASE/s/<source>     the same list over another source (BASE/s/ledgers: the crowsnest ledgers)
   BASE/all            every source at once
   BASE/i/<source>/<p> one file of a folder source (a ledger), rendered by its kind
   BASE/d/<id>         one document: markdown (rendered, with a source toggle), html (framed),
                       image, video, audio, pdf (inline), or a folder (gallery + file list)
   BASE/d/<id>?f=<p>   one file of a document, shown by its kind, with prev/next
   BASE/g/<gid>        a group: one URL for a set of documents
   BASE/trash          the recycle bin: restore, or delete forever
   BASE/shares         the links the owner made ("Links"): copy, or revoke
   BASE/audio          every spoken overview, searchable, by what you have heard of it
                       (not started, in progress, done); progress is kept per reader on the
                       server (annals.listening), so it follows you to every device
   Acting on documents is one model on a group and on a document: pick documents (a group's
   ticked cards, all of them when none is ticked; a document page is a pick of one), then
   one of three results, each in one sheet: Links (one link for a person, with expiry and
   password, or a link per document for a notebook; annals.share,
   annals.notebook), One file (the files as one Markdown, PDF or web page; annals.combine) and Listen (a
   spoken review of one, of all together, or one each; annals.overview). Actions that need
   no choosing are under More. The same file is the recipient's page: the share server sets
   window.ANNALS.share, BASE and API to the link, and the page then shows only what the
   share includes, without the owner's controls (its group keeps One file).
   The API lives at window.ANNALS.api (standalone: BASE/api; on enlace: /api/<app>). Items
   (every source's rows, and their tags) are read and patched through @zodal/store-http's
   provider, vendored at API/ui/vendor/, so the storage behind them can change without
   touching this page. Filters live in the URL: ?q=words&kind=md&session=a&date=7d&tag=x.  */
(function () {
  "use strict";
  var CFG = window.ANNALS || {};
  var BASE = (CFG.base || "/" + (location.pathname.split("/")[1] || "annals")).replace(/\/$/, "");
  var API = (CFG.api || BASE + "/api").replace(/\/$/, "");
  /* A document's frame: the same flags as the server's RAW_SANDBOX_FLAGS (annals/api.py; a
     test holds them equal). Escaping popups is what lets a link open a site that refuses
     sandboxed tabs (claude.ai). */
  var FRAME_SANDBOX = "allow-scripts allow-popups allow-popups-to-escape-sandbox allow-top-navigation-by-user-activation allow-forms allow-modals allow-downloads";
  var NAME = CFG.title || "annals";
  var SHARE = CFG.share || null;   /* set when this page is a share link's, for a recipient */
  var UI = (CFG.ui || API + "/ui").replace(/\/$/, "");
  var app = document.getElementById("app");
  var toastEl;
  var MEDIA_SLOW_MS = 3000;
  var GALLERY_PAGE = 120;
  var LIST_PAGE = 60;
  var SEARCH_DEBOUNCE_MS = 300;
  var LIST_REUSE_MS = 60000;   /* Back to a list re-filters what was loaded, no refetch */
  var FACET_SHOWN = 8;         /* values shown before "Show all" */
  var FACET_FILTER_AT = 12;    /* a family this long gets a type-ahead box */

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
      if (r.status === 401) { if (SHARE) location.reload(); else toLogin(); throw new Error("login"); }
      if (!r.ok) return r.json().catch(function () { return {}; }).then(function (b) { throw new Error(b.detail || r.statusText); });
      return r.json();
    });
  }
  function toLogin() { location.href = "/auth/login?login_required=1&next=" + encodeURIComponent(location.pathname + location.search); }
  function encPath(rel) { return rel.split("/").map(encodeURIComponent).join("/"); }
  function rawUrl(id, rel) { return API + "/raw/" + id + "/" + encPath(rel); }
  /* A markdown document as a download made by the server (annals.export): the same access
     as the page, the same filtered text on a share link. `base` lets the PDF link its media. */
  function exportUrl(id, fmt, file) {
    return API + "/export/" + id + "?format=" + fmt + (file ? "&file=" + encodeURIComponent(file) : "") + "&base=" + encodeURIComponent(new URL(API, location.href).href.replace(/\/$/, ""));
  }
  function filesUrl(source, rel) { return API + "/files/" + encodeURIComponent(source) + "/" + encPath(rel); }
  function itemHref(r) { return r.source === "published" ? BASE + "/d/" + r.id : BASE + "/i/" + encodeURIComponent(r.source) + "/" + encPath(r.id); }
  function scopeHref(scope) { return scope === "published" ? BASE + "/" : scope === "all" ? BASE + "/all" : BASE + "/s/" + encodeURIComponent(scope); }
  function thumbUrl(id, rel, w) { return API + "/thumb/" + id + "/" + encPath(rel) + "?w=" + w; }
  /* The same file as a download: the server answers with Content-Disposition: attachment,
     so it saves even where a viewer (a phone's PDF frame, a video tag) would show it. */
  function downloadUrl(url) { return url + (url.indexOf("?") < 0 ? "?" : "&") + "download=1"; }
  function downloadLink(url, name, cls) { return h("a", { class: cls || "btn", href: downloadUrl(url), download: basename(name) }, ["Download"]); }
  function fileUrl(id, rel) { return BASE + "/d/" + id + "?f=" + encodeURIComponent(rel); }
  /* Going somewhere is a new history entry; refining the current view replaces it.
     Each entry remembers the view it was reached from (`from`, and `fromLabel` to name it)
     so the page can offer its own Back: a home-screen app or a tab opened from a link has
     no browser Back button. A replaced entry keeps the origin of the one it replaces. */
  var viewLabel = "";
  function go(path, replace) {
    if (path === location.pathname + location.search) return route();
    /* Back to a list returns to the same place in it: remember the scroll and how many
       rows were shown on the entry being left */
    var st = history.state || {};
    if (!replace) history.replaceState(Object.assign({}, st, { scrollY: window.scrollY, shown: listShown }), "");
    var origin = replace ? { from: st.from, fromLabel: st.fromLabel } : { from: location.pathname + location.search, fromLabel: typeof viewLabel === "function" ? viewLabel() : viewLabel };
    history[replace ? "replaceState" : "pushState"](origin, "", path);
    route();
  }
  /* A link up to `path` that steps back when `path` is the entry underneath, so that page's
     own Back still leads where it led before (a file viewer up to its document). */
  function upTo(path, text, cls) {
    return h("a", { href: path, class: cls || null, onclick: function (e) {
      if (e.metaKey || e.ctrlKey) return;
      e.preventDefault();
      if ((history.state || {}).from === path) history.back(); else go(path);
    } }, [text]);
  }
  /* "‹ <where you were>": the previous view exactly as it was left (its filters, search and
     scroll), through history.back(); reached from outside annals (a pasted link), the
     view's parent instead. */
  function backLink(parentHref, parentLabel) {
    var st = history.state || {}, inApp = !!st.from;
    var href = inApp ? st.from : parentHref, label = (inApp ? st.fromLabel : parentLabel) || "Back";
    return h("nav", { class: "back", "aria-label": "Back" }, [h("a", { href: href, onclick: function (e) {
      if (e.metaKey || e.ctrlKey) return;
      e.preventDefault();
      if (inApp) history.back(); else go(href);
    } }, ["‹ " + label])]);
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
  /* How old something is, in the largest unit that fits: "5 min ago", "3 d ago". */
  function age(iso) {
    if (!iso) return "";
    var s = (Date.now() - new Date(iso)) / 1000;
    if (s < 60) return "just now";
    var units = [[60, "min"], [3600, "h"], [86400, "d"], [604800, "wk"], [2629800, "mo"], [31557600, "y"]], u = units[0];
    units.forEach(function (x) { if (s >= x[0]) u = x; });
    return Math.floor(s / u[0]) + " " + u[1] + " ago";
  }
  function ageEl(iso) { return h("span", { class: "age", title: when(iso) }, [age(iso)]); }
  function size(n) { return n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(0) + " KB" : (n / 1048576).toFixed(1) + " MB"; }
  function toast(msg, ms) {
    if (!toastEl) { toastEl = h("div", { class: "toast", role: "status" }); document.body.appendChild(toastEl); }
    toastEl.textContent = msg; toastEl.classList.add("show");
    clearTimeout(toastEl._t); toastEl._t = setTimeout(function () { toastEl.classList.remove("show"); }, ms || 1600);
  }
  /* The old way to copy: select a hidden textarea and ask the browser to copy it. An
     editable one at 16px, because iOS Safari selects nothing in a read-only one and
     zooms on a smaller font; inputmode none keeps its keyboard down. */
  function copyByCommand(text) {
    var ta = h("textarea", { class: "copy-buffer", inputmode: "none", "aria-hidden": "true", tabindex: "-1" }, [text]);
    document.body.appendChild(ta);
    var ok = false;
    try { ta.focus(); ta.select(); ta.setSelectionRange(0, text.length); ok = document.execCommand("copy"); } catch (e) { ok = false; }
    ta.remove();
    return ok;
  }
  /* Selects all of a field's text so the device's own Copy can take it. iOS selects nothing
     in a read-only field, so the flag is lifted until the field loses focus (inputmode none
     keeps the keyboard down). True only when something really is selected. */
  function selectAll(el) {
    if (el.readOnly) {
      var mode = el.getAttribute("inputmode");
      el.readOnly = false; el.setAttribute("inputmode", "none");
      el.addEventListener("blur", function () { el.readOnly = true; if (mode === null) el.removeAttribute("inputmode"); else el.setAttribute("inputmode", mode); }, { once: true });
    }
    try { el.focus(); el.select(); el.setSelectionRange(0, el.value.length); } catch (e) { return false; }
    return el.selectionEnd - el.selectionStart > 0;
  }
  /* Copies inside the tap that asked for it (iOS Safari refuses a clipboard write that
     waited on the network, so the text must already be here): the clipboard API, else
     the old way. When both fail, `selectEl` (a textarea on the page holding the same
     text) is selected, so the device's own Copy finishes the job. */
  /* Resolves to how it went: "copied", "selected" (the device's Copy must finish it) or
     "failed"; says so in a toast unless `opts.quiet` (the copy button answers on itself). */
  var COPY_SAYS = { copied: "Copied", selected: "Selected: use Copy from your device's menu", failed: "Could not copy" };
  function copyText(text, selectEl, opts) {
    var quiet = opts && opts.quiet;
    function done(how) { if (!quiet) toast(COPY_SAYS[how], how === "copied" ? 1600 : 4000); return how; }
    function byHand() {
      if (copyByCommand(text)) return done("copied");
      var el = typeof selectEl === "function" ? selectEl() : selectEl;
      return done(el && selectAll(el) ? "selected" : "failed");
    }
    if (navigator.clipboard && navigator.clipboard.writeText && window.isSecureContext !== false) {
      return navigator.clipboard.writeText(text).then(function () { return done("copied"); }, byHand);
    }
    return Promise.resolve(byHand());
  }

  /* -------- the copy control: one button for every value worth copying -------------- */
  /* A link, a list of links, a password, a code block, combined text: each gets the same
     control. It copies inside the tap (see copyText) and answers on itself (tw-frontend-ux
     principle 1): pressed at once, then a check and "Copied" for COPIED_MS, announced to
     screen readers, a short buzz where the device has one. When the device refuses, the
     value's own field is selected so the device's Copy finishes it, and the button says
     "Selected". Icon-only beside a value that is shown (`name` is its accessible label);
     with `label` where the value is not on screen. Waiting to move to @zodal/ui-vanilla as
     the renderer of zodal's `copyable` affordance. */
  var COPIED_MS = 1600, HAPTIC_MS = 12, srStatus;
  function announce(msg) {
    if (!srStatus) { srStatus = h("div", { class: "sr-only", role: "status", "aria-live": "polite" }); document.body.appendChild(srStatus); }
    srStatus.textContent = ""; setTimeout(function () { srStatus.textContent = msg; }, 30);
  }
  /* copyButton(text | () => text, {name, label, primary, field: el | () => el, cls}) */
  function copyButton(text, opts) {
    opts = opts || {};
    var name = opts.name || "Copy", ico = icon("copy"), timer;
    var lbl = opts.label ? h("span", { class: "lbl" }, [opts.label]) : null;
    var btn = h("button", { type: "button", class: "btn copy-btn " + (lbl ? "with-label" : "icon-only") + (opts.primary ? " primary" : "") + (opts.cls ? " " + opts.cls : ""),
      "aria-label": lbl ? null : name, title: name, "data-state": "idle" }, [ico, lbl]);
    function set(state) {
      clearTimeout(timer);
      btn.setAttribute("data-state", state);
      ico.innerHTML = svgPath(state === "copied" ? "check" : "copy");
      var said = state === "copied" ? "Copied" : state === "selected" ? "Selected" : null;
      if (lbl) lbl.textContent = said || opts.label; else btn.setAttribute("aria-label", said || name);
      if (state !== "idle") timer = setTimeout(function () { set("idle"); }, state === "copied" ? COPIED_MS : 2 * COPIED_MS);
    }
    btn.addEventListener("click", function () {
      var value = typeof text === "function" ? text() : text;
      if (value === null || value === undefined || value === "") return toast("Nothing to copy yet");
      return copyText(String(value), opts.field, { quiet: true }).then(function (how) {
        set(how);
        if (how === "copied") {
          announce(opts.copied || "Copied");
          try { if (navigator.vibrate) navigator.vibrate(HAPTIC_MS); } catch (e) { /* no buzz: the button already said it */ }
        } else toast(COPY_SAYS[how], 4000);
      });
    });
    return btn;
  }
  /* A value shown in full, selectable by hand, with its copy button beside it. */
  /* copyField(value, {name: what the field holds, copyName: the button's label, copied}) */
  function copyField(value, opts) {
    opts = opts || {};
    var field = h("input", { type: "text", readonly: "", value: value, class: "copy-value", spellcheck: "false", autocomplete: "off",
      "aria-label": opts.name || "Value", onfocus: function (e) { e.target.select(); } });
    return h("div", { class: "copy-field" + (opts.cls ? " " + opts.cls : "") }, [field, copyButton(value, { name: opts.copyName || "Copy", field: field, copied: opts.copied })]);
  }
  /* Every code block in `root` (a rendered page, a source view) gets a copy button. */
  function withCodeCopy(root) {
    [].forEach.call(root.querySelectorAll("pre"), function (pre) {
      var up = pre.parentElement;
      if (!up || up.classList.contains("code-wrap") || up.closest("pre")) return;
      /* a whole document in one block (the source view): the button stays in sight as it scrolls */
      var whole = pre.classList.contains("source");
      var wrap = h("div", { class: "code-wrap" + (whole ? " whole" : "") });
      up.insertBefore(wrap, pre);
      var btn = copyButton(function () { return pre.getAttribute("data-loading") === null ? pre.textContent : ""; }, { name: whole ? "Copy all the text" : "Copy code", cls: "code-copy" });
      if (whole) { wrap.appendChild(btn); wrap.appendChild(pre); } else { wrap.appendChild(pre); wrap.appendChild(btn); }
    });
    return root;
  }
  /* Pressed at once, on every button and menu row (principle 1): the state is set on
     pointerdown, before any work, and cleared when the finger lifts or slides off. */
  var PRESSABLE = "button, .btn, .menuitem, [role=menuitem]";
  function unpress() { [].forEach.call(document.querySelectorAll("[data-pressed]"), function (el) { el.removeAttribute("data-pressed"); }); }
  document.addEventListener("pointerdown", function (e) {
    var el = e.target.closest && e.target.closest(PRESSABLE);
    if (el && el.getAttribute("aria-disabled") !== "true" && !el.disabled) el.setAttribute("data-pressed", "");
  }, true);
  ["pointerup", "pointercancel", "lostpointercapture", "dragstart", "visibilitychange"].forEach(function (t) { document.addEventListener(t, unpress, true); });
  window.addEventListener("pageshow", unpress);
  window.addEventListener("blur", unpress);
  function kindBadge(kind) { return h("span", { class: "kind " + kind }, [kind]); }
  function sourceText(src) { return src ? [src.session, src.host].filter(Boolean).join(" @ ") : ""; }
  function basename(rel) { return rel.split("/").pop(); }
  function dirname(rel) { var i = rel.lastIndexOf("/"); return i < 0 ? "" : rel.slice(0, i + 1); }

  /* The markdown renderer and its sanitizer load on first use, from the API. Markdown may
     carry raw html, and this page shares its origin with every app on the host, so the
     rendered html always passes through DOMPurify before it touches the page. */
  var markedReady;
  function loadScript(name) {
    return new Promise(function (ok, ko) {
      var s = h("script", { src: UI + "/" + name });
      s.onload = ok; s.onerror = function () { ko(new Error("could not load " + name)); };
      document.head.appendChild(s);
    });
  }
  function withMarked() {
    if (window.marked && window.DOMPurify && window.annalsTables) return Promise.resolve(window.marked);
    markedReady = markedReady || Promise.all([loadScript("marked.min.js"), loadScript("purify.min.js"), loadScript("tables.js")]).then(function () { return window.marked; });
    return markedReady;
  }
  /* Items go through @zodal/store-http's provider (GET /items?q=, GET and PATCH /items/<key>):
     the one place this page knows how items are stored. */
  var storeHttpReady;
  function itemsProvider(opts) {
    opts = opts || {};
    storeHttpReady = storeHttpReady || (window.ZodalStoreHttp ? Promise.resolve() : loadScript("vendor/zodal-store-http.min.js"));
    return storeHttpReady.then(function () {
      return window.ZodalStoreHttp.createHttpProvider({
        baseUrl: API + "/items",
        idField: "key",
        init: { credentials: "same-origin" },
        capabilities: { serverSearch: true },
        toQuery: function (p) {
          var q = new URLSearchParams();
          if (p.search) q.set("q", p.search);
          if (opts.source) q.set("source", opts.source);
          if (opts.trash) q.set("trash", "1");
          return q;
        }
      });
    });
  }
  function viaStore(promise) {
    return promise.catch(function (e) {
      if (e && e.status === 401) { toLogin(); throw new Error("login"); }
      if (e && e.status === 404) throw new Error("Not found");
      if (e && e.status === 422) throw new Error("Refused: " + (String(e.message).split(": ").pop() || "invalid"));
      throw e;
    });
  }
  /* The sources, for the navigation: published first, then folders read in place. */
  var sourcesReady;
  function sources() {
    sourcesReady = sourcesReady || api("/sources").then(function (b) { return b.sources || []; }).catch(function () { sourcesReady = null; return [{ name: "published", title: "Published" }]; });
    return sourcesReady;
  }
  var knownSources = [{ name: "published", title: "Published" }];
  function sourceTitle(name) { var s = knownSources.filter(function (x) { return x.name === name; })[0]; return s ? s.title : name; }

  function safeHtml(html) { return window.DOMPurify.sanitize(html, { ADD_ATTR: ["target"], FORBID_TAGS: ["style", "form", "input", "button", "textarea", "select"], FORBID_ATTR: ["style"] }); }
  function decode(s) { try { return decodeURIComponent(s); } catch (e) { return s; } }

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
      el = h("video", { src: src, controls: "", preload: opts.preload || "metadata", playsinline: "" });
      el.addEventListener("loadedmetadata", done); el.addEventListener("error", fail);
      if (opts.preload === "none") done();  /* nothing is fetched until pressed: nothing to wait for */
    } else if (kind === "audio") {
      el = h("audio", { src: src, controls: "", preload: opts.preload || "metadata" });
      el.addEventListener("loadedmetadata", done); el.addEventListener("error", fail);
      if (opts.preload === "none") done();  /* nothing is fetched until pressed: nothing to wait for */
    } else if (kind === "pdf") {
      el = h("iframe", { src: src, title: opts.name || "pdf" });
      el.addEventListener("load", done);
    }
    box.appendChild(el); box.appendChild(status);
    return box;
  }

  /* -------- layout -------------------------------------------------------------- */
  function page(title, nav, body) {
    dropSheet();
    stopListening();
    app.innerHTML = ""; listShown = 0;
    document.title = title ? title + " · " + NAME : NAME;
    viewLabel = title || NAME;
    var wrap = h("div", { class: "wrap" });
    wrap.appendChild(h("header", { class: "bar" }, [h("div", { class: "row" }, [
      h("h1", { class: "grow" }, [link(BASE + "/", NAME)]),
      h("nav", null, nav || [])
    ])]));
    body.forEach(function (b) { if (b) wrap.appendChild(b); });
    app.appendChild(wrap);
    window.scrollTo(0, 0);
  }
  /* One link per source, then everything at once, then the bin; the current one marked. */
  function mainNav(current) {
    if (SHARE) return [];
    var items = knownSources.map(function (s) { return [scopeHref(s.name), s.title, s.name]; });
    if (knownSources.length > 1) items.push([BASE + "/all", "All", "all"]);
    items.push([BASE + "/audio", "Audio", "audio"]);
    items.push([BASE + "/shares", "Links", "shares"]);
    items.push([BASE + "/trash", "Bin", "trash"]);
    return items.map(function (x) { var a = link(x[0], x[1]); if (x[2] === current) a.setAttribute("aria-current", "page"); return a; });
  }
  function thumbFor(m) {
    if (!m.thumb) return null;
    return h("div", { class: "thumb" }, [mediaBox("image", thumbUrl(m.id, m.thumb, 160), { lazy: true, name: m.thumb, cls: "fill" })]);
  }
  function card(m, extra, opts) {
    opts = opts || {};
    var isRow = typeof m.source === "string";  /* an /items row, or a /docs meta */
    var href = isRow ? itemHref(m) : BASE + "/d/" + m.id;
    var t = m.time || m.created;
    var meta = h("div", { class: "meta" }, [
      opts.showSource && isRow ? h("span", { class: "src" }, [sourceTitle(m.source)]) : null,
      kindBadge(m.kind),
      t ? ageEl(t) : null,
      m.updated ? h("span", { class: "updated" }, ["updated"]) : null,
      (isRow ? sourceText({ session: m.session, host: m.host }) : sourceText(m.source)) ? h("span", null, [isRow ? sourceText({ session: m.session, host: m.host }) : sourceText(m.source)]) : null,
      m.size ? h("span", null, [size(m.size)]) : null,
      m.n_files > 1 ? h("span", null, [m.n_files + " files"]) : null,
      m.listen && m.listen.state === "done" ? h("span", { class: "tag review" }, [m.listen.stale ? "review (older)" : "▶ review"]) : null
    ].concat((m.tags || []).map(function (t) { return h("span", { class: "tag" }, [t]); })));
    var text = m.snippet || m.excerpt;
    var c = h("a", { class: "card" + (m.thumb ? " has-thumb" : ""), href: href, onclick: function (e) { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); go(href); } }, [
      thumbFor(m),
      h("div", { class: "card-body" }, [h("p", { class: "title" }, [m.title || m.id]), meta, text ? h("p", { class: "excerpt" + (m.snippet ? " snippet" : "") }, [text]) : null])
    ]);
    return extra ? h("div", null, [c, extra]) : c;
  }
  /* A group's entry: audio, video and images play or show in place (nothing is fetched until
     pressed, for media with preload "none"), so options can be compared without a view each;
     other kinds keep their card. */
  var INLINE_KINDS = ["audio", "video", "image"], INLINE_IMAGE_W = 960;
  function inlineItem(m) {
    if (INLINE_KINDS.indexOf(m.kind) < 0 || !m.main) return card(m);
    return h("div", { class: "card inline-item" }, [
      h("p", { class: "title" }, [link(BASE + "/d/" + m.id, m.title || m.id)]),
      mediaBox(m.kind, m.kind === "image" ? thumbUrl(m.id, m.main, INLINE_IMAGE_W) : rawUrl(m.id, m.main), { name: m.main, preload: "none", lazy: true })
    ]);
  }
  /* `time`: the date it is listed by (its newest member's, see byDate), shown so its place makes sense */
  function groupCard(g, time) {
    var href = BASE + "/g/" + g.id;
    return h("a", { class: "card", href: href, onclick: function (e) { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); go(href); } }, [
      h("div", { class: "card-body" }, [h("p", { class: "title" }, [g.title || g.id]),
        h("div", { class: "meta" }, [h("span", { class: "kind group" }, ["group"]), h("span", null, [g.docs.length + " documents"]), h("span", { title: when(time || g.created) }, [age(time || g.created)])])])
    ]);
  }
  /* Documents and groups as one list by date. A group dates from its newest member, or from
     its own creation or last addition when that is later, so it rises when something is added to it, and a
     new document is never pushed below the groups (they once all came first, whatever their
     dates). `all` is every loaded row, so a member that a search hides still dates its group. */
  function byDate(docs, groups, all, newestFirst) {
    var t = {};
    all.forEach(function (r) { t[r.id] = r.time || ""; });
    var entries = docs.map(function (r) { return { time: r.time || "", doc: r }; }).concat(groups.map(function (g) {
      var own = (g.updated || "") > (g.created || "") ? g.updated : g.created || "";
      var latest = (g.docs || []).reduce(function (m, id) { return t[id] && t[id] > m ? t[id] : m; }, own);
      return { time: latest, group: g };
    }));
    return entries.sort(function (a, b) { return newestFirst ? b.time.localeCompare(a.time) : a.time.localeCompare(b.time); });
  }

  /* -------- facets: OR within a family, AND across families ------------------------ */
  /* Counted here over the rows the search returned, so every toggle is instant and each
     count is what adding that value would give (a family's own selection is left out of
     its counts). zodal-groups' facetPanel has these semantics but was too slow for ~600
     items x ~500 sessions on a phone; see the annals ledger for the issue filed. */
  var DATES = [
    { v: "today", label: "Today", test: function (d, now) { return d.toDateString() === now.toDateString(); } },
    { v: "7d", label: "Past 7 days", test: function (d, now) { return now - d < 7 * 864e5; } },
    { v: "30d", label: "Past 30 days", test: function (d, now) { return now - d < 30 * 864e5; } },
    { v: "older", label: "Older", test: function (d, now) { return now - d >= 30 * 864e5; } }
  ];
  function dateValues(iso) {
    if (!iso) return [];
    var d = new Date(iso), now = new Date();
    return DATES.filter(function (x) { return x.test(d, now); }).map(function (x) { return x.v; });
  }
  var FAMILIES = [
    { key: "source", label: "Source", of: function (r) { return [r.source]; }, name: sourceTitle, allOnly: true },
    { key: "kind", label: "Kind", of: function (r) { return r.kind ? [r.kind] : []; } },
    { key: "session", label: "Session", of: function (r) { return r.session ? [r.session] : []; } },
    { key: "date", label: "Date", of: function (r) { return dateValues(r.time); }, order: DATES.map(function (x) { return x.v; }),
      name: function (v) { var d = DATES.filter(function (x) { return x.v === v; })[0]; return d ? d.label : v; } },
    { key: "tag", label: "Tag", of: function (r) { return r.tags || []; } }
  ];
  function famName(f, v) { return f.name ? f.name(v) : v; }
  function inFamily(r, f, chosen) {
    if (!chosen || !chosen.length) return true;
    var vals = f.of(r);
    return chosen.some(function (c) { return vals.indexOf(c) >= 0; });
  }
  function facetCounts(rows, fams, sel) {
    var out = {};
    fams.forEach(function (f) {
      var counts = {};
      rows.forEach(function (r) {
        for (var i = 0; i < fams.length; i++) if (fams[i] !== f && !inFamily(r, fams[i], sel[fams[i].key])) return;
        f.of(r).forEach(function (v) { counts[v] = (counts[v] || 0) + 1; });
      });
      out[f.key] = counts;
    });
    return out;
  }

  /* -------- the list: one view over any source, the bin included ------------------- */
  var SORTS = {
    newest: { label: "Newest first", fn: function (a, b) { return (b.time || "").localeCompare(a.time || ""); } },
    oldest: { label: "Oldest first", fn: function (a, b) { return (a.time || "").localeCompare(b.time || ""); } },
    title: { label: "Title A–Z", fn: function (a, b) { return (a.title || "").localeCompare(b.title || ""); } },
    kind: { label: "Kind", fn: function (a, b) { return (a.kind || "").localeCompare(b.kind || "") || (b.time || "").localeCompare(a.time || ""); } },
    size: { label: "Largest first", fn: function (a, b) { return (b.size || 0) - (a.size || 0); } }
  };
  function readPref(k, d) { try { return localStorage.getItem(NAME + ":" + k) || d; } catch (e) { return d; } }
  function writePref(k, v) { try { localStorage.setItem(NAME + ":" + k, v); } catch (e) { /* private mode */ } }
  var lastList = null;   /* {sig, rows, groups, at}: what the last list fetched */
  var listShown = 0;     /* how many rows the open list shows (0: no list open) */

  /* scope: a source name, "all", or "trash" (the published documents' bin) */
  function listView(scope) {
    var trash = scope === "trash", source = trash ? "published" : scope === "all" ? "" : scope;
    var fams = FAMILIES.filter(function (f) { return !f.allOnly || scope === "all"; });
    var params = new URLSearchParams(location.search);
    var back = history.state || {};
    var state = { q: params.get("q") || "", sort: readPref("sort", "newest"), open: null, shown: Math.max(LIST_PAGE, back.shown || 0), showAll: {} };
    var restoreY = back.scrollY || 0;
    var sel = {};
    fams.forEach(function (f) { sel[f.key] = params.getAll(f.key); });
    var rows = [], groups = [], loading = true, failed = null;
    var famBar = h("div", { class: "facets", role: "group", "aria-label": "Filters" });
    var panel = h("div", { class: "facet-panel", hidden: "" });
    var applied = h("div", { class: "applied", "aria-live": "polite" });
    var countEl = h("span", { class: "count" });
    var listEl = h("div", { class: "list" });

    function anySelected() { return fams.some(function (f) { return sel[f.key].length; }); }
    function urlFor() {
      var u = new URLSearchParams();
      if (state.q) u.set("q", state.q);
      fams.forEach(function (f) { sel[f.key].forEach(function (v) { u.append(f.key, v); }); });
      var qs = u.toString();
      return location.pathname + (qs ? "?" + qs : "");
    }
    /* each filter change is one history entry, so Back undoes it */
    function commit() { var u = urlFor(); if (u !== location.pathname + location.search) history.pushState({ list: true }, "", u); state.shown = LIST_PAGE; restoreY = 0; render(); }
    function toggle(f, v) {
      var i = sel[f.key].indexOf(v);
      if (i >= 0) sel[f.key].splice(i, 1); else sel[f.key].push(v);
      commit();
    }
    function clearFamily(f) { sel[f.key] = []; commit(); }

    function renderFacets(counts) {
      famBar.innerHTML = "";
      fams.forEach(function (f) {
        var n = sel[f.key].length, values = Object.keys(counts[f.key]).length;
        if (!values && !n) return;
        famBar.appendChild(h("button", { class: "btn fam" + (n ? " on" : ""), "aria-expanded": String(state.open === f.key), "aria-controls": "facet-panel",
          onclick: function () { state.open = state.open === f.key ? null : f.key; renderFacets(counts); } },
          [f.label + (n ? " · " + n : ""), h("span", { class: "caret", "aria-hidden": "true" }, [state.open === f.key ? "▴" : "▾"])]));
      });
      var f = fams.filter(function (x) { return x.key === state.open; })[0];
      panel.innerHTML = "";
      if (!f) { panel.hidden = true; return; }
      panel.hidden = false; panel.id = "facet-panel";
      var c = counts[f.key];
      var vals = Object.keys(c);
      sel[f.key].forEach(function (v) { if (vals.indexOf(v) < 0) vals.push(v); });  /* a choice never vanishes */
      if (f.order) vals.sort(function (a, b) { return f.order.indexOf(a) - f.order.indexOf(b); });
      else vals.sort(function (a, b) { return (c[b] || 0) - (c[a] || 0) || a.localeCompare(b); });
      var filterBox = null, needle = (state.filter || {})[f.key] || "";
      if (vals.length > FACET_FILTER_AT) {
        filterBox = h("input", { type: "search", class: "facet-filter", placeholder: "Find a " + f.label.toLowerCase(), value: needle, "aria-label": "Find a " + f.label.toLowerCase(),
          oninput: function (e) { state.filter = state.filter || {}; state.filter[f.key] = e.target.value; drawValues(); } });
      }
      var valuesEl = h("div", { class: "facet-values" });
      function drawValues() {
        var nd = ((state.filter || {})[f.key] || "").toLowerCase();
        var shown = vals.filter(function (v) { return !nd || famName(f, v).toLowerCase().indexOf(nd) >= 0 || sel[f.key].indexOf(v) >= 0; });
        var limit = state.showAll[f.key] || nd ? shown.length : FACET_SHOWN;
        valuesEl.innerHTML = "";
        shown.slice(0, limit).forEach(function (v) {
          var on = sel[f.key].indexOf(v) >= 0;
          valuesEl.appendChild(h("label", { class: "facet" + (on ? " on" : "") }, [
            h("input", { type: "checkbox", checked: on ? "" : null, onchange: function () { toggle(f, v); } }),
            h("span", { class: "facet-label" }, [famName(f, v)]),
            h("span", { class: "facet-count" }, [String(c[v] || 0)])
          ]));
        });
        if (!shown.length) valuesEl.appendChild(h("p", { class: "muted" }, ["None match."]));
        if (shown.length > limit) valuesEl.appendChild(h("button", { class: "btn more", onclick: function () { state.showAll[f.key] = true; drawValues(); } }, ["Show all " + shown.length]));
      }
      drawValues();
      panel.appendChild(h("div", { class: "facet-head" }, [
        h("strong", null, [f.label]), h("span", { class: "muted" }, ["any of"]),
        h("span", { class: "grow" }), sel[f.key].length ? h("button", { class: "btn link", onclick: function () { clearFamily(f); } }, ["Clear"]) : null,
        h("button", { class: "btn link", "aria-label": "Close", onclick: function () { state.open = null; renderFacets(counts); } }, ["Done"])
      ]));
      if (filterBox) panel.appendChild(filterBox);
      panel.appendChild(valuesEl);
    }

    /* the active query in words: one chip per family, "and" between them */
    function renderApplied() {
      applied.innerHTML = "";
      var active = fams.filter(function (f) { return sel[f.key].length; });
      if (!active.length) { applied.hidden = true; return; }
      applied.hidden = false;
      active.forEach(function (f, i) {
        if (i) applied.appendChild(h("span", { class: "and" }, ["and"]));
        var vs = sel[f.key].map(function (v) { return famName(f, v); });
        applied.appendChild(h("span", { class: "chip" }, [
          h("span", null, [f.label + (vs.length > 1 ? " is any of: " : " is: ") + vs.join(", ")]),
          h("button", { class: "chip-x", "aria-label": "Remove the " + f.label.toLowerCase() + " filter", onclick: function () { clearFamily(f); } }, ["×"])
        ]));
      });
      applied.appendChild(h("button", { class: "btn link", onclick: function () { fams.forEach(function (f) { sel[f.key] = []; }); commit(); } }, ["Clear all"]));
    }

    function render() {
      var counts = facetCounts(rows, fams, sel);
      renderFacets(counts); renderApplied();
      listEl.innerHTML = "";
      listEl.setAttribute("aria-busy", String(loading));
      if (loading) { countEl.textContent = ""; listEl.appendChild(h("p", { class: "muted" }, [state.q ? "Searching…" : "Loading…"])); return; }
      if (failed) { listEl.appendChild(h("p", { class: "err" }, [failed])); return; }
      var shown = rows.filter(function (r) { return fams.every(function (f) { return inFamily(r, f, sel[f.key]); }); }).sort(SORTS[state.sort].fn);
      var gs = scope === "published" && !anySelected() ? groups.filter(function (g) { return !state.q || (g.title || "").toLowerCase().indexOf(state.q.toLowerCase()) >= 0; }) : [];
      countEl.textContent = shown.length + (shown.length === 1 ? " item" : " items") + (gs.length ? ", " + gs.length + (gs.length === 1 ? " group" : " groups") : "");
      if (!shown.length && !gs.length) { listEl.appendChild(emptyState()); return; }
      var byTime = state.sort === "newest" || state.sort === "oldest";
      var entries = byTime ? byDate(shown, gs, rows, state.sort === "newest") : shown.map(function (r) { return { doc: r }; });
      entries.slice(0, state.shown).forEach(function (e) {
        if (e.group) return listEl.appendChild(groupCard(e.group, e.time));
        var r = e.doc;
        listEl.appendChild(trash ? card(r, trashActions(r)) : card(r, null, { showSource: scope === "all" }));
      });
      if (entries.length > state.shown) {
        listEl.appendChild(h("button", { class: "btn more", onclick: function () { state.shown += LIST_PAGE; listShown = state.shown; render(); } },
          ["Show " + Math.min(LIST_PAGE, entries.length - state.shown) + " more of " + (entries.length - state.shown)]));
      }
      listShown = state.shown;
      if (restoreY) { window.scrollTo(0, restoreY); restoreY = 0; }
    }
    /* "no results" always names the way back */
    function emptyState() {
      var active = fams.filter(function (f) { return sel[f.key].length; });
      if (!rows.length && !state.q) {
        if (trash) return h("div", { class: "empty" }, ["The recycle bin is empty."]);
        if (scope === "published") return h("div", { class: "empty" }, ["Nothing here yet. An agent publishes with ", h("code", null, ["annals publish report.md"]), "."]);
        return h("div", { class: "empty" }, ["This source is empty."]);
      }
      var ways = active.map(function (f) { return h("button", { class: "btn", onclick: function () { clearFamily(f); } }, ["Remove " + f.label.toLowerCase() + " filter"]); });
      if (state.q) ways.push(h("button", { class: "btn", onclick: function () { search.value = ""; state.q = ""; history.replaceState(history.state, "", urlFor()); load(); } }, ["Clear the search"]));
      return h("div", { class: "empty" }, [h("p", null, ["Nothing matches" + (state.q ? " “" + state.q + "”" : "") + (active.length ? " with these filters" : "") + "."]), h("div", { class: "toolbar center" }, ways)]);
    }
    function trashActions(r) {
      return h("div", { class: "toolbar" }, [
        h("button", { class: "btn", onclick: function () { api("/docs/" + r.id + "/restore", { method: "POST" }).then(function () { toast("Restored"); lastList = null; load(); }); } }, ["Restore"]),
        h("button", { class: "btn danger", onclick: function () {
          if (!window.confirm("Delete “" + (r.title || r.id) + "” forever?")) return;
          api("/docs/" + r.id, { method: "DELETE" }).then(function () { toast("Deleted"); lastList = null; load(); });
        } }, ["Delete forever"])
      ]);
    }
    var seq = 0;
    function load() {
      var sig = scope + "|" + state.q, my = ++seq;
      if (lastList && lastList.sig === sig && Date.now() - lastList.at < LIST_REUSE_MS) {
        rows = lastList.rows; groups = lastList.groups; loading = false; render(); return;
      }
      loading = true; failed = null; render();
      var reqs = [itemsProvider({ source: source, trash: trash }).then(function (p) { return viaStore(p.getList({ search: state.q || undefined })); })];
      if (scope === "published") reqs.push(api("/groups"));
      Promise.all(reqs).then(function (res) {
        if (my !== seq) return;  /* a newer search is on its way */
        rows = res[0].data || []; groups = res[1] ? (res[1].groups || []) : [];
        lastList = { sig: sig, rows: rows, groups: groups, at: Date.now() };
        loading = false; render();
      }).catch(function (e) { if (my !== seq) return; loading = false; failed = String(e.message || e); render(); });
    }
    var timer;
    var search = h("input", { type: "search", placeholder: trash ? "Search the bin" : "Search all text", value: state.q, autocomplete: "off", "aria-label": "Search",
      oninput: function (e) {
        state.q = e.target.value.trim(); history.replaceState(history.state, "", urlFor());
        clearTimeout(timer); timer = setTimeout(load, SEARCH_DEBOUNCE_MS);
      } });
    var sortSel = h("select", { "aria-label": "Sort", onchange: function (e) { state.sort = e.target.value; writePref("sort", state.sort); render(); } },
      Object.keys(SORTS).map(function (k) { var o = h("option", { value: k }, [SORTS[k].label]); if (k === state.sort) o.selected = true; return o; }));
    var title = trash ? "Recycle bin" : scope === "all" ? "Everything" : scope === "published" ? "" : sourceTitle(scope);
    page(title, mainNav(scope), [
      trash ? h("div", { class: "notice" }, ["Documents here stay until you delete them forever."]) : null,
      title && !trash ? h("h2", { class: "scope-title" }, [title]) : null,
      h("div", { class: "controls" }, [search, sortSel]),
      famBar, panel, applied,
      h("div", { class: "row", style: "margin-bottom:8px" }, [countEl]),
      listEl
    ]);
    /* named when it is left, so it says whether a search or filters were on */
    viewLabel = function () { return (title || sourceTitle(scope)) + (location.search ? ", filtered" : ""); };
    load();
  }

  /* -------- rendering one file by its kind ---------------------------------------- */
  /* A file is shown through a context that says where its bytes are and where its
     neighbours open, so a published document and a file of a folder source (a ledger)
     render the same way:
       raw(rel)   the url of the file itself     view(rel)  where a link to it opens here
       known(rel) whether rel exists              main, text the main file and its inline text */
  function docCtx(m) {
    var files = m.files || [];
    return {
      title: m.title, main: m.main, text: m.text, sizes: m.sizes || {},
      raw: function (rel) { return rawUrl(m.id, rel); },
      exportUrl: function (fmt, rel) { return exportUrl(m.id, fmt, rel === m.main ? "" : rel); },
      view: function (rel) { return (m.file_kinds || {})[rel] === "file" ? null : fileUrl(m.id, rel); },
      known: function (rel) { return files.indexOf(rel) >= 0; }
    };
  }
  function itemCtx(it) {
    return {
      title: it.title, main: it.id, text: it.text, sizes: {},
      raw: function (rel) { return filesUrl(it.source, rel); },
      view: function (rel) { return itemHref({ source: it.source, id: rel }); },
      known: function () { return true; }   /* the server answers 404 for a missing one */
    };
  }

  /* Relative links in a markdown file point at its neighbours: images load from their raw
     url, links to other files open them here. */
  function rebase(article, ctx, fromRel) {
    var dir = dirname(fromRel);
    function resolve(u) {
      if (!u || /^([a-z][a-z0-9+.-]*:|\/\/|\/|#)/i.test(u)) return null;
      var parts = (dir + u.split("#")[0].split("?")[0]).split("/"), out = [];
      parts.forEach(function (p) { if (p === "..") out.pop(); else if (p && p !== ".") out.push(p); });
      var rel = decode(out.join("/"));
      return rel && ctx.known(rel) ? rel : null;
    }
    article.querySelectorAll("img[src], video[src], audio[src], source[src]").forEach(function (el) {
      var rel = resolve(el.getAttribute("src")); if (rel) el.setAttribute("src", ctx.raw(rel));
    });
    article.querySelectorAll("a[href]").forEach(function (a) {
      var rel = resolve(a.getAttribute("href")); if (!rel) return;
      var to = ctx.view(rel);
      if (!to) { a.setAttribute("href", ctx.raw(rel)); return; }
      a.setAttribute("href", to);
      a.addEventListener("click", function (e) { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); go(to); });
    });
  }

  function textOf(ctx, rel) {
    if (rel === ctx.main && typeof ctx.text === "string") return Promise.resolve(ctx.text);
    return fetch(ctx.raw(rel), { credentials: "same-origin" }).then(function (r) { if (!r.ok) throw new Error(r.statusText); return r.text(); });
  }

  /* -------- page actions: one declared list, one bar ----------------------------------- */
  /* Every action of a page is a spec {section, label, hint, icon, href|run, ...}; the bar
     shows the primary ones and puts the rest in one "Actions" menu, grouped by section
     (Share, Copy, Download, View, Manage), each with the same icon-and-label row, a
     tooltip, and the keyboard (arrows, Home/End, Esc, type to open). On a phone the menu is
     a bottom sheet with 44px rows. A recipient of a share link gets the same bar without
     the owner's sections. */
  var ACTION_SECTIONS = [["copy", "Copy"], ["download", "Download"], ["view", "View"], ["manage", "Manage"]];
  var ICONS = {
    share: "M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7M16 6l-4-4-4 4M12 2v14",
    listen: "M4 14v-2a8 8 0 0 1 16 0v2M4 14a2 2 0 0 1 2-2h1v7H6a2 2 0 0 1-2-2zM20 14a2 2 0 0 0-2-2h-1v7h1a2 2 0 0 0 2-2z",
    link: "M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1",
    copy: "M9 9h10a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1zM5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1",
    download: "M12 3v12M7 10l5 5 5-5M5 21h14",
    file: "M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7zM14 3v4h4",
    open: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
    trash: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13",
    restore: "M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5",
    more: "M5 12h.01M12 12h.01M19 12h.01",
    check: "M5 12.5l4.5 4.5L19 7.5",
    code: "M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16",
    notebook: "M6 3h11a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6zM6 3v18M10 8h5M10 12h5M3 7h3M3 12h3M3 17h3"
  };
  function svgPath(name) {
    return '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="' + (ICONS[name] || ICONS.file) + '"/></svg>';
  }
  function icon(name) { return h("span", { class: "ico", "aria-hidden": "true", html: svgPath(name) }); }
  /* Saves what the server makes for `url` (a PDF takes a few seconds, so say so); a failure
     says why and leaves the page as it was. */
  var downloading = {};   /* one at a time per url: a second tap would start a second PDF job */
  function saveDownload(url, label) {
    if (downloading[url]) return toast("Still preparing the " + label + "…");
    downloading[url] = true;
    toast("Preparing " + label + "…", 30000);
    return fetch(url, { credentials: "same-origin" }).then(function (r) {
      if (r.status === 401) { if (SHARE) location.reload(); else toLogin(); throw new Error("login"); }
      if (!r.ok) return r.json().catch(function () { return {}; }).then(function (b) { throw new Error(b.detail || r.statusText); });
      var name = ((r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/) || [])[1] || "download";
      return r.blob().then(function (blob) {
        var a = h("a", { href: URL.createObjectURL(blob), download: name });
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 10000);
        toast("Saved " + name);
      });
    }).catch(function (e) { if (e.message !== "login") toast("Could not make the " + label + ": " + (e.message || e), 4000); })
      .then(function () { delete downloading[url]; });
  }
  /* The download actions for one file: a markdown file is exported (.md, PDF); anything else
     is the file itself. */
  function downloadActions(ctx, rel, kind) {
    if (kind === "md" && ctx.exportUrl) return [
      { section: "download", label: "Markdown (.md)", hint: "Save the text as a .md file named after the title", icon: "file", run: function () { return saveDownload(ctx.exportUrl("md", rel), "Markdown"); } },
      { section: "download", label: "PDF", hint: "Save a titled PDF with the images inside; other media are linked", icon: "download", run: function () { return saveDownload(ctx.exportUrl("pdf", rel), "PDF"); } }
    ];
    if (kind === "md") return [];
    return [{ section: "download", label: kind === "file" ? "File" : "Original file", hint: "Save the file as it is", icon: "download", href: downloadUrl(ctx.raw(rel)), download: basename(rel) }];
  }
  function actionItem(a, close) {
    var inner = [icon(a.icon), h("span", { class: "lbl" }, [a.label, a.hint ? h("span", { class: "menuhint" }, [a.hint]) : null])];
    var attrs = { role: "menuitem", class: "menuitem" + (a.danger ? " danger" : ""), title: a.hint || null, tabindex: "-1" };
    if (a.href) {
      Object.assign(attrs, { href: a.href, download: a.download || null, target: a.newTab ? "_blank" : null, rel: a.newTab ? "noopener" : null, onclick: close });
      return h("a", attrs, inner);
    }
    attrs.type = "button"; attrs.onclick = function () { close(); a.run(); };
    return h("button", attrs, inner);
  }
  function actionMenu(actions) {
    if (!actions.length) return null;
    var open = false, root = h("div", { class: "menu-wrap" });
    var btn = h("button", { class: "btn menu-btn", type: "button", "aria-haspopup": "menu", "aria-expanded": "false", "aria-label": "More actions" }, [icon("more"), h("span", { class: "lbl" }, ["More"])]);
    var menu = h("div", { class: "menu", role: "menu", "aria-label": "More actions", hidden: "" });
    var scrim = h("div", { class: "menu-scrim", hidden: "", onclick: function () { setOpen(false); } });
    ACTION_SECTIONS.forEach(function (sec) {
      var rows = actions.filter(function (a) { return a.section === sec[0]; });
      if (!rows.length) return;
      menu.appendChild(h("div", { class: "menu-group", role: "group", "aria-label": sec[1] }, [h("div", { class: "menu-title", "aria-hidden": "true" }, [sec[1]])].concat(rows.map(function (a) { return actionItem(a, function () { setOpen(false, true); }); }))));
    });
    function items() { return Array.prototype.slice.call(menu.querySelectorAll("[role=menuitem]")); }
    function setOpen(v, keepFocus) {
      open = v; btn.setAttribute("aria-expanded", String(v)); menu.hidden = !v; scrim.hidden = !v;
      if (v) { document.addEventListener("keydown", onKey, true); document.addEventListener("pointerdown", onOutside, true); }
      else { document.removeEventListener("keydown", onKey, true); document.removeEventListener("pointerdown", onOutside, true); if (!keepFocus) btn.focus(); }
    }
    function onOutside(e) { if (!root.contains(e.target)) setOpen(false, true); }
    function onKey(e) {
      if (!menu.isConnected) return setOpen(false, true);   /* the page changed under an open menu */
      var list = items(), i = list.indexOf(document.activeElement);
      if (e.key === "Escape") { e.preventDefault(); setOpen(false); }
      else if (e.key === "ArrowDown") { e.preventDefault(); list[(i + 1) % list.length].focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); list[(i - 1 + list.length) % list.length].focus(); }
      else if (e.key === "Home") { e.preventDefault(); list[0].focus(); }
      else if (e.key === "End") { e.preventDefault(); list[list.length - 1].focus(); }
      else if (e.key === "Tab") setOpen(false, true);
    }
    btn.addEventListener("click", function () { setOpen(!open); if (!open) return; items()[0].focus(); });
    btn.addEventListener("keydown", function (e) { if (e.key === "ArrowDown" && !open) { e.preventDefault(); setOpen(true); items()[0].focus(); } });
    root.appendChild(btn); root.appendChild(scrim); root.appendChild(menu);
    return root;
  }
  /* A bin action that ignores a second press while the first runs, and says why it failed. */
  function binOnce(work) {
    var busy = false;
    return function () {
      if (busy) return;
      busy = true;
      return work().catch(function (e) { if (e.message !== "login") toast("That did not work: " + (e.message || e), 4000); }).then(function () { busy = false; });
    };
  }
  /* view: controls that change how it is shown (Rendered | Source); primary: buttons that
     stay on the bar; actions: the menu. Any may be empty. */
  function actionBar(parts) {
    var primary = (parts.primary || []).filter(Boolean).map(function (a) {
      return h("button", { class: "btn", type: "button", "aria-expanded": a.expanded ? (a.expanded === "open" ? "true" : "false") : null, title: a.hint || null, onclick: a.run }, [icon(a.icon), h("span", { class: "lbl" }, [a.label])]);
    });
    var kids = [parts.lead || null].concat(parts.view || [], parts.results || [], primary, [actionMenu((parts.actions || []).filter(Boolean))]);
    return h("div", { class: "toolbar actionbar", role: "toolbar", "aria-label": "Page actions" }, kids);
  }
  /* This page's own address: it needs the owner's login, so it is for the owner's use, never
     for sending (Links makes those). */
  var COPY_ADDRESS = function () { return { section: "copy", label: "Copy my private address", hint: "Opens only with your login; your own agents read it with annals", icon: "link", run: function () { return copyText(location.href); } }; };

  /* Renders `rel` into a container; returns {view, actions} for the page's action bar. */
  function renderFile(ctx, rel, kind, container) {
    var view = [], actions = [];
    if (kind === "md") {
      var mode = readPref("mdmode", "rendered"), text = "";
      /* one toggle, pressed while the markdown source shows (one row of controls on a phone) */
      var seg = h("button", { class: "btn view-toggle", type: "button", "aria-pressed": String(mode === "source"), title: "Show the Markdown source", onclick: function () {
        mode = mode === "source" ? "rendered" : "source"; writePref("mdmode", mode); draw();
      } }, [icon("code"), h("span", { class: "lbl" }, ["Source"])]);
      function draw() {
        seg.setAttribute("aria-pressed", String(mode === "source"));
        container.innerHTML = "";
        if (mode === "source") { container.appendChild(h("pre", { class: "source" }, [text])); withCodeCopy(container); return; }
        withMarked().then(function (mk) {
          var art = h("article", { class: "rendered", html: safeHtml(mk.parse(text, { gfm: true, breaks: false })) });
          rebase(art, ctx, rel); withCodeCopy(art); container.innerHTML = ""; container.appendChild(art);
          if (window.annalsTables) window.annalsTables.enhance(art);
        }).catch(function (e) { container.appendChild(h("p", { class: "err" }, [String(e.message || e)])); });
      }
      container.appendChild(h("p", { class: "muted" }, ["Loading…"]));
      textOf(ctx, rel).then(function (t) { text = t; draw(); }).catch(function (e) { container.innerHTML = ""; container.appendChild(h("p", { class: "err" }, [String(e.message || e)])); });
      view.push(seg);
      actions.push({ section: "copy", label: "Copy source", hint: "Copy the markdown text", icon: "copy", run: function () { return copyText(text); } });
    } else if (kind === "text") {
      var pre = h("pre", { class: "source", "data-loading": "" }, ["Loading…"]), t2 = "";
      container.appendChild(pre);
      withCodeCopy(container);
      textOf(ctx, rel).then(function (t) { t2 = t; pre.textContent = t; pre.removeAttribute("data-loading"); }).catch(function (e) { pre.textContent = String(e.message || e); });
      actions.push({ section: "copy", label: "Copy text", hint: "Copy the file's text", icon: "copy", run: function () { return copyText(t2); } });
    } else if (kind === "html") {
      container.appendChild(h("iframe", { class: "frame", src: ctx.raw(rel), sandbox: FRAME_SANDBOX, title: ctx.title }));
    } else if (kind === "image" || kind === "video" || kind === "audio" || kind === "pdf") {
      container.appendChild(mediaBox(kind, ctx.raw(rel), { name: rel, cls: "full" }));
    } else {
      container.appendChild(h("div", { class: "empty" }, [h("a", { class: "btn primary", href: ctx.raw(rel), download: basename(rel) }, ["Download " + basename(rel)]),
        ctx.sizes[rel] ? h("p", { class: "muted" }, [size(ctx.sizes[rel])]) : null]));
    }
    actions.push({ section: "view", label: kind === "html" ? "Open full page" : "Open raw", hint: "Open the file itself in a new tab", icon: "open", href: ctx.raw(rel), newTab: true });
    return { view: view, actions: actions.concat(downloadActions(ctx, rel, kind)) };
  }

  /* -------- the owner's tags on one item -------------------------------------------- */
  /* Saved as soon as a tag is added or removed (no Save button); a failed save puts the
     tags back and keeps what was typed. Tags live apart from the item: annals never edits
     a ledger. */
  var tagNamesReady;
  function tagNames() {
    tagNamesReady = tagNamesReady || api("/tags").then(function (b) { return Object.keys(b.tags || {}); }).catch(function () { tagNamesReady = null; return []; });
    return tagNamesReady;
  }
  function tagEditor(key, tags, listHref) {
    var current = (tags || []).slice(), saving = Promise.resolve();
    var box = h("div", { class: "tags-edit", "aria-label": "Tags" });
    var chips = h("span", { class: "chips" });
    var listId = "tag-names-" + Math.random().toString(36).slice(2);
    var datalist = h("datalist", { id: listId });
    var input = h("input", { type: "text", list: listId, placeholder: "Add a tag", "aria-label": "Add a tag", autocomplete: "off", enterkeyhint: "done", maxlength: "64" });
    function draw() {
      chips.innerHTML = "";
      current.forEach(function (t) {
        chips.appendChild(h("span", { class: "chip" }, [
          link(listHref + "?tag=" + encodeURIComponent(t), t, "chip-link"),
          h("button", { class: "chip-x", type: "button", "aria-label": "Remove tag " + t, onclick: function () { save(current.filter(function (x) { return x !== t; }), "Removed “" + t + "”"); } }, ["×"])
        ]));
      });
    }
    function save(next, msg, typed) {
      var before = current.slice();
      current = next; draw();
      saving = saving.then(function () {
        return itemsProvider().then(function (p) { return viaStore(p.update(key, { tags: next })); }).then(function (row) {
          current = row.tags || []; draw(); toast(msg); lastList = null; tagNamesReady = null;
          if (typed) input.value = "";
        }).catch(function (e) {
          current = before; draw(); toast("Not saved: " + (e.message || e));
        });
      });
      return saving;
    }
    var form = h("form", { class: "tag-add", onsubmit: function (e) {
      e.preventDefault();
      var t = input.value.replace(/\s+/g, " ").trim();
      if (!t) return;
      if (current.some(function (x) { return x.toLowerCase() === t.toLowerCase(); })) { input.value = ""; return; }
      save(current.concat([t]), "Tagged “" + t + "”", true);
    } }, [input, h("button", { class: "btn", type: "submit" }, ["Add"])]);
    input.addEventListener("focus", function () {
      tagNames().then(function (names) { datalist.innerHTML = ""; names.forEach(function (n) { datalist.appendChild(h("option", { value: n })); }); });
    }, { once: true });
    draw();
    box.appendChild(h("span", { class: "tags-label muted" }, ["Tags"]));
    box.appendChild(chips); box.appendChild(form); box.appendChild(datalist);
    return box;
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
      return h("figure", { class: "player" }, [mediaBox("video", rawUrl(m.id, f), { name: f }), h("figcaption", null, [link(fileUrl(m.id, f), f), sizes[f] ? " · " + size(sizes[f]) : "", " · ", downloadLink(rawUrl(m.id, f), f, "dl")])]);
    }))));
    if (audios.length) out.appendChild(h("section", null, [h("h3", null, [audios.length + " audio"])].concat(audios.map(function (f) {
      return h("figure", { class: "player audio-row" }, [h("figcaption", null, [link(fileUrl(m.id, f), basename(f)), sizes[f] ? " · " + size(sizes[f]) : "", " · ", downloadLink(rawUrl(m.id, f), f, "dl")]), mediaBox("audio", rawUrl(m.id, f), { name: f })]);
    }))));
    if (others.length) out.appendChild(h("section", null, [h("h3", null, [others.length + (others.length === 1 ? " other file" : " other files")]),
      h("ul", { class: "filelist" }, others.map(function (f) {
        return h("li", null, [kindBadge(kinds[f] || "file"), " ", kinds[f] === "file" ? h("a", { href: rawUrl(m.id, f), download: basename(f) }, [f]) : link(fileUrl(m.id, f), f),
          sizes[f] ? h("span", { class: "muted" }, [" " + size(sizes[f])]) : null,
          kinds[f] === "file" ? null : h("span", null, [" · ", downloadLink(rawUrl(m.id, f), f, "dl")])]);
      }))]));
    return out;
  }

  /* -------- the versions of a replaced document (annals publish --replace) ---------- */
  function versionsPanel(m) {
    var base = m.version_of || m.id, list = (m.versions || []).slice();
    if (!list.length) return null;
    var current = m.version_of ? m.current_version : m.version;
    var rows = list.map(function (v) {
      var here = m.version_of && v.n === m.version;
      return h("li", null, [here ? h("strong", null, ["Version " + v.n]) : link(BASE + "/d/" + base + "@" + v.n, "Version " + v.n),
        " · ", h("span", { title: when(v.created) }, [age(v.created)]), v.title ? h("span", { class: "muted" }, [" " + v.title]) : null]);
    }).reverse();
    rows.unshift(h("li", null, [m.version_of ? link(BASE + "/d/" + base, "Version " + current + " (current)") : h("strong", null, ["Version " + current + " (current)"])]));
    return h("details", { class: "more-files versions" }, [h("summary", null, ["Versions (" + (list.length + 1) + ")"]), h("ul", { class: "filelist" }, rows)]);
  }

  /* -------- the interactive version of a page (annals publish --artifact) ----------- */
  /* The publisher and the API validate the link (annals.store.check_artifact_url); a meta
     written elsewhere is checked again here: an https link to claude.ai, nothing else. */
  var ARTIFACT_HOSTS = ["claude.ai"];
  function artifactLink(m) {
    var url = typeof m.artifact === "string" ? m.artifact : "", u;
    if (!/^https:\/\/[A-Za-z0-9\-._~:\/?#\[\]@!$&()*+,;=%]+$/.test(url)) return null;
    try { u = new URL(url); } catch (e) { return null; }
    var known = ARTIFACT_HOSTS.some(function (d) { return u.hostname === d || u.hostname.slice(-d.length - 1) === "." + d; });
    if (u.protocol !== "https:" || !known || u.username || u.password || u.port) return null;
    return h("a", { class: "btn primary", href: url, target: "_blank", rel: "noopener noreferrer" }, ["Open the interactive version"]);
  }

  /* -------- one document, or one file of it --------------------------------------- */
  function docView(id, rel) {
    page("Document", mainNav("published"), [h("p", { class: "muted" }, ["Loading…"])]);
    api("/docs/" + id).then(function (m) {
      var kinds = m.file_kinds || {};
      if (rel && (m.files || []).indexOf(rel) < 0) rel = null;
      var showRel = rel || (m.kind === "folder" ? null : m.main);
      var body = h("div", { class: "doc-body" });
      var tools = { view: [], actions: [] };
      if (showRel) tools = renderFile(docCtx(m), showRel, rel ? kinds[rel] : m.kind, body);

      var fileNav = null;
      if (rel) {  /* prev / next inside an open viewer replace the entry; Back returns to the document */
        /* step through files of the same kind (images among images), as the gallery shows them */
        var k = kinds[rel], same = m.files.filter(function (f) { return kinds[f] === k; });
        var files = ["image", "video", "audio", "pdf"].indexOf(k) >= 0 ? same : m.files, i = files.indexOf(rel);
        var prev = files[i - 1], next = files[i + 1];
        fileNav = h("div", { class: "toolbar filenav" }, [
          upTo(BASE + "/d/" + m.id, "← " + (m.title || "Document"), "btn"),
          h("span", { class: "grow muted" }, [(i + 1) + " / " + files.length + " · " + rel]),
          h("button", { class: "btn", disabled: prev ? null : "", onclick: function () { go(fileUrl(m.id, prev), true); } }, ["Prev"]),
          h("button", { class: "btn", disabled: next ? null : "", onclick: function () { go(fileUrl(m.id, next), true); } }, ["Next"])
        ]);
      }
      var owner = !(rel || SHARE || m.in_trash);
      /* the document is the pick: the same result buttons as a group's, acting on it */
      var docScope = function () { return { kind: "doc", doc: m, ref: m.id, ctx: docCtx(m), items: [m], total: 1, listen: m.listen ? { choices: m.listen.choices } : null }; };
      var docTools = actionBar({
        lead: SHARE ? null : artifactLink(m), view: tools.view,
        results: owner ? resultButtons(docScope) : null,
        actions: [COPY_ADDRESS()].concat(tools.actions, [
          rel || SHARE ? null : (m.in_trash
            ? { section: "manage", label: "Restore", hint: "Take it out of the recycle bin", icon: "restore", run: binOnce(function () { return api("/docs/" + m.id + "/restore", { method: "POST" }).then(function () { toast("Restored"); lastList = null; docView(m.id); }); }) }
            : { section: "manage", label: "Move to bin", hint: "You can restore it from the bin", icon: "trash", danger: true, run: binOnce(function () { return api("/docs/" + m.id + "/trash", { method: "POST" }).then(function () { toast("Moved to the bin"); lastList = null; go(BASE + "/"); }); }) })
        ])
      });
      var isVersion = !!m.version_of;
      var meta = h("div", { class: "meta" }, [
        kindBadge(m.kind), h("span", { title: when(m.created) }, [age(m.created)]),
        m.updated ? h("span", { class: "updated", title: when(m.updated) }, ["updated " + age(m.updated)]) : null,
        m.version > 1 || isVersion ? h("span", null, ["version " + m.version]) : null,
        m.size ? h("span", null, [size(m.size)]) : null,
        sourceText(m.source) ? h("span", null, [sourceText(m.source)]) : null,
        m.source && /^[\w.-]+$/.test(m.source.of || "") ? h("span", null, ["Overview of ", link(BASE + "/d/" + m.source.of, "this document")]) : null,
        m.listen && m.listen.state === "done" && m.listen.overview ? h("span", null, [link(BASE + "/d/" + m.listen.overview, m.listen.stale ? "▶ review (older)" : "▶ review")]) : null,
        m.files && m.files.length > 1 ? h("span", null, [m.files.length + " files"]) : null
      ]);
      /* the groups it is in, each a way to its group (a document reached by a link has no other) */
      var groups = rel || SHARE ? [] : (m.groups || []);
      var inGroups = groups.length ? h("nav", { class: "in-groups", "aria-label": "Groups this document is in" },
        [h("span", { class: "muted" }, [groups.length > 1 ? "In groups" : "In group"])].concat(groups.map(function (g) {
          return link(BASE + "/g/" + g.id, g.title, "group-chip");
        }))) : null;
      var showFiles = !rel && m.files && m.files.length > 1;
      page(rel ? basename(rel) : m.title, mainNav(m.in_trash ? "trash" : "published"), [
        rel ? null : backLink(SHARE ? BASE + "/" : scopeHref("published"), SHARE ? "Shared documents" : sourceTitle("published")),
        m.in_trash ? h("div", { class: "notice" }, ["This document is in the recycle bin."]) : null,
        isVersion ? h("div", { class: "notice" }, ["An earlier version (" + m.version + ") of this document. ", link(BASE + "/d/" + m.version_of, "Open the current version")]) : null,
        SHARE && !rel ? shareNotice() : null,
        h("div", { class: "doc-head" }, [h("h2", null, [m.title || m.id]), meta, inGroups, rel || isVersion || SHARE ? null : tagEditor("published:" + m.id, m.tags, BASE + "/")]),
        fileNav, isVersion ? actionBar({ view: tools.view, actions: [COPY_ADDRESS()].concat(tools.actions) }) : docTools,
        rel || SHARE || isVersion || !m.listenable ? null : listeningPanel(m, body),
        body,
        rel || SHARE ? null : versionsPanel(m),
        showFiles ? (m.kind === "folder" ? filesPanel(m) : h("details", { class: "more-files", open: (m.files || []).some(function (f) { return f !== m.main && ["image", "video", "audio"].indexOf(kinds[f]) >= 0; }) ? "" : null }, [h("summary", null, ["All " + m.files.length + " files"]), filesPanel(m, { skip: m.main })])) : null
      ]);
    }).catch(function (e) { page("Not found", mainNav(""), [h("div", { class: "empty" }, [String(e.message || e)])]); });
  }

  /* -------- pick, then choose what you want back ------------------------------------ */
  /* One way to act on documents, the same on a group and on a document: the documents
     picked (a group's ticked cards, or all of them when none is ticked; a document page is
     a pick of one), then one of three results, each in one sheet: Links, One file, Listen.
     Actions that need no choosing stay in the ⋯ More menu. A scope is
     {kind: "doc" | "group" | "shared", doc?, group?, items: [meta], total, listen?}. */
  var RESULTS = [
    { id: "links", label: "Links", icon: "link", title: "Links", body: linksBody,
      hint: function (sc) { return "Links to open in a browser, or to give a notebook or an agent"; },
      when: function (sc) { return sc.kind !== "shared"; } },
    { id: "file", label: "One file", icon: "file", title: "One file", body: fileBody,
      hint: function (sc) { return sc.items.length > 1 ? "All their files as one Markdown, PDF or web page file, to copy or save" : "Its files as one Markdown, PDF or web page file, to copy or save"; },
      when: function (sc) { return sc.items.some(canCombine); } },
    { id: "listen", label: "Listen", icon: "listen", title: "Listen", body: listenBody,
      hint: function (sc) { return "A few spoken minutes on " + (sc.items.length > 1 ? "these" : "this") + ". The cost is shown before anything is made"; },
      when: function (sc) { return !!sc.listen && sc.items.some(function (m) { return !!m.listen; }); } }
  ];
  /* Text a Markdown file can be made of: a markdown page, or a folder holding markdown. */
  /* What can go in One file (annals.combine): text, html, PDFs and images. Audio and video cannot. */
  var COMBINE_KINDS = ["md", "html", "text", "pdf", "image"];
  var COMBINE_FORMATS = [["md", "Markdown"], ["pdf", "PDF"], ["html", "Web page"]];
  /* the kinds of file a document holds: a listing row names them (held_kinds), a document
     page maps file -> kind (file_kinds); null when the row says neither (a folder source) */
  function heldKinds(m) {
    return m.held_kinds || (m.file_kinds ? Object.keys(m.file_kinds).map(function (f) { return m.file_kinds[f]; }) : null);
  }
  function canCombine(m) {
    var held = heldKinds(m);
    if (held) return held.some(function (k) { return COMBINE_KINDS.indexOf(k) >= 0; });
    return COMBINE_KINDS.indexOf(m.kind) >= 0 || m.kind === "folder";
  }
  function holdsMarkdown(m) { var held = heldKinds(m); return held ? held.indexOf("md") >= 0 : hasText(m); }
  function hasText(m) { return m.kind === "md" || (m.has_markdown === undefined ? m.kind === "folder" : !!m.has_markdown); }
  function scopeLabel(sc) {
    if (sc.kind === "doc") return sc.doc.title || sc.doc.id;
    var n = sc.items.length, of = sc.total;
    return n === of ? (of === 1 ? "1 document" : "all " + of + " documents") : n + " of " + of + " documents";
  }
  /* The result buttons for a scope that may change (a group's picks): each opens its sheet
     on the scope as it is when pressed. `getScope` is called again at every press. */
  function resultButtons(getScope) {
    var sc0 = getScope();
    return RESULTS.filter(function (r) { return r.when(sc0); }).map(function (r) {
      return h("button", { class: "btn result", type: "button", "data-result": r.id, "aria-haspopup": "dialog", onclick: function (e) {
        var sc = getScope();
        if (!sc.items.length) return toast("Pick at least one document");
        if (!r.when(sc)) return toast(r.id === "file" ? "None of these has files that can be put in one file" : "None of these can be spoken");
        taskSheet({ title: r.title, scope: scopeLabel(sc), hint: r.hint(sc), body: r.body(sc), returnTo: e.currentTarget });
      } }, [icon(r.icon), h("span", { class: "lbl" }, [r.label])]);
    });
  }

  /* One sheet at a time, over the page: from the bottom on a phone, a drawer on a wide
     screen. Opening it is a history entry on the same address, so Back closes it (and
     only it); Esc, the scrim and its own Back do the same. */
  var openSheet = null, skipNextPop = false;
  function dropSheet() {
    var s = openSheet;
    if (!s) return null;
    openSheet = null;
    s.el.remove(); s.scrim.remove();
    document.removeEventListener("keydown", s.onKey, true);
    document.documentElement.classList.remove("sheet-open");
    app.inert = false;
    return s;
  }
  /* closes the sheet; `fromHistory` when Back already left its entry. Closed any other way,
     the sheet's entry is stepped back over without drawing the page again, so its ticks,
     scroll and focus stay as they were. */
  function closeSheet(fromHistory) {
    var s = dropSheet();
    if (!s) return false;
    if (!fromHistory && (history.state || {}).sheet) { skipNextPop = true; history.back(); }
    if (s.returnTo && s.returnTo.isConnected) s.returnTo.focus();
    return true;
  }
  /* An entry left marked as a sheet's with no sheet on screen (a reload, or Forward into
     it) sits on top of the same page's own entry: step back onto that one, quietly, so the
     next Back leaves the page instead of drawing it again. */
  function forgetStaleSheet() {
    if ((history.state || {}).sheet && !openSheet) { skipNextPop = true; history.back(); }
  }
  /* leaves the sheet for another view, in place of the sheet's entry: Back then returns
     to the page the sheet was opened over, and the new view's own Back names that page */
  function leaveSheetTo(path) {
    var had = !!dropSheet() && (history.state || {}).sheet;
    if (!had) return go(path);
    history.replaceState({ from: location.pathname + location.search, fromLabel: typeof viewLabel === "function" ? viewLabel() : viewLabel }, "", path);
    route();
  }
  function sheetLink(path, text, cls) {
    return h("a", { href: path, class: cls || null, onclick: function (e) { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); leaveSheetTo(path); } }, [text]);
  }
  function taskSheet(o) {
    var replacing = !!dropSheet();
    var id = "sheet-" + Math.random().toString(36).slice(2);
    var el = h("section", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-labelledby": id }, [
      h("div", { class: "sheet-head" }, [
        h("button", { class: "btn link sheet-back", type: "button", onclick: function () { closeSheet(); } }, ["‹ Back"]),
        h("h3", { id: id }, [o.title, h("span", { class: "sheet-scope" }, [" · " + o.scope])])
      ]),
      o.hint ? h("p", { class: "muted sheet-hint" }, [o.hint]) : null,
      h("div", { class: "sheet-body" }, [o.body])
    ]);
    var scrim = h("div", { class: "sheet-scrim", onclick: function () { closeSheet(); } });
    function onKey(e) { if (e.key === "Escape") { e.preventDefault(); closeSheet(); } }
    openSheet = { el: el, scrim: scrim, onKey: onKey, returnTo: o.returnTo };
    document.body.appendChild(scrim); document.body.appendChild(el);
    document.documentElement.classList.add("sheet-open");
    app.inert = true;   /* aria-modal means it: focus and taps stay in the sheet */
    document.addEventListener("keydown", onKey, true);
    if (!replacing) history.pushState(Object.assign({}, history.state, { sheet: true }), "");
    el.querySelector(".sheet-back").focus();
    return el;
  }

  /* -------- a group: tick documents, then act on them ------------------------------- */
  function groupView(gid) {
    page("Group", mainNav("published"), [h("p", { class: "muted" }, ["Loading…"])]);
    api("/groups/" + gid).then(function (g) {
      var items = (g.items || []).filter(function (m) { return !m.in_trash; });
      var picked = {};   /* id -> true */
      function pickedItems() { return items.filter(function (m) { return picked[m.id]; }); }
      function scope() {
        var p = pickedItems();
        return { kind: "group", group: g, ref: g.id, items: p.length ? p : items, total: items.length, listen: g.listen || null };
      }
      var boxes = [];
      var allBox = h("input", { type: "checkbox", "aria-label": "Pick all documents", onchange: function () {
        var on = allBox.checked; picked = {};
        if (on) items.forEach(function (m) { picked[m.id] = true; });
        update();
      } });
      var count = h("span", { class: "sel-count", role: "status" });
      var clear = h("button", { class: "btn link", type: "button", onclick: function () { picked = {}; update(); } }, ["Clear"]);
      function update() {
        var n = pickedItems().length;
        boxes.forEach(function (b) { b.input.checked = !!picked[b.id]; b.row.classList.toggle("picked", !!picked[b.id]); });
        allBox.checked = n === items.length && n > 0;
        allBox.indeterminate = n > 0 && n < items.length;
        count.textContent = n ? n + " of " + items.length + " picked" : "All " + items.length + (items.length === 1 ? " document" : " documents");
        clear.hidden = !n;
      }
      var rows = items.map(function (m) {
        var input = h("input", { type: "checkbox", "aria-label": "Pick “" + (m.title || m.id) + "”", onchange: function () { if (input.checked) picked[m.id] = true; else delete picked[m.id]; update(); } });
        var row = h("div", { class: "pick-row" }, [h("label", { class: "pick" }, [input]), h("div", { class: "pick-body" }, [inlineItem(m)])]);
        boxes.push({ id: m.id, input: input, row: row });
        return row;
      });
      var more = actionMenu([
        COPY_ADDRESS()
        /* the seam for groups made by hand: "Add to group…" goes here, once the main list can pick too */
      ]);
      var bar = items.length ? h("div", { class: "selbar", role: "toolbar", "aria-label": "Act on the picked documents" }, [
        h("div", { class: "sel-row" }, [h("label", { class: "sel-all" }, [allBox, " All"]), count, clear]),
        h("div", { class: "sel-actions" }, resultButtons(scope).concat([more]))
      ]) : null;
      page(g.title, mainNav("published"), [
        backLink(BASE + "/", sourceTitle("published")),
        h("div", { class: "doc-head" }, [h("h2", null, [g.title || g.id]), h("div", { class: "meta" }, [h("span", { class: "kind group" }, ["group"]), h("span", null, [items.length + " documents"]), h("span", null, [when(g.created)])])]),
        items.length ? h("p", { class: "muted pick-help" }, ["Tick documents to act on some of them; with none ticked, the buttons below act on all of them."]) : null,
        h("div", { class: "list picklist" }, items.length ? rows : [h("div", { class: "empty" }, ["This group has no documents (they may be in the bin)."])]),
        bar
      ]);
      update();
    }).catch(function (e) { page("Not found", mainNav(""), [h("div", { class: "empty" }, [String(e.message || e)])]); });
  }

  /* -------- Links: one link for a person, or a link per document ------------------- */
  /* Both are one share (POST /shares) of what is picked; "a link per document" is a share
     of each document's pages only, listed one link each (annals.notebook), with no
     password since a notebook cannot type one. Nothing is revoked behind the owner's back:
     each press makes a new share, and the ones made before stay listed, each revocable. */
  var NOTEBOOK_URL = "https://notebooklm.google.com/";
  var LINK_MODES = [["one", "One link", "for a person"], ["each", "A link per document", "for a notebook"]];
  var LINK_EXPIRY = {
    one: [["1d", "1 day"], ["7d", "7 days"], ["30d", "30 days"], ["never", "Never"], ["date", "On a date…"]],
    each: [["1d", "1 day"], ["7d", "7 days"], ["30d", "30 days"]]
  };
  var LINK_DFLT_EXPIRY = { one: "7d", each: "1d" };
  function isSourceable(m) { return m.kind === "md" || m.kind === "html" || m.kind === "folder"; }
  function segmented(choices, value, onPick, label) {
    var seg = h("div", { class: "seg seg-wide", role: "group", "aria-label": label || null }, choices.map(function (c) {
      return h("button", { class: "btn", type: "button", "aria-pressed": String(String(c[0]) === String(value)), "data-value": String(c[0]), onclick: function () {
        [].forEach.call(seg.children, function (b) { b.setAttribute("aria-pressed", String(b.getAttribute("data-value") === String(c[0]))); });
        onPick(c[0]);
      } }, [h("span", { class: "seg-main" }, [c[1]]), c[2] ? h("span", { class: "seg-sub" }, [c[2]]) : null]);
    }));
    return seg;
  }
  /* The owner's own agents read the private address through the annals command, so a link
     made only for them is a public copy nobody needed: say so where links are made, and
     copy what to hand them (the page, or the picked documents' addresses, one per line). */
  function agentNote(sc) {
    var whole = sc.kind === "doc" || sc.items.length === sc.total;
    var addresses = whole ? [location.origin + location.pathname]
      : sc.items.map(function (m) { return location.origin + BASE + "/d/" + m.id; });
    var label = addresses.length === 1 ? "Copy the address" : "Copy " + addresses.length + " addresses";
    return h("div", { class: "agent-note" }, [
      h("p", { class: "muted" }, ["Your own agents need no link: give them the private address and they read it with ", h("code", null, ["annals aggregate"]), "."]),
      copyButton(function () { return addresses.join("\n"); }, { label: label, name: label })
    ]);
  }
  function linksBody(sc) {
    /* a share has one root, a document or a group (a pick from the whole list will get its
       group first, through "Add to group…") */
    var ref = sc.ref;
    var mode = readPref("linkmode:" + sc.kind, sc.kind === "doc" ? "one" : "each");
    if (mode !== "one" && mode !== "each") mode = "one";
    var wrap = h("div", { class: "links-body" });
    var opts = h("div", { class: "share-opts" });
    var result = h("div", { class: "share-result", "aria-live": "polite" });
    var made = h("details", { class: "made-links" }, [h("summary", null, ["Links you made for " + (sc.kind === "doc" ? "this" : "this group")])]);
    var madeList = h("div");
    made.appendChild(madeList);
    var redraw = existingShares(ref, madeList, made);
    var picks = [];   /* a document's files and linked pages, when it has a choice of them */
    var expSel, expDate, pw;
    var make = h("button", { class: "btn primary", type: "button", onclick: makeLinks }, [h("span", { class: "lbl" }, [""])]);
    function usable() { return mode === "each" ? sc.items.filter(isSourceable) : sc.items; }
    function drawOpts() {
      opts.innerHTML = ""; result.innerHTML = ""; picks = [];
      var choices = LINK_EXPIRY[mode];
      expSel = h("select", { "aria-label": "Links work for" }, choices.map(function (c) { var o = h("option", { value: c[0] }, [c[1]]); if (c[0] === LINK_DFLT_EXPIRY[mode]) o.selected = true; return o; }));
      expDate = h("input", { type: "date", "aria-label": "Until", hidden: "" });
      expSel.addEventListener("change", function () { expDate.hidden = expSel.value !== "date"; });
      opts.appendChild(h("label", null, [mode === "one" ? "Works for " : "Links work for ", expSel, " ", expDate]));
      if (mode === "one") {
        /* a password the owner hands on, not one of theirs: plain text, kept out of managers */
        pw = h("input", { type: "text", placeholder: "No password", autocomplete: "off", spellcheck: "false", "data-1p-ignore": "", "data-lpignore": "true", "aria-label": "Password (optional)" });
        opts.appendChild(h("label", null, ["Password ", pw, " ", h("button", { class: "btn link", type: "button", onclick: function () { pw.value = newPassword(); } }, ["Generate"])]));
        if (sc.kind === "doc") opts.appendChild(docIncludes(sc.doc.id, picks));
      } else {
        pw = null;
        opts.appendChild(h("p", { class: "muted" }, ["No password: a notebook cannot type one. Paste the links into the notebook's Website source, and each becomes its own source."]));
        var others = sc.items.filter(function (m) { return !isSourceable(m); });
        if (others.length) opts.appendChild(h("p", { class: "muted" }, [others.length + (others.length === 1 ? " is" : " are") + " not a page (" +
          others.map(function (m) { return m.kind; }).filter(function (k, i, a) { return a.indexOf(k) === i; }).join(", ") + ") and get" + (others.length === 1 ? "s" : "") + " no link: a notebook takes those only as uploads."]));
      }
      var n = usable().length;
      make.lastChild.textContent = mode === "one" ? "Make the link" : "Make " + n + (n === 1 ? " link" : " links");
    }
    function makeLinks() {
      if (isPending(make)) return;
      if (!usable().length) return toast("None of these is a page a notebook can read");
      var exp = expSel.value === "date" ? expDate.value : expSel.value;
      if (expSel.value === "date" && !exp) return toast("Pick a date");
      var body = { ref: ref, expires: exp };
      if (sc.kind === "group") body.include = usable().map(function (m) { return m.id; });
      else if (picks.length) body.include = picks.filter(function (p) { return p.input.checked; }).map(function (p) { return p.value; });
      var sentPw = pw ? pw.value : "";   /* what the share is locked with, whatever the field holds later */
      if (sentPw) body.password = sentPw;
      var forNotebook = mode === "each";
      if (forNotebook) { body.files = "sources"; body.title = (sc.kind === "doc" ? sc.doc.title : sc.group.title) + " (a link per document)"; }
      pending(make, true);
      result.innerHTML = "";
      result.appendChild(h("p", { class: "muted", role: "status" }, [forNotebook ? "Making the links…" : "Making the link…"]));
      var share = null;
      api("/shares", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
        .then(function (s) { share = s; return forNotebook ? api("/shares/" + encodeURIComponent(s.token) + "/sources") : null; })
        .then(function (out) { result.innerHTML = ""; if (forNotebook) drawEach(share, out); else drawOne(share, sentPw); redraw(); })
        .catch(function (e) {
          if (share) api("/shares/" + encodeURIComponent(share.token), { method: "DELETE" }).catch(function () {});   /* never leave a link nobody was shown */
          result.innerHTML = "";
          result.appendChild(h("p", { class: "err", role: "alert" }, ["Could not make " + (forNotebook ? "the links" : "the link") + ": " + (e.message || e)]));
        })
        .then(function () { pending(make, false); });
    }
    function drawOne(s, sentPw) {
      var url = absUrl(s.url);
      if (!url) return result.appendChild(h("p", { class: "err" }, ["The link is made, but this server has no public share address (ANNALS_SHARE_BASE_URL), so nobody can open it yet."]));
      /* no copy here on its own: it would run after the network wait, which iOS refuses */
      result.appendChild(copyField(url, { name: "Share link", copyName: "Copy the share link", copied: "Link copied" }));
      result.appendChild(h("p", { class: "muted" }, ["Anyone with it can open " + (sc.kind === "doc" ? "this document" : "these documents") + " without an account · " + shareSummary(s)]));
      if (sentPw) {
        result.appendChild(h("p", { class: "muted" }, ["Send the password separately:"]));
        result.appendChild(copyField(sentPw, { name: "Password", copyName: "Copy the password", copied: "Password copied" }));
      }
      result.appendChild(turnOff(s, "Turn this link off", "Link turned off."));
      result.querySelector(".copy-btn").focus();
    }
    function drawEach(s, out) {
      var urls = out.sources.map(function (x) { return absUrl(x.url); });
      if (!urls.length) return result.appendChild(h("p", { class: "err", role: "alert" }, ["None of these has a page a notebook can read."]));
      var text = urls.join("\n");
      var raw = h("textarea", { class: "combine-text", readonly: "", rows: String(Math.min(urls.length, 8)), spellcheck: "false", "aria-label": "One link per line" }, [text]);
      var asText = h("details", { class: "links-as-text" }, [h("summary", null, ["All links as text"]), raw]);
      var n = urls.length, nLinks = n + (n === 1 ? " link" : " links");
      result.appendChild(h("p", { role: "status" }, [nLinks + ", one per document" + (s.expires ? ", until " + until(s.expires) : "") + "."]));
      result.appendChild(h("div", { class: "toolbar combine-actions" }, [
        copyButton(text, { label: n === 1 ? "Copy the link" : "Copy all " + n + " links", primary: true, copied: nLinks + " copied", field: function () { asText.open = true; return raw; } }),
        h("a", { class: "btn", href: NOTEBOOK_URL, target: "_blank", rel: "noopener" }, [icon("open"), h("span", { class: "lbl" }, ["Open NotebookLM"])])
      ]));
      result.appendChild(h("ol", { class: "link-list" }, out.sources.map(function (x, i) {
        return h("li", null, [h("div", { class: "link-title" }, [x.title]), copyField(urls[i], { name: "Link to " + x.title, copyName: "Copy the link to " + x.title, copied: "Link copied" })]);
      })));
      result.appendChild(asText);
      (out.skipped || []).forEach(function (x) { result.appendChild(h("p", { class: "muted" }, ["“" + (x.title || x.doc) + "” has no page (only " + x.kinds.join(", ") + "), so it has no link."])); });
      result.appendChild(h("p", { class: "muted" }, ["A notebook keeps its own copy once a link is added, so turning the links off afterwards does not remove its sources."]));
      result.appendChild(turnOff(s, "Turn these links off", "Links turned off. Sources already in a notebook stay there."));
    }
    function turnOff(s, label, done) {
      var off = h("button", { class: "btn danger", type: "button", onclick: function () {
        if (isPending(off)) return;
        pending(off, true);
        api("/shares/" + encodeURIComponent(s.token), { method: "DELETE" }).then(function () {
          result.innerHTML = "";
          result.appendChild(h("p", { role: "status" }, [done]));
          redraw();
        }).catch(function (e) { pending(off, false); toast(String(e.message || e)); });
      } }, [label]);
      return h("div", { class: "toolbar" }, [off]);
    }
    wrap.appendChild(agentNote(sc));
    wrap.appendChild(segmented(LINK_MODES, mode, function (v) { mode = v; writePref("linkmode:" + sc.kind, v); drawOpts(); }, "What kind of links"));
    wrap.appendChild(opts);
    wrap.appendChild(h("div", { class: "toolbar" }, [make]));
    wrap.appendChild(result);
    wrap.appendChild(made);
    drawOpts();
    return wrap;
  }
  /* "What's included": a document's files and the annals pages it links to, folded; by
     default every file the page shows goes, and no linked page. */
  function docIncludes(id, picks) {
    var box = h("details", { class: "includes" }, [h("summary", null, ["What's included"])]);
    var inner = h("div", { class: "share-picks" }, [h("p", { class: "muted" }, ["Loading…"])]);
    box.appendChild(inner);
    function selectBy(test) { picks.forEach(function (p) { if (!p.input.disabled) p.input.checked = test(p); }); }
    api("/docs/" + id + "/shareable").then(function (r) {
      inner.innerHTML = "";
      var files = r.files || [];
      if (files.length > 1) {
        inner.appendChild(h("h4", null, ["Files"]));
        inner.appendChild(h("div", { class: "toolbar" }, [h("span", { class: "muted" }, ["Select:"]),
          h("button", { class: "btn link", type: "button", onclick: function () { selectBy(function (p) { return p.file; }); } }, ["All files"]),
          h("button", { class: "btn link", type: "button", onclick: function () { selectBy(function (p) { return p.referenced; }); } }, ["What the page shows"]),
          h("button", { class: "btn link", type: "button", onclick: function () { selectBy(function () { return false; }); } }, ["None"])]));
        files.forEach(function (f) {
          var row = checkRow([kindBadge(f.kind), " " + f.rel, f.main ? h("span", { class: "muted" }, [" (the page)"]) : f.referenced ? h("span", { class: "tag" }, ["on the page"]) : null,
            f.size ? h("span", { class: "muted" }, [" " + size(f.size)]) : null], true, { disabled: f.main, value: f.rel });
          picks.push({ input: row.input, value: f.rel, referenced: f.referenced || f.main, file: true });
          inner.appendChild(row.el);
        });
      }
      if ((r.pages || []).length) {
        inner.appendChild(h("h4", null, ["Pages it links to (each with what it shows)"]));
        inner.appendChild(h("p", { class: "muted" }, ["Unchecked, a link to one of these shows as “link not shared”."]));
        r.pages.forEach(function (pg) {
          var row = checkRow([kindBadge(pg.kind), " " + (pg.title || pg.id)], false, { value: pg.id });
          picks.push({ input: row.input, value: pg.id, referenced: false, file: false });
          inner.appendChild(row.el);
        });
      }
      if (!inner.children.length) inner.appendChild(h("p", { class: "muted" }, ["Just the page: it has no other files."]));
    }).catch(function (e) { inner.innerHTML = ""; inner.appendChild(h("p", { class: "err" }, [String(e.message || e)])); });
    return box;
  }

  /* -------- One file: the text as one Markdown file -------------------------------- */
  function fileBody(sc) {
    if (sc.kind === "doc" && sc.doc.kind === "md") return docFileBody(sc.doc, sc.ctx);
    var without = sc.items.filter(function (m) { return !canCombine(m); }).length;
    var url = sc.kind === "shared" ? API + "/aggregate" : aggregateUrl(sc, sc.items);
    var first = !sc.items.length || sc.items.some(holdsMarkdown) ? "md" : "pdf";
    return h("div", null, [combinePanel(url, first), without ? h("p", { class: "muted" }, [without + (without === 1 ? " has" : " have") + " nothing that can be put in one file (audio and video cannot) and " + (without === 1 ? "is" : "are") + " left out."]) : null]);
  }
  /* The owner's one-file url for a pick: GET /aggregate takes a group and/or documents. */
  function aggregateUrl(sc, docs) {
    var q = (sc.group ? ["group=" + encodeURIComponent(sc.group.id)] : []).concat(docs.map(function (m) { return "doc=" + encodeURIComponent(m.id); }));
    return API + "/aggregate?" + q.join("&");
  }
  function docFileBody(m, ctx) {
    var wrap = h("section", { class: "combine-panel" });
    var raw = h("textarea", { class: "combine-text", readonly: "", rows: "10", spellcheck: "false", "aria-label": "The Markdown text" }, [""]);
    var text = typeof m.text === "string" ? m.text : null;
    var copy = copyButton(function () { return text; }, { label: "Copy Markdown", primary: true, field: raw, copied: "Markdown copied" });
    var acts = [copy];
    if (ctx && ctx.exportUrl) {
      acts.push(h("button", { class: "btn", type: "button", onclick: function () { return saveDownload(ctx.exportUrl("md", m.main), "Markdown"); } }, [icon("file"), h("span", { class: "lbl" }, ["Download .md"])]));
      acts.push(h("button", { class: "btn", type: "button", onclick: function () { return saveDownload(ctx.exportUrl("pdf", m.main), "PDF"); } }, [icon("download"), h("span", { class: "lbl" }, ["Download PDF"])]));
    }
    wrap.appendChild(h("div", { class: "toolbar combine-actions" }, acts));
    wrap.appendChild(raw);
    function show(t) { text = t; raw.value = t; }
    if (text !== null) show(text);
    else { raw.value = "Loading…"; fetch(rawUrl(m.id, m.main), { credentials: "same-origin" }).then(function (r) { if (!r.ok) throw new Error(r.statusText); return r.text(); }).then(show).catch(function (e) { raw.value = "Could not read it: " + (e.message || e); }); }
    return wrap;
  }

  /* -------- Listen: a review of one document, or of several ------------------------ */
  function listenBody(sc) {
    var spoken = sc.items.filter(function (m) { return !!m.listen && !isCombined(m); });
    if (!spoken.length) spoken = sc.items.filter(function (m) { return !!m.listen; });
    if (sc.kind === "doc" || spoken.length === 1) return listenPanel(spoken[0], spoken[0].listen);
    return groupListen(sc, spoken);
  }
  /* a document made by putting several together for one review: it counts as those */
  function isCombined(m) { return (m.tags || []).indexOf("combined") >= 0; }
  function isCurrent(m) { return m.listen.state === "done" && !m.listen.stale; }
  function groupListen(sc, spoken) {
    var wrap = h("section", { class: "listen-panel" });
    var current = spoken.filter(isCurrent), missing = spoken.filter(function (m) { return !isCurrent(m) && ["queued", "running"].indexOf(m.listen.state) < 0; });
    var n = spoken.length, choices = (sc.listen && sc.listen.choices) || spoken[0].listen.choices;
    var mode = missing.length ? "all" : "each", minutes = choices[1] ? choices[1].minutes : choices[0].minutes;
    var skipped = sc.items.length - n;
    wrap.appendChild(h("p", null, [current.length ? current.length + " of " + n + (current.length === 1 ? " has" : " have") + " a current review." : "None of these " + n + " has a review yet.",
      skipped ? " " + skipped + " cannot be spoken and " + (skipped === 1 ? "is" : "are") + " left out." : ""]));
    var modeSeg = segmented([["all", "One review of all " + n, "covers them together"], ["each", "One each", missing.length ? "makes " + missing.length + ", reuses " + (n - missing.length) : "all made already"]], mode, function (v) { mode = v; draw(); }, "What kind of review");
    var lenSeg = segmented(choices.map(function (c) { return [c.minutes, c.minutes + " min"]; }), minutes, function (v) { minutes = +v; draw(); }, "Length");
    var cost = h("p", { class: "muted" });
    var start = h("button", { class: "btn primary", type: "button", onclick: ask }, [""]);
    var status = h("div", { "aria-live": "polite" });
    var rows = h("ul", { class: "review-rows" });
    function charsFor(m) { var c = choices.filter(function (x) { return x.minutes === minutes; })[0]; return c ? c.characters : 0; }
    function draw() {
      var spend = mode === "all" ? 1 : missing.length;
      var chars = spend * charsFor();
      cost.textContent = spend ? "About " + chars.toLocaleString() + " characters of voice, plus " + (spend === 1 ? "one Claude call" : spend + " Claude calls") + ". Nothing is spent until you press Make it." : "Every one already has a current review: play them below.";
      start.textContent = mode === "all" ? "Make it" : spend ? "Make " + spend + (spend === 1 ? " review" : " reviews") : "Nothing to make";
      start.hidden = !spend;
      lenSeg.hidden = !spend;
    }
    function drawRows() {
      rows.innerHTML = "";
      spoken.forEach(function (m) {
        var s = m.listen, state = isCurrent(m) ? sheetLink(BASE + "/d/" + s.overview, "▶ Play its review") : s.state === "done" ? h("span", { class: "muted" }, ["its review is older than the document"]) :
          s.state === "queued" || s.state === "running" ? h("span", { class: "muted" }, ["being made"]) : s.state === "failed" ? h("span", { class: "err" }, ["the last try failed"]) : h("span", { class: "muted" }, ["no review"]);
        rows.appendChild(h("li", null, [h("span", { class: "grow" }, [m.title || m.id]), " ", state]));
      });
    }
    function ask() {
      if (isPending(start)) return;
      pending(start, true);
      status.innerHTML = "";
      status.appendChild(h("p", { class: "muted", role: "status" }, ["Asking…"]));
      var done;
      if (mode === "all") {
        var body = { docs: spoken.map(function (m) { return m.id; }), minutes: minutes };
        if (sc.group) body.group = sc.group.id;
        done = api("/overviews", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
          .then(function (out) {
            var s = out.listen || {}, where = sheetLink(BASE + "/d/" + out.doc, "their combined document");
            status.innerHTML = "";
            if (s.state === "done" && s.overview) {
              status.appendChild(h("p", { role: "status" }, ["One review of all " + n + " already exists (" + s.minutes + " min). ", sheetLink(BASE + "/d/" + s.overview, "▶ Play it", "btn primary")]));
            } else {
              status.appendChild(h("p", { role: "status" }, ["Preparing one " + (s.minutes || minutes) + " minute review of all " + n + ". It takes about 2 minutes, and you can leave. It will be on ", where, sc.group ? ", now in this group." : "."]));
            }
            start.hidden = true; modeSeg.hidden = true; lenSeg.hidden = true; cost.hidden = true;
          });
      } else {
        var queue = missing.slice(), asked = 0;
        done = (function next() {
          var m = queue.shift();
          if (!m) return Promise.resolve();
          return api("/docs/" + encodeURIComponent(m.id) + "/overview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ minutes: minutes }) })
            .then(function (s) { m.listen = s; asked += 1; drawRows(); return next(); });
        })().then(function () {
          status.innerHTML = "";
          status.appendChild(h("p", { role: "status" }, [asked + (asked === 1 ? " review" : " reviews") + " asked for. Each takes about 2 minutes; the documents show ▶ review when theirs is ready."]));
          missing = []; start.hidden = true; lenSeg.hidden = true; cost.hidden = true;
        });
      }
      done.catch(function (e) {
        status.innerHTML = "";
        status.appendChild(h("p", { class: "err", role: "alert" }, ["Could not ask for it: " + (e.message || e)]));
        drawRows();
      }).then(function () { pending(start, false); });
    }
    wrap.appendChild(modeSeg); wrap.appendChild(lenSeg); wrap.appendChild(cost); wrap.appendChild(h("div", { class: "toolbar" }, [start])); wrap.appendChild(status); wrap.appendChild(rows);
    draw(); drawRows();
    return wrap;
  }

  /* -------- a spoken review of one document (annals.overview) ------------------- */
  var LISTEN_POLL_MS = 5000, LISTEN_MAX_MISSES = 5;
  function listenPanel(m, first) {
    var wrap = h("section", { class: "listen-panel", "aria-label": "Spoken review" });
    var url = "/docs/" + encodeURIComponent(m.id) + "/overview";
    var picked = first.minutes, misses = 0;
    function show(s, note) {
      m.listen = s;  /* so reopening the panel shows this, not what the page loaded with */
      wrap.innerHTML = "";
      wrap.setAttribute("aria-busy", String(s.state === "queued" || s.state === "running"));
      if (s.state === "queued" || s.state === "running") {
        wrap.appendChild(h("p", { role: "status" }, ["Preparing your " + s.minutes + " minute overview. This takes about 2 minutes, and you can leave this page."]));
        setTimeout(function () {
          if (!wrap.isConnected) return;
          api(url).then(function (next) { misses = 0; show(next); }).catch(function (e) {
            misses += 1;
            if (misses < LISTEN_MAX_MISSES) return show(s, "Could not check on it. Trying again.");
            wrap.setAttribute("aria-busy", "false");
            wrap.innerHTML = "";
            wrap.appendChild(h("p", { class: "err", role: "alert" }, ["Stopped checking on it: " + (e.message || e) + ". Reload this page to look again."]));
          });
        }, LISTEN_POLL_MS);
        if (note) wrap.appendChild(h("p", { class: "muted" }, [note]));
        return;
      }
      if (s.state === "done") wrap.appendChild(h("p", null, [sheetLink(BASE + "/d/" + s.overview, "▶ Play the review", "btn primary"), s.stale ? " This document has changed since it was made." : ""]));
      if (s.state === "done" && !s.stale) return;  /* current, so there is nothing to pay for */
      if (s.state === "failed") wrap.appendChild(h("p", { class: "err", role: "alert" }, ["That did not work: " + (s.error || "no reason given")]));
      if (note) wrap.appendChild(h("p", { class: "err", role: "alert" }, [note]));
      var cost = h("p", { class: "muted" });
      function drawCost() {
        var c = s.choices.filter(function (x) { return x.minutes === picked; })[0];
        cost.textContent = "About " + c.characters.toLocaleString() + " characters of voice, plus one Claude call. Your voice service bills by the character.";
      }
      var seg = h("div", { class: "seg", role: "group", "aria-label": "Length" }, s.choices.map(function (c) {
        return h("button", { class: "btn", type: "button", "aria-pressed": String(c.minutes === picked), onclick: function () {
          picked = c.minutes;
          [].forEach.call(seg.children, function (b, i) { b.setAttribute("aria-pressed", String(s.choices[i].minutes === picked)); });
          drawCost();
        } }, [c.minutes + " min"]);
      }));
      drawCost();
      var start = h("button", { class: "btn" + (s.state === "done" ? "" : " primary"), type: "button", onclick: function () {
        if (isPending(start)) return;
        pending(start, true); start.textContent = "Asking…";
        api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ minutes: picked }) })
          .then(function (next) { show(next); })
          .catch(function (e) { show(s, "Could not ask for it: " + (e.message || e)); });
      } }, [s.state === "done" ? "Make a new one" : "Make it"]);
      wrap.appendChild(seg); wrap.appendChild(cost); wrap.appendChild(start);
    }
    show(first);
    return wrap;
  }
  /* One file: the pick as Markdown (shown, to copy), PDF or a web page (made once, then saved
     or opened from memory, so a download is not a second job). The server says what it left
     out and why (X-Annals-Skipped); nothing is stored. */
  function combinePanel(url, first) {
    var wrap = h("section", { class: "combine-panel", "aria-label": "One file" });
    var body = h("div", { "aria-live": "polite" });
    var token = 0, blobUrl = null;
    wrap.appendChild(segmented(COMBINE_FORMATS.map(function (f) { return [f[0], f[1]]; }), first, show, "Which kind of file"));
    wrap.appendChild(body);
    function withFormat(f) { return url + (url.indexOf("?") < 0 ? "?" : "&") + "format=" + f; }
    function label(f) { return COMBINE_FORMATS.filter(function (x) { return x[0] === f; })[0][1]; }
    function skippedNote(r) {
      var raw = r.headers.get("X-Annals-Skipped");
      if (!raw) return null;
      var info; try { info = JSON.parse(decodeURIComponent(raw)); } catch (e) { return null; }
      var shown = (info.listed || []).slice(0, 5), more = info.n - shown.length;
      return h("details", { class: "muted", open: "" }, [h("summary", null, [info.n + (info.n === 1 ? " file" : " files") + " left out"]),
        h("ul", null, shown.map(function (x) { return h("li", null, [x.label + ": " + x.reason]); }).concat(more > 0 ? [h("li", null, ["and " + more + " more"])] : []))]);
    }
    function show(f) {
      var mine = ++token;
      if (blobUrl) { URL.revokeObjectURL(blobUrl); blobUrl = null; }
      body.innerHTML = ""; body.setAttribute("aria-busy", "true");
      var status = h("p", { class: "muted" }, [f === "pdf" ? "Making the PDF…" : "Combining the files…"]);
      body.appendChild(status);
      function fail(e) {
        if (mine !== token || e.message === "login") return;
        body.removeAttribute("aria-busy");
        status.className = "err"; status.textContent = "Could not combine them: " + (e.message || e);
      }
      fetch(withFormat(f), { credentials: "same-origin" }).then(function (r) {
        if (r.status === 401) { if (SHARE) location.reload(); else toLogin(); throw new Error("login"); }
        if (!r.ok) return r.json().catch(function () { return {}; }).then(function (b) { throw new Error(b.detail || r.statusText); });
        var n = +(r.headers.get("X-Annals-Sections") || 0);
        var name = ((r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/) || [])[1] || "combined." + f;
        return (f === "md" ? r.text() : r.blob()).then(function (data) {
          if (mine !== token) return;
          body.removeAttribute("aria-busy");
          var bytes = f === "md" ? new Blob([data]).size : data.size;
          status.textContent = n + (n === 1 ? " file, " : " files, ") + size(bytes) + (f === "pdf" ? ", with a bookmark for each file" : ", with a table of contents") + ". Made just now, not saved anywhere.";
          var left = skippedNote(r);
          if (left) body.appendChild(left);
          if (f === "md") draw(data, name); else drawFile(f, data, name);
        });
      }).catch(fail);
    }
    function draw(text, name) {
      var raw = h("textarea", { class: "combine-text", readonly: "", rows: "10", spellcheck: "false", "aria-label": "The combined Markdown" }, [text]);
      body.appendChild(h("div", { class: "toolbar combine-actions" }, [
        copyButton(text, { label: "Copy Markdown", primary: true, field: raw, copied: "Markdown copied" }),
        h("a", { class: "btn", href: downloadUrl(withFormat("md")), download: name }, [icon("download"), h("span", { class: "lbl" }, ["Download .md"])]),
        h("a", { class: "btn", href: withFormat("md"), target: "_blank", rel: "noopener" }, [icon("open"), h("span", { class: "lbl" }, ["Open as text"])])
      ]));
      body.appendChild(raw);
    }
    function drawFile(f, blob, name) {
      blobUrl = URL.createObjectURL(blob);
      body.appendChild(h("div", { class: "toolbar combine-actions" }, [
        h("a", { class: "btn primary", href: blobUrl, download: name }, [icon("download"), h("span", { class: "lbl" }, ["Download " + (f === "pdf" ? "PDF" : ".html")])]),
        /* a web page opens from the server, whose headers sandbox it; a blob url would not */
        h("a", { class: "btn", href: f === "html" ? withFormat("html") : blobUrl, target: "_blank", rel: "noopener" }, [icon("open"), h("span", { class: "lbl" }, ["Open " + label(f).toLowerCase()])])
      ]));
    }
    show(first);
    return wrap;
  }

  /* -------- share links: the owner's list, and the recipient's root ------------------ */
  function pending(btn, on) {
    btn.setAttribute("aria-busy", String(on));
    if (on) btn.setAttribute("aria-disabled", "true"); else btn.removeAttribute("aria-disabled");
  }
  function isPending(btn) { return btn.getAttribute("aria-busy") === "true"; }
  /* A share is made by the owner's API (POST /shares) and served by annals.share_api;
     the dialog only chooses what goes in it. Defaults are the safe ones: every file the
     page shows, a link that ends in 7 days, no password unless one is typed. */
  var PW_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789";
  function newPassword(n) {
    var a = new Uint32Array(n || 12), out = "";
    window.crypto.getRandomValues(a);
    a.forEach(function (x, i) { out += (i && i % 4 === 0 ? "-" : "") + PW_ALPHABET[x % PW_ALPHABET.length]; });
    return out;
  }
  /* A moment to come, as a date: "Oct 30, 14:00" (when() reads the past). */
  function until(iso) {
    var d = new Date(iso), now = new Date();
    return d.toLocaleDateString([], { month: "short", day: "numeric", year: d.getFullYear() !== now.getFullYear() ? "numeric" : undefined }) +
      ", " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  function absUrl(u) { return u ? new URL(u, location.href).href : null; }
  function shareSummary(s) {
    var bits = [s.expires ? "expires " + until(s.expires) : "never expires"];
    if (s.protected) bits.push("password");
    var n = 0; Object.keys(s.docs || {}).forEach(function (d) { n += (s.docs[d] || []).length; });
    if (n) bits.push(n + (n === 1 ? " file" : " files"));
    if (s.revoked) bits = ["revoked " + when(s.revoked)];
    else if (s.active === false) bits = ["expired " + until(s.expires)];
    return bits.join(" · ");
  }
  function shareRow(s, onChange) {
    var live = !s.revoked && s.active !== false;
    return h("li", { class: "share-row" + (live ? "" : " dead") }, [
      h("div", { class: "grow" }, [h("div", null, [s.title || s.token]), h("div", { class: "meta" }, [ageEl(s.created), h("span", null, [shareSummary(s)])])]),
      live && s.url ? copyField(absUrl(s.url), { name: "Link to " + (s.title || "this share"), copyName: "Copy the link to " + (s.title || "this share"), copied: "Link copied", cls: "row-link" }) : null,
      live ? h("button", { class: "btn danger", onclick: function () {
        if (!window.confirm("Turn off this link? Whoever has it loses access at once.")) return;
        api("/shares/" + encodeURIComponent(s.token), { method: "DELETE" }).then(function () { toast("Link turned off"); onChange(); })
          .catch(function (e) { toast(String(e.message || e)); });
      } }, ["Revoke"]) : null
    ]);
  }
  /* The live links made for `ref`, each revocable; `fold` (a <details>) is hidden while
     there are none and counts them when there are. */
  function existingShares(ref, box, fold) {
    function draw() {
      api("/shares?ref=" + encodeURIComponent(ref)).then(function (b) {
        box.innerHTML = "";
        if (fold) { fold.hidden = !b.shares.length; var sum = fold.querySelector("summary"); sum.textContent = sum.textContent.replace(/ \(\d+\)$/, "") + " (" + b.shares.length + ")"; }
        if (!b.shares.length) return;
        box.appendChild(h("ul", { class: "share-list" }, b.shares.map(function (s) { return shareRow(s, draw); })));
      }).catch(function () { box.innerHTML = ""; if (fold) fold.hidden = true; });
    }
    draw();
    return draw;
  }
  function checkRow(label, checked, opts) {
    opts = opts || {};
    var box = h("input", { type: "checkbox", checked: checked ? "" : null, disabled: opts.disabled ? "" : null, value: opts.value });
    return { input: box, el: h("label", { class: "check" }, [box, " "].concat(label)) };
  }
  function sharesView() {
    var all = new URLSearchParams(location.search).get("all") === "1";
    page("Links", mainNav("shares"), [h("p", { class: "muted" }, ["Loading…"])]);
    api("/shares" + (all ? "?all=1" : "")).then(function (b) {
      var list = b.shares || [];
      page("Links", mainNav("shares"), [
        h("div", { class: "doc-head" }, [h("h2", null, ["Links you made"]), h("p", { class: "muted" }, ["Public links to a document or to some of a group's documents. To make another, open it and press Links."])]),
        b.linkable ? null : h("div", { class: "notice" }, ["This server has no public share address (ANNALS_SHARE_BASE_URL): these links cannot be opened yet."]),
        h("div", { class: "toolbar" }, [link(BASE + "/shares" + (all ? "" : "?all=1"), all ? "Only live links" : "Show revoked and expired too", "btn")]),
        list.length ? h("ul", { class: "share-list" }, list.map(function (s) {
          var row = shareRow(s, sharesView);
          var href = BASE + (s.root.kind === "group" ? "/g/" : "/d/") + s.root.id;
          row.firstChild.firstChild.replaceWith(h("div", null, [link(href, s.title || s.root.id)]));
          return row;
        })) : h("div", { class: "empty" }, [all ? "No links yet." : "No live links. Press Links on a document or a group to make one."])
      ]);
    }).catch(function (e) { page("Links", mainNav("shares"), [h("div", { class: "empty" }, [String(e.message || e)])]); });
  }

  /* The recipient: one line saying what this is, and the share's documents. */
  function shareNotice() {
    return h("div", { class: "notice share-notice" }, ["Shared with you" + (SHARE.expires ? " · this link works until " + until(SHARE.expires) : "")]);
  }
  function shareRootView() {
    page(NAME, [], [h("p", { class: "muted" }, ["Loading…"])]);
    api("/share").then(function (s) {
      page(s.title, [], [shareNotice(),
        h("div", { class: "doc-head" }, [h("h2", null, [s.title]), h("div", { class: "meta" }, [h("span", { class: "kind group" }, ["shared"]), h("span", null, [s.docs.length + (s.docs.length === 1 ? " document" : " documents")])])]),
        (function () { var r = resultButtons(function () { return { kind: "shared", items: s.docs, total: s.docs.length }; }); return r.length ? actionBar({ results: r }) : null; })(),
        h("div", { class: "list" }, s.docs.length ? s.docs.map(inlineItem) : [h("div", { class: "empty" }, ["Nothing here any more."])])
      ]);
    }).catch(function (e) { page(NAME, [], [h("div", { class: "empty" }, [String(e.message || e)])]); });
  }

  /* -------- audio: every spoken overview, and what you have heard of each ----------- */
  /* annals.listening keeps, per reader and document, the seconds heard (a union of spans,
     so a replay counts once), the listens to the end, where playback stopped and the
     reader's own "done" mark, on the server, so it follows them to every device. The page
     sends what was played: a framed overview tells it through annals.media's relay
     (postMessage from the frame), a plain audio file through its own element. */
  var LISTEN = {
    flushEveryS: 15,   /* send once this many new seconds were heard */
    resumeMinS: 5      /* a stop earlier than this is not worth picking up from */
  };
  var STATUS_LABEL = { not_started: "Not started", started: "In progress", done: "Done" };
  var listener = null;   /* the tracker of the document on screen, or null */

  function clock(s) { s = Math.max(0, Math.round(s || 0)); var m = Math.floor(s / 60), r = s % 60; return m + ":" + (r < 10 ? "0" : "") + r; }
  function listeningUrl(id) { return API + "/listening/" + encodeURIComponent(id); }
  /* The listening API without the page's login redirect: progress is never worth leaving
     the audio for. Resolves to null when the host keeps no progress (404). */
  function listeningCall(id, opts) {
    return fetch(listeningUrl(id), Object.assign({ credentials: "same-origin" }, opts || {})).then(function (r) {
      if (r.status === 404 && !(opts && opts.method)) return null;
      if (!r.ok) throw new Error(r.statusText || "not saved");
      return r.json();
    });
  }
  function rangesOf(tr) { var out = []; for (var i = 0; tr && i < tr.length; i++) out.push([tr.start(i), tr.end(i)]); return out; }
  function total(spans) { return spans.reduce(function (n, s) { return n + Math.max(0, s[1] - s[0]); }, 0); }
  /* One document's player, reported as samples {why, t, d, playing, ended, played} (seconds;
     played: what the element itself says it played), sent to the server every so often.
     Whatever was played is sent whole each time: the server keeps the union, so a resend or
     a retry adds nothing twice, and nothing heard while events were held back is lost. */
  function listenTracker(docId, onSaved) {
    var played = [], sentS = 0, duration = null, position = null, moved = false, ends = [], stopped = false, everPlayed = false;
    function playId() { return Date.now().toString(36) + Math.random().toString(36).slice(2, 8); }
    var play = playId();
    function sample(s) {
      if (stopped || typeof s.t !== "number" || !isFinite(s.t)) return;
      if (typeof s.d === "number" && isFinite(s.d) && s.d > 0) duration = s.d;
      if (Array.isArray(s.played)) played = s.played.filter(function (r) { return Array.isArray(r) && r.length === 2 && isFinite(r[0]) && isFinite(r[1]); });
      if (s.playing || total(played) > 0) everPlayed = true;
      /* where it stopped is only worth saving once something played or was sought: a page
         that only loaded its audio (at 0:00) must not wipe the place another device left */
      if (total(played) > sentS || (s.why === "seeked" && everPlayed)) { position = s.t; moved = true; }
      if (s.why === "ended") { ends.push(play); play = playId(); flush(); }
      else if (s.why === "pause" || total(played) - sentS >= LISTEN.flushEveryS) flush();
    }
    function flush(leaving) {
      if (!moved && !ends.length) return Promise.resolve();
      var body = { spans: played.slice(0, 500), duration: duration };
      if (moved) body.position = position;
      var end = ends[0], heard = total(played);
      if (end) body.ended = end;
      moved = false;
      return listeningCall(docId, { method: "POST", keepalive: !!leaving, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
        .then(function (rec) {
          sentS = Math.max(sentS, heard);
          if (end && ends[0] === end) ends.shift();
          if (ends.length) flush(leaving);
          if (rec && onSaved && !stopped) onSaved(rec);
        })
        .catch(function () { if (body.position !== undefined) moved = true; });  /* sent again next time */
    }
    return {
      sample: sample, flush: flush, frame: null,
      hasPlayed: function () { return everPlayed; },
      discard: function () { stopped = true; moved = false; ends = []; },
      stop: function () { if (!stopped) { flush(true); stopped = true; } }
    };
  }
  function stopListening() { if (listener) { listener.stop(); listener = null; } }
  window.addEventListener("message", function (e) {
    var m = e.data;
    if (!listener || !listener.frame || !m || m.annals !== "media" || e.source !== listener.frame.contentWindow) return;
    listener.sample(m);
  });
  document.addEventListener("visibilitychange", function () { if (document.visibilityState === "hidden" && listener) listener.flush(true); });
  window.addEventListener("pagehide", function () { if (listener) listener.flush(true); });

  function progressBar(pct, label) {
    return h("div", { class: "heard", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(pct), "aria-label": label || "Heard" },
      [h("div", { class: "heard-fill", style: "width:" + pct + "%" })]);
  }
  function heardWords(L) {
    var parts = [STATUS_LABEL[L.status] || L.status];
    if (L.percent) parts.push(L.percent + "% heard");
    if (L.listens) parts.push(L.listens === 1 ? "heard to the end once" : "heard to the end " + L.listens + " times");
    if (L.status === "started" && L.position >= LISTEN.resumeMinS) parts.push("stopped at " + clock(L.position) + (L.duration ? " of " + clock(L.duration) : ""));
    else if (L.duration) parts.push(clock(L.duration) + " long");
    return parts.join(" · ");
  }
  /* "Done" from the page: the reader's own mark, set or cleared, saved at once. */
  function markButton(id, L, onSaved) {
    var done = L.status === "done";
    var btn = h("button", { class: "btn mark", "aria-pressed": String(done), title: done ? "Mark as not heard yet" : "Mark as heard",
      onclick: function () {
        if (isPending(btn)) return;
        pending(btn, true);
        listeningCall(id, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ done: !done }) })
          .then(function (rec) { toast(rec.status === "done" ? "Marked as heard" : "Marked as not heard yet"); onSaved(rec); })
          .catch(function (e) { pending(btn, false); toast("Not saved: " + (e.message || e), 4000); });
      } }, [done ? "✓ Done" : "Mark done"]);
    return btn;
  }

  /* On a document that plays audio: what you have heard of it, the mark, and Start over.
     Playback picks up where it stopped, on any device, unless it has already started here. */
  function listeningPanel(m, body) {
    var frame = body.querySelector("iframe.frame"), el = frame ? null : body.querySelector("audio, video");
    if (!frame && !el) return null;
    var wrap = h("section", { class: "listening", "aria-label": "What you have heard", hidden: "" });
    var t = listenTracker(m.id, function (rec) { draw(rec, false); });
    t.frame = frame;
    var frameReady = !frame, whenReady = null;
    /* the frame's relay hears a "start at" only once the frame has loaded (it cannot be
       asked: a sandboxed frame's document is never readable from here) */
    if (frame) frame.addEventListener("load", function () { frameReady = true; if (whenReady) whenReady(); }, { once: true });
    if (el) ["play", "pause", "seeking", "seeked", "ended", "timeupdate", "loadedmetadata"].forEach(function (name) {
      el.addEventListener(name, function () { t.sample({ why: name, t: el.currentTime, d: el.duration, playing: !el.paused && !el.ended, ended: el.ended, played: rangesOf(el.played) }); });
    });
    /* this page's tracker from now on, once the page holding the panel is on screen (page()
       stops the previous one); a panel left behind by a quick move on never takes over */
    Promise.resolve().then(function () { if (wrap.isConnected) { stopListening(); listener = t; } });
    function seek(at) {
      if (frame) { try { frame.contentWindow.postMessage({ annals: "media-cmd", seek: at }, "*"); } catch (e) { /* frame gone */ } }
      else if (el) { var to = function () { el.currentTime = at; }; if (el.readyState >= 1) to(); else el.addEventListener("loadedmetadata", to, { once: true }); }
    }
    function draw(L, arriving) {
      wrap.innerHTML = ""; wrap.hidden = false;
      wrap.appendChild(progressBar(L.percent));
      var resume = arriving && !t.hasPlayed() && L.status === "started" && L.position >= LISTEN.resumeMinS && (!L.duration || L.position < L.duration - LISTEN.resumeMinS);
      wrap.appendChild(h("div", { class: "listening-row" }, [
        h("p", { class: "meta grow", role: "status" }, [heardWords(L)]),
        resume ? h("button", { class: "btn", title: "Play from the beginning instead", onclick: function (e) { seek(0); e.currentTarget.remove(); toast("Starts from the beginning"); } }, ["Start over"]) : null,
        markButton(m.id, L, function (rec) { draw(rec, false); }),
        L.percent || L.listens || L.status !== "not_started" ? h("button", { class: "btn link", title: "Forget what you heard of this", onclick: function (e) {
          var b = e.currentTarget; if (isPending(b)) return; pending(b, true);
          /* the player still holds what it played; reload it, so nothing heard before is sent again */
          t.discard();
          listeningCall(m.id, { method: "DELETE" }).then(function () { toast("Progress cleared"); route(); }).catch(function (er) { pending(b, false); toast("Not cleared: " + (er.message || er), 4000); });
        } }, ["Reset"]) : null
      ]));
      if (resume) seek(L.position);
    }
    listeningCall(m.id).then(function (L) {
      if (!L || !wrap.isConnected) return;
      if (frameReady) draw(L, true); else whenReady = function () { draw(L, true); };
    }).catch(function () { /* progress unavailable: the audio still plays */ });
    return wrap;
  }

  /* BASE/audio: every spoken overview, searchable, filtered by what you have heard. */
  function audioView() {
    var params = new URLSearchParams(location.search);
    var state = { q: params.get("q") || "", status: params.get("status") || "" };
    var rows = null, tracked = true, failed = null, unmade = [], poll = null;
    var seg = h("div", { class: "seg status-filter", role: "group", "aria-label": "Show" });
    var unmadeEl = h("section", { class: "unmade", "aria-label": "Asked for, not made yet", "aria-live": "polite" });
    var countEl = h("span", { class: "count" });
    var listEl = h("div", { class: "list audio-list", "aria-busy": "true" }, [h("p", { class: "muted" }, ["Loading…"])]);
    function urlFor() {
      var u = new URLSearchParams();
      if (state.q) u.set("q", state.q);
      if (state.status) u.set("status", state.status);
      var qs = u.toString();
      return location.pathname + (qs ? "?" + qs : "");
    }
    function matches(r) {
      var hay = ((r.title || "") + " " + (r.tags || []).join(" ") + " " + (r.excerpt || "")).toLowerCase();
      return state.q.toLowerCase().split(/\s+/).filter(Boolean).every(function (w) { return hay.indexOf(w) >= 0; });
    }
    function render() {
      renderUnmade();
      listEl.innerHTML = "";
      listEl.setAttribute("aria-busy", String(rows === null && !failed));
      if (failed) { listEl.appendChild(h("p", { class: "err" }, [failed])); return; }
      if (rows === null) { listEl.appendChild(h("p", { class: "muted" }, ["Loading…"])); return; }
      var found = rows.filter(matches), counts = { "": found.length };
      found.forEach(function (r) { counts[r.listening.status] = (counts[r.listening.status] || 0) + 1; });
      seg.innerHTML = "";
      seg.hidden = !tracked;
      [""].concat(Object.keys(STATUS_LABEL)).forEach(function (s) {
        seg.appendChild(h("button", { class: "btn", "aria-pressed": String(state.status === s), onclick: function () {
          if (state.status === s) return;
          state.status = s; history.pushState(history.state, "", urlFor()); render();
        } }, [(s ? STATUS_LABEL[s] : "All") + " " + (counts[s] || 0)]));
      });
      var shown = found.filter(function (r) { return !state.status || r.listening.status === state.status; });
      countEl.textContent = shown.length + (shown.length === 1 ? " overview" : " overviews");
      if (!shown.length) { listEl.appendChild(emptyState()); return; }
      shown.forEach(function (r) { listEl.appendChild(audioRow(r)); });
    }
    /* What was asked for and is not in the list: being made, or failed with why and a retry.
       Without it an overview that failed simply never shows up, with no word of why. */
    function renderUnmade() {
      unmadeEl.innerHTML = "";
      var shown = state.status === "started" || state.status === "done" ? [] : unmade.filter(matches);
      unmadeEl.hidden = !shown.length;
      if (!shown.length) return;
      unmadeEl.appendChild(h("h3", null, ["Not made yet"]));
      shown.forEach(function (u) { unmadeEl.appendChild(unmadeRow(u)); });
    }
    /* One line of title, one of state: what happened, when it was last tried, and why behind
       a toggle (opened below it), with Try again beside the text rather than under it. */
    function unmadeRow(u) {
      var href = BASE + "/d/" + u.doc, making = u.state === "queued" || u.state === "running";
      var link = h("a", { class: "title", href: href, onclick: function (e) { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); go(href); } }, [u.title]);
      var why = h("p", { class: "why", hidden: true }, [u.error || ""]);
      var whyBtn = u.error && !making ? h("button", { class: "btn link", type: "button", "aria-expanded": "false", onclick: function () {
        var open = whyBtn.getAttribute("aria-expanded") !== "true";
        whyBtn.setAttribute("aria-expanded", String(open)); why.hidden = !open;
      } }, ["Why"]) : null;
      var tried = u.finished || u.requested;
      var line = h("p", { class: "meta" }, [
        h("span", { class: making ? "muted" : "err" }, [making ? "Being made (" + u.minutes + " min), about 2 minutes" : "Did not work"]),
        tried ? h("span", { title: until(tried) }, [(making ? "asked " : "tried ") + when(tried)]) : null,
        whyBtn,
        u.created ? h("span", { class: "muted", title: until(u.created) }, ["document from " + when(u.created)]) : null
      ]);
      var text = h("div", { class: "unmade-text" }, [link, line, why]);
      if (making) return h("div", { class: "unmade-row" }, [text]);
      var retry = h("button", { class: "btn", type: "button", onclick: function () {
        if (isPending(retry)) return;
        pending(retry, true);
        api("/docs/" + encodeURIComponent(u.doc) + "/overview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ minutes: u.minutes }) })
          .then(function (s) { Object.assign(u, s, { requested: new Date().toISOString(), finished: null }); render(); watch(); })
          .catch(function (e) { pending(retry, false); toast("Could not ask again: " + (e.message || e)); });
      } }, ["Try again"]);
      return h("div", { class: "unmade-row failed" }, [text, retry]);
    }
    /* While one is being made, look again now and then, so it moves into the list when ready. */
    function watch() {
      if (poll || !unmade.some(function (u) { return u.state === "queued" || u.state === "running"; })) return;
      poll = setTimeout(function () {
        poll = null;
        if (!unmadeEl.isConnected) return;
        load().catch(function () { watch(); });  /* a missed look: try again at the next tick */
      }, LISTEN_POLL_MS);
    }
    function load() {
      return api("/audio").then(function (res) {
        rows = res.docs || []; tracked = res.tracked !== false; unmade = res.unmade || [];
        render(); watch();
      });
    }
    function emptyState() {
      if (!rows.length) return h("div", { class: "empty" }, ["No spoken overviews yet. On a document, choose Listen to make one."]);
      var ways = [];
      if (state.status) ways.push(h("button", { class: "btn", onclick: function () { state.status = ""; history.replaceState(history.state, "", urlFor()); render(); } }, ["Show all"]));
      if (state.q) ways.push(h("button", { class: "btn", onclick: function () { search.value = ""; state.q = ""; history.replaceState(history.state, "", urlFor()); render(); } }, ["Clear the search"]));
      var what = state.status ? STATUS_LABEL[state.status].toLowerCase() + " " : "";
      return h("div", { class: "empty" }, [h("p", null, ["No " + what + "overviews" + (state.q ? " match “" + state.q + "”" : "") + "."]), h("div", { class: "toolbar center" }, ways)]);
    }
    function audioRow(r) {
      var L = r.listening, href = BASE + "/d/" + r.id;
      var title = (r.title || r.id).replace(/^Listen:\s*/, "");
      var card = h("a", { class: "card audio-card", href: href, onclick: function (e) { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); go(href); } }, [
        h("p", { class: "title" }, [title]),
        h("div", { class: "meta" }, [
          tracked ? h("span", { class: "status " + L.status }, [STATUS_LABEL[L.status]]) : null,
          L.duration ? h("span", null, [clock(L.duration)]) : null,
          L.percent && L.status !== "done" ? h("span", null, [L.percent + "% heard"]) : null,
          L.listens ? h("span", { title: "Heard to the end" }, [L.listens + "× to the end"]) : null,
          ageEl(r.created)
        ]),
        tracked ? progressBar(L.percent, "Heard of " + title) : null
      ]);
      return h("div", { class: "audio-row" }, [card, tracked ? markButton(r.id, L, function (rec) { r.listening = rec; render(); }) : null]);
    }
    var timer;
    var search = h("input", { type: "search", placeholder: "Search the overviews", value: state.q, autocomplete: "off", "aria-label": "Search the overviews",
      oninput: function (e) { state.q = e.target.value.trim(); clearTimeout(timer); timer = setTimeout(function () { history.replaceState(history.state, "", urlFor()); render(); }, 120); } });
    page("Audio", mainNav("audio"), [
      h("h2", { class: "scope-title" }, ["Audio"]),
      h("div", { class: "controls" }, [search]),
      unmadeEl,
      seg,
      h("div", { class: "row", style: "margin-bottom:8px" }, [countEl]),
      listEl
    ]);
    viewLabel = function () { return "Audio" + (location.search ? ", filtered" : ""); };
    load().catch(function (e) { failed = String(e.message || e); render(); });
  }

  /* -------- one file of a folder source (a ledger) ----------------------------------- */
  function itemView(source, id) {
    var key = source + ":" + id, back = scopeHref(source);
    page(basename(id), mainNav(source), [h("p", { class: "muted", "aria-busy": "true" }, ["Loading…"])]);
    itemsProvider().then(function (p) { return viaStore(p.getOne(key)); }).then(function (it) {
      var body = h("div", { class: "doc-body" });
      var tools = renderFile(itemCtx(it), it.id, it.kind, body);
      var meta = h("div", { class: "meta" }, [
        h("span", { class: "src" }, [sourceTitle(it.source)]), kindBadge(it.kind),
        h("span", { title: when(it.time) }, ["updated " + age(it.time)]),
        it.session ? link(back + "?session=" + encodeURIComponent(it.session), it.session) : null,
        it.size ? h("span", null, [size(it.size)]) : null,
        it.id.indexOf("/") >= 0 ? h("span", { class: "muted" }, [it.id]) : null
      ]);
      page(it.title || basename(id), mainNav(source), [
        backLink(back, sourceTitle(source)),
        h("div", { class: "doc-head" }, [h("h2", null, [it.title || it.id]), meta, tagEditor(key, it.tags, back)]),
        actionBar({ view: tools.view, actions: [COPY_ADDRESS()].concat(tools.actions) }),
        body
      ]);
    }).catch(function (e) { page("Not found", mainNav(source), [h("div", { class: "empty" }, [String(e.message || e), h("p", null, [link(back, "Back to " + sourceTitle(source))])])]); });
  }

  /* -------- router ------------------------------------------------------------------ */
  function route() {
    var path = location.pathname.indexOf(BASE) === 0 ? location.pathname.slice(BASE.length) : location.pathname;
    var parts = path.split("/").filter(Boolean).map(decode); // ["d", id]
    var kind = parts[0], arg = parts[1];
    if (SHARE) {
      if (kind === "d" && arg) return docView(arg, new URLSearchParams(location.search).get("f"));
      if (SHARE.root.kind === "doc") return docView(SHARE.root.id, new URLSearchParams(location.search).get("f"));
      return shareRootView();
    }
    return sources().then(function (list) {
      knownSources = list;
      if (kind === "d" && arg) return docView(arg, new URLSearchParams(location.search).get("f"));
      if (kind === "g" && arg) return groupView(arg);
      if (kind === "i" && arg && parts.length > 2) return itemView(arg, parts.slice(2).join("/"));
      if (kind === "s" && arg) return listView(arg);
      if (kind === "all") return listView("all");
      if (kind === "trash") return listView("trash");
      if (kind === "shares") return sharesView();
      if (kind === "audio") return audioView();
      return listView("published");
    });
  }
  // Back closes an expanded table (tables.js) before it changes the view.
  window.addEventListener("popstate", function () {
    if (skipNextPop) { skipNextPop = false; return; }
    if (closeSheet(true)) return;
    forgetStaleSheet();
    if (!(window.annalsTables && window.annalsTables.closeOnBack())) route();
  });
  forgetStaleSheet();
  route();
})();
