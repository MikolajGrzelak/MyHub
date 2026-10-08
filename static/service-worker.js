const VERSION = "2026.10.08.5";
const PREFIX = "myhub-";
const SHELL = `${PREFIX}shell-${VERSION}`;
const PAGES = `${PREFIX}pages-${VERSION}`;
const API = `${PREFIX}api-${VERSION}`;
const ASSETS = [
  "/",
  "/offline",
  `/static/css/app.css?v=${VERSION}`,
  `/static/js/preferences.js?v=${VERSION}`,
  `/static/js/app.js?v=${VERSION}`,
  `/static/js/hub.js?v=${VERSION}`,
  "/static/manifest.json",
  "/static/icon.svg",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/apple-touch-icon.png",
];
self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((cache) => cache.addAll(ASSETS)));
});
self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") self.skipWaiting();
});
self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter(
            (key) =>
              key.startsWith(PREFIX) && ![SHELL, PAGES, API].includes(key),
          )
          .map((key) => caches.delete(key)),
      );
      await self.clients.claim();
    })(),
  );
});
async function putBounded(cacheName, request, response, limit) {
  const cache = await caches.open(cacheName);
  await cache.put(request, response);
  const keys = await cache.keys();
  for (const key of keys.slice(0, Math.max(0, keys.length - limit)))
    await cache.delete(key);
}
async function networkFirst(event, cacheName, limit, navigation = false) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 7000);
  let response;
  try {
    response = await fetch(event.request, { signal: controller.signal });
    if (response.ok && response.type === "basic") {
      event.waitUntil(
        putBounded(cacheName, event.request, response.clone(), limit).catch(
          () => {},
        ),
      );
      return response;
    }
  } catch {
    /* Network unavailable, use only the exact requested view. */
  } finally {
    clearTimeout(timeout);
  }
  const cached =
    (await (
      await caches.open(cacheName)
    ).match(event.request, { ignoreSearch: false })) ||
    (await (
      await caches.open(SHELL)
    ).match(event.request, { ignoreSearch: false }));
  if (cached) {
    if (!navigation) {
      const headers = new Headers(cached.headers);
      headers.set("X-MyHub-Offline", "1");
      return new Response(await cached.arrayBuffer(), {
        status: cached.status,
        headers,
      });
    }
    return cached;
  }
  if (navigation)
    return (
      (await caches.match("/offline")) ||
      new Response(
        "MyHub jest offline. Spróbuj ponownie po odzyskaniu połączenia.",
        {
          status: 503,
          headers: { "Content-Type": "text/plain; charset=utf-8" },
        },
      )
    );
  return (
    response ||
    new Response(JSON.stringify({ error: "offline" }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    })
  );
}
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin)
    return;
  if (event.request.mode === "navigate")
    event.respondWith(networkFirst(event, PAGES, 24, true));
  else if (url.pathname === "/api/feed")
    event.respondWith(networkFirst(event, API, 24));
  else if (url.pathname.startsWith("/static/"))
    event.respondWith(
      caches
        .open(SHELL)
        .then(
          async (cache) =>
            (await cache.match(event.request)) ||
            networkFirst(event, SHELL, 40),
        ),
    );
  // Health checks and external images always go to the network and aren't cached.
});
