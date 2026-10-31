/* annals tables: every table in a document scrolls sideways and zooms.
   One self-contained script, used two ways: the page loads it after rendering markdown
   (window.annalsTables.enhance(root)), and the server inlines it into published html pages
   (annals.tables), where it enhances every table on load and as they are added.
   A table is wrapped in .at-table: a small toolbar (zoom out, zoom in, fit, 100%, expand)
   over a .at-scroll box that scrolls both ways. Columns keep a readable minimum width, so
   cells wrap at word boundaries and never mid-word; numbers stay on one line.
   Rows are told apart by alternating shades, and tapping a row highlights it.
   Sticking is earned, never assumed, because a stuck cell that fills the box leaves nothing
   reachable behind it: the first column sticks only if it fits COLUMN_SHARE of the box, the
   header row only if it fits HEADER_SHARE. Both are measured, and re-checked on zoom.
   Colours come from the page itself (currentColor, and the nearest opaque background), so
   light and dark both work.
   Opt out per table with data-annals-tables="off", or for a whole page on <html>. */
(function () {
  "use strict";
  if (window.annalsTables) return;

  var MIN_ZOOM = 0.1, MAX_ZOOM = 3, STEP = 1.25, STICKY_MIN_COLS = 4;
  var COLUMN_SHARE = 0.4, HEADER_SHARE = 0.3, MAX_HEIGHT_GROWTH = 1.25;
  var NOT_A_ROW_TAP = "a,button,input,select,textarea,label,summary";
  var NUMBER = /^[\s$€£¥+\-−~≈<>]*\d[\d,.\s_]*(e[+\-]?\d+)?\s*(%|[a-zA-Zµμ]{0,3})?\s*(\([^)]*\))?\s*$/i;

  var ZEBRA_ROW = ".at-zebra>table>tbody>tr:nth-child(even)", HIT_ROW = ".at-scroll tr.at-hit";
  var COLOR_MIX = "(color:color-mix(in srgb,red,blue))";
  var expandedOnBack = null;

  /* Cell backgrounds use :where (no specificity), so colours a page gives its own cells win.
     They stay opaque, so a stuck cell covers what scrolls under it. */
  var CSS = [
    ".at-table{margin:1em 0;max-width:100%;--at-bg:Canvas;--at-line:rgba(128,128,128,.4)}",
    ".at-bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;justify-content:flex-end;padding:0 0 6px;font:13px/1.2 system-ui,-apple-system,sans-serif}",
    ".at-bar button{font:inherit;color:inherit;background:transparent;border:1px solid var(--at-line);border-radius:7px;padding:5px 10px;min-width:34px;cursor:pointer}",
    "@media (hover:hover){.at-bar button:hover{background:rgba(128,128,128,.15)}}",
    "@media (pointer:coarse){.at-bar button{min-width:44px;min-height:44px}}",
    ".at-bar .at-pct{opacity:.65;min-width:3.2em;text-align:right;font-variant-numeric:tabular-nums}",
    ".at-scroll{overflow:auto;-webkit-overflow-scrolling:touch;overscroll-behavior-x:contain;touch-action:pan-x pan-y pinch-zoom;max-width:100%;max-height:80vh;border:1px solid var(--at-line);border-radius:8px}",
    ".at-scroll>table{border-collapse:separate;border-spacing:0;display:table;width:max-content;min-width:100%;max-width:none;margin:0;overflow-wrap:normal;word-break:normal;hyphens:none;-webkit-tap-highlight-color:transparent}",
    ".at-scroll th,.at-scroll td{overflow-wrap:normal;word-break:normal;hyphens:none;border:0;border-right:1px solid var(--at-line);border-bottom:1px solid var(--at-line);padding:5px 9px;text-align:left;vertical-align:top;min-width:6ch;max-width:32em;box-sizing:border-box}",
    ".at-scroll th{white-space:normal;font-weight:600}",
    ".at-scroll td.at-num,.at-scroll td.at-nowrap{white-space:nowrap}",
    ".at-scroll td.at-num{text-align:right;font-variant-numeric:tabular-nums}",
    ":where(.at-scroll) :where(th,td){background-color:var(--at-row,var(--at-bg))}",
    "@supports " + COLOR_MIX + "{",
    ":where(" + ZEBRA_ROW + "){--at-row:color-mix(in srgb,currentColor 7%,var(--at-bg))}",
    ":where(" + HIT_ROW + "){--at-row:color-mix(in srgb,currentColor 16%,var(--at-bg))}",
    "}",
    "@supports not " + COLOR_MIX + "{",
    ":where(" + ZEBRA_ROW + ")>*{background-image:linear-gradient(rgba(128,128,128,.12),rgba(128,128,128,.12))}",
    ":where(" + HIT_ROW + ")>*{background-image:linear-gradient(rgba(128,128,128,.28),rgba(128,128,128,.28))}",
    "}",
    ".at-capped .at-first{max-width:var(--at-cap)}",
    ".at-stick-col .at-first{position:sticky;left:0;z-index:1}",
    ".at-stick-head .at-head{position:sticky;top:0;z-index:2}",
    ".at-stick-col.at-stick-head .at-first.at-head{z-index:3}",
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

  function isOpaque(color) {
    if (!color || color === "transparent") return false;
    var alpha = /\/\s*([\d.]+)\s*\)$/.exec(color) || /^rgba\([^,]+,[^,]+,[^,]+,\s*([\d.]+)\s*\)$/.exec(color);
    return !alpha || parseFloat(alpha[1]) >= 1;
  }

  /* the first opaque background behind the node: sticky cells must cover what scrolls under them */
  function backdrop(node) {
    for (var n = node; n && n.nodeType === 1; n = n.parentElement) {
      var c = getComputedStyle(n).backgroundColor;
      if (isOpaque(c)) return c;
    }
    return "Canvas";
  }

  function textOf(cell) { return (cell.textContent || "").trim(); }

  function rowsOf(table) { return Array.prototype.slice.call(table.rows); }

  function markCells(table) {
    Array.prototype.forEach.call(table.querySelectorAll("td"), function (td) {
      var t = textOf(td);
      if (!t) return;
      if (NUMBER.test(t)) td.classList.add("at-num");
      else if (t.length <= 12 && !/\s/.test(t)) td.classList.add("at-nowrap");
    });
  }

  /* What can stick and shade. A span in the first column means a row's first cell is not in
     that column on the rows below, and a rowspan anywhere in the body makes stripes misleading. */
  function shapeOf(table) {
    var rows = rowsOf(table), head = rows[0];
    var cols = rows.reduce(function (n, r) { return Math.max(n, r.cells.length); }, 0);
    var firsts = rows.map(function (r) { return r.cells[0]; }).filter(Boolean);
    var firstSpans = firsts.some(function (c) { return c.rowSpan > 1 || c.colSpan > 1; });
    var bodyCells = Array.prototype.slice.call(table.querySelectorAll("tbody td,tbody th"));
    return {
      firsts: firsts,
      head: head,
      column: cols >= STICKY_MIN_COLS && !firstSpans,
      header: !!head && Array.prototype.every.call(head.cells, function (c) { return c.tagName === "TH"; }),
      zebra: !bodyCells.some(function (c) { return c.rowSpan > 1; })
    };
  }

  function wrap(table) {
    markCells(table);
    var shape = shapeOf(table);
    var bar = el("div", { class: "at-bar", role: "toolbar", "aria-label": "Table view" });
    var pct = el("span", { class: "at-pct", "aria-live": "polite" }, ["100%"]);
    var scroll = el("div", { class: "at-scroll", tabindex: "0" });
    var box = el("div", { class: "at-table" }, [bar, scroll]);
    var zoom = 1, full = false, pushed = false, columnFits = false, settledWidth = -1, hitRow = null;

    function widthOf(n) { return n.getBoundingClientRect().width; }
    function heightOf(n) { return n.getBoundingClientRect().height; }

    /* The ratios at the current zoom. Called on zoom, so zooming in cannot rebuild the trap. */
    function recheck() {
      var first = shape.firsts[0];
      scroll.classList.toggle("at-stick-col", columnFits && widthOf(first) <= scroll.clientWidth * COLUMN_SHARE + 1);
      scroll.classList.toggle("at-stick-head", shape.header && heightOf(shape.head) <= scroll.clientHeight * HEADER_SHARE);
    }
    /* Decides at 100% whether the first column can be capped and stuck. Runs when the box
       changes width; a change of height alone (a phone's address bar) never moves the layout. */
    function settle() {
      var kept = table.style.zoom;
      table.style.zoom = "";
      scroll.classList.remove("at-capped", "at-stick-col");
      table.style.removeProperty("--at-cap");
      columnFits = false;
      var room = scroll.clientWidth;
      if (shape.column && room > 0 && widthOf(table) > room) {
        var cap = Math.round(room * COLUMN_SHARE), before = heightOf(table);
        table.style.setProperty("--at-cap", cap + "px");
        scroll.classList.add("at-capped");
        columnFits = widthOf(shape.firsts[0]) <= cap + 1 && heightOf(table) <= before * MAX_HEIGHT_GROWTH;
        if (!columnFits) {
          scroll.classList.remove("at-capped");
          table.style.removeProperty("--at-cap");
        }
      }
      table.style.zoom = kept;
      recheck();
      settledWidth = widthOf(scroll);
    }
    function apply(z) {
      zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z));
      table.style.zoom = zoom === 1 ? "" : String(zoom);
      pct.textContent = Math.round(zoom * 100) + "%";
      recheck();
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
    var expandBtn = button("⤢", "Expand", function () { if (full) closeFull(); else openFull(); });
    function setFull(on) {
      full = on;
      box.classList.toggle("at-full", on);
      document.documentElement.classList.toggle("at-lock", on);
      expandBtn.textContent = on ? "✕" : "⤢";
      expandBtn.title = on ? "Close" : "Expand";
      expandBtn.setAttribute("aria-label", expandBtn.title);
      settle();
      if (on) fit();
    }
    /* Expand fills the screen, so Back closes it rather than leaving the document. */
    function onBack() {
      pushed = false;
      if (!box.isConnected) { // the app navigated away while expanded: this Back is the app's
        document.documentElement.classList.remove("at-lock");
        return false;
      }
      setFull(false);
      return true;
    }
    function openFull() {
      try {
        history.pushState(Object.assign({}, history.state, { atFull: true }), "");
        pushed = true;
        expandedOnBack = onBack;
      } catch (_) { /* a sandboxed frame may refuse: Close and Esc still work */ }
      setFull(true);
    }
    function closeFull() {
      if (pushed) history.back();
      else setFull(false);
    }
    box.addEventListener("keydown", function (e) { if (e.key === "Escape" && full) closeFull(); });

    /* A tap marks a row to keep your place. Scrolling, pinching and long-press fire no click. */
    table.addEventListener("click", function (e) {
      if (e.target.closest(NOT_A_ROW_TAP)) return;
      var selection = window.getSelection && window.getSelection();
      if (selection && !selection.isCollapsed) return;
      var row = e.target.closest("tr");
      if (!row || row.closest("table") !== table || row.parentNode.tagName !== "TBODY") return;
      if (shape.header && row === shape.head) return;
      if (hitRow) hitRow.classList.remove("at-hit");
      hitRow = row === hitRow ? null : row;
      if (hitRow) hitRow.classList.add("at-hit");
    });

    [button("−", "Zoom out", function () { apply(zoom / STEP); }),
     button("+", "Zoom in", function () { apply(zoom * STEP); }),
     button("Fit", "Fit to width", fit),
     button("100%", "Actual size", function () { apply(1); }),
     expandBtn, pct].forEach(function (n) { bar.appendChild(n); });

    shape.firsts.forEach(function (c) { c.classList.add("at-first"); });
    if (shape.header) Array.prototype.forEach.call(shape.head.cells, function (c) { c.classList.add("at-head"); });
    if (shape.zebra) scroll.classList.add("at-zebra");
    table.parentNode.insertBefore(box, table);
    scroll.appendChild(table);
    box.style.setProperty("--at-bg", backdrop(box));
    settle();
    if (window.ResizeObserver) new ResizeObserver(function () {
      if (Math.abs(widthOf(scroll) - settledWidth) > 0.5) settle();
    }).observe(scroll);
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

  /* If Back should close an expanded table, closes it and returns true. A page with its own
     router asks this first and skips routing on true: on window, listeners fire in the order
     they were added, so this script (often loaded later) cannot get in ahead of the router. */
  function closeOnBack() {
    var handler = expandedOnBack;
    expandedOnBack = null;
    return handler ? handler() : false;
  }
  window.addEventListener("popstate", closeOnBack);

  window.annalsTables = { enhance: enhance, watch: watch, closeOnBack: closeOnBack };
  var script = document.currentScript;
  if (script && script.hasAttribute("data-watch")) {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", watch);
    else watch();
  }
})();
