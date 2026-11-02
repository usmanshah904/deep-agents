/* GCP SRE Agent dashboard (Deep Agents version). Data pages only read. The Chat page talks to the
   agent; changes run only after the user clicks Approve on that change ID. */

const NAV = [
  { id: "overview", label: "Overview", icon: "overview", group: "Summary" },
  { id: "chat", label: "Chat", icon: "chat", group: "Summary" },
  { id: "billing", label: "Billing", icon: "billing", group: "Cost" },
  { id: "gke", label: "GKE", icon: "gke", group: "Cost" },
  { id: "bigquery", label: "BigQuery", icon: "bigquery", group: "Cost" },
  { id: "compute", label: "Compute Engine", icon: "compute", group: "Cost" },
  { id: "storage", label: "Cloud Storage", icon: "storage", group: "Cost" },
  { id: "savings", label: "Savings", icon: "savings", group: "Cost" },
  { id: "monitoring", label: "Monitoring", icon: "monitoring", group: "Operations" },
  { id: "logging", label: "Logging", icon: "logging", group: "Operations" },
  { id: "changes", label: "Changes", icon: "changes", group: "Operations" },
  { id: "agent", label: "Agent", icon: "agent", group: "Project" },
];

const SUBTITLES = {
  overview: "Cost, health and errors at a glance",
  chat: "Ask the agent. Changes wait for your Approve click",
  billing: "Total spend, by service and project, month over month",
  gke: "Cluster, namespace and workload cost, over-provisioning and live usage",
  bigquery: "Most expensive queries, what is wrong and how to fix them",
  compute: "VM cost, waste, commitments and Spot candidates",
  storage: "Bucket cost, cold data, cleanups and egress",
  savings: "Every estimated saving, ranked",
  monitoring: "CPU and memory usage from Cloud Monitoring",
  logging: "Errors, warnings and log search from Cloud Logging",
  changes: "Changes the agent proposed and applied after your approval",
  agent: "What the agent is made of: skills, tools and MCP server",
};

const state = {
  route: "overview",
  hours: 1,
  cost: null,
  obs: null,
  agent: null,
  updatedAt: null,
  monitor: { kind: "vm", metric: "cpu", selected: null },
  logSearch: { query: "", severity: "", resource: "" },
  chat: null, // set at startup from sessionStorage
};

/* Colors are resolved from CSS tokens so SVG attributes get real values; views re-render on theme change. */
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const SERVICE_SLOT = { "Kubernetes Engine": 1, BigQuery: 2, "Compute Engine": 3, "Cloud Storage": 4 }; // others: slot 5
const SERVICE_PAGE = { "Kubernetes Engine": "#gke", BigQuery: "#bigquery", "Compute Engine": "#compute", "Cloud Storage": "#storage" };
const servicePage = (svc) => SERVICE_PAGE[svc]; // Cloud SQL, Cloud Logging and others have no page
const serviceColor = (svc) => css(`--series-${SERVICE_SLOT[svc] || 5}`);
const slot = (n) => css(`--series-${n}`);
const SEVERITY_COLOR = { CRITICAL: "--critical", ALERT: "--critical", EMERGENCY: "--critical", ERROR: "--serious", WARNING: "--warning" };
const sevColor = (sev) => css(SEVERITY_COLOR[sev] || "--info");
const statusColor = (flag) => css(flag === "high" ? "--critical" : flag === "idle" ? "--info" : "--accent");

/* ---------- Data ---------- */

async function getJSON(url) {
  if (window.SNAPSHOT) return snapshotFetch(url); // saved data, no server
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

/* Loads everything (cost, monitoring, logs, changes). Runs on page load and when the user presses refresh. */
async function loadAll() {
  const view = document.getElementById("view");
  const btn = document.getElementById("refresh");
  view.classList.add("loading");
  btn.classList.add("spinning");
  try {
    const [cost, obs, agent, changes] = await Promise.all([
      getJSON("/api/cost"),
      getJSON(`/api/observability?hours=${state.hours}`),
      state.agent ? Promise.resolve(state.agent) : getJSON("/api/agent"),
      getJSON("/api/changes"),
    ]);
    Object.assign(state, { cost, obs, agent, changes, updatedAt: new Date() });
  } catch (e) {
    view.replaceChildren(emptyState("Could not load data from the dashboard server.", String(e)));
    return;
  } finally {
    view.classList.remove("loading");
    btn.classList.remove("spinning");
  }
  const y = window.scrollY;
  renderChrome();
  render();
  window.scrollTo({ top: y });
}

const obsOnline = () => state.obs && state.obs.log_summary && state.obs.log_summary.status === "ok";

/* ---------- Shell ---------- */

function renderNav() {
  const nav = document.getElementById("nav");
  nav.replaceChildren();
  let group = null;
  for (const item of NAV) {
    if (item.group !== group) { group = item.group; nav.appendChild(h("div", { class: "nav-group", text: group })); }
    const a = h("a", { class: "nav-item" + (state.route === item.id ? " active" : ""), href: "#" + item.id }, [icon(item.icon), item.label]);
    if (item.id === "logging" && obsOnline() && state.obs.errors.status === "ok" && state.obs.errors.total_errors) {
      a.appendChild(h("span", { class: "nav-badge", text: String(state.obs.errors.total_errors), title: "Errors in range" }));
    }
    const pending = state.changes?.history?.counts?.proposed || 0;
    if (item.id === "changes" && pending) a.appendChild(h("span", { class: "nav-badge pending", text: String(pending), title: "Waiting for your approval" }));
    if (state.route === item.id) a.setAttribute("aria-current", "page");
    nav.appendChild(a);
  }
}

function renderChrome() {
  renderNav();
  const src = document.getElementById("sources");
  const month = state.cost?.summary?.month || "";
  src.replaceChildren(
    h("span", { class: "pill", title: "Where the cost tools get their data" }, [h("span", { class: "dot" }), `Cost: ${state.cost?.source || "loading"}${month ? " · " + month : ""}`]),
    window.SNAPSHOT
      ? h("span", { class: "pill", title: "Saved copy of the dashboard. Data does not change." }, [h("span", { class: "dot" }), `Snapshot \u00b7 ${fmt.dateTime(window.SNAPSHOT.taken_at)}`])
      : obsOnline()
      ? h("span", { class: "pill", title: "Monitoring and logging tools read the floci-gcp emulator" }, [h("span", { class: "dot live" }), `floci-gcp live · ${state.obs.project}`])
      : h("span", { class: "pill", title: "floci-gcp is not reachable" }, [h("span", { class: "dot down" }), "floci-gcp offline"]),
  );
  if (state.updatedAt && !window.SNAPSHOT) {
    src.appendChild(h("span", { class: "pill", title: "Press refresh to load the latest data and changes" }, [`Updated ${fmt.time(state.updatedAt)}`]));
  }
  document.getElementById("page-title").textContent = NAV.find((n) => n.id === state.route).label;
  document.getElementById("page-sub").textContent = SUBTITLES[state.route];
}

function render() {
  const view = document.getElementById("view");
  tip.hide();
  if (!state.cost) return;
  const views = { overview, chat: chatView, billing, gke, bigquery, compute, storage, savings, monitoring, logging, changes: changesView, agentView };
  const fn = views[state.route === "agent" ? "agentView" : state.route] || overview;
  const grid = h("div", { class: "grid" });
  fn(grid);
  [...grid.children].forEach((c, i) => { c.style.animationDelay = Math.min(i, 10) * 0.04 + "s"; });
  view.replaceChildren(grid);
}

/* ---------- Building blocks ---------- */

function card(span, title, sub, body, actions) {
  return h("section", { class: `card ${span}` }, [
    title ? h("div", { class: "card-head" }, [
      h("div", {}, [h("h2", { class: "card-title", text: title }), sub ? h("div", { class: "card-sub", text: sub }) : null]),
      actions ? h("div", { class: "card-actions" }, actions) : null,
    ]) : null,
  ].concat(body));
}

function tile(span, label, value, format, foot, iconName, extra) {
  const v = h("div", { class: "tile-value" });
  countUp(v, value, format);
  return h("section", { class: `card tile ${span}` }, [
    iconName ? h("div", { class: "tile-icon" }, [icon(iconName)]) : null,
    h("div", { class: "tile-label", text: label }), v,
    foot ? (typeof foot === "string" ? h("div", { class: "tile-foot", text: foot }) : foot) : null,
    extra || null,
  ]);
}

function deltaChip(amount, pct, upIsBad = true) {
  const bad = upIsBad ? amount > 0 : amount < 0;
  const arrow = amount > 0 ? "▲" : amount < 0 ? "▼" : "●";
  return h("span", { class: "delta " + (amount === 0 ? "" : bad ? "bad" : "good") }, `${arrow} ${fmt.signedMoney(amount)} (${fmt.signedPct(pct)})`);
}

function statusChip(flag) {
  const labels = { high: "▲ High", idle: "◌ Idle", normal: "● Normal" };
  return h("span", { class: "chip " + flag, text: labels[flag] || flag });
}

function sevChip(sev) {
  const glyph = { CRITICAL: "▲", ALERT: "▲", EMERGENCY: "▲", ERROR: "■", WARNING: "◆" }[sev] || "●";
  return h("span", { class: "chip " + sev, text: `${glyph} ${sev}` });
}

function table(columns, rows, opts = {}) {
  const thead = h("thead", {}, [h("tr", {}, columns.map((c) => h("th", { class: c.num ? "num" : "", text: c.label })))]);
  const tbody = h("tbody", {}, rows.map((r) => {
    const tr = h("tr", { class: (opts.onClick ? "clickable " : "") + (opts.isSelected && opts.isSelected(r) ? "selected" : "") },
      columns.map((c) => {
        const v = c.render ? c.render(r) : r[c.key];
        return h("td", { class: c.num ? "num" : "" }, [v instanceof Node ? v : String(v ?? "")]);
      }));
    if (opts.onClick) tr.addEventListener("click", () => opts.onClick(r));
    return tr;
  }));
  return h("div", { class: "table-wrap" }, [h("table", {}, [thead, tbody])]);
}

function emptyState(title, detail) {
  return h("div", { class: "empty" }, [icon("cloud"), h("div", { text: title }), detail ? h("div", { class: "card-sub", text: detail }) : null]);
}

function offlineCard(span) {
  return card(span, "Monitoring and logging are offline", "floci-gcp is not reachable on localhost:4588", [
    h("div", { class: "empty" }, [
      icon("cloud"),
      h("div", {}, ["Start the emulator with ", h("code", { text: "docker compose up -d" }), " and seed it with ", h("code", { text: "python seed_floci.py" }), ", then press refresh."]),
    ]),
  ]);
}

function copyButton(text) {
  const b = h("button", { class: "btn", title: "Copy question" }, [icon("copy"), "Copy"]);
  b.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(text); b.lastChild.textContent = "Copied"; } catch (e) { b.lastChild.textContent = "Select and copy"; }
    setTimeout(() => { b.lastChild.textContent = "Copy"; }, 1500);
  });
  return b;
}

function assumptions(text) {
  return h("details", { class: "card-sub", style: { marginTop: "12px" } }, [h("summary", { text: "Assumptions behind these estimates" }), h("p", { text })]);
}

function utilResources() {
  if (!obsOnline()) return [];
  return [
    ...(state.obs.vm_cpu.resources || []).map((r) => ({ ...r, kind: "VM" })),
    ...(state.obs.gke_cpu.resources || []).map((r) => ({ ...r, kind: "GKE" })),
  ];
}

/* Group warning-and-worse log entries into time buckets for the timeline. */
function logBuckets() {
  const entries = state.obs.warnings_and_errors.entries || [];
  const mins = state.hours <= 1 ? 5 : state.hours <= 6 ? 30 : 60;
  const size = mins * 60000;
  const end = Math.ceil(nowMs() / size) * size;
  const start = end - state.hours * 3600000;
  const buckets = [];
  for (let t = start; t < end; t += size) buckets.push({ t, parts: {} });
  for (const e of entries) {
    const i = Math.floor((new Date(e.time).getTime() - start) / size);
    if (i < 0 || i >= buckets.length) continue;
    const key = ["ALERT", "EMERGENCY"].includes(e.severity) ? "CRITICAL" : e.severity;
    buckets[i].parts[key] = (buckets[i].parts[key] || 0) + 1;
  }
  return { buckets, mins };
}

const SEV_KEYS = () => [
  { key: "CRITICAL", label: "Critical", color: sevColor("CRITICAL") },
  { key: "ERROR", label: "Error", color: sevColor("ERROR") },
  { key: "WARNING", label: "Warning", color: sevColor("WARNING") },
];

/* ---------- Views ---------- */

function overview(grid) {
  const c = state.cost, o = state.obs;
  const online = obsOnline();

  // Incident banner
  if (!online) {
    grid.appendChild(h("div", { class: "banner offline s12" }, [
      h("div", { class: "banner-icon" }, [icon("cloud")]),
      h("div", { class: "banner-body" }, [h("div", { class: "banner-title", text: "Monitoring and logging offline" }),
        h("div", { class: "banner-text", text: "Start floci-gcp (docker compose up -d) and run python seed_floci.py to see health and errors." })]),
    ]));
  } else {
    const criticals = (o.errors.top_errors || []).filter((g) => ["CRITICAL", "ALERT", "EMERGENCY"].includes(g.severity));
    const critical = criticals.find((g) => !resolvedAt(g));
    const resolved = criticals.find((g) => resolvedAt(g));
    if (!critical && resolved) {
      grid.appendChild(h("div", { class: "banner ok s12" }, [
        h("div", { class: "banner-icon" }, [icon("check")]),
        h("div", { class: "banner-body" }, [
          h("div", { class: "banner-title", text: `Resolved: ${resolved.message}` }),
          h("div", { class: "banner-text", text: `${resolved.resources.join(", ")} recovered at ${fmt.time(resolvedAt(resolved))} · last error ${fmt.ago(resolved.last_seen)} · old errors stay in the logs until they leave the time window` }),
        ]),
        h("a", { class: "btn", href: "#logging" }, ["View logs"]),
      ]));
    } else if (critical) {
      const q = "Show me recent errors and find the root cause.";
      grid.appendChild(h("div", { class: "banner s12", role: "alert" }, [
        h("div", { class: "banner-icon" }, [icon("alert")]),
        h("div", { class: "banner-body" }, [
          h("div", { class: "banner-title", text: `${critical.severity}: ${critical.message}` }),
          h("div", { class: "banner-text", text: `${critical.resources.join(", ")} · ${critical.count} ${critical.count === 1 ? "time" : "times"} · last seen ${fmt.ago(critical.last_seen)} · Ask the agent: “${q}”` }),
        ]),
        copyButton(q),
        h("a", { class: "btn primary", href: "#logging" }, ["View logs"]),
      ]));
    } else {
      grid.appendChild(h("div", { class: "banner ok s12" }, [
        h("div", { class: "banner-icon" }, [icon("check")]),
        h("div", { class: "banner-body" }, [h("div", { class: "banner-title", text: `No critical errors in the last ${state.hours}h` })]),
      ]));
    }
  }

  // Hero + tiles
  const sum = c.summary;
  const heroVal = h("div", { class: "tile-value" });
  countUp(heroVal, sum.total_cost, fmt.money);
  grid.appendChild(h("section", { class: "card tile hero s6" }, [
    h("div", { class: "tile-label", text: `Total GCP cost · ${sum.month}` }),
    heroVal,
    deltaChip(sum.change_amount, sum.change_pct),
    h("div", { class: "tile-foot", text: `vs ${fmt.money(sum.previous_total_cost)} in ${sum.previous_month}` }),
  ]));
  grid.appendChild(tile("s3", "Estimated savings / month", c.savings.total_estimated_monthly_saving, fmt.money,
    `${fmt.pct(c.savings.pct_of_total_bill)} of the bill · estimate`, "savings"));
  if (online) {
    const { buckets } = logBuckets();
    const series = buckets.map((b) => (b.parts.ERROR || 0) + (b.parts.CRITICAL || 0));
    const crit = (o.log_summary.by_severity.CRITICAL || 0);
    grid.appendChild(tile("s3", `Errors · last ${state.hours}h`, o.errors.total_errors, fmt.num,
      `${o.errors.distinct_errors} distinct · ${crit} critical`, "alert", series.length > 1 ? sparkline(series, sevColor("ERROR")) : null));
  } else {
    grid.appendChild(tile("s3", "Errors", 0, () => "—", "floci-gcp offline", "alert"));
  }

  // Cost by service + change
  const svc = c.by_service.by_service;
  grid.appendChild(card("s6", "Where the money goes", `Cost by service · ${c.by_service.month}`,
    [shareBar(svc.map((x) => ({ label: x.service, value: x.cost, share: x.share_pct, color: serviceColor(x.service), href: servicePage(x.service) })))]));
  const cmp = c.compare.by_service;
  const maxAbs = Math.max(...cmp.map((x) => Math.abs(x.change_amount)), 1);
  grid.appendChild(card("s6", "What changed vs last month", `Total ${fmt.signedMoney(c.compare.total_change_amount)} (${fmt.signedPct(c.compare.total_change_pct)})`, [
    hbars(cmp.map((x) => ({
      label: x.service, value: Math.abs(x.change_amount), href: servicePage(x.service),
      color: x.change_amount > 0 ? css("--div-up") : x.change_amount < 0 ? css("--div-down") : css("--baseline"),
      display: `${fmt.signedMoney(x.change_amount)} (${fmt.signedPct(x.change_pct)})`, tipLabel: `${fmt.money(x.previous_cost)} → ${fmt.money(x.current_cost)}`,
    })), { max: maxAbs }),
    h("div", { class: "card-sub", style: { marginTop: "12px" }, text: "Red = cost went up, blue = cost went down, gray = no change." }),
  ]));

  // Top savings + health
  const ops = c.savings.opportunities.slice(0, 6);
  grid.appendChild(card("s7", "Top savings opportunities", "Estimated monthly saving · open Savings for all", [
    hbars(ops.map((x) => ({ label: x.title.split(": ")[1] || x.title, sub: x.service, value: x.estimated_monthly_saving, color: serviceColor(x.service),
      display: fmt.money(x.estimated_monthly_saving) + "/mo", tipLabel: x.service }))),
  ]));
  if (online) {
    const res = utilResources().sort((a, b) => b.peak_pct - a.peak_pct);
    const high = res.filter((r) => r.flag === "high").length, idle = res.filter((r) => r.flag === "idle").length;
    grid.appendChild(card("s5", "Resource health", `CPU · last ${state.hours}h · ${high} high, ${idle} idle`, [
      h("div", { class: "stack" }, res.slice(0, 6).map((r) => h("div", {}, [
        h("div", { class: "item-head" }, [h("span", { class: "item-title", text: r.resource }), h("span", { style: { display: "flex", gap: "8px", alignItems: "center" } }, [
          h("span", { class: "muted", text: `${fmt.pct(r.peak_pct)} peak` }), statusChip(r.flag)])]),
        h("div", { style: { marginTop: "6px" } }, [meter(r.avg_pct, statusColor(r.flag), r.peak_pct)]),
      ]))),
      h("div", { class: "card-sub", style: { marginTop: "12px" }, text: "Bar = average, tick = peak. High = peak ≥ 80%, idle = average < 5%." }),
    ]));
  } else grid.appendChild(offlineCard("s5"));

  if (online) {
    const { buckets, mins } = logBuckets();
    grid.appendChild(card("s7", "Warnings and errors over time", `${mins}-minute buckets · last ${state.hours}h`, [stackedColumns(buckets, SEV_KEYS(), { label: "Warnings and errors over time" })]));
    grid.appendChild(card("s5", "Top errors", `Grouped by message · last ${state.hours}h`, [errorList(o.errors.top_errors.slice(0, 4))]));
  }
  linkOverviewCards(grid);
}

/* An error group is resolved when every resource it hit logged "RESOLVED:" after the group's last occurrence.
   Returns the time of the latest of those recoveries, or null. */
function resolvedAt(g) {
  const resolutions = state.obs?.resolutions?.entries || [];
  const times = g.resources.map((res) => resolutions.filter((e) => e.resource === res && e.time > g.last_seen).map((e) => e.time).sort().pop());
  return times.every(Boolean) ? times.sort().pop() : null;
}

/* Overview cards link to the page with the details. Matched by the card's title. */
const OVERVIEW_LINKS = [
  ["Estimated savings", "savings"],
  ["Errors", "logging"],
  ["Where the money goes", "billing"],
  ["What changed", "billing"],
  ["Top savings", "savings"],
  ["Resource health", "monitoring"],
  ["Warnings and errors", "logging"],
  ["Top errors", "logging"],
];

function linkCard(el, route) {
  const label = NAV.find((n) => n.id === route).label;
  el.classList.add("link-card");
  Object.assign(el, { tabIndex: 0, title: `Open ${label}` });
  el.setAttribute("role", "link");
  el.dataset.goLabel = label;
  const go = (e) => {
    if (e.target.closest("a, button, input, select")) return; // the card's own buttons keep working
    location.hash = route;
  };
  el.addEventListener("click", go);
  el.addEventListener("keydown", (e) => { if (e.key === "Enter") go(e); });
}

function linkOverviewCards(grid) {
  for (const el of grid.children) {
    const title = el.querySelector(".card-title, .tile-label")?.textContent || "";
    const route = el.classList.contains("banner") ? (el.classList.contains("offline") ? null : "logging")
      : el.classList.contains("hero") ? "billing"
      : OVERVIEW_LINKS.find(([prefix]) => title.startsWith(prefix))?.[1];
    if (route) linkCard(el, route);
  }
}

function errorList(groups) {
  if (!groups.length) return emptyState("No errors in this time range.");
  return h("div", { class: "stack" }, groups.map((g) => {
    const fixed = resolvedAt(g);
    return h("div", { class: "item" + (fixed ? " resolved" : "") }, [
      h("div", { class: "item-head" }, [
        h("span", { style: { display: "flex", gap: "6px", alignItems: "center", flexWrap: "wrap" } }, [
          sevChip(g.severity),
          fixed ? h("span", { class: "chip normal", title: "A recovery was logged after the last occurrence", text: `✓ Resolved ${fmt.time(fixed)}` }) : null,
        ]),
        h("span", { class: "count-badge", text: `${g.count}×` }),
      ]),
      h("div", { class: "item-title", style: { marginTop: "6px" }, text: g.message }),
      h("div", { class: "item-meta" }, [
        h("span", { text: g.resources.join(", ") }),
        h("span", { text: `first ${fmt.dateTime(g.first_seen)}` }),
        h("span", { text: `last ${fmt.ago(g.last_seen)}` }),
      ]),
    ]);
  }));
}

function billing(grid) {
  const c = state.cost, sum = c.summary;
  grid.appendChild(tile("s3", `This month · ${sum.month}`, sum.total_cost, fmt.money, null, "billing"));
  grid.appendChild(tile("s3", `Last month · ${sum.previous_month}`, sum.previous_total_cost, fmt.money, null, "billing"));
  grid.appendChild(tile("s3", "Change", sum.change_amount, fmt.signedMoney, deltaChip(sum.change_amount, sum.change_pct), "trend"));
  grid.appendChild(tile("s3", "Projects", c.by_project.by_project.length, fmt.num, c.by_project.by_project.map((p) => p.project).join(", "), "cloud"));

  grid.appendChild(card("s6", "Cost by service", c.by_service.month, [hbars(c.by_service.by_service.map((x) => ({
    label: x.service, value: x.cost, color: serviceColor(x.service), display: `${fmt.money(x.cost)} · ${fmt.pct(x.share_pct)}` })))]));
  grid.appendChild(card("s6", "Cost by project", c.by_project.month, [shareBar(c.by_project.by_project.map((x, i) => ({
    label: x.project, value: x.cost, share: x.share_pct, color: slot(i + 1) })))]));

  const cmp = c.compare;
  grid.appendChild(card("s7", "Month over month by service", `${cmp.previous_month} vs ${cmp.month}`, [pairedHbars(
    cmp.by_service.map((x) => ({ label: x.service, a: x.previous_cost, b: x.current_cost })),
    [{ label: cmp.previous_month, color: css("--prev") }, { label: cmp.month, color: slot(1) }])]));
  grid.appendChild(card("s5", "Change table", `Total ${fmt.signedMoney(cmp.total_change_amount)} (${fmt.signedPct(cmp.total_change_pct)})`, [table([
    { label: "Service", key: "service" },
    { label: cmp.previous_month, num: true, render: (r) => fmt.money(r.previous_cost) },
    { label: cmp.month, num: true, render: (r) => fmt.money(r.current_cost) },
    { label: "Change", num: true, render: (r) => h("span", { class: r.change_amount > 0 ? "up" : r.change_amount < 0 ? "down" : "", text: `${fmt.signedMoney(r.change_amount)} (${fmt.signedPct(r.change_pct)})` }) },
  ], cmp.by_service)]));
}

function gke(grid) {
  const c = state.cost;
  const over = c.gke_overprovisioned;
  const workloads = c.gke_workloads.top_workloads;
  grid.appendChild(tile("s3", "GKE cost", c.gke_clusters.total_gke_cost, fmt.money, c.gke_clusters.month, "gke"));
  grid.appendChild(tile("s3", "Clusters", c.gke_clusters.by_cluster.length, fmt.num, c.gke_clusters.by_cluster.map((x) => `${x.cluster} (${x.mode})`).join(", "), "gke"));
  grid.appendChild(tile("s3", "Workloads", workloads.length, fmt.num, `${over.overprovisioned.length} over-provisioned`, "cpu"));
  grid.appendChild(tile("s3", "Rightsizing saving", over.total_estimated_monthly_saving, fmt.money, "per month · estimate", "savings"));

  grid.appendChild(card("s5", "Cost by cluster", null, [shareBar(c.gke_clusters.by_cluster.map((x, i) => ({
    label: `${x.cluster} · ${x.mode}`, value: x.cost, share: x.share_pct, color: slot(i + 1) })))]));
  grid.appendChild(card("s7", "Cost by namespace", null, [hbars(c.gke_namespaces.by_namespace.map((x) => ({
    label: x.namespace, sub: x.cluster, value: x.cost, color: slot(1), display: `${fmt.money(x.cost)} · ${fmt.pct(x.share_pct)}` })))]));

  const overBy = Object.fromEntries(over.overprovisioned.map((w) => [w.workload, w]));
  const live = Object.fromEntries((obsOnline() ? state.obs.gke_cpu.resources || [] : []).map((r) => [r.resource.split("/").pop(), r]));
  grid.appendChild(card("s12", "Workloads", "Cost from billing · requested vs used from the cost data · live CPU from Cloud Monitoring", [table([
    { label: "Workload", render: (r) => h("div", {}, [h("div", { class: "item-title", text: r.workload }), h("div", { class: "card-sub", text: `${r.cluster} / ${r.namespace}` })]) },
    { label: "Cost", num: true, render: (r) => h("span", { class: "money", text: fmt.money(r.cost) }) },
    { label: "Avg use of requests", render: (r) => overBy[r.workload]
      ? h("div", { style: { minWidth: "140px" } }, [meter(overBy[r.workload].avg_utilization_pct, statusColor("normal")), h("div", { class: "card-sub", text: `${fmt.pct(overBy[r.workload].avg_utilization_pct)} · CPU ${overBy[r.workload].cpu_used}/${overBy[r.workload].cpu_requested} · mem ${overBy[r.workload].mem_used_gb}/${overBy[r.workload].mem_requested_gb} GB` })])
      : h("span", { class: "muted", text: "≥ 50% (not over-provisioned)" }) },
    { label: `Live CPU (${state.hours}h)`, render: (r) => live[r.workload] ? h("div", { style: { display: "flex", gap: "8px", alignItems: "center" } }, [h("span", { text: `${fmt.pct(live[r.workload].peak_pct)} peak` }), statusChip(live[r.workload].flag)]) : h("span", { class: "muted", text: "—" }) },
    { label: "Est. saving", num: true, render: (r) => overBy[r.workload] ? h("span", { class: "saving", text: fmt.money2(overBy[r.workload].estimated_monthly_saving) + "/mo" }) : "" },
  ], workloads)]));

  grid.appendChild(card("s12", "Over-provisioned workloads", `Total ${fmt.money(over.total_estimated_monthly_saving)}/mo · estimate`, [
    hbars(over.overprovisioned.map((w) => ({ label: w.workload, sub: `${w.cluster} / ${w.namespace}`, value: w.estimated_monthly_saving, color: slot(1),
      display: fmt.money(w.estimated_monthly_saving) + "/mo", tipLabel: `${fmt.pct(w.avg_utilization_pct)} of requests used` }))),
    assumptions(over.assumptions),
  ]));
}

function bigquery(grid) {
  const c = state.cost, q = c.bigquery;
  const bqCost = c.by_service.by_service.find((x) => x.service === "BigQuery");
  const tb = q.expensive_queries.reduce((a, x) => a + x.tb_billed, 0);
  grid.appendChild(tile("s3", "BigQuery cost", bqCost ? bqCost.cost : 0, fmt.money, `${q.pricing_model} pricing`, "bigquery"));
  grid.appendChild(tile("s3", "Expensive queries", q.expensive_queries.length, fmt.num, "found in this month's jobs", "search"));
  grid.appendChild(tile("s3", "TB billed by these queries", tb, fmt.num, "terabytes", "storage"));
  grid.appendChild(tile("s3", "Possible saving", q.total_estimated_monthly_saving, fmt.money, "per month · estimate", "savings"));

  const keys = [{ key: "keep", label: "Cost after fix", color: slot(1) }, { key: "save", label: "Avoidable (est.)", color: slot(3) }];
  grid.appendChild(card("s12", "Query cost and what a fix would save", null, [stackedHbars(q.expensive_queries.map((x) => ({
    label: `${x.query_id} · ${x.table}`, sub: x.user, parts: { keep: x.cost - x.estimated_monthly_saving, save: x.estimated_monthly_saving } })), keys)]));
  grid.appendChild(card("s12", "What is wrong and how to fix it", null, [h("div", { class: "stack" }, q.expensive_queries.map((x) => h("div", { class: "item" }, [
    h("div", { class: "item-head" }, [
      h("span", { class: "item-title", text: `${x.query_id} · ${x.table}` }),
      h("span", { style: { display: "flex", gap: "8px", alignItems: "center" } }, [h("span", { class: "badge", text: `${x.tb_billed} TB` }), h("span", { class: "money", text: fmt.money(x.cost) }), h("span", { class: "saving", text: `save ${fmt.money(x.estimated_monthly_saving)}` })]),
    ]),
    h("div", { class: "item-body" }, [h("strong", { text: "Problem: " }), x.issue]),
    h("div", { class: "item-body" }, [h("strong", { text: "Fix: " }), x.fix, ` (≈${x.est_saving_pct}% less)`]),
    h("div", { class: "item-meta" }, [h("span", { text: `user ${x.user}` }), h("span", { text: `project ${x.project}` })]),
  ]))), assumptions(q.assumptions)]));
}

function compute(grid) {
  const c = state.cost, vms = c.vms, w = c.vm_waste, cud = c.commitments;
  grid.appendChild(tile("s3", "Compute Engine cost", vms.total_compute_cost, fmt.money, `${fmt.money(vms.vm_cost)} VMs + ${fmt.money(vms.unused_resources_cost)} unused`, "compute"));
  grid.appendChild(tile("s3", "VMs", vms.vm_count, fmt.num, `${w.idle_vms.length} idle · ${w.oversized_vms.length} oversized`, "cpu"));
  grid.appendChild(tile("s3", "CUD coverage", cud.coverage_pct, fmt.pct, `${fmt.money(cud.covered_cost)} of ${fmt.money(cud.steady_vm_cost)} steady spend`, "check"));
  grid.appendChild(tile("s3", "Waste saving", w.total_estimated_monthly_saving, fmt.money, `${fmt.pct(w.pct_of_compute_cost)} of compute · estimate`, "savings"));

  const live = Object.fromEntries((obsOnline() ? state.obs.vm_cpu.resources || [] : []).map((r) => [r.resource, r]));
  grid.appendChild(card("s12", "Virtual machines", "Monthly cost and average use from the cost data · live CPU from Cloud Monitoring", [table([
    { label: "VM", render: (r) => h("div", {}, [h("div", { class: "item-title", text: r.name }), h("div", { class: "card-sub", text: `${r.project} · ${r.machine_type}` })]) },
    { label: "Cost", num: true, render: (r) => h("span", { class: "money", text: fmt.money(r.cost) }) },
    { label: "Share", render: (r) => h("div", { style: { minWidth: "90px" } }, [meter(r.share_pct * 4, slot(3)), h("div", { class: "card-sub", text: fmt.pct(r.share_pct) })]) },
    { label: "CPU (month)", render: (r) => h("div", { style: { minWidth: "90px" } }, [meter(r.cpu_util_pct, slot(1)), h("div", { class: "card-sub", text: fmt.pct(r.cpu_util_pct) })]) },
    { label: "Memory (month)", render: (r) => h("div", { style: { minWidth: "90px" } }, [meter(r.mem_util_pct, slot(1)), h("div", { class: "card-sub", text: fmt.pct(r.mem_util_pct) })]) },
    { label: `Live CPU (${state.hours}h)`, render: (r) => live[r.name] ? h("div", { style: { display: "flex", gap: "8px", alignItems: "center" } }, [h("span", { text: `${fmt.pct(live[r.name].peak_pct)} peak` }), statusChip(live[r.name].flag)]) : h("span", { class: "muted", text: "—" }) },
  ], vms.top_instances), h("div", { class: "card-sub", style: { marginTop: "8px" }, text: "Share bar is scaled so 25% of compute fills the bar." })]));

  const wasteItems = [
    ...w.idle_vms.map((x) => ({ title: x.name, tag: "Idle VM", detail: `${x.machine_type} · CPU ${x.cpu_util_pct}%`, save: x.estimated_monthly_saving })),
    ...w.oversized_vms.map((x) => ({ title: x.name, tag: "Oversized", detail: `${x.machine_type} · CPU ${x.cpu_util_pct}% · mem ${x.mem_util_pct}%`, save: x.estimated_monthly_saving })),
    ...w.unused_resources.map((x) => ({ title: x.name, tag: x.type.replace("_", " "), detail: `${x.detail} · ${x.age_days} days old`, save: x.estimated_monthly_saving })),
  ].sort((a, b) => b.save - a.save);
  grid.appendChild(card("s6", "Waste to remove or resize", `Total ${fmt.money(w.total_estimated_monthly_saving)}/mo · estimate`, [
    h("div", { class: "stack" }, wasteItems.map((x) => h("div", { class: "item" }, [
      h("div", { class: "item-head" }, [h("span", { style: { display: "flex", gap: "8px", alignItems: "center" } }, [h("span", { class: "badge accent", text: x.tag }), h("span", { class: "item-title", text: x.title })]), h("span", { class: "saving", text: fmt.money2(x.save) + "/mo" })]),
      h("div", { class: "item-meta", text: x.detail }),
    ]))), assumptions(w.assumptions)]));

  grid.appendChild(card("s6", "Commitments and Spot", `CUD ${fmt.money2(cud.cud_estimated_monthly_saving)}/mo · Spot ${fmt.money2(cud.spot_estimated_monthly_saving)}/mo`, [
    h("div", { class: "tile-label", text: `Committed use discount coverage: ${fmt.pct(cud.coverage_pct)}` }),
    h("div", { style: { margin: "8px 0 16px" } }, [meter(cud.coverage_pct, slot(1))]),
    h("div", { class: "card-title", style: { margin: "6px 0 8px" }, text: "Buy a 1-year CUD for" }),
    table([{ label: "VM", key: "name" }, { label: "After rightsizing", num: true, render: (r) => fmt.money2(r.cost_after_rightsizing) }, { label: "Saving", num: true, render: (r) => h("span", { class: "saving", text: fmt.money2(r.estimated_monthly_saving) }) }], cud.cud_candidates),
    h("div", { class: "card-title", style: { margin: "16px 0 8px" }, text: "Move to Spot VMs (batch)" }),
    table([{ label: "VM", key: "name" }, { label: "Cost", num: true, render: (r) => fmt.money(r.cost) }, { label: "Saving", num: true, render: (r) => h("span", { class: "saving", text: fmt.money2(r.estimated_monthly_saving) }) }], cud.spot_candidates),
    assumptions(cud.assumptions),
  ]));
}

function storage(grid) {
  const c = state.cost, b = c.buckets, w = c.storage_waste;
  grid.appendChild(tile("s3", "Cloud Storage cost", b.total_storage_cost, fmt.money, c.buckets.month, "storage"));
  grid.appendChild(tile("s3", "Buckets", b.by_bucket.length, fmt.num, `${w.buckets_without_lifecycle_rules.length} without lifecycle rules`, "storage"));
  grid.appendChild(tile("s3", "Possible saving", w.total_estimated_monthly_saving, fmt.money, `${fmt.pct(w.pct_of_storage_cost)} of storage · estimate`, "savings"));
  grid.appendChild(tile("s3", "High-egress buckets", w.high_egress.length, fmt.num, w.high_egress.map((x) => x.bucket).join(", ") || "none", "trend"));

  const keys = [{ key: "storage", label: "Storage", color: slot(1) }, { key: "ops", label: "Operations", color: slot(2) }, { key: "egress", label: "Egress", color: slot(3) }];
  grid.appendChild(card("s7", "Cost by bucket", "Split into storage, operations and egress", [stackedHbars(b.by_bucket.map((x) => ({
    label: x.name, sub: `${x.storage_class} · ${fmt.num(x.current_gb)} GB`, parts: { storage: x.storage_cost, ops: x.operations_cost, egress: x.egress_cost } })), keys)]));
  grid.appendChild(card("s5", "Cost type", null, [shareBar([
    { label: "Storage", value: b.storage_cost, color: slot(1) },
    { label: "Operations", value: b.operations_cost, color: slot(2) },
    { label: "Egress", value: b.egress_cost, color: slot(3) },
  ])]));

  grid.appendChild(card("s7", "Move cold data to a cheaper class", null, [table([
    { label: "Bucket", render: (r) => h("div", {}, [h("div", { class: "item-title", text: r.bucket }), h("div", { class: "card-sub", text: r.project })]) },
    { label: "Change", render: (r) => h("span", {}, [h("span", { class: "badge", text: r.current_class }), " → ", h("span", { class: "badge accent", text: r.target_class })]) },
    { label: "Cold data", num: true, render: (r) => `${fmt.num(r.cold_gb)} GB` },
    { label: "Last read", num: true, render: (r) => `${r.cold_data_last_read_days} days` },
    { label: "Saving", num: true, render: (r) => h("span", { class: "saving", text: fmt.money2(r.estimated_monthly_saving) + "/mo" }) },
  ], w.class_changes)]));
  grid.appendChild(card("s5", "Cleanups and flags", null, [
    h("div", { class: "stack" }, [
      ...w.cleanups.map((x) => h("div", { class: "item" }, [
        h("div", { class: "item-head" }, [h("span", { class: "item-title", text: x.bucket }), h("span", { class: "saving", text: fmt.money2(x.estimated_monthly_saving) + "/mo" })]),
        h("div", { class: "item-meta", text: [x.noncurrent_gb ? `${fmt.num(x.noncurrent_gb)} GB old versions` : null, x.deletable_gb ? `${fmt.num(x.deletable_gb)} GB deletable` : null].filter(Boolean).join(" · ") }),
      ])),
      ...w.high_egress.map((x) => h("div", { class: "item" }, [
        h("div", { class: "item-head" }, [h("span", { class: "item-title", text: x.bucket }), h("span", { class: "badge", text: "High egress" })]),
        h("div", { class: "item-meta", text: `${fmt.money(x.egress_cost)} egress · ${fmt.pct(x.egress_pct_of_bucket)} of the bucket's cost · consider Cloud CDN` }),
      ])),
      h("div", { class: "item" }, [
        h("div", { class: "item-title", text: "No lifecycle rules" }),
        h("div", { class: "item-meta", text: w.buckets_without_lifecycle_rules.join(", ") }),
      ]),
    ]),
    assumptions(w.assumptions),
  ]));
}

function savings(grid) {
  const sv = state.cost.savings;
  const bySvc = {};
  sv.opportunities.forEach((o) => { bySvc[o.service] = (bySvc[o.service] || 0) + o.estimated_monthly_saving; });
  const heroVal = h("div", { class: "tile-value" });
  countUp(heroVal, sv.total_estimated_monthly_saving, fmt.money);
  grid.appendChild(h("section", { class: "card tile hero s4" }, [
    h("div", { class: "tile-label", text: "Estimated savings per month" }), heroVal,
    h("span", { class: "delta", text: `${fmt.pct(sv.pct_of_total_bill)} of the bill` }),
    h("div", { class: "tile-foot", text: `${sv.opportunities.length} opportunities · all are estimates` }),
  ]));
  grid.appendChild(card("s8", "Savings by service", sv.not_covered, [shareBar(Object.entries(bySvc).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ label: k, value: v, color: serviceColor(k) })), fmt.money)]));
  grid.appendChild(card("s12", "All opportunities, ranked", "Each one names the agent skill that explains it", [
    hbars(sv.opportunities.map((o) => ({ label: o.title.split(": ")[1] || o.title, sub: o.service, value: o.estimated_monthly_saving, color: serviceColor(o.service),
      display: `${fmt.money(o.estimated_monthly_saving)}/mo · ${o.pct_of_service_cost === null ? "" : fmt.pct(o.pct_of_service_cost) + " of service"}`, tipLabel: o.basis }))),
  ]));
  grid.appendChild(card("s12", "Details", null, [table([
    { label: "Opportunity", render: (r) => h("div", {}, [h("div", { class: "item-title", text: r.title }), h("div", { class: "card-sub", text: r.basis })]) },
    { label: "Skill", render: (r) => h("span", { class: "badge accent", text: r.skill }) },
    { label: "Saving / month", num: true, render: (r) => h("span", { class: "saving", text: fmt.money2(r.estimated_monthly_saving) }) },
  ], sv.opportunities)]));
}

const METRIC_SCALE = { "vm.cpu": 100, "vm.memory": 1, "gke.cpu": 100, "gke.memory": 100 };

function monitoring(grid) {
  if (!obsOnline()) { grid.appendChild(offlineCard("s12")); return; }
  const m = state.monitor, o = state.obs;
  const data = o[`${m.kind}_${m.metric}`];
  const seg = (opts, cur, onPick) => h("div", { class: "segmented" }, opts.map(([v, l]) => {
    const b = h("button", { class: v === cur ? "active" : "", text: l });
    b.addEventListener("click", () => { onPick(v); render(); });
    return b;
  }));
  const controls = h("div", { class: "controls s12", style: { marginBottom: "0" } }, [
    seg([["vm", "VMs"], ["gke", "GKE workloads"]], m.kind, (v) => { m.kind = v; m.selected = null; }),
    seg([["cpu", "CPU"], ["memory", "Memory"]], m.metric, (v) => { m.metric = v; m.selected = null; }),
    h("span", { class: "muted", text: `Last ${state.hours}h · change the range at the top` }),
  ]);
  grid.appendChild(controls);
  if (data.status !== "ok") { grid.appendChild(card("s12", "No data", null, [emptyState(data.message)])); return; }

  grid.appendChild(tile("s3", "Resources", data.resource_count, fmt.num, data.metric_type, "cpu"));
  grid.appendChild(tile("s3", "High usage", data.high_count, fmt.num, "peak ≥ 80%", "alert"));
  grid.appendChild(tile("s3", "Idle", data.idle_count, fmt.num, "average < 5%", "monitoring"));
  grid.appendChild(tile("s3", "Metric types tracked", o.metrics.metric_count || 0, fmt.num, `project ${o.project}`, "monitoring"));

  const sel = data.resources.find((r) => r.resource === m.selected) || data.resources[0];
  m.selected = sel.resource;
  grid.appendChild(card("s5", "Usage by resource", "Click a row to see it over time", [table([
    { label: "Resource", render: (r) => h("span", { class: "item-title", text: r.resource }) },
    { label: "Average", render: (r) => h("div", { style: { minWidth: "100px" } }, [meter(r.avg_pct, statusColor(r.flag), r.peak_pct), h("div", { class: "card-sub", text: `${fmt.pct(r.avg_pct)} avg · ${fmt.pct(r.peak_pct)} peak` })]) },
    { label: "Status", render: (r) => statusChip(r.flag) },
  ], data.resources, { onClick: (r) => { m.selected = r.resource; render(); }, isSelected: (r) => r.resource === m.selected })]));

  const chartBox = h("div", {}, [h("div", { class: "empty", text: "Loading…" })]);
  grid.appendChild(card("s7", `${sel.resource}`, `${m.metric === "cpu" ? "CPU" : "Memory"} use over time (%)`, [
    h("div", { style: { display: "flex", gap: "8px", marginBottom: "10px", flexWrap: "wrap" } }, [
      statusChip(sel.flag), h("span", { class: "badge", text: `avg ${fmt.pct(sel.avg_pct)}` }), h("span", { class: "badge", text: `peak ${fmt.pct(sel.peak_pct)}` }), h("span", { class: "badge", text: `latest ${fmt.pct(sel.latest_pct)}` }),
    ]),
    chartBox,
    h("div", { class: "card-sub", style: { marginTop: "8px" }, text: "Red line = 80% high threshold." }),
  ]));
  const scale = METRIC_SCALE[`${m.kind}.${m.metric}`];
  getJSON(`/api/timeseries?metric_type=${encodeURIComponent(data.metric_type)}&resource=${encodeURIComponent(sel.resource)}&hours=${state.hours}`).then((ts) => {
    if (ts.status !== "ok") { chartBox.replaceChildren(emptyState(ts.message)); return; }
    const series = ts.series.find((x) => x.resource === sel.resource) || ts.series[0];
    chartBox.replaceChildren(lineChart([{ name: sel.resource, color: statusColor(sel.flag === "high" ? "high" : "normal"), points: series.points.map((p) => ({ t: p.time, v: Math.round(p.value * scale * 10) / 10 })) }],
      { yMax: 100, threshold: 80, thresholdLabel: "80%", valueFormat: fmt.pct, yFormat: (v) => v + "%", label: `${sel.resource} usage over time` }));
  }).catch((e) => chartBox.replaceChildren(emptyState("Could not load the time series.", String(e))));

  grid.appendChild(card("s12", "Metrics in Cloud Monitoring", `${o.metrics.metric_count} metric types with data`, [h("div", { class: "tools" }, (o.metrics.metrics || []).map((x) => h("span", { class: "tool", text: x })))]));
}

function logging(grid) {
  if (!obsOnline()) { grid.appendChild(offlineCard("s12")); return; }
  const o = state.obs, ls = o.log_summary, sev = ls.by_severity;
  const errorsTotal = Object.entries(sev).filter(([k]) => ["ERROR", "CRITICAL", "ALERT", "EMERGENCY"].includes(k)).reduce((a, [, v]) => a + v, 0);
  grid.appendChild(tile("s3", `Log entries · ${state.hours}h`, ls.total_entries, fmt.num, `${ls.by_resource.length} resources`, "logging"));
  grid.appendChild(tile("s3", "Errors and worse", errorsTotal, fmt.num, `${o.errors.distinct_errors} distinct messages`, "alert"));
  grid.appendChild(tile("s3", "Critical", sev.CRITICAL || 0, fmt.num, "most urgent", "alert"));
  grid.appendChild(tile("s3", "Warnings", sev.WARNING || 0, fmt.num, "may lead to errors", "monitoring"));

  const { buckets, mins } = logBuckets();
  grid.appendChild(card("s8", "Warnings and errors over time", `${mins}-minute buckets`, [stackedColumns(buckets, SEV_KEYS(), { label: "Warnings and errors over time" })]));
  const sevOrder = ["CRITICAL", "ERROR", "WARNING", "NOTICE", "INFO", "DEBUG", "DEFAULT"];
  grid.appendChild(card("s4", "By severity", null, [shareBar(sevOrder.filter((k) => sev[k]).map((k) => ({ label: k, value: sev[k], color: sevColor(k) })), fmt.num)]));

  const resRows = ls.by_resource.filter((r) => r.errors || r.warnings);
  grid.appendChild(card("s6", "Problems by resource", "Errors and warnings per resource", [stackedHbars(resRows.map((r) => ({
    label: r.resource.split("/").pop(), sub: r.resource, parts: { errors: r.errors, warnings: r.warnings } })),
    [{ key: "errors", label: "Errors", color: sevColor("ERROR") }, { key: "warnings", label: "Warnings", color: sevColor("WARNING") }], { format: fmt.num })]));
  grid.appendChild(card("s6", "Top errors", "Grouped by message, most frequent first", [errorList(o.errors.top_errors)]));

  // Search
  const ls2 = state.logSearch;
  const q = h("input", { class: "input grow", placeholder: "Search text, e.g. timeout", value: ls2.query, "aria-label": "Search text" });
  const sevSel = h("select", { class: "input", "aria-label": "Minimum severity" }, [["", "Any severity"], ["INFO", "INFO and up"], ["WARNING", "WARNING and up"], ["ERROR", "ERROR and up"], ["CRITICAL", "CRITICAL"]]
    .map(([v, l]) => h("option", { value: v, text: l, selected: v === ls2.severity ? "selected" : null })));
  const resIn = h("input", { class: "input", placeholder: "Resource, e.g. checkout", value: ls2.resource, "aria-label": "Resource" });
  const results = h("div", {});
  const run = async () => {
    Object.assign(ls2, { query: q.value.trim(), severity: sevSel.value, resource: resIn.value.trim() });
    results.style.opacity = 0.5;
    const p = new URLSearchParams({ hours: state.hours, limit: 100 });
    if (ls2.query) p.set("query", ls2.query);
    if (ls2.severity) p.set("severity", ls2.severity);
    if (ls2.resource) p.set("resource", ls2.resource);
    try {
      const r = await getJSON(`/api/logs?${p}`);
      if (r.status !== "ok") { results.replaceChildren(emptyState(r.message)); return; }
      results.replaceChildren(
        h("div", { class: "card-sub", style: { marginBottom: "8px" }, text: `${r.match_count} matches · showing ${r.shown}` }),
        r.entries.length ? table([
          { label: "Time", render: (e) => h("span", { class: "muted", text: fmt.dateTime(e.time) }) },
          { label: "Severity", render: (e) => sevChip(e.severity) },
          { label: "Resource", render: (e) => h("span", { text: e.resource }) },
          { label: "Message", render: (e) => h("span", { text: e.message }) },
        ], r.entries) : emptyState("No log entries match."),
      );
    } catch (e) { results.replaceChildren(emptyState("Search failed.", String(e))); }
    finally { results.style.opacity = 1; }
  };
  let timer;
  [q, resIn].forEach((el) => el.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 300); }));
  sevSel.addEventListener("change", run);
  grid.appendChild(card("s12", "Search logs", `Last ${state.hours}h · newest first`, [h("div", { class: "controls" }, [q, sevSel, resIn]), results]));
  run();
}

function agentView(grid) {
  const a = state.agent;
  const cost = a.tools.filter((t) => t.group === "cost"), obs = a.tools.filter((t) => t.group === "observability");
  const chg = a.tools.filter((t) => t.group === "changes");
  grid.appendChild(tile("s3", "Skills", a.skills.length, fmt.num, `${a.skills.filter((x) => x.source === "Google").length} Google · ${a.skills.filter((x) => x.source === "Custom").length} custom`, "agent"));
  grid.appendChild(tile("s3", "Tools", a.tools.length, fmt.num, `${cost.length} cost · ${obs.length} monitoring and logging · ${chg.length} changes`, "cpu"));
  grid.appendChild(tile("s3", "MCP servers", 1, fmt.num, "gcp-sre-mcp", "cloud"));
  grid.appendChild(tile("s3", "Approved changes applied", state.changes?.history?.counts?.applied || 0, fmt.num, "only after your approval", "changes"));

  grid.appendChild(card("s12", "How it works", "A Deep Agents + Gemini agent. Skills say how to think, the MCP server's tools fetch the facts.", [h("div", { class: "arch" }, [archDiagram(a)])]));
  grid.appendChild(card("s12", "Skills", "Loaded on demand from skills/", [h("div", { class: "skills" }, a.skills.map((x, i) => h("div", { class: "skill", style: { animationDelay: i * 0.04 + "s" } }, [
    h("div", { class: "item-head" }, [h("span", { class: "skill-name", text: x.name }), h("span", { class: "badge " + (x.source === "Custom" ? "accent" : ""), text: x.source })]),
    h("div", { class: "skill-desc", text: x.description }),
  ])))]));
  const toolChips = (list) => h("div", { class: "tools" }, list.map((t) => hoverable(h("span", { class: "tool", text: t.name }), () => ({ title: t.name, rows: [{ value: t.description }] }))));
  grid.appendChild(card("s8", "Tools on the MCP server", "Hover a tool to see what it does", [
    h("div", { class: "card-title", style: { margin: "0 0 8px" }, text: `Cost · ${cost.length} · ${a.cost_source}` }), toolChips(cost),
    h("div", { class: "card-title", style: { margin: "16px 0 8px" }, text: `Monitoring and logging · ${obs.length} · floci-gcp` }), toolChips(obs),
    h("div", { class: "card-title", style: { margin: "16px 0 8px" }, text: `Changes \u00b7 ${chg.length} \u00b7 apply_change needs your approval` }), toolChips(chg),
  ]));
  const questions = ["Why did our GCP costs go up?", "Where can we save the most?", "Which VMs have high CPU?", "Show me recent errors and find the root cause.", "Which GKE workloads are over-provisioned?"];
  grid.appendChild(card("s4", "Ask the agent", "Opens the Chat page", [h("div", { class: "stack" }, questions.map((qq) => h("div", { class: "question" }, [h("span", { text: qq }), askInChat(qq)])))]));
}

function archDiagram(a) {
  const W = 960, H = 300;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Architecture: user, Deep Agents agent, skills, MCP server, data sources" });
  const node = (x, y, w, hgt, title, sub, main) => {
    const g = s("g", { class: "node" + (main ? " main" : "") });
    g.appendChild(s("rect", { x, y, width: w, height: hgt, rx: 12 }));
    g.appendChild(s("text", { x: x + w / 2, y: y + hgt / 2 - (sub ? 4 : -5), text: title }));
    if (sub) g.appendChild(s("text", { class: "sub", x: x + w / 2, y: y + hgt / 2 + 14, text: sub }));
    return g;
  };
  const flow = (d, alt) => s("path", { class: "flow" + (alt ? " alt" : ""), d });
  [
    flow("M150 150 H210"), flow("M390 120 C440 120 440 70 490 70"), flow("M390 180 C440 180 440 230 490 230"),
    flow("M690 230 C730 230 730 110 770 110", true), flow("M690 230 C730 230 730 210 770 210", true),
  ].forEach((p) => svg.appendChild(p));
  svg.appendChild(node(20, 115, 130, 70, "You", "ask a question"));
  svg.appendChild(node(210, 100, 180, 100, "Deep Agents", "Gemini · agent.py", true));
  svg.appendChild(node(490, 35, 200, 70, `Skills (${a.skills.length})`, "how to think"));
  svg.appendChild(node(490, 195, 200, 70, "MCP server", `gcp-sre-mcp · ${a.tools.length} tools`, true));
  svg.appendChild(node(770, 75, 170, 70, a.cost_source === "mock data" ? "Mock JSON" : "BigQuery", a.cost_source === "mock data" ? "cost data" : "billing export"));
  svg.appendChild(node(770, 175, 170, 70, "floci-gcp", "monitoring · logging"));
  svg.appendChild(s("text", { x: 820, y: 285, "text-anchor": "middle", fill: css("--text-muted"), "font-size": 11, text: "later: real GCP APIs" }));
  return svg;
}

const CHANGE_STATUS = {
  applied: ["normal", "✓ Applied"],
  proposed: ["WARNING", "◆ Waiting for approval"],
  failed: ["high", "✕ Failed"],
  cancelled: ["idle", "– Cancelled"],
  expired: ["idle", "◌ Expired"],
};

function changeChip(status) {
  const [cls, label] = CHANGE_STATUS[status] || ["idle", status];
  return h("span", { class: "chip " + cls, text: label });
}

function diffText(before, after) {
  const parts = [];
  for (const k of Object.keys(after || {})) {
    const b = JSON.stringify(before?.[k]), a = JSON.stringify(after[k]);
    if (b === a) continue;
    if (k === "lifecycle_rules") parts.push(`lifecycle rules ${before?.[k]?.length || 0} → ${after[k].length}`);
    else parts.push(`${k.replace("_", " ")}: ${before?.[k] ?? "—"} → ${after[k]}`);
  }
  return parts.join(" · ") || "no state change (restart)";
}

function changesView(grid) {
  const data = state.changes;
  if (!data || data.history.status !== "ok") { grid.appendChild(card("s12", "Changes", null, [emptyState("Could not load the change history.")])); return; }
  const counts = data.history.counts || {};
  grid.appendChild(h("div", { class: "banner ok s12" }, [
    h("div", { class: "banner-icon" }, [icon("check")]),
    h("div", { class: "banner-body" }, [
      h("div", { class: "banner-title", text: "Changes happen only after your approval" }),
      h("div", { class: "banner-text", text: "The agent proposes a change (nothing happens). It waits until you approve or cancel it in the Chat page, even days later: use Open chat. Before an older change is applied, the agent re-checks it, and you confirm once more. No deletes. floci-gcp only." }),
    ]),
  ]));
  grid.appendChild(tile("s3", "Applied", counts.applied || 0, fmt.num, "after approval", "check"));
  grid.appendChild(tile("s3", "Waiting for approval", counts.proposed || 0, fmt.num, "until you approve or cancel", "changes"));
  grid.appendChild(tile("s3", "Cancelled or expired", (counts.cancelled || 0) + (counts.expired || 0), fmt.num, "never applied", "changes"));
  grid.appendChild(tile("s3", "Failed", counts.failed || 0, fmt.num, "see the error in the history", "alert"));

  const rows = data.history.changes;
  grid.appendChild(card("s12", "Change history", "Newest first · saved in changes.jsonl", [rows.length ? table([
    { label: "Change", render: (c) => h("div", {}, [h("div", { class: "item-title", text: c.summary }), h("div", { class: "card-sub", text: `${c.id}${c.reason ? " · " + c.reason : ""}` })]) },
    { label: "Status", render: (c) => changeChip(c.status) },
    { label: "Before → after", render: (c) => h("span", { class: "secondary", text: c.error ? c.error : diffText(c.before, c.result || c.after) }) },
    { label: "Proposed", render: (c) => h("span", { class: "muted", text: c.proposed_at ? fmt.dateTime(c.proposed_at) : "" }) },
    { label: "Applied", render: (c) => h("span", { class: "muted", text: c.applied_at ? fmt.dateTime(c.applied_at) : "—" }) },
    { label: "Chat", render: (c) => c.status === "proposed"
      ? h("button", { class: "btn primary", title: "Open the chat to approve or cancel", onclick: () => openChat(c.id) }, [icon("chat"), "Open chat"])
      : data.chat_links && data.chat_links[c.id]
        ? h("button", { class: "btn", title: "See the chat that proposed it", onclick: () => openChat(c.id) }, [icon("chat"), "View chat"])
        : h("span", { class: "muted", text: "—" }) },
  ], rows) : emptyState("No changes yet. Ask the agent in the Chat page, for example: “Restart db-proxy”.")]));

  const inv = data.inventory;
  if (inv.status !== "ok") { grid.appendChild(offlineCard("s12")); return; }
  grid.appendChild(card("s7", "Virtual machines", `From floci-gcp · ${inv.project}`, [table([
    { label: "VM", render: (v) => h("span", { class: "item-title", text: v.name }) },
    { label: "Zone", key: "zone" },
    { label: "Machine type", render: (v) => h("span", { class: "badge", text: v.machine_type }) },
    { label: "Status", render: (v) => h("span", { class: "chip " + (v.status === "RUNNING" ? "normal" : "idle"), text: v.status === "RUNNING" ? "● Running" : "■ " + v.status }) },
  ], inv.vms)]));
  grid.appendChild(card("s5", "Buckets", "From floci-gcp", [table([
    { label: "Bucket", render: (b) => h("span", { class: "item-title", text: b.name }) },
    { label: "Class", render: (b) => h("span", { class: "badge" + (b.storage_class === "STANDARD" ? "" : " accent"), text: b.storage_class }) },
    { label: "Lifecycle rules", num: true, render: (b) => String(b.lifecycle_rules.length) },
  ], inv.buckets)]));
  const questions = ["Restart db-proxy.", "Resize web-vm-1 to n2-standard-4.", "Move prod-db-backups to Coldline.", "Add a rule to prod-logs-archive: objects older than 365 days go to Archive."];
  grid.appendChild(card("s12", "Try it in the Chat page", "The agent will propose first and wait for your approval", [h("div", { class: "stack" }, questions.map((q) => h("div", { class: "question" }, [h("span", { text: q }), askInChat(q)])))]));
}

/* ---------- Chat (Deep Agents) ---------- */

const CHAT_KEY = "sre-chat";
const CHAT_QUESTIONS = [
  "Why did our costs go up?",
  "Find the root cause of the errors in the last 24 hours, propose a fix, and wait for my approval.",
  "Where can we save the most?",
  "Which VMs have high CPU?",
];

function loadChat() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(CHAT_KEY) || "null");
    if (saved && Array.isArray(saved.messages)) return { thread: saved.thread || null, messages: saved.messages, pending: saved.pending || null, focus: saved.focus || null };
  } catch (e) { /* storage blocked */ }
  return { thread: null, messages: [], pending: null, focus: null };
}

function saveChat() {
  const c = state.chat;
  try { sessionStorage.setItem(CHAT_KEY, JSON.stringify({ thread: c.thread, messages: c.messages, pending: c.pending, focus: c.focus })); } catch (e) { /* storage blocked */ }
}

async function postJSON(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  let data = null;
  try { data = await r.json(); } catch (e) { /* no body */ }
  if (!r.ok) throw new Error((data && data.detail) || `${url}: ${r.status}`);
  return data;
}

function chatRerender() {
  if (state.route !== "chat") return;
  render();
  const box = document.querySelector(".chat-log");
  if (box) box.scrollTop = box.scrollHeight;
  const input = document.getElementById("chat-input");
  if (input && !input.disabled) input.focus({ preventScroll: true });
}

function addAgentReply(r) {
  const c = state.chat;
  c.thread = r.thread_id;
  if (r.answer || r.steps.length || r.error) c.messages.push({ role: "agent", text: r.answer || "", steps: r.steps, error: r.error });
  c.pending = r.approval;
}

async function chatSend(text) {
  const c = state.chat;
  text = (text || "").trim();
  if (!text || c.busy || c.pending) return;
  c.messages.push({ role: "user", text });
  c.draft = "";
  c.busy = true;
  saveChat(); chatRerender();
  try {
    addAgentReply(await postJSON("/api/chat", { message: text, thread_id: c.thread }));
  } catch (e) {
    c.messages.push({ role: "agent", text: "", steps: [], error: String(e.message || e) });
  } finally {
    c.busy = false;
    saveChat(); chatRerender();
    refreshChanges();
  }
}

async function chatDecide(decision) {
  const c = state.chat;
  if (!c.pending || c.busy) return;
  const id = c.pending.change_id;
  c.messages.push({ role: "user", text: decision === "approve" ? `Clicked Approve for ${id}` : `Clicked Reject for ${id}`, click: true });
  c.busy = true;
  saveChat(); chatRerender();
  try {
    addAgentReply(await postJSON("/api/chat/approve", { thread_id: c.thread, change_id: id, decision }));
  } catch (e) {
    c.messages.push({ role: "agent", text: "", steps: [], error: String(e.message || e) });
  } finally {
    c.busy = false;
    saveChat();
    loadAll(); // refresh Changes, Overview and the nav badges
  }
}

function chatReset() {
  state.chat = { thread: null, messages: [], pending: null, focus: null, busy: false, draft: "" };
  saveChat(); chatRerender();
}

/* Reload only the change list (statuses, chat links), then redraw. */
async function refreshChanges() {
  if (window.SNAPSHOT) return;
  try { state.changes = await getJSON("/api/changes"); } catch (e) { return; }
  renderNav();
  if (state.route === "chat" || state.route === "changes") render();
}

/* Load a saved conversation from the server. */
async function loadThread(thread, focus) {
  const r = await getJSON(`/api/chat/thread/${encodeURIComponent(thread)}`);
  state.chat = { thread, messages: r.messages, pending: r.approval, focus: focus || null, busy: false, draft: "" };
  saveChat();
}

/* Changes page -> the chat that proposed this change (or a new chat about it). */
async function openChat(changeId) {
  if (state.chat.busy) { location.hash = "chat"; return; }
  const thread = state.changes?.chat_links?.[changeId];
  try {
    if (thread) await loadThread(thread, changeId);
    else state.chat = { thread: null, messages: [], pending: null, focus: changeId, busy: false, draft: "" };
  } catch (e) {
    state.chat = { thread: null, messages: [], pending: null, focus: changeId, busy: false, draft: "" };
  }
  saveChat();
  if (location.hash === "#chat") chatRerender(); else location.hash = "chat";
}

/* Approve / Cancel buttons for a change that is waiting (new or old). */
async function chatChangeAction(change, action) {
  const c = state.chat;
  if (c.busy || c.pending) return;
  c.messages.push({ role: "user", text: `Clicked ${action === "approve" ? "Approve" : "Cancel"} for ${change.id}`, click: true });
  c.busy = true;
  saveChat(); chatRerender();
  try {
    addAgentReply(await postJSON("/api/chat/change", { change_id: change.id, action, thread_id: c.thread }));
  } catch (e) {
    c.messages.push({ role: "agent", text: "", steps: [], error: String(e.message || e) });
  } finally {
    c.busy = false;
    saveChat(); chatRerender();
    refreshChanges();
  }
}

/* Changes waiting for approval that belong to this chat (or that the user opened it for). */
function waitingChanges() {
  const c = state.chat;
  const rows = state.changes?.history?.changes || [];
  const links = state.changes?.chat_links || {};
  return rows.filter((r) => r.status === "proposed" && ((c.thread && links[r.id] === c.thread) || r.id === c.focus));
}

function askInChat(q) {
  const b = h("button", { class: "btn", title: "Ask this in the Chat page" }, [icon("chat"), "Ask"]);
  b.addEventListener("click", () => { location.hash = "chat"; setTimeout(() => chatSend(q), 0); });
  return b;
}

/* Small, safe markdown: text is escaped first, then only a few tags are added. */
function md(text) {
  const esc = (t) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = (t) => esc(t)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
  const lines = String(text).replace(/\r/g, "").split("\n");
  const out = [];
  let list = null, para = [];
  const flushPara = () => { if (para.length) { out.push(`<p>${para.map(inline).join("<br>")}</p>`); para = []; } };
  const flushList = () => { if (list) { out.push(`<${list.tag}>${list.items.map((x) => `<li>${inline(x)}</li>`).join("")}</${list.tag}>`); list = null; } };
  const flush = () => { flushPara(); flushList(); };
  for (let i = 0; i < lines.length; i++) {
    const t = lines[i].trim();
    if (t.startsWith("```")) {
      flush();
      const code = [];
      while (++i < lines.length && !lines[i].trim().startsWith("```")) code.push(lines[i]);
      out.push(`<pre>${esc(code.join("\n"))}</pre>`);
    } else if (t.startsWith("|")) {
      flush();
      const rows = [];
      for (; i < lines.length && lines[i].trim().startsWith("|"); i++) rows.push(lines[i].trim());
      i--;
      const cells = (r) => r.replace(/^\||\|$/g, "").split("|").map((x) => x.trim());
      const [head, ...rest] = rows.filter((r) => !/^\|[\s:|-]+\|?$/.test(r));
      if (head) out.push(`<div class="table-wrap"><table><thead><tr>${cells(head).map((x) => `<th>${inline(x)}</th>`).join("")}</tr></thead><tbody>${rest.map((r) => `<tr>${cells(r).map((x) => `<td>${inline(x)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
    } else if (/^#{1,6}\s/.test(t)) {
      flush(); out.push(`<h4>${inline(t.replace(/^#+\s*/, ""))}</h4>`);
    } else if (/^(-{3,}|\*{3,})$/.test(t)) {
      flush(); out.push("<hr>");
    } else if (/^[-*]\s+/.test(t)) {
      flushPara();
      if (!list || list.tag !== "ul") { flushList(); list = { tag: "ul", items: [] }; }
      list.items.push(t.replace(/^[-*]\s+/, ""));
    } else if (/^\d+\.\s+/.test(t)) {
      flushPara();
      if (!list || list.tag !== "ol") { flushList(); list = { tag: "ol", items: [] }; }
      list.items.push(t.replace(/^\d+\.\s+/, ""));
    } else if (!t) {
      flush();
    } else {
      flushList(); para.push(t);
    }
  }
  flush();
  const div = h("div", { class: "md" });
  div.innerHTML = out.join("");
  return div;
}

function chatMessage(m) {
  if (m.role === "user") return h("div", { class: "msg user" + (m.click ? " click" : "") }, [h("div", { class: "bubble", text: m.text })]);
  const parts = [];
  if (m.steps && m.steps.length) {
    const calls = m.steps.filter((x) => x.startsWith("->"));
    const notes = m.steps.length - calls.length;
    parts.push(h("details", { class: "steps" }, [
      h("summary", { text: `${calls.length} tool call${calls.length === 1 ? "" : "s"}${notes ? ` · ${notes} retry note${notes === 1 ? "" : "s"}` : ""}` }),
      h("div", { class: "steps-list" }, m.steps.map((x) => h("div", { text: x.replace(/^->\s*/, "") }))),
    ]));
  }
  if (m.text) parts.push(md(m.text));
  if (m.error) parts.push(h("div", { class: "chat-error", text: m.error }));
  return h("div", { class: "msg agent" }, [h("div", { class: "bubble" }, parts)]);
}

function chatView(grid) {
  const c = state.chat;
  const a = state.agent || {};
  const sub = a.model ? `Deep Agents + ${a.model}${a.fallbacks && a.fallbacks.length ? " · backups: " + a.fallbacks.join(", ") : ""}` : "Deep Agents + Gemini";
  const log = h("div", { class: "chat-log", "aria-live": "polite" });
  if (!c.messages.length) {
    log.appendChild(h("div", { class: "chat-empty" }, [
      h("div", { class: "card-sub", text: "Ask about costs, usage, errors or incidents. Changes always wait for your click on Approve." }),
      h("div", { class: "stack" }, CHAT_QUESTIONS.map((q) => h("button", { class: "question chat-suggest", text: q, onclick: () => chatSend(q) }))),
    ]));
  }
  c.messages.forEach((m) => log.appendChild(chatMessage(m)));
  if (c.busy) log.appendChild(h("div", { class: "msg agent" }, [h("div", { class: "bubble thinking", text: "The agent is working. This can take a minute…" })]));

  const body = [log];
  if (!c.pending) {
    for (const w of waitingChanges()) {
      body.push(h("div", { class: "approval" }, [
        h("div", { class: "approval-text" }, [
          h("div", { class: "banner-title", text: `${w.id} is waiting for your approval` }),
          h("div", { class: "banner-text", text: `${w.summary} · proposed ${fmt.ago(w.proposed_at)}. Approve asks the agent to check it is still needed, then you confirm once more. Cancel drops it.` }),
        ]),
        h("div", { class: "approval-actions" }, [
          h("button", { class: "btn primary", disabled: c.busy || undefined, onclick: () => chatChangeAction(w, "approve") }, [icon("check"), `Approve ${w.id}`]),
          h("button", { class: "btn", disabled: c.busy || undefined, onclick: () => chatChangeAction(w, "cancel") }, ["Cancel"]),
        ]),
      ]));
    }
  }
  if (c.pending) {
    const id = c.pending.change_id;
    body.push(h("div", { class: "approval" }, [
      h("div", { class: "approval-text" }, [
        h("div", { class: "banner-title", text: `Final check: apply ${id} now?` }),
        h("div", { class: "banner-text", text: "Nothing has changed yet. Approve runs it on the local floci emulator. Reject cancels it." }),
      ]),
      h("div", { class: "approval-actions" }, [
        h("button", { class: "btn primary", disabled: c.busy || undefined, onclick: () => chatDecide("approve") }, [icon("check"), `Approve ${id}`]),
        h("button", { class: "btn", disabled: c.busy || undefined, onclick: () => chatDecide("reject") }, ["Reject"]),
      ]),
    ]));
  }
  const locked = c.busy || !!c.pending;
  const input = h("textarea", {
    id: "chat-input", rows: 2, class: "chat-input",
    placeholder: c.pending ? "Approve or reject the change first" : "Ask the agent…  (Enter to send, Shift+Enter for a new line)",
    disabled: locked || undefined,
    "aria-label": "Message to the agent",
  });
  input.value = c.draft || "";
  input.addEventListener("input", () => { c.draft = input.value; });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); chatSend(input.value); } });
  const send = h("button", { class: "btn primary", disabled: locked || undefined, onclick: () => chatSend(input.value) }, ["Send"]);
  body.push(h("div", { class: "chat-form" }, [input, send]));

  const reset = h("button", { class: "btn", title: "Start a new conversation", disabled: c.busy || undefined, onclick: chatReset }, ["New chat"]);
  grid.appendChild(card("s12 chat-card", "Chat with the agent", sub, body, [reset]));
}

/* ---------- Events ---------- */

function route() {
  const id = (location.hash || "#overview").slice(1);
  state.route = NAV.some((n) => n.id === id) ? id : "overview";
  renderChrome();
  render();
  document.getElementById("view").focus({ preventScroll: true });
  window.scrollTo({ top: 0 });
}

function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("theme"); } catch (e) { /* storage blocked */ }
  if (saved) document.documentElement.dataset.theme = saved;
  document.getElementById("theme").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) { /* storage blocked */ }
    render();
  });
}

document.getElementById("range").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-hours]");
  if (!b) return;
  state.hours = Number(b.dataset.hours);
  document.querySelectorAll("#range button").forEach((x) => x.classList.toggle("active", x === b));
  loadAll();
});
document.getElementById("refresh").addEventListener("click", () => loadAll());
window.addEventListener("hashchange", route);
initTheme();
state.chat = { ...loadChat(), busy: false, draft: "" };
if (state.chat.thread && !window.SNAPSHOT) loadThread(state.chat.thread, state.chat.focus).then(chatRerender).catch(() => {});
state.route = (location.hash || "#overview").slice(1);
if (!NAV.some((n) => n.id === state.route)) state.route = "overview";
renderNav();
loadAll();
