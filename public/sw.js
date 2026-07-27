/**
 * Service Worker for FRIDAY PWA
 *
 * NOTE: Shell caching was removed because it caused stale pages to persist
 * after updates. This worker now purges all old caches and always serves
 * fresh content from the network. It also cleans up any previous caches
 * (e.g. the old "jarvis-v1" shell cache) on activation.
 */

// Install immediately, don't wait for old worker to release control
self.addEventListener('install', () => {
  self.skipWaiting();
});

// On activate: delete every cache and take control of all open pages
self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => caches.delete(k)));
      await self.clients.claim();
    })()
  );
});

// Always go to the network — never serve a cached shell
self.addEventListener('fetch', (event) => {
  event.respondWith(fetch(event.request));
});

// Allow the page to force activation of a waiting worker
// Verify the message origin to prevent cross-origin attacks (SonarCloud S2819)
self.addEventListener('message', (event) => {
  // SERVICE WORKER ORIGIN VERIFICATION (SonarCloud S2819 compliant)
  // 
  // In service workers, same-origin messages have:
  //   - event.origin === '' (empty string) OR event.origin === self.location.origin
  //   - event.source is a WindowClient or Client object
  //
  // Cross-origin messages (from iframes, other windows) have:
  //   - event.origin set to the sender's actual origin (e.g., 'https://evil.com')
  //
  // We MUST explicitly verify the origin before processing ANY message.
  
  const trustedOrigin = self.location.origin;
  const messageOrigin = event.origin;
  
  // Verify origin: allow empty string (same-origin) or exact match to our origin
  // Reject any message with a different, non-empty origin
  const isOriginTrusted = messageOrigin === '' || messageOrigin === trustedOrigin;
  
  if (!isOriginTrusted) {
    console.warn('[SW] Rejected message from untrusted origin:', messageOrigin);
    return;
  }
  
  // Ensure the message comes from a valid client (WindowClient or Client)
  // This guards against spoofed or synthetic message events
  if (!event.source) {
    console.warn('[SW] Rejected message with no source client');
    return;
  }
  
  // Process trusted same-origin messages
  if (event.data === 'skipWaiting') {
    self.skipWaiting();
  }
});
