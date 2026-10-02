/* Sensewright Web Studio — zero-dependency vanilla JS SPA.
 *
 * Talks to the sidecar REST API (/v1/*) and the SPA's own locale files served
 * at /ui/locales/<code>.json + /ui/manifest.json. All reads tolerate missing
 * data; all writes are fire-and-forget with optimistic UI.
 */
(function () {
  'use strict';

  /* ── State ──────────────────────────────────────────────────────────── */
  var state = {
    manifest: null,
    locales: {},          // code -> {app,status,tabs,common,sims,god,providers,toast}
    currentLang: null,
    sims: [],
    selectedSim: null,
    godControls: {},
    status: null,
    health: null
  };

  var $ = function (id) { return document.getElementById(id); };

  /* ── i18n ───────────────────────────────────────────────────────────── */
  function dottedGet(obj, key) {
    if (!obj) return undefined;
    var parts = key.split('.');
    var cur = obj;
    for (var i = 0; i < parts.length; i++) {
      if (cur == null || typeof cur !== 'object') return undefined;
      cur = cur[parts[i]];
    }
    return cur;
  }

  function t(key) {
    var dict = state.locales[state.currentLang] || state.locales[state.manifest ? state.manifest.default_locale : null] || {};
    var val = dottedGet(dict, key);
    return (val === undefined || val === null) ? key : val;
  }

  function applyI18n() {
    var els = document.querySelectorAll('[data-i18n]');
    for (var i = 0; i < els.length; i++) {
      var key = els[i].getAttribute('data-i18n');
      if (key) els[i].textContent = t(key);
    }
    var empties = document.querySelectorAll('[data-i18n-empty]');
    for (var j = 0; j < empties.length; j++) {
      empties[j].dataset.emptyText = t(empties[j].getAttribute('data-i18n-empty'));
    }
  }

  function setLang(code) {
    state.currentLang = code;
    try { localStorage.setItem('sensewright-lang', code); } catch (e) {}
    loadLocale(code).then(function () {
      applyI18n();
      renderAll();
    });
  }

  function loadLocale(code) {
    return fetch('/ui/locales/' + encodeURIComponent(code) + '.json')
      .then(function (r) { return r.json(); })
      .then(function (data) { state.locales[code] = data || {}; })
      .catch(function () { state.locales[code] = {}; });
  }

  function buildLangSelect() {
    var select = $('lang-select');
    if (!select || !state.manifest || !state.manifest.locales) return;
    select.innerHTML = '';
    state.manifest.locales.forEach(function (loc) {
      var opt = document.createElement('option');
      opt.value = loc.code;
      opt.textContent = loc.display_name || loc.code;
      select.appendChild(opt);
    });
    select.value = state.currentLang;
    select.addEventListener('change', function () { setLang(select.value); });
  }

  /* ── API helpers ────────────────────────────────────────────────────── */
  function apiGet(path) {
    return fetch(path).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  function apiPost(path, body) {
    return fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json().catch(function () { return {}; });
    });
  }

  function toast(message, isError) {
    var container = $('toast-container');
    if (!container) return;
    var el = document.createElement('div');
    el.className = 'toast' + (isError ? ' toast-error' : '');
    el.textContent = message;
    container.appendChild(el);
    setTimeout(function () {
      el.classList.add('toast-hide');
      setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 300);
    }, 2600);
  }

  /* ── Tabs ───────────────────────────────────────────────────────────── */
  function initTabs() {
    var tabs = ['sims', 'god', 'providers'];
    tabs.forEach(function (name) {
      var btn = $('tab-' + name);
      if (!btn) return;
      btn.addEventListener('click', function () {
        tabs.forEach(function (other) {
          $('tab-' + other).classList.toggle('active', other === name);
          $('tab-' + other).setAttribute('aria-selected', other === name ? 'true' : 'false');
          $('panel-' + other).classList.toggle('hidden', other !== name);
        });
      });
    });
  }

  /* ── Status polling ─────────────────────────────────────────────────── */
  function pollStatus() {
    apiGet('/v1/health').then(function (h) {
      state.health = h;
      renderHealth(h);
    }).catch(function () {
      renderHealth({ status: 'offline' });
    });
    apiGet('/v1/status').then(function (s) {
      state.status = s;
      renderStatus(s);
    }).catch(function () { /* status may be unavailable during early boot */ });
  }

  function renderHealth(h) {
    var badge = $('health-badge');
    var text = $('health-text');
    var pidText = $('pid-text');
    var saveText = $('save-text');
    if (!h || !h.status || h.status !== 'ok') {
      if (badge) badge.setAttribute('data-state', 'offline');
      if (text) text.textContent = t('status.offline');
      if (pidText) pidText.textContent = '—';
      if (saveText) saveText.textContent = t('status.no_save');
      return;
    }
    if (badge) badge.setAttribute('data-state', 'online');
    if (text) text.textContent = t('status.online');
    if (pidText) pidText.textContent = h.game_pid != null ? String(h.game_pid) : '—';
  }

  function renderStatus(s) {
    if (!s) return;
    if ($('save-text') && s.active_save != null) {
      $('save-text').textContent = String(s.active_save);
    }
    if ($('chain-status')) renderChainStatus(s);
    if ($('diag-queue')) $('diag-queue').textContent = JSON.stringify(s.queue || {}, null, 2);
    if ($('diag-limits')) $('diag-limits').textContent = JSON.stringify(s.chain || s.limits || {}, null, 2);
    if ($('diag-pool')) $('diag-pool').textContent = JSON.stringify(s.pool || {}, null, 2);
    if ($('diag-tiers')) $('diag-tiers').textContent = JSON.stringify(s.tiers || {}, null, 2);
  }

  function renderChainStatus(s) {
    var el = $('chain-status');
    if (!el) return;
    var providers = s.providers || {};
    var names = Object.keys(providers);
    if (!names.length) { el.textContent = t('common.none'); return; }
    el.innerHTML = '';
    names.forEach(function (name) {
      var row = document.createElement('div');
      row.className = 'chain-row';
      row.textContent = name + ' · ' + (providers[name].enabled ? t('status.online') : t('status.offline'));
      el.appendChild(row);
    });
  }

  /* ── Sims tab ───────────────────────────────────────────────────────── */
  function loadSims() {
    apiGet('/v1/agency/seats').then(function (data) {
      var seats = (data && data.seats) || [];
      state.sims = seats;
      renderSimSelect();
    }).catch(function () {
      // Seats endpoint may not be wired yet; try census via status.
      state.sims = [];
      renderSimSelect();
    });
  }

  function renderSimSelect() {
    var select = $('sim-select');
    if (!select) return;
    var current = select.value;
    select.innerHTML = '';
    var placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.disabled = true;
    placeholder.selected = true;
    placeholder.textContent = t('sims.select_placeholder');
    select.appendChild(placeholder);
    state.sims.forEach(function (sim) {
      var opt = document.createElement('option');
      opt.value = String(sim.sim_id != null ? sim.sim_id : sim.id);
      opt.textContent = sim.name || ('Sim ' + (sim.sim_id || ''));
      select.appendChild(opt);
    });
    if (current) select.value = current;
    if (!state.sims.length) {
      $('sim-profile').classList.add('hidden');
      $('no-sim-selected').classList.remove('hidden');
    }
  }

  function onSimSelected(simId) {
    var sim = state.sims.filter(function (s) { return String(s.sim_id != null ? s.sim_id : s.id) === String(simId); })[0];
    state.selectedSim = sim;
    if (!sim) {
      $('sim-profile').classList.add('hidden');
      $('no-sim-selected').classList.remove('hidden');
      return;
    }
    $('sim-profile').classList.remove('hidden');
    $('no-sim-selected').classList.add('hidden');
    renderSimProfile(sim);
  }

  function renderSimProfile(sim) {
    var profile = sim.profile || {};
    setVal('pf-name', profile.name || sim.name || '');
    setVal('pf-species', profile.species || '');
    setVal('pf-age', profile.age_stage || '');
    setVal('pf-household', sim.household_id != null ? String(sim.household_id) : '');
    setVal('pf-core', profile.core_personality || '');
    setVal('pf-demeanor', profile.current_demeanor || '');
    setVal('pf-speech', profile.speech_style || '');
    setVal('pf-dream', profile.dream_narrative || '');
    setVal('pf-dream-archetype', profile.dream_archetype || '');
    setVal('pf-dream-urge', profile.dream_urge || '');
    setVal('pf-plan', JSON.stringify(profile.daily_plan || {}, null, 2));
    setVal('pf-lifestory', profile.life_story || '');
    setVal('pf-diary', profile.diary || '');
    renderPsyche(profile.psyche_blocks || {});
    renderRelationships(sim.relationships || []);
  }

  function setVal(id, value) {
    var el = $(id);
    if (el) el.value = value;
  }

  function renderPsyche(blocks) {
    var list = $('psyche-list');
    if (!list) return;
    list.innerHTML = '';
    var keys = Object.keys(blocks || {});
    if (!keys.length) { list.textContent = list.dataset.emptyText || ''; return; }
    keys.forEach(function (key) {
      var row = document.createElement('div');
      row.className = 'psyche-row';
      var intensity = blocks[key] != null ? Number(blocks[key]) : 0;
      row.innerHTML = '<span class="psyche-key">' + escapeHtml(key) + '</span>' +
        '<input type="range" min="0" max="1" step="0.05" value="' + intensity + '" data-psyche-key="' + escapeHtml(key) + '">' +
        '<span class="psyche-val">' + intensity.toFixed(2) + '</span>';
      list.appendChild(row);
    });
    list.querySelectorAll('input[type=range]').forEach(function (input) {
      input.addEventListener('input', function () {
        var val = input.parentNode.querySelector('.psyche-val');
        if (val) val.textContent = Number(input.value).toFixed(2);
      });
    });
  }

  function renderRelationships(rels) {
    var list = $('relationships-list');
    if (!list) return;
    list.innerHTML = '';
    if (!rels || !rels.length) { list.textContent = list.dataset.emptyText || ''; return; }
    rels.forEach(function (rel) {
      var row = document.createElement('div');
      row.className = 'rel-row';
      row.textContent = (rel.target_name || rel.target_id || '?') + ' · ' +
        t('sims.friendship_short') + ' ' + (rel.friendship != null ? rel.friendship : '');
      list.appendChild(row);
    });
  }

  function saveSimProfile() {
    if (!state.selectedSim) return;
    var simId = state.selectedSim.sim_id != null ? state.selectedSim.sim_id : state.selectedSim.id;
    var body = {
      sim_id: simId,
      profile: {
        core_personality: val('pf-core'),
        current_demeanor: val('pf-demeanor'),
        speech_style: val('pf-speech'),
        daily_plan: safeJson(val('pf-plan'), {})
      }
    };
    apiPost('/v1/profile', body).then(function () { toast(t('toast.saved')); })
      .catch(function () { toast(t('toast.save_failed'), true); });
  }

  function val(id) { var el = $(id); return el ? el.value : ''; }
  function safeJson(text, fallback) {
    try { return JSON.parse(text); } catch (e) { return fallback; }
  }
  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  /* ── God tab ────────────────────────────────────────────────────────── */
  var GOD_DIALS = ['intervention_frequency', 'intensity', 'mood_influence', 'autonomy_degree', 'chaos_degree'];

  function loadGodControls() {
    apiGet('/v1/god/controls').then(function (data) {
      var controls = (data && data.controls) || [];
      controls.forEach(function (c) { state.godControls[c.key] = c.value; });
      renderDials();
      var preset = state.godControls.preset;
      if (preset && $('god-preset')) $('god-preset').value = preset;
      if ($('free-only')) $('free-only').checked = !!state.godControls.free_only;
      var zeitgeist = state.godControls.zeitgeist;
      if (zeitgeist && typeof zeitgeist === 'object') {
        if ($('zeitgeist-tags')) $('zeitgeist-tags').value = (zeitgeist.tags || []).join(', ');
        if ($('zeitgeist-weather')) $('zeitgeist-weather').value = zeitgeist.weather_preference || '';
      }
    }).catch(function () { renderDials(); });
  }

  function renderDials() {
    var grid = $('dials-grid');
    if (!grid) return;
    grid.innerHTML = '';
    GOD_DIALS.forEach(function (dial) {
      var value = state.godControls[dial] != null ? Number(state.godControls[dial]) : 0.5;
      var wrap = document.createElement('div');
      wrap.className = 'dial-row';
      wrap.innerHTML = '<label>' + t('god.' + dial) + '</label>' +
        '<input type="range" min="0" max="1" step="0.05" value="' + value + '" data-dial="' + dial + '">' +
        '<span class="dial-val">' + value.toFixed(2) + '</span>';
      grid.appendChild(wrap);
    });
    grid.querySelectorAll('input[type=range]').forEach(function (input) {
      input.addEventListener('change', function () {
        var dial = input.getAttribute('data-dial');
        state.godControls[dial] = Number(input.value);
        input.parentNode.querySelector('.dial-val').textContent = Number(input.value).toFixed(2);
        apiPost('/v1/god/controls', { key: dial, value: Number(input.value) })
          .catch(function () { toast(t('toast.apply_failed'), true); });
      });
    });
  }

  function applyPreset() {
    var preset = $('god-preset') ? $('god-preset').value : null;
    if (!preset) return;
    apiPost('/v1/god/controls', { key: 'preset', value: preset })
      .then(function () { toast(t('toast.applied')); })
      .catch(function () { toast(t('toast.apply_failed'), true); });
  }

  function saveZeitgeist() {
    var tagsText = $('zeitgeist-tags') ? $('zeitgeist-tags').value : '';
    var weather = $('zeitgeist-weather') ? $('zeitgeist-weather').value : '';
    var tags = tagsText.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    apiPost('/v1/god/zeitgeist', { zeitgeist_text: tags.join(', '), tags: tags, weather_preference: weather })
      .then(function () { toast(t('toast.zeitgeist_saved')); })
      .catch(function () { toast(t('toast.zeitgeist_failed'), true); });
  }

  /* ── Providers tab ──────────────────────────────────────────────────── */
  function renderProvidersConfig() {
    var el = $('providers-config');
    if (!el || !state.status) return;
    var providers = state.status.providers || {};
    var names = Object.keys(providers);
    if (!names.length) { el.textContent = t('providers.loading'); return; }
    el.innerHTML = '';
    names.forEach(function (name) {
      var card = document.createElement('div');
      card.className = 'provider-card';
      var enabled = !!providers[name].enabled;
      card.innerHTML = '<h4>' + escapeHtml(name) + '</h4>' +
        '<div class="field-row"><label>' + t('providers.api_key') + '</label>' +
        '<input type="password" data-provider-key="' + escapeHtml(name) + '" placeholder="••••••••"></div>' +
        '<div class="field-row actions">' +
        '<button class="btn btn-secondary" data-test="' + escapeHtml(name) + '">' + t('providers.test_connection') + '</button>' +
        '<button class="btn btn-primary" data-save-key="' + escapeHtml(name) + '">' + t('common.save') + '</button>' +
        '</div>';
      el.appendChild(card);
    });
    el.querySelectorAll('[data-test]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        apiGet('/v1/status').then(function () { toast(t('toast.connection_ok')); })
          .catch(function () { toast(t('toast.connection_failed'), true); });
      });
    });
    el.querySelectorAll('[data-save-key]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var name = btn.getAttribute('data-save-key');
        var input = el.querySelector('[data-provider-key="' + name + '"]');
        apiPost('/v1/god/controls', { key: 'provider.' + name + '.api_key', value: input ? input.value : '' })
          .then(function () { toast(t('toast.saved')); })
          .catch(function () { toast(t('toast.save_failed'), true); });
      });
    });
  }

  function renderRoutesConfig() {
    var el = $('routes-config');
    if (!el || !state.status) return;
    var routes = state.status.routes || {};
    var tiers = state.status.tiers || {};
    var html = '';
    Object.keys(tiers).forEach(function (tier) {
      html += '<div class="route-row"><span class="route-tier">' + escapeHtml(tier) + '</span> ' +
        escapeHtml(JSON.stringify(tiers[tier])) + '</div>';
    });
    if (!Object.keys(routes).length && !Object.keys(tiers).length) {
      html = t('providers.loading_routes');
    }
    el.innerHTML = html;
  }

  /* ── Render all ─────────────────────────────────────────────────────── */
  function renderAll() {
    renderHealth(state.health);
    renderStatus(state.status);
    renderSimSelect();
    renderDials();
    renderProvidersConfig();
    renderRoutesConfig();
  }

  /* ── Boot ───────────────────────────────────────────────────────────── */
  function boot() {
    initTabs();
    applyI18n();

    // Manifest → language list + default locale.
    apiGet('/ui/manifest.json').then(function (manifest) {
      state.manifest = manifest;
      var saved = null;
      try { saved = localStorage.getItem('sensewright-lang'); } catch (e) {}
      var defaultLang = manifest.default_locale;
      state.currentLang = saved || defaultLang;
      buildLangSelect();
      return loadLocale(state.currentLang);
    }).catch(function () {
      // Fallback: assume the html option value is usable.
      state.currentLang = $('lang-select') ? $('lang-select').value : null;
      return loadLocale(state.currentLang);
    }).then(function () {
      applyI18n();
      // Wire static interactions.
      if ($('sim-select')) $('sim-select').addEventListener('change', function () { onSimSelected($('sim-select').value); });
      if ($('btn-refresh-sims')) $('btn-refresh-sims').addEventListener('click', loadSims);
      if ($('btn-save-personality')) $('btn-save-personality').addEventListener('click', saveSimProfile);
      if ($('btn-save-plan')) $('btn-save-plan').addEventListener('click', saveSimProfile);
      if ($('btn-apply-preset')) $('btn-apply-preset').addEventListener('click', applyPreset);
      if ($('btn-save-zeitgeist')) $('btn-save-zeitgeist').addEventListener('click', saveZeitgeist);
      if ($('btn-refresh-status')) $('btn-refresh-status').addEventListener('click', pollStatus);
      if ($('spoiler-shield')) $('spoiler-shield').addEventListener('change', function () {
        var beats = $('god-beats-container');
        if (beats) beats.classList.toggle('spoiler-on', $('spoiler-shield').checked);
      });

      loadSims();
      loadGodControls();
      pollStatus();
      setInterval(pollStatus, 2000);
      setInterval(loadGodControls, 15000);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
