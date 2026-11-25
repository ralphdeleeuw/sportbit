const CACHE = 'sportbit-v18';
const ASSETS = [
  '/sportbit/',
  '/sportbit/index.html',
  '/sportbit/style.css',
  '/sportbit/js/core.js',
  '/sportbit/js/ui.js',
  '/sportbit/js/push.js',
  '/sportbit/js/state.js',
  '/sportbit/js/wod.js',
  '/sportbit/js/activities.js',
  '/sportbit/js/data.js',
  '/sportbit/js/tabs.js',
  '/sportbit/js/workflows.js',
  '/sportbit/js/health.js',
  '/sportbit/js/personal.js',
  '/sportbit/js/running.js',
  '/sportbit/js/injuries.js',
  '/sportbit/js/homeworkout.js',
  '/sportbit/js/insights.js',
  '/sportbit/js/main.js',
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
