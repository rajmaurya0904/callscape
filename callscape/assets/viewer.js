(function () {
  "use strict";
  var DATA = JSON.parse(document.getElementById("callscape-data").textContent);
  var SYMS = DATA.syms, FILES = DATA.files, STATS = DATA.stats;
  var KIND_NAME = { c: "call", r: "reference", t: "type use" };
  var $main = document.getElementById("main");
  var $side = document.getElementById("sidebar");
  var $menu = document.getElementById("menu");
  var $search = document.getElementById("search");
  var graphDepth = 1;

  function el(tag, attrs) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === "class") node.className = attrs[k];
        else if (k === "text") node.textContent = attrs[k];
        else if (k.slice(0, 2) === "on") node.addEventListener(k.slice(2), attrs[k]);
        else node.setAttribute(k, attrs[k]);
      });
    }
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c == null) continue;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return node;
  }

  function href(idx) { return "#s=" + idx; }
  function go(idx) { location.hash = "s=" + idx; }
  function loc(s) { return FILES[s.f].p + ":" + s.s; }
  function sortSyms(a, b) { return SYMS[a].q < SYMS[b].q ? -1 : 1; }

  function symLink(idx, extra) {
    var s = SYMS[idx];
    var a = el("a", { href: href(idx), class: "nm", text: s.q });
    var box = el("span", null, a);
    if (extra) box.appendChild(extra);
    return box;
  }

  /* ---------- sidebar ---------- */

  var opened = {};

  function fileSymbols(fileIdx, body, current) {
    body.textContent = "";
    FILES[fileIdx].s.forEach(function (idx) {
      var s = SYMS[idx];
      var cls = "sym-link" + (idx === current ? " current" : "");
      body.appendChild(
        el("a", { href: href(idx), class: cls, "data-idx": idx },
          el("span", { class: "badge " + s.k, text: s.k === "module" ? "top" : s.k.slice(0, 4) }),
          el("span", { class: "nm", text: s.q === "<module>" ? "(top-level code)" : s.q })));
    });
  }

  function buildSidebar(current) {
    $side.textContent = "";
    var lastDir = null;
    var currentFile = current != null ? SYMS[current].f : -1;
    FILES.forEach(function (f, i) {
      if (!f.s.length) return;
      var dir = f.p.indexOf("/") >= 0 ? f.p.slice(0, f.p.lastIndexOf("/")) : ".";
      if (dir !== lastDir) { $side.appendChild(el("div", { class: "dir", text: dir })); lastDir = dir; }
      var name = f.p.slice(f.p.lastIndexOf("/") + 1);
      var det = el("details", null, el("summary", { text: name + (f.x ? "  (parse errors)" : "") }));
      var holder = el("div");
      det.appendChild(holder);
      var fill = function () { if (!holder.firstChild) fileSymbols(i, holder, current); };
      det.addEventListener("toggle", function () { if (det.open) fill(); });
      if (i === currentFile || opened[i]) { det.open = true; fill(); }
      $side.appendChild(det);
      if (i === currentFile) setTimeout(function () { det.scrollIntoView({ block: "nearest" }); }, 0);
    });
  }

  /* ---------- search ---------- */

  function runSearch(q) {
    q = q.trim().toLowerCase();
    if (!q) { route(); return; }
    var hits = [];
    for (var i = 0; i < SYMS.length && hits.length < 300; i++) {
      var s = SYMS[i];
      if (s.k === "module") continue;
      var hay = (s.q + " " + FILES[s.f].p).toLowerCase();
      var at = s.q.toLowerCase().indexOf(q);
      if (hay.indexOf(q) >= 0) hits.push([at < 0 ? 999 : at + (s.n.toLowerCase() === q ? -100 : 0), i]);
    }
    hits.sort(function (a, b) { return a[0] - b[0] || SYMS[a[1]].q.length - SYMS[b[1]].q.length; });
    $main.textContent = "";
    $main.appendChild(el("h1", { text: "Search: " + q }));
    var list = el("ul", { class: "rel" });
    hits.slice(0, 100).forEach(function (h) { list.appendChild(relRow(h[1])); });
    if (!hits.length) list.appendChild(el("li", { class: "empty", text: "No symbol matches." }));
    $main.appendChild(list);
  }

  /* ---------- shared pieces ---------- */

  function relRow(idx, edge) {
    var s = SYMS[idx];
    var li = el("li", null,
      el("span", { class: "badge " + s.k, text: s.k }),
      el("a", { href: href(idx), class: "nm", text: s.q }));
    if (edge) {
      if (edge[2] > 1) li.appendChild(el("span", { class: "loc", text: "x" + edge[2] }));
      if (edge[3]) li.appendChild(el("span", { class: "amb", title: "several candidates matched this name", text: "~" }));
      if (edge[4] && edge[4].length) li.appendChild(el("span", { class: "loc", text: "line " + edge[4].join(", ") }));
    }
    li.appendChild(el("span", { class: "loc", text: loc(s) }));
    return li;
  }

  function relList(title, edges, kinds, emptyText) {
    var rows = edges.filter(function (e) { return kinds.indexOf(e[1]) >= 0; });
    rows.sort(function (a, b) { return sortSyms(a[0], b[0]); });
    var box = el("div", null, el("h2", { text: title + " (" + rows.length + ")" }));
    var ul = el("ul", { class: "rel" });
    rows.forEach(function (e) { ul.appendChild(relRow(e[0], e)); });
    if (!rows.length) ul.appendChild(el("li", { class: "empty", text: emptyText }));
    box.appendChild(ul);
    return box;
  }

  function symTable(rows) {
    var t = el("table");
    rows.forEach(function (r) {
      var s = SYMS[r[0]];
      t.appendChild(el("tr", null,
        el("td", null, el("a", { href: href(r[0]), text: s.q })),
        el("td", { class: "loc", text: loc(s) }),
        el("td", { class: "num", text: String(r[1]) })));
    });
    if (!rows.length) t.appendChild(el("tr", null, el("td", { class: "empty", text: "None found." })));
    return t;
  }

  /* ---------- overview ---------- */

  function overview() {
    $main.textContent = "";
    $main.appendChild(el("h1", { text: DATA.meta.name }));
    $main.appendChild(el("div", { class: "meta", text: "generated " + DATA.meta.generated + " by callscape " + DATA.meta.version }));
    var cards = el("div", { class: "cards" });
    function card(n, label) { cards.appendChild(el("div", { class: "card" }, el("b", { text: String(n) }), el("span", { text: label }))); }
    card(STATS.files, "files");
    card(STATS.symbols, "symbols");
    card(STATS.edges, "edges");
    var pct = STATS.call_sites ? Math.round(100 * STATS.call_sites_resolved / STATS.call_sites) : 0;
    card(pct + "%", "call sites resolved to repo code (" + STATS.call_sites_resolved + " of " + STATS.call_sites + ")");
    card(STATS.cycles.length, "call cycles");
    $main.appendChild(cards);
    var langs = Object.keys(STATS.files_by_language).map(function (k) { return STATS.files_by_language[k] + " " + k; });
    var kinds = Object.keys(STATS.symbols_by_kind).map(function (k) { return STATS.symbols_by_kind[k] + " " + k; });
    $main.appendChild(el("p", { class: "meta", text: langs.join(", ") + "  |  " + kinds.join(", ") }));

    $main.appendChild(el("h2", { text: "Most called" }));
    $main.appendChild(symTable(STATS.most_called));
    $main.appendChild(el("h2", { text: "Calls the most distinct functions" }));
    $main.appendChild(symTable(STATS.most_calling));
    $main.appendChild(el("h2", { text: "Never called from the repository (" + STATS.entry_points.length + ")" }));
    var entry = STATS.entry_points.slice().sort(sortSyms).slice(0, 60).map(function (i) { return [i, SYMS[i].y]; });
    $main.appendChild(symTable(entry));
    if (STATS.entry_points.length > 60) $main.appendChild(el("div", { class: "note", text: "Showing 60 of " + STATS.entry_points.length + ". Use the search box for the rest." }));
    if (STATS.cycles.length) {
      $main.appendChild(el("h2", { text: "Call cycles" }));
      var ul = el("ul", { class: "rel" });
      STATS.cycles.slice(0, 20).forEach(function (c) {
        var li = el("li");
        c.slice(0, 8).forEach(function (i, n) {
          if (n) li.appendChild(document.createTextNode(" → "));
          li.appendChild(el("a", { href: href(i), class: "nm", text: SYMS[i].q }));
        });
        if (c.length > 8) li.appendChild(el("span", { class: "loc", text: "+" + (c.length - 8) + " more" }));
        ul.appendChild(li);
      });
      $main.appendChild(ul);
    }
    if (STATS.files_with_syntax_errors.length) {
      $main.appendChild(el("h2", { text: "Files with syntax errors (parsed best-effort)" }));
      $main.appendChild(el("div", { class: "note", text: STATS.files_with_syntax_errors.join(", ") }));
    }
    if (DATA.meta.skipped.length) {
      $main.appendChild(el("h2", { text: "Skipped files" }));
      $main.appendChild(el("div", { class: "note", text: DATA.meta.skipped.map(function (s) { return s[0] + " (" + s[1] + ")"; }).join(", ") }));
    }
  }

  /* ---------- source view ---------- */

  function openMenu(ev, targets) {
    $menu.textContent = "";
    targets.forEach(function (t) {
      var s = SYMS[t];
      $menu.appendChild(el("a", { href: href(t) }, s.q, el("small", { text: loc(s) })));
    });
    $menu.hidden = false;
    var x = Math.min(ev.clientX, window.innerWidth - 300);
    var y = Math.min(ev.clientY + 8, window.innerHeight - 160);
    $menu.style.left = Math.max(8, x) + "px";
    $menu.style.top = Math.max(8, y) + "px";
  }

  function sourceView(s) {
    var lines = s.b.split("\n");
    var byLine = {};
    s.r.forEach(function (r) { (byLine[r[0]] = byLine[r[0]] || []).push(r); });
    var pre = el("pre", { class: "code" });
    lines.forEach(function (text, i) {
      var row = el("span", { class: "ln", id: "L" + (s.bs + i) }, el("i", { text: String(s.bs + i) }));
      var refs = (byLine[i] || []).slice().sort(function (a, b) { return a[1] - b[1]; });
      var chars = Array.from(text);
      var pos = 0;
      refs.forEach(function (r) {
        if (r[1] < pos) return;
        row.appendChild(document.createTextNode(chars.slice(pos, r[1]).join("")));
        var label = chars.slice(r[1], r[2]).join("");
        var a = el("a", { class: "r k-" + r[4], href: href(r[3][0]), title: KIND_NAME[r[4]] + (r[5] ? " (several candidates)" : "") });
        a.textContent = label;
        if (r[3].length > 1) {
          a.addEventListener("click", function (ev) { ev.preventDefault(); ev.stopPropagation(); openMenu(ev, r[3]); });
        }
        row.appendChild(a);
        pos = r[2];
      });
      row.appendChild(document.createTextNode(chars.slice(pos).join("") || " "));
      pre.appendChild(row);
    });
    var box = el("div", null, pre);
    if (s.t) box.appendChild(el("div", { class: "note", text: "Truncated: only the first " + lines.length + " lines are shown. Re-run with a larger --max-body-lines to see more." }));
    box.appendChild(el("div", { class: "legend" },
      el("span", { class: "c", text: "call" }), " / ", el("span", { class: "t", text: "type" }), " / ",
      el("span", { class: "r", text: "passed as a value" }),
      " – click an underlined name to jump to its definition."));
    return box;
  }

  /* ---------- neighbourhood graph ---------- */

  var GRAPH_KINDS = ["c", "r"];
  var COL_W = 210, NODE_W = 190, NODE_H = 26, ROW_H = 34, MAX_PER_COL = 14;

  function neighbours(idx, dir) {
    var s = SYMS[idx];
    var edges = dir === "out" ? s.o : s.c;
    var out = [];
    edges.forEach(function (e) { if (GRAPH_KINDS.indexOf(e[1]) >= 0 && e[0] !== idx) out.push([e[0], e[1]]); });
    return out;
  }

  function layers(idx, dir, depth) {
    var seen = {}; seen[idx] = true;
    var cols = [];
    var frontier = [idx];
    for (var d = 1; d <= depth; d++) {
      var col = [];
      frontier.forEach(function (from) {
        neighbours(from, dir).forEach(function (n) {
          if (seen[n[0]]) return;
          seen[n[0]] = true;
          col.push({ idx: n[0], from: from, kind: n[1] });
        });
      });
      cols.push(col);
      frontier = col.map(function (c) { return c.idx; });
    }
    return cols;
  }

  function svg(tag, attrs) {
    var n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    return n;
  }

  function graphView(idx) {
    var wrap = el("div");
    var tools = el("div", { class: "graph-tools" }, "Neighbourhood depth:");
    [1, 2, 3].forEach(function (d) {
      tools.appendChild(el("button", { class: d === graphDepth ? "on" : "", text: String(d), onclick: function () { graphDepth = d; render(idx); } }));
    });
    wrap.appendChild(tools);
    var left = layers(idx, "in", graphDepth), right = layers(idx, "out", graphDepth);
    var colsL = left.length, colsR = right.length;
    var any = left.some(function (c) { return c.length; }) || right.some(function (c) { return c.length; });
    if (!any) {
      wrap.appendChild(el("div", { class: "empty", text: "No calls to or from this symbol were found in the repository." }));
      return wrap;
    }
    var pos = {};
    var nodes = [];
    var rows = 1;
    function place(cols, side) {
      cols.forEach(function (col, ci) {
        var shown = col.slice(0, MAX_PER_COL);
        var x = side < 0 ? (colsL - 1 - ci) * COL_W : (colsL + 1 + ci) * COL_W;
        shown.forEach(function (c, r) { pos[c.idx + ":" + side] = { x: x, row: r }; nodes.push({ idx: c.idx, x: x, row: r }); });
        if (col.length > MAX_PER_COL) nodes.push({ more: col.length - MAX_PER_COL, x: x, row: MAX_PER_COL });
        rows = Math.max(rows, Math.min(col.length, MAX_PER_COL) + (col.length > MAX_PER_COL ? 1 : 0));
      });
    }
    place(left, -1); place(right, 1);
    var centreX = colsL * COL_W;
    var height = rows * ROW_H + 16;
    var width = (colsL + colsR + 1) * COL_W;
    var cy = Math.floor((rows - 1) / 2);
    var root = svg("svg", { width: width, height: height, viewBox: "0 0 " + width + " " + height });
    var defs = svg("defs");
    var marker = svg("marker", { id: "arr", markerWidth: 8, markerHeight: 8, refX: 7, refY: 4, orient: "auto" });
    marker.appendChild(svg("path", { d: "M0,0 L8,4 L0,8 z" }));
    defs.appendChild(marker);
    root.appendChild(defs);
    function ny(row) { return 8 + row * ROW_H; }
    function edge(x1, row1, x2, row2, kind) {
      var y1 = ny(row1) + NODE_H / 2, y2 = ny(row2) + NODE_H / 2;
      var mx = (x1 + x2) / 2;
      root.appendChild(svg("path", { class: "edge " + (kind === "r" ? "ref" : ""), d: "M" + x1 + "," + y1 + " C" + mx + "," + y1 + " " + mx + "," + y2 + " " + x2 + "," + y2, "marker-end": "url(#arr)" }));
    }
    left.forEach(function (col, ci) {
      col.slice(0, MAX_PER_COL).forEach(function (c) {
        var a = pos[c.idx + ":-1"];
        var b = c.from === idx ? { x: centreX, row: cy } : pos[c.from + ":-1"];
        if (a && b) edge(a.x + NODE_W, a.row, b.x, b.row, c.kind);
      });
    });
    right.forEach(function (col) {
      col.slice(0, MAX_PER_COL).forEach(function (c) {
        var a = c.from === idx ? { x: centreX, row: cy } : pos[c.from + ":1"];
        var b = pos[c.idx + ":1"];
        if (a && b) edge(a.x + NODE_W, a.row, b.x, b.row, c.kind);
      });
    });
    function node(n) {
      var g = svg("g", { class: "node" + (n.more ? " more" : "") + (n.center ? " center" : "") });
      g.appendChild(svg("rect", { x: n.x, y: ny(n.row), width: NODE_W, height: NODE_H, rx: 5 }));
      var label = n.more ? "+" + n.more + " more" : SYMS[n.idx].q;
      if (label.length > 27) label = label.slice(0, 12) + "…" + label.slice(-14);
      var t = svg("text", { x: n.x + 8, y: ny(n.row) + 17 });
      t.textContent = label;
      g.appendChild(t);
      if (!n.more) {
        var title = svg("title");
        title.textContent = SYMS[n.idx].q + "  " + loc(SYMS[n.idx]);
        g.appendChild(title);
        if (!n.center) g.addEventListener("click", function () { go(n.idx); });
      }
      root.appendChild(g);
    }
    nodes.forEach(node);
    node({ idx: idx, x: centreX, row: cy, center: true });
    var box = el("div", { class: "graph-box" });
    box.appendChild(root);
    wrap.appendChild(box);
    wrap.appendChild(el("div", { class: "legend", text: "Callers on the left, callees on the right. Dashed lines are functions passed as values rather than called directly." }));
    return wrap;
  }

  /* ---------- symbol page ---------- */

  function symbolPage(idx) {
    var s = SYMS[idx];
    $main.textContent = "";
    var title = s.q === "<module>" ? "(top-level code) " + FILES[s.f].p : s.q;
    $main.appendChild(el("h1", { text: title }));
    $main.appendChild(el("div", { class: "meta" },
      el("span", { class: "badge " + s.k, text: s.k }), " " + s.l + "  " + FILES[s.f].p + ":" + s.s + (s.e > s.s ? "-" + s.e : "")));
    if (s.g && s.k !== "module") $main.appendChild(el("div", { class: "sig", text: s.g }));
    if (s.d) $main.appendChild(el("div", { class: "doc", text: s.d }));

    $main.appendChild(el("h2", { text: "Call graph" }));
    $main.appendChild(graphView(idx));

    $main.appendChild(el("h2", { text: "Source" }));
    $main.appendChild(sourceView(s));

    var lists = el("div", { class: "lists" });
    lists.appendChild(relList("Called by", s.c, ["c", "r"], "Nothing in the repository calls this."));
    lists.appendChild(relList("Calls", s.o, ["c", "r"], "No calls into repository code."));
    lists.appendChild(relList("Uses types", s.o, ["t"], "No repository types used."));
    lists.appendChild(relList("Used as a type by", s.c, ["t"], "Not used as a type elsewhere."));
    if (s.m && s.m.length) {
      var box = el("div", null, el("h2", { text: "Members (" + s.m.length + ")" }));
      var ul = el("ul", { class: "rel" });
      s.m.slice().sort(sortSyms).forEach(function (m) { ul.appendChild(relRow(m)); });
      box.appendChild(ul);
      lists.appendChild(box);
    }
    $main.appendChild(lists);
  }

  /* ---------- routing ---------- */

  function render(idx) {
    if (idx == null) { buildSidebar(null); overview(); document.title = "callscape: " + DATA.meta.name; return; }
    var s = SYMS[idx];
    if (!s) { overview(); return; }
    buildSidebar(idx);
    symbolPage(idx);
    document.title = s.q + " – " + DATA.meta.name;
    $main.scrollTop = 0;
  }

  function route() {
    $menu.hidden = true;
    var m = /^#s=(\d+)$/.exec(location.hash);
    render(m ? parseInt(m[1], 10) : null);
  }

  document.getElementById("repo-name").textContent = DATA.meta.name;
  window.addEventListener("hashchange", function () { $search.value = ""; route(); });
  document.addEventListener("click", function (ev) { if (!$menu.contains(ev.target)) $menu.hidden = true; });
  $search.addEventListener("input", function () { runSearch($search.value); });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "/" && document.activeElement !== $search) { ev.preventDefault(); $search.focus(); }
    else if (ev.key === "Escape") { $menu.hidden = true; $search.value = ""; $search.blur(); route(); }
  });
  route();
})();
