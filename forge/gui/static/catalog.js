/* Phase 3 — Catalog Curation UI frontend.
 *
 * Single-file vanilla JS module (no framework — match the existing
 * Forge GUI patterns from app.js). Manages two views (list, detail),
 * filter state in the URL, keyboard navigation, and the approve /
 * reject / annotate workflow.
 *
 * # State
 *
 *   STATE.allFacets       - { families, statuses, personas, ... } from /api/catalog/facets
 *   STATE.filters         - current filter values (mirrored to URL)
 *   STATE.items           - current filtered list of summaries
 *   STATE.selectedIndex   - keyboard cursor position in the list
 *   STATE.detailSlotId    - currently-open slot_id (or null = list view)
 *   STATE.bulkSelection   - Set<slot_id> for bulk operations (Stage D)
 *   STATE.tierSuggestions - autocomplete tags/tiers from /api/catalog/tags
 *
 * # Loop
 *
 *   1. boot() loads facets + initial list
 *   2. user filter change -> refreshList()
 *   3. user clicks row -> openDetail(slot_id)
 *   4. user presses A/R/P -> apply status update -> auto-advance to next
 *   5. when no next item, return to list view
 */
"use strict";

const STATE = {
  allFacets: null,
  filters: {
    search: "",
    family: new Set(),
    status: new Set(["pending_review"]),
    persona: "",
    era: "",
    theme: "",
    phrasebook: "",
    tier: "",
    tag: "",
    min_distinctiveness: 0,
    sort_by: "slot_id",
    sort_dir: "desc",
  },
  items: [],
  selectedIndex: 0,
  detailSlotId: null,
  detailIndex: 0,
  bulkSelection: new Set(),
  tagSuggestions: [],
};


// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", boot);

async function boot() {
  // Decode filters from URL hash (so back-button works).
  parseHash();
  await loadFacets();
  buildFilterUI();
  await refreshProgress();
  await refreshList();
  bindKeyboard();
  bindFilterListeners();
  bindDetailListeners();
  bindBulkListeners();
  // If the URL hash has #slot/<id>, open that detail view.
  if (location.hash.startsWith("#slot/")) {
    const slot = location.hash.slice("#slot/".length);
    openDetail(slot, /*pushState=*/false);
  }
  window.addEventListener("popstate", handlePopState);
}


// ---------------------------------------------------------------------------
// Facets + filter UI
// ---------------------------------------------------------------------------

async function loadFacets() {
  const r = await fetch("/api/catalog/facets");
  STATE.allFacets = await r.json();
}

function buildFilterUI() {
  const f = STATE.allFacets;
  // Family checkboxes.
  const famDiv = document.getElementById("filter-family");
  famDiv.innerHTML = "";
  for (const fam of f.families || []) {
    const id = `fam-${fam}`;
    famDiv.insertAdjacentHTML("beforeend",
      `<label><input type="checkbox" value="${escAttr(fam)}" ${STATE.filters.family.has(fam) ? "checked" : ""}> ${escHtml(fam)}</label>`
    );
  }
  fillSelect("filter-persona", f.personas || []);
  fillSelect("filter-era", f.eras || []);
  fillSelect("filter-theme", f.themes || []);
  fillSelect("filter-phrasebook", f.phrasebooks || []);

  // Restore filter form state from STATE.filters.
  document.getElementById("filter-search").value = STATE.filters.search;
  for (const cb of document.querySelectorAll("#filter-status input")) {
    cb.checked = STATE.filters.status.has(cb.value);
  }
  document.getElementById("filter-persona").value = STATE.filters.persona || "";
  document.getElementById("filter-era").value = STATE.filters.era || "";
  document.getElementById("filter-theme").value = STATE.filters.theme || "";
  document.getElementById("filter-phrasebook").value = STATE.filters.phrasebook || "";
  document.getElementById("filter-min-distinctiveness").value = STATE.filters.min_distinctiveness;
  document.getElementById("min-d-display").textContent =
    STATE.filters.min_distinctiveness.toFixed(2);
  document.getElementById("filter-sort-by").value = STATE.filters.sort_by;
  document.getElementById("filter-sort-dir").value = STATE.filters.sort_dir;
}

function fillSelect(id, values) {
  const sel = document.getElementById(id);
  sel.innerHTML = '<option value="">— any —</option>';
  for (const v of values) {
    const opt = document.createElement("option");
    opt.value = v; opt.textContent = v;
    sel.appendChild(opt);
  }
}


// ---------------------------------------------------------------------------
// List view
// ---------------------------------------------------------------------------

async function refreshList() {
  const params = filterParams();
  const r = await fetch(`/api/catalog/list?${params}`);
  const data = await r.json();
  STATE.items = data.items || [];
  if (STATE.selectedIndex >= STATE.items.length) {
    STATE.selectedIndex = Math.max(0, STATE.items.length - 1);
  }
  renderList(data);
  updateHash();
}

function filterParams() {
  const f = STATE.filters;
  const params = new URLSearchParams();
  if (f.search) params.set("search", f.search);
  if (f.persona) params.set("persona", f.persona);
  if (f.era) params.set("era", f.era);
  if (f.theme) params.set("theme", f.theme);
  if (f.phrasebook) params.set("phrasebook", f.phrasebook);
  if (f.tier) params.set("tier", f.tier);
  if (f.tag) params.set("tag", f.tag);
  if (f.min_distinctiveness > 0)
    params.set("min_distinctiveness", String(f.min_distinctiveness));
  params.set("sort_by", f.sort_by);
  params.set("sort_dir", f.sort_dir);
  // family + status: backend only takes one of each; if multiple
  // selected we filter post-fetch on the client for the union.
  if (f.family.size === 1) params.set("family", [...f.family][0]);
  if (f.status.size === 1) params.set("status", [...f.status][0]);
  return params.toString();
}

function renderList(data) {
  const list = document.getElementById("catalog-list");
  // Apply multi-select filters client-side (for family + status).
  let items = data.items || [];
  if (STATE.filters.family.size > 1) {
    items = items.filter(i => STATE.filters.family.has(i.family));
  }
  if (STATE.filters.status.size > 1) {
    items = items.filter(i => STATE.filters.status.has(i.status));
  }
  if (STATE.filters.status.size === 0) items = [];
  if (STATE.filters.family.size === 0 && STATE.allFacets.families.length > 0) {
    // Empty family selection means show all families (since no checkboxes).
    // (Default has all families; explicit none = none.)
  }
  STATE.items = items;
  document.getElementById("list-count").textContent =
    `${items.length} of ${data.total_unfiltered}`;
  if (items.length === 0) {
    list.innerHTML = '<div class="list-empty">no candidates match the current filters</div>';
    return;
  }
  list.innerHTML = "";
  items.forEach((item, idx) => {
    const sel = idx === STATE.selectedIndex ? "selected" : "";
    const dist = item.distinctiveness != null
      ? item.distinctiveness.toFixed(2)
      : "—";
    const coh = item.coherence != null ? item.coherence.toFixed(2) : "—";
    const comp = item.completeness != null ? item.completeness.toFixed(2) : "—";
    const distClass = item.distinctiveness >= 0.6 ? "high" : "";
    const cust = compactCustomization(item);
    const row = document.createElement("div");
    row.className = `catalog-row ${sel}`;
    row.dataset.slotId = item.slot_id;
    row.dataset.index = String(idx);
    row.innerHTML = `
      <input type="checkbox" class="row-checkbox" data-slot-id="${escAttr(item.slot_id)}"
        ${STATE.bulkSelection.has(item.slot_id) ? "checked" : ""}>
      <span class="row-slot">${escHtml(item.slot_id)}</span>
      <span class="row-family">${escHtml(item.family)}</span>
      <span class="row-score ${distClass}">d ${dist}</span>
      <span class="row-score">c ${coh}</span>
      <span class="row-score">f ${comp}</span>
      <span class="row-cust">${escHtml(cust)}</span>
      <span class="row-status ${escAttr(item.status)}">${escHtml(item.status.replace("_", " "))}</span>
    `;
    row.querySelector(".row-checkbox").addEventListener("click", e => {
      e.stopPropagation();
      toggleBulkSelection(item.slot_id, e.target.checked);
    });
    // Phase 3 follow-up Item 4: a click on a row syncs the keyboard
    // cursor (STATE.selectedIndex) so subsequent J/K navigation
    // continues from where the click landed, not from the previous
    // arrow-key cursor position.
    row.addEventListener("click", () => {
      STATE.selectedIndex = idx;
      openDetailByIndex(idx);
    });
    list.appendChild(row);
  });
  // Scroll selected row into view.
  const selRow = list.querySelector(".catalog-row.selected");
  if (selRow) selRow.scrollIntoView({ block: "nearest" });
}

function compactCustomization(item) {
  const bits = [];
  if (item.persona) bits.push(`persona:${item.persona}`);
  if (item.era) bits.push(`era:${item.era}`);
  if (item.theme) bits.push(`theme:${item.theme}`);
  if (item.phrasebook) bits.push(`phrasebook:${item.phrasebook}`);
  if (item.feature_bans && item.feature_bans.length)
    bits.push(`bans:[${item.feature_bans.join(",")}]`);
  if (item.tier) bits.push(`tier:${item.tier}`);
  return bits.length ? bits.join(" · ") : "(no customization)";
}


// ---------------------------------------------------------------------------
// Filter event listeners
// ---------------------------------------------------------------------------

function bindFilterListeners() {
  document.getElementById("filter-search").addEventListener("input", debounce(e => {
    STATE.filters.search = e.target.value.trim();
    refreshList();
  }, 200));
  for (const cb of document.querySelectorAll("#filter-status input")) {
    cb.addEventListener("change", () => {
      STATE.filters.status = new Set(
        [...document.querySelectorAll("#filter-status input")]
          .filter(c => c.checked).map(c => c.value)
      );
      refreshList();
    });
  }
  document.getElementById("filter-family").addEventListener("change", () => {
    STATE.filters.family = new Set(
      [...document.querySelectorAll("#filter-family input")]
        .filter(c => c.checked).map(c => c.value)
    );
    refreshList();
  });
  for (const id of ["filter-persona", "filter-era", "filter-theme", "filter-phrasebook"]) {
    document.getElementById(id).addEventListener("change", e => {
      const key = id.replace("filter-", "");
      STATE.filters[key] = e.target.value;
      refreshList();
    });
  }
  document.getElementById("filter-min-distinctiveness").addEventListener("input", e => {
    STATE.filters.min_distinctiveness = parseFloat(e.target.value);
    document.getElementById("min-d-display").textContent =
      STATE.filters.min_distinctiveness.toFixed(2);
    refreshList();
  });
  document.getElementById("filter-sort-by").addEventListener("change", e => {
    STATE.filters.sort_by = e.target.value;
    refreshList();
  });
  document.getElementById("filter-sort-dir").addEventListener("change", e => {
    STATE.filters.sort_dir = e.target.value;
    refreshList();
  });
  document.getElementById("btn-clear-filters").addEventListener("click", () => {
    STATE.filters = {
      search: "", family: new Set(), status: new Set(["pending_review"]),
      persona: "", era: "", theme: "", phrasebook: "",
      tier: "", tag: "",
      min_distinctiveness: 0, sort_by: "slot_id", sort_dir: "desc",
    };
    buildFilterUI();
    refreshList();
  });
}


// ---------------------------------------------------------------------------
// Detail view
// ---------------------------------------------------------------------------

async function openDetailByIndex(idx) {
  if (idx < 0 || idx >= STATE.items.length) return;
  STATE.detailIndex = idx;
  STATE.selectedIndex = idx;
  await openDetail(STATE.items[idx].slot_id, /*pushState=*/true);
}

async function openDetail(slotId, pushState) {
  STATE.detailSlotId = slotId;
  if (pushState) {
    history.pushState({ slot: slotId }, "", `#slot/${encodeURIComponent(slotId)}`);
  }
  const r = await fetch(`/api/catalog/${encodeURIComponent(slotId)}`);
  if (!r.ok) {
    alert(`error loading ${slotId}: ${r.status}`);
    return;
  }
  const data = await r.json();
  renderDetail(data);
  document.getElementById("list-view").hidden = true;
  document.getElementById("detail-view").hidden = false;
}

function renderDetail(data) {
  document.getElementById("detail-slot-id").textContent = data.slot_id;
  const badge = document.getElementById("detail-status-badge");
  badge.className = `detail-status-badge ${data.status}`;
  badge.textContent = data.status.replace("_", " ");

  // Progress indicator: position in current filtered list
  const progEl = document.getElementById("detail-progress");
  const idx = STATE.items.findIndex(i => i.slot_id === data.slot_id);
  if (idx >= 0) {
    progEl.textContent = `${idx + 1} of ${STATE.items.length}`;
    STATE.detailIndex = idx;
  } else {
    progEl.textContent = "";
  }

  // Summary block
  const sumEl = document.getElementById("detail-summary-block");
  sumEl.innerHTML = "";
  for (const [label, value] of [
    ["family", data.family],
    ["typing", data.typing],
    ["memory", data.memory],
    ["pipeline", data.pipeline_path],
    ["persona", data.persona || "—"],
    ["era", data.era || "—"],
    ["theme", data.theme || "—"],
    ["phrasebook", data.phrasebook || "—"],
    ["bans", (data.feature_bans || []).join(", ") || "—"],
    ["display_name", data.display_name],
  ]) {
    sumEl.insertAdjacentHTML("beforeend",
      `<div class="detail-summary-row"><span class="label">${escHtml(label)}</span><span class="value">${escHtml(value)}</span></div>`);
  }

  // Quality bars
  const qEl = document.getElementById("detail-quality-block");
  qEl.innerHTML = "";
  const qr = data.quality_report || {};
  for (const [label, score] of [
    ["correctness", qr.correctness && qr.correctness.passed ? 1.0 : 0.0],
    ["distinctiveness", (qr.distinctiveness || {}).score],
    ["coherence", (qr.coherence || {}).score],
    ["completeness", (qr.completeness || {}).score],
  ]) {
    const sNum = (score == null) ? 0 : score;
    const sStr = (score == null) ? "—" : sNum.toFixed(2);
    qEl.insertAdjacentHTML("beforeend",
      `<div class="detail-quality-row">
        <span class="label">${escHtml(label)}</span>
        <span class="bar"><span class="bar-fill" style="width:${(sNum*100).toFixed(0)}%"></span></span>
        <span class="value">${escHtml(sStr)}</span>
       </div>`);
  }

  // JSON dumps
  document.getElementById("detail-spec-json").textContent =
    JSON.stringify(data.resolved_spec, null, 2);
  document.getElementById("detail-slot-json").textContent =
    JSON.stringify(data.slot_json, null, 2);

  // Files list
  const filesEl = document.getElementById("detail-files");
  filesEl.innerHTML = "";
  for (const f of data.files || []) {
    const meta = f.line_count != null
      ? (f.type === "dir" ? `${f.line_count} files` : `${f.line_count} lines`)
      : (f.size_bytes != null ? `${f.size_bytes}b` : "");
    filesEl.insertAdjacentHTML("beforeend",
      `<li><span>${escHtml(f.name)}</span><span class="file-meta">${escHtml(meta)}</span></li>`);
  }

  // README + LANGUAGE.md. Phase 3 follow-up: when on-disk README
  // is missing, the backend serves the spec's creative.readme_intro
  // + origin_story as a fallback. Tag the rendering so the curator
  // knows what they're reading.
  const readmeEl = document.getElementById("detail-readme");
  if (data.readme_source === "db_spec") {
    readmeEl.innerHTML =
      '<div class="readme-source-tag">📦 recovered from DB (on-disk README missing)</div>';
    const pre = document.createElement("pre");
    pre.style.margin = "0";
    pre.style.background = "transparent";
    pre.style.border = "none";
    pre.style.padding = "0";
    pre.style.whiteSpace = "pre-wrap";
    pre.textContent = data.readme || "";
    readmeEl.appendChild(pre);
  } else if (data.readme_source === "missing" || !data.readme) {
    readmeEl.innerHTML = '<div class="muted">(README.md missing on disk and not in spec)</div>';
  } else {
    readmeEl.textContent = data.readme;
  }
  document.getElementById("detail-language-md").textContent =
    data.language_md || "(LANGUAGE.md missing)";

  // Phase 3 follow-up Item 1: canonical test results.
  renderCanonicalTests(data);
  // Phase 3 follow-up Item 2: kata pack inline.
  renderKataPack(data);
  // Phase 3 follow-up Item 5: launch-REPL button.
  renderLaunchRepl(data);

  // Notes + tier + tags
  document.getElementById("reviewer-notes").value = data.reviewer_notes || "";
  document.getElementById("detail-tier").value = data.tier || "";
  const tags = data.tags ? (Array.isArray(data.tags) ? data.tags.join(", ") : data.tags) : "";
  document.getElementById("detail-tags").value = tags;

  // Rejection-reason block: shown if status == rejected, otherwise hidden
  // until R is pressed.
  const rrBlock = document.getElementById("rejection-reason-block");
  const rrInput = document.getElementById("rejection-reason");
  rrInput.value = data.rejection_reason || "";
  rrBlock.hidden = data.status !== "rejected";
}


// ---------------------------------------------------------------------------
// Phase 3 follow-up: render functions for canonical tests, kata pack,
// and launch-REPL button (Items 1, 2, 5)
// ---------------------------------------------------------------------------

function renderCanonicalTests(data) {
  // Insert / update a "Canonical tests" section in the spec pane.
  // The aggregate count comes from data.canonical_summary; the
  // per-test source/expected come from data.canonical_tests.
  const target = ensureSection("canonical-tests-block",
                               document.querySelector(".detail-pane-spec"),
                               "Canonical tests");
  const summary = data.canonical_summary || {};
  const passed = summary.passed != null ? summary.passed : "?";
  const total = summary.total != null ? summary.total : "?";
  const tests = data.canonical_tests || [];

  let html = `<div class="canonical-summary">`;
  if (typeof passed === "number" && typeof total === "number") {
    const cls = passed === total ? "pass-all" : "pass-partial";
    html += `<span class="canonical-rate ${cls}">${passed} / ${total} passed</span>`;
  } else {
    html += `<span class="canonical-rate">scoring unavailable</span>`;
  }
  html += `</div>`;

  if (tests.length === 0) {
    html += `<div class="muted">no canonical tests on disk</div>`;
  } else {
    html += `<ul class="canonical-test-list">`;
    for (const t of tests.slice(0, 10)) {
      html += `<li class="canonical-test">
        <details>
          <summary><span class="test-name">${escHtml(t.name)}</span></summary>
          ${t.source ? `<div class="test-block-label">source</div>
            <pre class="test-block">${escHtml(t.source)}</pre>` : ""}
          ${t.expected ? `<div class="test-block-label">expected output</div>
            <pre class="test-block">${escHtml(t.expected)}</pre>` : ""}
        </details>
      </li>`;
    }
    if (tests.length > 10) {
      html += `<li class="muted">… and ${tests.length - 10} more</li>`;
    }
    html += `</ul>`;
  }
  target.innerHTML = html;
}


function renderKataPack(data) {
  // Insert a "Kata pack" section in the spec pane showing each
  // kata's id/title/difficulty + sample test calls.
  const target = ensureSection("kata-pack-block",
                               document.querySelector(".detail-pane-spec"),
                               "Kata pack");
  const pack = data.kata_pack;

  if (!pack || !pack.katas || pack.katas.length === 0) {
    target.innerHTML = `<div class="muted">no kata pack on disk
      (run <code>load-pack</code> in the kata workspace to generate one)
    </div>`;
    return;
  }

  let html = `<div class="kata-pack-summary">
    <span class="kata-count">${pack.katas.length} katas</span>
    ${pack.dropped && pack.dropped.length
      ? `<span class="muted"> · ${pack.dropped.length} dropped</span>`
      : ""}
  </div>`;
  html += `<ul class="kata-list">`;
  for (const k of pack.katas.slice(0, 12)) {
    const tests = (k.tests || []).slice(0, 2);
    html += `<li class="kata-card">
      <details>
        <summary>
          <span class="kata-id">${escHtml(k.id)}</span>
          <span class="kata-title">${escHtml(k.title || "")}</span>
          <span class="kata-diff kata-diff-${escAttr(k.difficulty || "easy")}">${escHtml(k.difficulty || "")}</span>
        </summary>
        ${k.problem
          ? `<div class="kata-problem">${escHtml(k.problem.slice(0, 280))}${k.problem.length > 280 ? "…" : ""}</div>`
          : ""}
        ${tests.length > 0 ? `<div class="kata-tests">
          <div class="kata-tests-label">sample tests</div>
          ${tests.map(t => `<div class="kata-test">
            <code>${escHtml(t.call)}</code>
            <span class="muted"> -> </span>
            <code>${escHtml(t.expected)}</code>
          </div>`).join("")}
        </div>` : ""}
      </details>
    </li>`;
  }
  html += `</ul>`;
  // Phase 3 follow-up Item 2 (Option B): also link to the existing
  // kata workspace for full kata-solving experience.
  html += `<a class="btn-launch-kata" href="/?lang=${encodeURIComponent(data.slot_id)}&view=kata&include_catalog=all"
    target="_blank" rel="noopener">Open in kata workspace ↗</a>`;
  target.innerHTML = html;
}


function renderLaunchRepl(data) {
  // Insert a "Try it" block at the top of the spec pane with a
  // "Launch REPL" button. Phase 3 follow-up Item 5.
  const target = ensureSection("launch-repl-block",
                               document.querySelector(".detail-pane-spec"),
                               "Try the language",
                               /*prepend=*/true);
  const slotId = data.slot_id;
  if (!data.lang_dir_exists) {
    target.innerHTML = `<div class="muted">language directory not on disk;
      can't launch REPL for this candidate</div>`;
    return;
  }
  target.innerHTML = `
    <div class="launch-actions">
      <a class="btn-launch-repl" href="/?lang=${encodeURIComponent(slotId)}&view=playground&include_catalog=all"
         target="_blank" rel="noopener">
        Launch REPL ↗
      </a>
      <a class="btn-launch-kata" href="/?lang=${encodeURIComponent(slotId)}&view=kata&include_catalog=all"
         target="_blank" rel="noopener">
        Open kata workspace ↗
      </a>
    </div>
    <div class="muted launch-help">
      Opens the existing Forge playground in a new tab so you don't
      lose your place in the catalog.
    </div>
  `;
}


function ensureSection(blockId, parentEl, label, prepend = false) {
  /* Idempotently inject a labeled section into the spec pane.
     Returns the inner content div for renderers to populate. */
  let section = document.getElementById(blockId);
  if (section) {
    return section.querySelector(".section-content") || section;
  }
  section = document.createElement("div");
  section.className = "detail-section";
  section.id = `wrap-${blockId}`;
  section.innerHTML = `
    <h4>${escHtml(label)}</h4>
    <div id="${blockId}" class="section-content"></div>
  `;
  if (prepend && parentEl.firstChild) {
    parentEl.insertBefore(section, parentEl.firstChild);
  } else {
    parentEl.appendChild(section);
  }
  return section.querySelector(".section-content");
}


function bindDetailListeners() {
  document.getElementById("btn-back").addEventListener("click", backToList);
  document.getElementById("btn-approve").addEventListener("click", () => decide("approved"));
  document.getElementById("btn-reject").addEventListener("click", () => onRejectClick());
  document.getElementById("btn-pending").addEventListener("click", () => decide("pending_review"));
  document.getElementById("btn-skip").addEventListener("click", () => advance(+1));
  document.getElementById("reviewer-notes").addEventListener("blur", saveNotes);
  document.getElementById("rejection-reason").addEventListener("change", () => {
    // If currently rejected, update rejection reason in-place.
    if (STATE.detailSlotId) {
      decide("rejected", /*advance=*/false);
    }
  });
  document.getElementById("detail-tier").addEventListener("change", saveTier);
  document.getElementById("detail-tags").addEventListener("change", saveTags);
}


function backToList() {
  STATE.detailSlotId = null;
  document.getElementById("list-view").hidden = false;
  document.getElementById("detail-view").hidden = true;
  history.pushState({}, "", "#");
  refreshList();
}


function onRejectClick() {
  // Show the rejection reason input + focus it before saving.
  document.getElementById("rejection-reason-block").hidden = false;
  const rr = document.getElementById("rejection-reason");
  if (!rr.value) {
    rr.focus();
  } else {
    decide("rejected");
  }
}


async function decide(status, advanceAfter = true) {
  const slotId = STATE.detailSlotId;
  if (!slotId) return;
  const reviewerNotes = document.getElementById("reviewer-notes").value;
  const rejectionReason = document.getElementById("rejection-reason").value;
  const body = { status, reviewer_notes: reviewerNotes };
  if (status === "rejected") body.rejection_reason = rejectionReason;
  const r = await fetch(`/api/catalog/${encodeURIComponent(slotId)}/status`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    alert(`error: ${err.error || r.status}`);
    return;
  }
  // Phase 3 follow-up: visual confirmation BEFORE auto-advance fires.
  // Without this, the badge stays "pending" until advance loads the
  // next slot, which makes the user think nothing happened. Update
  // the badge for the slot we just decided + show a brief toast so
  // the user can SEE the action took effect.
  const badge = document.getElementById("detail-status-badge");
  if (badge) {
    badge.className = `detail-status-badge ${status}`;
    badge.textContent = status.replace("_", " ");
  }
  showToast(`${slotId}: ${status}`, status);

  // Update the in-memory item so the list reflects the change without
  // a refetch.
  const item = STATE.items.find(i => i.slot_id === slotId);
  if (item) {
    item.status = status;
    item.reviewer_notes = reviewerNotes;
    if (status === "rejected") item.rejection_reason = rejectionReason;
  }
  await refreshProgress();
  if (advanceAfter) advance(+1);
}


function showToast(message, kind) {
  /* Phase 3 follow-up: brief 1.2s toast in the bottom-right corner
     to confirm decisions land. The auto-advance feature was happening
     so quietly that the validation user thought clicks weren't
     registering. The toast solves that with zero ambiguity. */
  let host = document.getElementById("toast-host");
  if (!host) {
    host = document.createElement("div");
    host.id = "toast-host";
    host.className = "toast-host";
    document.body.appendChild(host);
  }
  const el = document.createElement("div");
  el.className = `toast toast-${kind || "info"}`;
  el.textContent = message;
  host.appendChild(el);
  // Trigger CSS animation, then remove.
  requestAnimationFrame(() => el.classList.add("toast-shown"));
  setTimeout(() => {
    el.classList.remove("toast-shown");
    setTimeout(() => el.remove(), 250);
  }, 1200);
}


async function saveNotes() {
  const slotId = STATE.detailSlotId;
  if (!slotId) return;
  const notes = document.getElementById("reviewer-notes").value;
  await fetch(`/api/catalog/${encodeURIComponent(slotId)}/notes`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ reviewer_notes: notes }),
  });
}


async function saveTier() {
  const slotId = STATE.detailSlotId;
  if (!slotId) return;
  const tier = document.getElementById("detail-tier").value.trim();
  await fetch(`/api/catalog/${encodeURIComponent(slotId)}/tier`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ tier: tier || null }),
  });
}


async function saveTags() {
  const slotId = STATE.detailSlotId;
  if (!slotId) return;
  const raw = document.getElementById("detail-tags").value;
  const tags = raw.split(",").map(s => s.trim()).filter(Boolean);
  await fetch(`/api/catalog/${encodeURIComponent(slotId)}/tags`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ tags }),
  });
  // Refresh the tag autocomplete so newly-added tags appear there next time.
  refreshTagSuggestions();
}


function advance(delta) {
  // Move to the next/prev item in the filtered list. If we're at the end,
  // return to list view.
  const newIdx = STATE.detailIndex + delta;
  if (newIdx < 0 || newIdx >= STATE.items.length) {
    backToList();
    return;
  }
  STATE.detailIndex = newIdx;
  STATE.selectedIndex = newIdx;
  openDetail(STATE.items[newIdx].slot_id, /*pushState=*/true);
}


// ---------------------------------------------------------------------------
// Keyboard navigation
// ---------------------------------------------------------------------------

function bindKeyboard() {
  document.addEventListener("keydown", e => {
    // Don't intercept keys when the user is typing in an input.
    const inInput = e.target.tagName === "INPUT" ||
                    e.target.tagName === "TEXTAREA" ||
                    e.target.tagName === "SELECT";
    const inDetail = !document.getElementById("detail-view").hidden;

    if (inInput && e.key !== "Escape") return;

    if (inDetail) {
      switch (e.key) {
        case "a": case "A": e.preventDefault(); decide("approved"); break;
        case "r": case "R": e.preventDefault(); onRejectClick(); break;
        case "p": case "P": e.preventDefault(); decide("pending_review"); break;
        case "s": case "S": e.preventDefault(); advance(+1); break;
        case "j": case "J": case "ArrowDown": e.preventDefault(); advance(+1); break;
        case "k": case "K": case "ArrowUp": e.preventDefault(); advance(-1); break;
        case "n": case "N": e.preventDefault(); saveNotes(); break;
        case "Escape": e.preventDefault(); backToList(); break;
      }
    } else {
      switch (e.key) {
        case "j": case "J": case "ArrowDown":
          e.preventDefault();
          STATE.selectedIndex = Math.min(STATE.items.length - 1,
                                          STATE.selectedIndex + 1);
          renderListSelection();
          break;
        case "k": case "K": case "ArrowUp":
          e.preventDefault();
          STATE.selectedIndex = Math.max(0, STATE.selectedIndex - 1);
          renderListSelection();
          break;
        case "Enter":
          e.preventDefault();
          if (STATE.items.length > 0) openDetailByIndex(STATE.selectedIndex);
          break;
        case "/":
          e.preventDefault();
          document.getElementById("filter-search").focus();
          break;
      }
    }
  });
}

function renderListSelection() {
  const rows = document.querySelectorAll(".catalog-row");
  rows.forEach((row, idx) => {
    row.classList.toggle("selected", idx === STATE.selectedIndex);
    if (idx === STATE.selectedIndex) {
      row.scrollIntoView({ block: "nearest" });
    }
  });
}


// ---------------------------------------------------------------------------
// Bulk selection (Stage D)
// ---------------------------------------------------------------------------

function toggleBulkSelection(slotId, on) {
  if (on) STATE.bulkSelection.add(slotId);
  else STATE.bulkSelection.delete(slotId);
  renderBulkBar();
}

function renderBulkBar() {
  let bar = document.getElementById("bulk-bar");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "bulk-bar";
    bar.className = "bulk-bar";
    document.querySelector(".catalog-list-pane").prepend(bar);
  }
  const n = STATE.bulkSelection.size;
  if (n === 0) {
    bar.classList.remove("active");
    bar.innerHTML = "";
    return;
  }
  bar.classList.add("active");
  bar.innerHTML = `
    <span class="bulk-count">${n} selected</span>
    <button id="bulk-approve">approve all</button>
    <button id="bulk-reject">reject all</button>
    <button id="bulk-pending">mark pending</button>
    <button id="bulk-tag">add tag…</button>
    <button id="bulk-clear">clear</button>
  `;
  bar.querySelector("#bulk-approve").addEventListener("click", () => bulkAction("approved"));
  bar.querySelector("#bulk-reject").addEventListener("click", () => bulkAction("rejected"));
  bar.querySelector("#bulk-pending").addEventListener("click", () => bulkAction("pending_review"));
  bar.querySelector("#bulk-tag").addEventListener("click", () => bulkAddTagPrompt());
  bar.querySelector("#bulk-clear").addEventListener("click", () => {
    STATE.bulkSelection.clear();
    refreshList();
  });
}

async function bulkAction(status) {
  const slotIds = [...STATE.bulkSelection];
  if (slotIds.length === 0) return;
  let reason = null;
  if (status === "rejected") {
    reason = prompt(`Reject ${slotIds.length} languages with reason:`);
    if (reason == null) return;
  }
  if (!confirm(`Set status=${status} on ${slotIds.length} languages?`)) return;
  const r = await fetch("/api/catalog/bulk/status", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ slot_ids: slotIds, status, rejection_reason: reason }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    alert(`bulk update failed: ${err.error || r.status}`);
    return;
  }
  STATE.bulkSelection.clear();
  await refreshProgress();
  await refreshList();
}

async function bulkAddTagPrompt() {
  const slotIds = [...STATE.bulkSelection];
  if (slotIds.length === 0) return;
  const tag = prompt(`Add tag to ${slotIds.length} languages:`);
  if (!tag) return;
  await fetch("/api/catalog/bulk/tag", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ slot_ids: slotIds, tag }),
  });
  await refreshList();
}

function bindBulkListeners() {
  // Bulk-bar buttons are bound dynamically in renderBulkBar.
}


// ---------------------------------------------------------------------------
// Progress + tag autocomplete
// ---------------------------------------------------------------------------

async function refreshProgress() {
  const r = await fetch("/api/catalog/progress");
  if (!r.ok) return;
  const p = await r.json();
  const el = document.getElementById("progress-summary");
  el.innerHTML = `
    ${p.total} candidates ·
    <span class="approved">${p.approved} approved</span> ·
    <span class="rejected">${p.rejected} rejected</span> ·
    <span class="pending">${p.pending_review} pending</span>
  `;
}

async function refreshTagSuggestions() {
  try {
    const r = await fetch("/api/catalog/tags");
    if (!r.ok) return;
    const data = await r.json();
    STATE.tagSuggestions = data.tags || [];
    const dl = document.getElementById("tag-suggestions");
    if (dl) {
      dl.innerHTML = "";
      for (const t of STATE.tagSuggestions) {
        const opt = document.createElement("option");
        opt.value = t;
        dl.appendChild(opt);
      }
    }
  } catch (e) { /* tags endpoint may not exist yet */ }
}


// ---------------------------------------------------------------------------
// URL hash sync
// ---------------------------------------------------------------------------

function parseHash() {
  // Format: #slot/<id> for detail; #?<filter-params> for list filters.
  const h = location.hash.replace(/^#/, "");
  if (!h) return;
  if (h.startsWith("?")) {
    const p = new URLSearchParams(h.slice(1));
    if (p.has("search")) STATE.filters.search = p.get("search") || "";
    if (p.has("persona")) STATE.filters.persona = p.get("persona") || "";
    if (p.has("era")) STATE.filters.era = p.get("era") || "";
    if (p.has("theme")) STATE.filters.theme = p.get("theme") || "";
    if (p.has("phrasebook")) STATE.filters.phrasebook = p.get("phrasebook") || "";
    if (p.has("min_distinctiveness"))
      STATE.filters.min_distinctiveness =
        parseFloat(p.get("min_distinctiveness")) || 0;
    if (p.has("sort_by")) STATE.filters.sort_by = p.get("sort_by");
    if (p.has("sort_dir")) STATE.filters.sort_dir = p.get("sort_dir");
  }
}

function updateHash() {
  // Only update when in list view; detail view manages its own hash.
  if (STATE.detailSlotId) return;
  // Don't pollute history on every filter change — replace.
  const params = new URLSearchParams();
  for (const k of ["search", "persona", "era", "theme", "phrasebook", "sort_by", "sort_dir"]) {
    const v = STATE.filters[k];
    if (v) params.set(k, v);
  }
  if (STATE.filters.min_distinctiveness > 0)
    params.set("min_distinctiveness", String(STATE.filters.min_distinctiveness));
  const hash = params.toString() ? `#?${params}` : "";
  if (hash !== location.hash) {
    history.replaceState({}, "", location.pathname + hash);
  }
}

function handlePopState(e) {
  // Browser back/forward — re-parse hash and re-render.
  if (location.hash.startsWith("#slot/")) {
    const slot = location.hash.slice("#slot/".length);
    openDetail(slot, /*pushState=*/false);
  } else {
    STATE.detailSlotId = null;
    document.getElementById("list-view").hidden = false;
    document.getElementById("detail-view").hidden = true;
    parseHash();
    buildFilterUI();
    refreshList();
  }
}


// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function debounce(fn, ms) {
  let t = null;
  return function(...args) {
    clearTimeout(t);
    t = setTimeout(() => fn.apply(this, args), ms);
  };
}

function escHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
function escAttr(s) {
  return escHtml(s).replace(/"/g, "&quot;");
}
