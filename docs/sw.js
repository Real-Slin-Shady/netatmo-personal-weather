// Copyright (c) 2024 Nils Tinner. All Rights Reserved.
// Service worker: serve cached assets when offline, always revalidate JSON data.
const CACHE = 'weather-v1';
const STATIC = ['./index.html', './config.js', './manifest.json'];

self.addEventListener('install', e =>
    e.waitUntil(caches.open(CACHE).then(c => c.addAll(STATIC)))
);

self.addEventListener('fetch', e => {
    const url = new URL(e.request.url);
    // Always fetch JSON fresh; serve static assets from cache on failure
    if (url.pathname.endsWith('.json')) {
        e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    } else {
        e.respondWith(
            caches.match(e.request).then(cached =>
                cached || fetch(e.request).then(res => {
                    caches.open(CACHE).then(c => c.put(e.request, res.clone()));
                    return res;
                })
            )
        );
    }
});
