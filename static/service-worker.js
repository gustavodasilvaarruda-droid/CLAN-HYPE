const CACHE = 'hype-shell-v31-3';
const SHELL = ['/', '/static/style.css?v=3130', '/static/community_v30.css?v=3130', '/static/reino_v31.css?v=3130', '/static/breed_pricing_v313.css?v=3130', '/static/imagens/emblema_hype_novo.png', '/static/imagens/logodragaoh.png'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).catch(() => null));
  self.skipWaiting();
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  event.respondWith(fetch(event.request).catch(() => caches.match(event.request).then(r => r || caches.match('/'))));
});
