// @vitest-environment jsdom
// Feature: friday-desktop-agent, Property 21: State maps to a distinct indicator
/**
 * Property test for the Desktop Agent Active_Indicator state-to-indicator mapping.
 * **Validates: Requirements 9.1, 9.2, 9.3, 10.6**
 *
 * Property 21: For any Desktop_Agent state (enabled, observing, disabled), the
 * Active_Indicator shows the DISTINCT visible state corresponding to that agent
 * state. State is conveyed by data-state (colour), glyph, and text so it never
 * relies on colour alone — each of those visible facets must be distinct per state.
 *
 * Uses the real Active_Indicator markup from public/index.html plus the state
 * machine logic mirrored verbatim in _agent_indicator_snippets.js.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import fc from 'fast-check';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { JSDOM } from 'jsdom';
import { AGENT_VIEW, createAgentIndicator } from './_agent_indicator_snippets.js';

const VALID_STATES = ['enabled', 'observing', 'disabled'];

function loadIndicatorDoc() {
  const htmlPath = resolve(__dirname, '../../public/index.html');
  const html = readFileSync(htmlPath, 'utf-8');
  const dom = new JSDOM(html); // scripts NOT executed; we wire the mirrored logic
  return dom.window.document;
}

// Read the visible facets the user (and assistive tech) perceives for the indicator.
function readIndicatorView(doc) {
  const ind = doc.getElementById('agentIndicator');
  return {
    dataState: ind.getAttribute('data-state'),
    aria: ind.getAttribute('aria-label'),
    glyph: doc.getElementById('agentGlyph').textContent,
    text: doc.getElementById('agentText').textContent,
  };
}

describe('Property 21: Active_Indicator state maps to a distinct indicator', () => {
  let doc;
  let agent;

  beforeEach(() => {
    doc = loadIndicatorDoc();
    agent = createAgentIndicator(doc);
  });

  it('the real markup contains the Active_Indicator and its facet elements', () => {
    expect(doc.getElementById('agentIndicator')).not.toBeNull();
    expect(doc.getElementById('agentGlyph')).not.toBeNull();
    expect(doc.getElementById('agentText')).not.toBeNull();
  });

  // Core property: for ANY valid state, the indicator shows THAT state's distinct view.
  it('for any valid agent state, the indicator reflects that exact distinct view', () => {
    fc.assert(
      fc.property(fc.constantFrom(...VALID_STATES), (state) => {
        agent.setAgentState(state);
        const view = readIndicatorView(doc);
        const expected = AGENT_VIEW[state];
        // The visible state (colour via data-state, glyph, text, aria) all correspond
        // to the agent state that was set (Req 9.1 enabled, 9.2 observing/10.6, 9.3 disabled).
        expect(view.dataState).toBe(state);
        expect(view.glyph).toBe(expected.glyph);
        expect(view.text).toBe(expected.text);
        expect(view.aria).toBe(expected.aria);
      }),
      { numRuns: 200 }
    );
  });

  // Distinctness property: any two DIFFERENT valid states yield a distinct visible
  // indicator on every facet (colour/data-state, glyph, and text).
  it('for any two different valid states, the visible indicators are distinct', () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...VALID_STATES),
        fc.constantFrom(...VALID_STATES),
        (a, b) => {
          fc.pre(a !== b);
          const docA = loadIndicatorDoc();
          createAgentIndicator(docA).setAgentState(a);
          const viewA = readIndicatorView(docA);

          const docB = loadIndicatorDoc();
          createAgentIndicator(docB).setAgentState(b);
          const viewB = readIndicatorView(docB);

          // Distinct on every user-perceivable facet — never relies on colour alone.
          expect(viewA.dataState).not.toBe(viewB.dataState);
          expect(viewA.glyph).not.toBe(viewB.glyph);
          expect(viewA.text).not.toBe(viewB.text);
          expect(viewA.aria).not.toBe(viewB.aria);
        }
      ),
      { numRuns: 200 }
    );
  });

  // Robustness: for ANY invalid/unknown state input, setAgentState is a no-op and the
  // indicator remains on a valid, distinct state (fail-closed, never a blank/unknown view).
  it('for any invalid state input, the indicator stays on a valid distinct state', () => {
    fc.assert(
      fc.property(fc.string(), (garbage) => {
        fc.pre(!VALID_STATES.includes(garbage));
        // Start from a known valid state, then attempt an invalid transition.
        agent.setAgentState('enabled');
        agent.setAgentState(garbage);
        const view = readIndicatorView(doc);
        // Unknown input rejected: state unchanged and still a valid distinct view.
        expect(agent.getAgentState()).toBe('enabled');
        expect(view.dataState).toBe('enabled');
        expect(view.glyph).toBe(AGENT_VIEW.enabled.glyph);
        expect(view.text).toBe(AGENT_VIEW.enabled.text);
      }),
      { numRuns: 200 }
    );
  });
});
