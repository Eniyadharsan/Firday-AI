/**
 * Feature: multi-provider-ai
 * Property 7: Model Name Abbreviation
 * **Validates: Requirements 8.2**
 *
 * The JS `abbreviateModelName(name)` (public/index.html) must produce a display
 * name of 12 characters or fewer while preserving the model family identifier.
 */

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';
import { abbreviateModelName } from './_provider_ui_snippets.js';

// Family keyword -> the substring that MUST survive into the abbreviated label
// (case-insensitive). e.g. "mixtral" collapses into the "Mistral" family label.
const FAMILIES = [
  { keyword: 'gpt', preserved: 'gpt' },
  { keyword: 'claude', preserved: 'claude' },
  { keyword: 'gemini', preserved: 'gemini' },
  { keyword: 'deepseek', preserved: 'deepseek' },
  { keyword: 'grok', preserved: 'grok' },
  { keyword: 'llama', preserved: 'llama' },
  { keyword: 'mistral', preserved: 'mistral' },
  { keyword: 'mixtral', preserved: 'mistral' },
  { keyword: 'qwen', preserved: 'qwen' },
  { keyword: 'cerebras', preserved: 'cerebras' },
];

// Org/route prefixes that should be stripped and must not affect the family.
const PREFIXES = ['', 'openai/', 'anthropic/', 'google/', 'meta-llama/', 'x-ai/', 'openrouter/'];

// A "safe" suffix alphabet: digits, dot, dash. These never introduce a competing
// family keyword, so the injected family remains the one that matches.
const suffixArb = fc.stringOf(fc.constantFrom(...'0123456789.-'.split('')), { maxLength: 20 });

describe('Property 7: Model Name Abbreviation (Req 8.2)', () => {
  it('output is always 12 characters or fewer for arbitrary input', () => {
    fc.assert(
      fc.property(fc.string(), (name) => {
        const out = abbreviateModelName(name);
        expect(out.length).toBeLessThanOrEqual(12);
      }),
      { numRuns: 500 }
    );
  });

  it('output is 12 chars or fewer AND preserves the family identifier for known families', () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...FAMILIES),
        fc.constantFrom(...PREFIXES),
        suffixArb,
        (fam, prefix, suffix) => {
          const name = prefix + fam.keyword + suffix;
          const out = abbreviateModelName(name);
          // Length invariant.
          expect(out.length).toBeLessThanOrEqual(12);
          // Family identifier preserved (case-insensitive).
          expect(out.toLowerCase()).toContain(fam.preserved);
        }
      ),
      { numRuns: 500 }
    );
  });

  // Representative concrete examples (unit-style anchors for the property).
  it('abbreviates representative real model names correctly', () => {
    expect(abbreviateModelName('openai/gpt-4o')).toBe('GPT-4o');
    expect(abbreviateModelName('gpt-4o-mini')).toBe('GPT-4o');
    expect(abbreviateModelName('claude-3-5-sonnet-20241022')).toBe('Claude-Son');
    expect(abbreviateModelName('claude-3-opus')).toBe('Claude-Opus');
    expect(abbreviateModelName('gemini-1.5-flash')).toBe('Gemini-Fl');
    expect(abbreviateModelName('gemini-1.5-pro')).toBe('Gemini-Pro');
    expect(abbreviateModelName('deepseek-r1')).toBe('DeepSeek-R1');
    expect(abbreviateModelName('meta-llama/llama-3.1-70b')).toBe('Llama');
    expect(abbreviateModelName('mixtral-8x7b')).toBe('Mistral');
    expect(abbreviateModelName('qwen-2.5-72b')).toBe('Qwen');
    expect(abbreviateModelName('cerebras-3b')).toBe('Cerebras');
    // Every one of these is within the 12-char cap.
    for (const label of ['GPT-4o', 'Claude-Son', 'Claude-Opus', 'Gemini-Fl', 'DeepSeek-R1']) {
      expect(label.length).toBeLessThanOrEqual(12);
    }
  });

  it('handles null / empty / whitespace with a placeholder', () => {
    expect(abbreviateModelName(null)).toBe('—');
    expect(abbreviateModelName(undefined)).toBe('—');
    expect(abbreviateModelName('')).toBe('—');
    expect(abbreviateModelName('   ')).toBe('—');
  });
});
