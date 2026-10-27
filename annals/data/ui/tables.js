/* annals tables: every table in a document scrolls sideways and zooms.
   One self-contained script, used two ways: the page loads it after rendering markdown
   (window.annalsTables.enhance(root)), and the server inlines it into published html pages
   (annals.tables), where it enhances every table on load and as they are added.
   A table is wrapped in .at-table: a small toolbar (zoom out, zoom in, fit, 100%, expand)
   over a .at-scroll box that scrolls both ways. Columns keep a readable minimum width, so
   cells wrap at word boundaries and never mid-word; numbers stay on one line. The header
   row and the first column stick while scrolling. Colours come from the page itself
   (currentColor, and the nearest opaque background), so light and dark both work.
   Opt out per table with data-annals-tables="off", or for a whole page on <html>. */
(function () {
  "use strict";
  if (window.annalsTables) return;

  var MIN_ZOOM = 0.1, MAX_ZOOM = 3, STEP = 1.25, STICKY_MIN_COLS = 4;
  var NUMBER = /^[\s$€£¥+\-−~≈<>]*\d[\d,.\s_]*(e[+\-]?\d+)?\s*(%|[a-zA-Zµμ]{0,3})?\s*(\([^)]*\))?\s*$/i;

  var CSS = [
    ".at-table{margin:1em 0;max-width:100%;--at-bg:Canvas;--at-line:rgba(128,128,128,.4)}",
    ".at-bar{display:flex;gap:6px;align-items:center;justify-content:flex-end;padding:0 0 6px;font:13px/1.2 system-ui,-apple-system,sans-serif}",
    ".at-bar button{font:inherit;color:inherit;background:transparent;border:1px solid var(--at-line);border-radius:7px;padding:5px 10px;min-width:34px;cursor:pointer}",
    ".at-bar button:hover{background:rgba(128,128,128,.15)}",
    ".at-bar .at-pct{opacity:.65;min-width:3.2em;text-align:right;font-variant-numeric:tabular-nums}",
    ".at-scroll{overflow:auto;-webkit-overflow-scrolling:touch;overscroll-behavior:contain;touch-action:pan-x pan-y pinch-zoom;max-width:100%;max-height:80vh;border:1px solid var(--at-line);border-radius:8px}",
    ".at-scroll>table{border-collapse:separate;border-spacing:0;display:table;width:max-content;min-width:100%;max-width:none;margin:0;overflow-wrap:normal;word-break:normal;hyphens:none}",
    ".at-scroll th,.at-scroll td{overflow-wrap:normal;word-break:normal;hyphens:none;border:0;border-right:1px solid var(--at-line);border-bottom:1px solid var(--at-line);padding:5px 9px;text-align:left;vertical-align:top;min-width:6ch;max-width:32em;box-sizing:border-box}",
    ".at-scroll th{white-space:normal;position:sticky;top:0;z-index:2;background:var(--at-bg);font-weight:600}",
    ".at-scroll td.at-num,.at-scroll td.at-nowrap{white-space:nowrap}",
    ".at-scroll td.at-num{text-align:right;font-variant-numeric:tabular-nums}",
    ".at-scroll td{background:var(--at-bg)}",
    ".at-sticky-col th:first-child,.at-sticky-col td:first-child{position:sticky;left:0;z-index:1}",
    ".at-sticky-col th:first-child{z-index:3}",
    ".at-scroll tr:last-child>td{border-bottom:0}.at-scroll tr>:last-child{border-right:0}",
    ".at-table.at-full{position:fixed;inset:0;z-index:2147483000;margin:0;padding:10px;background:var(--at-bg);display:flex;flex-direction:column}",
    ".at-table.at-full .at-scroll{flex:1 1 auto;max-height:none;min-height:0}",
    "html.at-lock,html.at-lock body{overflow:hidden}"
  ].join("\n");

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    (kids || []).forEach(function (c) { n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }

  function addStyle() {
    if (document.getElementById("at-style")) return;
    var s = el("style", { id: "at-style" }, [CSS]);
    (document.head || document.documentElement).appendChild(s);
  }

  /* the first opaque background behind the node: sticky cells must cover what scrolls under them */
  function backdrop(node) {
    for (var n = node; n && n.nodeType === 1; n = n.parentElement) {
      var c = getComputedStyle(n).backgroundColor;
      if (c && c !== "transparent" && !/rgba\(\s*\d+,\s*\d+,\s*\d+,\s*0\s*\)/.test(c)) return c;
    }
    return "Canvas";
  }

  function textOf(cell) { return (cell.textContent || "").trim(); }

  function markCells(table) {
    var cols = 0;
    Array.prototype.forEach.call(table.rows, function (r) { cols = Math.max(cols, r.cells.length); });
    Array.prototype.forEach.call(table.querySelectorAll("td"), function (td) {
      var t = textOf(td);
      if (!t) return;
      if (NUMBER.test(t)) td.classList.add("at-num");
      else if (t.length <= 12 && !/\s/.test(t)) td.classList.add("at-nowrap");
    });
    return cols;
  }

  function wrap(table) {
    var cols = markCells(table);
    var bar = el("div", { class: "at-bar", role: "toolbar", "aria-label": "Table view" });
    var pct = el("span", { class: "at-pct", "aria-live": "polite" }, ["100%"]);
    var scroll = el("div", { class: "at-scroll", tabindex: "0" });
    var box = el("div", { class: "at-table" }, [bar, scroll]);
    var zoom = 1, full = false;

    function apply(z) {
      zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z));
      table.style.zoom = zoom === 1 ? "" : String(zoom);
      pct.textContent = Math.round(zoom * 100) + "%";
    }
    function fit() {
      table.style.zoom = "";
      var natural = table.scrollWidth, room = scroll.clientWidth;
      apply(natural > room ? room / natural : 1);
      if (scroll.scrollWidth > room) apply(zoom * room / scroll.scrollWidth * 0.995); // zoom does not scale borders and padding exactly
    }
    function button(label, title, fn) {
      var b = el("button", { type: "button", title: title, "aria-label": title }, [label]);
      b.addEventListener("click", fn);
      return b;
    }
    var expandBtn = button("⤢", "Expand", function () { setFull(!full); });
    function setFull(on) {
      full = on;
      box.classList.toggle("at-full", on);
      document.documentElement.classList.toggle("at-lock", on);
      expandBtn.textContent = on ? "✕" : "⤢";
      expandBtn.title = on ? "Close" : "Expand";
      expandBtn.setAttribute("aria-label", expandBtn.title);
      if (on) fit();
    }
    box.addEventListener("keydown", function (e) { if (e.key === "Escape" && full) setFull(false); });

    [button("−", "Zoom out", function () { apply(zoom / STEP); }),
     button("+", "Zoom in", function () { apply(zoom * STEP); }),
     button("Fit", "Fit to width", fit),
     button("100%", "Actual size", function () { apply(1); }),
     expandBtn, pct].forEach(function (n) { bar.appendChild(n); });

    if (cols >= STICKY_MIN_COLS) scroll.classList.add("at-sticky-col");
    table.parentNode.insertBefore(box, table);
    scroll.appendChild(table);
    box.style.setProperty("--at-bg", backdrop(box));
    return box;
  }

  function worthy(table) {
    if (table.hasAttribute("data-annals-tables") || table.closest("[data-annals-tables=off],.at-table")) return false;
    if (document.documentElement.getAttribute("data-annals-tables") === "off") return false;
    if (table.parentElement && table.parentElement.closest("table")) return false; // nested: layout, not data
    var r = table.rows[0];
    return !!r && r.cells.length >= 2;
  }

  /* Wraps every data table under root; safe to call again. */
  function enhance(root) {
    root = root || document;
    addStyle();
    var found = [];
    Array.prototype.forEach.call(root.querySelectorAll("table"), function (t) {
      if (worthy(t)) { t.setAttribute("data-annals-tables", "on"); found.push(t); }
    });
    return found.map(wrap);
  }

  /* For a whole page: enhance now, and again whenever script adds a table. */
  function watch() {
    var pending = false;
    function run() { pending = false; enhance(document); }
    function schedule() { if (!pending) { pending = true; setTimeout(run, 50); } }
    enhance(document);
    if (window.MutationObserver) new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        var added = muts[i].addedNodes;
        for (var j = 0; j < added.length; j++) {
          var n = added[j];
          if (n.nodeType === 1 && (n.tagName === "TABLE" || (n.querySelector && n.querySelector("table")))) return schedule();
        }
      }
    }).observe(document.documentElement, { childList: true, subtree: true });
  }

  window.annalsTables = { enhance: enhance, watch: watch };
  var script = document.currentScript;
  if (script && script.hasAttribute("data-watch")) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", watch);
    else watch();
  }
})();
