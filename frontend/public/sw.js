const CACHE = "pat-v1";
self.addEventListener("install", (e: any) => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(["/", "/index.html"])));
});
self.addEventListener("fetch", (e: any) => {
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request)).catch(() => caches.match("/index.html")));
});