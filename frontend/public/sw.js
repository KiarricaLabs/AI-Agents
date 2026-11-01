const CACHE = "pat-v1";
self.addEventListener("install", (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(["/", "/index.html"])));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(self.clients.claim());
});
self.addEventListener("fetch", (e) => {
  // Only handle GET same-origin; never cache API responses.
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/workspaces") || url.pathname.startsWith("/episodes") || url.pathname.startsWith("/memory") || url.pathname.startsWith("/metrics")) {
    return; // do not cache API data / sensitive responses
  }
  e.respondWith(
    caches.match(e.request).then((cached) => {
      const fetched = fetch(e.request).then((resp) => {
        if (resp && resp.status === 200) {
          const clone = resp.clone();
          caches.open(CACHE).then((c) => c.put(e.request, clone));
        }
        return resp;
      });
      return cached || fetched;
    })
  );
});
