/* ============================================================
   동네링크 — 즉시 업데이트 PWA Service Worker (FINAL)
   - 최신 파일 즉시 적용 (skipWaiting + clients.claim)
   - 필수 파일 최소 캐싱
   - online-first 방식 (fetch → 실패하면 cache)
   ============================================================ */

const CACHE_NAME = "dongnelink-v1";   // ⭐ 버전 바꾸면 즉시 업데이트됨 (v2, v3 ...)

// ⭐ 실제 존재하는 파일만 캐싱함 (오류 방지)
const urlsToCache = [
  "/",                
  "/manifest.json",
  "/static/style.css",
];

/* -----------------------------
   INSTALL — 새로운 SW 즉시 적용
------------------------------ */
self.addEventListener("install", event => {
  self.skipWaiting();  // 새 버전 즉시 적용
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(urlsToCache))
  );
});

/* -----------------------------
   ACTIVATE — 오래된 캐시 삭제
------------------------------ */
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(key => key !== CACHE_NAME)
            .map(key => caches.delete(key))
      )
    )
  );
  self.clients.claim(); // 모든 탭에서 즉시 새 SW 적용
});

/* -----------------------------
   FETCH — 최신 서버 파일 우선
------------------------------ */
self.addEventListener("fetch", event => {
  event.respondWith(
    fetch(event.request)                 // 항상 최신 서버 먼저
      .then(response => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then(cache => {
          cache.put(event.request, clone);  // 최신 버전 캐싱
        });
        return response;
      })
      .catch(() => {
        // 오프라인일 때만 캐시 사용
        return caches.match(event.request);
      })
  );
});
