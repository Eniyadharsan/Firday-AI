// @vitest-environment jsdom
/**
 * DOM Structure Tests for Neural Orb Redesign
 * **Validates: Requirements 4.1, 4.5, 3.1, 9.1, 9.4, 12.1, 12.3, 12.4**
 *
 * These tests load public/index.html and verify the neural orb DOM structure
 * matches the spec requirements.
 */

import { describe, it, expect, beforeAll } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { JSDOM } from 'jsdom';

describe('Neural Orb DOM Structure', () => {
  let document;

  beforeAll(() => {
    const htmlPath = resolve(__dirname, '../../public/index.html');
    const html = readFileSync(htmlPath, 'utf-8');
    const dom = new JSDOM(html);
    document = dom.window.document;
  });

  describe('Reactor element (Req 9.1, 12.3, 12.4)', () => {
    it('#reactor element exists', () => {
      const reactor = document.querySelector('#reactor');
      expect(reactor).not.toBeNull();
    });

    it('#reactor has onclick="handleOrb()"', () => {
      const reactor = document.querySelector('#reactor');
      expect(reactor).not.toBeNull();
      const onclick = reactor.getAttribute('onclick');
      expect(onclick).toBe('handleOrb()');
    });
  });

  describe('Neural orb core elements (Req 12.1, 12.3)', () => {
    it('.neural-orb element is present', () => {
      const neuralOrb = document.querySelector('.neural-orb');
      expect(neuralOrb).not.toBeNull();
    });

    it('.neural-connections element is present', () => {
      const connections = document.querySelector('.neural-connections');
      expect(connections).not.toBeNull();
    });

    it('.particle-system element is present', () => {
      const particleSystem = document.querySelector('.particle-system');
      expect(particleSystem).not.toBeNull();
    });
  });

  describe('Particle system (Req 4.1)', () => {
    it('at least 15 .particle elements exist', () => {
      const particles = document.querySelectorAll('.particle');
      expect(particles.length).toBeGreaterThanOrEqual(15);
    });
  });

  describe('Neural connections (Req 3.1)', () => {
    it('at least 6 .connection elements exist', () => {
      const connections = document.querySelectorAll('.connection');
      expect(connections.length).toBeGreaterThanOrEqual(6);
    });
  });

  describe('Sub-label (Req 9.4)', () => {
    it('.sub-label contains "TAP TO TALK"', () => {
      const subLabel = document.querySelector('.sub-label');
      expect(subLabel).not.toBeNull();
      expect(subLabel.textContent).toContain('TAP TO TALK');
    });
  });

  describe('Pointer events (Req 4.5, 3.1)', () => {
    it('.particle-system has pointer-events: none in inline style or class', () => {
      const particleSystem = document.querySelector('.particle-system');
      expect(particleSystem).not.toBeNull();
      // Check via computed styles from the embedded stylesheet
      // Since jsdom doesn't compute CSS, we verify the style attribute or rely on
      // the CSS rule existing in the document's stylesheet
      const styleSheets = document.querySelectorAll('style');
      let cssText = '';
      styleSheets.forEach(sheet => {
        cssText += sheet.textContent;
      });
      const hasParticleSystemPointerNone = cssText.includes('.particle-system') &&
        cssText.includes('pointer-events') &&
        (cssText.includes('pointer-events:none') || cssText.includes('pointer-events: none'));
      expect(hasParticleSystemPointerNone).toBe(true);
    });

    it('.neural-connections has pointer-events: none in CSS', () => {
      const connections = document.querySelector('.neural-connections');
      expect(connections).not.toBeNull();
      const styleSheets = document.querySelectorAll('style');
      let cssText = '';
      styleSheets.forEach(sheet => {
        cssText += sheet.textContent;
      });
      const hasConnectionsPointerNone = cssText.includes('.neural-connections') &&
        cssText.includes('pointer-events') &&
        (cssText.includes('pointer-events:none') || cssText.includes('pointer-events: none'));
      expect(hasConnectionsPointerNone).toBe(true);
    });
  });
});
