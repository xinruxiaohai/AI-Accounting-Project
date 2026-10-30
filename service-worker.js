/* AI记账管家 · Service Worker（v0.07.2）
 *
 * 目标：装到桌面后断网也能打开，核心样式 / 脚本 / 图表库全部走本地缓存。
 * 策略：
 *   - 页面导航：network-first，请求失败回退缓存的首页（离线打开还能看上次的看板）
 *   - 静态资源：stale-while-revalidate，先用缓存秒开，后台顺手更新
 *   - /api/ 与后台页面：完全不缓存，避免把旧余额当成新数据
 */
const CACHE_NAME = "ai-accounting-v0.12.6";
const CACHE_PREFIX = "ai-accounting-";
const PRECACHE_URLS = [
  "/",
  "/manifest.json",
  "/static/style.css",
  "/static/script.js",
  "/static/vendor/bootstrap.min.css",
  "/static/vendor/bootstrap.bundle.min.js",
  "/static/vendor/math.min.js",
  "/static/vendor/echarts.min.js",
  "/static/vendor/sortable.min.js",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/icon-maskable-512.png",
  "/static/icons/favicon.png"
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      // 逐个 add：某一个文件 404 不应该让整个安装失败
      return Promise.all(
        PRECACHE_URLS.map(function (url) {
          return cache.add(new Request(url, { cache: "reload" })).catch(function () {});
        })
      );
    }).then(function () {
      return self.skipWaiting();
    })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys
          .filter(function (key) {
            return key.indexOf(CACHE_PREFIX) === 0 && key !== CACHE_NAME;
          })
          .map(function (key) {
            return caches.delete(key);
          })
      );
    }).then(function () {
      return self.clients.claim();
    })
  );
});

self.addEventListener("fetch", function (event) {
  const request = event.request;
  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return;
  }

  // 接口、健康检查、开发者后台：永远走网络，不缓存
  if (
    url.pathname.indexOf("/api/") === 0 ||
    url.pathname === "/health" ||
    url.pathname === "/admin"
  ) {
    return;
  }

  // 页面：先网络，断网再回退首页缓存
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then(function (response) {
          if (response && response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then(function (cache) {
              cache.put("/", copy);
            }).catch(function () {});
          }
          return response;
        })
        .catch(function () {
          return caches.match("/").then(function (cached) {
            return cached || caches.match(request);
          });
        })
    );
    return;
  }

  // 静态资源：缓存优先，后台更新
  event.respondWith(
    caches.match(request).then(function (cached) {
      const network = fetch(request)
        .then(function (response) {
          if (response && response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then(function (cache) {
              cache.put(request, copy);
            }).catch(function () {});
          }
          return response;
        })
        .catch(function () {
          return cached;
        });
      return cached || network;
    })
  );
});
