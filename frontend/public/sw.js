// CardioCoach Service Worker
// Prompt natif du navigateur seulement – pas d'UI custom
// Ce SW permet l'installabilité PWA et le cache offline basique

const CACHE_NAME = 'cardiocoach-v1';
const OFFLINE_URL = '/offline.html';

// Assets à mettre en cache immédiatement
const PRECACHE_ASSETS = [
  '/',
  '/manifest.json',
  '/icons/icon-192x192.png',
  '/icons/icon-512x512.png'
];

// Installation du Service Worker
self.addEventListener('install', (event) => {
  console.log('[SW] Installing Service Worker...');
  
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        console.log('[SW] Pre-caching app shell');
        return cache.addAll(PRECACHE_ASSETS);
      })
      .then(() => {
        // Force le SW à devenir actif immédiatement
        return self.skipWaiting();
      })
  );
});

// Activation - nettoyage des anciens caches
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating Service Worker...');
  
  event.waitUntil(
    caches.keys()
      .then((cacheNames) => {
        return Promise.all(
          cacheNames
            .filter((cacheName) => cacheName !== CACHE_NAME)
            .map((cacheName) => {
              console.log('[SW] Deleting old cache:', cacheName);
              return caches.delete(cacheName);
            })
        );
      })
      .then(() => {
        // Prend le contrôle de toutes les pages immédiatement
        return self.clients.claim();
      })
  );
});

// Stratégie de fetch: Network First avec fallback cache
self.addEventListener('fetch', (event) => {
  // Ignore les requêtes non-GET
  if (event.request.method !== 'GET') {
    return;
  }

  // Ignore les requêtes vers des APIs externes
  if (event.request.url.includes('/api/')) {
    return;
  }

  // Ignore les requêtes chrome-extension et autres schemes non-http
  if (!event.request.url.startsWith('http')) {
    return;
  }

  event.respondWith(
    // Essaie d'abord le réseau
    fetch(event.request)
      .then((response) => {
        // Clone la réponse car elle ne peut être consommée qu'une fois
        const responseClone = response.clone();
        
        // Met en cache les réponses réussies
        if (response.status === 200) {
          caches.open(CACHE_NAME)
            .then((cache) => {
              cache.put(event.request, responseClone);
            });
        }
        
        return response;
      })
      .catch(() => {
        // En cas d'erreur réseau, utilise le cache
        return caches.match(event.request)
          .then((cachedResponse) => {
            if (cachedResponse) {
              return cachedResponse;
            }
            
            // Pour les navigations, retourne la page offline si disponible
            if (event.request.mode === 'navigate') {
              return caches.match(OFFLINE_URL);
            }
            
            // Sinon, retourne une erreur
            return new Response('Offline', {
              status: 503,
              statusText: 'Service Unavailable'
            });
          });
      })
  );
});

// Écoute les messages pour forcer la mise à jour
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

console.log('[SW] Service Worker loaded - PWA installability enabled');
