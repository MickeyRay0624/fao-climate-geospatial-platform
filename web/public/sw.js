const CACHE = "fao-extension-shell-v2";
const SHELL = ["/", "/manifest.webmanifest", "/extension-icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))));
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const neverCache =
    url.pathname.startsWith("/api/")
    || url.pathname.startsWith("/objects/")
    || url.pathname.includes("/media/");
  if (event.request.method !== "GET" || neverCache) return;
  if (event.request.mode === "navigate") {
    event.respondWith(fetch(event.request).catch(() => caches.match("/")));
    return;
  }
  event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request).then((response) => {
    if (url.origin === self.location.origin && response.ok) {
      const stored = response.clone();
      event.waitUntil(caches.open(CACHE).then((cache) => cache.put(event.request, stored)));
    }
    return response;
  })));
});
