// Offline shell only. Money data is never cached: a stale balance is worse
// than no balance, and this app is one login away from being wrong on purpose.
const SHELL = 'tally-shell-v1'
const SHELL_FILES = ['/', '/manifest.webmanifest', '/icon-192.png', '/favicon.svg']

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_FILES)).then(() => self.skipWaiting()))
})

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url)
  if (e.request.method !== 'GET' || url.origin !== self.location.origin) return
  // Never serve API responses from cache.
  if (url.pathname.startsWith('/api/') || url.pathname === '/healthz') return

  // Hashed build assets are immutable: cache first, and fill the cache as they load.
  if (url.pathname.startsWith('/assets/')) {
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request).then((res) => {
      const copy = res.clone()
      caches.open(SHELL).then((c) => c.put(e.request, copy))
      return res
    })))
    return
  }

  // Everything else (the app shell): network first, cache as a fallback offline.
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone()
        caches.open(SHELL).then((c) => c.put(e.request, copy))
        return res
      })
      .catch(() => caches.match(e.request).then((hit) => hit || caches.match('/'))),
  )
})
