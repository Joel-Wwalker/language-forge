// ----------------------------------------------------------------------
// Language Forge, frontend
// ----------------------------------------------------------------------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

let currentLang = null;
let providers = { available: { api: false, claude_cli: false }, default: 'api' };

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
async function refreshLibrary() {
  const r = await fetch('/api/languages');
  const { languages } = await r.json();
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
    const card = document.createElement('div');
    card.className = 'lang-card';
    const opts = lang.options || {};
    const tags = ['syntax', 'typing', 'memory']
      .map(k => opts[k] ? `<span class="tag">${opts[k]}</span>` : '')
      .filter(Boolean).join('');
    card.innerHTML = `
      <div class="lc-head">
        <div class="lc-name">${lang.name}<span class="lc-ext">${lang.ext}</span></div>
        <span class="lc-status status-pill checking" data-status>checking…</span>
      </div>
      <div class="lc-tags">${tags || '<span class="muted">no tags</span>'}</div>
      <div class="lc-actions lc-primary">
        <button class="primary lc-open" title="Open in the playground">Open</button>
        <button class="ghost lc-repl" title="In-browser REPL (Pyodide). No install.">▶ Browser</button>
        <button class="ghost lc-verify" title="Run all canonical tests">Verify</button>
      </div>
      <div class="lc-actions lc-secondary">
        <button class="link lc-spec" title="View the resolved spec">Spec</button>
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
    // Best-effort initial status check (cheap, runs the verifier locally)
    silentVerify(lang.name, card);
    list.append(card);
  }
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
  const r = await fetch('/api/languages');
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
  ed.setOption('mode', syntax === 'python_like' ? 'python' : { name: 'clike', keywords: {} });
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
    const r = await fetch('/api/languages');
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
  const r = await fetch('/api/languages');
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
    const acceptance = kata.acceptance_rate != null
      ? ` · <span title="Indicative acceptance rate">${(kata.acceptance_rate * 100).toFixed(0)}%</span>`
      : '';
    const tagsHtml = (kata.tags || []).slice(0, 3).map(t =>
      `<span class="kata-tag">${escapeHtml(t)}</span>`).join('');
    row.innerHTML = `
      <div class="kata-row-title">${escapeHtml(kata.title)}${stubBadge}
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
  toast('Solution revealed. Try writing yours first next time!', 'info', 3000);
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
    result.textContent = `✕ ${data.stage}: ${data.stderr || ''}`;
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
  } else if (data.stage === 'compile') {
    result.className = 'kata-result show failed';
    result.textContent = `✕ Compilation error\n${data.stderr || ''}`;
  } else if (data.stage === 'run') {
    result.className = 'kata-result show failed';
    result.textContent = `✕ Runtime error\n${data.stderr || ''}`;
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
      <p style="margin:6px 0 0">Switch the language dropdown to a vanilla c_like language (e.g. <strong>toylang</strong>), or click <strong>✨ Generate (slow)</strong> to make a fresh pack for this language.</p>
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
      ? `Try a vanilla c_like language (<strong>toylang</strong> works), or click <strong>✨ Generate</strong> to have the LLM write a fresh pack in <code>${escapeHtml(lang)}</code>'s actual dialect.`
      : `Click <strong>✨ Generate</strong> again so the model can take another pass.`;
  } else if (/no_mutation|cannot reassign|immutable|cannot mutate/i.test(firstReason)) {
    cause = `<code>${escapeHtml(lang)}</code> bans variable reassignment. The references all loop with <code>i = i + 1</code>, which this language doesn't allow.`;
    action = `Try a c_like language without the <code>no_mutation</code> ban (<strong>toylang</strong> works), or click <strong>✨ Generate</strong> for a recursion-only pack tailored to this language.`;
  } else if (/no_loops|while.*not allowed|loop.*ban/i.test(firstReason)) {
    cause = `<code>${escapeHtml(lang)}</code> bans loops. The references use <code>while</code>.`;
    action = `Try a c_like language with loops, or click <strong>✨ Generate</strong> for a recursion-based pack.`;
  } else if (/expected.*output.*lines.*got/i.test(firstReason)) {
    cause = `The references compile but their stdout doesn't match the expected outputs. <code>${escapeHtml(lang)}</code>'s <code>print</code> formatter probably differs from toylang's (e.g. lists print as <code>(1 2 3)</code> instead of <code>[1, 2, 3]</code>).`;
    action = `Click <strong>✨ Generate</strong> to make a pack whose expected outputs match this language's actual print formatter.`;
  } else {
    cause = `The pack's reference solutions don't compile or run correctly on <code>${escapeHtml(lang)}</code>.`;
    action = `Try <strong>toylang</strong> first (the reference c_like target), or click <strong>✨ Generate</strong> to make a pack tailored to <code>${escapeHtml(lang)}</code>.`;
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
