/* 양안 뉴스 트래커 — 프런트엔드. 번들러 없음, 의존성 없음. */
(function () {
  "use strict";

  var state = {
    events: [],
    tension: null,
    sources: null,
    meta: null,
    sort: "recent",
    grade: "all",
    query: "",
    archive: { month: "", query: "", events: [], cache: {} }
  };

  // ---------------------------------------------------------------- 유틸
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === "class") node.className = attrs[k];
        else if (k === "text") node.textContent = attrs[k];
        else if (k === "html") node.innerHTML = attrs[k];
        else if (attrs[k] !== null && attrs[k] !== undefined) node.setAttribute(k, attrs[k]);
      });
    }
    (children || []).forEach(function (c) { if (c) node.appendChild(c); });
    return node;
  }

  function svgEl(tag, attrs) {
    var node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (attrs[k] !== null && attrs[k] !== undefined) node.setAttribute(k, attrs[k]);
    });
    return node;
  }

  function fmtDate(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return iso;
    return d.getFullYear() + "." + pad(d.getMonth() + 1) + "." + pad(d.getDate());
  }
  function fmtDateTime(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return iso;
    return fmtDate(iso) + " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }
  function pad(n) { return (n < 10 ? "0" : "") + n; }

  function relative(iso) {
    var diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (isNaN(diff)) return "";
    if (diff < 3600) return Math.max(1, Math.round(diff / 60)) + "분 전";
    if (diff < 86400) return Math.round(diff / 3600) + "시간 전";
    return Math.round(diff / 86400) + "일 전";
  }

  var LANG_LABEL = { en: "EN", ko: "KO", zh: "ZH", ja: "JA" };

  function getJSON(url) {
    return fetch(url, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error(url + " → HTTP " + r.status);
      return r.json();
    });
  }

  // ------------------------------------------------------------ 테마 전환
  function initTheme() {
    var saved = null;
    try { saved = localStorage.getItem("tst-theme"); } catch (e) { /* 사생활 보호 모드 */ }
    if (saved) document.documentElement.setAttribute("data-theme", saved);
    updateThemeIcon();
    $("#theme-toggle").addEventListener("click", function () {
      var now = document.documentElement.getAttribute("data-theme");
      if (!now) {
        var dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        now = dark ? "dark" : "light";
      }
      var next = now === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("tst-theme", next); } catch (e) { /* 무시 */ }
      updateThemeIcon();
      renderTension();  // SVG 는 CSS 변수를 계산값으로 굳혀 쓰므로 다시 그린다
    });
  }

  function updateThemeIcon() {
    var theme = document.documentElement.getAttribute("data-theme");
    var dark = theme ? theme === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    $("[data-theme-icon]").textContent = dark ? "☀" : "☾";
  }

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  // ------------------------------------------------------------ 사건 카드
  function gradeBadge(cred) {
    return el("span", { class: "badge", "data-grade": cred.grade, title: cred.score + "점" }, [
      el("span", { text: cred.grade }),
      el("span", { text: cred.grade_label })
    ]);
  }

  function eventCard(event) {
    var cred = event.credibility;

    var title = el("h3", { class: "event-title" }, [
      el("a", { href: event.headline_url, target: "_blank", rel: "noopener noreferrer", text: event.headline })
    ]);

    var meta = el("p", { class: "event-meta" }, [
      el("span", { text: event.headline_source }),
      el("span", { text: fmtDateTime(event.last_seen) + " (" + relative(event.last_seen) + ")" }),
      el("span", { text: cred.n_articles + "개 기사" })
    ]);
    if (event.cross_language) {
      meta.appendChild(el("span", { class: "tag-cross", text: "교차언어 " + event.langs.map(function (l) { return LANG_LABEL[l] || l; }).join("·") }));
    }

    var reasons = el("p", { class: "reasons" },
      cred.reasons.map(function (r) { return el("span", { text: r }); }));

    var seen = {};
    var chips = el("div", { class: "chips" });
    event.articles.forEach(function (a) {
      if (seen[a.source_name]) return;
      seen[a.source_name] = 1;
      chips.appendChild(el("span", {
        class: "src-chip",
        "data-bloc": a.bloc,
        title: a.tier_label + (a.bias ? " — " + a.bias : ""),
        text: a.source_name
      }));
    });

    var rows = event.articles.map(function (a) {
      return el("div", { class: "article-row" }, [
        el("span", { class: "lang", text: LANG_LABEL[a.lang] || a.lang }),
        el("span", { class: "src", text: a.source_name }),
        el("span", {}, [
          el("a", { href: a.url, target: "_blank", rel: "noopener noreferrer", text: a.title }),
          a.bias ? el("span", { class: "bias-note", text: " — " + a.bias }) : null
        ])
      ]);
    });

    var details = el("details", {}, [
      el("summary", { text: "기사 " + event.articles.length + "건 전체 보기" })
    ].concat(rows));

    return el("article", { class: "event" }, [
      el("div", { class: "event-top" }, [gradeBadge(cred), el("div", {}, [title, meta])]),
      reasons, chips, details
    ]);
  }

  function matchesQuery(event, query) {
    if (!query) return true;
    var q = query.toLowerCase();
    if (event.headline.toLowerCase().indexOf(q) >= 0) return true;
    return event.articles.some(function (a) {
      return a.title.toLowerCase().indexOf(q) >= 0 ||
        (a.source_name || "").toLowerCase().indexOf(q) >= 0;
    });
  }

  function renderEvents() {
    var list = $("#events-list");
    list.textContent = "";

    var items = state.events.filter(function (e) {
      if (state.grade !== "all" && e.credibility.grade !== state.grade) return false;
      return matchesQuery(e, state.query);
    });

    if (state.sort === "credibility") {
      items = items.slice().sort(function (a, b) {
        return b.credibility.score - a.credibility.score ||
          (a.last_seen < b.last_seen ? 1 : -1);
      });
    }

    $("#events-count").textContent = items.length + "건" +
      (items.length !== state.events.length ? " (전체 " + state.events.length + "건 중)" : "");

    if (!items.length) {
      list.appendChild(el("p", {
        class: "empty",
        text: state.events.length
          ? "조건에 맞는 사건이 없음."
          : "아직 수집된 사건이 없음. 수집기를 한 번 실행하면 채워진다."
      }));
      return;
    }
    items.forEach(function (e) { list.appendChild(eventCard(e)); });
  }

  // -------------------------------------------------------------- 차트
  // 막대 + 기준선. 90일 정도의 작은 데이터라 라이브러리를 쓰지 않는다.
  function barChart(host, opts) {
    host.textContent = "";
    var data = opts.data;
    if (!data.length) {
      host.appendChild(el("p", { class: "empty", text: "표시할 데이터가 없음." }));
      return;
    }

    var W = 1000, H = opts.height || 240;
    var m = { top: 14, right: 12, bottom: 26, left: 40 };
    var iw = W - m.left - m.right;
    var ih = H - m.top - m.bottom;

    var maxVal = Math.max.apply(null, data.map(function (d) { return d.value; }));
    if (opts.line) maxVal = Math.max(maxVal, Math.max.apply(null, opts.line));
    maxVal = Math.max(maxVal, 1);
    var top = niceCeil(maxVal);

    var slot = iw / data.length;
    var barW = Math.max(1, slot - 2);   // 표면 간격 2px
    var y = function (v) { return m.top + ih - (v / top) * ih; };

    var svg = svgEl("svg", {
      viewBox: "0 0 " + W + " " + H,
      role: "img",
      "aria-label": opts.ariaLabel || ""
    });

    // 가로 격자 — 눈에 띄지 않게
    var ticks = [0, top / 2, top];
    ticks.forEach(function (t) {
      svg.appendChild(svgEl("line", {
        class: t === 0 ? "baseline" : "gridline",
        x1: m.left, x2: W - m.right, y1: y(t), y2: y(t)
      }));
      var label = svgEl("text", { class: "tick tick-num", x: m.left - 7, y: y(t) + 4, "text-anchor": "end" });
      label.textContent = Math.round(t);
      svg.appendChild(label);
    });

    // 막대
    data.forEach(function (d, i) {
      var h = Math.max(d.value > 0 ? 2 : 0, (d.value / top) * ih);
      var rect = svgEl("rect", {
        x: m.left + i * slot + (slot - barW) / 2,
        y: m.top + ih - h,
        width: barW,
        height: h,
        rx: Math.min(4, barW / 2),
        fill: opts.color
      });
      svg.appendChild(rect);
    });

    // 기준선(이동중앙값)
    if (opts.line) {
      var pts = [];
      opts.line.forEach(function (v, i) {
        if (v === null || v === undefined) return;
        pts.push((m.left + i * slot + slot / 2).toFixed(1) + "," + y(v).toFixed(1));
      });
      if (pts.length > 1) {
        svg.appendChild(svgEl("polyline", {
          points: pts.join(" "),
          fill: "none",
          stroke: opts.lineColor,
          "stroke-width": 2,
          "stroke-linejoin": "round",
          "stroke-linecap": "round"
        }));
      }
    }

    // x축 눈금 — 월이 바뀌는 날에만. 창 시작이 월말이면 첫 두 라벨이 붙으므로
    // 최소 간격을 두고 건너뛴다.
    var lastMonth = null, lastX = -Infinity;
    data.forEach(function (d, i) {
      var month = d.date.slice(0, 7);
      if (month === lastMonth) return;
      lastMonth = month;
      var x = m.left + i * slot + slot / 2;
      if (x - lastX < 42) return;
      lastX = x;
      var t = svgEl("text", {
        class: "tick",
        x: x,
        y: H - 8,
        "text-anchor": "middle"
      });
      t.textContent = Number(d.date.slice(5, 7)) + "월";
      svg.appendChild(t);
    });

    // 마우스 위치 대응 — 막대보다 넓은 히트 영역
    var tip = el("div", { class: "chart-tip" });
    host.appendChild(svg);
    host.appendChild(tip);

    var hover = svgEl("rect", {
      x: m.left, y: m.top, width: iw, height: ih, fill: "transparent"
    });
    svg.appendChild(hover);

    var marker = svgEl("rect", {
      y: m.top, width: 2, height: ih, fill: cssVar("--text-muted"), opacity: 0
    });
    svg.appendChild(marker);

    function onMove(evt) {
      var box = svg.getBoundingClientRect();
      var px = (evt.clientX - box.left) / box.width * W;
      var idx = Math.floor((px - m.left) / slot);
      if (idx < 0 || idx >= data.length) return onLeave();
      var d = data[idx];
      marker.setAttribute("x", m.left + idx * slot + slot / 2 - 1);
      marker.setAttribute("opacity", 0.35);
      tip.innerHTML = "";
      tip.appendChild(el("div", { class: "tip-date", text: d.date }));
      tip.appendChild(el("div", { html: opts.tipHtml(d) }));
      tip.classList.add("on");
      var hostBox = host.getBoundingClientRect();
      var left = evt.clientX - hostBox.left + host.scrollLeft + 12;
      if (left + tip.offsetWidth > host.scrollLeft + hostBox.width) {
        left = evt.clientX - hostBox.left + host.scrollLeft - tip.offsetWidth - 12;
      }
      tip.style.left = Math.max(0, left) + "px";
      tip.style.top = "8px";
    }
    function onLeave() {
      tip.classList.remove("on");
      marker.setAttribute("opacity", 0);
    }
    svg.addEventListener("mousemove", onMove);
    svg.addEventListener("mouseleave", onLeave);
  }

  function niceCeil(v) {
    var mag = Math.pow(10, Math.floor(Math.log10(v)));
    return Math.ceil(v / (mag / 2)) * (mag / 2);
  }

  function renderTension() {
    var t = state.tension;
    var tiles = $("#tension-tiles");
    tiles.textContent = "";
    if (!t || !t.records || !t.records.length) {
      tiles.appendChild(el("p", { class: "empty", text: "국방부 집계 데이터가 아직 없음." }));
      return;
    }

    var recs = t.records;
    var last = recs[recs.length - 1];
    var recent = recs.slice(-90);

    function tile(k, v, sub) {
      return el("div", { class: "tile" }, [
        el("div", { class: "k", text: k }),
        el("div", { class: "v", text: v }),
        el("div", { class: "sub", text: sub || "" })
      ]);
    }

    var ratioText = last.ratio ? last.ratio + "배" : "—";
    var ratioSub = last.ratio
      ? (last.ratio >= 1.5 ? "평소보다 뚜렷이 높음" : last.ratio >= 1.1 ? "평소보다 다소 높음"
        : last.ratio <= 0.7 ? "평소보다 낮음" : "평소 수준")
      : "기준선 계산에 14일 필요";

    tiles.appendChild(tile("최신 지수", String(last.index), last.date + " 기준"));
    tiles.appendChild(tile("평소 대비", ratioText, ratioSub));
    tiles.appendChild(tile("항공기 소티", String(last.aircraft), "직전 24시간"));
    tiles.appendChild(tile("해군 함정", String(last.navy_ships), "직전 24시간"));
    tiles.appendChild(tile("중간선 통과", String(last.crossed_median), "소티 기준"));

    var legend = $("#tension-legend");
    legend.textContent = "";
    legend.appendChild(el("span", { class: "legend-item" }, [
      el("span", { class: "legend-swatch", style: "background:" + cssVar("--series-1") }),
      el("span", { text: "일일 지수" })
    ]));
    legend.appendChild(el("span", { class: "legend-item" }, [
      el("span", { class: "legend-swatch line", style: "background:" + cssVar("--text-secondary") }),
      el("span", { text: "직전 90일 중앙값" })
    ]));

    barChart($("#chart-tension"), {
      data: recent.map(function (r) { return { date: r.date, value: r.index, raw: r }; }),
      line: recent.map(function (r) { return r.baseline; }),
      color: cssVar("--series-1"),
      lineColor: cssVar("--text-secondary"),
      height: 240,
      ariaLabel: "최근 " + recent.length + "일간 일일 긴장도 지수 막대그래프. 표로 보기 제공.",
      tipHtml: function (d) {
        var r = d.raw;
        return "지수 <b>" + r.index + "</b>" +
          (r.ratio ? " (평소 대비 <b>" + r.ratio + "배</b>)" : "") +
          "<br>항공기 <b>" + r.aircraft + "</b> · 함정 <b>" + r.navy_ships +
          "</b> · 관공선 <b>" + r.official_ships + "</b>";
      }
    });

    barChart($("#chart-crossed"), {
      data: recent.map(function (r) { return { date: r.date, value: r.crossed_median, raw: r }; }),
      color: cssVar("--series-2"),
      height: 170,
      ariaLabel: "최근 " + recent.length + "일간 해협 중간선 통과 소티 막대그래프. 표로 보기 제공.",
      tipHtml: function (d) {
        return "중간선 통과 <b>" + d.raw.crossed_median + "</b> 소티<br>" +
          "당일 총 항공기 <b>" + d.raw.aircraft + "</b> 소티";
      }
    });

    renderTensionTable(recs.slice(-60).reverse());
  }

  function renderTensionTable(rows) {
    var host = $("#tension-table");
    host.textContent = "";
    var head = ["날짜", "지수", "평소 대비", "항공기", "함정", "관공선", "중간선 통과", "기구"];
    var table = el("table", {}, [
      el("thead", {}, [el("tr", {}, head.map(function (h) { return el("th", { text: h }); }))])
    ]);
    var body = el("tbody", {});
    rows.forEach(function (r) {
      body.appendChild(el("tr", {}, [
        el("td", { text: r.date }),
        el("td", { text: String(r.index) }),
        el("td", { text: r.ratio ? r.ratio + "배" : "—" }),
        el("td", { text: String(r.aircraft) }),
        el("td", { text: String(r.navy_ships) }),
        el("td", { text: String(r.official_ships) }),
        el("td", { text: String(r.crossed_median) }),
        el("td", { text: String(r.balloons || 0) })
      ]));
    });
    table.appendChild(body);
    host.appendChild(table);
  }

  // -------------------------------------------------------- 관점 대조
  function miniRow(a) {
    return el("div", { class: "mini-row" }, [
      el("a", { href: a.url, target: "_blank", rel: "noopener noreferrer", text: a.title }),
      el("div", { class: "mini-meta", text: a.source_name + " · " + fmtDate(a.published) + (a.bias ? " · " + a.bias : "") })
    ]);
  }

  function renderPerspective() {
    var prc = [], other = [], shared = [];
    var seen = {};

    state.events.forEach(function (e) {
      if (e.perspectives.prc.length && e.perspectives.tw_west.length) shared.push(e);
      e.articles.forEach(function (a) {
        if (seen[a.id]) return;
        seen[a.id] = 1;
        (a.bloc === "prc_state" ? prc : other).push(a);
      });
    });

    function byDate(a, b) { return a.published < b.published ? 1 : -1; }
    prc.sort(byDate);
    other.sort(byDate);

    var block = $("#shared-events");
    block.textContent = "";
    if (shared.length) {
      var wrap = el("div", { class: "shared-block" }, [
        el("h2", { text: "양측이 같은 사건을 보도한 경우 (" + shared.length + "건)" })
      ]);
      shared.slice(0, 6).forEach(function (e) { wrap.appendChild(eventCard(e)); });
      block.appendChild(wrap);
    } else {
      block.appendChild(el("p", { class: "empty" }, [
        el("span", { text: "현재 수집분에서 양측이 같은 사건을 보도한 사례는 없음. 드문 일이 아니라 기본값에 가깝다 — 두 진영은 애초에 서로 다른 것을 기사로 만든다." })
      ]));
    }

    fillMini($("#persp-prc"), prc, "중국 관영 기사가 아직 없음.");
    fillMini($("#persp-other"), other, "기사가 아직 없음.");
  }

  function fillMini(host, items, emptyText) {
    host.textContent = "";
    if (!items.length) {
      host.appendChild(el("p", { class: "empty", text: emptyText }));
      return;
    }
    items.slice(0, 40).forEach(function (a) { host.appendChild(miniRow(a)); });
  }

  // ------------------------------------------------------------ 아카이브
  function initArchive() {
    var select = $("#archive-month");
    var months = (state.meta && state.meta.archive_months) || [];
    if (!months.length) {
      select.appendChild(el("option", { value: "", text: "아카이브 없음" }));
      $("#archive-list").appendChild(el("p", { class: "empty", text: "아직 쌓인 아카이브가 없음. 수집이 반복될수록 채워진다." }));
      return;
    }
    months.slice().reverse().forEach(function (m) {
      select.appendChild(el("option", { value: m, text: m.replace("-", "년 ") + "월" }));
    });
    state.archive.month = months[months.length - 1];
    select.value = state.archive.month;
    select.addEventListener("change", function () {
      state.archive.month = select.value;
      loadArchive();
    });
    $("#archive-search").addEventListener("input", function (e) {
      state.archive.query = e.target.value.trim();
      renderArchive();
    });
    loadArchive();
  }

  function loadArchive() {
    var month = state.archive.month;
    if (!month) return;
    if (state.archive.cache[month]) {
      state.archive.events = state.archive.cache[month];
      return renderArchive();
    }
    $("#archive-list").textContent = "";
    $("#archive-count").textContent = "불러오는 중…";
    getJSON("data/archive/" + month + ".json").then(function (data) {
      state.archive.cache[month] = data.events || [];
      state.archive.events = state.archive.cache[month];
      renderArchive();
    }).catch(function (err) {
      $("#archive-count").textContent = "";
      $("#archive-list").textContent = "";
      $("#archive-list").appendChild(el("div", { class: "error-box", text: "아카이브를 불러오지 못함: " + err.message }));
    });
  }

  function renderArchive() {
    var list = $("#archive-list");
    list.textContent = "";
    var items = state.archive.events.filter(function (e) { return matchesQuery(e, state.archive.query); });
    $("#archive-count").textContent = items.length + "건";
    if (!items.length) {
      list.appendChild(el("p", { class: "empty", text: "조건에 맞는 사건이 없음." }));
      return;
    }
    items.forEach(function (e) { list.appendChild(eventCard(e)); });
  }

  // ---------------------------------------------------------------- 푸터
  function renderFooter() {
    var meta = state.meta || {};

    var rules = $("#grade-rules");
    rules.textContent = "";
    ((state.sources && state.sources.grade_rules) || []).forEach(function (r) {
      rules.appendChild(el("div", { class: "rule-row" }, [
        el("span", { class: "badge", "data-grade": r.grade }, [
          el("span", { text: r.grade }), el("span", { text: r.label })
        ]),
        el("span", { class: "rule-text", text: r.rule })
      ]));
    });

    var table = $("#source-table");
    table.textContent = "";
    ((state.sources && state.sources.tiers) || []).forEach(function (tier) {
      if (!tier.sources.length) return;
      var chips = el("div", { class: "tier-sources" });
      tier.sources.forEach(function (s) {
        chips.appendChild(el("span", {
          class: "s",
          title: (s.bias || "") + (s.bias ? " — " : "") + s.bloc_label,
          text: s.name
        }));
      });
      table.appendChild(el("div", { class: "tier-block" }, [
        el("div", { class: "tier-head", text: tier.tier + " " + tier.label + " (가중치 " + tier.weight + ")" }),
        chips
      ]));
    });

    var feeds = $("#feed-status");
    feeds.textContent = "";
    (meta.feeds || []).forEach(function (f) {
      var cls = f.status === "error" ? "dot-bad" : (f.status === "empty" ? "dot-warn" : "dot-ok");
      var msg = f.status === "error" ? f.error
        : f.status === "not_modified" ? "변경 없음"
          : f.n_entries + "개 항목";
      feeds.appendChild(el("div", { class: "feed-row" }, [
        el("span", { class: "dot " + cls }),
        el("span", { class: "fname", text: f.name }),
        el("span", { class: "fmsg", text: msg })
      ]));
    });
    if (meta.tension_error) {
      feeds.appendChild(el("div", { class: "feed-row" }, [
        el("span", { class: "dot dot-bad" }),
        el("span", { class: "fname", text: "대만 국방부 스크래핑" }),
        el("span", { class: "fmsg", text: meta.tension_error + " — 기존 데이터 유지" })
      ]));
    }

    $("#foot-meta").textContent = meta.updated
      ? "마지막 수집 " + fmtDateTime(meta.updated) + " · 소요 " + meta.duration_sec + "초 · 사건 " + meta.n_events + "건 · 기사 " + meta.n_articles + "건"
      : "";
  }

  function renderHeadStats() {
    var host = $("#head-stats");
    host.textContent = "";
    var meta = state.meta || {};
    var grades = meta.grades || {};
    var last = state.tension && state.tension.records && state.tension.records.length
      ? state.tension.records[state.tension.records.length - 1] : null;

    function stat(label, value) {
      return el("span", {}, [document.createTextNode(label + " "), el("b", { text: value })]);
    }
    host.appendChild(stat("사건", String(meta.n_events || state.events.length)));
    host.appendChild(stat("A 검증됨", String(grades.A || 0)));
    host.appendChild(stat("D 주의", String(grades.D || 0)));
    host.appendChild(stat("교차언어 사건", String(meta.cross_language_events || 0)));
    if (last) {
      host.appendChild(stat("긴장도 지수", last.index + (last.ratio ? " (평소 " + last.ratio + "배)" : "")));
    }
    if (meta.updated) host.appendChild(stat("갱신", relative(meta.updated)));
  }

  // ---------------------------------------------------------------- 탭
  var VIEWS = ["events", "tension", "perspective", "archive"];

  function showView(name) {
    if (VIEWS.indexOf(name) < 0) name = "events";
    $$(".tab").forEach(function (t) {
      t.setAttribute("aria-selected", String(t.dataset.view === name));
    });
    $$(".view").forEach(function (v) { v.hidden = true; });
    $("#view-" + name).hidden = false;
    if (name === "tension") renderTension();
  }

  function initTabs() {
    $$(".tab").forEach(function (tab) {
      tab.addEventListener("click", function () {
        // 해시로 남겨 화면을 그대로 공유할 수 있게 한다
        location.hash = tab.dataset.view;
      });
    });
    window.addEventListener("hashchange", function () {
      showView(location.hash.replace("#", ""));
    });
  }

  function initControls() {
    $$("[data-sort]").forEach(function (b) {
      b.addEventListener("click", function () {
        $$("[data-sort]").forEach(function (x) { x.classList.toggle("is-on", x === b); });
        state.sort = b.dataset.sort;
        renderEvents();
      });
    });
    $$("[data-grade]").forEach(function (b) {
      b.addEventListener("click", function () {
        $$("[data-grade]").forEach(function (x) { x.classList.toggle("is-on", x === b); });
        state.grade = b.dataset.grade;
        renderEvents();
      });
    });
    $("#events-search").addEventListener("input", function (e) {
      state.query = e.target.value.trim();
      renderEvents();
    });
  }

  // ---------------------------------------------------------------- 시작
  function boot() {
    initTheme();
    initTabs();
    initControls();

    Promise.all([
      getJSON("data/events.json").catch(function () { return { events: [] }; }),
      getJSON("data/tension.json").catch(function () { return { records: [] }; }),
      getJSON("data/sources.json").catch(function () { return {}; }),
      getJSON("data/build_meta.json").catch(function () { return {}; })
    ]).then(function (res) {
      state.events = res[0].events || [];
      state.tension = res[1];
      state.sources = res[2];
      state.meta = res[3];

      renderHeadStats();
      renderEvents();
      renderTension();
      renderPerspective();
      renderFooter();
      initArchive();
      showView(location.hash.replace("#", ""));
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
