// Coupled with app.js takeHandoff(): cache name and handoff/<id> key path must match.
const HANDOFF_CACHE = 'repobox-handoff';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method === 'POST' && url.pathname === new URL('share', self.registration.scope).pathname) {
    event.respondWith(handleShare(event.request));
  }
});

async function handleShare(request) {
  const form = await request.formData();
  const payload = {
    title: String(form.get('title') || ''),
    text: String(form.get('text') || ''),
    url: String(form.get('url') || ''),
  };
  const id = crypto.randomUUID();
  const cache = await caches.open(HANDOFF_CACHE);
  await cache.put(new URL(`handoff/${id}`, self.registration.scope).href, new Response(JSON.stringify(payload)));
  return Response.redirect(new URL(`./#s=${id}`, self.registration.scope).href, 303);
}
