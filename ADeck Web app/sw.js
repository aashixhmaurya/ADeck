/* ADeck service worker: makes the app installable and lets the installed
   window open even while the local backend is stopped. Backend state
   (/api/*) is never cached. */

// Bump when the cached shell files change so old copies are dropped.
const CACHE = "adeck-shell-1";
const SHELL = [
  "/",
  "/index.html",
  "/style.css",
  "/script.js",
  "/manifest.webmanifest",
  "/icon-192.png",
  "/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE);
      await Promise.all(
        SHELL.map(async (url) => {
          try {
            const response = await fetch(new Request(url, { cache: "reload" }));
            if (response && response.ok) await cache.put(url, response);
          } catch (_) {
            /* a missing asset must not block installation */
          }
        })
      );
      await self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(
        names.filter((name) => name !== CACHE).map((name) => caches.delete(name))
      );
      await self.clients.claim();
    })()
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "adeck:skip-waiting") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // Live service state must always come from the backend, never from cache.
  if (url.pathname.startsWith("/api/")) return;

  event.respondWith(
    (async () => {
      const cache = await caches.open(CACHE);
      try {
        const response = await fetch(request);
        if (response && response.ok && response.type === "basic") {
          cache.put(request, response.clone()).catch(() => {});
        }
        return response;
      } catch (error) {
        const cached = await cache.match(request, { ignoreSearch: true });
        if (cached) return cached;
        if (request.mode === "navigate") {
          const shell =
            (await cache.match("/index.html")) || (await cache.match("/"));
          if (shell) return shell;
        }
        throw error;
      }
    })()
  );
});
