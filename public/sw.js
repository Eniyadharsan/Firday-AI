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
self.addEventListener('message', (event) => {
  if (event.data === 'skipWaiting') self.skipWaiting();
});
