/* v0.15.4 · 移动端资产页：顶栏搜索「图标 → 浮层」
 * ----------------------------------------------------------------------------
 * 只干一件事：≤575.98px 时把整行搜索栏收成顶栏里的一枚图标，点开再浮出来。
 * 输入框本身没有移动、没有复制，仍是 #global-search —— script.js 的
 * onSearchInput / initGlobalSearchPopover / 结果浮层（z-index 4000）全部照旧，
 * 这里只负责给它换个「容器位置」，不碰任何搜索业务逻辑。
 */
(function () {
  "use strict";

  var MQ = "(max-width: 575.98px)";

  function ready() {
    var btn = document.getElementById("topbar-search-btn");
    var wrap = document.querySelector(".topbar-search");
    var input = document.getElementById("global-search");
    if (!btn || !wrap || !input) {
      return;
    }

    function isMobile() {
      return !window.matchMedia || window.matchMedia(MQ).matches;
    }

    function onKey(event) {
      if (event.key === "Escape") {
        event.stopPropagation();
        close();
      }
    }

    function onOutside(event) {
      if (wrap.contains(event.target) || btn.contains(event.target)) {
        return;
      }
      /* 结果列表是挂在 body 上的独立浮层，点它不算「点外面」 */
      if (event.target.closest && event.target.closest(".search-popover")) {
        return;
      }
      close();
    }

    /* 展开时把搜索块临时挂到 body：
       顶栏有 backdrop-filter，会成为 fixed 子元素的包含块，left/right 会按
       「顶栏的内边距盒」算而不是视口，实测偏 12px 且右边缘顶出屏幕。
       挂到 body 后 left:12/right:12 就是视口坐标，不再受祖先链影响；
       收起时按记录的原位还回去，桌面端结构完全不变。 */
    var home = { parent: null, next: null };

    function open() {
      if (wrap.parentNode && wrap.parentNode !== document.body) {
        home.parent = wrap.parentNode;
        home.next = wrap.nextSibling;
        document.body.appendChild(wrap);
      }
      /* 贴在顶栏下沿 6px：顶栏保持完整可见，搜索图标本身就成了「再点一下收起」的开关，
         触屏上不必依赖 Esc 才能退出 */
      var bar = document.querySelector(".topbar");
      if (bar) {
        wrap.style.top = Math.round(bar.getBoundingClientRect().bottom + 6) + "px";
      }
      wrap.classList.add("is-open");
      btn.setAttribute("aria-expanded", "true");
      document.addEventListener("keydown", onKey, true);
      document.addEventListener("pointerdown", onOutside, true);
      /* 等浮层完成布局再聚焦，否则 iOS 会把页面顶上去 */
      window.setTimeout(function () {
        try {
          input.focus();
          input.setSelectionRange(input.value.length, input.value.length);
        } catch (error) { /* 忽略：聚焦失败不影响输入 */ }
      }, 30);
    }

    function close() {
      if (!wrap.classList.contains("is-open")) {
        return;
      }
      wrap.classList.remove("is-open");
      btn.setAttribute("aria-expanded", "false");
      wrap.style.top = "";
      if (home.parent && wrap.parentNode === document.body) {
        home.parent.insertBefore(wrap, home.next);
        home.next = null;
      }
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onOutside, true);
      try { input.blur(); } catch (error) { /* 忽略 */ }
    }

    btn.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      if (!isMobile()) {
        return;
      }
      if (wrap.classList.contains("is-open")) {
        close();
      } else {
        open();
      }
    });

    /* 点搜索结果是「完成一次搜索」，浮层收起来；点底部 tab 切页同理 */
    document.addEventListener("click", function (event) {
      var target = event.target;
      if (!target || !target.closest) {
        return;
      }
      if (target.closest(".search-pop-item") || target.closest(".mtab-item")) {
        close();
      }
    });

    /* 从手机宽度拖回桌面：把残留的浮层状态清掉，避免它变成固定层挡内容 */
    if (window.matchMedia) {
      var mq = window.matchMedia(MQ);
      var onChange = function () {
        if (!mq.matches) {
          close();
        }
      };
      if (mq.addEventListener) {
        mq.addEventListener("change", onChange);
      } else if (mq.addListener) {
        mq.addListener(onChange);
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ready, true);
  } else {
    ready();
  }
})();
