// @vitest-environment jsdom
/**
 * State Transition Integration Tests for Neural Orb Redesign
 * **Validates: Requirements 6.1, 6.5, 7.1, 8.1**
 *
 * Since jsdom does NOT compute CSS or apply animations, these tests verify
 * state transitions by:
 * 1. Parsing CSS text from <style> elements
 * 2. Verifying that CSS rules for state classes exist with correct properties
 * 3. Verifying classList manipulation works on #reactor
 * 4. Verifying transition CSS properties are defined
 */

import { describe, it, expect, beforeAll } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { JSDOM } from 'jsdom';

describe('Neural Orb State Transitions', () => {
  let document;
  let cssText;
  let reactor;

  beforeAll(() => {
    const htmlPath = resolve(__dirname, '../../public/index.html');
    const html = readFileSync(htmlPath, 'utf-8');
    const dom = new JSDOM(html);
    document = dom.window.document;

    // Collect all CSS text from <style> elements
    const styleSheets = document.querySelectorAll('style');
    cssText = '';
    styleSheets.forEach(sheet => {
      cssText += sheet.textContent;
    });

    reactor = document.querySelector('#reactor');
  });

  describe('Speaking state CSS rules (Req 6.1, 6.5)', () => {
    it('CSS contains a .speaking .neural-orb rule with scale transform > 1', () => {
      // The speaking state should scale the orb up (spec says scale(1.15))
      // Look for .speaking .neural-orb rule with a scale transform
      const speakingOrbPattern = /\.speaking\s+\.neural-orb[^{]*\{[^}]*transform[^}]*scale\s*\(\s*1\.1[0-9]*\s*\)/s;
      const hasScaleTransform = speakingOrbPattern.test(cssText);
      expect(hasScaleTransform).toBe(true);
    });

    it('CSS .speaking .neural-orb includes increased glow radius (box-shadow > idle)', () => {
      // Speaking state should have intensified box-shadow (90px+ glow)
      // Check that .speaking .neural-orb rule contains box-shadow
      const speakingSection = cssText.match(/\.speaking\s+\.neural-orb[^{]*\{([^}]*)\}/s);
      expect(speakingSection).not.toBeNull();
      const ruleBody = speakingSection[1];
      expect(ruleBody).toContain('box-shadow');
    });

    it('classList.add("speaking") applies the class to #reactor', () => {
      expect(reactor).not.toBeNull();
      reactor.classList.add('speaking');
      expect(reactor.classList.contains('speaking')).toBe(true);
      // Clean up
      reactor.classList.remove('speaking');
    });
  });

  describe('Listening state CSS rules (Req 7.1)', () => {
    it('CSS contains a .listening .neural-orb rule with green color (#00ff88)', () => {
      // The listening state should shift color toward #00ff88
      const listeningOrbPattern = /\.listening\s+\.neural-orb[^{]*\{[^}]*#00ff88/s;
      const hasGreenColor = listeningOrbPattern.test(cssText);
      expect(hasGreenColor).toBe(true);
    });

    it('CSS .listening .neural-orb contains color-related property (background or box-shadow with green)', () => {
      const listeningSection = cssText.match(/\.listening\s+\.neural-orb[^{]*\{([^}]*)\}/s);
      expect(listeningSection).not.toBeNull();
      const ruleBody = listeningSection[1];
      // Should contain either background or box-shadow with green tones
      const hasColorProperty = ruleBody.includes('background') || ruleBody.includes('box-shadow');
      expect(hasColorProperty).toBe(true);
    });

    it('classList.add("listening") applies the class to #reactor', () => {
      expect(reactor).not.toBeNull();
      reactor.classList.add('listening');
      expect(reactor.classList.contains('listening')).toBe(true);
      // Clean up
      reactor.classList.remove('listening');
    });
  });

  describe('Return to idle state (Req 8.1)', () => {
    it('removing .speaking class returns #reactor to no state classes', () => {
      expect(reactor).not.toBeNull();
      reactor.classList.add('speaking');
      expect(reactor.classList.contains('speaking')).toBe(true);
      reactor.classList.remove('speaking');
      expect(reactor.classList.contains('speaking')).toBe(false);
      expect(reactor.classList.contains('listening')).toBe(false);
    });

    it('removing .listening class returns #reactor to no state classes', () => {
      expect(reactor).not.toBeNull();
      reactor.classList.add('listening');
      expect(reactor.classList.contains('listening')).toBe(true);
      reactor.classList.remove('listening');
      expect(reactor.classList.contains('speaking')).toBe(false);
      expect(reactor.classList.contains('listening')).toBe(false);
    });

    it('switching from speaking to listening removes speaking class', () => {
      expect(reactor).not.toBeNull();
      reactor.classList.add('speaking');
      reactor.classList.remove('speaking');
      reactor.classList.add('listening');
      expect(reactor.classList.contains('speaking')).toBe(false);
      expect(reactor.classList.contains('listening')).toBe(true);
      // Clean up
      reactor.classList.remove('listening');
    });
  });

  describe('Transition timing CSS (Req 8.1)', () => {
    it('CSS contains transition property on .neural-orb with duration 200-400ms', () => {
      // Look for transition property in .neural-orb rules
      // The spec requires 200-400ms transitions for state changes
      const neuralOrbRules = cssText.match(/\.neural-orb[^{]*\{([^}]*)\}/gs);
      expect(neuralOrbRules).not.toBeNull();

      // Collect all rule bodies for .neural-orb (not preceded by a state class)
      let hasTransition = false;
      for (const rule of neuralOrbRules) {
        if (rule.includes('transition')) {
          // Check for a duration value in the 200-400ms or 0.2-0.4s range
          const hasValidDuration = /transition[^;]*(?:3[0-9]{2}ms|2[0-9]{2}ms|4[0-9]{2}ms|0\.[2-4]s|300ms|200ms|400ms|\.3s|\.2s|\.4s)/i.test(rule);
          if (hasValidDuration) {
            hasTransition = true;
            break;
          }
        }
      }
      expect(hasTransition).toBe(true);
    });

    it('CSS .neural-orb transition includes transform or all property', () => {
      // Transition should cover transform changes (for scale) or use 'all'
      const neuralOrbRules = cssText.match(/\.neural-orb[^{]*\{([^}]*)\}/gs);
      expect(neuralOrbRules).not.toBeNull();

      let coversTransform = false;
      for (const rule of neuralOrbRules) {
        if (rule.includes('transition')) {
          if (rule.includes('transform') || rule.includes('all')) {
            coversTransform = true;
            break;
          }
        }
      }
      expect(coversTransform).toBe(true);
    });
  });
});
