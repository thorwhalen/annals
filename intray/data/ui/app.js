/* tray: the page. One file, no build. Routes by path under the first segment:
   /tray/            home: search + sort, newest first
   /tray/d/<id>      one document (md rendered with a source toggle; html framed)
   /tray/g/<gid>     a group: one URL for a set of documents
   /tray/trash       the recycle bin: restore, or delete forever                      */
(function () {
  "use strict";
  var BASE = "/" + (location.pathname.split("/")[1] || "tray");
  var API = BASE + "/api";
  var app = document.getElementById("app");
  var toastEl;

  /* -------- helpers ------------------------------------------------------------- */
  function h(tag, attrs, children) {
    var el = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === "class") el.className = attrs[k];
      else if (k === "html") el.innerHTML = attrs[k];
      else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), attrs[k]);
      else if (attrs[k] !== null && attrs[k] !== undefined) el.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) {
      if (c === null || c === undefined) return;
      el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return el;
  }
  function api(path, opts) {
    return fetch(API + path, Object.assign({ credentials: "same-origin" }, opts || {})).then(function (r) {
      if (r.status === 401) { location.href = "/auth/login?login_required=1&next=" + encodeURIComponent(location.pathname); throw new Error("login"); }
      if (!r.ok) return r.json().catch(function () { return {}; }).then(function (b) { throw new Error(b.detail || r.statusText); });
      return r.json();
    });
  }
  function go(path) { history.pushState(null, "", path); route(); }
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
  function sourceText(src) {
    if (!src) return "";
    return [src.session, src.host].filter(Boolean).join(" @ ");
  }

  /* -------- layout -------------------------------------------------------------- */
  function page(title, nav, body) {
    app.innerHTML = "";
    document.title = title ? title + " · tray" : "tray";
    var wrap = h("div", { class: "wrap" });
    var header = h("header", { class: "bar" }, [h("div", { class: "row" }, [
      h("h1", { class: "grow" }, [link(BASE + "/", "tray")]),
      h("nav", null, nav || [])
    ])]);
    wrap.appendChild(header);
    body.forEach(function (b) { wrap.appendChild(b); });
    app.appendChild(wrap);
    window.scrollTo(0, 0);
  }
  function card(m, extra) {
    var href = BASE + "/d/" + m.id;
    var meta = h("div", { class: "meta" }, [
      kindBadge(m.kind),
      h("span", null, [when(m.created)]),
      m.size ? h("span", null, [size(m.size)]) : null,
      sourceText(m.source) ? h("span", null, [sourceText(m.source)]) : null
    ].concat((m.tags || []).map(function (t) { return h("span", { class: "tag" }, [t]); })));
    var c = h("a", { class: "card", href: href, onclick: function (e) { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); go(href); } }, [
      h("p", { class: "title" }, [m.title || m.id]), meta,
      m.excerpt ? h("p", { class: "excerpt" }, [m.excerpt]) : null
    ]);
    if (extra) { var box = h("div", null, [c, extra]); return box; }
    return c;
  }
  function groupCard(g) {
    var href = BASE + "/g/" + g.id;
    return h("a", { class: "card", href: href, onclick: function (e) { if (e.metaKey || e.ctrlKey) return; e.preventDefault(); go(href); } }, [
      h("p", { class: "title" }, [g.title || g.id]),
      h("div", { class: "meta" }, [h("span", { class: "kind group" }, ["group"]), h("span", null, [g.docs.length + " documents"]), h("span", null, [when(g.created)])])
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
  function readPref(k, d) { try { return localStorage.getItem("tray:" + k) || d; } catch (e) { return d; } }
  function writePref(k, v) { try { localStorage.setItem("tray:" + k, v); } catch (e) { /* private mode */ } }

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
          : h("div", { class: "empty" }, [state.q ? "Nothing matches." : "Nothing here yet. An agent publishes with ", h("code", null, ["tray publish report.md"]), "."]));
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
      oninput: function (e) { state.q = e.target.value; var u = new URL(location.href); if (state.q) u.searchParams.set("q", state.q); else u.searchParams.delete("q"); history.replaceState(null, "", u); render(); } });
    var sortSel = h("select", { "aria-label": "Sort", onchange: function (e) { state.sort = e.target.value; writePref("sort", state.sort); render(); } },
      Object.keys(SORTS).map(function (k) { var o = h("option", { value: k }, [SORTS[k].label]); if (k === state.sort) o.selected = true; return o; }));
    var nav = opts.trash ? [link(BASE + "/", "Documents")] : [link(BASE + "/trash", "Recycle bin")];
    page(opts.trash ? "Recycle bin" : "", nav, [
      opts.trash ? h("div", { class: "notice" }, ["Documents here stay until you delete them forever."]) : null,
      h("div", { class: "controls" }, [search, sortSel]),
      h("div", { class: "row", style: "margin-bottom:8px" }, [countEl]),
      listEl
    ].filter(Boolean));
    load();
  }

  /* -------- one document ---------------------------------------------------------- */
  function docView(id) {
    page("Document", [link(BASE + "/", "Documents")], [h("p", { class: "muted" }, ["Loading…"])]);
    api("/docs/" + id).then(function (m) {
      var rawUrl = API + "/raw/" + m.id + "/" + m.main;
      var mode = m.kind === "md" ? readPref("mdmode", "rendered") : "rendered";
      var body = h("div");
      function renderBody() {
        body.innerHTML = "";
        if (m.kind === "md") {
          if (mode === "rendered") {
            var html = window.marked ? window.marked.parse(m.text || "", { gfm: true, breaks: false }) : "";
            body.appendChild(h("article", { class: "rendered", html: html }));
          } else {
            body.appendChild(h("pre", { class: "source" }, [m.text || ""]));
          }
        } else if (m.kind === "text") {
          body.appendChild(h("pre", { class: "source" }, [m.text || ""]));
        } else if (m.kind === "html") {
          body.appendChild(h("iframe", { class: "frame", src: rawUrl, sandbox: "allow-scripts allow-popups allow-forms allow-modals allow-downloads", title: m.title }));
        } else {
          body.appendChild(h("div", { class: "empty" }, [h("a", { class: "btn primary", href: rawUrl }, ["Download " + m.main])]));
        }
      }
      var seg = m.kind === "md" ? h("div", { class: "seg" }, [
        h("button", { class: "btn", "aria-pressed": String(mode === "rendered"), onclick: function () { mode = "rendered"; writePref("mdmode", mode); refreshSeg(); renderBody(); } }, ["Rendered"]),
        h("button", { class: "btn", "aria-pressed": String(mode === "source"), onclick: function () { mode = "source"; writePref("mdmode", mode); refreshSeg(); renderBody(); } }, ["Source"])
      ]) : null;
      function refreshSeg() { if (!seg) return; seg.children[0].setAttribute("aria-pressed", String(mode === "rendered")); seg.children[1].setAttribute("aria-pressed", String(mode === "source")); }
      var tools = h("div", { class: "toolbar" }, [
        seg,
        (m.kind === "md" || m.kind === "text") ? h("button", { class: "btn", onclick: function () { copyText(m.text || ""); } }, ["Copy source"]) : null,
        h("a", { class: "btn", href: rawUrl, target: "_blank", rel: "noopener" }, [m.kind === "html" ? "Open full page" : "Open raw"]),
        h("button", { class: "btn", onclick: function () { copyText(location.href); } }, ["Copy link"]),
        m.in_trash
          ? h("button", { class: "btn", onclick: function () { api("/docs/" + m.id + "/restore", { method: "POST" }).then(function () { toast("Restored"); docView(m.id); }); } }, ["Restore"])
          : h("button", { class: "btn danger", onclick: function () { api("/docs/" + m.id + "/trash", { method: "POST" }).then(function () { toast("Moved to the bin"); go(BASE + "/"); }); } }, ["Move to bin"])
      ]);
      var meta = h("div", { class: "meta" }, [
        kindBadge(m.kind), h("span", null, [when(m.created)]), m.size ? h("span", null, [size(m.size)]) : null,
        sourceText(m.source) ? h("span", null, [sourceText(m.source)]) : null,
        m.files && m.files.length > 1 ? h("span", null, [m.files.length + " files"]) : null
      ].concat((m.tags || []).map(function (t) { return link(BASE + "/?q=" + encodeURIComponent(t), t, "tag"); })));
      page(m.title, [link(BASE + "/", "Documents"), link(BASE + "/trash", "Bin")], [
        m.in_trash ? h("div", { class: "notice" }, ["This document is in the recycle bin."]) : null,
        h("div", { class: "doc-head" }, [h("h2", null, [m.title || m.id]), meta]),
        tools, body
      ].filter(Boolean));
      renderBody();
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
    var parts = location.pathname.split("/").filter(Boolean); // ["tray", "d", id]
    var kind = parts[1], arg = parts[2];
    if (kind === "d" && arg) return docView(arg);
    if (kind === "g" && arg) return groupView(arg);
    if (kind === "trash") return listView({ trash: true });
    return listView({ trash: false });
  }
  window.addEventListener("popstate", route);
  route();
})();
