# Implementation Plan: Neural Orb Redesign

## Overview

Replace the current molecular/orbiting-electron orb structure in `public/index.html` with a neural-core aesthetic featuring a fiery blue plasma sphere, neural network connections, synapse firing patterns, particle trails, and cosmic energy emissions. The implementation is purely front-end (CSS animations, HTML restructuring, minimal JS class management adjustments) within the existing `.center` container.

## Tasks

- [x] 1. Define CSS custom properties and keyframe animations
  - [x] 1.1 Add CSS design tokens and keyframe definitions
    - Add `:root` custom properties for orb colors, sizes, glow radii, and transition timings
    - Define `@keyframes orbBreathe` for the slow scale/opacity pulse (3-5s idle cycle)
    - Define `@keyframes plasmaFlicker` for the outer plasma fire effect (2-4s idle cycle)
    - Define `@keyframes pulseTravel` for neural connection pulse travel animation
    - Define `@keyframes particleDrift` for particle orbit/drift outward animation (6-12s idle)
    - Define `@keyframes orbPress` for the click feedback scale animation (150ms)
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 5.1, 5.2, 5.3, 8.1, 11.1_

- [x] 2. Implement core neural orb styles
  - [x] 2.1 Create base `.neural-orb` styles and pseudo-element effects
    - Style `.neural-orb` with radial-gradient (#00e5ff center to #0040ff edges), 140px size, border-radius 50%
    - Add multi-layered box-shadow producing 60px+ outer glow
    - Apply `orbBreathe` animation for idle state
    - Style `::before` pseudo-element as inner volumetric glow layer with blur and semi-transparency
    - Style `::after` pseudo-element as outer plasma fire with animated radial gradient and `plasmaFlicker`
    - Set `pointer-events: none` on pseudo-elements
    - Set `will-change: transform, opacity` for GPU acceleration
    - Set `transition: all 300ms ease` for state changes
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 5.1, 5.4, 8.1, 11.1_

  - [x] 2.2 Create neural connections styles
    - Style `.neural-connections` as a positioned container centered on the orb
    - Style `.connection` as thin lines (1-2px) using CSS custom properties `--angle` and `--length` for rotation and sizing
    - Style `.pulse` element with `pulseTravel` animation (translateX travel along line, staggered 2-4s delays)
    - Use semi-transparent cyan/blue coloring consistent with palette
    - Set `pointer-events: none` on connection container
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 5.3, 11.1_

  - [x] 2.3 Create particle system styles
    - Style `.particle-system` container with `pointer-events: none` and absolute positioning
    - Style `.particle` elements using CSS custom properties (--size, --delay, --duration, --start-angle)
    - Apply `particleDrift` animation with varied durations (6-12s) and delays
    - Use blue-cyan palette with opacity 0.2-0.8
    - Set `will-change: transform, opacity` on particles
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 5.2, 11.2_

- [x] 3. Implement state-specific CSS rules
  - [x] 3.1 Add speaking state styles
    - `.speaking .neural-orb`: scale(1.15), increased glow radius (90px+), faster breathe cycle (1-2s)
    - `.speaking .neural-orb::after`: faster plasma flicker (0.5-1.5s cycle)
    - `.speaking .connection .pulse`: faster pulse interval (0.5-1s)
    - `.speaking .particle`: increased animation speed (3-6s duration)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 3.2 Add listening state styles
    - `.listening .neural-orb`: color shift to #00ff88, rhythmic pulse animation (1-2s cycle)
    - `.listening .neural-orb::after`: glow color transition to green-cyan
    - `.listening .connection`: color shift to green-cyan palette
    - `.listening .connection .pulse`: moderate pulse interval (1-2s)
    - `.listening .particle`: moderate animation speed (4-8s)
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x] 3.3 Add transition and interaction styles
    - Set `transition` on `.neural-orb` for color and transform changes (200-400ms)
    - Add `.neural-orb:active` or click feedback class with `orbPress` animation (scale down briefly, 150ms)
    - Set `cursor: pointer` on `#reactor`
    - _Requirements: 8.1, 8.2, 8.3, 9.2, 9.3_

- [x] 4. Implement responsive and accessibility styles
  - [x] 4.1 Add responsive breakpoint and reduced-motion styles
    - Add `@media (max-width: 500px)` rule: reduce `.neural-orb` to 100px, reduce connection lengths proportionally, reduce particle count (hide particles beyond index 10 using nth-child)
    - Add `@media (prefers-reduced-motion: reduce)` rule: disable all animations, show static blue sphere with glow
    - Add `@supports not (animation: none)` fallback: static gradient sphere with single box-shadow
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 11.4_

- [x] 5. Replace HTML structure in index.html
  - [x] 5.1 Replace the molecular structure DOM with neural orb DOM
    - Remove the existing `.molecule`, `.orbit`, `.electron`, `.nucleus` elements inside `.center`
    - Add new `#reactor` div with `onclick="handleOrb()"` and `cursor: pointer`
    - Add `.neural-orb` element inside `#reactor`
    - Add `.neural-connections` container with 8 `.connection` elements (each containing a `.pulse` child), using varied `--angle` (0deg, 45deg, 90deg, 135deg, 180deg, 225deg, 270deg, 315deg) and varied `--length` values
    - Add `.particle-system` container with 20 `.particle` elements using varied `--size`, `--delay`, `--duration`, and `--start-angle` custom properties
    - Preserve `.label` (FRIDAY) and `.sub-label` (TAP TO TALK) elements below the orb
    - _Requirements: 9.1, 9.4, 12.1, 12.2, 12.3, 12.4_

  - [x] 5.2 Remove old molecular CSS styles
    - Remove all `.molecule`, `.orbit`, `.electron`, `.nucleus` CSS rules
    - Remove `.molecule.speaking` and `.molecule.listening` CSS rules
    - Remove `@keyframes orbit1`, `orbit2`, `orbit3` keyframe definitions
    - Remove the `.molecule` size in the `@media (max-width: 500px)` block
    - _Requirements: 12.1_

- [x] 6. Verify JavaScript compatibility
  - [x] 6.1 Update JavaScript references from `.molecule` to `#reactor` state management
    - Verify that all `reactor.classList.add('speaking')` and `reactor.classList.remove('speaking')` calls target the new `#reactor` element correctly (they should since `id="reactor"` is preserved)
    - Confirm no JavaScript references `.molecule` class directly for state toggling
    - Ensure `handleOrb()` function still works with the new DOM structure
    - Test that state classes are applied to `#reactor` and cascade to `.neural-orb`, `.neural-connections`, `.particle-system` children via CSS
    - _Requirements: 9.1, 12.2, 12.3, 12.4_

- [x] 7. Checkpoint - Ensure visual integrity and interactions work
  - Ensure all tests pass, ask the user if questions arise.
  - Verify the orb renders with blue plasma sphere, neural connections, and particles
  - Verify tap-to-talk triggers handleOrb() and state transitions work
  - Verify responsive layout at ≤500px viewport
  - Verify prefers-reduced-motion disables animations

- [x] 8. Write automated DOM and CSS assertion tests
  - [x] 8.1 Write DOM structure tests
    - Verify `#reactor` element exists with `onclick="handleOrb()"`
    - Verify `.neural-orb`, `.neural-connections`, `.particle-system` elements are present
    - Verify at least 15 `.particle` elements exist
    - Verify at least 6 `.connection` elements exist
    - Verify `.sub-label` contains "TAP TO TALK"
    - Verify `pointer-events: none` on `.particle-system` and `.neural-connections`
    - _Requirements: 4.1, 4.5, 3.1, 9.1, 9.4, 12.1, 12.3, 12.4_

  - [x] 8.2 Write CSS computed style tests
    - Verify `.neural-orb` minimum width/height is 120px on desktop viewports
    - Verify `cursor: pointer` on `#reactor`
    - Verify `will-change` property on `.neural-orb` and `.particle` elements
    - Verify responsive sizing (≤100px) at viewport ≤500px
    - _Requirements: 1.1, 9.2, 10.1, 11.1, 11.2_

  - [x] 8.3 Write state transition integration tests
    - Add `.speaking` class to `#reactor`, verify `.neural-orb` computed transform includes scale > 1
    - Add `.listening` class to `#reactor`, verify color values shift toward green
    - Remove state classes, verify return to idle appearance
    - _Requirements: 6.1, 6.5, 7.1, 8.1_

- [x] 9. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
  - Verify 60fps performance during idle and speaking states
  - Confirm no layout thrashing (only transform/opacity used for animations)
  - Confirm click events are not blocked by decorative layers

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- The implementation is CSS/HTML only — no canvas, WebGL, or external animation libraries
- All JavaScript state management is preserved via the existing `reactor.classList.add/remove` pattern
- The `id="reactor"` and `onclick="handleOrb()"` attributes are maintained for backward compatibility
- GPU acceleration is achieved through `will-change`, `transform`, and `opacity` animations only

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3"] },
    { "id": 2, "tasks": ["3.1", "3.2", "3.3"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["5.1", "5.2"] },
    { "id": 5, "tasks": ["6.1"] },
    { "id": 6, "tasks": ["8.1", "8.2", "8.3"] }
  ]
}
```
