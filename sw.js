const CACHE = 'sportbit-v6';
const ASSETS = [
  '/sportbit/',
  '/sportbit/index.html',
  '/sportbit/style.css',
  '/sportbit/app.js',
  '/sportbit/manifest.json',
  '/sportbit/icon.svg',
  '/sportbit/icon-maskable.svg',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('push', e => {
  const data = e.data?.json() ?? {};
  e.waitUntil(
    self.registration.showNotification(data.title ?? 'RalphFit', {
      body: data.body ?? '',
      icon: '/sportbit/icon.svg',
      badge: '/sportbit/icon-maskable.svg',
      data: { url: data.url ?? '/sportbit/' },
    })
  );
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.openWindow(e.notification.data.url));
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // GitHub API-verzoeken altijd passthrough (geen cache)
  if (url.hostname === 'api.github.com') return;

  // Network-first voor alles: altijd verse code en data, cache als fallback
  e.respondWith(
    fetch(e.request)
      .then(res => {
        if (res.ok) {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return res;
      })
      .catch(() => caches.match(e.request).then(cached =>
        cached || caches.match('/sportbit/index.html')
      ))
  );
});
