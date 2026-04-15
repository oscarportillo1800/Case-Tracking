/**
 * Federal Litigation Tracker — Frontend
 *
 * Communicates with the Flask backend at /api/.
 * Provides full filtering, pagination, case detail modal,
 * hide (soft-remove), restore, and permanent delete.
 */

const API = "/api";

/* ── State ───────────────────────────────────────────────────────── */
const state = {
  page: 1,
  perPage: 50,
  search: "",
  courtLevel: "",
  court: "",
  caseType: "",
  source: "",
  org: "",
  federalOnly: true,
  dateFrom: "",
  dateTo: "",
  sort: "date_filed",
  order: "desc",
  view: "grid",
  activeTab: "active",   // "active" | "hidden"
};

let debounceTimer = null;

/* ── Boot ────────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  bindFilters();
  bindSearch();
  bindViewToggle();
  bindTabs();
  loadStats();
  loadCases();
});

/* ── API helpers ─────────────────────────────────────────────────── */
async function apiFetch(path, options = {}) {
  const resp = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
  }
  return resp.json();
}

/* ── Stats bar ───────────────────────────────────────────────────── */
async function loadStats() {
  try {
    const data = await apiFetch("/stats");
    document.getElementById("stat-total").textContent = data.total_cases.toLocaleString();
    document.getElementById("stat-hidden").textContent = data.hidden_cases.toLocaleString();
    document.getElementById("stat-district").textContent =
      (data.by_court_level["District Court"] || 0).toLocaleString();
    document.getElementById("stat-circuit").textContent =
      (data.by_court_level["Circuit Court"] || 0).toLocaleString();
    document.getElementById("stat-supreme").textContent =
      (data.by_court_level["Supreme Court"] || 0).toLocaleString();
    if (data.last_sync) {
      const d = new Date(data.last_sync);
      document.getElementById("last-sync").textContent =
        "Last sync: " + d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
    }
    // Update tab hidden count badge
    const hiddenBadge = document.getElementById("hidden-tab-count");
    if (hiddenBadge) hiddenBadge.textContent = data.hidden_cases;
  } catch (e) {
    console.error("Stats load failed:", e);
  }
}

/* ── Load cases ──────────────────────────────────────────────────── */
async function loadCases() {
  const container = document.getElementById("cases-container");
  container.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Loading cases…</p></div>`;

  if (state.activeTab === "hidden") {
    await loadHiddenCases();
    return;
  }

  try {
    const params = new URLSearchParams({
      page: state.page,
      per_page: state.perPage,
      sort: state.sort,
      order: state.order,
      federal_only: state.federalOnly,
    });
    if (state.search)     params.set("search", state.search);
    if (state.courtLevel) params.set("court_level", state.courtLevel);
    if (state.court)      params.set("court", state.court);
    if (state.caseType)   params.set("case_type", state.caseType);
    if (state.source)     params.set("source", state.source);
    if (state.org)        params.set("org", state.org);
    if (state.dateFrom)   params.set("date_from", state.dateFrom);
    if (state.dateTo)     params.set("date_to", state.dateTo);

    const data = await apiFetch(`/cases?${params}`);
    renderCases(data.cases, container);
    renderPagination(data.pagination);
    document.getElementById("result-count").textContent =
      `${data.pagination.total.toLocaleString()} case${data.pagination.total !== 1 ? "s" : ""}`;
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><p>Error loading cases: ${escHtml(e.message)}</p></div>`;
  }
}

async function loadHiddenCases() {
  const container = document.getElementById("cases-container");
  try {
    const data = await apiFetch(`/cases/hidden?page=${state.page}&per_page=${state.perPage}`);
    if (data.cases.length === 0) {
      container.innerHTML = `
        <div class="empty-state">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M3 3l18 18M10.477 10.477A3 3 0 0013.06 13.06M9 9a3 3 0 014.243 4.243M6.53 6.53A9.003 9.003 0 0121 12a9.003 9.003 0 01-2.53 6.217M3 12a9.003 9.003 0 012.53-6.217"/>
          </svg>
          <p>No hidden cases</p>
        </div>`;
    } else {
      renderCases(data.cases, container, true);
      renderPagination(data.pagination);
    }
    document.getElementById("result-count").textContent =
      `${data.pagination.total.toLocaleString()} hidden`;
  } catch (e) {
    container.innerHTML = `<div class="empty-state"><p>Error: ${escHtml(e.message)}</p></div>`;
  }
}

/* ── Render cases ────────────────────────────────────────────────── */
function renderCases(cases, container, isHiddenView = false) {
  if (cases.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M9 13h6m-3-3v6m5-13H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V7l-4-4z"/>
        </svg>
        <p>No cases match your filters.</p>
        <p style="font-size:0.8rem;margin-top:0.5rem;">Try adjusting your search or filter settings.</p>
      </div>`;
    return;
  }

  container.className = `${state.view}-view`;
  container.innerHTML = cases.map(c => renderCard(c, isHiddenView)).join("");

  // Bind card action buttons
  container.querySelectorAll("[data-action]").forEach(btn => {
    btn.addEventListener("click", e => {
      e.stopPropagation();
      const action = btn.dataset.action;
      const id = parseInt(btn.dataset.id, 10);
      const name = btn.dataset.name || "";
      if (action === "view")    openCaseModal(id);
      if (action === "hide")    confirmHide(id, name);
      if (action === "unhide")  doUnhide(id, name);
      if (action === "delete")  confirmDelete(id, name);
    });
  });

  // Click card to open modal
  container.querySelectorAll(".case-card").forEach(card => {
    card.addEventListener("click", () => {
      const id = parseInt(card.dataset.id, 10);
      openCaseModal(id);
    });
  });
}

function renderCard(c, isHiddenView) {
  const priority = c.involves_democracy_forward || c.involves_aclu ||
    c.involves_democracy_defenders || c.involves_public_citizen ||
    c.involves_protect_democracy;

  const badges = buildBadges(c);
  const meta = buildMeta(c);

  const actions = isHiddenView
    ? `<button class="btn-icon" data-action="unhide" data-id="${c.id}" data-name="${escAttr(c.case_name)}" title="Restore case">
         <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
           <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>
         </svg>
       </button>
       <button class="btn-icon danger" data-action="delete" data-id="${c.id}" data-name="${escAttr(c.case_name)}" title="Permanently delete">
         <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
           <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/>
         </svg>
       </button>`
    : `<button class="btn-icon" data-action="hide" data-id="${c.id}" data-name="${escAttr(c.case_name)}" title="Hide this case">
         <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
           <path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/>
           <line x1="1" y1="1" x2="23" y2="23"/>
         </svg>
       </button>
       <button class="btn-icon danger" data-action="delete" data-id="${c.id}" data-name="${escAttr(c.case_name)}" title="Permanently delete">
         <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
           <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/>
         </svg>
       </button>`;

  const docketLink = c.docket_url
    ? `<a href="${escAttr(c.docket_url)}" target="_blank" rel="noopener noreferrer" class="btn btn-sm btn-outline" onclick="event.stopPropagation()">
         <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12">
           <path d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/>
         </svg>CourtListener Docket
       </a>`
    : "";

  return `
    <div class="case-card${priority ? " priority" : ""}" data-id="${c.id}">
      <div class="card-header">
        <div class="case-name">${escHtml(c.case_name)}</div>
        <div class="card-actions">${actions}</div>
      </div>
      <div class="badges">${badges}</div>
      <div class="card-meta">${meta}</div>
      <div class="card-footer">
        ${c.case_number ? `<span class="case-number">${escHtml(c.case_number)}</span>` : "<span></span>"}
        ${docketLink}
      </div>
    </div>`;
}

function buildBadges(c) {
  const parts = [];

  // Source
  const sourceClass = {
    "CourtListener": "badge-source",
    "Just Security": "badge-source",
    "Michigan Clearinghouse": "badge-court",
  }[c.source] || "badge-source";
  parts.push(`<span class="badge ${sourceClass}">${escHtml(c.source)}</span>`);

  // Court level
  if (c.court_level) {
    const levelClass = c.court_level === "Supreme Court" ? "badge-supremecourt" : "badge-court";
    parts.push(`<span class="badge ${levelClass}">${escHtml(c.court_level)}</span>`);
  }

  // Case type
  if (c.case_type) {
    const typeClass = {
      "FOIA": "badge-foia",
      "APA": "badge-apa",
      "Habeas Corpus": "badge-habeas",
    }[c.case_type] || "badge-type";
    parts.push(`<span class="badge ${typeClass}">${escHtml(c.case_type)}</span>`);
  }

  // Federal defendant
  if (c.names_federal_defendant) {
    parts.push(`<span class="badge badge-federal">Federal Defendant</span>`);
  }

  // Priority orgs
  if (c.involves_democracy_forward) parts.push(`<span class="badge badge-org">Democracy Forward</span>`);
  if (c.involves_aclu)              parts.push(`<span class="badge badge-org">ACLU</span>`);
  if (c.involves_democracy_defenders) parts.push(`<span class="badge badge-org">Democracy Defenders</span>`);
  if (c.involves_public_citizen)    parts.push(`<span class="badge badge-org">Public Citizen</span>`);
  if (c.involves_protect_democracy) parts.push(`<span class="badge badge-org">Protect Democracy</span>`);

  return parts.join("");
}

function buildMeta(c) {
  const parts = [];

  if (c.court) {
    parts.push(`<span class="meta-item">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>
      </svg>${escHtml(c.court)}</span>`);
  }

  if (c.date_filed) {
    parts.push(`<span class="meta-item">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>
      </svg>Filed ${fmtDate(c.date_filed)}</span>`);
  }

  if (c.date_terminated) {
    parts.push(`<span class="meta-item" style="color:#f87171">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>
      </svg>Closed ${fmtDate(c.date_terminated)}</span>`);
  }

  return parts.join("");
}

/* ── Case detail modal ───────────────────────────────────────────── */
async function openCaseModal(id) {
  let c;
  try {
    c = await apiFetch(`/cases/${id}`);
  } catch (e) {
    showToast("Failed to load case details", "error");
    return;
  }

  const orgList = [
    c.involves_democracy_forward && "Democracy Forward Foundation",
    c.involves_aclu && "ACLU",
    c.involves_democracy_defenders && "Democracy Defenders Fund",
    c.involves_public_citizen && "Public Citizen",
    c.involves_protect_democracy && "Protect Democracy",
  ].filter(Boolean).join(", ") || "None identified";

  const docketBtn = c.docket_url
    ? `<a href="${escAttr(c.docket_url)}" target="_blank" rel="noopener noreferrer" class="btn btn-primary">
         <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
           <path d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/>
         </svg>View Docket on CourtListener
       </a>`
    : "";

  const sourceBtn = c.source_url && c.source_url !== c.docket_url
    ? `<a href="${escAttr(c.source_url)}" target="_blank" rel="noopener noreferrer" class="btn btn-outline">
         Source: ${escHtml(c.source)}
       </a>`
    : "";

  const html = `
    <div class="modal-backdrop" id="case-modal" role="dialog" aria-modal="true">
      <div class="modal">
        <div class="modal-header">
          <div class="modal-title">${escHtml(c.case_name)}</div>
          <button class="modal-close" id="modal-close-btn" aria-label="Close">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
        <div class="modal-body">
          <div class="modal-section">
            <h3>Case Identification</h3>
            <p><strong>Case Name:</strong> ${escHtml(c.case_name)}</p>
            ${c.case_number ? `<p><strong>Case Number:</strong> <code>${escHtml(c.case_number)}</code></p>` : ""}
            ${c.court ? `<p><strong>Court:</strong> ${escHtml(c.court)}</p>` : ""}
            ${c.court_level ? `<p><strong>Court Level:</strong> ${escHtml(c.court_level)}</p>` : ""}
          </div>
          <div class="modal-section">
            <h3>Parties</h3>
            ${c.plaintiff ? `<p><strong>Plaintiff(s):</strong> ${escHtml(c.plaintiff)}</p>` : ""}
            ${c.defendant ? `<p><strong>Defendant(s):</strong> ${escHtml(c.defendant)}</p>` : ""}
            <p><strong>Priority Organizations:</strong> ${escHtml(orgList)}</p>
            <p><strong>Names Federal Defendant:</strong> ${c.names_federal_defendant ? "Yes" : "No"}</p>
          </div>
          <div class="modal-section">
            <h3>Case Type &amp; Cause of Action</h3>
            ${c.case_type ? `<p><strong>Type:</strong> ${escHtml(c.case_type)}</p>` : ""}
            ${c.cause_of_action ? `<p><strong>Cause of Action:</strong> ${escHtml(c.cause_of_action)}</p>` : ""}
            ${c.nature_of_suit ? `<p><strong>Nature of Suit:</strong> ${escHtml(c.nature_of_suit)}</p>` : ""}
          </div>
          <div class="modal-section">
            <h3>Dates</h3>
            ${c.date_filed ? `<p><strong>Filed:</strong> ${fmtDate(c.date_filed)}</p>` : ""}
            ${c.date_terminated ? `<p><strong>Terminated:</strong> ${fmtDate(c.date_terminated)}</p>` : "<p><strong>Status:</strong> Active / Ongoing</p>"}
          </div>
          <div class="modal-section">
            <h3>Data Source</h3>
            <p><strong>Source:</strong> ${escHtml(c.source)}</p>
            ${c.source_url ? `<p><strong>Source URL:</strong> <a href="${escAttr(c.source_url)}" target="_blank" rel="noopener noreferrer">${escHtml(c.source_url)}</a></p>` : ""}
            ${c.docket_url ? `<p><strong>CourtListener Docket:</strong> <a href="${escAttr(c.docket_url)}" target="_blank" rel="noopener noreferrer">${escHtml(c.docket_url)}</a></p>` : ""}
          </div>
          ${c.hidden ? `
          <div class="modal-section">
            <h3>Hidden</h3>
            <p>This case is currently hidden from the main view.</p>
            ${c.hidden_reason ? `<p><strong>Reason:</strong> ${escHtml(c.hidden_reason)}</p>` : ""}
            ${c.hidden_at ? `<p><strong>Hidden on:</strong> ${fmtDate(c.hidden_at)}</p>` : ""}
          </div>` : ""}
        </div>
        <div class="modal-footer">
          ${docketBtn}
          ${sourceBtn}
          ${!c.hidden
            ? `<button class="btn btn-outline" id="modal-hide-btn">Hide Case</button>`
            : `<button class="btn btn-outline" id="modal-unhide-btn">Restore Case</button>`}
          <button class="btn btn-danger" id="modal-delete-btn">Delete Case</button>
        </div>
      </div>
    </div>`;

  document.body.insertAdjacentHTML("beforeend", html);
  const backdrop = document.getElementById("case-modal");

  document.getElementById("modal-close-btn").onclick = () => backdrop.remove();
  backdrop.addEventListener("click", e => { if (e.target === backdrop) backdrop.remove(); });

  const hideBtn = document.getElementById("modal-hide-btn");
  if (hideBtn) hideBtn.onclick = () => { backdrop.remove(); confirmHide(c.id, c.case_name); };

  const unhideBtn = document.getElementById("modal-unhide-btn");
  if (unhideBtn) unhideBtn.onclick = () => { backdrop.remove(); doUnhide(c.id, c.case_name); };

  document.getElementById("modal-delete-btn").onclick = () => {
    backdrop.remove();
    confirmDelete(c.id, c.case_name);
  };
}

/* ── Hide / unhide / delete ──────────────────────────────────────── */
function confirmHide(id, name) {
  showConfirmDialog({
    title: "Hide Case",
    body: `Hide <strong>${escHtml(name)}</strong> from your tracker view?
           <br><br>It will be moved to the Hidden tab and can be restored at any time.`,
    placeholder: "Optional: reason for hiding (e.g. not relevant)",
    confirmLabel: "Hide Case",
    confirmClass: "btn-outline",
    onConfirm: async (reason) => {
      await apiFetch(`/cases/${id}/hide`, {
        method: "PATCH",
        body: JSON.stringify({ reason }),
      });
      showToast("Case hidden", "info");
      loadStats();
      loadCases();
    },
  });
}

async function doUnhide(id, name) {
  await apiFetch(`/cases/${id}/unhide`, { method: "PATCH" });
  showToast(`"${name}" restored to tracker`, "success");
  loadStats();
  loadCases();
}

function confirmDelete(id, name) {
  showConfirmDialog({
    title: "Permanently Delete Case",
    body: `<span style="color:#f87171"><strong>This cannot be undone.</strong></span>
           <br><br>Permanently remove <strong>${escHtml(name)}</strong> from the database?
           <br><small style="color:var(--text-muted)">The case may reappear on the next daily sync unless it no longer matches tracker criteria.</small>`,
    placeholder: "",
    confirmLabel: "Delete Permanently",
    confirmClass: "btn-danger",
    onConfirm: async () => {
      await apiFetch(`/cases/${id}`, { method: "DELETE" });
      showToast("Case permanently deleted", "info");
      loadStats();
      loadCases();
    },
    noReason: true,
  });
}

function showConfirmDialog({ title, body, placeholder, confirmLabel, confirmClass, onConfirm, noReason }) {
  const html = `
    <div class="modal-backdrop" id="confirm-modal">
      <div class="modal confirm-modal">
        <div class="modal-header">
          <div class="modal-title">${title}</div>
          <button class="modal-close" id="confirm-close" aria-label="Close">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>
        <div class="modal-body">
          <p>${body}</p>
          ${!noReason ? `<textarea id="confirm-reason" placeholder="${escAttr(placeholder || '')}"></textarea>` : ""}
        </div>
        <div class="modal-footer">
          <button class="btn btn-outline" id="confirm-cancel">Cancel</button>
          <button class="btn ${confirmClass}" id="confirm-ok">${confirmLabel}</button>
        </div>
      </div>
    </div>`;

  document.body.insertAdjacentHTML("beforeend", html);
  const backdrop = document.getElementById("confirm-modal");
  const close = () => backdrop.remove();

  document.getElementById("confirm-close").onclick = close;
  document.getElementById("confirm-cancel").onclick = close;
  backdrop.addEventListener("click", e => { if (e.target === backdrop) close(); });

  document.getElementById("confirm-ok").onclick = async () => {
    const reason = noReason ? "" : (document.getElementById("confirm-reason")?.value.trim() || "");
    close();
    try {
      await onConfirm(reason);
    } catch (e) {
      showToast("Action failed: " + e.message, "error");
    }
  };
}

/* ── Pagination ──────────────────────────────────────────────────── */
function renderPagination({ page, total_pages }) {
  const el = document.getElementById("pagination");
  if (total_pages <= 1) { el.innerHTML = ""; return; }

  const pages = [];
  pages.push(makePage(page - 1, "←", page <= 1));
  const range = pageRange(page, total_pages);
  range.forEach(p => {
    if (p === "…") pages.push(`<span style="padding:0 0.25rem;color:var(--text-muted)">…</span>`);
    else pages.push(makePage(p, p, false, p === page));
  });
  pages.push(makePage(page + 1, "→", page >= total_pages));

  el.innerHTML = pages.join("");
  el.querySelectorAll(".page-btn:not([disabled])").forEach(btn => {
    btn.addEventListener("click", () => {
      state.page = parseInt(btn.dataset.page, 10);
      loadCases();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  });
}

function makePage(p, label, disabled, active = false) {
  return `<button class="page-btn${active ? " active" : ""}" data-page="${p}" ${disabled ? "disabled" : ""}>${label}</button>`;
}

function pageRange(current, total) {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages = [1];
  if (current > 3) pages.push("…");
  for (let i = Math.max(2, current - 1); i <= Math.min(total - 1, current + 1); i++) pages.push(i);
  if (current < total - 2) pages.push("…");
  pages.push(total);
  return pages;
}

/* ── Filters & search ────────────────────────────────────────────── */
function bindFilters() {
  const bind = (id, key, reset = true) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("change", () => {
      state[key] = el.value;
      if (reset) state.page = 1;
      loadCases();
    });
  };

  bind("filter-court-level", "courtLevel");
  bind("filter-case-type", "caseType");
  bind("filter-source", "source");
  bind("filter-date-from", "dateFrom");
  bind("filter-date-to", "dateTo");
  bind("filter-sort", "sort");
  bind("filter-per-page", "perPage", false);

  // Federal only toggle
  const fedToggle = document.getElementById("filter-federal-only");
  if (fedToggle) {
    fedToggle.addEventListener("change", () => {
      state.federalOnly = fedToggle.checked;
      state.page = 1;
      loadCases();
    });
  }

  // Org pills
  document.querySelectorAll(".org-pill").forEach(pill => {
    pill.addEventListener("click", () => {
      const org = pill.dataset.org;
      if (state.org === org) {
        state.org = "";
        pill.classList.remove("active");
      } else {
        state.org = org;
        document.querySelectorAll(".org-pill").forEach(p => p.classList.remove("active"));
        pill.classList.add("active");
      }
      state.page = 1;
      loadCases();
    });
  });

  // Clear filters button
  const clearBtn = document.getElementById("clear-filters");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      state.org = "";
      state.courtLevel = "";
      state.caseType = "";
      state.source = "";
      state.dateFrom = "";
      state.dateTo = "";
      state.search = "";
      state.page = 1;
      document.querySelectorAll(".org-pill").forEach(p => p.classList.remove("active"));
      document.getElementById("search-input").value = "";
      document.getElementById("filter-court-level").value = "";
      document.getElementById("filter-case-type").value = "";
      document.getElementById("filter-source").value = "";
      const df = document.getElementById("filter-date-from");
      const dt = document.getElementById("filter-date-to");
      if (df) df.value = "";
      if (dt) dt.value = "";
      loadCases();
    });
  }
}

function bindSearch() {
  const input = document.getElementById("search-input");
  if (!input) return;
  input.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      state.search = input.value.trim();
      state.page = 1;
      loadCases();
    }, 350);
  });
}

/* ── View toggle (grid / list) ───────────────────────────────────── */
function bindViewToggle() {
  document.querySelectorAll(".view-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      state.view = btn.dataset.view;
      document.querySelectorAll(".view-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const container = document.getElementById("cases-container");
      container.className = `${state.view}-view`;
      loadCases();
    });
  });
}

/* ── Tabs (active / hidden) ──────────────────────────────────────── */
function bindTabs() {
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      state.activeTab = btn.dataset.tab;
      state.page = 1;
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      loadCases();
    });
  });
}

/* ── Manual sync ─────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  const syncBtn = document.getElementById("sync-btn");
  if (!syncBtn) return;
  syncBtn.addEventListener("click", async () => {
    syncBtn.disabled = true;
    syncBtn.innerHTML = `<span class="syncing-pill">Syncing all sources…</span>`;
    try {
      const result = await apiFetch("/sync", { method: "POST", body: JSON.stringify({ source: "all" }) });
      const s = result.summary;
      const added = Object.values(s).reduce((a, v) => a + (v.added || 0), 0);
      const updated = Object.values(s).reduce((a, v) => a + (v.updated || 0), 0);
      showToast(`Sync complete — ${added} new, ${updated} updated`, "success");
      loadStats();
      loadCases();
    } catch (e) {
      showToast("Sync failed: " + e.message, "error");
    } finally {
      syncBtn.disabled = false;
      syncBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
        <polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 102.13-9.36L1 10"/>
      </svg>Sync Now`;
    }
  });
});

/* ── Toast ───────────────────────────────────────────────────────── */
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 4000);
}

/* ── Utilities ───────────────────────────────────────────────────── */
function escHtml(s) {
  if (!s) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escAttr(s) { return escHtml(s); }

function fmtDate(d) {
  if (!d) return "";
  const dt = new Date(d + (d.length === 10 ? "T00:00:00" : ""));
  return dt.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}
