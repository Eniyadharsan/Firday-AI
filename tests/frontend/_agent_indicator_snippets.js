/**
 * Ported UI logic for the FRIDAY Desktop Agent "Active_Indicator" state machine.
 *
 * ⚠ SYNC NOTE: This mirrors the inline <script> in `public/index.html` VERBATIM
 * (behaviour-for-behaviour). It is duplicated here only so the DOM-manipulating
 * state-machine logic can be property / unit tested outside a live browser.
 * If you change the originals in index.html, update these too.
 *
 * Source in public/index.html:
 *   - const AGENT_VIEW = { ... }        (Req 9.1-9.4 — state → distinct glyph+text+aria+colour)
 *   - window.setAgentState(state)       (state push from the agent, rejects unknown states)
 *   - renderState()                     (writes data-state / glyph / text / aria-label)
 */

// ── Active_Indicator state machine (Req 9.1-9.4) ──
// Each state maps to a distinct glyph + text + colour (via data-state CSS).
export const AGENT_VIEW = {
  enabled:   { glyph: '▶', text: 'AGENT ACTIVE',    aria: 'Desktop agent status: enabled' },
  observing: { glyph: '◉', text: 'OBSERVING SCREEN', aria: 'Desktop agent status: observing screen' },
  disabled:  { glyph: '■', text: 'AGENT OFF',        aria: 'Desktop agent status: disabled' }
};

/**
 * Wire the Active_Indicator state machine to a given document. The original
 * index.html closes over the global `document` and a module-level `agentState`;
 * here we pass the document in explicitly so the render output can be asserted.
 */
export function createAgentIndicator(doc) {
  let agentState = 'disabled';

  function renderState() {
    const ind = doc.getElementById('agentIndicator');
    if (!ind) return;
    const v = AGENT_VIEW[agentState] || AGENT_VIEW.disabled;
    ind.setAttribute('data-state', agentState);
    ind.setAttribute('aria-label', v.aria);
    const g = doc.getElementById('agentGlyph'); if (g) g.textContent = v.glyph;
    const t = doc.getElementById('agentText');  if (t) t.textContent = v.text;
    const kill = doc.getElementById('agentKill');
    // Kill switch is only actionable while the agent can still act.
    if (kill) kill.disabled = (agentState === 'disabled');
  }

  // Public: set the visible agent state (called by state pushes from the agent).
  function setAgentState(state) {
    // Reject unknown states — use hasOwnProperty so inherited Object keys
    // (e.g. "toString", "constructor") can't slip past the guard (fail closed).
    if (!Object.prototype.hasOwnProperty.call(AGENT_VIEW, state)) return;
    agentState = state;
    renderState();
  }
  function getAgentState() { return agentState; }

  return { setAgentState, getAgentState, renderState };
}
