"use strict";

/* Sensewright web panel — vanilla, dependency-free. Talks to /v1/* with the
   shared token disclosed by GET /ui/session (loopback only). */

const S = {
  token: null,
  lang: "en",
  locales: [],
  strings: {},   // panel + control-label strings for the active locale
  version: "",
  tab: "status",
  controls: [],  // ControlSpec list
  values: {},    // current control values
  dirty: {},     // edited control values
  timer: null,
  auto: true,    // status auto-refresh
};

const $ = (sel, root = document) => root.querySelector(sel);

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function t(key, args) {
  let s = S.strings[key] || key;
  if (args) {
    for (const [k, v] of Object.entries(args)) s = s.replaceAll("{" + k + "}", String(v));
  }
  return s;
}

function tc(key) {
  return S.strings[key] || "";
}

function label(spec) {
  return tc(spec.label_key) || spec.key;
}

function pretty(key) {
  return String(key).split(".").pop().replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

let toastTimer = null;
function toast(msg, isError) {
  const box = $("#toast");
  box.textContent = msg;
  box.classList.toggle("err", !!isError);
  box.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.classList.add("hidden"), 3500);
}

function applyI18n() {
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.getAttribute("data-i18n"));
  });
  document.title = t("web.title");
}

function setConn(state) {
  const dot = $("#connDot");
  dot.classList.remove("on", "off");
  if (state === "on") { dot.classList.add("on"); $("#connText").textContent = t("web.online"); }
  else if (state === "off") { dot.classList.add("off"); $("#connText").textContent = t("web.offline"); }
  else { $("#connText").textContent = "…"; }
}

function needToken() {
  $("#tokenBar").classList.remove("hidden");
}

function saveToken() {
  const value = $("#tokenInput").value.trim();
  if (!value) return;
  S.token = value;
  localStorage.setItem("sw_token", value);
  $("#tokenBar").classList.add("hidden");
  renderTab();
}

/* ── API ─────────────────────────────────────────────────────────────── */

async function api(path, opts) {
  const { method = "GET", body = null, auth = true } = opts || {};
  const headers = {};
  if (body !== null) headers["Content-Type"] = "application/json";
  if (auth && S.token) headers["X-Sensewright-Token"] = S.token;
  const res = await fetch(path, {
    method,
    headers,
    body: body !== null ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) { needToken(); throw new Error(t("web.token.invalid")); }
  if (!res.ok) throw new Error("HTTP " + res.status);
  return JSON.parse(quoteBigInts(await res.text()));
}

function quoteBigInts(text) {
  // The Sims 4 ids (~5.9e17) exceed JavaScript's safe-integer precision
  // (2^53), so JSON.parse would round them and collapse distinct Sims. Quote
  // 16+ digit object values so they survive as exact strings.
  return text.replace(/:\s*(-?\d{16,})(?=\s*[,}\]])/g, ': "$1"');
}

// Discover the active save from the sidecar when the panel has none yet.
async function detectContext() {
  const current = localStorage.getItem("sw_save_id");
  if (current && current !== "unknown") return;
  try {
    const status = await api("/v1/status");
    const active = (((status.agency || {}).seats) || {}).active || [];
    if (active.length) {
      localStorage.setItem("sw_save_id", String(active[0].save_id || "unknown"));
      localStorage.setItem("sw_player_id", String(active[0].player_id || "local"));
    }
  } catch (_) { /* best effort */ }
}

function ctxValue(key, fallback) {
  return localStorage.getItem(key) || fallback;
}

/* ── Boot ────────────────────────────────────────────────────────────── */

async function loadStrings(lang) {
  const candidates = [lang, "en"];
  for (const code of candidates) {
    try {
      const res = await fetch("/ui/locales/" + encodeURIComponent(code) + ".json");
      if (res.ok) { S.strings = await res.json(); return; }
    } catch (_) { /* try next */ }
  }
  S.strings = {};
}

async function boot() {
  let session;
  try {
    const res = await fetch("/ui/session");
    if (res.status === 404) return renderDisabled();
    if (!res.ok) throw new Error("HTTP " + res.status);
    session = await res.json();
  } catch (err) {
    setConn("off");
    $("#view").replaceChildren(el("div", "empty", t("web.offline")));
    return;
  }

  S.version = session.version || "";
  S.lang = session.lang || "en";
  S.locales = session.locales || [];
  S.token = session.token || localStorage.getItem("sw_token") || null;

  await loadStrings(S.lang);
  applyI18n();
  $("#version").textContent = S.version ? "v" + S.version : "";
  setConn("on");

  if (S.token) {
    $("#tokenBar").classList.add("hidden");
    await detectContext();
  } else {
    needToken();
  }

  bindTabs();
  bindToken();
  renderTab();
}

function renderDisabled() {
  setConn("off");
  const view = $("#view");
  view.replaceChildren();
  const card = el("div", "card");
  card.append(el("h2", null, t("web.disabled.title")));
  card.append(el("p", "muted", t("web.disabled.body")));
  view.append(card);
}

function bindToken() {
  $("#tokenSave").addEventListener("click", saveToken);
  $("#tokenInput").addEventListener("keydown", (e) => { if (e.key === "Enter") saveToken(); });
}

function bindTabs() {
  document.querySelectorAll("#tabs button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#tabs button").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      S.tab = btn.dataset.tab;
      renderTab();
    });
  });
}

function renderTab() {
  if (S.timer) { clearInterval(S.timer); S.timer = null; }
  const view = $("#view");
  view.replaceChildren(el("div", "loading", t("web.loading")));
  const fn = { status: renderStatus, controls: renderControls, roster: renderRoster, world: renderWorld, pending: renderPending }[S.tab];
  if (fn) { Promise.resolve(fn()).catch((e) => { view.replaceChildren(el("div", "empty err-text", String(e.message || e))); }); }
}

/* ── Context bar (save_id / player_id) ───────────────────────────────── */

function contextBar(onLoad) {
  const bar = el("div", "toolbar");
  const save = el("input");
  save.type = "text";
  save.value = ctxValue("sw_save_id", "unknown");
  save.placeholder = t("web.save_id");
  save.title = t("web.save_id");
  const player = el("input");
  player.type = "text";
  player.value = ctxValue("sw_player_id", "local");
  player.placeholder = t("web.player_id");
  player.title = t("web.player_id");
  const load = el("button", "primary", t("web.reload"));
  load.addEventListener("click", () => {
    localStorage.setItem("sw_save_id", save.value.trim() || "unknown");
    localStorage.setItem("sw_player_id", player.value.trim() || "local");
    onLoad(save.value.trim() || "unknown", player.value.trim() || "local");
  });
  bar.append(el("span", "muted", t("web.save_id") + ":"), save,
             el("span", "muted", t("web.player_id") + ":"), player, load);
  return bar;
}

/* ── Status tab ──────────────────────────────────────────────────────── */

function startStatusTimer() {
  if (S.timer) { clearInterval(S.timer); S.timer = null; }
  if (S.auto) S.timer = setInterval(() => renderStatus().catch(() => {}), 5000);
}

async function renderStatus() {
  const view = $("#view");
  const [health, status] = await Promise.all([
    api("/v1/health", { auth: false }),
    api("/v1/status"),
  ]);
  setConn("on");
  view.replaceChildren();

  const bar = el("div", "toolbar");
  const refresh = el("button", "primary", t("web.refresh_now"));
  refresh.addEventListener("click", renderStatus);
  const auto = el("label", "row");
  const cb = el("input");
  cb.type = "checkbox";
  cb.checked = S.auto;
  cb.addEventListener("change", () => { S.auto = cb.checked; startStatusTimer(); });
  auto.append(cb, el("span", "muted", t("web.auto_refresh")));
  bar.append(refresh, auto);
  view.append(bar);

  const grid = el("div", "grid");
  const head = el("div", "card");
  head.append(el("h2", null, t("web.tab.status")));
  const stats = [
    ["ok", String(status.ok)],
    ["version", status.sidecar_version || health.version],
    ["uptime_s", Math.round(status.uptime_s) + "s"],
    ["lang", status.lang],
  ];
  stats.forEach(([k, v]) => head.append(statRow(k, v)));
  grid.append(head);

  grid.append(providersCard(status.providers || []));
  ["chain_health", "autonomy", "memory", "god", "rails", "backgrounds", "budget", "agency"]
    .forEach((key) => grid.append(jsonCard(key, status[key])));
  view.append(grid);

  startStatusTimer();
}

function statRow(k, v) {
  const row = el("div", "stat");
  row.append(el("span", "k", String(k)), el("span", "v", String(v)));
  return row;
}

function jsonCard(title, obj) {
  const card = el("div", "card");
  card.append(el("h2", null, title));
  const empty = obj === undefined || obj === null || (typeof obj === "object" && Object.keys(obj).length === 0);
  if (empty) { card.append(el("div", "muted", t("web.none"))); return card; }
  const pre = el("pre", null, JSON.stringify(obj, null, 2));
  card.append(pre);
  return card;
}

function providersCard(providers) {
  const card = el("div", "card");
  card.append(el("h2", null, "providers"));
  if (!providers.length) { card.append(el("div", "muted", t("web.none"))); return card; }
  const table = el("table");
  const thead = el("thead");
  const hr = el("tr");
  ["name", "status", "model"].forEach((h) => hr.append(el("th", null, h)));
  thead.append(hr);
  const tbody = el("tbody");
  providers.forEach((p) => {
    const tr = el("tr");
    tr.append(el("td", null, p.name || "?"));
    tr.append(el("td", null, p.status || p.healthy === undefined ? "-" : String(p.healthy)));
    tr.append(el("td", null, p.model || "-"));
    tbody.append(tr);
  });
  table.append(thead, tbody);
  card.append(table);
  return card;
}

/* ── Controls tab ────────────────────────────────────────────────────── */

const SECTION_LABELS = {
  "god": "web.section.god",
  "god.powers": "web.section.god.powers",
  "god.settings": "web.section.god.settings",
  "agents": "web.section.agents",
  "agents.initiative": "web.section.agents.initiative",
  "agents.layers": "web.section.agents.layers",
  "agents.evolution": "web.section.agents.evolution",
  "agents.personality": "web.section.agents.personality",
  "agents.social": "web.section.agents.social",
  "llm": "web.section.llm",
  "memory": "web.section.memory",
  "ui": "web.section.ui",
  "runtime": "web.section.runtime",
  "network": "web.section.network",
};

const SECTION_ORDER = [
  "god", "god.powers", "god.settings",
  "agents", "agents.initiative", "agents.layers", "agents.evolution",
  "agents.personality", "agents.social",
  "ui", "llm", "memory", "runtime", "network",
];

function sectionOf(spec) {
  return spec.target || "other";
}

async function renderControls() {
  const res = await api("/v1/god/controls?include_advanced=true");
  S.controls = res.controls || [];
  S.values = res.values || {};
  S.dirty = {};

  const view = $("#view");
  view.replaceChildren();
  const toolbar = el("div", "toolbar");
  const apply = el("button", null, t("web.apply"));
  apply.addEventListener("click", () => applyControls(false));
  const applySave = el("button", "primary", t("web.apply_save"));
  applySave.addEventListener("click", () => applyControls(true));
  const reload = el("button", null, t("web.reload"));
  reload.addEventListener("click", renderControls);
  toolbar.append(apply, applySave, reload, el("span", "muted", t("web.restart_only")));
  view.append(toolbar);

  const groups = {};
  S.controls.forEach((spec) => {
    const key = sectionOf(spec);
    (groups[key] = groups[key] || []).push(spec);
  });

  const seen = new Set();
  const order = [...SECTION_ORDER.filter((k) => groups[k]), ...Object.keys(groups).filter((k) => !SECTION_ORDER.includes(k))];
  order.forEach((key) => {
    if (seen.has(key)) return;
    seen.add(key);
    const card = el("div", "card");
    const heading = SECTION_LABELS[key] ? t(SECTION_LABELS[key]) : pretty(key);
    card.append(el("h2", null, heading));
    groups[key].forEach((spec) => card.append(controlRow(spec)));
    view.append(card);
  });
}

function currentValue(spec) {
  if (Object.prototype.hasOwnProperty.call(S.dirty, spec.key)) return S.dirty[spec.key];
  if (Object.prototype.hasOwnProperty.call(S.values, spec.key)) return S.values[spec.key];
  return spec.default;
}

function markDirty(spec, value) {
  S.dirty[spec.key] = value;
}
function clearDirty(spec, node) {
  delete S.dirty[spec.key];
  if (node) node.classList.remove("dirty");
}
function setDirty(spec, value, node) {
  markDirty(spec, value);
  if (node) node.classList.add("dirty");
}

function controlRow(spec) {
  const row = el("div", "ctrl");
  const head = el("div", "head");
  const nameWrap = el("div");
  nameWrap.append(el("div", "name", label(spec)));
  const desc = tc(spec.description_key);
  if (desc) nameWrap.append(el("div", "desc", desc));
  head.append(nameWrap);
  if (spec.restart_only) head.append(el("span", "badge", t("web.restart_only")));
  row.append(head);

  const body = el("div", "body");
  row.append(body);
  const disabled = !!spec.restart_only;
  const value = currentValue(spec);

  if (spec.kind === "slider") {
    const range = el("input");
    range.type = "range";
    range.min = spec.min_value ?? 0;
    range.max = spec.max_value ?? 1;
    range.step = spec.step || 0.05;
    range.value = value;
    range.disabled = disabled;
    const out = el("span", "val", String(value));
    range.addEventListener("input", () => {
      out.textContent = range.value;
      setDirty(spec, Number(range.value), row);
    });
    body.append(range, out);
  } else if (spec.kind === "toggle") {
    const cb = el("input");
    cb.type = "checkbox";
    cb.checked = !!value;
    cb.disabled = disabled;
    cb.addEventListener("change", () => setDirty(spec, cb.checked, row));
    body.append(cb);
  } else if (spec.kind === "select") {
    const sel = el("select");
    sel.disabled = disabled;
    (spec.options || []).forEach((opt) => {
      const o = el("option", null, opt.label || tc(opt.label_key) || opt.value);
      o.value = opt.value;
      if (opt.value === value) o.selected = true;
      sel.append(o);
    });
    sel.addEventListener("change", () => setDirty(spec, sel.value, row));
    body.append(sel);
  } else if (spec.kind === "tags") {
    const wrap = el("div", "tags");
    const selected = new Set(Array.isArray(value) ? value : []);
    (spec.options || []).forEach((opt) => {
      const lab = el("label", "row");
      const cb = el("input");
      cb.type = "checkbox";
      cb.checked = selected.has(opt.value);
      cb.disabled = disabled;
      cb.addEventListener("change", () => {
        if (cb.checked) selected.add(opt.value); else selected.delete(opt.value);
        setDirty(spec, [...selected], row);
      });
      lab.append(cb, el("span", null, tc(opt.label_key) || opt.value));
      wrap.append(lab);
    });
    body.append(wrap);
  } else {
    body.append(el("span", "muted", String(value)));
  }
  return row;
}

async function applyControls(persist) {
  const settings = { ...S.dirty };
  if (!Object.keys(settings).length) { toast(t("web.none")); return; }
  try {
    await api("/v1/config/god", { method: "POST", body: { settings, persist } });
    toast(t("web.control_applied", { count: Object.keys(settings).length }));
    await renderControls();
  } catch (err) {
    toast(String(err.message || err), true);
  }
}

/* ── Roster tab ──────────────────────────────────────────────────────── */

async function renderRoster() {
  const view = $("#view");
  view.replaceChildren();
  await detectContext();
  let saveId = ctxValue("sw_save_id", "unknown");
  let playerId = ctxValue("sw_player_id", "local");
  view.append(contextBar((s, p) => { saveId = s; playerId = p; load(); }));

  const body = el("div", "grid");
  view.append(body);

  async function load() {
    body.replaceChildren(el("div", "loading", t("web.loading")));
    try {
      const res = await api(`/v1/agency/seats?save_id=${encodeURIComponent(saveId)}&player_id=${encodeURIComponent(playerId)}`);
      body.replaceChildren();

      const info = el("div", "card");
      info.append(el("h2", null, t("web.tab.roster")));
      info.append(statRow("save_id", res.save_id || saveId));
      info.append(statRow(t("web.seats"), res.seats));
      info.append(statRow(t("web.used"), res.used));
      const resize = el("div", "row");
      const num = el("input");
      num.type = "number";
      num.min = 1;
      num.value = res.seats || 12;
      const btn = el("button", null, t("web.resize_seats"));
      btn.addEventListener("click", async () => {
        await api("/v1/agency/seats", {
          method: "POST",
          body: { sim: { save_id: saveId, player_id: playerId }, seats: Number(num.value) },
        });
        load();
      });
      resize.append(num, btn);
      info.append(resize);
      body.append(info);

      const table = el("div", "card");
      table.append(el("h2", null, t("web.tab.roster")));
      if (!(res.agents || []).length) { table.append(el("div", "muted", t("web.none"))); body.append(table); return; }
      const t2 = el("table");
      const thead = el("thead");
      const hr = el("tr");
      [t("web.sim"), t("web.tier"), t("web.household"), t("web.player"), t("web.impulse")].forEach((h) => hr.append(el("th", null, h)));
      thead.append(hr);
      const tbody = el("tbody");
      res.agents.forEach((a) => {
        const tr = el("tr");
        tr.append(el("td", null, String(a.sim_id)));
        tr.append(el("td", null, a.tier || "-"));
        tr.append(el("td", null, a.household_id === null || a.household_id === undefined ? "-" : String(a.household_id)));
        tr.append(el("td", null, a.is_player ? "✓" : ""));
        tr.append(el("td", null, a.impulse_frequency === null || a.impulse_frequency === undefined ? "-" : String(a.impulse_frequency)));
        tbody.append(tr);
      });
      t2.append(thead, tbody);
      table.append(t2);
      body.append(table);
    } catch (err) {
      body.replaceChildren(el("div", "empty err-text", String(err.message || err)));
    }
  }
  load();
}

/* ── World tab ───────────────────────────────────────────────────────── */

async function renderWorld() {
  const view = $("#view");
  view.replaceChildren();
  await detectContext();
  let saveId = ctxValue("sw_save_id", "unknown");
  view.append(contextBar((s) => { saveId = s; load(); }));
  const body = el("div", "grid");
  view.append(body);

  async function load() {
    body.replaceChildren(el("div", "loading", t("web.loading")));
    try {
      const res = await api(`/v1/god/aggregates?save_id=${encodeURIComponent(saveId)}`);
      const n = res.neighborhood || {};
      body.replaceChildren();
      const card = el("div", "card");
      card.append(el("h2", null, t("web.tab.world")));
      card.append(statRow(t("web.population"), n.population ?? 0));
      card.append(statRow(t("web.households"), n.household_count ?? 0));
      card.append(statRow(t("web.mood"), n.mood ?? "neutral"));
      card.append(statRow(t("web.tension"), n.tension ?? 0));
      card.append(statRow(t("web.funds"), n.funds ?? 0));
      body.append(card);
      body.append(jsonCard("mood_distribution", n.mood_distribution));
      body.append(jsonCard("households", n.households));
    } catch (err) {
      body.replaceChildren(el("div", "empty err-text", String(err.message || err)));
    }
  }
  load();
}

/* ── Pending tab ─────────────────────────────────────────────────────── */

async function renderPending() {
  const view = $("#view");
  view.replaceChildren();
  await detectContext();
  let saveId = ctxValue("sw_save_id", "unknown");
  let playerId = ctxValue("sw_player_id", "local");
  view.append(contextBar((s, p) => { saveId = s; playerId = p; load(); }));
  const body = el("div", "grid");
  view.append(body);

  async function load() {
    body.replaceChildren(el("div", "loading", t("web.loading")));
    try {
      const [dirs, intents] = await Promise.all([
        api(`/v1/autonomy/directives?save_id=${encodeURIComponent(saveId)}&player_id=${encodeURIComponent(playerId)}`),
        api(`/v1/autonomy/intents?save_id=${encodeURIComponent(saveId)}&player_id=${encodeURIComponent(playerId)}`),
      ]);
      body.replaceChildren();
      body.append(listCard(t("web.directives"), dirs.directives));
      body.append(listCard(t("web.intents"), intents.intents));
    } catch (err) {
      body.replaceChildren(el("div", "empty err-text", String(err.message || err)));
    }
  }
  load();
}

function listCard(title, items) {
  const card = el("div", "card");
  card.append(el("h2", null, title + " (" + (items ? items.length : 0) + ")"));
  if (!items || !items.length) { card.append(el("div", "muted", t("web.none"))); return card; }
  const pre = el("pre", null, JSON.stringify(items, null, 2));
  card.append(pre);
  return card;
}

document.addEventListener("DOMContentLoaded", boot);
