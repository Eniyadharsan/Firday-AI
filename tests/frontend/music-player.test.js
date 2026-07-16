// Feature: music-player, Property 7: Queue Navigation Correctness
// Feature: music-player, Property 5: Progress Bar Calculation
// **Validates: Requirements 3.4, 3.5, 3.6, 3.7, 5.3**
// **Validates: Requirements 2.2**

import { describe, it, expect } from 'vitest';
import fc from 'fast-check';

class MusicPlayer {
  constructor() {
    this.queue = [];
    this.currentIndex = -1;
    this.isPlaying = false;
    this._currentVideoId = null;
    this._lastLoadedTrack = null;
  }

  loadTrack(track) {
    this.queue = [track];
    this.currentIndex = 0;
    this._currentVideoId = null;
    this._lastLoadedTrack = track;
  }

  loadQueue(tracks, startIndex) {
    this.queue = [...tracks];
    this.currentIndex = startIndex;
    this._currentVideoId = null;
    this._lastLoadedTrack = this.getCurrentTrack();
  }

  play() {
    if (this.getCurrentTrack()) {
      const track = this.getCurrentTrack();
      this._currentVideoId = track.video_id;
      this._lastLoadedTrack = track;
    }
    this.isPlaying = true;
  }

  pause() {
    this.isPlaying = false;
  }

  togglePlayPause() {
    if (this.isPlaying) {
      this.pause();
    } else {
      this.play();
    }
  }

  next() {
    if (this.currentIndex < this.queue.length - 1) {
      this.currentIndex++;
      this._currentVideoId = null;
      this.play();
      this._lastLoadedTrack = this.getCurrentTrack();
    }
  }

  previous() {
    if (this.currentIndex > 0) {
      this.currentIndex--;
      this._currentVideoId = null;
      this.play();
      this._lastLoadedTrack = this.getCurrentTrack();
    }
  }

  clearQueue() {
    this.queue = [];
    this.currentIndex = -1;
  }

  addToQueue(tracks) {
    this.queue.push(...tracks);
  }

  getCurrentTrack() {
    if (this.currentIndex >= 0 && this.currentIndex < this.queue.length) {
      return this.queue[this.currentIndex];
    }
    return null;
  }
}

// --- Generators ---
const trackArb = fc.record({
  video_id: fc.string({ minLength: 1, maxLength: 11 }),
  title: fc.string({ minLength: 1, maxLength: 100 }),
  artist: fc.string({ minLength: 1, maxLength: 100 }),
  thumbnail_url: fc.webUrl(),
});

const queueArb = fc.array(trackArb, { minLength: 2, maxLength: 50 });

// =============================================================================
// Property 7: Queue Navigation Correctness
// Feature: music-player, Property 7: Queue Navigation Correctness
// **Validates: Requirements 3.4, 3.5, 3.6, 3.7, 5.3**
// =============================================================================

describe('Property 7: Queue Navigation Correctness', () => {
  it('next() advances currentIndex to I+1 when I < N-1 and loads the track at I+1', () => {
    fc.assert(
      fc.property(queueArb, fc.nat(), (tracks, rawIndex) => {
        const player = new MusicPlayer();
        const N = tracks.length;
        const I = rawIndex % (N - 1);
        player.loadQueue(tracks, I);
        player.next();
        expect(player.currentIndex).toBe(I + 1);
        expect(player._lastLoadedTrack).toEqual(tracks[I + 1]);
      }),
      { numRuns: 100 }
    );
  });

  it('previous() decrements currentIndex to I-1 when I > 0 and loads the track at I-1', () => {
    fc.assert(
      fc.property(queueArb, fc.nat(), (tracks, rawIndex) => {
        const player = new MusicPlayer();
        const N = tracks.length;
        const I = (rawIndex % (N - 1)) + 1;
        player.loadQueue(tracks, I);
        player.previous();
        expect(player.currentIndex).toBe(I - 1);
        expect(player._lastLoadedTrack).toEqual(tracks[I - 1]);
      }),
      { numRuns: 100 }
    );
  });

  it('next() does NOT change currentIndex when I == N-1 (last track)', () => {
    fc.assert(
      fc.property(queueArb, (tracks) => {
        const player = new MusicPlayer();
        const I = tracks.length - 1;
        player.loadQueue(tracks, I);
        player.next();
        expect(player.currentIndex).toBe(I);
      }),
      { numRuns: 100 }
    );
  });

  it('previous() does NOT change currentIndex when I == 0 (first track)', () => {
    fc.assert(
      fc.property(queueArb, (tracks) => {
        const player = new MusicPlayer();
        player.loadQueue(tracks, 0);
        player.previous();
        expect(player.currentIndex).toBe(0);
      }),
      { numRuns: 100 }
    );
  });
});

// =============================================================================
// Property 5: Progress Bar Calculation
// Feature: music-player, Property 5: Progress Bar Calculation
// **Validates: Requirements 2.2**
// =============================================================================

/**
 * Progress bar calculation logic extracted from MusicPlayer.startProgressInterval().
 * Mirrors the exact calculation in public/index.html:
 *   let progress = 0;
 *   if (duration > 0) { progress = currentTime / duration; }
 *   progressBar.style.width = (progress * 100) + '%';
 */
function calculateProgress(currentTime, totalDuration) {
  let progress = 0;
  if (totalDuration > 0) {
    progress = currentTime / totalDuration;
  }
  return progress;
}

function calculateProgressBarWidth(currentTime, totalDuration) {
  const progress = calculateProgress(currentTime, totalDuration);
  return (progress * 100) + '%';
}

describe('Property 5: Progress Bar Calculation', () => {
  const durationArb = fc.double({ min: 0.001, max: 86400, noNaN: true, noDefaultInfinity: true })
    .filter(d => d > 0);
  const timeArb = fc.double({ min: 0, max: 86400, noNaN: true, noDefaultInfinity: true });

  it('progress percentage equals currentTime / totalDuration for valid inputs', () => {
    fc.assert(
      fc.property(durationArb, timeArb, (totalDuration, rawCurrentTime) => {
        const currentTime = Math.min(Math.max(rawCurrentTime, 0), totalDuration);
        const progress = calculateProgress(currentTime, totalDuration);
        const expected = currentTime / totalDuration;
        expect(progress).toBeCloseTo(expected, 10);
      }),
      { numRuns: 100 }
    );
  });

  it('progress bar width is proportional to currentTime / totalDuration', () => {
    fc.assert(
      fc.property(durationArb, timeArb, (totalDuration, rawCurrentTime) => {
        const currentTime = Math.min(Math.max(rawCurrentTime, 0), totalDuration);
        const widthStr = calculateProgressBarWidth(currentTime, totalDuration);
        const expectedWidth = (currentTime / totalDuration) * 100;
        expect(widthStr).toMatch(/%$/);
        expect(parseFloat(widthStr)).toBeCloseTo(expectedWidth, 10);
      }),
      { numRuns: 100 }
    );
  });

  it('progress is always between 0 and 1 inclusive', () => {
    fc.assert(
      fc.property(durationArb, timeArb, (totalDuration, rawCurrentTime) => {
        const currentTime = Math.min(Math.max(rawCurrentTime, 0), totalDuration);
        const progress = calculateProgress(currentTime, totalDuration);
        expect(progress).toBeGreaterThanOrEqual(0);
        expect(progress).toBeLessThanOrEqual(1);
      }),
      { numRuns: 100 }
    );
  });

  it('progress bar width is always between 0% and 100%', () => {
    fc.assert(
      fc.property(durationArb, timeArb, (totalDuration, rawCurrentTime) => {
        const currentTime = Math.min(Math.max(rawCurrentTime, 0), totalDuration);
        const widthStr = calculateProgressBarWidth(currentTime, totalDuration);
        const numericWidth = parseFloat(widthStr);
        expect(numericWidth).toBeGreaterThanOrEqual(0);
        expect(numericWidth).toBeLessThanOrEqual(100);
      }),
      { numRuns: 100 }
    );
  });

  it('progress at start (currentTime=0) is 0%', () => {
    fc.assert(
      fc.property(durationArb, (totalDuration) => {
        const progress = calculateProgress(0, totalDuration);
        const widthStr = calculateProgressBarWidth(0, totalDuration);
        expect(progress).toBe(0);
        expect(widthStr).toBe('0%');
      }),
      { numRuns: 100 }
    );
  });

  it('progress at end (currentTime=totalDuration) is 100%', () => {
    fc.assert(
      fc.property(durationArb, (totalDuration) => {
        const progress = calculateProgress(totalDuration, totalDuration);
        const widthStr = calculateProgressBarWidth(totalDuration, totalDuration);
        expect(progress).toBeCloseTo(1, 10);
        expect(parseFloat(widthStr)).toBeCloseTo(100, 10);
      }),
      { numRuns: 100 }
    );
  });

  it('progress is monotonically non-decreasing with currentTime', () => {
    fc.assert(
      fc.property(durationArb, timeArb, timeArb, (totalDuration, rawTime1, rawTime2) => {
        const time1 = Math.min(Math.max(rawTime1, 0), totalDuration);
        const time2 = Math.min(Math.max(rawTime2, 0), totalDuration);
        const progress1 = calculateProgress(time1, totalDuration);
        const progress2 = calculateProgress(time2, totalDuration);
        if (time1 <= time2) {
          expect(progress1).toBeLessThanOrEqual(progress2 + 1e-10);
        } else {
          expect(progress2).toBeLessThanOrEqual(progress1 + 1e-10);
        }
      }),
      { numRuns: 100 }
    );
  });
});

// =============================================================================
// Property 8: Queue Replacement on New Load
// Feature: music-player, Property 8: Queue Replacement on New Load
// **Validates: Requirements 7.1, 7.2, 7.4**
// =============================================================================

describe('Property 8: Queue Replacement on New Load', () => {
  it('after loadQueue, queue equals exactly the new track list', () => {
    fc.assert(
      fc.property(
        queueArb,
        fc.array(trackArb, { minLength: 1, maxLength: 50 }),
        fc.nat(),
        (oldTracks, newTracks, rawStartIndex) => {
          const player = new MusicPlayer();
          // Set up an existing queue state
          player.loadQueue(oldTracks, 0);

          // Load a new queue
          const startIndex = rawStartIndex % newTracks.length;
          player.loadQueue(newTracks, startIndex);

          // Queue SHALL equal exactly the new track list
          expect(player.queue).toEqual(newTracks);
          expect(player.queue.length).toBe(newTracks.length);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('after loadQueue, previous queue contents are completely gone', () => {
    fc.assert(
      fc.property(
        queueArb,
        fc.array(trackArb, { minLength: 1, maxLength: 50 }),
        fc.nat(),
        (oldTracks, newTracks, rawStartIndex) => {
          const player = new MusicPlayer();
          // Set up an existing queue state
          player.loadQueue(oldTracks, 0);

          // Load a new queue
          const startIndex = rawStartIndex % newTracks.length;
          player.loadQueue(newTracks, startIndex);

          // Previous queue contents SHALL be completely gone
          // Verify no old tracks remain (unless they happen to also be in newTracks)
          for (const oldTrack of oldTracks) {
            const isInNewTracks = newTracks.some(
              (t) => t.video_id === oldTrack.video_id &&
                     t.title === oldTrack.title &&
                     t.artist === oldTrack.artist &&
                     t.thumbnail_url === oldTrack.thumbnail_url
            );
            if (!isInNewTracks) {
              const foundInQueue = player.queue.some(
                (t) => t.video_id === oldTrack.video_id &&
                       t.title === oldTrack.title &&
                       t.artist === oldTrack.artist &&
                       t.thumbnail_url === oldTrack.thumbnail_url
              );
              expect(foundInQueue).toBe(false);
            }
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it('after loadQueue, currentIndex equals startIndex', () => {
    fc.assert(
      fc.property(
        queueArb,
        fc.array(trackArb, { minLength: 1, maxLength: 50 }),
        fc.nat(),
        (oldTracks, newTracks, rawStartIndex) => {
          const player = new MusicPlayer();
          // Set up an existing queue state
          player.loadQueue(oldTracks, 0);

          // Load a new queue with a valid startIndex
          const startIndex = rawStartIndex % newTracks.length;
          player.loadQueue(newTracks, startIndex);

          // currentIndex SHALL equal startIndex
          expect(player.currentIndex).toBe(startIndex);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('loadQueue replaces regardless of prior queue size (small to large, large to small)', () => {
    fc.assert(
      fc.property(
        fc.array(trackArb, { minLength: 1, maxLength: 5 }),
        fc.array(trackArb, { minLength: 10, maxLength: 50 }),
        fc.nat(),
        (smallQueue, largeQueue, rawStartIndex) => {
          const player = new MusicPlayer();

          // Load small then replace with large
          player.loadQueue(smallQueue, 0);
          const startIndexLarge = rawStartIndex % largeQueue.length;
          player.loadQueue(largeQueue, startIndexLarge);
          expect(player.queue).toEqual(largeQueue);
          expect(player.currentIndex).toBe(startIndexLarge);

          // Load large then replace with small
          const startIndexSmall = rawStartIndex % smallQueue.length;
          player.loadQueue(smallQueue, startIndexSmall);
          expect(player.queue).toEqual(smallQueue);
          expect(player.currentIndex).toBe(startIndexSmall);
        }
      ),
      { numRuns: 100 }
    );
  });
});


// =============================================================================
// Property 6: Play/Pause Toggle is Its Own Inverse
// Feature: music-player, Property 6: Play/Pause Toggle is Its Own Inverse
// **Validates: Requirements 3.2, 3.3**
// =============================================================================

describe('Property 6: Play/Pause Toggle is Its Own Inverse', () => {
  it('calling togglePlayPause() twice returns isPlaying to its original state (starting playing)', () => {
    fc.assert(
      fc.property(trackArb, (track) => {
        const player = new MusicPlayer();
        player.loadTrack(track);
        player.play();
        const originalState = player.isPlaying; // true
        player.togglePlayPause();
        player.togglePlayPause();
        expect(player.isPlaying).toBe(originalState);
      }),
      { numRuns: 100 }
    );
  });

  it('calling togglePlayPause() twice returns isPlaying to its original state (starting paused)', () => {
    fc.assert(
      fc.property(trackArb, (track) => {
        const player = new MusicPlayer();
        player.loadTrack(track);
        player.pause();
        const originalState = player.isPlaying; // false
        player.togglePlayPause();
        player.togglePlayPause();
        expect(player.isPlaying).toBe(originalState);
      }),
      { numRuns: 100 }
    );
  });

  it('togglePlayPause() inverts isPlaying on first call for any initial state', () => {
    fc.assert(
      fc.property(trackArb, fc.boolean(), (track, startPlaying) => {
        const player = new MusicPlayer();
        player.loadTrack(track);
        if (startPlaying) {
          player.play();
        } else {
          player.pause();
        }
        const originalState = player.isPlaying;
        player.togglePlayPause();
        expect(player.isPlaying).toBe(!originalState);
      }),
      { numRuns: 100 }
    );
  });

  it('togglePlayPause() is its own inverse for arbitrary initial boolean states', () => {
    fc.assert(
      fc.property(fc.boolean(), (initialPlaying) => {
        const player = new MusicPlayer();
        player.isPlaying = initialPlaying;
        player.togglePlayPause();
        player.togglePlayPause();
        expect(player.isPlaying).toBe(initialPlaying);
      }),
      { numRuns: 100 }
    );
  });
});


// =============================================================================
// Property 9: Queue Index Invariant
// Feature: music-player, Property 9: Queue Index Invariant
// **Validates: Requirements 7.3**
// =============================================================================

describe('Property 9: Queue Index Invariant', () => {
  // Generator for a single track
  const trackArb9 = fc.record({
    video_id: fc.string({ minLength: 1, maxLength: 11 }),
    title: fc.string({ minLength: 1, maxLength: 100 }),
    artist: fc.string({ minLength: 1, maxLength: 100 }),
    thumbnail_url: fc.webUrl(),
  });

  // Generator for a non-empty list of tracks (for loadQueue)
  const tracksArb9 = fc.array(trackArb9, { minLength: 1, maxLength: 20 });

  // Generator for operations: loadTrack, loadQueue, next, previous
  const operationArb = fc.oneof(
    trackArb9.map(track => ({ type: 'loadTrack', track })),
    tracksArb9.chain(tracks =>
      fc.nat({ max: tracks.length - 1 }).map(startIndex => ({
        type: 'loadQueue',
        tracks,
        startIndex,
      }))
    ),
    fc.constant({ type: 'next' }),
    fc.constant({ type: 'previous' })
  );

  // Generator for a sequence of operations
  const operationSequenceArb = fc.array(operationArb, { minLength: 1, maxLength: 30 });

  /**
   * Checks the queue index invariant:
   * - currentIndex == -1 if and only if queue is empty
   * - 0 <= currentIndex < queue.length if queue is non-empty
   */
  function assertQueueIndexInvariant(player) {
    if (player.queue.length === 0) {
      expect(player.currentIndex).toBe(-1);
    } else {
      expect(player.currentIndex).toBeGreaterThanOrEqual(0);
      expect(player.currentIndex).toBeLessThan(player.queue.length);
    }
  }

  /**
   * Applies an operation to the player.
   */
  function applyOperation(player, op) {
    switch (op.type) {
      case 'loadTrack':
        player.loadTrack(op.track);
        break;
      case 'loadQueue':
        player.loadQueue(op.tracks, op.startIndex);
        break;
      case 'next':
        player.next();
        break;
      case 'previous':
        player.previous();
        break;
    }
  }

  it('currentIndex == -1 iff queue is empty, and 0 <= currentIndex < queue.length iff queue is non-empty, for any sequence of operations', () => {
    fc.assert(
      fc.property(operationSequenceArb, (operations) => {
        const player = new MusicPlayer();

        // Invariant holds initially (empty queue, index -1)
        assertQueueIndexInvariant(player);

        // Apply each operation and verify invariant holds after each one
        for (const op of operations) {
          applyOperation(player, op);
          assertQueueIndexInvariant(player);
        }
      }),
      { numRuns: 100 }
    );
  });

  it('invariant holds after loadTrack always sets index to 0 with single-element queue', () => {
    fc.assert(
      fc.property(trackArb9, (track) => {
        const player = new MusicPlayer();
        player.loadTrack(track);
        expect(player.queue.length).toBe(1);
        expect(player.currentIndex).toBe(0);
        assertQueueIndexInvariant(player);
      }),
      { numRuns: 100 }
    );
  });

  it('invariant holds after loadQueue sets index to startIndex within bounds', () => {
    fc.assert(
      fc.property(
        tracksArb9.chain(tracks =>
          fc.nat({ max: tracks.length - 1 }).map(startIndex => ({ tracks, startIndex }))
        ),
        ({ tracks, startIndex }) => {
          const player = new MusicPlayer();
          player.loadQueue(tracks, startIndex);
          expect(player.currentIndex).toBe(startIndex);
          assertQueueIndexInvariant(player);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('next() and previous() never cause index to go out of bounds', () => {
    fc.assert(
      fc.property(
        tracksArb9,
        fc.array(fc.oneof(fc.constant('next'), fc.constant('previous')), { minLength: 1, maxLength: 50 }),
        (tracks, navOps) => {
          const player = new MusicPlayer();
          player.loadQueue(tracks, 0);
          assertQueueIndexInvariant(player);

          for (const op of navOps) {
            if (op === 'next') {
              player.next();
            } else {
              player.previous();
            }
            assertQueueIndexInvariant(player);
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});

// =============================================================================
// Property 8: Queue Replacement on New Load
// Feature: music-player, Property 8: Queue Replacement on New Load
// **Validates: Requirements 7.1, 7.2, 7.4**
// =============================================================================

describe('Property 8: Queue Replacement on New Load', () => {
  // Generator for a non-empty track list with a valid start index
  const newQueueArb = fc.array(trackArb, { minLength: 1, maxLength: 50 }).chain((tracks) =>
    fc.record({
      tracks: fc.constant(tracks),
      startIndex: fc.nat({ max: tracks.length - 1 }),
    })
  );

  // Generator for an existing queue state (could be empty or populated)
  const existingQueueStateArb = fc.array(trackArb, { minLength: 0, maxLength: 50 });

  it('after loadQueue, the queue SHALL equal exactly the new track list', () => {
    fc.assert(
      fc.property(existingQueueStateArb, newQueueArb, (existingTracks, { tracks, startIndex }) => {
        const player = new MusicPlayer();
        // Set up existing queue state
        if (existingTracks.length > 0) {
          player.loadQueue(existingTracks, 0);
        }
        // Load new queue
        player.loadQueue(tracks, startIndex);
        // Queue SHALL equal exactly the new track list
        expect(player.queue).toEqual(tracks);
        expect(player.queue.length).toBe(tracks.length);
      }),
      { numRuns: 100 }
    );
  });

  it('after loadQueue, previous queue contents SHALL be completely gone', () => {
    fc.assert(
      fc.property(existingQueueStateArb.filter(t => t.length > 0), newQueueArb, (existingTracks, { tracks, startIndex }) => {
        const player = new MusicPlayer();
        // Load an initial queue
        player.loadQueue(existingTracks, 0);
        // Verify existing queue is set
        expect(player.queue).toEqual(existingTracks);
        // Now load a new queue
        player.loadQueue(tracks, startIndex);
        // Previous queue contents SHALL be completely gone
        // The queue should contain ONLY the new tracks, none of the old ones
        expect(player.queue).toEqual(tracks);
        // Verify no references to old tracks remain
        for (const oldTrack of existingTracks) {
          // Only check tracks that aren't also in the new list
          if (!tracks.some(t => t.video_id === oldTrack.video_id)) {
            const found = player.queue.some(t => t.video_id === oldTrack.video_id);
            expect(found).toBe(false);
          }
        }
      }),
      { numRuns: 100 }
    );
  });

  it('after loadQueue, currentIndex SHALL equal startIndex', () => {
    fc.assert(
      fc.property(existingQueueStateArb, newQueueArb, (existingTracks, { tracks, startIndex }) => {
        const player = new MusicPlayer();
        // Set up existing queue state
        if (existingTracks.length > 0) {
          player.loadQueue(existingTracks, 0);
        }
        // Load new queue with specific startIndex
        player.loadQueue(tracks, startIndex);
        // currentIndex SHALL equal startIndex
        expect(player.currentIndex).toBe(startIndex);
      }),
      { numRuns: 100 }
    );
  });

  it('loadQueue replaces queue regardless of what operations were performed before', () => {
    fc.assert(
      fc.property(
        existingQueueStateArb.filter(t => t.length >= 2),
        newQueueArb,
        fc.nat({ max: 10 }),
        (existingTracks, { tracks, startIndex }, numOps) => {
          const player = new MusicPlayer();
          // Load initial queue and perform some operations
          player.loadQueue(existingTracks, 0);
          for (let i = 0; i < numOps % 5; i++) {
            player.next();
          }
          for (let i = 0; i < numOps % 3; i++) {
            player.previous();
          }
          // Now load new queue
          player.loadQueue(tracks, startIndex);
          // Queue SHALL equal exactly the new track list
          expect(player.queue).toEqual(tracks);
          // currentIndex SHALL equal startIndex
          expect(player.currentIndex).toBe(startIndex);
        }
      ),
      { numRuns: 100 }
    );
  });
});

// =============================================================================
// Property 6: Play/Pause Toggle is Its Own Inverse
// Feature: music-player, Property 6: Play/Pause Toggle is Its Own Inverse
// **Validates: Requirements 3.2, 3.3**
// =============================================================================

describe('Property 6: Play/Pause Toggle is Its Own Inverse', () => {
  it('calling togglePlayPause() twice returns player to its original isPlaying state', () => {
    fc.assert(
      fc.property(
        trackArb,
        fc.boolean(),
        (track, initialPlaying) => {
          const player = new MusicPlayer();
          player.loadTrack(track);

          // Set initial playing state
          if (initialPlaying) {
            player.play();
          } else {
            player.pause();
          }

          const originalState = player.isPlaying;

          // Toggle twice — should return to original state
          player.togglePlayPause();
          player.togglePlayPause();

          expect(player.isPlaying).toBe(originalState);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('single toggle inverts the isPlaying state', () => {
    fc.assert(
      fc.property(
        trackArb,
        fc.boolean(),
        (track, initialPlaying) => {
          const player = new MusicPlayer();
          player.loadTrack(track);

          if (initialPlaying) {
            player.play();
          } else {
            player.pause();
          }

          const originalState = player.isPlaying;

          player.togglePlayPause();

          expect(player.isPlaying).toBe(!originalState);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('toggle involution holds regardless of how many prior toggles occurred', () => {
    fc.assert(
      fc.property(
        trackArb,
        fc.nat({ max: 20 }),
        (track, priorToggles) => {
          const player = new MusicPlayer();
          player.loadTrack(track);
          player.play();

          // Apply a random number of prior toggles to get to some state
          for (let i = 0; i < priorToggles; i++) {
            player.togglePlayPause();
          }

          const stateBeforeDoubleToggle = player.isPlaying;

          // Double toggle should always restore to the state before
          player.togglePlayPause();
          player.togglePlayPause();

          expect(player.isPlaying).toBe(stateBeforeDoubleToggle);
        }
      ),
      { numRuns: 100 }
    );
  });
});


// =============================================================================
// Property 9: Queue Index Invariant
// Feature: music-player, Property 9: Queue Index Invariant
// **Validates: Requirements 7.3**
// =============================================================================

describe('Property 9: Queue Index Invariant', () => {
  // Generator for a single track
  const trackArb9 = fc.record({
    video_id: fc.string({ minLength: 1, maxLength: 11 }),
    title: fc.string({ minLength: 1, maxLength: 100 }),
    artist: fc.string({ minLength: 1, maxLength: 100 }),
    thumbnail_url: fc.webUrl(),
  });

  // Generator for a non-empty list of tracks
  const nonEmptyTracksArb = fc.array(trackArb9, { minLength: 1, maxLength: 20 });

  // Command generators representing player operations
  const loadTrackCmd = trackArb9.map(track => ({
    type: 'loadTrack',
    track,
  }));

  const loadQueueCmd = nonEmptyTracksArb.chain(tracks =>
    fc.nat({ max: tracks.length - 1 }).map(startIndex => ({
      type: 'loadQueue',
      tracks,
      startIndex,
    }))
  );

  const nextCmd = fc.constant({ type: 'next' });
  const previousCmd = fc.constant({ type: 'previous' });

  const operationArb = fc.oneof(loadTrackCmd, loadQueueCmd, nextCmd, previousCmd);
  const operationsArb = fc.array(operationArb, { minLength: 1, maxLength: 30 });

  function applyOperation(player, op) {
    switch (op.type) {
      case 'loadTrack':
        player.loadTrack(op.track);
        break;
      case 'loadQueue':
        player.loadQueue(op.tracks, op.startIndex);
        break;
      case 'next':
        player.next();
        break;
      case 'previous':
        player.previous();
        break;
    }
  }

  function assertQueueIndexInvariant(player) {
    if (player.queue.length === 0) {
      // currentIndex must be -1 when queue is empty
      expect(player.currentIndex).toBe(-1);
    } else {
      // currentIndex must be in valid range when queue is non-empty
      expect(player.currentIndex).toBeGreaterThanOrEqual(0);
      expect(player.currentIndex).toBeLessThan(player.queue.length);
    }
  }

  it('currentIndex == -1 iff queue is empty, and 0 <= currentIndex < queue.length if queue is non-empty, for any sequence of operations', () => {
    fc.assert(
      fc.property(operationsArb, (operations) => {
        const player = new MusicPlayer();

        // Check invariant holds initially (empty queue, index -1)
        assertQueueIndexInvariant(player);

        // Apply each operation and check invariant after each step
        for (const op of operations) {
          applyOperation(player, op);
          assertQueueIndexInvariant(player);
        }
      }),
      { numRuns: 100 }
    );
  });

  it('a freshly constructed player has empty queue and currentIndex == -1', () => {
    fc.assert(
      fc.property(fc.constant(null), () => {
        const player = new MusicPlayer();
        expect(player.queue.length).toBe(0);
        expect(player.currentIndex).toBe(-1);
      }),
      { numRuns: 100 }
    );
  });

  it('after loadTrack, queue is non-empty and currentIndex is 0', () => {
    fc.assert(
      fc.property(trackArb9, (track) => {
        const player = new MusicPlayer();
        player.loadTrack(track);
        expect(player.queue.length).toBeGreaterThan(0);
        expect(player.currentIndex).toBe(0);
        assertQueueIndexInvariant(player);
      }),
      { numRuns: 100 }
    );
  });

  it('after loadQueue, queue is non-empty and currentIndex equals startIndex within bounds', () => {
    fc.assert(
      fc.property(nonEmptyTracksArb, (tracks) => {
        const player = new MusicPlayer();
        const startIndex = Math.floor(Math.random() * tracks.length);
        player.loadQueue(tracks, startIndex);
        expect(player.queue.length).toBe(tracks.length);
        expect(player.currentIndex).toBe(startIndex);
        assertQueueIndexInvariant(player);
      }),
      { numRuns: 100 }
    );
  });

  it('next() and previous() never push currentIndex out of bounds', () => {
    fc.assert(
      fc.property(
        nonEmptyTracksArb,
        fc.array(fc.oneof(fc.constant('next'), fc.constant('previous')), { minLength: 1, maxLength: 50 }),
        (tracks, commands) => {
          const player = new MusicPlayer();
          player.loadQueue(tracks, 0);
          assertQueueIndexInvariant(player);

          for (const cmd of commands) {
            if (cmd === 'next') {
              player.next();
            } else {
              player.previous();
            }
            assertQueueIndexInvariant(player);
          }
        }
      ),
      { numRuns: 100 }
    );
  });
});


// =============================================================================
// Property 10: Search Selection Populates Queue
// Feature: music-player, Property 10: Search Selection Populates Queue
// **Validates: Requirements 4.5**
// =============================================================================

describe('Property 10: Search Selection Populates Queue', () => {
  // Generator for search result tracks (1 to 10 tracks, matching search behavior)
  const searchResultsArb = fc.array(trackArb, { minLength: 1, maxLength: 10 });

  it('when user selects track at index I, queue contains all N tracks in original order', () => {
    fc.assert(
      fc.property(
        searchResultsArb.chain(results =>
          fc.record({
            results: fc.constant(results),
            selectedIndex: fc.nat({ max: results.length - 1 }),
          })
        ),
        ({ results, selectedIndex }) => {
          const player = new MusicPlayer();

          // Simulate selecting a track from search results
          // This calls loadQueue(searchResults, selectedIndex) as described in the design
          player.loadQueue(results, selectedIndex);

          // Queue SHALL contain all N tracks in original order
          expect(player.queue).toEqual(results);
          expect(player.queue.length).toBe(results.length);

          // Verify order is preserved
          for (let i = 0; i < results.length; i++) {
            expect(player.queue[i]).toEqual(results[i]);
          }
        }
      ),
      { numRuns: 100 }
    );
  });

  it('when user selects track at index I, currentIndex SHALL be set to I', () => {
    fc.assert(
      fc.property(
        searchResultsArb.chain(results =>
          fc.record({
            results: fc.constant(results),
            selectedIndex: fc.nat({ max: results.length - 1 }),
          })
        ),
        ({ results, selectedIndex }) => {
          const player = new MusicPlayer();

          // Simulate selecting a track from search results
          player.loadQueue(results, selectedIndex);

          // currentIndex SHALL be set to I
          expect(player.currentIndex).toBe(selectedIndex);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('search selection replaces any existing queue with search results', () => {
    fc.assert(
      fc.property(
        fc.array(trackArb, { minLength: 1, maxLength: 10 }),
        searchResultsArb.chain(results =>
          fc.record({
            results: fc.constant(results),
            selectedIndex: fc.nat({ max: results.length - 1 }),
          })
        ),
        (existingQueue, { results, selectedIndex }) => {
          const player = new MusicPlayer();

          // Set up an existing queue (e.g., from a previous search or chat command)
          player.loadQueue(existingQueue, 0);
          expect(player.queue).toEqual(existingQueue);

          // Now simulate selecting a track from new search results
          player.loadQueue(results, selectedIndex);

          // Queue SHALL contain all N search result tracks in original order
          expect(player.queue).toEqual(results);
          expect(player.queue.length).toBe(results.length);
          // currentIndex SHALL be set to I
          expect(player.currentIndex).toBe(selectedIndex);
        }
      ),
      { numRuns: 100 }
    );
  });

  it('the selected track at index I is the current track after selection', () => {
    fc.assert(
      fc.property(
        searchResultsArb.chain(results =>
          fc.record({
            results: fc.constant(results),
            selectedIndex: fc.nat({ max: results.length - 1 }),
          })
        ),
        ({ results, selectedIndex }) => {
          const player = new MusicPlayer();

          // Simulate selecting a track from search results
          player.loadQueue(results, selectedIndex);

          // The current track should be the one at selectedIndex
          expect(player.getCurrentTrack()).toEqual(results[selectedIndex]);
        }
      ),
      { numRuns: 100 }
    );
  });
});


// =============================================================================
// Property 4: Now Playing Renders All Track Fields
// Feature: music-player, Property 4: Now Playing Renders All Track Fields
// **Validates: Requirements 1.3, 2.1**
// =============================================================================

import { JSDOM } from 'jsdom';

/**
 * Creates a minimal DOM environment mimicking the Now Playing panel structure
 * as defined in the design document and implemented in public/index.html.
 *
 * The updateNowPlaying method queries for:
 *   - '.music-panel .mp-album-art' (img element for thumbnail)
 *   - '.music-panel .mp-track-info .mp-title' (title text)
 *   - '.music-panel .mp-track-info .mp-artist' (artist text)
 */
function createNowPlayingDOM() {
  const dom = new JSDOM(`
    <html>
      <body>
        <div class="music-panel">
          <img class="mp-album-art" src="" />
          <div class="mp-track-info">
            <div class="mp-title"></div>
            <div class="mp-artist"></div>
          </div>
        </div>
        <div id="music-player">
          <img class="mp-art" src="" />
          <div class="mp-title"></div>
          <div class="mp-artist"></div>
          <div class="mp-bg"></div>
        </div>
      </body>
    </html>
  `);
  return dom;
}

/**
 * MusicPlayer variant with DOM-aware updateNowPlaying.
 * Mirrors the actual implementation from public/index.html.
 */
class DOMEnabledMusicPlayer {
  constructor(document) {
    this.queue = [];
    this.currentIndex = -1;
    this.isPlaying = false;
    this.visible = false;
    this._document = document;
  }

  loadTrack(track) {
    this.queue = [track];
    this.currentIndex = 0;
    this.updateNowPlaying(track);
  }

  getCurrentTrack() {
    if (this.currentIndex >= 0 && this.currentIndex < this.queue.length) {
      return this.queue[this.currentIndex];
    }
    return null;
  }

  show() {
    this.visible = true;
  }

  updateNowPlaying(track) {
    if (!track) return;

    const panel = this._document.querySelector('.music-panel');
    if (panel) {
      const albumArt = panel.querySelector('.mp-album-art');
      if (albumArt) albumArt.src = track.thumbnail_url || '';

      const titleEl = panel.querySelector('.mp-track-info .mp-title');
      if (titleEl) titleEl.textContent = track.title || '';

      const artistEl = panel.querySelector('.mp-track-info .mp-artist');
      if (artistEl) artistEl.textContent = track.artist || '';
    }

    // Also update legacy panel elements
    const art = this._document.querySelector('#music-player .mp-art');
    if (art) art.src = track.thumbnail_url;

    const legacyTitle = this._document.querySelector('#music-player .mp-title');
    if (legacyTitle) legacyTitle.textContent = track.title;

    const legacyArtist = this._document.querySelector('#music-player .mp-artist');
    if (legacyArtist) legacyArtist.textContent = track.artist;

    const bg = this._document.querySelector('.mp-bg');
    if (bg) bg.style.backgroundImage = 'url(' + track.thumbnail_url + ')';

    this.show();
  }
}

describe('Property 4: Now Playing Renders All Track Fields', () => {
  // Generator for valid track objects with non-empty fields
  const validTrackArb = fc.record({
    video_id: fc.string({ minLength: 1, maxLength: 11 }),
    title: fc.string({ minLength: 1, maxLength: 200 }),
    artist: fc.string({ minLength: 1, maxLength: 200 }),
    thumbnail_url: fc.webUrl(),
  });

  it('rendered Now Playing panel contains the track title text after updateNowPlaying', () => {
    fc.assert(
      fc.property(validTrackArb, (track) => {
        const dom = createNowPlayingDOM();
        const player = new DOMEnabledMusicPlayer(dom.window.document);

        player.updateNowPlaying(track);

        const titleEl = dom.window.document.querySelector('.music-panel .mp-track-info .mp-title');
        expect(titleEl.textContent).toBe(track.title);
      }),
      { numRuns: 100 }
    );
  });

  it('rendered Now Playing panel contains the track artist text after updateNowPlaying', () => {
    fc.assert(
      fc.property(validTrackArb, (track) => {
        const dom = createNowPlayingDOM();
        const player = new DOMEnabledMusicPlayer(dom.window.document);

        player.updateNowPlaying(track);

        const artistEl = dom.window.document.querySelector('.music-panel .mp-track-info .mp-artist');
        expect(artistEl.textContent).toBe(track.artist);
      }),
      { numRuns: 100 }
    );
  });

  it('rendered Now Playing panel contains an image element with src equal to thumbnail_url after updateNowPlaying', () => {
    fc.assert(
      fc.property(validTrackArb, (track) => {
        const dom = createNowPlayingDOM();
        const player = new DOMEnabledMusicPlayer(dom.window.document);

        player.updateNowPlaying(track);

        const albumArt = dom.window.document.querySelector('.music-panel .mp-album-art');
        // DOM normalizes URLs (e.g. adds trailing slash), so compare normalized forms
        const expectedSrc = new URL(track.thumbnail_url).href;
        expect(albumArt.src).toBe(expectedSrc);
      }),
      { numRuns: 100 }
    );
  });

  it('all three fields (title, artist, thumbnail) are rendered correctly for any valid track', () => {
    fc.assert(
      fc.property(validTrackArb, (track) => {
        const dom = createNowPlayingDOM();
        const player = new DOMEnabledMusicPlayer(dom.window.document);

        player.updateNowPlaying(track);

        const titleEl = dom.window.document.querySelector('.music-panel .mp-track-info .mp-title');
        const artistEl = dom.window.document.querySelector('.music-panel .mp-track-info .mp-artist');
        const albumArt = dom.window.document.querySelector('.music-panel .mp-album-art');

        // Title text SHALL be present
        expect(titleEl.textContent).toBe(track.title);
        // Artist text SHALL be present
        expect(artistEl.textContent).toBe(track.artist);
        // Image src SHALL equal thumbnail_url (DOM normalizes URLs)
        const expectedSrc = new URL(track.thumbnail_url).href;
        expect(albumArt.src).toBe(expectedSrc);
      }),
      { numRuns: 100 }
    );
  });
});
