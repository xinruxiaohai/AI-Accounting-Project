/* ============================================================
 * v0.14.3 · 全局临时通知跑马灯
 * ------------------------------------------------------------
 * 首页 / 登录页 / 注册页 / 管理后台共用这一份：
 *   1. 页面加载即请求 GET /api/notices/active_temp（公开接口，未登录也能取）；
 *   2. 有生效条目就在顶部渲染 #global-marquee 并开始滚动，
 *      多条用「|」隔开，复制一份做无缝循环；
 *   3. 到结束时间自动隐藏；隐藏时、服务器版本变化时、网络恢复时
 *      各触发一次全量数据刷新（页面自己暴露 window.__zhRefresh）；
 *   4. 每 60 秒再对一次时，后台改了通知不用刷新页面就能生效。
 * ============================================================ */
(function () {
  "use strict";

  var POLL_MS = 60000;
  var DESKTOP_SPEED = 68;   // px / 秒
  var MOBILE_SPEED = 42;    // 手机慢一点，看得清
  var VERSION_KEY = "zh_app_version";

  var state = {
    notices: [],
    serverOffset: 0,
    hideTimer: 0,
    pollTimer: 0,
    refreshing: false,
    booted: false,
    emptyRefreshDone: false
  };

  function isMobile() {
    return window.matchMedia("(max-width: 640px)").matches;
  }

  function parseServerTime(text) {
    var value = String(text || "").trim().replace(" ", "T");
    if (!value) {
      return 0;
    }
    var stamp = Date.parse(value);
    return isNaN(stamp) ? 0 : stamp;
  }

  function ensureNode() {
    var node = document.getElementById("global-marquee");
    if (node) {
      // 模板里已静态注入；极端情况下（老模板缓存）缺 track 就补一个
      if (!node.querySelector(".global-marquee-track")) {
        var fallbackTrack = document.createElement("div");
        fallbackTrack.className = "global-marquee-track";
        node.appendChild(fallbackTrack);
      }
      return node;
    }
    node = document.createElement("div");
    node.id = "global-marquee";
    node.className = "global-marquee";
    node.setAttribute("role", "status");
    node.setAttribute("aria-live", "polite");
    node.hidden = true;

    var track = document.createElement("div");
    track.className = "global-marquee-track";
    node.appendChild(track);

    if (document.body) {
      document.body.insertBefore(node, document.body.firstChild);
    } else {
      document.addEventListener("DOMContentLoaded", function () {
        document.body.insertBefore(node, document.body.firstChild);
      });
    }
    return node;
  }

  /* ---------- 渲染 ---------- */

  /* 每一组 = 所有生效通知 + 竖线分隔 + 组首/组尾的大段留白。
     留白放在 group 上而不是单条 item 上，复制多份做无缝循环时
     「上一组最后一句 → 下一组第一句」之间才不会黏在一起。 */
  function buildGroup(notices) {
    var group = document.createElement("span");
    group.className = "global-marquee-group";
    notices.forEach(function (notice, index) {
      if (index > 0) {
        var sep = document.createElement("span");
        sep.className = "global-marquee-sep";
        sep.textContent = "|";
        group.appendChild(sep);
      }
      var item = document.createElement("span");
      item.className = "global-marquee-item";
      item.textContent = notice.content;
      group.appendChild(item);
    });
    return group;
  }

  function render(notices) {
    var node = ensureNode();
    var track = node.querySelector(".global-marquee-track");
    if (!track) {
      return;
    }
    track.textContent = "";

    // 必须先显示再量宽度：#global-marquee[hidden] 是 display:none，
    // 隐藏状态下 scrollWidth 恒为 0，量不到就直接退化了。
    node.hidden = false;
    document.body.classList.add("has-global-marquee");

    // 先铺一份，量出这一组有多宽
    var firstGroup = buildGroup(notices);
    track.appendChild(firstGroup);
    var groupWidth = firstGroup.getBoundingClientRect().width || track.scrollWidth;
    if (!groupWidth) {
      hide();
      return;
    }

    // 内容太短时多铺几份，保证滚起来不会留一大片空白
    var viewport = node.clientWidth || window.innerWidth || 360;
    var copies = Math.max(1, Math.ceil(viewport / groupWidth));
    if (copies > 8) {
      copies = 8;
    }
    while (copies > 1) {
      track.appendChild(buildGroup(notices));
      copies -= 1;
    }

    // 再整份复制一次：translateX(-50%) 正好回到同一个起点，无缝衔接
    var totalCopies = 0;
    var children = Array.prototype.slice.call(track.childNodes);
    children.forEach(function (child) {
      track.appendChild(child.cloneNode(true));
      totalCopies += 1;
    });

    var speed = isMobile() ? MOBILE_SPEED : DESKTOP_SPEED;
    var distance = track.scrollWidth / 2;
    var duration = Math.max(8, Math.round(distance / speed));

    track.style.animation = "none";
    void track.offsetWidth;  // 强制回流，让动画从头开始
    track.style.animation = "";
    track.style.animationDuration = duration + "s";
  }

  function hide() {
    var node = document.getElementById("global-marquee");
    if (node) {
      node.hidden = true;
    }
    document.body.classList.remove("has-global-marquee");
  }

  /* ---------- 刷新联动 ---------- */

  function notifyDataRefresh(reason) {
    if (state.refreshing) {
      return;
    }
    state.refreshing = true;
    window.setTimeout(function () {
      state.refreshing = false;
    }, 5000);

    // 首页 / 登录后的看板：script.js 暴露的一次性全量刷新
    if (typeof window.__zhRefresh === "function") {
      try {
        window.__zhRefresh(reason);
      } catch (error) {
        // 刷新失败不影响跑马灯本身
      }
    }
    // 管理后台 / 其它模块可以监听这个事件重拉自己的面板
    try {
      document.dispatchEvent(new CustomEvent("zh:data-refresh", { detail: { reason: reason } }));
    } catch (error) {
      // 老浏览器没有 CustomEvent 构造器时忽略
    }
  }

  function checkVersion(version) {
    if (!version) {
      return;
    }
    var last = "";
    try {
      last = window.sessionStorage.getItem(VERSION_KEY) || "";
      window.sessionStorage.setItem(VERSION_KEY, version);
    } catch (error) {
      return;
    }
    if (last && last !== version) {
      notifyDataRefresh("version");
    }
  }

  /* ---------- 数据 ---------- */

  function scheduleExpiry(notices) {
    window.clearTimeout(state.hideTimer);
    var now = Date.now() + state.serverOffset;
    var next = 0;
    notices.forEach(function (notice) {
      var end = parseServerTime(notice.end_time);
      if (end && end > now && (!next || end < next)) {
        next = end;
      }
    });
    if (!next) {
      return;
    }
    var delay = Math.min(Math.max(next - now + 1500, 1000), 2147000000);
    state.hideTimer = window.setTimeout(function () {
      load();
    }, delay);
  }

  function apply(data) {
    var notices = (data && data.notices) || [];
    var hadNotices = state.notices.length > 0;
    state.notices = notices;
    if (data && data.server_time) {
      var serverStamp = parseServerTime(data.server_time);
      if (serverStamp) {
        state.serverOffset = serverStamp - Date.now();
      }
    }
    checkVersion(data && data.version);

    if (!notices.length) {
      hide();
      window.clearTimeout(state.hideTimer);
      // 「一旦获取不到生效的通知」就补一次全量刷新：
      //   * 由有变无（维护结束）→ 用户在离线期间盯着的旧数据要重拉；
      //   * 首屏本来就没有通知 → 同样对齐一次服务端最新账本。
      // 用 emptyRefreshDone 保证「一次」，恢复播放时复位，下次结束还能再刷。
      if (hadNotices || !state.emptyRefreshDone) {
        state.emptyRefreshDone = true;
        notifyDataRefresh(hadNotices ? "marquee-ended" : "marquee-empty");
      }
      return;
    }
    state.emptyRefreshDone = false;
    render(notices);
    scheduleExpiry(notices);
  }

  function load() {
    return fetch("/api/notices/active_temp", {
      method: "GET",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      cache: "no-store"
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }
        return response.json();
      })
      .then(apply)
      .catch(function () {
        // 接口挂了就保持现状，下一轮再试；不要把跑马灯抖没
      });
  }

  /* ---------- 启动 ---------- */

  function boot() {
    if (state.booted) {
      return;
    }
    state.booted = true;
    ensureNode();
    load();
    state.pollTimer = window.setInterval(load, POLL_MS);

    // 网络恢复：纯在线系统，没有本地待同步账单，直接拉一次最新数据
    window.addEventListener("online", function () {
      load();
      notifyDataRefresh("online");
    });

    // 手机 / 桌面切换时重新量宽度，滚动速度跟着变
    var query = window.matchMedia("(max-width: 640px)");
    var onChange = function () {
      if (state.notices.length) {
        render(state.notices);
      }
    };
    if (query.addEventListener) {
      query.addEventListener("change", onChange);
    } else if (query.addListener) {
      query.addListener(onChange);
    }
  }

  window.zhMarqueeRefresh = load;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();