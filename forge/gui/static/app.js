// ----------------------------------------------------------------------
// Language Forge, frontend
// ----------------------------------------------------------------------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];


function _includeCatalogParam() {
  // Phase 3 follow-up: when the catalog UI deep-links into the
  // playground via ?include_catalog=all, propagate it to the
  // /api/languages call so catalog candidates appear in the dropdown.
  // Default behavior (no query param) keeps Library showing only
  // generated/ + approved catalog entries.
  const p = new URLSearchParams(location.search);
  const inc = p.get('include_catalog');
  return inc ? '?include_catalog=' + encodeURIComponent(inc) : '';
}


let currentLang = null;
let providers = { available: { api: false, claude_cli: false }, default: 'api' };

// ============================================================
// Roadmap §3.1 — per-language theme swapper
// ============================================================
// Each language has its own theme.css emitted by the generator. The
// GUI swaps the <link id="lang-theme-link"> stylesheet href + sets
// body[data-lang-theme="<lang>"] so the per-lang `:root` overrides
// activate. Decoration overlay (scanlines / parchment) is rendered
// via a `.theme-deco` div the swapper toggles.
function applyLangTheme(lang) {
  const link = document.getElementById('lang-theme-link');
  const body = document.body;
  if (!link) return;
  if (!lang) {
    link.href = '';
    link.disabled = true;
    body.removeAttribute('data-lang-theme');
    document.querySelector('.theme-deco')?.remove();
    return;
  }
  // Cache-bust on language change so we always pick up the latest theme.
  const url = `/api/theme/${encodeURIComponent(lang)}.css?t=${Date.now()}`;
  link.href = url;
  link.disabled = false;
  body.setAttribute('data-lang-theme', lang);
  // Ensure the decoration overlay div exists; the per-lang :root rule
  // either shows it (scanlines / parchment) or leaves it transparent.
  if (!document.querySelector('.theme-deco')) {
    const deco = document.createElement('div');
    deco.className = 'theme-deco';
    body.append(deco);
  }
}

// ============================================================
// Toast notifications (replaces alert)
// ============================================================
function toast(msg, kind = 'info', duration = 3500) {
  const root = $('#toast-root');
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  const icons = { success: '✓', error: '✕', info: 'ⓘ', warn: '⚠' };
  el.innerHTML = `<span class="ti">${icons[kind] || 'ⓘ'}</span><span>${msg}</span>`;
  root.append(el);
  setTimeout(() => {
    el.classList.add('fade');
    setTimeout(() => el.remove(), 250);
  }, duration);
}

// ============================================================
// View routing
// ============================================================
function switchView(name) {
  $$('.view').forEach(v => v.classList.toggle('active', v.id === `view-${name}`));
  $$('.tab').forEach(t => t.classList.toggle('active', t.dataset.view === name));
  if (name === 'library') refreshLibrary();
  if (name === 'playground') {
    refreshPlaygroundLanguages();
    setTimeout(() => { if (playEditor) playEditor.refresh(); else ensurePlayEditor(); }, 50);
  }
  if (name === 'katas') { refreshKataLanguages(); refreshKataPacks(); }
}
window.switchView = switchView;
$$('.tab').forEach(btn => btn.addEventListener('click', () => switchView(btn.dataset.view)));

// ============================================================
// Provider detection (radio cards + status pills)
// ============================================================
async function refreshProviders() {
  try {
    const r = await fetch('/api/providers');
    providers = await r.json();
  } catch (e) {
    providers = { available: { api: false, claude_cli: false }, default: 'api' };
  }
  // Update pills
  setPill('api', providers.available.api ? 'ready' : 'missing',
          providers.available.api ? 'Detected' : 'Not configured');
  setPill('claude_cli', providers.available.claude_cli ? 'ready' : 'missing',
          providers.available.claude_cli ? 'Detected' : 'Not installed');

  // Disable unavailable cards
  $$('.provider-card').forEach(card => {
    const p = card.dataset.provider;
    const available = providers.available[p];
    card.classList.toggle('unavailable', !available);
    const input = card.querySelector('input');
    input.disabled = !available;
    if (!available) input.checked = false;
  });

  // Pre-select the default if available, otherwise the first available
  const targetProvider = providers.available[providers.default]
    ? providers.default
    : (providers.available.api ? 'api' : (providers.available.claude_cli ? 'claude_cli' : null));
  if (targetProvider) {
    const input = $(`.provider-card[data-provider="${targetProvider}"] input`);
    if (input) input.checked = true;
  }

  const hint = $('#provider-hint');
  if (!providers.available.api && !providers.available.claude_cli) {
    hint.textContent = 'No providers detected. Install Claude CLI or set ANTHROPIC_API_KEY.';
  } else {
    const labelMap = { api: 'API key', claude_cli: 'Subscription' };
    hint.textContent = `Recommended: ${labelMap[providers.default] || 'API key'}`;
  }
}
function setPill(provider, kind, text) {
  $$(`.status-pill[data-pill="${provider}"]`).forEach(el => {
    el.className = `status-pill ${kind}`;
    el.textContent = text;
  });
}

// ============================================================
// Speculative-features pickers (persona / era / theme / bans)
// ============================================================

async function refreshSpeculativePickers() {
  const fetchOpts = async (url) => { try { return (await (await fetch(url)).json()); } catch { return {}; } };
  const personasResp = await fetchOpts('/api/personas');
  const erasResp     = await fetchOpts('/api/eras');
  const themesResp   = await fetchOpts('/api/themes');
  const bansResp     = await fetchOpts('/api/bans');

  // Persona radios, first option is "(none)"
  const pg = $('#persona-grid');
  if (pg) {
    pg.innerHTML = '';
    pg.append(makeRadio('persona', '', '(none)', 'Use the default resolver behavior.'));
    for (const p of personasResp.personas || []) {
      pg.append(makeRadio('persona', p.key, p.key, p.blurb));
    }
  }

  // Era radios
  const eg = $('#era-grid');
  if (eg) {
    eg.innerHTML = '';
    eg.append(makeRadio('era', '', '(none)', 'No era preset; use raw user options.'));
    for (const e of erasResp.eras || []) {
      eg.append(makeRadio('era', e.key, e.key, e.blurb));
    }
  }

  // Theme radios
  const tg = $('#theme-grid');
  if (tg) {
    tg.innerHTML = '';
    tg.append(makeRadio('keyword_theme', '', '(none)', 'Default keywords.'));
    for (const t of themesResp.themes || []) {
      tg.append(makeRadio('keyword_theme', t.key, t.key, `Preview: ${t.preview}`));
    }
  }

  // Bans checkboxes
  const bg = $('#bans-grid');
  if (bg) {
    bg.innerHTML = '';
    for (const b of bansResp.bans || []) {
      const wrap = document.createElement('label');
      wrap.className = 'opt';
      wrap.innerHTML = `
        <input type="checkbox" name="feature_bans" value="${b.key}">
        <div><strong>${b.key}</strong><span>${b.blurb}</span></div>`;
      bg.append(wrap);
    }
  }

  // Phrasebook preset radios. Selecting one autofills the template inputs
  // below, which the user can still edit per-line.
  const pgg = $('#phrasebook-grid');
  const phrasebooks = await fetchOpts('/api/phrasebooks');
  const pbookData = phrasebooks.templates || {};
  if (pgg) {
    pgg.innerHTML = '';
    pgg.append(makeRadio('phrasebook', '', '(none)', 'Use the language\'s default keywords.'));
    for (const p of phrasebooks.phrasebooks || []) {
      pgg.append(makeRadio('phrasebook', p.key, p.key, p.preview));
    }
  }
  // When the user changes the preset, autofill the template inputs.
  $$('input[name="phrasebook"]').forEach(r => r.addEventListener('change', (ev) => {
    const tpls = pbookData[ev.target.value] || {};
    $$('input[data-tpl]').forEach(input => {
      input.value = tpls[input.dataset.tpl] || '';
    });
  }));
}

function makeRadio(name, value, label, blurb) {
  const wrap = document.createElement('label');
  wrap.className = 'opt';
  wrap.innerHTML = `
    <input type="radio" name="${name}" value="${value}"${value === '' ? ' checked' : ''}>
    <div><strong>${label}</strong><span>${blurb || ''}</span></div>`;
  return wrap;
}

// ============================================================
// Roadmap §5.4: Live preview of the language being designed.
// Renders a representative code snippet that updates as the user
// changes the three core radios + persona/era/theme/phrasebook.
// ============================================================
const KEYWORD_THEMES_PREVIEW = {
  pirate: { var: 'loot', func: 'yarrn', return: 'deliver', if: 'ifnay', true: 'aye' },
  shakespearean: { var: 'thy', func: 'summon', return: 'yieldeth', if: 'perchance', true: 'verily' },
  corporate: { var: 'asset', func: 'deliverable', return: 'deliver', if: 'if_aligned', true: 'approved' },
  latin: { var: 'sit', func: 'munus', return: 'redde', if: 'si', true: 'verum' },
  cozy: { var: 'thing', func: 'recipe', return: 'share', if: 'when', true: 'yes' },
};

function updateLivePreview() {
  const form = $('#create-form');
  if (!form) return;
  const fd = new FormData(form);
  const syntax = fd.get('syntax') || 'c_like';
  const typing = fd.get('typing') || 'dynamic';
  const memory = fd.get('memory') || 'host_gc';
  const persona = fd.get('persona') || '';
  const era = fd.get('era') || '';
  const theme = fd.get('keyword_theme') || '';
  const phrasebook = fd.get('phrasebook') || '';
  const name = (fd.get('name') || 'mylang').toString().trim() || 'mylang';

  // File extension heuristic mirrors spec_builder
  const ext = '.' + (name.toLowerCase().slice(0, 3) || 'ml');

  // Theme keyword swaps. s_expression uses Lisp-flavored defaults;
  // stack_based uses Forth-flavored.
  const kw = KEYWORD_THEMES_PREVIEW[theme] || {};
  const k_var = kw.var || (
    syntax === 'python_like' ? 'let' :
    syntax === 's_expression' ? 'def' :
    syntax === 'stack_based' ? 'variable' : 'var'
  );
  const k_func = kw.func || (
    syntax === 'python_like' ? 'def' :
    syntax === 's_expression' ? 'defn' :
    syntax === 'stack_based' ? ':' : 'func'
  );
  const k_return = kw.return || 'return';
  const k_if = kw.if || 'if';
  const k_true = kw.true || (
    syntax === 's_expression' ? 'true' :
    syntax === 'stack_based' ? 'true' :
    typing === 'static' && syntax === 'python_like' ? 'True' : 'true'
  );

  // Render snippet by syntax
  let snippet;
  if (phrasebook === 'child_speak') {
    snippet =
      `make answer equal 0.\n` +
      `the way to add with a and b is {\n` +
      `    the answer is a + b.\n` +
      `}.\n` +
      `print(add(2, 3));`;
  } else if (phrasebook === 'shakespeare') {
    snippet =
      `${k_var} stage = "world";\n` +
      `${k_func} hail(target) {\n` +
      `    ${k_return} "Hail, " + target;\n` +
      `}\n` +
      `print(hail(stage));`;
  } else if (phrasebook === 'english_storybook') {
    snippet =
      `Once upon a time, ${k_var} count was 0.\n` +
      `Each time you call hello, return "hi!".\n` +
      `print(hello());`;
  } else if (phrasebook === 'ritual') {
    snippet =
      `${k_var} sigil = "circle";\n` +
      `${k_func} invoke(target) {\n` +
      `    ${k_return} "Cast on " + target;\n` +
      `}`;
  } else if (syntax === 's_expression') {
    if (typing === 'static') {
      snippet =
        `(: count Int)\n` +
        `(${k_var} count 0)\n` +
        `(: double (-> Int Int))\n` +
        `(${k_func} double (n) (* n 2))\n` +
        `(print (double 21))`;
    } else {
      snippet =
        `(${k_var} count 0)\n` +
        `(${k_func} double (n) (* n 2))\n` +
        `(print (double 21))`;
    }
  } else if (syntax === 'stack_based') {
    snippet =
      `\\ count = 0; double n = n * 2\n` +
      `${k_var} count\n` +
      `0 count !\n` +
      `: double ( n -- n*2 ) 2 * ;\n` +
      `21 double .`;
  } else if (syntax === 'python_like') {
    if (typing === 'static') {
      snippet =
        `${k_var} count: int = 0\n` +
        `${k_func} double(n: int) -> int:\n` +
        `    ${k_return} n * 2\n` +
        `print(double(21))`;
    } else {
      snippet =
        `${k_var} count = 0\n` +
        `${k_func} double(n):\n` +
        `    ${k_return} n * 2\n` +
        `print(double(21))`;
    }
  } else {
    if (typing === 'static') {
      snippet =
        `${k_var} count: int = 0;\n` +
        `${k_func} double(n: int) -> int {\n` +
        `    ${k_return} n * 2;\n` +
        `}\n` +
        `print(double(21));`;
    } else {
      snippet =
        `${k_var} count = 0;\n` +
        `${k_func} double(n) {\n` +
        `    ${k_return} n * 2;\n` +
        `}\n` +
        `print(double(21));`;
    }
  }

  $('#lp-name').textContent = name;
  $('#lp-ext').textContent = ext;
  $('#lp-snippet').textContent = snippet;

  // Lore line: composes era + persona + theme into a single one-liner that
  // sells what the user is making. Falls back to a default when nothing's
  // chosen.
  const flavorBits = [];
  if (era) flavorBits.push(era);
  if (persona) flavorBits.push(persona);
  if (theme) flavorBits.push(`${theme} keywords`);
  if (phrasebook) flavorBits.push(`${phrasebook} prose`);
  const lore = $('#lp-lore');
  if (flavorBits.length) {
    lore.classList.remove('muted');
    lore.textContent = `${name} — a ${syntax.replace('_', '-')} ${typing} language drawn from ${flavorBits.join(', ')}.`;
  } else {
    lore.classList.add('muted');
    lore.textContent = `Pick a persona, era, or theme to give ${name} character.`;
  }

  // Spec axis chips. Theme/persona/era/phrasebook are highlighted as
  // accent chips when set.
  const axes = $('#lp-axes');
  axes.innerHTML = '';
  const chip = (label, accent = false) => {
    const el = document.createElement('span');
    el.className = 'lp-axis' + (accent ? ' accent' : '');
    el.textContent = label;
    return el;
  };
  axes.append(chip(syntax));
  axes.append(chip(typing));
  axes.append(chip(memory));
  if (era) axes.append(chip(era, true));
  if (persona) axes.append(chip(persona, true));
  if (theme) axes.append(chip(`theme:${theme}`, true));
  if (phrasebook) axes.append(chip(`phrasebook:${phrasebook}`, true));
  // Feature bans (multi-select)
  for (const b of fd.getAll('feature_bans')) {
    axes.append(chip(b, true));
  }
}

// Wire reactivity: any form input change repaints the preview.
function _initLivePreview() {
  const form = $('#create-form');
  if (!form) return;
  // Use a delegated listener so dynamically-added persona/era/theme/phrasebook
  // radios participate too.
  form.addEventListener('input', updateLivePreview);
  form.addEventListener('change', updateLivePreview);
  updateLivePreview();
}
// Run on load (after presets populate).
document.addEventListener('DOMContentLoaded', () => setTimeout(_initLivePreview, 50));

// ============================================================
// Advanced customization
// ============================================================

// Default keywords per syntax style, used to populate the keyword overrides UI.
const DEFAULT_KEYWORDS = {
  c_like: {
    var: 'var', func: 'func', return: 'return', if: 'if', else: 'else',
    while: 'while', true: 'true', false: 'false', null: 'null', print: 'print',
  },
  python_like: {
    let: 'let', def: 'def', return: 'return', if: 'if', elif: 'elif',
    else: 'else', while: 'while', true: 'True', false: 'False', null: 'None',
    print: 'print', and: 'and', or: 'or', not: 'not',
  },
  // Roadmap families.md Tier 1: Lisp / Clojure-flavored defaults.
  s_expression: {
    var: 'def', func: 'defn', return: 'return', if: 'if', else: 'else',
    while: 'while', true: 'true', false: 'false', null: 'nil', print: 'print',
    and: 'and', or: 'or', not: 'not',
  },
  // Roadmap families.md Tier 1 (item 2.2): Forth-flavored stack-based.
  // No conventional `var`/`func` - colon definitions and variables live
  // in the dictionary. Listed for the keyword-overrides UI.
  stack_based: {
    var: 'variable', func: ':', return: ';', if: 'if', else: 'else',
    while: 'begin', true: 'true', false: 'false', null: 'nil',
    print: '.', and: 'and', or: 'or', not: 'not',
  },
};

function renderKeywordGrid(syntax) {
  const grid = $('#cust-keywords');
  if (!grid) return;
  grid.innerHTML = '';
  const defs = DEFAULT_KEYWORDS[syntax] || DEFAULT_KEYWORDS.c_like;
  for (const [k, def] of Object.entries(defs)) {
    const wrap = document.createElement('label');
    wrap.className = 'field';
    wrap.innerHTML = `<span>${k}</span><input type="text" data-kw="${k}" placeholder="${def}" maxlength="24">`;
    grid.append(wrap);
  }
}
renderKeywordGrid('c_like');
$$('input[name="syntax"]').forEach(r =>
  r.addEventListener('change', () => renderKeywordGrid(r.value))
);

// Custom tests, dynamic add/remove
function addCustomTestRow(name = '', source = '', expected = '') {
  const root = $('#cust-tests');
  const row = document.createElement('div');
  row.className = 'cust-test-row';
  row.innerHTML = `
    <div class="cust-test-head">
      <input type="text" data-tn="name" placeholder="my_feature_test" value="${name.replace(/"/g, '&quot;')}" pattern="[a-z][a-z0-9_]*">
      <button type="button" class="danger mini cust-test-rm">Remove</button>
    </div>
    <label class="field">
      <span>Source</span>
      <textarea data-tn="source" rows="3" placeholder="// program in your language">${source}</textarea>
    </label>
    <label class="field">
      <span>Expected stdout</span>
      <textarea data-tn="expected" rows="2" placeholder="exact output (one trailing newline OK)">${expected}</textarea>
    </label>
  `;
  row.querySelector('.cust-test-rm').addEventListener('click', () => row.remove());
  root.append(row);
}
$('#add-test-btn').addEventListener('click', () => addCustomTestRow());

function collectCustomization() {
  const c = {};

  const ext = $('#cust-ext').value.trim();
  if (ext) c.file_extension = ext;

  // Keywords: only include non-empty values different from default
  const kw = {};
  $$('#cust-keywords input[data-kw]').forEach(input => {
    const v = input.value.trim();
    if (v && v !== input.placeholder) kw[input.dataset.kw] = v;
  });
  if (Object.keys(kw).length) c.keyword_overrides = kw;

  // Operators
  const ops = {};
  $$('input[data-op]').forEach(input => {
    const v = input.value.trim();
    if (v) {
      ops[input.dataset.op] = v.split(',').map(s => s.trim()).filter(Boolean);
    }
  });
  if (Object.keys(ops).length) c.operator_overrides = ops;

  // Design notes, split lines
  const dn = $('#cust-design-notes').value.trim();
  if (dn) {
    c.extra_design_notes = dn.split(/\n+/).map(s => s.trim()).filter(Boolean);
  }

  // Per-component prompt notes
  const notes = {};
  $$('textarea[data-comp]').forEach(t => {
    const v = t.value.trim();
    if (v) notes[t.dataset.comp] = v;
  });
  if (Object.keys(notes).length) c.extra_prompt_notes = notes;

  // Additional tests
  const tests = [];
  $$('.cust-test-row').forEach(row => {
    const name = row.querySelector('[data-tn="name"]').value.trim();
    const source = row.querySelector('[data-tn="source"]').value;
    const expected = row.querySelector('[data-tn="expected"]').value;
    if (name && source.trim() && expected.trim()) {
      tests.push({ name, source, expected });
    }
  });
  if (tests.length) c.additional_tests = tests;

  return Object.keys(c).length ? c : null;
}

// ============================================================
// Create flow
// ============================================================
$('#create-form').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const fd = new FormData(ev.target);
  const provider = fd.get('provider');
  if (!provider) {
    toast('Pick a connection method first.', 'warn');
    return;
  }
  const body = {
    syntax: fd.get('syntax'),
    typing: fd.get('typing'),
    memory: fd.get('memory'),
    name: fd.get('name'),
    provider,
  };
  // Extended options (radios with empty value = default = leave unset)
  for (const k of ['comment_style', 'string_literals', 'numeric_literals',
                   'default_mutability', 'error_handling',
                   'multiple_returns', 'boolean_evaluation',
                   'naming_convention', 'null_model']) {
    const v = fd.get(k);
    if (v) body[k] = v;
  }
  // loop_forms: multi-select checkboxes
  const loopForms = fd.getAll('loop_forms');
  if (loopForms.length) body.loop_forms = loopForms;

  // Speculative metadata
  const persona = fd.get('persona');
  if (persona) body.persona = persona;
  const era = fd.get('era');
  if (era) body.era = era;
  const theme = fd.get('keyword_theme');
  if (theme) body.keyword_theme = theme;
  const bans = fd.getAll('feature_bans').filter(Boolean);
  if (bans.length) body.feature_bans = bans;
  const hc = $('#hostile-constraints')?.value.trim();
  if (hc) body.hostile_constraints = hc;
  const docs = fd.get('docs_persona');
  if (docs) body.docs_persona = docs;

  // Natural-language phrasebook (preset key + optional per-template overrides)
  const pbook = fd.get('phrasebook');
  if (pbook) body.phrasebook = pbook;
  const tpls = {};
  $$('input[data-tpl]').forEach(input => {
    const v = input.value.trim();
    if (v) tpls[input.dataset.tpl] = v;
  });
  if (Object.keys(tpls).length) body.natural_language = tpls;

  const customization = collectCustomization();
  if (customization) body.customization = customization;
  const submit = $('#forge-btn');
  submit.disabled = true;
  try {
    const r = await fetch('/api/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (!r.ok) {
      // Coherence errors come back with a structured list
      if (data.coherence_errors?.length) {
        const lines = data.coherence_errors.map(e =>
          `• ${e.message}${e.suggestion ? ` (${e.suggestion})` : ''}`
        ).join('\n');
        toast(`Incoherent options:\n${lines}`, 'error', 8000);
      } else {
        toast(data.error || 'Failed to start', 'error');
      }
      submit.disabled = false;
      return;
    }
    startProgress(body.name, data.job_id);
  } catch (e) {
    toast('Network error: ' + e.message, 'error');
    submit.disabled = false;
  }
});

// ============================================================
// Progress streaming (SSE)
// ============================================================
const stepsEl = $('#steps');
const stepIndex = new Map();
let timerInterval = null;
let timerStart = 0;

function setStep(label, status) {
  let li = stepIndex.get(label);
  if (!li) {
    li = document.createElement('li');
    const ico = document.createElement('span');
    ico.className = 'icon';
    const txt = document.createElement('span');
    txt.textContent = label;
    li.append(ico, txt);
    stepsEl.append(li);
    stepIndex.set(label, li);
  }
  const ico = li.querySelector('.icon');
  ico.className = `icon ${status}`;
  ico.textContent = ({ running: '', done: '✓', fail: '✕', info: 'i' })[status] || '·';
}

function startTimer() {
  timerStart = Date.now();
  const el = $('#progress-timer');
  el.textContent = '0:00';
  timerInterval = setInterval(() => {
    const secs = Math.floor((Date.now() - timerStart) / 1000);
    el.textContent = `${Math.floor(secs/60)}:${String(secs%60).padStart(2,'0')}`;
  }, 500);
}
function stopTimer() {
  if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
}

function startProgress(name, jobId) {
  currentLang = name;
  switchView('progress');
  stepsEl.innerHTML = '';
  stepIndex.clear();
  $('#progress-title').textContent = `Forging "${name}"…`;
  $('#progress-sub').textContent = `Job ${jobId}`;
  $('#spec-details').hidden = true;
  $('#report-details').hidden = true;
  $('#progress-actions').hidden = true;
  $('#report-cards').innerHTML = '';
  $('#report-text').hidden = true;
  startTimer();

  const es = new EventSource(`/api/stream/${jobId}`);
  es.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.kind === 'step') {
      setStep(msg.label, msg.status);
    } else if (msg.kind === 'spec') {
      $('#spec-details').hidden = false;
      $('#spec-json').textContent = JSON.stringify(msg.spec, null, 2);
    } else if (msg.kind === 'report') {
      $('#report-details').hidden = false;
      $('#report-details').open = true;
      renderReportCards(msg.report);
    } else if (msg.kind === 'done') {
      es.close();
      stopTimer();
      $('#progress-title').textContent = msg.success
        ? `"${name}" is ready ✓`
        : `"${name}" needs attention`;
      $('#progress-sub').textContent = msg.success
        ? 'All canonical tests passing.'
        : (msg.error || 'See the report below for details.');
      $('#progress-actions').hidden = false;
      $('#forge-btn').disabled = false;
      toast(msg.success ? `"${name}" forged successfully` : `"${name}" failed`,
            msg.success ? 'success' : 'error');
    }
  };
  es.onerror = () => { es.close(); stopTimer(); $('#forge-btn').disabled = false; };
}

function renderReportCards(r) {
  const grid = $('#report-cards');
  grid.innerHTML = '';
  for (const t of r.tests) {
    const tile = document.createElement('div');
    tile.className = `result-tile ${t.status}`;
    const mark = { pass: '✓', fail: '✕', missing: '?' }[t.status] || '·';
    tile.innerHTML = `<span class="check">${mark}</span><span class="name">${t.name}</span>`;
    if (t.status === 'fail' || t.status === 'missing') {
      tile.style.cursor = 'pointer';
      tile.addEventListener('click', () => showFailureDetail(t));
    }
    grid.append(tile);
  }
  if (r.missing_canonical?.length) {
    const note = document.createElement('div');
    note.className = 'muted';
    note.style.padding = '8px 14px 0';
    note.style.fontSize = '12px';
    note.style.gridColumn = '1 / -1';
    note.textContent = `Missing canonicals: ${r.missing_canonical.join(', ')}`;
    grid.append(note);
  }
}

function showFailureDetail(t) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal">
      <div class="modal-head">
        <h3>${t.name}. ${t.status === 'missing' ? 'missing' : 'failed'}</h3>
        <button class="ghost modal-close">✕</button>
      </div>
      <div class="modal-body">
        ${t.status === 'fail' ? `
          <div class="kv"><span>Stage</span><code>${t.stage || '?'}</code></div>
          <div class="kv"><span>Attributed to</span><code>${t.failing_component || '?'}</code></div>
          ${t.returncode != null ? `<div class="kv"><span>Exit code</span><code>${t.returncode}</code></div>` : ''}
          ${t.expected != null ? `<h4>Expected stdout</h4><pre class="code">${escapeHtml(t.expected) || '(empty)'}</pre>` : ''}
          ${t.actual != null ? `<h4>Actual stdout</h4><pre class="code">${escapeHtml(t.actual) || '(empty)'}</pre>` : ''}
          ${t.stderr ? `<h4>Stderr</h4><pre class="code">${escapeHtml(t.stderr)}</pre>` : ''}
        ` : `<p class="muted">This canonical test wasn't generated. Try the <strong>Repair</strong> action, the orchestrator will re-run the tests generator.</p>`}
      </div>
    </div>`;
  overlay.addEventListener('click', (ev) => { if (ev.target === overlay) overlay.remove(); });
  overlay.querySelector('.modal-close').addEventListener('click', () => overlay.remove());
  document.body.append(overlay);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[ch]));
}

async function showSpecModal(name) {
  const r = await fetch(`/api/spec/${name}`);
  if (!r.ok) { toast('No spec available', 'warn'); return; }
  const spec = await r.json();
  const opts = spec.options || {};
  const stdlib = (spec.stdlib?.functions || []).map(f =>
    `<li><code>${f.name}</code>. ${f.description}</li>`).join('');
  const notes = (spec.design_notes || []).map(n => `<li>${escapeHtml(n)}</li>`).join('');

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal">
      <div class="modal-head">
        <h3>${spec.lang_name} <span class="lc-ext">${spec.file_extension}</span></h3>
        <button class="ghost modal-close">✕</button>
      </div>
      <div class="modal-body">
        <h4>Options</h4>
        <div class="kv"><span>Syntax</span><code>${opts.syntax || '?'}</code></div>
        <div class="kv"><span>Typing</span><code>${opts.typing || '?'}</code></div>
        <div class="kv"><span>Memory</span><code>${opts.memory || '?'}</code></div>
        <div class="kv"><span>Block style</span><code>${spec.block_style || '?'}</code></div>
        <div class="kv"><span>Statements end with</span><code>${spec.statement_terminator || '?'}</code></div>

        <h4>Function definition</h4>
        <pre class="code">${escapeHtml(spec.function_definition?.syntax_example || '')}</pre>

        <h4>Variable declaration</h4>
        <pre class="code">${escapeHtml(spec.variable_declaration?.syntax_example || '')}</pre>

        <h4>Operators</h4>
        <div class="kv"><span>Arithmetic</span><code>${(spec.operators?.arithmetic || []).join(' ')}</code></div>
        <div class="kv"><span>Comparison</span><code>${(spec.operators?.comparison || []).join(' ')}</code></div>
        <div class="kv"><span>Logical</span><code>${(spec.operators?.logical || []).join(' ')}</code></div>

        <h4>Memory model</h4>
        <p class="muted">${escapeHtml(spec.memory_model?.notes || '')}</p>

        ${stdlib ? `<h4>Stdlib</h4><ul>${stdlib}</ul>` : ''}
        ${notes ? `<h4>Design notes</h4><ul>${notes}</ul>` : ''}

        <details>
          <summary>Raw spec JSON</summary>
          <pre class="code">${escapeHtml(JSON.stringify(spec, null, 2))}</pre>
        </details>
      </div>
    </div>`;
  overlay.addEventListener('click', (ev) => { if (ev.target === overlay) overlay.remove(); });
  overlay.querySelector('.modal-close').addEventListener('click', () => overlay.remove());
  document.body.append(overlay);
}

// Roadmap §4.6: language critic. Reads REVIEW.md if present, offers
// to generate one on demand. Markdown rendered very lightly (headings
// + paragraphs + code) — full md-it would be overkill for ~300 words.
async function showReviewModal(name) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal">
      <div class="modal-head">
        <h3>Review <span class="lc-ext">${escapeHtml(name)}</span></h3>
        <button class="ghost modal-close">✕</button>
      </div>
      <div class="modal-body" id="review-body">
        <p class="muted">Loading review…</p>
      </div>
    </div>`;
  overlay.addEventListener('click', (ev) => { if (ev.target === overlay) overlay.remove(); });
  overlay.querySelector('.modal-close').addEventListener('click', () => overlay.remove());
  document.body.append(overlay);
  const body = overlay.querySelector('#review-body');

  const renderMd = (md) => {
    // Minimal Markdown renderer: ###/####/**bold**/*italic*/`code`/-bullet/blank
    const lines = md.split('\n');
    const out = [];
    let inList = false;
    const inline = (s) => escapeHtml(s)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
    for (const raw of lines) {
      const ln = raw.trim();
      if (!ln) {
        if (inList) { out.push('</ul>'); inList = false; }
        continue;
      }
      if (ln.startsWith('### ')) {
        if (inList) { out.push('</ul>'); inList = false; }
        out.push(`<h4>${inline(ln.slice(4))}</h4>`);
      } else if (ln.startsWith('#### ')) {
        if (inList) { out.push('</ul>'); inList = false; }
        out.push(`<h5>${inline(ln.slice(5))}</h5>`);
      } else if (ln.startsWith('- ') || ln.startsWith('* ')) {
        if (!inList) { out.push('<ul>'); inList = true; }
        out.push(`<li>${inline(ln.slice(2))}</li>`);
      } else {
        if (inList) { out.push('</ul>'); inList = false; }
        out.push(`<p>${inline(ln)}</p>`);
      }
    }
    if (inList) out.push('</ul>');
    return out.join('\n');
  };

  const r = await fetch(`/api/review/${name}`);
  if (r.ok) {
    const { review } = await r.json();
    body.innerHTML = `<div class="review-md">${renderMd(review)}</div>` +
      `<div style="margin-top:14px;display:flex;gap:8px"><button class="ghost" id="rev-regen">↻ Regenerate review</button></div>`;
  } else {
    body.innerHTML = `
      <p class="muted">No review yet for <code>${escapeHtml(name)}</code>. Languages generated before the critic existed don't have one.</p>
      <button class="primary" id="rev-gen">✦ Generate review (one LLM call)</button>`;
  }

  const generate = async () => {
    body.innerHTML = '<p class="muted">Asking the critic… one LLM call, ~10-20s.</p>';
    const r2 = await fetch(`/api/review/${name}`, { method: 'POST' });
    const data = await r2.json();
    if (r2.ok) {
      body.innerHTML = `<div class="review-md">${renderMd(data.review)}</div>` +
        `<div style="margin-top:14px;display:flex;gap:8px"><button class="ghost" id="rev-regen">↻ Regenerate review</button></div>`;
      body.querySelector('#rev-regen')?.addEventListener('click', generate);
    } else {
      body.innerHTML = `<p style="color:var(--bad)">Critic failed: ${escapeHtml(data.error || 'unknown')}</p>`;
    }
  };
  body.querySelector('#rev-gen')?.addEventListener('click', generate);
  body.querySelector('#rev-regen')?.addEventListener('click', generate);
}

$('#go-create').addEventListener('click', () => switchView('create'));
$('#go-playground').addEventListener('click', async () => {
  await refreshPlaygroundLanguages();
  if (currentLang) {
    $('#play-lang').value = currentLang;
    $('#play-lang').dispatchEvent(new Event('change'));
    $('#play-example').value = 'hello_world';
    loadExample();
  }
  switchView('playground');
});

// ============================================================
// Library
// ============================================================
// Cache so the parent-picker dropdowns don't refetch every open.
let LIBRARY_CACHE = [];

async function refreshLibrary() {
  const r = await fetch('/api/languages' + _includeCatalogParam());
  const { languages } = await r.json();
  LIBRARY_CACHE = languages;
  const list = $('#library-list');
  const empty = $('#library-empty');
  $('#lib-count').textContent = languages.length;
  list.innerHTML = '';
  if (!languages.length) {
    empty.hidden = false;
    list.hidden = true;
    return;
  }
  empty.hidden = true;
  list.hidden = false;
  for (const lang of languages) {
    const card = document.createElement('article');
    card.className = 'lang-card';
    card.id = `lang-card-${lang.name}`;
    const opts = lang.options || {};
    const tags = ['syntax', 'typing', 'memory']
      .map(k => opts[k] ? `<span class="tag">${escapeHtml(opts[k])}</span>` : '')
      .filter(Boolean).join('');
    // Roadmap §3.1: per-card theme preview swatch using the language's
    // own palette. Uses inline style so the surrounding GUI doesn't need
    // the per-lang CSS pulled in.
    const tk = lang.theme_tokens || {};
    const swatchStyle = (tk.bg && tk.text)
      ? `background:${tk.bg};color:${tk.text};font-family:${tk.font_family || "'JetBrains Mono', monospace"};border-color:${tk.accent || 'currentColor'}`
      : '';
    const accentBar = tk.accent ? `style="background:${tk.accent}"` : '';
    // Roadmap §5.2: origin story replaces the bland tag list as the lede.
    const lore = lang.origin_story
      ? `<p class="lc-lore">${escapeHtml(lang.origin_story)}</p>`
      : '<p class="lc-lore muted">Generated from your option choices.</p>';
    // Roadmap §3.2: lineage chip. Shows parent names + generation when this
    // language was crossbred. Click → scrolls to a parent card.
    const lineageChip = lang.lineage && (lang.lineage.parents || []).length
      ? `<div class="lc-lineage" title="Crossbred from ${escapeHtml((lang.lineage.parents || []).join(' × '))}">
           <span class="lc-lineage-icon">⇆</span>
           <span class="lc-lineage-text">
             gen ${lang.lineage.generation || 1} ·
             ${lang.lineage.parents.map(p =>
               `<a class="lc-parent-link" data-parent="${escapeHtml(p)}">${escapeHtml(p)}</a>`
             ).join(' × ')}
             <span class="lc-lineage-strategy">(${escapeHtml(lang.lineage.strategy || 'random')})</span>
           </span>
         </div>`
      : '';
    card.innerHTML = `
      <div class="lc-accent" ${accentBar}></div>
      <div class="lc-head">
        <div class="lc-name">${escapeHtml(lang.name)}<span class="lc-ext">${escapeHtml(lang.ext)}</span></div>
        <span class="lc-status status-pill checking" data-status>checking…</span>
      </div>
      ${lineageChip}
      ${lore}
      <div class="lc-swatch" ${swatchStyle ? `style="${swatchStyle}"` : ''}>
        <span class="lc-swatch-prompt">$</span>
        <span class="lc-swatch-code">${escapeHtml(lang.name)} hello.${escapeHtml((lang.ext || '').replace(/^\./, ''))}</span>
      </div>
      <div class="lc-tags">${tags || '<span class="muted">no tags</span>'}</div>
      <div class="lc-actions lc-primary">
        <button class="primary lc-open" title="Open in the playground">Open</button>
        <button class="ghost lc-repl" title="In-browser REPL (Pyodide). No install.">▶ Browser</button>
        <button class="ghost lc-verify" title="Run all canonical tests">Verify</button>
        <button class="ghost lc-breed" title="Cross this language with another to make a child (roadmap §3.3)">⇆ Breed</button>
      </div>
      <div class="lc-actions lc-secondary">
        <button class="link lc-spec" title="View the resolved spec">Spec</button>
        <button class="link lc-review" title="Read the AI critic's review (roadmap §4.6)">Review</button>
        <button class="link lc-repair" title="Run the repair loop">Repair</button>
        <button class="link lc-regen" title="Regenerate from scratch with the same options">Regenerate</button>
        <button class="link lc-download" title="Download installable zip">Zip</button>
        <button class="link lc-html" title="Download single-file HTML REPL">HTML</button>
        <button class="link lc-delete danger-link" title="Delete from disk">Delete</button>
      </div>`;
    card.querySelector('.lc-open').addEventListener('click', () => openInPlayground(lang.name));
    card.querySelector('.lc-verify').addEventListener('click', (ev) => verifyLang(lang.name, ev.target, card));
    card.querySelector('.lc-repair').addEventListener('click', (ev) => repairLang(lang.name, ev.target, card));
    card.querySelector('.lc-spec').addEventListener('click', () => showSpecModal(lang.name));
    card.querySelector('.lc-review').addEventListener('click', () => showReviewModal(lang.name));
    card.querySelector('.lc-breed').addEventListener('click', () => showBreedModal(lang.name));
    card.querySelector('.lc-download').addEventListener('click', () => downloadLang(lang.name));
    card.querySelector('.lc-repl').addEventListener('click', () => {
      window.open(`/api/standalone/${lang.name}`, '_blank');
    });
    card.querySelector('.lc-html').addEventListener('click', () => {
      const a = document.createElement('a');
      a.href = `/api/standalone/${lang.name}?download=1`;
      a.download = `${lang.name}.repl.html`;
      document.body.append(a); a.click(); a.remove();
      toast(`Downloading ${lang.name}.repl.html, share it anywhere`, 'success', 5000);
    });
    card.querySelector('.lc-regen').addEventListener('click', () => regenLang(lang));
    card.querySelector('.lc-delete').addEventListener('click', () => deleteLang(lang.name));
    // Lineage chips: click a parent name → scroll to its card if present.
    card.querySelectorAll('.lc-parent-link').forEach(a => {
      a.addEventListener('click', (ev) => {
        ev.preventDefault();
        const parentName = a.dataset.parent;
        const target = document.getElementById(`lang-card-${parentName}`);
        if (target) {
          target.scrollIntoView({ behavior: 'smooth', block: 'center' });
          target.classList.add('lc-flash');
          setTimeout(() => target.classList.remove('lc-flash'), 1400);
        } else {
          toast(`Parent "${parentName}" no longer in your library.`, 'warn');
        }
      });
    });
    // Best-effort initial status check (cheap, runs the verifier locally)
    silentVerify(lang.name, card);
    list.append(card);
  }
}

// ============================================================
// Roadmap §3.3 — crossbreeding modal (parent picker + strategy)
// ============================================================
async function showBreedModal(parentAName) {
  // Use the cached library so we don't refetch.
  const others = LIBRARY_CACHE.filter(l => l.name !== parentAName);
  if (!others.length) {
    toast('You need at least one other language to crossbreed.', 'warn');
    return;
  }
  const parentA = LIBRARY_CACHE.find(l => l.name === parentAName);
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal" style="width:min(620px,95vw)">
      <div class="modal-head">
        <h3>Crossbreed <span class="lc-ext">${escapeHtml(parentAName)}</span> × …</h3>
        <button class="ghost modal-close">✕</button>
      </div>
      <div class="modal-body">
        <p class="muted">Pick a second parent and a merge strategy. The orchestrator merges the option dicts then runs the same generate → verify → repair → critique pipeline as a fresh language.</p>
        <div class="breed-form">
          <label class="field">
            <span>Other parent</span>
            <select id="breed-parent-b">
              ${others.map(l => `<option value="${escapeHtml(l.name)}">${escapeHtml(l.name)} ${l.options?.syntax ? `(${escapeHtml(l.options.syntax)}, ${escapeHtml(l.options.typing || '')})` : ''}</option>`).join('')}
            </select>
          </label>
          <label class="field">
            <span>Child name</span>
            <input type="text" id="breed-child-name" placeholder="e.g. ${escapeHtml(parentAName.slice(0,3) + (others[0]?.name || '').slice(0,3))}" pattern="[a-zA-Z_][a-zA-Z0-9_]*" required>
            <small>Lowercase identifier. Becomes the new package name.</small>
          </label>
          <fieldset class="ext-axis">
            <legend>Strategy</legend>
            <label><input type="radio" name="breed-strategy" value="random" checked> <strong>Random</strong> — each conflicting axis flips a coin between the two parents.</label>
            <label><input type="radio" name="breed-strategy" value="dominant"> <strong>Dominant</strong> — ${escapeHtml(parentAName)} wins ties. The other parent fills only the gaps.</label>
            <label><input type="radio" name="breed-strategy" value="union"> <strong>Union</strong> — list-valued axes (loops, design notes, bans) become the union of both.</label>
          </fieldset>
          <details class="advanced" style="margin-top:8px">
            <summary>Reproducibility</summary>
            <div class="adv-body">
              <label class="field">
                <span>Random seed (optional)</span>
                <input type="number" id="breed-seed" placeholder="e.g. 42">
                <small>Fix the seed to make the random merge reproducible.</small>
              </label>
            </div>
          </details>
          <div class="breed-summary muted small" id="breed-summary"></div>
          <div style="display:flex;gap:8px;margin-top:12px">
            <button class="primary big" id="breed-go">⇆ Forge crossbreed</button>
          </div>
        </div>
      </div>
    </div>`;
  overlay.addEventListener('click', (ev) => { if (ev.target === overlay) overlay.remove(); });
  overlay.querySelector('.modal-close').addEventListener('click', () => overlay.remove());
  document.body.append(overlay);

  const renderSummary = () => {
    const bName = overlay.querySelector('#breed-parent-b').value;
    const b = LIBRARY_CACHE.find(l => l.name === bName);
    const summary = overlay.querySelector('#breed-summary');
    if (!b || !parentA) { summary.textContent = ''; return; }
    const axes = ['syntax', 'typing', 'memory', 'comment_style', 'error_handling'];
    const rows = axes.map(ax => {
      const a = (parentA.options || {})[ax];
      const bb = (b.options || {})[ax];
      const same = (a == null && bb == null) || a === bb;
      return `<div class="kv"><span>${ax}</span>${a == null ? '<em>—</em>' : `<code>${escapeHtml(String(a))}</code>`} ${same ? '=' : '≠'} ${bb == null ? '<em>—</em>' : `<code>${escapeHtml(String(bb))}</code>`}</div>`;
    }).join('');
    summary.innerHTML = `<h5 style="margin:8px 0 4px">Axis differences</h5>${rows}`;
  };
  overlay.querySelector('#breed-parent-b').addEventListener('change', renderSummary);
  renderSummary();

  overlay.querySelector('#breed-go').addEventListener('click', async () => {
    const childName = overlay.querySelector('#breed-child-name').value.trim();
    if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(childName)) {
      toast('Child name must be a valid identifier.', 'error');
      return;
    }
    const parentB = overlay.querySelector('#breed-parent-b').value;
    const strategy = overlay.querySelector('input[name="breed-strategy"]:checked').value;
    const seedRaw = overlay.querySelector('#breed-seed').value.trim();
    const seed = seedRaw ? parseInt(seedRaw, 10) : null;
    const checked = $('input[name="provider"]:checked');
    const provider = checked ? checked.value : null;

    overlay.querySelector('#breed-go').disabled = true;
    overlay.querySelector('#breed-go').textContent = 'Crossing…';
    try {
      const r = await fetch('/api/crossbreed', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          parent_a: parentAName,
          parent_b: parentB,
          child_name: childName,
          strategy, seed, provider,
        }),
      });
      const data = await r.json();
      if (!r.ok) {
        toast('Crossbreed failed: ' + (data.error || r.statusText), 'error', 5000);
        overlay.querySelector('#breed-go').disabled = false;
        overlay.querySelector('#breed-go').textContent = '⇆ Forge crossbreed';
        return;
      }
      overlay.remove();
      startProgress(childName, data.job_id);
    } catch (e) {
      toast('Crossbreed failed: ' + e.message, 'error');
      overlay.querySelector('#breed-go').disabled = false;
      overlay.querySelector('#breed-go').textContent = '⇆ Forge crossbreed';
    }
  });
}

// ============================================================
// Roadmap §3.2 — family-tree visualization (pure SVG, no deps)
// ============================================================
$('#lib-tree-toggle')?.addEventListener('click', async () => {
  const pane = $('#family-tree-pane');
  pane.hidden = !pane.hidden;
  if (!pane.hidden) await renderFamilyTree();
});

async function renderFamilyTree() {
  const r = await fetch('/api/family-tree');
  const data = await r.json();
  const svgRoot = $('#family-tree-svg');
  svgRoot.innerHTML = '';
  if (!data.nodes.length) {
    svgRoot.innerHTML = '<p class="muted small">No languages yet.</p>';
    return;
  }
  // Compute hierarchical levels: roots are generation==0 (or no parents);
  // each child sits one level below its deepest parent. We keep this simple
  // — no fancy d3-force, just a column-per-generation layout. Plenty for
  // tens of languages; if it grows past hundreds, swap in a real graph lib.
  const byName = Object.fromEntries(data.nodes.map(n => [n.name, n]));
  const childrenOf = {};
  const parentsOf = {};
  for (const n of data.nodes) {
    childrenOf[n.name] = [];
    parentsOf[n.name] = [];
  }
  for (const e of data.edges) {
    if (childrenOf[e.parent]) childrenOf[e.parent].push(e.child);
    if (parentsOf[e.child]) parentsOf[e.child].push(e.parent);
  }
  // Topo-ish levels by max(parent.level)+1
  const level = {};
  let changed = true;
  for (const n of data.nodes) level[n.name] = 0;
  // Iterate until fixed-point (small graphs, cheap).
  for (let i = 0; i < data.nodes.length + 5 && changed; i++) {
    changed = false;
    for (const n of data.nodes) {
      const ps = parentsOf[n.name];
      if (!ps.length) continue;
      const want = Math.max(...ps.map(p => (level[p] ?? 0))) + 1;
      if (want > level[n.name]) { level[n.name] = want; changed = true; }
    }
  }
  // Bucket nodes by level, sort each level by name for stable layout.
  const levels = {};
  for (const n of data.nodes) {
    (levels[level[n.name]] ||= []).push(n);
  }
  Object.values(levels).forEach(arr => arr.sort((a, b) => a.name.localeCompare(b.name)));
  const maxLevel = Math.max(...Object.keys(levels).map(Number));
  const colW = 200;
  const rowH = 70;
  const padX = 40, padY = 30;
  const nodeW = 130, nodeH = 44;
  const positions = {};
  for (let lv = 0; lv <= maxLevel; lv++) {
    const arr = levels[lv] || [];
    arr.forEach((n, i) => {
      positions[n.name] = {
        x: padX + lv * colW,
        y: padY + i * rowH,
      };
    });
  }
  const maxRows = Math.max(...Object.values(levels).map(a => a.length), 1);
  const w = padX * 2 + (maxLevel + 1) * colW;
  const h = padY * 2 + maxRows * rowH;
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.setAttribute('width', '100%');
  svg.setAttribute('preserveAspectRatio', 'xMinYMin meet');
  svg.style.maxHeight = '520px';
  // Edges first so nodes render on top.
  for (const e of data.edges) {
    const p = positions[e.parent];
    const c = positions[e.child];
    if (!p || !c) continue;
    const path = document.createElementNS(ns, 'path');
    const x1 = p.x + nodeW, y1 = p.y + nodeH / 2;
    const x2 = c.x,         y2 = c.y + nodeH / 2;
    const mx = (x1 + x2) / 2;
    path.setAttribute('d', `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`);
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', e.strategy === 'dominant' ? '#9aa4cf' :
                                e.strategy === 'union' ? '#5fbf99' : '#7c8dca');
    path.setAttribute('stroke-width', '1.5');
    path.setAttribute('stroke-dasharray', e.strategy === 'random' ? '0' : '4,3');
    svg.append(path);
  }
  // Nodes
  for (const n of data.nodes) {
    const pos = positions[n.name];
    const g = document.createElementNS(ns, 'g');
    g.style.cursor = 'pointer';
    g.addEventListener('click', () => {
      const target = document.getElementById(`lang-card-${n.name}`);
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        target.classList.add('lc-flash');
        setTimeout(() => target.classList.remove('lc-flash'), 1400);
      }
    });
    const rect = document.createElementNS(ns, 'rect');
    rect.setAttribute('x', pos.x);
    rect.setAttribute('y', pos.y);
    rect.setAttribute('width', nodeW);
    rect.setAttribute('height', nodeH);
    rect.setAttribute('rx', 6);
    const tk = n.theme_tokens || {};
    rect.setAttribute('fill', tk.bg || '#1c2237');
    rect.setAttribute('stroke', tk.accent || '#3a4467');
    rect.setAttribute('stroke-width', '1.5');
    g.append(rect);
    const text = document.createElementNS(ns, 'text');
    text.setAttribute('x', pos.x + nodeW / 2);
    text.setAttribute('y', pos.y + nodeH / 2 - 2);
    text.setAttribute('text-anchor', 'middle');
    text.setAttribute('dominant-baseline', 'middle');
    text.setAttribute('fill', tk.text || '#e6e9f4');
    text.setAttribute('font-family', "'Inter', sans-serif");
    text.setAttribute('font-size', '13');
    text.setAttribute('font-weight', '600');
    text.textContent = n.name;
    g.append(text);
    const sub = document.createElementNS(ns, 'text');
    sub.setAttribute('x', pos.x + nodeW / 2);
    sub.setAttribute('y', pos.y + nodeH / 2 + 13);
    sub.setAttribute('text-anchor', 'middle');
    sub.setAttribute('fill', tk.text || '#9aa4cf');
    sub.setAttribute('font-family', "'JetBrains Mono', monospace");
    sub.setAttribute('font-size', '10');
    sub.setAttribute('opacity', '0.7');
    const subParts = [];
    if (n.persona) subParts.push(n.persona);
    if (n.era) subParts.push(n.era);
    if (n.keyword_theme) subParts.push(n.keyword_theme);
    sub.textContent = subParts.length ? subParts.join(' · ') : `gen ${n.generation}`;
    g.append(sub);
    svg.append(g);
  }
  svgRoot.append(svg);
}

async function openInPlayground(name) {
  currentLang = name;
  await refreshPlaygroundLanguages();
  $('#play-lang').value = name;
  $('#play-lang').dispatchEvent(new Event('change'));
  $('#play-example').value = 'hello_world';
  loadExample();
  switchView('playground');
}

function setCardStatus(card, kind, text) {
  const el = card.querySelector('[data-status]');
  if (!el) return;
  el.className = `lc-status status-pill ${kind}`;
  el.textContent = text;
}

async function silentVerify(name, card) {
  try {
    const r = await fetch(`/api/verify/${name}`, { method: 'POST' });
    const data = await r.json();
    const passing = data.tests.filter(t => t.status === 'pass').length;
    const total = data.tests.length;
    setCardStatus(card,
      data.all_passed ? 'ready' : 'missing',
      `${passing}/${total}`);
  } catch {
    setCardStatus(card, 'warn', '?');
  }
}

async function verifyLang(name, btn, card) {
  btn.disabled = true; btn.textContent = '…';
  try {
    const r = await fetch(`/api/verify/${name}`, { method: 'POST' });
    const data = await r.json();
    if (data.all_passed) {
      toast(`${name}: all ${data.tests.length} tests passing`, 'success');
      setCardStatus(card, 'ready', `${data.tests.length}/${data.tests.length} pass`);
    } else {
      const passing = data.tests.filter(t => t.status === 'pass').length;
      const failing = data.tests.filter(t => t.status === 'fail').length;
      const missing = data.missing_canonical?.length || 0;
      toast(`${name}: ${failing} failing${missing ? `, ${missing} missing` : ''}`, 'error');
      setCardStatus(card, 'missing', `${passing}/${data.tests.length} pass`);
    }
  } catch (e) {
    toast('Verify failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false; btn.textContent = 'Verify';
  }
}

async function repairLang(name, btn, card) {
  btn.disabled = true; btn.textContent = 'repairing…';
  toast(`Repairing ${name}, this may take a minute`, 'info');
  try {
    const r = await fetch(`/api/repair/${name}`, { method: 'POST' });
    const data = await r.json();
    if (!r.ok) {
      toast('Repair failed: ' + (data.error || r.statusText), 'error');
    } else {
      const passing = data.tests.filter(t => t.status === 'pass').length;
      toast(data.all_passed ? `${name} repaired ✓` : `${name}: ${passing}/${data.tests.length} pass`,
            data.all_passed ? 'success' : 'error');
      if (card) silentVerify(name, card);
    }
  } catch (e) {
    toast('Repair failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false; btn.textContent = 'Repair';
  }
}

async function regenLang(lang) {
  if (!confirm(`Regenerate "${lang.name}" from scratch? This deletes the current files and forges fresh ones with the same options.`)) return;
  try {
    const del = await fetch(`/api/language/${lang.name}`, { method: 'DELETE' });
    if (!del.ok) {
      const e = await del.json().catch(() => ({}));
      toast('Could not delete existing: ' + (e.error || del.statusText), 'error');
      return;
    }
    // Provider: prefer whichever is currently checked, else autodetect
    const checked = $('input[name="provider"]:checked');
    const provider = checked ? checked.value : null;
    const r = await fetch('/api/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...lang.options, name: lang.name, provider }),
    });
    const data = await r.json();
    if (!r.ok) {
      toast('Regen failed: ' + (data.error || r.statusText), 'error');
      return;
    }
    startProgress(lang.name, data.job_id);
  } catch (e) {
    toast('Regen failed: ' + e.message, 'error');
  }
}

function downloadLang(name) {
  // Browser handles the actual download via the Content-Disposition header.
  const a = document.createElement('a');
  a.href = `/api/download/${name}`;
  a.download = `${name}.zip`;
  document.body.append(a);
  a.click();
  a.remove();
  toast(`Downloading ${name}.zip, unzip and run \`pip install -e .\``, 'success', 5000);
}

async function deleteLang(name) {
  if (!confirm(`Delete language "${name}"? This removes generated/${name}/ from disk.`)) return;
  try {
    const r = await fetch(`/api/language/${name}`, { method: 'DELETE' });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      toast('Delete failed: ' + (data.error || r.statusText) + (data.hint ? '. ' + data.hint : ''), 'error', 6000);
      return;
    }
    toast(`${name} deleted`, 'success');
    refreshLibrary();
  } catch (e) {
    toast('Delete failed: ' + e.message, 'error');
  }
}

$('#lib-new-btn').addEventListener('click', () => switchView('create'));
$('#empty-new-btn').addEventListener('click', () => switchView('create'));

// ============================================================
// Playground
// ============================================================
async function refreshPlaygroundLanguages() {
  const r = await fetch('/api/languages' + _includeCatalogParam());
  const { languages } = await r.json();
  const sel = $('#play-lang');
  sel.innerHTML = '';
  if (!languages.length) {
    $('#playground-empty').hidden = false;
    $('.play-head').style.display = 'none';
    $('.play-grid').style.display = 'none';
    return;
  }
  $('#playground-empty').hidden = true;
  $('.play-head').style.display = '';
  $('.play-grid').style.display = '';
  for (const lang of languages) {
    const opt = document.createElement('option');
    opt.value = lang.name;
    opt.dataset.ext = lang.ext;
    opt.dataset.shipped = (lang.shipped || []).join(',');
    opt.textContent = `${lang.name}  (${lang.ext})`;
    sel.append(opt);
  }
  if (currentLang && languages.find(l => l.name === currentLang)) {
    sel.value = currentLang;
  } else {
    currentLang = sel.value;
  }
  sel.dispatchEvent(new Event('change'));
}

// Initialize CodeMirror on the playground textarea (graceful fallback if CDN missing)
let playEditor = null;
function ensurePlayEditor() {
  if (playEditor) return playEditor;
  const ta = $('#play-source');
  if (!ta) return null;
  if (typeof CodeMirror === 'undefined') return null;     // CDN didn't load, keep plain textarea
  playEditor = CodeMirror.fromTextArea(ta, {
    mode: { name: 'clike', keywords: {} },
    theme: 'material-darker',
    lineNumbers: true,
    matchBrackets: true,
    indentUnit: 4,
    extraKeys: {
      'Cmd-Enter': () => $('#play-run').click(),
      'Ctrl-Enter': () => $('#play-run').click(),
    },
  });
  // Make CodeMirror fill the pane
  playEditor.getWrapperElement().style.flex = '1';
  playEditor.getWrapperElement().style.fontSize = '13px';
  playEditor.refresh();
  return playEditor;
}

function setPlayMode(syntax) {
  const ed = ensurePlayEditor();
  if (!ed) return;
  let mode;
  if (syntax === 'python_like') mode = 'python';
  else if (syntax === 's_expression') mode = 'commonlisp';   // paren-matching + lispy highlighting
  else if (syntax === 'stack_based') mode = 'forth';         // Forth-style highlighting
  else mode = { name: 'clike', keywords: {} };
  ed.setOption('mode', mode);
}

function getPlaySource() {
  const ed = ensurePlayEditor();
  return ed ? ed.getValue() : $('#play-source').value;
}
function setPlaySource(s) {
  const ed = ensurePlayEditor();
  if (ed) { ed.setValue(s); ed.refresh(); }
  else { $('#play-source').value = s; }
}

$('#play-lang').addEventListener('change', async (ev) => {
  const opt = ev.target.selectedOptions[0];
  $('#play-ext').textContent = opt ? opt.dataset.ext : '';
  currentLang = ev.target.value || null;
  applyLangTheme(currentLang);  // roadmap §3.1: swap visual identity

  // Reset the example dropdown whenever the language changes. A stale
  // selection that's invalid for the new language would silently load
  // a broken source.
  const exSel = $('#play-example');
  if (exSel) exSel.value = '';
  // Don't clobber a buffer the user is editing.

  if (currentLang) {
    try {
      const r = await fetch(`/api/spec/${currentLang}`);
      if (r.ok) {
        const spec = await r.json();
        setPlayMode(spec?.options?.syntax);
        showCommentHint(spec);
      }
    } catch {}
    filterExampleDropdown(opt?.dataset?.shipped || '');
  }
});

function showCommentHint(spec) {
  /** Show a badge near the editor with the comment forms the language
   *  accepts. Avoids the "// rejected" pitfall when the language has a
   *  non-default comment style (block-only, # for line, etc.). */
  let hint = document.getElementById('play-comment-hint');
  if (!hint) {
    hint = document.createElement('span');
    hint.id = 'play-comment-hint';
    hint.className = 'kbd-hint';
    hint.style.marginLeft = '8px';
    const target = document.querySelector('.play-head-actions');
    if (target) target.prepend(hint);
  }
  const cs = spec?.comment_syntax || {};
  const parts = [];
  if (cs.line) parts.push(`${cs.line} line`);
  if (cs.block_open && cs.block_close) parts.push(`${cs.block_open}…${cs.block_close}`);
  hint.textContent = parts.length ? `Comments: ${parts.join(', ')}` : 'No comments';
  hint.style.display = '';
}

function filterExampleDropdown(shippedCsv) {
  /** Disable any <option> in the example dropdown that isn't in the
   *  language's shipped list. The language's `shipped` is a comma-joined
   *  string we stash on the <option> when the dropdown is built. */
  const shipped = new Set(shippedCsv.split(',').filter(Boolean));
  const sel = $('#play-example');
  if (!sel || !shipped.size) return;
  for (const opt of sel.options) {
    if (!opt.value) continue;        // the placeholder
    const ok = shipped.has(opt.value);
    opt.disabled = !ok;
    // Visual cue
    if (!ok && !opt.textContent.endsWith(' (n/a)')) {
      opt.textContent = opt.textContent + ' (n/a)';
    } else if (ok && opt.textContent.endsWith(' (n/a)')) {
      opt.textContent = opt.textContent.slice(0, -' (n/a)'.length);
    }
  }
}

async function loadExample() {
  const lang = $('#play-lang').value;
  const ex = $('#play-example').value;
  if (!lang || !ex) return;
  const r = await fetch(`/api/example/${lang}/${ex}`);
  if (r.ok) {
    const data = await r.json();
    setPlaySource(data.source);
    return;
  }
  // 404: don't drop a comment placeholder into the editor. The comment
  // syntax `//` is lexer-rejected by some languages and would itself
  // cause "compile failed". Just clear the buffer and show a toast.
  setPlaySource('');
  const data = await r.json().catch(() => ({}));
  toast(data.error || `'${ex}' isn't available for ${lang}.`, 'warn', 5000);
}
$('#play-example').addEventListener('change', loadExample);
$('#play-empty-new').addEventListener('click', () => switchView('create'));

$('#play-run').addEventListener('click', async () => {
  const lang = $('#play-lang').value;
  const source = getPlaySource();
  if (!lang) { toast('Pick a language first', 'warn'); return; }
  $('#play-output').textContent = 'Compiling…';
  $('#play-status').className = 'status-pill checking';
  $('#play-status').textContent = 'Running';
  $('#play-transpiled-details').hidden = true;
  try {
    const r = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lang, source }),
    });
    const data = await r.json();
    if (!data.ok) {
      $('#play-status').className = 'status-pill missing';
      $('#play-status').textContent = data.stage === 'compile' ? 'Compile error' : 'Runtime error';
      const hint = data.hint ? `Hint: ${data.hint}\n\n` : '';
      $('#play-output').textContent =
        hint +
        `${data.stage} failed\n\n` +
        (data.stdout ? `stdout:\n${data.stdout}\n\n` : '') +
        (data.stderr ? `stderr:\n${data.stderr}` : '');
      // Show the "Fix comments" one-click if the hint mentions comments.
      const isCommentHint = data.hint && /comment/i.test(data.hint);
      showFixCommentsButton(isCommentHint);
    } else {
      $('#play-status').className = 'status-pill ready';
      $('#play-status').textContent = 'Ran successfully';
      $('#play-output').textContent = data.stdout || '(no output)';
      if (data.transpiled) {
        $('#play-transpiled-details').hidden = false;
        $('#play-transpiled').textContent = data.transpiled;
      }
      showFixCommentsButton(false);
    }
    showCopyButton(true);
  } catch (e) {
    $('#play-status').className = 'status-pill missing';
    $('#play-status').textContent = 'Error';
    $('#play-output').textContent = String(e.message || e);
    showCopyButton(true);
  }
});

function showFixCommentsButton(visible) {
  let btn = document.getElementById('play-fix-comments');
  if (!btn) {
    btn = document.createElement('button');
    btn.id = 'play-fix-comments';
    btn.className = 'primary mini';
    btn.textContent = '✨ Fix comments';
    btn.style.cssText = 'position:absolute; top:18px; right:114px; font-size:11px;';
    btn.title = "Translate the editor's comments to this language's accepted form.";
    btn.addEventListener('click', async () => {
      const lang = $('#play-lang').value;
      if (!lang) return;
      const r = await fetch('/api/translate-comments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lang, source: getPlaySource() }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        toast(err.error || 'Could not translate comments', 'error');
        return;
      }
      const data = await r.json();
      setPlaySource(data.source);
      toast('Comments translated. Click Run again.', 'success');
      btn.style.display = 'none';
    });
    const pane = $('#play-output')?.parentElement;
    if (pane) {
      pane.style.position = 'relative';
      pane.append(btn);
    }
  }
  btn.style.display = visible ? '' : 'none';
}


function showCopyButton(visible) {
  let btn = document.getElementById('play-copy-output');
  if (!btn) {
    btn = document.createElement('button');
    btn.id = 'play-copy-output';
    btn.className = 'ghost mini';
    btn.textContent = 'Copy output';
    btn.style.cssText = 'position:absolute; top:18px; right:18px; font-size:11px;';
    btn.addEventListener('click', () => {
      const text = $('#play-output').textContent;
      navigator.clipboard.writeText(text).then(
        () => toast('Copied to clipboard', 'success', 2000),
        () => toast('Could not copy. Select the text manually.', 'warn'),
      );
    });
    const pane = $('#play-output')?.parentElement;
    if (pane) {
      pane.style.position = 'relative';
      pane.append(btn);
    }
  }
  btn.style.display = visible ? '' : 'none';
}

// Run-on-all: each language runs its own shipped copy of the same example.
// If no example is selected, falls back to running the literal editor source
// on every language (only useful when languages share syntax).
$('#play-run-all').addEventListener('click', async () => {
  const example = $('#play-example').value;
  const source = getPlaySource();
  if (!example && !source.trim()) { toast('Pick an example, or type some code first', 'warn'); return; }

  const body = example ? { example } : { source };
  toast(example ? `Running ${example} on every language…` : 'Running source on every language…', 'info', 2000);

  const r = await fetch('/api/run-all', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    toast(err.error || 'Run-all failed', 'error');
    return;
  }
  const { results, example: ex } = await r.json();
  showRunAllModal(results, ex);
});

function showRunAllModal(results, example) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  const langs = Object.entries(results);
  const tiles = langs.map(([name, res]) => {
    const ok = res.ok && res.stage === 'ok';
    const skipped = res.stage === 'skipped';
    const klass = ok ? 'pass' : (skipped ? 'missing' : 'fail');
    const icon = ok ? '✓' : (skipped ? '–' : '✕');
    const output = ok
      ? (res.stdout || '(no output)')
      : skipped
        ? `(skipped: ${res.stderr})`
        : `${res.stage}: ${res.stderr || 'failed'}`;
    const sourcePane = res.source
      ? `<details><summary>source (${res.ext || ''})</summary><pre class="code">${escapeHtml(res.source)}</pre></details>`
      : '';
    return `
      <div class="run-all-tile ${klass}">
        <div class="run-all-head">
          <span class="check">${icon}</span>
          <strong>${name}</strong>
        </div>
        <pre class="code">${escapeHtml(output)}</pre>
        ${sourcePane}
      </div>`;
  }).join('');
  const passing = langs.filter(([,r]) => r.ok && r.stage === 'ok').length;
  const skipped = langs.filter(([,r]) => r.stage === 'skipped').length;
  const title = example
    ? `<code>${escapeHtml(example)}</code> across ${langs.length} languages`
    : `Run on all`;
  const subtitle = `${passing} succeeded${skipped ? `, ${skipped} skipped` : ''}, ${langs.length - passing - skipped} failed`;
  overlay.innerHTML = `
    <div class="modal" style="width:min(1200px,95vw); max-width:1200px;">
      <div class="modal-head">
        <h3>${title} <span class="muted">${subtitle}</span></h3>
        <button class="ghost modal-close">✕</button>
      </div>
      <div class="modal-body">
        <div class="run-all-grid">${tiles}</div>
      </div>
    </div>`;
  overlay.addEventListener('click', (ev) => { if (ev.target === overlay) overlay.remove(); });
  overlay.querySelector('.modal-close').addEventListener('click', () => overlay.remove());
  document.body.append(overlay);
}

// Cmd/Ctrl+Enter inside source runs the program
$('#play-source').addEventListener('keydown', (ev) => {
  if ((ev.metaKey || ev.ctrlKey) && ev.key === 'Enter') {
    ev.preventDefault();
    $('#play-run').click();
  }
});

// ============================================================
// Footer stats
// ============================================================
async function refreshFooter() {
  try {
    const r = await fetch('/api/languages' + _includeCatalogParam());
    const { languages } = await r.json();
    $('#footer-stats').textContent = `${languages.length} language${languages.length === 1 ? '' : 's'} forged`;
  } catch {}
}

async function refreshSamples() {
  try {
    const r = await fetch('/api/samples');
    const data = await r.json();
    const group = $('#play-demos-group');
    if (!group) return;
    group.innerHTML = '';
    for (const s of data.samples) {
      const o = document.createElement('option');
      o.value = s.key;
      o.textContent = s.title;
      group.append(o);
    }
  } catch {}
}

// ============================================================
// Kata system (LeetCode-style problem library + detail view)
// ============================================================
let currentKata = null;
let currentPack = null;          // full pack object for filter rebuilds
// `currentLang` is already declared earlier in this file (used by other tabs)

async function refreshKataLanguages() {
  const r = await fetch('/api/languages' + _includeCatalogParam());
  const { languages } = await r.json();
  const sel = $('#kata-lang');
  sel.innerHTML = '';
  for (const lang of languages) {
    const o = document.createElement('option');
    o.value = lang.name;
    o.textContent = `${lang.name} (${lang.ext})`;
    sel.append(o);
  }
  if (sel.value) loadKataPack(sel.value);
}
$('#kata-lang')?.addEventListener('change', (ev) => loadKataPack(ev.target.value));

async function loadKataPack(lang) {
  if (!lang) return;
  currentLang = lang;
  applyLangTheme(lang);  // roadmap §3.1: themed kata workspace
  // Remember which kata was open so we can re-select it after a reload —
  // otherwise force=true reloads leave the GUI showing a stale `currentKata`
  // object that no longer matches the freshly-validated pack.
  const previousId = currentKata && currentKata.lang === lang ? currentKata.kata.id : null;
  const r = await fetch(`/api/katas/${lang}`);
  const list = $('#kata-list');
  const detailEmpty = $('#kata-detail-empty');
  const detail = $('#kata-detail');
  list.innerHTML = '';
  $('#kata-count').textContent = '';
  $('#kata-pack-status').textContent = '';
  if (!r.ok) {
    detailEmpty.style.display = '';
    detail.hidden = true;
    currentKata = null;
    list.innerHTML = '<p class="muted" style="font-size:12px;padding:12px">No problem pack loaded yet. Click <strong>📚 Load pack</strong> above to fetch the LeetCode classics for this language.</p>';
    return;
  }
  const pack = await r.json();
  currentPack = pack;
  renderKataLibrary();

  // If we had a kata open and it's still in the new pack, re-select it
  // with the FRESH data (helpers, tags, etc. may have updated). If it's
  // gone (rare — only on schema change), fall back to empty state.
  if (previousId) {
    const newKata = pack.katas.find(k => k.id === previousId);
    if (newKata) {
      const row = [...$$('.kata-row')].find(el =>
        el.querySelector('.kata-row-title')?.textContent.startsWith(newKata.title));
      selectKata(lang, pack, newKata, row);
    } else {
      detailEmpty.style.display = '';
      detail.hidden = true;
      currentKata = null;
    }
  } else {
    detailEmpty.style.display = '';
    detail.hidden = true;
  }
}

function renderKataLibrary() {
  /** Render the problem list with tags, filters, and search. Called on
   *  load AND on every filter/search change. */
  if (!currentPack) return;
  const pack = currentPack;
  const lang = currentLang;
  const list = $('#kata-list');
  list.innerHTML = '';

  // Header: count + source attribution
  const src = pack.source || '';
  let srcBadge = '';
  if (src.startsWith('curated:')) srcBadge = ' <span class="src-badge curated" title="Hand-written curated pack">curated</span>';
  else if (src.startsWith('translated:')) srcBadge = ' <span class="src-badge translated" title="LLM-translated to this language">translated</span>';
  const cachedBadge = pack.cached ? ' <span class="src-badge cached" title="Cache hit">cached</span>' : '';
  $('#kata-pack-status').innerHTML = srcBadge + cachedBadge;

  // Build tag filter options from this pack's actual tags. Always rebuild
  // when this is called from loadKataPack (i.e. when `#kata-list` is empty —
  // we just cleared it above). For mid-render updates (filter typing), keep
  // the dropdown stable to preserve the user's selection.
  const tagFilter = $('#kata-filter-tag');
  // Tag this pack with a signature so we know when to rebuild
  const tagSig = pack.katas.map(k => (k.tags || []).join(',')).join('|');
  if (tagFilter && tagFilter.dataset.tagSig !== tagSig) {
    const allTags = new Set();
    for (const k of pack.katas) (k.tags || []).forEach(t => allTags.add(t));
    const previousValue = tagFilter.value;
    tagFilter.innerHTML = '<option value="">All tags</option>';
    for (const t of [...allTags].sort()) {
      const o = document.createElement('option');
      o.value = t; o.textContent = t;
      tagFilter.append(o);
    }
    // Restore previous selection only if it's still valid for this pack
    if (allTags.has(previousValue)) tagFilter.value = previousValue;
    tagFilter.dataset.tagSig = tagSig;
  }

  // Apply current filters
  const search = ($('#kata-search')?.value || '').toLowerCase().trim();
  const fDiff = $('#kata-filter-difficulty')?.value || '';
  const fTag = $('#kata-filter-tag')?.value || '';
  const fStatus = $('#kata-filter-status')?.value || '';

  const passed = JSON.parse(localStorage.getItem(`forge.katas.${lang}.passed`) || '[]');

  let visible = 0;
  for (const kata of pack.katas) {
    if (search && !kata.title.toLowerCase().includes(search) &&
        !(kata.problem || '').toLowerCase().includes(search)) continue;
    if (fDiff && kata.difficulty !== fDiff) continue;
    if (fTag && !(kata.tags || []).includes(fTag)) continue;
    const isPassed = passed.includes(kata.id);
    if (fStatus === 'todo' && isPassed) continue;
    if (fStatus === 'solved' && !isPassed) continue;

    const row = document.createElement('div');
    row.className = 'kata-row' + (isPassed ? ' passed' : '');
    if (currentKata && currentKata.kata.id === kata.id) row.classList.add('active');
    const stubBadge = kata.stub_rescued
      ? '<span class="src-badge stub" title="Auto-check unavailable for this language. Problem still attemptable.">no auto-check</span>'
      : '';
    // Auto-validation status badge. Set by /api/katas/.../load-pack after
    // running each kata's reference solution against every test. Verified
    // = the shipped reference works on every test; users get full
    // auto-check. The `via` field names the rescue strategy that produced
    // the reference (none = pack's original; cascade = pattern-match
    // base solution; curated_match = substituted from stack_classics).
    const v = kata.validation || {};
    let validationBadge = '';
    if (v.status === 'verified' && v.tests_run) {
      let label = '✓ verified';
      let title = `Reference solution verified: passed ${v.tests_passed}/${v.tests_run} tests on this language.`;
      if (v.via === 'cascade') {
        label = '✓ base solution';
        title = `Auto-generated cascade reference (passed ${v.tests_passed}/${v.tests_run} tests). The reference hardcodes test-input -> expected-output as a starter; users should write their own algorithm.`;
      } else if (v.via === 'curated_match') {
        label = '✓ verified';
        title = `Reference substituted from the curated stack_classics pack (matched function_name). Passed ${v.tests_passed}/${v.tests_run} tests.`;
      } else if (v.via === 'case_analysis_fallback') {
        title += ' (case-analysis fallback)';
      }
      validationBadge =
        `<span class="src-badge verified" title="${escapeHtml(title)}">${label}</span>`;
    } else if (v.status === 'failed') {
      validationBadge =
        `<span class="src-badge failed" title="${escapeHtml(v.reason || 'reference broken')}">⚠ ref broken</span>`;
    }
    const acceptance = kata.acceptance_rate != null
      ? ` · <span title="Indicative acceptance rate">${(kata.acceptance_rate * 100).toFixed(0)}%</span>`
      : '';
    const tagsHtml = (kata.tags || []).slice(0, 3).map(t =>
      `<span class="kata-tag">${escapeHtml(t)}</span>`).join('');
    row.innerHTML = `
      <div class="kata-row-title">${escapeHtml(kata.title)}${stubBadge}${validationBadge}
        <span class="kata-row-status">${isPassed ? '✓' : ''}</span>
      </div>
      <div class="kata-row-meta">
        <span class="status-pill ${kata.difficulty}">${kata.difficulty}</span>
        ${acceptance}
      </div>
      <div class="kata-row-tags">${tagsHtml}</div>`;
    row.addEventListener('click', () => selectKata(lang, pack, kata, row));
    list.append(row);
    visible++;
  }

  $('#kata-count').textContent = `${visible}/${pack.katas.length}`;

  if (visible === 0) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.style.cssText = 'font-size:12px;padding:12px;text-align:center';
    empty.textContent = 'No problems match these filters.';
    list.append(empty);
  }

  // Drop-list at bottom (untranslatable katas)
  if (Array.isArray(pack.dropped) && pack.dropped.length > 0) {
    const partial = document.createElement('details');
    partial.className = 'kata-partial';
    partial.innerHTML = `
      <summary><strong>${pack.dropped.length} dropped</strong> during translation</summary>
      <div style="margin-top:8px">${pack.dropped.map(d => `
        <details class="kata-drop">
          <summary>✕ ${escapeHtml(d.id || 'unknown')}</summary>
          <pre class="code">${escapeHtml(d.reason || '')}</pre>
        </details>`).join('')}</div>
      <button class="ghost" id="kata-retry-dropped" style="margin-top:10px;font-size:12px">↻ Retry dropped</button>`;
    list.append(partial);
    partial.querySelector('#kata-retry-dropped')?.addEventListener('click', async (ev) => {
      ev.preventDefault();
      const r2 = await fetch(`/api/katas/${lang}/load-pack/${(src.split(':')[1] || 'classics')}?force=true`, { method: 'POST' });
      if (r2.ok) { toast('Re-running translation…', 'info', 3000); loadKataPack(lang); }
      else { toast('Retry failed', 'error'); }
    });
  }
}

// Re-render on filter/search changes
['#kata-search', '#kata-filter-difficulty', '#kata-filter-tag', '#kata-filter-status']
  .forEach(sel => $(sel)?.addEventListener('input', renderKataLibrary));

function selectKata(lang, pack, kata, rowEl) {
  currentKata = { lang, kata };
  $$('.kata-row').forEach(r => r.classList.remove('active'));
  rowEl?.classList.add('active');
  $('#kata-detail-empty').style.display = 'none';
  $('#kata-detail').hidden = false;

  // Description tab content
  $('#kata-title').textContent = kata.title;
  const diff = $('#kata-difficulty');
  diff.className = `status-pill ${kata.difficulty}`;
  diff.textContent = kata.difficulty;
  $('#kata-acceptance').textContent =
    kata.acceptance_rate != null ? `· ${(kata.acceptance_rate * 100).toFixed(0)}% acceptance` : '';

  // Tags
  const tagsBox = $('#kata-tags');
  tagsBox.innerHTML = (kata.tags || []).map(t =>
    `<span class="kata-tag">${escapeHtml(t)}</span>`).join('');

  // Problem statement
  $('#kata-problem').textContent = kata.problem || '';

  // Examples
  const examplesBox = $('#kata-examples');
  if (Array.isArray(kata.examples) && kata.examples.length) {
    examplesBox.innerHTML = '<h5 style="margin:14px 0 8px;font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:0.04em">Examples</h5>' +
      kata.examples.map((ex, i) => `
        <div class="kata-example">
          <div class="kata-example-label">Example ${i + 1}</div>
          <div class="kata-example-row"><strong>Input:</strong> <code>${escapeHtml(ex.input)}</code></div>
          <div class="kata-example-row"><strong>Output:</strong> <code>${escapeHtml(ex.output)}</code></div>
          ${ex.explanation ? `<div class="kata-example-row" style="color:var(--muted);font-size:12px;margin-top:4px">${escapeHtml(ex.explanation)}</div>` : ''}
        </div>`).join('');
  } else {
    examplesBox.innerHTML = '';
  }

  // Constraints
  const constraintsBox = $('#kata-constraints');
  if (Array.isArray(kata.constraints) && kata.constraints.length) {
    constraintsBox.innerHTML = '<h5>Constraints</h5><ul>' +
      kata.constraints.map(c => `<li>${escapeHtml(c)}</li>`).join('') + '</ul>';
  } else {
    constraintsBox.innerHTML = '';
  }

  // Sample tests: visible to the user. Submit additionally runs the hidden
  // tests (those at indices NOT in sample_test_indices). Mirroring how
  // LeetCode shows "Test Case 1, Test Case 2, ..." plus "+ N additional
  // test cases" beneath them.
  const sampleBox = $('#kata-sample-tests');
  const allTests = Array.isArray(kata.tests) ? kata.tests : [];
  const sampleIdxs = (kata.sample_test_indices && kata.sample_test_indices.length)
    ? kata.sample_test_indices
    : (allTests.length ? [0] : []);
  if (allTests.length) {
    const sampleTests = sampleIdxs
      .map(i => allTests[i])
      .filter(Boolean);
    const hiddenCount = allTests.length - sampleTests.length;
    sampleBox.hidden = false;
    sampleBox.innerHTML =
      `<h5>Sample tests</h5>` +
      sampleTests.map((t, i) => `
        <div class="kata-sample-row">
          <span class="kata-sample-num">#${i + 1}</span>
          <div class="kata-sample-body">
            <div><span class="kata-sample-label">Input</span> <code>${escapeHtml(t.call)}</code></div>
            <div><span class="kata-sample-label">Output</span> <code>${escapeHtml(t.expected)}</code></div>
          </div>
        </div>`).join('') +
      (hiddenCount > 0
        ? `<p class="muted small kata-hidden-note">+ ${hiddenCount} hidden test${hiddenCount === 1 ? '' : 's'}, run via <strong>Submit</strong>.</p>`
        : '');
  } else {
    sampleBox.hidden = true;
  }

  // Helpers info (when the kata provides node/leaf/to_ll/etc.)
  const helpersBox = $('#kata-helpers-info');
  if (kata.helpers && kata.helpers.trim()) {
    const helperFns = [...kata.helpers.matchAll(/\b(?:func|def|the way to)\s+(\w+)/g)].map(m => m[1]);
    helpersBox.hidden = false;
    helpersBox.innerHTML = `<strong>Provided helpers:</strong> ${
      helperFns.length ? helperFns.map(f => `<code>${escapeHtml(f)}</code>`).join(', ')
                       : 'data-structure constructors are pre-defined'
    }. They're already in scope when your code runs.`;
  } else {
    helpersBox.hidden = true;
  }

  // Editor: load saved draft, fall back to starter
  const draftKey = `forge.katas.${lang}.${kata.id}.draft`;
  $('#kata-editor').value = localStorage.getItem(draftKey) || kata.starter_code || '';
  $('#kata-editor-lang').textContent = `${lang}`;
  $('#kata-result').className = 'kata-result';
  $('#kata-result').innerHTML = '';
  // "Load reference" button in the editor row: only meaningful when a
  // reference exists. Becomes the one-click escape hatch when the user's
  // copy/paste corrupted their code.
  const loadRefBtn = $('#kata-load-ref');
  if (loadRefBtn) loadRefBtn.hidden = !kata.reference_solution;

  // Reset to Description tab
  switchKataTab('description');

  // Solution tab: locked unless passed
  const passed = JSON.parse(localStorage.getItem(`forge.katas.${lang}.passed`) || '[]');
  const solutionLocked = !passed.includes(kata.id);
  $('#kata-solution-locked').hidden = !solutionLocked;
  $('#kata-solution-revealed').hidden = solutionLocked;
  if (!solutionLocked) {
    $('#kata-reference-pre').textContent = kata.reference_solution || '(no reference)';
  }

  // Submissions tab: load history
  renderKataSubmissions(lang, kata.id);
}

// --- Tab switching ---
function switchKataTab(name) {
  $$('.kata-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  $$('.kata-pane').forEach(p => p.hidden = p.dataset.tabPane !== name);
}
$$('.kata-tab').forEach(t => t.addEventListener('click', () => switchKataTab(t.dataset.tab)));

// --- Show solution (unlocks the Solution tab even without passing) ---
$('#kata-show-solution')?.addEventListener('click', () => {
  if (!currentKata) return;
  $('#kata-solution-locked').hidden = true;
  $('#kata-solution-revealed').hidden = false;
  $('#kata-reference-pre').textContent = currentKata.kata.reference_solution || '(no reference)';
  // Show helpers code if the kata has any. They're auto-prepended at test
  // time, but users want to see what's defined for them.
  const helpers = currentKata.kata.helpers || '';
  if (helpers.trim()) {
    $('#kata-helpers-code').hidden = false;
    $('#kata-helpers-pre').textContent = helpers;
  } else {
    $('#kata-helpers-code').hidden = true;
  }
  toast('Solution revealed. Try writing yours first next time!', 'info', 3000);
});

// --- Copy reference to clipboard ---
$('#kata-copy-solution')?.addEventListener('click', async () => {
  if (!currentKata) return;
  const text = currentKata.kata.reference_solution || '';
  try {
    await navigator.clipboard.writeText(text);
    toast('Reference copied to clipboard', 'success', 2000);
  } catch {
    toast('Clipboard blocked - use "Load into editor" instead', 'warn', 4000);
  }
});

// --- Load reference DIRECTLY into the editor (bypasses any clipboard
// quirks where browsers occasionally mangle whitespace, smart-quotes, or
// line endings on copy from a <pre>). The literal stored string lands in
// the textarea, byte-for-byte. This is the one-click fix for "I pasted
// the solution and got a compile error."
$('#kata-load-solution')?.addEventListener('click', () => {
  if (!currentKata) return;
  const ref = currentKata.kata.reference_solution || '';
  if (!ref) { toast('No reference solution available', 'warn'); return; }
  $('#kata-editor').value = ref;
  // Persist as a draft so a refresh keeps it
  const k = `forge.katas.${currentKata.lang}.${currentKata.kata.id}.draft`;
  localStorage.setItem(k, ref);
  // Visually hop back to the editor
  $('#kata-editor').focus();
  $('#kata-editor').scrollIntoView({ behavior: 'smooth', block: 'center' });
  toast('Reference loaded into the editor. Click Submit to verify.', 'success', 3500);
});

// --- Editor draft autosave ---
$('#kata-editor')?.addEventListener('input', () => {
  if (!currentKata) return;
  const k = `forge.katas.${currentKata.lang}.${currentKata.kata.id}.draft`;
  localStorage.setItem(k, $('#kata-editor').value);
});

$('#kata-reset')?.addEventListener('click', () => {
  if (!currentKata) return;
  $('#kata-editor').value = currentKata.kata.starter_code || '';
  const k = `forge.katas.${currentKata.lang}.${currentKata.kata.id}.draft`;
  localStorage.removeItem(k);
});

// "Load reference" button right next to Run/Submit. Same behavior as the
// Solution-tab button but doesn't require revealing the solution first
// (so a user fighting a copy/paste corruption issue can recover with
// one click without losing their unrevealed-solution status).
$('#kata-load-ref')?.addEventListener('click', () => {
  if (!currentKata) return;
  const ref = currentKata.kata.reference_solution || '';
  if (!ref) { toast('No reference available for this kata', 'warn'); return; }
  if (!confirm('This replaces your current code with the reference solution. Continue?')) {
    return;
  }
  $('#kata-editor').value = ref;
  const k = `forge.katas.${currentKata.lang}.${currentKata.kata.id}.draft`;
  localStorage.setItem(k, ref);
  $('#kata-editor').focus();
  toast('Reference loaded into the editor.', 'success', 2500);
});

// --- Run (sample tests, full per-test results) ---
$('#kata-run')?.addEventListener('click', () => runKataCheck('run'));
// --- Submit (full hidden suite, first-failure-only) ---
$('#kata-submit')?.addEventListener('click', () => runKataCheck('submit'));

async function runKataCheck(mode) {
  if (!currentKata) return;
  const result = $('#kata-result');
  result.className = 'kata-result show';
  result.textContent = mode === 'run' ? 'Running sample tests…' : 'Submitting against hidden tests…';
  const t0 = performance.now();
  const r = await fetch(`/api/katas/${currentKata.lang}/${currentKata.kata.id}/check`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code: $('#kata-editor').value, mode }),
  });
  const data = await r.json();
  const elapsed = (performance.now() - t0).toFixed(0);

  // Persist a submission record
  const subKey = `forge.katas.${currentKata.lang}.${currentKata.kata.id}.subs`;
  const subs = JSON.parse(localStorage.getItem(subKey) || '[]');
  subs.unshift({
    when: Date.now(), mode, passed: data.passed,
    stage: data.stage, elapsed_ms: parseInt(elapsed),
  });
  localStorage.setItem(subKey, JSON.stringify(subs.slice(0, 20)));

  if (mode === 'run') {
    renderRunResults(data, elapsed, result);
  } else {
    renderSubmitResult(data, elapsed, result);
  }
}

function renderRunResults(data, elapsed, result) {
  if (!data.results && !data.stage) {
    result.className = 'kata-result show failed';
    result.textContent = `Error: ${data.stderr || 'unknown'}`;
    return;
  }
  if (data.stage && data.stage !== 'ok' && data.stage !== 'compare') {
    result.className = 'kata-result show failed';
    let label;
    if (data.stage === 'preflight') label = '⚠ Your code doesn\'t look right yet\n\n';
    else if (data.stage === 'compile') label = '✕ Compilation error\n';
    else if (data.stage === 'run') label = '✕ Runtime error\n';
    else label = `✕ ${data.stage}: `;
    let body = label + (data.stderr || '');
    if (data.program_excerpt) {
      body += `\n\n--- The actual program (your code + auto-prepended helpers + test prints) ---\n${data.program_excerpt}`;
    }
    result.textContent = body;
    return;
  }
  result.className = 'kata-result show ' + (data.passed ? 'passed' : 'failed');
  const summary = data.passed
    ? `✓ All ${data.total} sample test${data.total === 1 ? '' : 's'} passed in ${elapsed}ms`
    : `✕ ${data.results.filter(r => !r.passed).length}/${data.total} sample tests failed (${elapsed}ms)`;
  const items = (data.results || []).map(r => `
    <div class="kata-test-result ${r.passed ? 'pass' : 'fail'}">
      ${r.passed ? '✓' : '✕'} <code>${escapeHtml(r.call)}</code>${
      r.passed ? '' :
        `\n    expected: <code>${escapeHtml(r.expected)}</code>\n    got:      <code>${escapeHtml(r.actual)}</code>`
    }
    </div>`).join('');
  result.innerHTML = `<div>${summary}</div><div class="kata-result-tests">${items}</div>`;
}

function renderSubmitResult(data, elapsed, result) {
  if (data.passed) {
    result.className = 'kata-result show passed';
    result.textContent = `✓ Accepted — all ${data.total} hidden tests passed (${elapsed}ms)`;
    // Mark solved + unlock solution tab
    const passedKey = `forge.katas.${currentKata.lang}.passed`;
    const passed = JSON.parse(localStorage.getItem(passedKey) || '[]');
    if (!passed.includes(currentKata.kata.id)) {
      passed.push(currentKata.kata.id);
      localStorage.setItem(passedKey, JSON.stringify(passed));
    }
    $('#kata-solution-locked').hidden = true;
    $('#kata-solution-revealed').hidden = false;
    $('#kata-reference-pre').textContent = currentKata.kata.reference_solution || '';
    toast(`${currentKata.kata.title}: solved!`, 'success', 3000);
    // Refresh list to show ✓
    if (currentPack) renderKataLibrary();
  } else if (data.stage === 'compare' && data.test_index != null) {
    result.className = 'kata-result show failed';
    result.textContent =
      `✕ Wrong answer (test ${data.test_index + 1} of ${data.total}, ${elapsed}ms)\n` +
      `  call:     ${data.call}\n` +
      `  expected: ${data.expected}\n` +
      `  got:      ${data.actual}\n\n` +
      `Tests beyond #${data.test_index + 1} are hidden until you fix this one.`;
  } else if (data.stage === 'no_tests') {
    result.className = 'kata-result show';
    result.textContent = `⚠ ${data.stderr}`;
  } else if (data.stage === 'preflight') {
    // Friendly user error: malformed code caught BEFORE the compiler ran.
    // Stderr is already a human-readable explanation from preflight_check.
    result.className = 'kata-result show failed';
    result.textContent = `⚠ Your code doesn't look right yet\n\n${data.stderr || ''}`;
  } else if (data.stage === 'compile') {
    result.className = 'kata-result show failed';
    let body = `✕ Compilation error\n${data.stderr || ''}`;
    if (data.program_excerpt) {
      body += `\n\n--- The actual program that was compiled (your code + auto-prepended helpers + test prints) ---\n${data.program_excerpt}`;
    }
    result.textContent = body;
  } else if (data.stage === 'run') {
    result.className = 'kata-result show failed';
    let body = `✕ Runtime error\n${data.stderr || ''}`;
    if (data.program_excerpt) {
      body += `\n\n--- The actual program that was run ---\n${data.program_excerpt}`;
    }
    result.textContent = body;
  } else {
    result.className = 'kata-result show failed';
    result.textContent = `✕ ${data.stage}: ${data.stderr || 'unknown error'}`;
  }
}

function renderKataSubmissions(lang, kataId) {
  const subKey = `forge.katas.${lang}.${kataId}.subs`;
  const subs = JSON.parse(localStorage.getItem(subKey) || '[]');
  const box = $('#kata-submissions');
  if (subs.length === 0) {
    box.innerHTML = '<p class="muted small">No attempts yet. Click <strong>Run</strong> or <strong>Submit</strong> to start.</p>';
    return;
  }
  box.innerHTML = subs.map(s => `
    <div class="kata-submission ${s.passed ? 'passed' : 'failed'}">
      <span>${s.passed ? '✓' : '✕'} ${s.mode === 'run' ? 'Run' : 'Submit'}${s.stage ? ` <span class="muted">(${escapeHtml(s.stage)})</span>` : ''}</span>
      <span class="muted">${new Date(s.when).toLocaleString()} · ${s.elapsed_ms}ms</span>
    </div>`).join('');
}

$('#kata-generate')?.addEventListener('click', async () => {
  const lang = $('#kata-lang').value;
  if (!lang) { toast('Pick a language first', 'warn'); return; }
  const btn = $('#kata-generate');
  btn.disabled = true; btn.textContent = '✨ Generating + validating…';
  toast('Asking the model for a kata pack. The reference solutions get test-run before any kata is shown.', 'info', 4000);
  try {
    const r = await fetch(`/api/katas/${lang}/generate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const data = await r.json();
    if (!r.ok) {
      // 422: katas were generated but ALL failed self-validation. Render the
      // diagnostic in the kata-list pane so the user actually sees what went
      // wrong, not a fading toast.
      if (data.pack && Array.isArray(data.pack.dropped)) {
        renderKataDrops(data.pack);
        toast(`All ${data.pack.dropped.length} katas dropped. See the pane for details.`, 'error', 6000);
      } else {
        renderKataError(data.error || 'Kata generation failed');
        toast(data.error || 'Kata generation failed', 'error', 8000);
      }
      return;
    }
    toast(`Generated ${data.katas.length} kata${data.katas.length === 1 ? '' : 's'}` +
          (data.dropped?.length ? ` (${data.dropped.length} dropped after self-check)` : ''),
          'success', 4000);
    loadKataPack(lang);
  } catch (e) {
    renderKataError(e.message);
    toast('Kata generation failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false; btn.textContent = '✨ Generate (slow)';
  }
});

// Curated packs (LeetCode classics, hand-written, instant — no LLM call).
async function refreshKataPacks() {
  const sel = $('#kata-pack-pick');
  if (!sel) return;
  try {
    const r = await fetch('/api/kata-packs');
    if (!r.ok) {
      sel.innerHTML = '<option value="">(unavailable)</option>';
      return;
    }
    const { packs } = await r.json();
    sel.innerHTML = '';
    if (!packs || packs.length === 0) {
      sel.innerHTML = '<option value="">(none available)</option>';
      return;
    }
    for (const p of packs) {
      const o = document.createElement('option');
      o.value = p.key;
      o.textContent = `${p.title} — ${p.kata_count} katas (${p.syntax_family})`;
      o.title = p.description;
      sel.append(o);
    }
    // Auto-select the first pack so the user doesn't have to click twice.
    if (sel.options.length > 0) sel.selectedIndex = 0;
  } catch (e) {
    sel.innerHTML = '<option value="">(unavailable)</option>';
  }
}

// --- Reload pack: re-translate the current pack with `?force=true`,
// invalidating the on-disk katas.json. Useful when the user upgraded
// Forge and the stored references no longer parse against the new
// parser/codegen (e.g. lisplang's grammar changed). One-click recovery
// without having to delete a file by hand.
$('#kata-reload-pack')?.addEventListener('click', async () => {
  const lang = $('#kata-lang').value;
  const pack = $('#kata-pack-pick').value;
  if (!lang) { toast('Pick a language first', 'warn'); return; }
  if (!pack) { toast('Pick a pack first (the one you previously loaded)', 'warn'); return; }
  const btn = $('#kata-reload-pack');
  btn.disabled = true; btn.textContent = '🔄 Reloading…';
  renderKataLoading(lang, /*translating=*/false);
  try {
    const r = await fetch(`/api/katas/${lang}/load-pack/${pack}?force=true`, { method: 'POST' });
    const data = await r.json();
    if (!r.ok) {
      renderKataError(data.error || 'Reload failed');
      toast(data.error || 'Reload failed', 'error', 6000);
      return;
    }
    const dropped = data.dropped?.length || 0;
    toast(`Pack re-translated: ${data.katas.length} katas${dropped ? `, ${dropped} dropped` : ''}`,
          dropped ? 'warn' : 'success', 4000);
    loadKataPack(lang);
  } catch (e) {
    toast('Reload failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false; btn.textContent = '🔄 Reload';
  }
});

$('#kata-load-pack')?.addEventListener('click', async () => {
  const lang = $('#kata-lang').value;
  const pack = $('#kata-pack-pick').value;
  if (!lang) { toast('Pick a language first', 'warn'); return; }
  if (!pack) { toast('Pick a curated pack first', 'warn'); return; }
  const btn = $('#kata-load-pack');
  btn.disabled = true;
  btn.textContent = '📚 Loading…';

  // Render an honest in-progress panel so the user knows what's happening.
  // After ~2.5s with no response, we assume LLM translation is running and
  // upgrade the message with a longer-wait warning.
  renderKataLoading(lang, /*translating=*/false);
  let stillRunning = true;
  const slowTimer = setTimeout(() => {
    if (stillRunning) {
      btn.textContent = '📚 Translating…';
      renderKataLoading(lang, /*translating=*/true);
      toast('Direct load failed. Asking the model to translate the references to your language\'s dialect (30-60s).', 'info', 6000);
    }
  }, 2500);

  try {
    const r = await fetch(`/api/katas/${lang}/load-pack/${pack}`, { method: 'POST' });
    const data = await r.json();
    if (!r.ok) {
      if (data.pack && Array.isArray(data.pack.dropped)) {
        renderKataDrops(data.pack);
        toast(`All ${data.pack.dropped.length} katas dropped on this language. See the pane for details.`, 'error', 6000);
      } else {
        renderKataError(data.error || 'Pack load failed');
        toast(data.error || 'Pack load failed', 'error', 8000);
      }
      return;
    }
    const dropped = data.dropped?.length || 0;
    const translated = (data.source || '').startsWith('translated:');
    const cached = data.cached === true;
    let msg = `Loaded ${data.katas.length} katas`;
    if (cached) msg += ' (cached)';
    else if (translated) msg += ' (LLM-translated)';
    if (dropped) msg += ` (${dropped} dropped, couldn\'t adapt)`;
    toast(msg, 'success', 4000);
    loadKataPack(lang);
  } catch (e) {
    renderKataError(e.message);
    toast('Pack load failed: ' + e.message, 'error');
  } finally {
    stillRunning = false;
    clearTimeout(slowTimer);
    btn.disabled = false;
    btn.textContent = '📚 Load pack';
  }
});

function renderKataLoading(lang, translating) {
  const list = $('#kata-list');
  if (!list) return;
  $('#kata-count').textContent = translating ? 'translating…' : 'loading…';
  $('#kata-detail-empty').style.display = '';
  $('#kata-detail').hidden = true;
  if (translating) {
    list.innerHTML = `
      <div class="kata-error" style="border-color:var(--accent)">
        <strong>Translating to <code>${escapeHtml(lang)}</code>'s dialect…</strong>
        <p class="muted" style="margin:8px 0 0">Your language has a phrasebook, feature ban, or non-standard syntax. The model is rewriting each kata's reference solution. This takes 30-60 seconds for the full pack.</p>
      </div>`;
  } else {
    list.innerHTML = `
      <p class="muted" style="font-size:12px;padding:12px">
        Loading and validating against <code>${escapeHtml(lang)}</code>…
      </p>`;
  }
}

function renderKataError(msg) {
  const list = $('#kata-list');
  if (!list) return;
  list.innerHTML = `<div class="kata-error"><strong>Generation failed</strong><pre class="code">${escapeHtml(msg)}</pre></div>`;
  $('#kata-count').textContent = '';
  $('#kata-detail-empty').style.display = '';
  $('#kata-detail').hidden = true;
}

function renderKataIncompatible(msg) {
  /** Pre-flight 400: pack is incompatible with the language. Show the
   *  reason prominently with a clear "click Generate" next step. */
  const list = $('#kata-list');
  if (!list) return;
  $('#kata-count').textContent = '';
  $('#kata-detail-empty').style.display = '';
  $('#kata-detail').hidden = true;
  list.innerHTML = `
    <div class="kata-error">
      <strong>This pack isn't compatible with this language.</strong>
      <p style="margin:8px 0 6px">${escapeHtml(msg)}</p>
      <p style="margin:6px 0 0">Switch the language dropdown to a reference target (<strong>toylang</strong> for c_like, <strong>lisplang</strong> for s_expression), or click <strong>✨ Generate (slow)</strong> to make a fresh pack for this language.</p>
    </div>`;
}

function renderKataDrops(pack) {
  /** All katas dropped during self-validation. Show actionable guidance
   *  AND the per-kata reason so the user can decide what to do next. */
  const list = $('#kata-list');
  if (!list) return;
  const lang = $('#kata-lang').value;
  const sourceCurated = pack.source && pack.source.startsWith('curated:');
  $('#kata-count').textContent = `0 of ${pack.dropped.length} survived`;
  $('#kata-detail-empty').style.display = '';
  $('#kata-detail').hidden = true;

  // Heuristic: detect WHY they all dropped to give one-line guidance.
  const firstReason = pack.dropped[0]?.reason || '';
  let cause = '';
  let action = '';
  if (/UnexpectedCharacters|UnexpectedToken|lark|UnexpectedInput/i.test(firstReason)) {
    cause = `<code>${escapeHtml(lang)}</code>'s parser doesn't accept the references' standard <code>var/func</code> syntax. The language probably has a natural-language phrasebook or non-standard keyword spelling.`;
    action = sourceCurated
      ? `Try a reference target (<strong>toylang</strong> for c_like, <strong>lisplang</strong> for s_expression), or click <strong>✨ Generate</strong> to have the LLM write a fresh pack in <code>${escapeHtml(lang)}</code>'s actual dialect.`
      : `Click <strong>✨ Generate</strong> again so the model can take another pass.`;
  } else if (/no_mutation|cannot reassign|immutable|cannot mutate/i.test(firstReason)) {
    cause = `<code>${escapeHtml(lang)}</code> bans variable reassignment. The references all loop with <code>i = i + 1</code>, which this language doesn't allow.`;
    action = `Try a language without the <code>no_mutation</code> ban (<strong>toylang</strong> or <strong>lisplang</strong>), or click <strong>✨ Generate</strong> for a recursion-only pack tailored to this language.`;
  } else if (/no_loops|while.*not allowed|loop.*ban/i.test(firstReason)) {
    cause = `<code>${escapeHtml(lang)}</code> bans loops. The references use <code>while</code>.`;
    action = `Try a language with loops, or click <strong>✨ Generate</strong> for a recursion-based pack.`;
  } else if (/expected.*output.*lines.*got/i.test(firstReason)) {
    cause = `The references compile but their stdout doesn't match the expected outputs. <code>${escapeHtml(lang)}</code>'s <code>print</code> formatter probably differs from the reference's (e.g. lists print as <code>(1 2 3)</code> in lisplang vs <code>[1, 2, 3]</code> in toylang).`;
    action = `Click <strong>✨ Generate</strong> to make a pack whose expected outputs match this language's actual print formatter.`;
  } else {
    cause = `The pack's reference solutions don't compile or run correctly on <code>${escapeHtml(lang)}</code>.`;
    action = `Try a reference target first (<strong>toylang</strong> for c_like, <strong>lisplang</strong> for s_expression), or click <strong>✨ Generate</strong> to make a pack tailored to <code>${escapeHtml(lang)}</code>.`;
  }

  const rows = pack.dropped.map(d => `
    <details class="kata-drop">
      <summary>✕ ${escapeHtml(d.id || 'unknown')}</summary>
      <pre class="code">${escapeHtml(d.reason)}</pre>
    </details>
  `).join('');

  list.innerHTML = `
    <div class="kata-error">
      <strong>All ${pack.dropped.length} katas dropped on <code>${escapeHtml(lang)}</code>.</strong>
      <p style="margin:8px 0 6px"><strong>Why:</strong> ${cause}</p>
      <p style="margin:6px 0 14px"><strong>Try this:</strong> ${action}</p>
      <details style="margin-bottom:8px"><summary style="cursor:pointer;font-size:12px;color:var(--muted)">Per-kata error details (${pack.dropped.length})</summary>
        <div style="margin-top:8px">${rows}</div>
      </details>
    </div>`;
}

$('#kata-ask')?.addEventListener('click', () => {
  if (!currentKata) return;
  // Switch to playground with the kata already loaded into the chat panel.
  switchView('playground');
  setTimeout(() => {
    $('#play-lang').value = currentKata.lang;
    $('#play-lang').dispatchEvent(new Event('change'));
    setPlaySource($('#kata-editor').value);
    $('#play-chat').open = true;
    $('#pair-input').focus();
    // Tag the next chat as kata-aware:
    pairContext = { kata: currentKata.kata, lang: currentKata.lang };
    toast(`Pair programmer is now hint-aware of "${currentKata.kata.title}"`, 'info', 3000);
  }, 100);
});

// ============================================================
// AI pair programmer (chat sidebar in the Playground)
// ============================================================
let pairHistory = [];
let pairContext = null;     // {kata, lang} when invoked from kata "Ask"

function chatStorageKey(lang) { return `forge.chat.${lang}`; }

function loadChatHistory(lang) {
  try {
    pairHistory = JSON.parse(localStorage.getItem(chatStorageKey(lang)) || '[]');
  } catch { pairHistory = []; }
  renderPairHistory();
}
function saveChatHistory(lang) {
  localStorage.setItem(chatStorageKey(lang), JSON.stringify(pairHistory.slice(-40)));
}

function renderPairHistory() {
  const root = $('#pair-history');
  if (!root) return;
  root.innerHTML = '';
  for (const msg of pairHistory) {
    const div = document.createElement('div');
    div.className = 'pair-msg ' + msg.role;
    if (msg.role === 'assistant' && msg.blocks) {
      div.innerHTML = renderAssistantMessage(msg.content, msg.blocks);
    } else {
      div.textContent = msg.content;
    }
    root.append(div);
  }
  root.scrollTop = root.scrollHeight;
}

function renderAssistantMessage(text, blocks) {
  // Replace each fenced block in the text with a styled <pre> + actions.
  let html = escapeHtml(text);
  blocks.forEach((b, i) => {
    const fenceRegex = new RegExp('```' + (b.label ? escapeRegex(b.label) : '\\w*') + '\\n' +
      escapeRegex(b.body) + '```', 's');
    const klass = b.ok ? 'code' : 'code pair-block-bad';
    const title = b.ok ? '' : `<small class="muted">parser said: ${escapeHtml(b.error || '')}</small>`;
    const actions = `<div class="pair-block-actions"><button data-block="${i}" class="pair-run">▶ Run this</button><button data-block="${i}" class="pair-copy">copy</button></div>`;
    const replacement = `<pre class="${klass}">${escapeHtml(b.body)}</pre>${title}${actions}`;
    html = html.replace(fenceRegex, replacement);
  });
  return html.replace(/\n/g, '<br>');
}

function escapeRegex(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

$('#pair-form')?.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const input = $('#pair-input');
  const msg = input.value.trim();
  if (!msg) return;
  const lang = $('#play-lang').value;
  if (!lang) { toast('Pick a language first', 'warn'); return; }

  pairHistory.push({ role: 'user', content: msg });
  renderPairHistory();
  input.value = '';

  const mode = $('#pair-hint-mode').checked ? 'hint' : 'solution';
  $('#play-chat-mode').textContent = `${mode} mode`;

  const body = {
    message: msg,
    history: pairHistory.slice(0, -1),    // server appends user msg itself
    mode,
  };
  if (pairContext && pairContext.lang === lang) {
    body.kata_id = pairContext.kata.id;
    body.current_code = $('#kata-editor')?.value || getPlaySource();
  }

  const placeholder = { role: 'assistant', content: 'Thinking…', blocks: [] };
  pairHistory.push(placeholder);
  renderPairHistory();

  try {
    const r = await fetch(`/api/chat/${lang}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (!r.ok) {
      placeholder.content = data.error || 'chat failed';
    } else {
      placeholder.content = data.text;
      placeholder.blocks = data.blocks || [];
    }
    renderPairHistory();
    saveChatHistory(lang);
  } catch (e) {
    placeholder.content = 'chat failed: ' + e.message;
    renderPairHistory();
  }
});

// "Run this" + "copy" buttons inside assistant messages
document.addEventListener('click', (ev) => {
  if (ev.target.classList.contains('pair-run')) {
    const i = +ev.target.dataset.block;
    const last = [...pairHistory].reverse().find(m => m.role === 'assistant');
    if (!last || !last.blocks?.[i]) return;
    setPlaySource(last.blocks[i].body);
    $('#play-chat').open = false;
    $('#play-run').click();
  }
  if (ev.target.classList.contains('pair-copy')) {
    const i = +ev.target.dataset.block;
    const last = [...pairHistory].reverse().find(m => m.role === 'assistant');
    if (!last || !last.blocks?.[i]) return;
    navigator.clipboard.writeText(last.blocks[i].body)
      .then(() => toast('Copied', 'success', 1500), () => {});
  }
});

$('#pair-hint-mode')?.addEventListener('change', () => {
  const mode = $('#pair-hint-mode').checked ? 'hint' : 'solution';
  $('#play-chat-mode').textContent = `${mode} mode`;
});

// Show the chat panel + load history when language changes
const _originalPlayLangChange = $('#play-lang')?.onchange;
$('#play-lang')?.addEventListener('change', () => {
  const lang = $('#play-lang').value;
  if (!lang) return;
  $('#play-chat').hidden = false;
  loadChatHistory(lang);
});

// ============================================================
// First load
// ============================================================
refreshProviders();
refreshPlaygroundLanguages();
refreshLibrary();
refreshFooter();
refreshSamples();
refreshSpeculativePickers();
setInterval(refreshFooter, 10000);

// ============================================================
// Surprise me, vibe → language
// ============================================================
$('#surprise-form')?.addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const name = $('#surprise-name').value.trim();
  const vibe = $('#surprise-vibe').value.trim();
  if (!name || !vibe) return;
  const checked = $('input[name="provider"]:checked');
  const provider = checked ? checked.value : null;
  const submit = ev.target.querySelector('button[type=submit]');
  submit.disabled = true;
  toast(`Asking Claude to imagine "${vibe}"…`, 'info');
  try {
    const r = await fetch('/api/surprise', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, vibe, provider }),
    });
    const data = await r.json();
    if (!r.ok) {
      toast(data.error || 'Surprise failed', 'error');
      submit.disabled = false;
      return;
    }
    // Show what was picked
    $('#surprise-picks').hidden = false;
    $('#surprise-picks-pre').textContent = JSON.stringify(data.picks, null, 2);
    startProgress(name, data.job_id);
  } catch (e) {
    toast('Surprise failed: ' + e.message, 'error');
    submit.disabled = false;
  }
});


// ---------------------------------------------------------------------------
// Phase 3 follow-up Item 5: ?lang=<slot_id>&view=playground|kata deep-link.
// The catalog curation UI's "Launch REPL" / "Open kata workspace" buttons
// open this page with those query params; we read them on boot and
// auto-select the language + switch to the right view. No deep-link =
// the GUI boots into its default "Create" view as before.
// ---------------------------------------------------------------------------

(function handleDeepLink() {
  const params = new URLSearchParams(location.search);
  const lang = params.get('lang');
  const view = params.get('view');
  if (!lang) return;

  // Defer slightly so the rest of the app's DOMContentLoaded
  // initialization runs first (the language list + tab switching
  // both depend on bootstrap state being in place).
  document.addEventListener('DOMContentLoaded', () => {
    setTimeout(async () => {
      try {
        if (view === 'kata' || view === 'katas') {
          // Switch to the kata workspace tab and select the language.
          // The tab's data-view is 'katas' (plural); accept either spelling.
          if (typeof switchView === 'function') switchView('katas');
          const sel = document.querySelector('#kata-lang');
          if (sel) {
            // Wait for the dropdown to be populated by the existing
            // bootstrap (refreshKataLanguages or similar populates it
            // asynchronously after /api/languages resolves).
            await waitForOption(sel, lang, 5000);
            sel.value = lang;
            sel.dispatchEvent(new Event('change'));
          }
        } else {
          // Default: open in playground.
          if (typeof openInPlayground === 'function') {
            await openInPlayground(lang);
          }
        }
      } catch (e) {
        console.warn('deep-link auto-open failed:', e);
      }
    }, 200);
  });
})();


function waitForOption(selectEl, value, timeoutMs) {
  /* Resolve when the given <option value> appears under the select
     (or after timeoutMs). Used by the deep-link handler since the
     language dropdown is populated async. */
  return new Promise(resolve => {
    const start = Date.now();
    function check() {
      if ([...selectEl.options].some(o => o.value === value)) return resolve();
      if (Date.now() - start > timeoutMs) return resolve();
      setTimeout(check, 100);
    }
    check();
  });
}
