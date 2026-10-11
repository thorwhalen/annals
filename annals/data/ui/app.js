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
   The API lives at window.ANNALS.api (standalone: BASE/api; on enlace: /api/<app>). Items
   (every source's rows, and their tags) are read and patched through @zodal/store-http's
   provider, vendored at API/ui/vendor/, so the storage behind them can change without
   touching this page. Filters live in the URL: ?q=words&kind=md&session=a&date=7d&tag=x.  */
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
      if (r.status === 401) { toLogin(); throw new Error("login"); }
      if (!r.ok) return r.json().catch(function () { return {}; }).then(function (b) { throw new Error(b.detail || r.statusText); });
      return r.json();
    });
  }
  function toLogin() { location.href = "/auth/login?login_required=1&next=" + encodeURIComponent(location.pathname + location.search); }
  function encPath(rel) { return rel.split("/").map(encodeURIComponent).join("/"); }
  function rawUrl(id, rel) { return API + "/raw/" + id + "/" + encPath(rel); }
  function filesUrl(source, rel) { return API + "/files/" + encodeURIComponent(source) + "/" + encPath(rel); }
  function itemHref(r) { return r.source === "published" ? BASE + "/d/" + r.id : BASE + "/i/" + encodeURIComponent(r.source) + "/" + encPath(r.id); }
  function scopeHref(scope) { return scope === "published" ? BASE + "/" : scope === "all" ? BASE + "/all" : BASE + "/s/" + encodeURIComponent(scope); }
  function thumbUrl(id, rel, w) { return API + "/thumb/" + id + "/" + encPath(rel) + "?w=" + w; }
  function fileUrl(id, rel) { return BASE + "/d/" + id + "?f=" + encodeURIComponent(rel); }
  /* Going somewhere is a new history entry; refining the current view replaces it. */
  function go(path, replace) {
    if (path === location.pathname + location.search) return route();
    /* Back to a list returns to the same place in it: remember the scroll and how many
       rows were shown on the entry being left */
    if (!replace) history.replaceState(Object.assign({}, history.state, { scrollY: window.scrollY, shown: listShown }), "");
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

  /* The markdown renderer and its sanitizer load on first use, from the API. Markdown may
     carry raw html, and this page shares its origin with every app on the host, so the
     rendered html always passes through DOMPurify before it touches the page. */
  var markedReady;
  function loadScript(name) {
    return new Promise(function (ok, ko) {
      var s = h("script", { src: API + "/ui/" + name });
      s.onload = ok; s.onerror = function () { ko(new Error("could not load " + name)); };
      document.head.appendChild(s);
    });
  }
  function withMarked() {
    if (window.marked && window.DOMPurify) return Promise.resolve(window.marked);
    markedReady = markedReady || Promise.all([loadScript("marked.min.js"), loadScript("purify.min.js")]).then(function () { return window.marked; });
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

  function safeHtml(html) { return window.DOMPurify.sanitize(html, { ADD_ATTR: ["target"] }); }
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
    app.innerHTML = ""; listShown = 0;
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
  /* One link per source, then everything at once, then the bin; the current one marked. */
  function mainNav(current) {
    var items = knownSources.map(function (s) { return [scopeHref(s.name), s.title, s.name]; });
    if (knownSources.length > 1) items.push([BASE + "/all", "All", "all"]);
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
      (isRow ? sourceText({ session: m.session, host: m.host }) : sourceText(m.source)) ? h("span", null, [isRow ? sourceText({ session: m.session, host: m.host }) : sourceText(m.source)]) : null,
      m.size ? h("span", null, [size(m.size)]) : null,
      m.n_files > 1 ? h("span", null, [m.n_files + " files"]) : null
    ].concat((m.tags || []).map(function (t) { return h("span", { class: "tag" }, [t]); })));
    var text = m.snippet || m.excerpt;
    var c = h("a", { class: "card" + (m.thumb ? " has-thumb" : ""), href: href, onclick: function (e) { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); go(href); } }, [
      thumbFor(m),
      h("div", { class: "card-body" }, [h("p", { class: "title" }, [m.title || m.id]), meta, text ? h("p", { class: "excerpt" + (m.snippet ? " snippet" : "") }, [text]) : null])
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
      if (state.sort === "newest" || state.sort === "oldest") gs.forEach(function (g) { listEl.appendChild(groupCard(g)); });
      shown.slice(0, state.shown).forEach(function (r) { listEl.appendChild(trash ? card(r, trashActions(r)) : card(r, null, { showSource: scope === "all" })); });
      if (shown.length > state.shown) {
        listEl.appendChild(h("button", { class: "btn more", onclick: function () { state.shown += LIST_PAGE; listShown = state.shown; render(); } },
          ["Show " + Math.min(LIST_PAGE, shown.length - state.shown) + " more of " + (shown.length - state.shown)]));
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

  /* Renders `rel` into a container; returns tools for the toolbar. */
  function renderFile(ctx, rel, kind, container) {
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
          var art = h("article", { class: "rendered", html: safeHtml(mk.parse(text, { gfm: true, breaks: false })) });
          rebase(art, ctx, rel); container.innerHTML = ""; container.appendChild(art);
        }).catch(function (e) { container.appendChild(h("p", { class: "err" }, [String(e.message || e)])); });
      }
      container.appendChild(h("p", { class: "muted" }, ["Loading…"]));
      textOf(ctx, rel).then(function (t) { text = t; draw(); }).catch(function (e) { container.innerHTML = ""; container.appendChild(h("p", { class: "err" }, [String(e.message || e)])); });
      tools.push(seg, h("button", { class: "btn", onclick: function () { copyText(text); } }, ["Copy source"]));
    } else if (kind === "text") {
      var pre = h("pre", { class: "source" }, ["Loading…"]), t2 = "";
      container.appendChild(pre);
      textOf(ctx, rel).then(function (t) { t2 = t; pre.textContent = t; }).catch(function (e) { pre.textContent = String(e.message || e); });
      tools.push(h("button", { class: "btn", onclick: function () { copyText(t2); } }, ["Copy"]));
    } else if (kind === "html") {
      container.appendChild(h("iframe", { class: "frame", src: ctx.raw(rel), sandbox: "allow-scripts allow-popups allow-forms allow-modals allow-downloads", title: ctx.title }));
    } else if (kind === "image" || kind === "video" || kind === "audio" || kind === "pdf") {
      container.appendChild(mediaBox(kind, ctx.raw(rel), { name: rel, cls: "full" }));
    } else {
      container.appendChild(h("div", { class: "empty" }, [h("a", { class: "btn primary", href: ctx.raw(rel), download: basename(rel) }, ["Download " + basename(rel)]),
        ctx.sizes[rel] ? h("p", { class: "muted" }, [size(ctx.sizes[rel])]) : null]));
    }
    tools.push(h("a", { class: "btn", href: ctx.raw(rel), target: "_blank", rel: "noopener" }, [kind === "html" ? "Open full page" : "Open raw"]));
    return tools;
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
    page("Document", mainNav("published"), [h("p", { class: "muted" }, ["Loading…"])]);
    api("/docs/" + id).then(function (m) {
      var kinds = m.file_kinds || {};
      if (rel && (m.files || []).indexOf(rel) < 0) rel = null;
      var showRel = rel || (m.kind === "folder" ? null : m.main);
      var body = h("div", { class: "doc-body" });
      var tools = [];
      if (showRel) tools = renderFile(docCtx(m), showRel, rel ? kinds[rel] : m.kind, body);

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
          ? h("button", { class: "btn", onclick: function () { api("/docs/" + m.id + "/restore", { method: "POST" }).then(function () { toast("Restored"); lastList = null; docView(m.id); }); } }, ["Restore"])
          : h("button", { class: "btn danger", onclick: function () { api("/docs/" + m.id + "/trash", { method: "POST" }).then(function () { toast("Moved to the bin"); lastList = null; go(BASE + "/"); }); } }, ["Move to bin"]))
      ]));
      var meta = h("div", { class: "meta" }, [
        kindBadge(m.kind), h("span", { title: when(m.created) }, [age(m.created)]), m.size ? h("span", null, [size(m.size)]) : null,
        sourceText(m.source) ? h("span", null, [sourceText(m.source)]) : null,
        m.files && m.files.length > 1 ? h("span", null, [m.files.length + " files"]) : null
      ]);
      var showFiles = !rel && m.files && m.files.length > 1;
      page(rel ? basename(rel) : m.title, mainNav(m.in_trash ? "trash" : "published"), [
        m.in_trash ? h("div", { class: "notice" }, ["This document is in the recycle bin."]) : null,
        h("div", { class: "doc-head" }, [h("h2", null, [m.title || m.id]), meta, rel ? null : tagEditor("published:" + m.id, m.tags, BASE + "/")]),
        fileNav, docTools, body,
        showFiles ? (m.kind === "folder" ? filesPanel(m) : h("details", { class: "more-files", open: (m.files || []).some(function (f) { return f !== m.main && ["image", "video", "audio"].indexOf(kinds[f]) >= 0; }) ? "" : null }, [h("summary", null, ["All " + m.files.length + " files"]), filesPanel(m, { skip: m.main })])) : null
      ]);
    }).catch(function (e) { page("Not found", mainNav(""), [h("div", { class: "empty" }, [String(e.message || e)])]); });
  }

  /* -------- a group ----------------------------------------------------------------- */
  function groupView(gid) {
    page("Group", mainNav("published"), [h("p", { class: "muted" }, ["Loading…"])]);
    api("/groups/" + gid).then(function (g) {
      var items = (g.items || []).filter(function (m) { return !m.in_trash; });
      page(g.title, mainNav("published"), [
        h("div", { class: "doc-head" }, [h("h2", null, [g.title || g.id]), h("div", { class: "meta" }, [h("span", { class: "kind group" }, ["group"]), h("span", null, [items.length + " documents"]), h("span", null, [when(g.created)])])]),
        h("div", { class: "toolbar" }, [h("button", { class: "btn", onclick: function () { copyText(location.href); } }, ["Copy link"])]),
        h("div", { class: "list" }, items.length ? items.map(function (m) { return card(m); }) : [h("div", { class: "empty" }, ["This group has no documents (they may be in the bin)."])])
      ]);
    }).catch(function (e) { page("Not found", mainNav(""), [h("div", { class: "empty" }, [String(e.message || e)])]); });
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
        h("div", { class: "doc-head" }, [h("h2", null, [it.title || it.id]), meta, tagEditor(key, it.tags, back)]),
        h("div", { class: "toolbar" }, tools.concat([h("button", { class: "btn", onclick: function () { copyText(location.href); } }, ["Copy link"])])),
        body
      ]);
    }).catch(function (e) { page("Not found", mainNav(source), [h("div", { class: "empty" }, [String(e.message || e), h("p", null, [link(back, "Back to " + sourceTitle(source))])])]); });
  }

  /* -------- router ------------------------------------------------------------------ */
  function route() {
    var path = location.pathname.indexOf(BASE) === 0 ? location.pathname.slice(BASE.length) : location.pathname;
    var parts = path.split("/").filter(Boolean).map(decode); // ["d", id]
    var kind = parts[0], arg = parts[1];
    return sources().then(function (list) {
      knownSources = list;
      if (kind === "d" && arg) return docView(arg, new URLSearchParams(location.search).get("f"));
      if (kind === "g" && arg) return groupView(arg);
      if (kind === "i" && arg && parts.length > 2) return itemView(arg, parts.slice(2).join("/"));
      if (kind === "s" && arg) return listView(arg);
      if (kind === "all") return listView("all");
      if (kind === "trash") return listView("trash");
      return listView("published");
    });
  }
  window.addEventListener("popstate", route);
  route();
})();
