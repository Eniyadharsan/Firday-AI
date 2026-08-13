// @vitest-environment jsdom
/**
 * Feature: multi-provider-ai
 * Unit tests for failover UI (task 16.3)
 * **Validates: Requirements 9.3, 9.6**
 *
 * Covers:
 *   - Badge updates on failover        (setModelBadge with failover state)
 *   - Restore notification display     (showPrimaryRestorePrompt)
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { JSDOM } from 'jsdom';
import { setModelBadge, showPrimaryRestorePrompt } from './_provider_ui_snippets.js';

const BADGE_HTML = `<!DOCTYPE html><body>
  <button class="model-badge" id="modelBadge" style="display:none">
    <span class="model-badge-dot gray" id="modelBadgeDot"></span>
    <span class="model-badge-name" id="modelBadgeName">—</span>
  </button>
</body>`;

describe('Badge updates on failover (Req 9.3)', () => {
  let document;
  beforeEach(() => {
    document = new JSDOM(BADGE_HTML).window.document;
  });

  it('adds the failover marker class and names the fallen-over primary when in failover', () => {
    setModelBadge(
      document, 'llama-3.1-70b', 'green', 'operational', 'cerebras',
      { in_failover: true, primary: 'openai/gpt-4o' }
    );
    const badge = document.getElementById('modelBadge');
    expect(badge.classList.contains('failover')).toBe(true);
    expect(badge.style.display).toBe('');
    // Title communicates backup + failover + the abbreviated primary.
    expect(badge.title).toContain('backup');
    expect(badge.title).toContain('failover active');
    expect(badge.title).toContain('GPT-4o'); // abbreviated primary
    // Name shows the current (backup) model, abbreviated.
    expect(document.getElementById('modelBadgeName').textContent).toBe('Llama');
    // Dot reflects the current provider color.
    expect(document.getElementById('modelBadgeDot').className).toContain('green');
  });

  it('removes the failover marker when not in failover', () => {
    const badge = document.getElementById('modelBadge');
    // First put it into failover...
    setModelBadge(document, 'llama', 'green', 'operational', 'cerebras', { in_failover: true, primary: 'openai' });
    expect(badge.classList.contains('failover')).toBe(true);
    // ...then a normal (non-failover) refresh clears it.
    setModelBadge(document, 'gpt-4o', 'green', 'operational', 'openai', { in_failover: false });
    expect(badge.classList.contains('failover')).toBe(false);
    expect(badge.title).toContain('operational');
    expect(badge.title).not.toContain('failover active');
  });

  it('handles a missing failover object as a normal badge', () => {
    setModelBadge(document, 'gpt-4o', 'green', 'operational', 'openai', null);
    const badge = document.getElementById('modelBadge');
    expect(badge.classList.contains('failover')).toBe(false);
    expect(badge.title).toContain('openai');
  });

  it('falls back to "primary" text when the primary name is unknown', () => {
    setModelBadge(document, 'llama', 'yellow', 'degraded', 'cerebras', { in_failover: true });
    expect(document.getElementById('modelBadge').title).toContain('primary');
  });
});

describe('Restore notification display (Req 9.6)', () => {
  let document;
  beforeEach(() => {
    document = new JSDOM('<!DOCTYPE html><body></body>').window.document;
  });

  it('renders a restore toast with a message and Switch back / Keep backup actions', () => {
    showPrimaryRestorePrompt(document, { provider: 'openai' });
    const toast = document.querySelector('.fri-toast.action.restore');
    expect(toast).not.toBeNull();
    expect(toast.querySelector('.fri-toast-msg').textContent).toContain('openai');
    const btnLabels = [...toast.querySelectorAll('button')].map((b) => b.textContent);
    expect(btnLabels).toContain('Switch back');
    expect(btnLabels).toContain('Keep backup');
  });

  it('uses a custom message when provided', () => {
    showPrimaryRestorePrompt(document, { provider: 'openai', message: 'Primary is back online.' });
    expect(document.querySelector('.fri-toast-msg').textContent).toBe('Primary is back online.');
  });

  it('does nothing when no provider is supplied', () => {
    const result = showPrimaryRestorePrompt(document, {});
    expect(result).toBeUndefined();
    expect(document.querySelector('.fri-toast.restore')).toBeNull();
  });

  it('replaces any existing restore toast (no duplicates)', () => {
    showPrimaryRestorePrompt(document, { provider: 'openai' });
    showPrimaryRestorePrompt(document, { provider: 'openai' });
    expect(document.querySelectorAll('.fri-toast.action.restore').length).toBe(1);
  });

  it('"Switch back" invokes the switch callback with the provider, "Keep backup" dismisses', () => {
    let switched = null;
    const toast = showPrimaryRestorePrompt(document, { provider: 'openai' }, (p) => { switched = p; });
    const buttons = [...toast.querySelectorAll('button')];
    const switchBtn = buttons.find((b) => b.textContent === 'Switch back');
    const keepBtn = buttons.find((b) => b.textContent === 'Keep backup');

    switchBtn.click();
    expect(switched).toBe('openai');
    expect(switchBtn.disabled).toBe(true);

    // Dismiss removes the toast from the DOM.
    keepBtn.click();
    expect(document.querySelector('.fri-toast.action.restore')).toBeNull();
  });
});
