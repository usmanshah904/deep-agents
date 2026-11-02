/* Small chart kit: DOM helper, tooltip, bars, share bar, line chart, stacked columns, meters.
   All text goes in through textContent (tool output can contain any text). */

const SVG_NS = "http://www.w3.org/2000/svg";

/* "Now": the snapshot time when the page runs from saved data, otherwise the real time. */
const nowMs = () => (window.SNAPSHOT ? window.SNAPSHOT.taken_ms : Date.now());

function h(tag, props = {}, children = []) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c === undefined || c === null || c === false) continue;
    el.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
  }
  return el;
}

function s(tag, attrs = {}, children = []) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null) continue;
    if (k === "text") el.textContent = v;
    else el.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c) el.appendChild(c);
  return el;
}

/* Inline icons (stroke icons, 24x24). */
const ICONS = {
  overview: "M3 13h8V3H3zM13 21h8V11h-8zM3 21h8v-6H3zM13 9h8V3h-8z",
  billing: "M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6",
  gke: "M12 2l8.5 5v10L12 22l-8.5-5V7zM12 22V12M20.5 7L12 12 3.5 7",
  bigquery: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5M8 11v3M11 9v5M14 12v2",
  compute: "M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01",
  storage: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  savings: "M19 5c-1.5 0-2.8 1.4-3 2-3.5-1.5-11-.3-11 5 0 1.8 0 3 2 4.5V20h4v-2h3v2h4v-4c1-.5 1.7-1 2-2h2v-4h-2c0-1-.5-1.5-1-2V5zM2 9v1c0 1.1.9 2 2 2h1",
  monitoring: "M22 12h-4l-3 9L9 3l-3 9H2",
  logging: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M8 13h8M8 17h8M8 9h2",
  agent: "M12 8V4H8M4 8h16v12H4zM2 14h2M20 14h2M9 13v2M15 13v2",
  alert: "M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  check: "M20 6L9 17l-5-5",
  chat: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
  copy: "M9 9h11v11H9zM5 15H4V4h11v1",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5",
  cloud: "M18 10h-1.3A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z",
  trend: "M23 6l-9.5 9.5-5-5L1 18M17 6h6v6",
  changes: "M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6",
  cpu: "M4 4h16v16H4zM9 9h6v6H9zM9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3",
};

function icon(name, cls) {
  const svg = s("svg", { viewBox: "0 0 24 24", "aria-hidden": "true", class: cls || "" });
  svg.appendChild(s("path", { d: ICONS[name] || ICONS.overview }));
  return svg;
}

/* Formatting */
const fmt = {
  money: (v) => "$" + Math.round(v).toLocaleString("en-US"),
  money2: (v) => "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 2 }),
  pct: (v) => (Math.round(v * 10) / 10).toLocaleString("en-US") + "%",
  num: (v) => Number(v).toLocaleString("en-US"),
  signedMoney: (v) => (v > 0 ? "+" : v < 0 ? "−" : "") + "$" + Math.abs(Math.round(v)).toLocaleString("en-US"),
  signedPct: (v) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toLocaleString("en-US") + "%",
  time: (iso) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
  dateTime: (iso) => new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }),
  ago: (iso) => {
    const m = Math.round((nowMs() - new Date(iso).getTime()) / 60000);
    if (m < 1) return "just now";
    if (m < 60) return m + " min ago";
    const hr = Math.floor(m / 60);
    return hr < 24 ? hr + " h ago" : Math.floor(hr / 24) + " d ago";
  },
};

const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const noMotion = () => prefersReducedMotion;

/* Count-up for big numbers */
function countUp(el, target, format) {
  if (noMotion()) { el.textContent = format(target); return; }
  const start = performance.now(), dur = 900;
  const step = (now) => {
    const t = Math.min(1, (now - start) / dur);
    const eased = 1 - Math.pow(1 - t, 3);
    el.textContent = format(target * eased);
    if (t < 1) requestAnimationFrame(step);
    else el.textContent = format(target);
  };
  requestAnimationFrame(step);
}

/* Tooltip */
const tip = {
  el: null,
  show(evt, title, rows) {
    this.el = this.el || document.getElementById("tooltip");
    this.el.replaceChildren();
    if (title) this.el.appendChild(h("div", { class: "tt-title", text: title }));
    for (const r of rows) {
      this.el.appendChild(h("div", { class: "tt-row" }, [
        r.color ? h("span", { class: "tt-key", style: { background: r.color } }) : null,
        h("span", { class: "tt-value", text: r.value }),
        r.label ? h("span", { class: "tt-label", text: r.label }) : null,
      ]));
    }
    this.el.classList.add("show");
    this.move(evt);
  },
  move(evt) {
    if (!this.el) return;
    let x, y;
    if (evt.clientX !== undefined && evt.type !== "focus") { x = evt.clientX; y = evt.clientY; }
    else { const r = evt.target.getBoundingClientRect(); x = r.left + r.width / 2; y = r.top; }
    const w = this.el.offsetWidth, hgt = this.el.offsetHeight;
    let left = x + 14, top = y - hgt - 10;
    if (left + w > window.innerWidth - 8) left = x - w - 14;
    if (top < 8) top = y + 18;
    this.el.style.left = left + "px";
    this.el.style.top = top + "px";
  },
  hide() { if (this.el) this.el.classList.remove("show"); },
};

function hoverable(el, getTip) {
  el.tabIndex = 0;
  const show = (e) => { const t = getTip(); tip.show(e, t.title, t.rows); };
  el.addEventListener("pointerenter", show);
  el.addEventListener("pointermove", (e) => tip.move(e));
  el.addEventListener("pointerleave", () => tip.hide());
  el.addEventListener("focus", show);
  el.addEventListener("blur", () => tip.hide());
  return el;
}

function animateWidth(el, pct) {
  const set = () => { el.style.width = pct + "%"; };
  if (noMotion()) set(); else requestAnimationFrame(() => requestAnimationFrame(set));
}

/* A label that links to a dashboard page when href is given (e.g. "#gke"). */
function labelLink(text, href) {
  return href ? h("a", { class: "svc-link", href, title: `Open ${text}`, text }) : text;
}

/* Horizontal bars. rows: {label, sub, value, color, display, tipLabel, href} */
function hbars(rows, opts = {}) {
  const max = opts.max || Math.max(...rows.map((r) => r.value), 1);
  const wrap = h("div", { class: "hbars" });
  rows.forEach((r) => {
    const fill = h("div", { class: "hbar-fill", style: { background: r.color || "var(--series-1)" } });
    const row = h("div", { class: "hbar" }, [
      h("div", { class: "hbar-label", title: r.label }, [labelLink(r.label, r.href), r.sub ? h("small", { text: r.sub }) : null]),
      h("div", { class: "hbar-track" }, [fill, h("span", { class: "hbar-value", text: r.display || fmt.money(r.value) })]),
    ]);
    hoverable(row, () => ({ title: r.label, rows: [{ value: r.display || fmt.money(r.value), label: r.tipLabel || "", color: r.color }] }));
    animateWidth(fill, Math.max(0.5, (r.value / max) * 100));
    wrap.appendChild(row);
  });
  return wrap;
}

/* Stacked horizontal bars. rows: {label, sub, parts: {key: value}}, keys: [{key, label, color}] */
function stackedHbars(rows, keys, opts = {}) {
  const total = (r) => keys.reduce((a, k) => a + (r.parts[k.key] || 0), 0);
  const max = opts.max || Math.max(...rows.map(total), 1);
  const wrap = h("div", {}, [legend(keys)]);
  const list = h("div", { class: "hbars" });
  rows.forEach((r) => {
    const t = total(r);
    const stack = h("div", { class: "hbar-stack" });
    keys.forEach((k) => {
      const v = r.parts[k.key] || 0;
      if (v > 0) stack.appendChild(h("span", { style: { flex: String(v), background: k.color } }));
    });
    const row = h("div", { class: "hbar" }, [
      h("div", { class: "hbar-label", title: r.label }, [r.label, r.sub ? h("small", { text: r.sub }) : null]),
      h("div", { class: "hbar-track" }, [stack, h("span", { class: "hbar-value", text: (opts.format || fmt.money)(t) })]),
    ]);
    hoverable(row, () => ({
      title: r.label,
      rows: keys.filter((k) => r.parts[k.key]).map((k) => ({ value: (opts.format || fmt.money)(r.parts[k.key]), label: k.label, color: k.color })),
    }));
    animateWidth(stack, Math.max(0.5, (t / max) * 100));
    list.appendChild(row);
  });
  wrap.appendChild(list);
  return wrap;
}

/* Paired bars (previous vs current). rows: {label, a, b} */
function pairedHbars(rows, keys) {
  const max = Math.max(...rows.flatMap((r) => [r.a, r.b]), 1);
  const wrap = h("div", {}, [legend(keys)]);
  const list = h("div", { class: "hbars" });
  rows.forEach((r) => {
    const fa = h("div", { class: "hbar-fill", style: { background: keys[0].color } });
    const fb = h("div", { class: "hbar-fill", style: { background: keys[1].color } });
    const row = h("div", { class: "hbar" }, [
      h("div", { class: "hbar-label", text: r.label }),
      h("div", { class: "hbar-pair" }, [
        h("div", { class: "hbar-track" }, [fa, h("span", { class: "hbar-value", text: fmt.money(r.a) })]),
        h("div", { class: "hbar-track" }, [fb, h("span", { class: "hbar-value", text: fmt.money(r.b) })]),
      ]),
    ]);
    hoverable(row, () => ({ title: r.label, rows: [
      { value: fmt.money(r.a), label: keys[0].label, color: keys[0].color },
      { value: fmt.money(r.b), label: keys[1].label, color: keys[1].color },
    ] }));
    animateWidth(fa, Math.max(0.5, (r.a / max) * 100));
    animateWidth(fb, Math.max(0.5, (r.b / max) * 100));
    list.appendChild(row);
  });
  wrap.appendChild(list);
  return wrap;
}

function legend(keys, cls) {
  return h("div", { class: "legend " + (cls || "") }, keys.map((k) =>
    h("span", { class: "legend-item" }, [h("span", { class: "swatch", style: { background: k.color } }), k.label])));
}

/* One stacked 100% bar plus a legend table. segs: {label, value, color, share, href} */
function shareBar(segs, format = fmt.money) {
  const total = segs.reduce((a, x) => a + x.value, 0) || 1;
  const bar = h("div", { class: "sharebar" });
  segs.forEach((x, i) => {
    const seg = h("span", { class: x.href ? "seg-link" : "", style: { flex: String(x.value), background: x.color, animationDelay: i * 0.08 + "s" } });
    hoverable(seg, () => ({ title: x.label, rows: [{ value: format(x.value), label: fmt.pct(x.share ?? (x.value / total) * 100) + " of total", color: x.color }] }));
    if (x.href) {
      const go = (e) => { e.stopPropagation(); location.hash = x.href; };
      seg.addEventListener("click", go);
      seg.addEventListener("keydown", (e) => { if (e.key === "Enter") go(e); });
    }
    bar.appendChild(seg);
  });
  const list = h("div", { class: "legend-list" }, segs.map((x) => h("div", { class: "legend-row" }, [
    h("span", { class: "swatch", style: { background: x.color } }),
    h("span", {}, [labelLink(x.label, x.href)]),
    h("span", { class: "num money", text: format(x.value) }),
    h("span", { class: "num muted", text: fmt.pct(x.share ?? (x.value / total) * 100) }),
  ])));
  return h("div", {}, [bar, list]);
}

/* Meter with optional peak marker. */
function meter(value, color, peak) {
  const fill = h("div", { class: "meter-fill", style: { background: color } });
  const m = h("div", { class: "meter" }, [fill]);
  if (peak !== undefined) m.appendChild(h("div", { class: "meter-peak", style: { left: `calc(${Math.min(100, peak)}% - 1px)` } }));
  animateWidth(fill, Math.min(100, Math.max(0, value)));
  return m;
}

/* Responsive SVG: renders on mount and on resize. */
function responsive(container, render) {
  const draw = () => {
    const w = Math.max(280, container.clientWidth);
    container.replaceChildren(render(w));
  };
  const ro = new ResizeObserver(() => {
    if (container.__lastW !== container.clientWidth) { container.__lastW = container.clientWidth; draw(); }
  });
  ro.observe(container);
  return container;
}

function niceMax(v) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
}

/* Smallest whole number from 1, 2, 5, 10, 20, 50 ... that is >= v. */
function niceIntStep(v) {
  for (let p = 1; ; p *= 10) for (const m of [1, 2, 5]) if (m * p >= v) return m * p;
}

/* Line chart with crosshair. series: [{name, color, points: [{t: Date|string, v}]}] */
function lineChart(series, opts = {}) {
  const height = opts.height || 240;
  const container = h("div", { class: "chart" });
  return responsive(container, (W) => {
    const m = { top: 16, right: 56, bottom: 28, left: 40 };
    const iw = W - m.left - m.right, ih = height - m.top - m.bottom;
    const all = series.flatMap((x) => x.points.map((p) => ({ t: +new Date(p.t), v: p.v })));
    if (!all.length) return h("div", { class: "empty", text: "No data points in this time range." });
    const t0 = Math.min(...all.map((p) => p.t)), t1 = Math.max(...all.map((p) => p.t));
    const yMax = opts.yMax || niceMax(Math.max(...all.map((p) => p.v), opts.threshold || 0) * 1.1);
    const x = (t) => m.left + (t1 === t0 ? iw / 2 : ((t - t0) / (t1 - t0)) * iw);
    const y = (v) => m.top + ih - (v / yMax) * ih;
    const svg = s("svg", { viewBox: `0 0 ${W} ${height}`, height, role: "img", "aria-label": opts.label || "Line chart" });
    for (let i = 0; i <= 4; i++) {
      const v = (yMax / 4) * i;
      svg.appendChild(s("line", { class: i === 0 ? "baseline" : "gridline", x1: m.left, x2: m.left + iw, y1: y(v), y2: y(v) }));
      svg.appendChild(s("text", { class: "tick", x: m.left - 8, y: y(v) + 4, "text-anchor": "end", text: (opts.yFormat || fmt.num)(v) }));
    }
    const ticks = 5;
    for (let i = 0; i <= ticks; i++) {
      const t = t0 + ((t1 - t0) / ticks) * i;
      svg.appendChild(s("text", { class: "tick", x: x(t), y: height - 8, "text-anchor": i === 0 ? "start" : i === ticks ? "end" : "middle", text: fmt.time(t) }));
    }
    if (opts.threshold !== undefined && opts.threshold <= yMax) {
      svg.appendChild(s("line", { class: "threshold", x1: m.left, x2: m.left + iw, y1: y(opts.threshold), y2: y(opts.threshold) }));
      svg.appendChild(s("text", { class: "threshold-label", x: m.left + iw + 6, y: y(opts.threshold) + 4, text: opts.thresholdLabel || "" }));
    }
    series.forEach((ser) => {
      const pts = ser.points.map((p) => [x(+new Date(p.t)), y(p.v)]);
      if (!pts.length) return;
      const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join("");
      svg.appendChild(s("path", { class: "area", fill: ser.color, d: `${d}L${pts[pts.length - 1][0]},${y(0)}L${pts[0][0]},${y(0)}Z` }));
      const path = s("path", { class: "line" + (noMotion() ? "" : " draw"), stroke: ser.color, d });
      svg.appendChild(path);
      requestAnimationFrame(() => { try { path.style.setProperty("--len", path.getTotalLength()); } catch (e) { /* ignore */ } });
      const last = pts[pts.length - 1], lastV = ser.points[ser.points.length - 1].v;
      svg.appendChild(s("circle", { cx: last[0], cy: last[1], r: 4, fill: ser.color, stroke: "var(--surface-1)", "stroke-width": 2 }));
      svg.appendChild(s("text", { class: "endlabel", x: last[0] + 8, y: last[1] + 4, text: (opts.valueFormat || fmt.num)(lastV) }));
    });
    const cross = s("line", { class: "crosshair", y1: m.top, y2: m.top + ih });
    const dot = s("circle", { r: 5, fill: series[0].color, stroke: "var(--surface-1)", "stroke-width": 2, opacity: 0 });
    svg.appendChild(cross);
    svg.appendChild(dot);
    const hit = s("rect", { x: m.left, y: m.top, width: iw, height: ih, fill: "transparent" });
    const times = [...new Set(all.map((p) => p.t))].sort((a, b) => a - b);
    const onMove = (evt) => {
      const rect = svg.getBoundingClientRect();
      const px = ((evt.clientX - rect.left) / rect.width) * W;
      const t = times.reduce((best, c) => (Math.abs(x(c) - px) < Math.abs(x(best) - px) ? c : best), times[0]);
      cross.setAttribute("x1", x(t)); cross.setAttribute("x2", x(t)); cross.style.opacity = 1;
      const rows = series.map((ser) => {
        const p = ser.points.find((q) => +new Date(q.t) === t);
        return p ? { value: (opts.valueFormat || fmt.num)(p.v), label: ser.name, color: ser.color, v: p.v } : null;
      }).filter(Boolean);
      if (rows[0]) { dot.setAttribute("cx", x(t)); dot.setAttribute("cy", y(rows[0].v)); dot.setAttribute("opacity", 1); }
      tip.show(evt, fmt.dateTime(t), rows);
    };
    hit.addEventListener("pointermove", onMove);
    hit.addEventListener("pointerleave", () => { cross.style.opacity = 0; dot.setAttribute("opacity", 0); tip.hide(); });
    svg.appendChild(hit);
    return svg;
  });
}

/* Stacked columns over time. buckets: [{t, parts: {key: n}}], keys: [{key, label, color}] */
function stackedColumns(buckets, keys, opts = {}) {
  const height = opts.height || 220;
  const container = h("div", { class: "chart" });
  const wrap = h("div", {}, [legend(keys), container]);
  responsive(container, (W) => {
    const m = { top: 12, right: 12, bottom: 28, left: 34 };
    const iw = W - m.left - m.right, ih = height - m.top - m.bottom;
    const totals = buckets.map((b) => keys.reduce((a, k) => a + (b.parts[k.key] || 0), 0));
    const yMax = niceIntStep(Math.max(...totals, 1) / 4) * 4; // counts: whole-number ticks
    const y = (v) => m.top + ih - (v / yMax) * ih;
    const svg = s("svg", { viewBox: `0 0 ${W} ${height}`, height, role: "img", "aria-label": opts.label || "Column chart" });
    for (let i = 0; i <= 4; i++) {
      const v = (yMax / 4) * i;
      svg.appendChild(s("line", { class: i === 0 ? "baseline" : "gridline", x1: m.left, x2: m.left + iw, y1: y(v), y2: y(v) }));
      svg.appendChild(s("text", { class: "tick", x: m.left - 8, y: y(v) + 4, "text-anchor": "end", text: fmt.num(Math.round(v * 10) / 10) }));
    }
    const band = iw / buckets.length;
    const bw = Math.min(24, Math.max(3, band - 4));
    const every = Math.ceil(buckets.length / Math.max(2, Math.floor(iw / 70)));
    buckets.forEach((b, i) => {
      const cx = m.left + band * i + band / 2;
      const g = s("g", { class: "colgroup" });
      let acc = 0;
      const present = keys.filter((k) => b.parts[k.key]);
      present.forEach((k, j) => {
        const v = b.parts[k.key];
        const y0 = y(acc), y1 = y(acc + v);
        const top = j === present.length - 1;
        const hgt = Math.max(0, y0 - y1 - (j > 0 ? 2 : 0));
        const yTop = y1;
        const r = top ? Math.min(4, hgt) : 0;
        const d = `M${cx - bw / 2},${yTop + hgt}V${yTop + r}${r ? `Q${cx - bw / 2},${yTop} ${cx - bw / 2 + r},${yTop}` : ""}H${cx + bw / 2 - r}${r ? `Q${cx + bw / 2},${yTop} ${cx + bw / 2},${yTop + r}` : ""}V${yTop + hgt}Z`;
        const p = s("path", { class: "col rise", d, fill: k.color });
        p.style.animationDelay = (noMotion() ? 0 : i * 0.015) + "s";
        g.appendChild(p);
        acc += v;
      });
      g.appendChild(s("rect", { x: cx - band / 2, y: m.top, width: band, height: ih, fill: "transparent" }));
      g.addEventListener("pointermove", (evt) => tip.show(evt, opts.bucketLabel ? opts.bucketLabel(b) : fmt.time(b.t),
        present.length ? present.map((k) => ({ value: fmt.num(b.parts[k.key]), label: k.label, color: k.color })) : [{ value: "0", label: "entries" }]));
      g.addEventListener("pointerleave", () => tip.hide());
      svg.appendChild(g);
      if (i % every === 0) svg.appendChild(s("text", { class: "tick", x: cx, y: height - 8, "text-anchor": "middle", text: fmt.time(b.t) }));
    });
    return svg;
  });
  return wrap;
}

/* Sparkline for the hero tile (decorative). */
function sparkline(values, color) {
  const W = 200, H = 60;
  const max = Math.max(...values), min = Math.min(...values);
  const x = (i) => (i / (values.length - 1)) * W;
  const y = (v) => H - 6 - ((v - min) / (max - min || 1)) * (H - 12);
  const d = values.map((v, i) => (i ? "L" : "M") + x(i) + "," + y(v)).join("");
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", class: "hero-spark", "aria-hidden": "true" });
  svg.appendChild(s("path", { d: d + `L${W},${H}L0,${H}Z`, fill: color, opacity: 0.25 }));
  svg.appendChild(s("path", { d, fill: "none", stroke: color, "stroke-width": 2 }));
  return svg;
}
