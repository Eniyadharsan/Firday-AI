/**
 * Service Worker for FRIDAY PWA
 * Enables offline shell caching and app-like behavior
 */

const CACHE_NAME = 'friday-v2';
const SHELL_FILES = [
  '/',
  '/manifest.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png'
];

// Install — cache app shell
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES))
  );
  self.skipWaiting();
});

// Allow the page to tell a waiting worker to activate immediately
self.addEventListener('message', (event) => {
  if (event.data === 'skipWaiting') self.skipWaiting();
});

// Activate — clean old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch — network first, fallback to cache for shell
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // API calls always go to network
  if (url.pathname.startsWith('/chat') || url.pathname.startsWith('/auth') ||
      url.pathname.startsWith('/speak') || url.pathname.startsWith('/ask') ||
      url.pathname.startsWith('/memories') || url.pathname.startsWith('/preferences') ||
      url.pathname.startsWith('/health')) {
    event.respondWith(fetch(event.request));
    return;
  }

  // Shell files — network first, fallback cache
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
