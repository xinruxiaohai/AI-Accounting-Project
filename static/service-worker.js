/* 智汇账 · Service Worker（v0.15.0-mobile1）
 *
 * 目标：装到桌面后是真正的全屏独立窗口，断网也能打开完整界面。
 * 策略：
 *   - 页面导航：network-first，请求失败回退缓存的首页（离线打开还能看上次的看板）
 *   - 静态资源：stale-while-revalidate，先用缓存秒开，后台顺手更新
 *   - /api/ 与后台页面：完全不缓存，避免把旧余额当成新数据
 *
 * v0.15.0 修复：预缓存清单原先只列了不带版本号的 /static/style.css 等裸路径，
 * 而模板实际请求的是 ?v=... 的带参 URL，于是「添加到桌面」后首次离线打开
 * 样式与 auth/charts/invest 三个脚本全部落空、只剩一个空壳页面。
 * 现在按模板真实 URL 精确预缓存，并同步 bump CACHE_NAME 与模板 ?v=。
 */
const CACHE_NAME = "ai-accounting-v0.15.0-mobile1";
const CACHE_PREFIX = "ai-accounting-";
const ASSET_VERSION = "0.15.0-mobile1";
const PRECACHE_URLS = [
  "/",
  "/manifest.json",
  "/manifest.json?v=" + ASSET_VERSION,
  "/static/style.css",
  "/static/style.css?v=" + ASSET_VERSION,
  "/static/script.js",
  "/static/script.js?v=" + ASSET_VERSION,
  "/static/auth-v012.js?v=" + ASSET_VERSION,
  "/static/access-guard.js?v=" + ASSET_VERSION,
  "/static/charts-v013.js?v=" + ASSET_VERSION,
  "/static/invest-v0133.js?v=" + ASSET_VERSION,
  "/static/vendor/bootstrap.min.css",
  "/static/vendor/bootstrap.bundle.min.js",
  "/static/vendor/math.min.js",
  "/static/vendor/echarts.min.js",
  "/static/vendor/sortable.min.js",
  "/static/images/logo-main.png",
  "/static/images/logo-main.png?v=" + ASSET_VERSION
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    // 版本串退回旧值时浏览器里可能残留同名旧缓存，install 先删同名缓存再重建，
    // 避免强刷后仍拿到上一轮旧 CSS / JS。
    caches.delete(CACHE_NAME)
      .then(function () { return caches.open(CACHE_NAME); })
      .then(function (cache) {
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
      // 清掉所有旧版本缓存，保证升级后不会继续命中上一版的旧 style.css / script.js
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

// 新版本发布后，页面可主动 postMessage({type:"SKIP_WAITING"}) 让独立窗口立刻吃到新资源，
// 不必等所有已打开的 PWA 窗口都关掉。
self.addEventListener("message", function (event) {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
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
