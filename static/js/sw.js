/* Service worker do PWA do painel admin (atendentes/profissionais).
 * Escopo registrado como /admin/ (ver base.html). Nunca cacheia respostas de
 * navegação nem de API — agenda, comandas etc. precisam sempre vir da rede
 * para não exibir dado desatualizado; só o "app shell" estático (css/js/
 * imagens) e a página offline.html ficam em cache. */
const SW_VERSION = 'v1';
const STATIC_CACHE = 'unitto-static-' + SW_VERSION;
const OFFLINE_URL = '/static/offline.html';

const PRECACHE_URLS = [
  OFFLINE_URL,
  '/static/css/admin.css',
  '/static/images/logo.png',
];

self.addEventListener('install', function (event) {
  self.skipWaiting();
  event.waitUntil(
    caches.open(STATIC_CACHE).then(function (cache) {
      return cache.addAll(PRECACHE_URLS);
    })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.filter(function (k) { return k !== STATIC_CACHE; })
            .map(function (k) { return caches.delete(k); })
      );
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (event) {
  const req = event.request;
  if (req.method !== 'GET') return; // nunca intercepta POST (login, salvar agendamento etc.)

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Navegação (abrir uma página do painel): sempre tenta a rede primeiro;
  // sem internet, mostra a página offline em vez do erro do navegador.
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(function () {
        return caches.match(OFFLINE_URL);
      })
    );
    return;
  }

  // Assets estáticos (css/js/imagens/ícones): cache-first, atualizando em
  // segundo plano a cada visita.
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.open(STATIC_CACHE).then(function (cache) {
        return cache.match(req).then(function (cached) {
          const network = fetch(req).then(function (resp) {
            if (resp && resp.ok) cache.put(req, resp.clone());
            return resp;
          }).catch(function () { return cached; });
          return cached || network;
        });
      })
    );
  }
  // Qualquer outra requisição (APIs, dados) passa direto pela rede.
});
