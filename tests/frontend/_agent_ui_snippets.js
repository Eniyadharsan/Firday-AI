/**
 * Ported UI logic for the FRIDAY Desktop Agent controls.
 *
 * ⚠ SYNC NOTE: These functions are ported (behaviour-for-behaviour) from the
 * inline <script> in `public/index.html` (task 15.1). They are duplicated here
 * only so the DOM-manipulating controls can be unit tested outside a live
 * browser. If you change the originals in index.html, update these too.
 *
 * Sources in public/index.html:
 *   - agentKillSwitch()                  (Req 8.1  — Kill_Switch dispatch)
 *   - agentShowConfirmation(prompt)      (Req 6.1  — Confirmation_Prompt)
 *   - agentResolveConfirmation(ok,why)   (Req 6.1  — approve/decline/timeout)
 *   - agentShowAmbiguity(cands, onPick)  (Req 5.4  — ambiguity candidate list)
 *   - renderHistory(entries)             (Req 7.5  — newest-first history)
 *
 * The originals close over module state (agentState, _cfp, _localHistory) and
 * reference the global `document` / `fetch`. Here they are wrapped in a factory
 * that takes an explicit `doc` and an injectable `fetch`, so tests can drive
 * them deterministically.
 */

// ---- Pure helpers (mirror index.html) -------------------------------------
export function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

export function tsMs(ts) {
  const t = Date.parse(ts);
  return isNaN(t) ? 0 : t;
}

export function fmtTime(ts) {
  const t = Date.parse(ts);
  if (isNaN(t)) return String(ts || '');
  const d = new Date(t);
  return d.toLocaleString();
}

export function prettyCommand(id) {
  if (!id) return '';
  const map = {
    launch_app: 'Launch application', open_path: 'Open file or folder', web_search: 'Web search',
    media_control: 'Media control', dictation: 'Dictate text', window_management: 'Window management', lock_pc: 'Lock PC'
  };
  if (map[id]) return map[id];
  return id.replace(/[_-]+/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); });
}

/**
 * Build a Desktop Agent UI controller bound to a document.
 * @param {Document} doc  jsdom document containing the agent markup.
 * @param {object} [opts]
 * @param {Function} [opts.fetch]  fetch implementation (defaults to a no-op resolved promise).
 * @param {Function} [opts.toast]  toast callback (optional).
 */
export function createAgentUI(doc, opts) {
  opts = opts || {};
  const doFetch = opts.fetch || function () { return Promise.resolve({ ok: true, json: function () { return Promise.resolve({}); } }); };
  const toast = opts.toast || function () {};

  const AGENT_VIEW = {
    enabled: { glyph: '▶', text: 'AGENT ACTIVE', aria: 'Desktop agent status: enabled' },
    observing: { glyph: '◉', text: 'OBSERVING SCREEN', aria: 'Desktop agent status: observing screen' },
    disabled: { glyph: '■', text: 'AGENT OFF', aria: 'Desktop agent status: disabled' }
  };
  let agentState = 'disabled';

  function renderState() {
    const ind = doc.getElementById('agentIndicator');
    if (!ind) return;
    const v = AGENT_VIEW[agentState] || AGENT_VIEW.disabled;
    ind.setAttribute('data-state', agentState);
    ind.setAttribute('aria-label', v.aria);
    const g = doc.getElementById('agentGlyph'); if (g) g.textContent = v.glyph;
    const t = doc.getElementById('agentText'); if (t) t.textContent = v.text;
    const kill = doc.getElementById('agentKill');
    if (kill) kill.disabled = (agentState === 'disabled');
  }

  function setAgentState(state) {
    if (!AGENT_VIEW[state]) return;
    agentState = state;
    renderState();
  }
  function getAgentState() { return agentState; }

  // ── Kill_Switch (Req 8.1) ──
  async function agentKillSwitch() {
    setAgentState('disabled');
    try {
      await doFetch('/agent/kill-switch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    } catch (e) { /* fail closed — UI already shows disabled */ }
    toast('Desktop agent disabled');
    agentRecordLocal({ event_type: 'kill_switch', reason: 'user_activated' });
  }

  // ── Confirmation_Prompt (Req 6.1) ──
  let _cfp = null;

  function agentShowConfirmation(prompt) {
    _cfp = prompt || {};
    const cmdEl = doc.getElementById('cfpCmd');
    if (cmdEl) cmdEl.textContent = prettyCommand(_cfp.commandId) || 'Unknown action';
    const pEl = doc.getElementById('cfpParams');
    if (pEl) {
      const params = _cfp.parameters && Object.keys(_cfp.parameters).length ? _cfp.parameters : null;
      if (params) { pEl.textContent = JSON.stringify(params, null, 2); pEl.style.display = 'block'; }
      else { pEl.textContent = ''; pEl.style.display = 'none'; }
    }
    const ov = doc.getElementById('cfpOverlay');
    if (ov) ov.classList.add('open');
    return new Promise(function (res) { _cfp.resolve = res; });
  }

  async function agentResolveConfirmation(approved, reason) {
    const ov = doc.getElementById('cfpOverlay');
    if (ov) ov.classList.remove('open');
    const prompt = _cfp || {};
    _cfp = null;
    const decision = approved ? 'approve' : (reason === 'timeout' ? 'timeout' : 'decline');
    try {
      await doFetch('/agent/confirm', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt_id: prompt.promptId, decision: decision })
      });
    } catch (e) { /* fail closed — the agent cancels on its own 30s timeout */ }
    if (typeof prompt.resolve === 'function') prompt.resolve(decision);
    if (!approved) toast(decision === 'timeout' ? 'Risky action timed out — cancelled' : 'Risky action declined');
    return decision;
  }

  // ── Ambiguity / unrecognized prompts (Req 5.4, 5.2) ──
  function agentShowAmbiguity(candidates, onPick) {
    const box = doc.getElementById('ambChoices');
    const msg = doc.getElementById('ambMsg');
    const title = doc.getElementById('ambTitle');
    if (title) title.textContent = '◈ CLARIFY COMMAND';
    if (msg) msg.textContent = 'That could mean a few things — which did you want?';
    if (box) {
      box.innerHTML = '';
      (candidates || []).forEach(function (c, i) {
        const btn = doc.createElement('button');
        btn.className = 'amb-choice';
        btn.type = 'button';
        const conf = (typeof c.confidence === 'number') ? (Math.round(c.confidence * 100) + '%') : '';
        btn.innerHTML = '<span class="amb-conf">' + conf + '</span>' +
          '<div>' + escapeHtml(prettyCommand(c.commandId) || c.commandId || 'Option ' + (i + 1)) + '</div>' +
          '<div class="amb-cid">' + escapeHtml(c.commandId || '') + '</div>';
        btn.onclick = function () { closeAmbiguity(); if (typeof onPick === 'function') onPick(c, i); };
        box.appendChild(btn);
      });
    }
    const ov = doc.getElementById('ambOverlay');
    if (ov) ov.classList.add('open');
  }

  function agentShowUnrecognized(text) {
    const box = doc.getElementById('ambChoices');
    const msg = doc.getElementById('ambMsg');
    const title = doc.getElementById('ambTitle');
    if (title) title.textContent = '◈ COMMAND NOT RECOGNIZED';
    if (msg) msg.textContent = text
      ? ('I couldn\u2019t match \u201C' + text + '\u201D to a desktop action. Try rephrasing.')
      : 'I couldn\u2019t match that to a desktop action. Try rephrasing.';
    if (box) box.innerHTML = '';
    const ov = doc.getElementById('ambOverlay');
    if (ov) ov.classList.add('open');
  }

  function closeAmbiguity() {
    const ov = doc.getElementById('ambOverlay');
    if (ov) ov.classList.remove('open');
  }

  // ── Audit_Log history view (Req 7.5, reverse chronological) ──
  let _localHistory = [];

  function agentRecordLocal(entry) {
    if (!entry) return;
    if (!entry.timestamp) entry.timestamp = new Date().toISOString();
    _localHistory.push(entry);
    const panel = doc.getElementById('auditPanel');
    if (panel && panel.classList.contains('open')) renderHistory(_localHistory);
  }

  async function openAuditHistory() {
    const p = doc.getElementById('auditPanel');
    if (p) p.classList.add('open');
    let entries = null;
    try {
      const r = await doFetch('/agent/history');
      if (r && r.ok) { const d = await r.json(); entries = Array.isArray(d) ? d : (d.entries || null); }
    } catch (e) { /* fall back to locally-observed events */ }
    renderHistory(entries || _localHistory);
  }

  function closeAuditHistory() {
    const p = doc.getElementById('auditPanel');
    if (p) p.classList.remove('open');
  }

  function renderHistory(entries) {
    const body = doc.getElementById('auditBody');
    if (!body) return;
    const list = (entries || []).slice();
    // Reverse chronological: newest first (Req 7.5).
    list.sort(function (a, b) { return tsMs(b.timestamp) - tsMs(a.timestamp); });
    if (!list.length) { body.innerHTML = '<div class="audit-empty">No activity recorded yet.</div>'; return; }
    body.innerHTML = list.map(function (e) {
      const type = e.event_type || 'event';
      const cmd = e.command_id ? prettyCommand(e.command_id) : '';
      const detailBits = [];
      if (e.outcome) detailBits.push('outcome: ' + e.outcome);
      if (e.reason) detailBits.push('reason: ' + e.reason);
      const detail = detailBits.join('  ·  ');
      return '<div class="audit-entry" data-outcome="' + escapeHtml(type) + '">' +
        '<div class="ae-top"><span class="ae-type">' + escapeHtml(type) + '</span>' +
        '<span class="ae-time">' + escapeHtml(fmtTime(e.timestamp)) + '</span></div>' +
        (cmd ? '<div class="ae-cmd">' + escapeHtml(cmd) + '</div>' : '') +
        (detail ? '<div class="ae-detail">' + escapeHtml(detail) + '</div>' : '') +
        '</div>';
    }).join('');
  }

  renderState();

  return {
    setAgentState, getAgentState,
    agentKillSwitch,
    agentShowConfirmation, agentResolveConfirmation,
    agentShowAmbiguity, agentShowUnrecognized, closeAmbiguity,
    agentRecordLocal, openAuditHistory, closeAuditHistory, renderHistory,
    _getLocalHistory: function () { return _localHistory.slice(); }
  };
}
