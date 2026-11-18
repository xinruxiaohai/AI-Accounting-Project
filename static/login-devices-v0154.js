/* v0.15.4 · 设置页「最近登录设备」面板
 * ----------------------------------------------------------------------------
 * 契约：GET /api/user/login-devices
 *   → {"devices":[{"device":"Windows 电脑","browser":"Edge","city":"东莞",
 *                  "last_at":"2026-11-18 15:20:31"}]}
 *
 * 三条硬规矩：
 * 1) 只渲染三样——设备类型、城市、最近登录时间。IP / 经纬度 / 街道 / 设备唯一标识
 *    即使接口带回来了也不读、不落 DOM（隐私红线）。
 * 2) 接口失败就是「暂时无法获取」，绝不弹 toast、不抛错、不写 console。
 *    （所以这里用 XHR 而不是 window.fetch：auth-v012 给 fetch 包了一层，
 *      断网 / 5xx 会弹全局搞笑 toast，放在设置页里太吵。）
 * 3) 「当前设备」只在 UA 比对成立时标，且只标第一条；比对上不就不标，不硬猜。
 *
 * v0.15.4 退出设备：
 * - GET 返回带 id，每行右侧一个 ×（24px 圆形，移动端靠 padding 撑到 32 热区）。
 * - 确认走项目统一 confirmAction()（Promise 风格，禁用原生 alert/confirm）；
 *   成功 DELETE /api/user/login-devices/<id>，失败 Toast + 保留该行。
 * - 这里用 XHR 而不是 window.fetch：auth-v012 给 fetch 包了一层会弹全局 toast。
 */
(function () {
  "use strict";

  var API = "/api/user/login-devices";
  var TOKEN_KEY = "ai_accounting_token";
  var MAX_ITEMS = 5;          // 接口给 10 条，前端只留最近 5 条
  var REFRESH_MS = 30000;     // 反复切 tab 不重复打接口
  var TEXT = {
    loading: "正在加载…",
    error: "暂时无法获取",
    empty: "暂无记录",
    unknownCity: "未知地区",
    unknownDevice: "未知设备",
    current: "当前设备",
    revokeLabel: "退出该设备",
    revokeSuccess: "已退出该设备",
    revokeFail: "操作失败，请稍后重试",
  };
  var WEEK = 86400000;

  var listEl = null;
  var state = { inflight: false, loaded: false, lastAt: 0, devices: [], revoking: false };
  var current = null;         // UA 自报的家门，懒算一次
  var REVOKE_LOCK_MS = 400;   // 确认后 0.4s 内按钮 disabled，防连点重复删除

  /* ---------------- 静默请求（同 theme 同步一套写法） ---------------- */

  function readToken() {
    try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (error) { return ""; }
  }

  function silentRequest(method, url, done) {
    if (!url || navigator.onLine === false) { done(null, 0); return; }
    var xhr;
    try { xhr = new XMLHttpRequest(); } catch (error) { done(null, 0); return; }
    try {
      xhr.open(method, url, true);
      xhr.timeout = 8000;
      xhr.setRequestHeader("Accept", "application/json");
      var token = readToken();
      if (token) { xhr.setRequestHeader("Authorization", "Bearer " + token); }
      xhr.onload = function () {
        var body = null;
        if (xhr.status >= 200 && xhr.status < 300) {
          try { body = JSON.parse(xhr.responseText || "null"); } catch (error) { body = null; }
        }
        done(body, xhr.status);
      };
      xhr.onerror = xhr.ontimeout = xhr.onabort = function () { done(null, 0); };
      xhr.send(null);
    } catch (error) { done(null, 0); }
  }

  /* ---------------- 轻提示（复用 script.js 的全局 toast，缺席则静默） ---------------- */

  function notify(text, kind) {
    try {
      if (typeof window.toast === "function") {
        window.toast(text, kind || "success", { exclusive: true, duration: 2200 });
      }
    } catch (error) { /* toast 本身不能让设备面板崩掉 */ }
  }

  /** 项目统一确认弹窗（Promise<boolean>）；节点缺失时宁可不删，也不退回原生 confirm */
  function confirmRevoke(text) {
    if (typeof window.confirmAction === "function") {
      return window.confirmAction({
        title: TEXT.revokeLabel,
        text: text,
        confirmText: "确认退出",
        danger: true,
      });
    }
    return Promise.resolve(false);
  }

  /* ---------------- UA 归一：只认「操作系统」和「浏览器」两档 ---------------- */

  function osOf(text) {
    var s = String(text || "").toLowerCase();
    if (!s) { return ""; }
    if (/ipad|平板|tablet/.test(s)) { return "ipad"; }
    if (/iphone|ipod|ios|苹果手机/.test(s)) { return "iphone"; }
    if (/harmony|鸿蒙/.test(s)) { return "harmony"; }
    if (/android|安卓/.test(s)) { return "android"; }
    if (/macintosh|mac os|macbook|mac 电脑|mac电脑/.test(s)) { return "mac"; }
    if (/windows|win32|win64|微软视窗/.test(s)) { return "windows"; }
    if (/linux|ubuntu/.test(s)) { return "linux"; }
    return "";
  }

  function browserOf(text) {
    var s = String(text || "").toLowerCase();
    if (!s) { return ""; }
    /* 顺序讲究：Edge 的 UA 里同时有 Chrome 和 Safari，必须先判 Edge */
    if (/edge|edg\/|edga\/|edgios\/|微软/.test(s)) { return "edge"; }
    if (/firefox|fxios|火狐/.test(s)) { return "firefox"; }
    if (/opera|opr\/|欧朋/.test(s)) { return "opera"; }
    if (/chrome|chromium|crios|谷歌/.test(s)) { return "chrome"; }
    if (/safari/.test(s)) { return "safari"; }
    return "";
  }

  function runtime() {
    if (current) { return current; }
    var ua = (navigator && navigator.userAgent) || "";
    current = { os: osOf(ua), browser: browserOf(ua) };
    return current;
  }

  /** 比对成立才返回 true：系统必须对上；两边都认得出浏览器时，浏览器也要对上 */
  function isThisDevice(item) {
    var me = runtime();
    var os = osOf(item.device) || osOf(item.browser);
    if (!os || !me.os || os !== me.os) { return false; }
    var br = browserOf(item.browser) || browserOf(item.device);
    if (br && me.browser && br !== me.browser) { return false; }
    return true;
  }

  function iconOf(device) {
    var os = osOf(device);
    if (os === "iphone" || os === "android" || os === "harmony" || os === "ipad") { return "📱"; }
    return "🖥️";
  }

  /* ---------------- 时间友好化：今天 / 昨天 / MM-DD ---------------- */

  function pad2(value) { return value < 10 ? "0" + value : String(value); }

  function parseTime(raw) {
    var matched = String(raw || "").match(/^(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})/);
    if (!matched) { return null; }
    var date = new Date(
      Number(matched[1]), Number(matched[2]) - 1, Number(matched[3]),
      Number(matched[4]), Number(matched[5])
    );
    return isNaN(date.getTime()) ? null : date;
  }

  function friendlyTime(raw) {
    var date = parseTime(raw);
    if (!date) {
      /* 认不出的格式不猜，原样截到分钟；确实没有就留空 */
      var plain = String(raw || "").replace("T", " ");
      return plain ? plain.slice(0, 16) : "";
    }
    var now = new Date();
    var hm = pad2(date.getHours()) + ":" + pad2(date.getMinutes());
    var todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    var dayStart = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
    var days = Math.round((todayStart - dayStart) / WEEK);
    if (days === 0) { return "今天 " + hm; }
    if (days === 1) { return "昨天 " + hm; }
    if (date.getFullYear() !== now.getFullYear()) {
      return date.getFullYear() + "-" + pad2(date.getMonth() + 1) + "-" + pad2(date.getDate()) + " " + hm;
    }
    return pad2(date.getMonth() + 1) + "-" + pad2(date.getDate()) + " " + hm;
  }

  /* ---------------- 渲染 ---------------- */

  function stateRow(text) {
    var li = document.createElement("li");
    li.className = "login-device-state";
    li.textContent = text;
    return li;
  }

  function clearList() {
    if (!listEl) { return; }
    while (listEl.firstChild) { listEl.removeChild(listEl.firstChild); }
  }

  function labelOf(item) {
    var parts = [];
    var device = String(item.device || "").trim();
    var browser = String(item.browser || "").trim();
    if (device) { parts.push(device); }
    if (browser) { parts.push(browser); }
    return parts.length ? parts.join(" · ") : TEXT.unknownDevice;
  }

  function itemRow(item, index) {
    var li = document.createElement("li");
    li.className = "login-device-item";
    li.setAttribute("data-device-id", item.id == null ? "" : String(item.id));
    li.__deviceItem = item;

    var icon = document.createElement("span");
    icon.className = "login-device-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = iconOf(item.device);

    var main = document.createElement("div");
    main.className = "login-device-main";

    var title = document.createElement("p");
    title.className = "login-device-title";
    var name = document.createElement("span");
    name.className = "login-device-name";
    name.textContent = labelOf(item);
    title.appendChild(name);

    if (index === 0 && isThisDevice(item)) {
      var tag = document.createElement("span");
      tag.className = "login-device-tag";
      tag.textContent = TEXT.current;
      title.appendChild(tag);
    }

    var meta = document.createElement("p");
    meta.className = "login-device-meta";
    var city = String(item.city || "").trim() || TEXT.unknownCity;
    var when = friendlyTime(item.last_at);
    meta.textContent = when ? city + " · " + when : city;

    main.appendChild(title);
    main.appendChild(meta);
    li.appendChild(icon);
    li.appendChild(main);

    /* 退出按钮：没有 id 的记录不渲染（后端没给 id 就没法 DELETE） */
    if (item.id != null && String(item.id)) {
      var revoke = document.createElement("button");
      revoke.type = "button";
      revoke.className = "login-device-revoke";
      revoke.setAttribute("data-device-id", String(item.id));
      revoke.setAttribute("aria-label", TEXT.revokeLabel);
      revoke.title = TEXT.revokeLabel;
      revoke.innerHTML =
        '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true">' +
        '<path d="M4 4l8 8M12 4l-8 8"></path></svg>';
      li.appendChild(revoke);
    }
    return li;
  }

  function render(devices) {
    if (!listEl) { return; }
    clearList();
    state.devices = devices;
    if (!devices.length) {
      listEl.appendChild(stateRow(TEXT.empty));
      return;
    }
    for (var i = 0; i < devices.length; i += 1) {
      listEl.appendChild(itemRow(devices[i], i));
    }
  }

  /* ---------------- 退出设备 ---------------- */

  /**
   * 删掉一行并同步内存缓存：淡出 → 移除 → 空了就显示「暂无记录」。
   * 不从服务端重拉，避免刚删的记录因为 30s 缓存又冒出来。
   */
  function removeRow(li, deviceId) {
    li.classList.add("is-revoking");
    window.setTimeout(function () {
      if (li.parentNode === listEl) { listEl.removeChild(li); }
      state.devices = state.devices.filter(function (item) {
        return String(item.id) !== String(deviceId);
      });
      if (!state.devices.length) {
        clearList();
        listEl.appendChild(stateRow(TEXT.empty));
      }
    }, 220);
  }

  function revokeDevice(button, li) {
    if (state.revoking || button.disabled) { return; }
    var deviceId = button.getAttribute("data-device-id");
    if (!deviceId) { return; }
    var item = li.__deviceItem || null;
    var label = item ? labelOf(item) : TEXT.unknownDevice;
    var city = item ? (String(item.city || "").trim() || TEXT.unknownCity) : TEXT.unknownCity;

    var accepted = confirmRevoke("退出「" + label + " · " + city + "」？该设备需要重新登录。");
    if (!accepted || typeof accepted.then !== "function") { return; }
    accepted.then(function (ok) {
      if (!ok) { return; }              // 取消：不发任何请求
      state.revoking = true;
      button.disabled = true;           // 0.4s 防重复点击
      window.setTimeout(function () {
        state.revoking = false;
        button.disabled = false;
      }, REVOKE_LOCK_MS);

      silentRequest("DELETE", API + "/" + encodeURIComponent(deviceId), function (body, status) {
        if (status >= 200 && status < 300) {
          removeRow(li, deviceId);
          notify(TEXT.revokeSuccess, "success");
        } else {
          notify(TEXT.revokeFail, "error");  // 失败保留该行
        }
      });
    });
  }

  function normalize(raw) {
    if (!raw || typeof raw !== "object") { return null; }
    var devices = raw.devices;
    if (!devices || typeof devices.length !== "number") { return null; }
    var picked = [];
    for (var i = 0; i < devices.length && picked.length < MAX_ITEMS; i += 1) {
      var item = devices[i];
      if (!item || typeof item !== "object") { continue; }
      /* 设备 id 只用于 DELETE 的 URL，不进任何可见文本 */
      picked.push({
        id: item.id,
        device: item.device,
        browser: item.browser,
        city: item.city,
        last_at: item.last_at
      });
    }
    return picked;
  }

  /* ---------------- 加载 ---------------- */

  function load(force) {
    if (!listEl || state.inflight) { return; }
    if (!force && state.loaded && (Date.now() - state.lastAt) < REFRESH_MS) { return; }
    state.inflight = true;
    /* 已渲染过就保留旧行，刷新时不再闪「正在加载…」 */
    if (!state.loaded) { clearList(); listEl.appendChild(stateRow(TEXT.loading)); }

    silentRequest("GET", API, function (body) {
      state.inflight = false;
      state.lastAt = Date.now();
      var devices = normalize(body);
      if (!devices) {
        /* 失败：有旧数据就静默保留，没有才给一句人话 */
        if (!state.loaded) {
          clearList();
          listEl.appendChild(stateRow(TEXT.error));
        }
        return;
      }
      state.loaded = true;
      render(devices);
    });
  }

  /* ---------------- 挂载：只在「账户与密码」tab 打开时按需加载 ---------------- */

  function accountPaneOpen() {
    var pane = document.getElementById("settings-pane-account");
    return !!pane && !pane.hidden;
  }

  function bind() {
    listEl = document.getElementById("login-device-list");
    if (!listEl) { return; }

    /* 1) tab 点击（auth-v012 的 showPane 与这里各管各的，互不依赖） */
    document.addEventListener("click", function (event) {
      var tab = event.target && event.target.closest && event.target.closest('[data-settings-tab="account"]');
      if (tab) { window.setTimeout(function () { load(false); }, 0); }
    });

    /* 2) 弹窗已经停在账户页时（例如上次关闭前就停在 account）也补一次 */
    var modal = document.getElementById("settings-modal");
    if (modal) {
      modal.addEventListener("shown.bs.modal", function () {
        if (accountPaneOpen()) { load(false); }
      });
    }

    /* 3) 退出按钮：事件委托，连点靠 state.revoking + button.disabled 双重拦截 */
    listEl.addEventListener("click", function (event) {
      var button = event.target && event.target.closest
        ? event.target.closest(".login-device-revoke") : null;
      if (!button || !listEl.contains(button)) { return; }
      event.preventDefault();
      event.stopPropagation();
      var li = button.closest(".login-device-item");
      if (li) { revokeDevice(button, li); }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind, true);
  } else {
    bind();
  }
})();
