const CACHE = 'hype-shell-v31-4';
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
  // Nunca apresentar o Início no lugar de outra página quando houver falha na rede.
  // Esse fallback antigo fazia a navegação parecer presa na página inicial.
  if (event.request.mode === 'navigate') {
    event.respondWith(fetch(event.request).catch(async () => {
      const cached = await caches.match(event.request);
      if (cached) return cached;
      return new Response('Não foi possível abrir esta página. Verifique sua conexão e tente novamente.', {
        status: 503,
        headers: { 'Content-Type': 'text/plain; charset=utf-8' }
      });
    }));
    return;
  }
  event.respondWith(fetch(event.request).catch(async () => {
    return (await caches.match(event.request)) || Response.error();
  }));
});
