// @vitest-environment jsdom
/**
 * Feature: multi-provider-ai
 * Unit tests for frontend components (task 15.5)
 * **Validates: Requirements 8.3, 8.4, 8.5, 15.4, 15.5**
 *
 * Covers:
 *   - Badge status indicator colors  (providerStatusColor)
 *   - Badge click opens the Model Manager  (#modelBadge onclick, static DOM)
 *   - Provider list display  (renderProviders)
 *   - API key masking / write-only key input  (renderProviders)
 */

import { describe, it, expect, beforeAll, beforeEach } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { JSDOM } from 'jsdom';
import { providerStatusColor, renderProviders } from './_provider_ui_snippets.js';

describe('Badge status indicator colors (Req 8.3)', () => {
  it('maps each provider status to its color', () => {
    expect(providerStatusColor('operational')).toBe('green');
    expect(providerStatusColor('degraded')).toBe('yellow');
    expect(providerStatusColor('unavailable')).toBe('red');
    expect(providerStatusColor('not_configured')).toBe('gray');
  });

  it('is case-insensitive', () => {
    expect(providerStatusColor('OPERATIONAL')).toBe('green');
    expect(providerStatusColor('Degraded')).toBe('yellow');
  });

  it('falls back to gray for unknown / empty / null status', () => {
    expect(providerStatusColor('something-else')).toBe('gray');
    expect(providerStatusColor('')).toBe('gray');
    expect(providerStatusColor(null)).toBe('gray');
    expect(providerStatusColor(undefined)).toBe('gray');
  });
});

describe('Badge click opens Model Manager (Req 8.5)', () => {
  let document;
  beforeAll(() => {
    const htmlPath = resolve(__dirname, '../../public/index.html');
    const html = readFileSync(htmlPath, 'utf-8');
    document = new JSDOM(html).window.document;
  });

  it('#modelBadge exists and is a button', () => {
    const badge = document.querySelector('#modelBadge');
    expect(badge).not.toBeNull();
    expect(badge.tagName.toLowerCase()).toBe('button');
  });

  it('#modelBadge onclick invokes openModelManager()', () => {
    const badge = document.querySelector('#modelBadge');
    expect(badge.getAttribute('onclick')).toBe('openModelManager()');
  });
});

describe('Provider list display (Req 7.1, 7.2, 7.5)', () => {
  let document;
  beforeEach(() => {
    document = new JSDOM('<!DOCTYPE html><div id="mmList"></div>').window.document;
  });

  const providers = [
    {
      name: 'openai', is_configured: true, is_active: true, status: 'operational',
      latency_ms: 250,
      models: [
        { id: 'gpt-4o', name: 'gpt-4o', context_window: 128000 },
        { id: 'gpt-4o-mini', name: 'gpt-4o-mini', context_window: 128000 },
      ],
    },
    {
      name: 'anthropic', is_configured: true, is_active: false, status: 'degraded',
      latency_ms: 900, models: [{ id: 'claude-3-opus', name: 'claude-3-opus', context_window: 200000 }],
    },
    { name: 'grok', is_configured: false, is_active: false, models: [] },
  ];

  it('renders one card per provider with its name', () => {
    renderProviders(document, providers, 'openai', 'gpt-4o');
    const cards = document.querySelectorAll('.mm-provider');
    expect(cards.length).toBe(3);
    const names = [...document.querySelectorAll('.mm-prov-name')].map((el) => el.textContent);
    expect(names).toEqual(['openai', 'anthropic', 'grok']);
  });

  it('color-codes each provider dot from its status', () => {
    renderProviders(document, providers, 'openai', 'gpt-4o');
    const dots = document.querySelectorAll('.mm-dot');
    expect(dots[0].className).toContain('green');  // operational
    expect(dots[1].className).toContain('yellow'); // degraded
    expect(dots[2].className).toContain('gray');   // not configured
  });

  it('marks the active provider and selected model', () => {
    renderProviders(document, providers, 'openai', 'gpt-4o');
    const active = document.querySelector('.mm-provider.active');
    expect(active).not.toBeNull();
    expect(active.querySelector('.mm-prov-name').textContent).toBe('openai');
    expect(active.querySelector('.mm-badge-active')).not.toBeNull();
    const selected = document.querySelector('.mm-model.selected');
    expect(selected.getAttribute('data-model')).toBe('gpt-4o');
  });

  it('lists models with formatted context window', () => {
    renderProviders(document, providers, 'openai', 'gpt-4o');
    const models = document.querySelectorAll('.mm-provider .mm-model');
    expect(models.length).toBe(3); // 2 openai + 1 anthropic
    const ctx = [...document.querySelectorAll('.mm-model .cw')].map((el) => el.textContent);
    expect(ctx).toContain('128K ctx');
    expect(ctx).toContain('200K ctx');
  });

  it('renders an empty-state message when no providers registered', () => {
    renderProviders(document, [], null, null);
    expect(document.getElementById('mmList').textContent).toContain('No providers registered');
  });
});

describe('API key masking / write-only key input (Req 7.3)', () => {
  let document;
  beforeEach(() => {
    document = new JSDOM('<!DOCTYPE html><div id="mmList"></div>').window.document;
  });

  it('uses a password (masked) input for every API key field', () => {
    const providers = [
      { name: 'openai', is_configured: true, models: [] },
      { name: 'grok', is_configured: false, models: [] },
    ];
    renderProviders(document, providers, null, null);
    const inputs = document.querySelectorAll('[data-key-input]');
    expect(inputs.length).toBe(2);
    inputs.forEach((inp) => {
      expect(inp.getAttribute('type')).toBe('password');
      // Write-only: never pre-filled with a stored value.
      expect(inp.value).toBe('');
      expect(inp.hasAttribute('value')).toBe(false);
      expect(inp.getAttribute('autocomplete')).toBe('off');
    });
  });

  it('shows a CONFIGURED state (never the key) for configured providers', () => {
    renderProviders(document, [{ name: 'openai', is_configured: true, models: [] }], null, null);
    const html = document.getElementById('mmList').innerHTML;
    expect(html).toContain('CONFIGURED');
    expect(html).toContain('data-replace="openai"'); // replace toggle offered
    // The masked replace field starts hidden.
    const wrap = document.querySelector('[data-keywrap="openai"]');
    expect(wrap.getAttribute('style')).toContain('display:none');
  });

  it('shows a NOT SET state with a visible key field for unconfigured providers', () => {
    renderProviders(document, [{ name: 'grok', is_configured: false, models: [] }], null, null);
    const html = document.getElementById('mmList').innerHTML;
    expect(html).toContain('NOT SET');
    const wrap = document.querySelector('[data-keywrap="grok"]');
    // Not hidden for an unconfigured provider (needs a key).
    expect(wrap.getAttribute('style') || '').not.toContain('display:none');
  });

  it('never renders any raw key material into the DOM', () => {
    // Even if an (incorrect) api_key field were present on the provider object,
    // the renderer must not emit it.
    const providers = [{ name: 'openai', is_configured: true, api_key: 'sk-SECRET-123', models: [] }];
    renderProviders(document, providers, null, null);
    expect(document.getElementById('mmList').innerHTML).not.toContain('sk-SECRET-123');
  });
});
