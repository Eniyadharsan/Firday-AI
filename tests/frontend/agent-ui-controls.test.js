// @vitest-environment jsdom
/**
 * Feature: friday-desktop-agent
 * Frontend tests for the Desktop Agent UI controls (task 15.3).
 * **Validates: Requirements 6.1, 8.1, 5.4, 7.5**
 *
 * Covers:
 *   - Kill_Switch dispatch                 (Req 8.1)
 *   - Confirmation_Prompt approve/decline  (Req 6.1)
 *   - Ambiguity candidate rendering        (Req 5.4)
 *   - History newest-first rendering       (Req 7.5)
 *
 * Logic is ported verbatim from public/index.html into _agent_ui_snippets.js.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { JSDOM } from 'jsdom';
import { createAgentUI, prettyCommand } from './_agent_ui_snippets.js';

// Minimal markup mirroring the agent controls in public/index.html.
const AGENT_HTML = `<!DOCTYPE html><body>
  <div class="active-indicator" id="agentIndicator" data-state="disabled">
    <span class="ai-dot"></span>
    <span class="ai-glyph" id="agentGlyph">■</span>
    <span class="ai-text" id="agentText">AGENT OFF</span>
    <button class="agent-kill" id="agentKill" disabled>KILL</button>
  </div>

  <div class="cfp-overlay" id="cfpOverlay">
    <div class="cfp-panel">
      <div class="cfp-cmd" id="cfpCmd">—</div>
      <pre class="cfp-params" id="cfpParams" style="display:none"></pre>
      <div class="cfp-timer" id="cfpTimer"></div>
    </div>
  </div>

  <div class="amb-overlay" id="ambOverlay">
    <div class="amb-title" id="ambTitle"></div>
    <div class="amb-msg" id="ambMsg"></div>
    <div class="amb-choices" id="ambChoices"></div>
  </div>

  <div class="audit-panel" id="auditPanel">
    <div class="audit-body" id="auditBody"></div>
  </div>
</body>`;

function newDoc() {
  return new JSDOM(AGENT_HTML).window.document;
}

// ── Kill_Switch dispatch (Req 8.1) ──────────────────────────────────────────
describe('Kill_Switch dispatch (Req 8.1)', () => {
  let document, fetchMock, toastMock, ui;
  beforeEach(() => {
    document = newDoc();
    fetchMock = vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }));
    toastMock = vi.fn();
    ui = createAgentUI(document, { fetch: fetchMock, toast: toastMock });
    ui.setAgentState('enabled');
  });

  it('immediately reflects the disabled state in the indicator', async () => {
    expect(ui.getAgentState()).toBe('enabled');
    await ui.agentKillSwitch();
    expect(ui.getAgentState()).toBe('disabled');
    expect(document.getElementById('agentIndicator').getAttribute('data-state')).toBe('disabled');
    expect(document.getElementById('agentText').textContent).toBe('AGENT OFF');
    // Kill button becomes non-actionable once disabled.
    expect(document.getElementById('agentKill').disabled).toBe(true);
  });

  it('dispatches the disable action to the agent kill-switch endpoint', async () => {
    await ui.agentKillSwitch();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/agent/kill-switch');
    expect(init.method).toBe('POST');
  });

  it('records the kill-switch activation in local history', async () => {
    await ui.agentKillSwitch();
    const hist = ui._getLocalHistory();
    expect(hist.length).toBe(1);
    expect(hist[0].event_type).toBe('kill_switch');
    expect(hist[0].reason).toBe('user_activated');
    expect(hist[0].timestamp).toBeTruthy();
  });

  it('fails closed: still shows disabled even if the dispatch rejects', async () => {
    fetchMock.mockImplementation(() => Promise.reject(new Error('network down')));
    await ui.agentKillSwitch();
    expect(ui.getAgentState()).toBe('disabled');
  });
});

// ── Confirmation_Prompt approve/decline (Req 6.1) ───────────────────────────
describe('Confirmation_Prompt approve/decline (Req 6.1)', () => {
  let document, fetchMock, ui;
  beforeEach(() => {
    document = newDoc();
    fetchMock = vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }));
    ui = createAgentUI(document, { fetch: fetchMock });
  });

  it('opens the prompt and renders the risky command + parameters', () => {
    ui.agentShowConfirmation({ promptId: 'p1', commandId: 'lock_pc', parameters: { scope: 'session' } });
    expect(document.getElementById('cfpOverlay').classList.contains('open')).toBe(true);
    expect(document.getElementById('cfpCmd').textContent).toBe(prettyCommand('lock_pc'));
    const params = document.getElementById('cfpParams');
    expect(params.style.display).toBe('block');
    expect(params.textContent).toContain('session');
  });

  it('approve resolves with "approve", closes the prompt, and posts the decision', async () => {
    const pending = ui.agentShowConfirmation({ promptId: 'p1', commandId: 'lock_pc' });
    const decision = await ui.agentResolveConfirmation(true);
    expect(decision).toBe('approve');
    expect(await pending).toBe('approve');
    expect(document.getElementById('cfpOverlay').classList.contains('open')).toBe(false);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/agent/confirm');
    const sent = JSON.parse(init.body);
    expect(sent.prompt_id).toBe('p1');
    expect(sent.decision).toBe('approve');
  });

  it('decline resolves with "decline", closes the prompt, and posts the decision', async () => {
    const pending = ui.agentShowConfirmation({ promptId: 'p2', commandId: 'lock_pc' });
    const decision = await ui.agentResolveConfirmation(false);
    expect(decision).toBe('decline');
    expect(await pending).toBe('decline');
    expect(document.getElementById('cfpOverlay').classList.contains('open')).toBe(false);
    const sent = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(sent.decision).toBe('decline');
  });

  it('a no-response timeout resolves with "timeout" (still not an approval)', async () => {
    const pending = ui.agentShowConfirmation({ promptId: 'p3', commandId: 'lock_pc' });
    const decision = await ui.agentResolveConfirmation(false, 'timeout');
    expect(decision).toBe('timeout');
    expect(await pending).toBe('timeout');
    const sent = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(sent.decision).toBe('timeout');
  });
});

// ── Ambiguity candidate rendering (Req 5.4) ─────────────────────────────────
describe('Ambiguity candidate rendering (Req 5.4)', () => {
  let document, ui;
  beforeEach(() => {
    document = newDoc();
    ui = createAgentUI(document, {});
  });

  it('renders one selectable choice per candidate with its command label', () => {
    const candidates = [
      { commandId: 'launch_app', parameters: { app: 'chrome' }, confidence: 0.72 },
      { commandId: 'web_search', parameters: { query: 'chrome' }, confidence: 0.68 }
    ];
    ui.agentShowAmbiguity(candidates, () => {});
    expect(document.getElementById('ambOverlay').classList.contains('open')).toBe(true);
    const choices = document.querySelectorAll('#ambChoices .amb-choice');
    expect(choices.length).toBe(2);
    expect(choices[0].textContent).toContain('Launch application');
    expect(choices[0].textContent).toContain('72%');
    expect(choices[1].textContent).toContain('Web search');
  });

  it('invokes the onPick callback with the chosen candidate and index', () => {
    const candidates = [
      { commandId: 'launch_app', confidence: 0.72 },
      { commandId: 'web_search', confidence: 0.68 }
    ];
    const onPick = vi.fn();
    ui.agentShowAmbiguity(candidates, onPick);
    document.querySelectorAll('#ambChoices .amb-choice')[1].click();
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick.mock.calls[0][0]).toEqual(candidates[1]);
    expect(onPick.mock.calls[0][1]).toBe(1);
    // Picking a candidate closes the prompt.
    expect(document.getElementById('ambOverlay').classList.contains('open')).toBe(false);
  });

  it('re-rendering replaces prior candidates (no stale choices)', () => {
    ui.agentShowAmbiguity([{ commandId: 'launch_app', confidence: 0.5 }], () => {});
    ui.agentShowAmbiguity([
      { commandId: 'media_control', confidence: 0.5 },
      { commandId: 'window_management', confidence: 0.5 }
    ], () => {});
    const choices = document.querySelectorAll('#ambChoices .amb-choice');
    expect(choices.length).toBe(2);
    expect(document.getElementById('ambChoices').textContent).not.toContain('Launch application');
  });
});

// ── History newest-first rendering (Req 7.5) ────────────────────────────────
describe('History newest-first rendering (Req 7.5)', () => {
  let document, ui;
  beforeEach(() => {
    document = newDoc();
    ui = createAgentUI(document, {});
  });

  it('renders audit entries ordered newest timestamp first', () => {
    const entries = [
      { event_type: 'execute', command_id: 'launch_app', outcome: 'success', timestamp: '2024-01-01T10:00:00Z' },
      { event_type: 'kill_switch', reason: 'user_activated', timestamp: '2024-01-01T12:00:00Z' },
      { event_type: 'decline', command_id: 'lock_pc', reason: 'declined', timestamp: '2024-01-01T11:00:00Z' }
    ];
    ui.renderHistory(entries);
    const types = [...document.querySelectorAll('#auditBody .ae-type')].map(e => e.textContent);
    expect(types).toEqual(['kill_switch', 'decline', 'execute']);
  });

  it('newest-first ordering holds regardless of input order', () => {
    const entries = [
      { event_type: 'a', timestamp: '2024-03-03T00:00:00Z' },
      { event_type: 'b', timestamp: '2024-01-01T00:00:00Z' },
      { event_type: 'c', timestamp: '2024-02-02T00:00:00Z' }
    ];
    ui.renderHistory(entries);
    const times = [...document.querySelectorAll('#auditBody .audit-entry')].map(e => e.querySelector('.ae-type').textContent);
    expect(times).toEqual(['a', 'c', 'b']);
  });

  it('renders an empty-state message when there are no entries', () => {
    ui.renderHistory([]);
    expect(document.getElementById('auditBody').textContent).toContain('No activity recorded yet');
  });

  it('shows locally-recorded events newest-first once the panel is open', () => {
    document.getElementById('auditPanel').classList.add('open');
    ui.agentRecordLocal({ event_type: 'execute', command_id: 'web_search', timestamp: '2024-01-01T09:00:00Z' });
    ui.agentRecordLocal({ event_type: 'kill_switch', timestamp: '2024-01-01T09:30:00Z' });
    const types = [...document.querySelectorAll('#auditBody .ae-type')].map(e => e.textContent);
    expect(types[0]).toBe('kill_switch');
  });
});
