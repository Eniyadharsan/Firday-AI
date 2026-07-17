# Requirements Document

## Introduction

Redesign the FRIDAY center orb animation from its current molecular/orbiting-electron structure to a neural-core aesthetic. The new design presents a large fiery blue sphere as the central element, surrounded by neural network connections, synapse firing patterns, particle trails, and cosmic energy emissions. The orb retains all existing interactive states (idle, speaking, listening) and the tap-to-talk interaction.

## Glossary

- **Neural_Orb**: The redesigned center sphere element that replaces the current molecular structure, rendered as a fiery blue plasma core with neural network visual effects
- **Orb_Container**: The `.center` container element that positions the Neural_Orb and its surrounding effects within the viewport
- **Idle_State**: The default state when FRIDAY is neither speaking nor listening, characterized by a gentle ambient glow and slow particle drift
- **Speaking_State**: The active state when FRIDAY is producing speech output, characterized by intensified energy emissions, faster neural firing, and expanded glow radius
- **Listening_State**: The state when FRIDAY is receiving voice input, characterized by a color shift toward green/teal and rhythmic pulsing
- **Neural_Connections**: Animated line elements radiating from the Neural_Orb that simulate synaptic pathways and neural network links
- **Particle_System**: A collection of small animated elements representing cosmic dust, energy particles, and synapse sparks around the Neural_Orb
- **Plasma_Effect**: The fiery blue glow and flame-like animation surrounding the core sphere, simulating blue fire or plasma energy
- **Tap_Interaction**: The existing click/tap handler on the orb element that initiates voice input mode

## Requirements

### Requirement 1: Core Sphere Rendering

**User Story:** As a user, I want to see a large fiery blue sphere in the center of the interface, so that FRIDAY feels like an intelligent neural core rather than a molecular diagram.

#### Acceptance Criteria

1. THE Neural_Orb SHALL render as a radial-gradient sphere with a minimum diameter of 120px at its core element
2. THE Neural_Orb SHALL use a blue color palette ranging from bright cyan (#00e5ff) at the center to deep blue (#0040ff) at the edges
3. THE Neural_Orb SHALL display a multi-layered box-shadow producing a soft outer glow of at least 60px radius
4. THE Neural_Orb SHALL be centered horizontally and positioned in the upper-center area of the viewport, matching the current `.center` container placement

### Requirement 2: Plasma Fire Effect

**User Story:** As a user, I want to see a blue fire/plasma visual effect around the sphere, so that the orb looks like a living energy source.

#### Acceptance Criteria

1. THE Plasma_Effect SHALL render animated glow layers around the Neural_Orb using CSS animations or pseudo-elements
2. THE Plasma_Effect SHALL produce a flickering or pulsating animation with a cycle duration between 2 and 4 seconds during Idle_State
3. THE Plasma_Effect SHALL use semi-transparent blue and cyan gradients to simulate volumetric fire
4. THE Plasma_Effect SHALL not obscure the Neural_Orb core visibility

### Requirement 3: Neural Network Connections

**User Story:** As a user, I want to see animated neural connections radiating from the orb, so that it looks like a neural network hub processing information.

#### Acceptance Criteria

1. THE Neural_Connections SHALL render at least 6 visible connection lines radiating outward from the Neural_Orb
2. THE Neural_Connections SHALL animate with a travelling pulse or firing effect along their length to simulate synaptic activity
3. THE Neural_Connections SHALL use semi-transparent cyan or blue coloring consistent with the Neural_Orb palette
4. THE Neural_Connections SHALL vary in length and angle to create an organic, non-uniform appearance

### Requirement 4: Cosmic Particle System

**User Story:** As a user, I want to see particle trails and cosmic dust around the orb, so that it feels like the center of a universe with energy emissions.

#### Acceptance Criteria

1. THE Particle_System SHALL render at least 15 animated particle elements around the Neural_Orb
2. THE Particle_System SHALL animate particles drifting outward from or orbiting around the Neural_Orb
3. THE Particle_System SHALL vary particle size between 1px and 4px to create depth
4. THE Particle_System SHALL use colors from the blue-cyan palette with varying opacity levels between 0.2 and 0.8
5. THE Particle_System SHALL ensure particles do not interfere with click events on the Neural_Orb by using pointer-events:none on particle elements

### Requirement 5: Idle State Behavior

**User Story:** As a user, I want the orb to display a calm, gentle animation when FRIDAY is idle, so that I know the system is available but not actively processing.

#### Acceptance Criteria

1. WHILE in Idle_State, THE Neural_Orb SHALL display a slow breathing glow animation with a cycle duration between 3 and 5 seconds
2. WHILE in Idle_State, THE Particle_System SHALL drift at a slow speed with animation durations between 6 and 12 seconds per particle
3. WHILE in Idle_State, THE Neural_Connections SHALL fire synaptic pulses at a relaxed interval of one pulse every 2 to 4 seconds per connection
4. WHILE in Idle_State, THE Plasma_Effect SHALL maintain a subtle ambient intensity without rapid fluctuations

### Requirement 6: Speaking State Behavior

**User Story:** As a user, I want the orb to become visually intense and active when FRIDAY is speaking, so that I have clear visual feedback that the system is producing output.

#### Acceptance Criteria

1. WHEN the Speaking_State is activated, THE Neural_Orb SHALL increase its glow radius by at least 50% compared to Idle_State
2. WHILE in Speaking_State, THE Particle_System SHALL increase particle animation speed by at least 2x compared to Idle_State
3. WHILE in Speaking_State, THE Neural_Connections SHALL fire synaptic pulses at a rapid interval of one pulse every 0.5 to 1 second per connection
4. WHILE in Speaking_State, THE Plasma_Effect SHALL increase animation intensity with a faster flicker cycle between 0.5 and 1.5 seconds
5. WHEN the Speaking_State is activated, THE Neural_Orb SHALL expand its core diameter by 10% to 20% compared to Idle_State

### Requirement 7: Listening State Behavior

**User Story:** As a user, I want the orb to change appearance when FRIDAY is listening to me, so that I have clear visual confirmation that my voice input is being received.

#### Acceptance Criteria

1. WHEN the Listening_State is activated, THE Neural_Orb SHALL shift its primary color toward green-cyan (#00ff88) tones
2. WHILE in Listening_State, THE Neural_Orb SHALL display a rhythmic pulse animation with a cycle duration between 1 and 2 seconds
3. WHILE in Listening_State, THE Neural_Connections SHALL shift color to match the green-cyan listening palette
4. WHILE in Listening_State, THE Plasma_Effect SHALL transition its glow color from blue to green-cyan within 300ms of state activation

### Requirement 8: State Transitions

**User Story:** As a user, I want smooth visual transitions between orb states, so that the interface feels polished and responsive.

#### Acceptance Criteria

1. WHEN transitioning between any two states, THE Neural_Orb SHALL animate the color and size change over a duration between 200ms and 400ms using CSS transitions
2. WHEN transitioning between any two states, THE Plasma_Effect SHALL blend between intensity levels without abrupt visual jumps
3. WHEN transitioning between any two states, THE Neural_Connections SHALL adjust their firing rate gradually over 300ms

### Requirement 9: Tap-to-Talk Interaction Preservation

**User Story:** As a user, I want to tap or click the orb to initiate voice input, so that the existing interaction model is preserved after the redesign.

#### Acceptance Criteria

1. THE Neural_Orb SHALL retain a click event handler that triggers the same `handleOrb()` function as the current implementation
2. THE Neural_Orb SHALL display a cursor:pointer style to indicate interactivity
3. THE Neural_Orb SHALL provide a visual press feedback effect on click (brief scale or flash) completing within 150ms
4. THE Orb_Container SHALL preserve the "TAP TO TALK" sub-label text below the orb

### Requirement 10: Responsive Layout

**User Story:** As a user accessing FRIDAY on a mobile device, I want the neural orb to scale appropriately, so that the visual effect works across screen sizes.

#### Acceptance Criteria

1. WHEN the viewport width is 500px or less, THE Neural_Orb SHALL reduce its core diameter to no larger than 100px
2. WHEN the viewport width is 500px or less, THE Neural_Connections SHALL reduce their maximum length proportionally
3. THE Orb_Container SHALL maintain center-horizontal positioning across all viewport widths
4. THE Particle_System SHALL reduce particle count on viewports below 500px to maintain performance

### Requirement 11: Performance

**User Story:** As a user, I want the orb animation to run smoothly without causing frame drops, so that the interface remains responsive.

#### Acceptance Criteria

1. THE Neural_Orb SHALL use CSS transforms and opacity for animations to enable GPU acceleration
2. THE Particle_System SHALL use the `will-change` property on animated elements to hint compositor optimization
3. THE Neural_Orb SHALL maintain a target frame rate of 60fps during all animation states on modern browsers
4. IF the browser does not support CSS animations, THEN THE Neural_Orb SHALL display a static blue sphere with a glow effect as a graceful fallback

### Requirement 12: DOM Structure Replacement

**User Story:** As a developer, I want the new orb to replace the existing molecular structure HTML, so that the codebase remains clean and the old animation code is removed.

#### Acceptance Criteria

1. THE Neural_Orb SHALL replace the existing `.molecule`, `.orbit`, `.electron`, and `.nucleus` HTML elements within the `.center` container
2. THE Neural_Orb SHALL apply state classes (`.speaking`, `.listening`) on the new root orb element to control visual state changes via CSS
3. THE Neural_Orb SHALL preserve the existing `id="reactor"` attribute on the clickable orb element for JavaScript compatibility
4. THE Neural_Orb SHALL preserve the `onclick="handleOrb()"` attribute on the clickable element
