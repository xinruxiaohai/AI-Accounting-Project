/* =====================================================================
 * 智汇账 v0.14.2 · 后台前端（仅 admin.html 加载）
 *
 * 模块一：管理员双重门禁（先身份，再原有访问密码）
 * 模块三：工单中心（三段筛选 / 全局搜索 / 微信式聊天窗 / 快捷语录 /
 *         问题日志弹窗与列表 / 所有编号列表搜索框）
 *
 * ── 后端契约（本轮纪律：严禁改后端，以下为「已支持 / 待后端补」两种口径）──
 * 已存在的真实接口：
 *   GET  /api/auth/me                              → { user }
 *   GET  /api/admin/feedback                      → { feedback: [...] }
 *   PUT  /api/admin/feedback/<id>/reply           → { feedback }
 *   POST /api/access/verify                       → { ok, token }
 * 约定接口（后端补齐后自动生效，缺失时静默降级到 localStorage，不报错不空白）：
 *   GET  /api/access/check-identity               → { is_admin, user, admins }
 *   PUT  /api/admin/feedback/<id>/status          → { status }
 *   PUT  /api/admin/feedback/<id>/read            → { is_read }
 *   GET  /api/admin/problem-logs                  → { logs: [...] }
 *   POST /api/admin/problem-logs                  → { log }
 * 所有用户内容一律 esc()/textContent 渲染，绝不拼接未净化的 innerHTML。
 * ===================================================================== */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var qs = function (sel, root) { return (root || document).querySelector(sel); };

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function pad(n) { return String(n).padStart(2, "0"); }
  function nowStamp() {
    var d = new Date();
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " +
      pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  }
  function shortTime(value) { return value ? String(value).replace("T", " ").slice(0, 16) : "—"; }
  function toast(message, isError) {
    var box = $("admin-toast");
    if (!box) { return; }
    box.textContent = message;
    box.classList.toggle("is-error", !!isError);
    box.classList.add("is-show");
    window.clearTimeout(toast._timer);
    toast._timer = window.setTimeout(function () { box.classList.remove("is-show"); }, 2600);
  }
  function api(path, options) {
    var opts = Object.assign({}, options || {});
    opts.headers = Object.assign({ Accept: "application/json" }, opts.headers || {});
    return window.fetch(path, opts).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok) { throw new Error(data.error || "请求失败（HTTP " + response.status + "）"); }
        return data;
      });
    });
  }
  function jsonOptions(method, body) {
    return { method: method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) };
  }

  /* ---------------- 本地降级层：接口未就绪时 UI 仍可完整演示 ---------------- */
  var STORE_KEY = "zh_v0142_admin_store_v1";
  function readStore() {
    try { return JSON.parse(window.localStorage.getItem(STORE_KEY)) || {}; }
    catch (error) { return {}; }
  }
  function writeStore(data) {
    try { window.localStorage.setItem(STORE_KEY, JSON.stringify(data)); }
    catch (error) { /* 隐私模式：只影响持久化，不影响当前会话 */ }
  }
  function store() {
    var data = readStore();
    if (!data.ticketMeta || typeof data.ticketMeta !== "object") { data.ticketMeta = {}; }
    if (!Array.isArray(data.logs)) { data.logs = []; }
    return data;
  }
  function metaOf(id) {
    var data = store();
    var key = String(id);
    if (!data.ticketMeta[key]) {
      data.ticketMeta[key] = { is_read: undefined, status: "", replied: undefined, messages: [], admin_reply: "" };
    }
    if (!Array.isArray(data.ticketMeta[key].messages)) { data.ticketMeta[key].messages = []; }
    return data.ticketMeta[key];
  }
  function saveMeta(id, meta) {
    var data = store();
    data.ticketMeta[String(id)] = meta;
    writeStore(data);
  }

  /* ==================================================================
   * 模块一：管理员双重门禁
   * ================================================================== */
  function buildGate() {
    var gate = document.createElement("div");
    gate.id = "v142-identity-gate";
    gate.className = "v142-gate";
    gate.setAttribute("role", "dialog");
    gate.setAttribute("aria-modal", "true");
    gate.setAttribute("aria-label", "管理员身份核验");
    gate.innerHTML =
      '<div class="v142-gate-card">' +
      '  <div class="v142-gate-mark" aria-hidden="true">' +
      '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" ' +
      '         stroke-linecap="round" stroke-linejoin="round">' +
      '      <rect x="4" y="10" width="16" height="10" rx="2"></rect>' +
      '      <path d="M8 10V7a4 4 0 0 1 8 0v3"></path>' +
      '    </svg>' +
      '  </div>' +
      '  <h1 class="v142-gate-title" id="v142-gate-title">正在核验管理员身份…</h1>' +
      '  <p class="v142-gate-sub" id="v142-gate-sub">先确认你是管理员，再进入后台密码验证。</p>' +
      '  <div class="v142-gate-dots" aria-hidden="true"><i></i><i></i><i></i></div>' +
      "</div>";
    document.body.appendChild(gate);
    return gate;
  }
  function renderBlocked(gate, hint) {
    var card = qs(".v142-gate-card", gate);
    card.innerHTML =
      '<div class="v142-gate-mark" aria-hidden="true">' +
      '  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" ' +
      '       stroke-linecap="round" stroke-linejoin="round">' +
      '    <path d="M12 3l8 4v5c0 5-3.4 8.2-8 9-4.6-.8-8-4-8-9V7l8-4z"></path>' +
      '    <path d="M9.5 12l5 5M14.5 12l-5 5"></path>' +
      '  </svg>' +
      "</div>" +
      '<h1 class="v142-gate-title">抱歉呢，前面是管理员后端，用户止步哟！</h1>' +
      '<p class="v142-gate-sub">' + esc(hint || "这里只接待管理员，回到看板继续记你的账吧 (・ω・)ノ") + "</p>" +
      '<a class="v142-gate-btn" href="/" role="button">返回看板</a>';
    document.documentElement.classList.remove("v142-gating");
    var back = qs(".v142-gate-btn", card);
    if (back) { back.focus(); }
  }
  function checkIdentity() {
    return api("/api/access/check-identity").then(function (data) {
      return {
        isAdmin: !!(data.is_admin || data.isAdmin ||
          (data.user && (data.user.is_admin || data.user.role === "admin"))),
        user: data.user || null,
        source: "check-identity"
      };
    }).catch(function () {
      // 约定接口未上线：退化到 /api/auth/me + 内置超管 UID=1
      return api("/api/auth/me").then(function (data) {
        var user = data.user || {};
        return {
          isAdmin: user.is_admin === true || user.role === "admin" || Number(user.id) === 1 || user.id === 1,
          user: user,
          source: "auth/me"
        };
      });
    });
  }
  function bootGate() {
    var gate = buildGate();
    checkIdentity().then(function (identity) {
      window.__v0142Identity = identity;
      gate.dataset.resolved = "1";
      if (!identity.isAdmin) {
        renderBlocked(gate);
        return;
      }
      // 身份通过：撤掉黑屏，交给 access-guard.js 的原有访问密码逻辑
      gate.hidden = true;
      document.documentElement.classList.remove("v142-gating");
    }).catch(function (error) {
      window.__v0142Identity = { isAdmin: false, source: "error", error: String(error) };
      gate.dataset.resolved = "1";
      renderBlocked(gate, "没能确认你的身份：" + (error && error.message ? error.message : "请先登录") + "。先回主站登录再试一次。");
    });
  }

  /* ==================================================================
   * 通用列表搜索（所有有编号的列表页）
   * ================================================================== */
  function attachListSearch(paneSelector, listSelector, placeholder) {
    var pane = qs(paneSelector);
    var list = qs(listSelector);
    if (!pane || !list) { return null; }
    if (pane.querySelector(".v142-search[data-v142-list-search]")) { return null; }
    var box = document.createElement("div");
    box.className = "v142-search";
    box.setAttribute("data-v142-list-search", "1");
    box.innerHTML =
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
      '     stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle>' +
      '<path d="M20 20l-3.5-3.5"></path></svg>' +
      '<input type="search" aria-label="' + esc(placeholder) + '" placeholder="' + esc(placeholder) + '">' +
      '<span class="v142-search-count" aria-live="polite"></span>';
    var card = qs(".admin-card", pane);
    if (card) {
      // 卡片首行如果是标题行（h2 / .d-flex 包裹的标题），搜索框插到它下面，别压住标题
      var head = card.firstElementChild;
      var isHeadRow = !!head && (
        head.tagName === "H2" ||
        head.classList.contains("d-flex") ||
        (!!head.firstElementChild && (
          head.firstElementChild.tagName === "H2" ||
          head.firstElementChild.classList.contains("admin-card-title")
        ))
      );
      if (isHeadRow) { card.insertBefore(box, head.nextSibling); }
      else { card.insertBefore(box, card.firstChild); }
    } else {
      pane.insertBefore(box, pane.firstChild);
    }
    var input = qs("input", box);
    var count = qs(".v142-search-count", box);
    function rows() {
      var tbody = qs("tbody", list);
      return tbody ? Array.prototype.slice.call(tbody.children) : Array.prototype.slice.call(list.children);
    }
    function apply() {
      var q = String(input.value || "").trim().toLowerCase();
      var list_rows = rows();
      var shown = 0;
      list_rows.forEach(function (row) {
        var hit = !q || (row.textContent || "").toLowerCase().indexOf(q) >= 0;
        if (hit) { row.style.removeProperty("display"); shown += 1; }
        else { row.style.setProperty("display", "none", "important"); }
      });
      count.textContent = q ? shown + " / " + list_rows.length : "";
    }
    input.addEventListener("input", apply);
    return { input: input, apply: apply };
  }

  /* ==================================================================
   * 模块三：工单中心
   * ================================================================== */
  var PROCESS_LABELS = { pending: "待处理", resolved: "已解决", ignored: "已忽略" };
  var QUICK_PHRASES = [
    "您好，问题我们已经收到，正在排查，有进展会第一时间在这里回复您。",
    "麻烦补充一下出现问题的具体操作步骤和截图，我们尽快定位。",
    "这个问题已修复并发布，请刷新页面或升级到最新版本后再试一次。",
    "感谢反馈！该建议已收录进需求池，后续版本会评估排期。"
  ];
  var ticketState = {
    items: [],
    filters: { read: "all", process: "all", reply: "all", q: "" },
    currentId: null,
    imageData: "",
    imageFile: null,
    searchHooks: []
  };
  // v0.14.3.1：filter = all | 0（未解决）| 1（已解决），currentId 为详情弹窗当前日志
  var logState = { items: null, filter: "all", currentId: null };

  function mapBackendStatus(raw, meta) {
    if (meta.status) { return meta.status; }
    var s = String(raw || "pending").toLowerCase();
    if (s === "resolved" || s === "closed" || s === "已解决") { return "resolved"; }
    if (s === "ignored" || s === "已忽略") { return "ignored"; }
    return "pending";
  }
  function buildMessages(raw, meta) {
    var out = [];
    var seen = {};
    function push(role, text, image, time, local) {
      var t = String(text || "").trim();
      var img = String(image || "");
      if (!t && !img) { return; }
      var key = role + "|" + t.slice(0, 120) + "|" + (img ? img.slice(-24) : "");
      if (seen[key]) { return; }
      seen[key] = true;
      out.push({ role: role, text: t, image: img, time: time || "", local: !!local });
    }
    push("user", raw.issue_description, raw.image_path, shortTime(raw.created_at), false);
    push("admin", raw.admin_reply || meta.admin_reply, "", shortTime(raw.updated_at), false);
    meta.messages.forEach(function (m) {
      push(m.role === "admin" ? "admin" : "user", m.text, m.image, m.created_at, m.local);
    });
    return out;
  }
  var PROCESS_FROM_INT = ["pending", "resolved", "ignored"];

  /**
   * 后端 v0.14.2 工单字段（优先）：process_status 0/1/2、read_status 0/1、
   * reply_status 0/1（由 feedback_replies 动态算出）。老字段 / 本机乐观更新做兜底。
   */
  function normalizeTicket(raw) {
    var meta = metaOf(raw.id);
    var messages = buildMessages(raw, meta);
    var backendReply = String(raw.admin_reply || "").trim();

    var status = PROCESS_FROM_INT[Number(raw.process_status)];
    if (!status) { status = mapBackendStatus(raw.status, meta); }
    if (meta.status) { status = meta.status; }

    var isRead;
    if (meta.is_read !== undefined && meta.is_read !== null) { isRead = !!meta.is_read; }
    else if (raw.read_status !== undefined && raw.read_status !== null) { isRead = Number(raw.read_status) === 1; }
    else { isRead = raw.is_read === true; }

    var replied;
    if (raw.reply_status !== undefined && raw.reply_status !== null) { replied = Number(raw.reply_status) === 1; }
    else if (meta.replied !== undefined && meta.replied !== null) { replied = !!meta.replied; }
    else {
      replied = !!backendReply ||
        messages.some(function (m) { return m.role === "admin" && m.text; });
    }
    if (meta.replied === true) { replied = true; }

    return {
      id: String(raw.id),
      uid: raw.uid != null ? raw.uid : raw.user_id,
      email: raw.email || "",
      nickname: raw.nickname || "",
      issue: raw.issue_description || "",
      occurDate: raw.occur_date || "",
      image: raw.image_path || "",
      contactType: raw.contact_type || "",
      contactInfo: raw.contact_info || "",
      createdAt: raw.created_at || "",
      rawStatus: raw.status || "pending",
      status: status,
      isRead: isRead,
      replied: !!replied,
      replyCount: Number(raw.reply_count || 0),
      ccEmail: Number(raw.cc_email || 0),
      adminReply: backendReply || meta.admin_reply || "",
      messages: messages,
      meta: meta
    };
  }

  function buildTicketPane() {
    var pane = $("pane-user-feedback");
    if (!pane) { return; }
    // 旧版查看器保留在 DOM 里（内联脚本仍会引用它的按钮/容器），只隐藏，避免空指针
    Array.prototype.slice.call(pane.children).forEach(function (child) {
      if (child.tagName === "SECTION" || child.classList.contains("admin-card")) {
        child.classList.add("v142-legacy-hidden");
      }
    });
    var card = document.createElement("div");
    card.className = "admin-card";
    card.id = "v142-ticket-pane";
    card.innerHTML =
      '<div class="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-2">' +
      '  <h2 class="admin-card-title mb-0">工单管理 <span class="badge text-bg-secondary" id="v142-ticket-total">0</span></h2>' +
      '  <button class="btn btn-sm btn-outline-secondary" type="button" id="v142-ticket-refresh">刷新</button>' +
      '</div>' +
      '<p class="admin-hint mb-3">点工单进入对话；左侧是用户，右侧是管理员。状态、已读、聊天记录与问题日志在后端接口就绪前保存在本机，不会丢。</p>' +
      '<div class="v142-filter-bar" id="v142-filter-bar">' +
      '  <div class="v142-filter-group"><span class="v142-filter-label">阅读</span>' +
      '    <div class="v142-seg" data-filter="read">' +
      '      <button type="button" data-value="all" class="is-active">全部</button>' +
      '      <button type="button" data-value="unread">未读</button>' +
      '      <button type="button" data-value="read">已读</button>' +
      '    </div></div>' +
      '  <div class="v142-filter-group"><span class="v142-filter-label">处理</span>' +
      '    <div class="v142-seg" data-filter="process">' +
      '      <button type="button" data-value="all" class="is-active">全部</button>' +
      '      <button type="button" data-value="pending">待处理</button>' +
      '      <button type="button" data-value="resolved">已解决</button>' +
      '      <button type="button" data-value="ignored">已忽略</button>' +
      '    </div></div>' +
      '  <div class="v142-filter-group"><span class="v142-filter-label">回复</span>' +
      '    <div class="v142-seg" data-filter="reply">' +
      '      <button type="button" data-value="all" class="is-active">全部</button>' +
      '      <button type="button" data-value="unreplied">未回复</button>' +
      '      <button type="button" data-value="replied">已回复</button>' +
      '    </div></div>' +
      '  <div class="v142-search v142-filter-search">' +
      '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><path d="M20 20l-3.5-3.5"></path></svg>' +
      '    <input type="search" id="v142-ticket-search" aria-label="搜索单号 / UID / 邮箱" placeholder="搜索单号 / UID / 邮箱">' +
      '  </div>' +
      '</div>' +
      '<div class="v142-ticket-list" id="v142-ticket-list"><div class="v142-empty">正在加载…</div></div>';
    pane.insertBefore(card, pane.firstChild);

    qs("#v142-filter-bar", card).addEventListener("click", function (event) {
      var btn = event.target.closest(".v142-seg button");
      if (!btn) { return; }
      var group = btn.closest(".v142-seg");
      var key = group.getAttribute("data-filter");
      ticketState.filters[key] = btn.getAttribute("data-value");
      Array.prototype.slice.call(group.querySelectorAll("button")).forEach(function (b) {
        b.classList.toggle("is-active", b === btn);
      });
      renderTicketList();
    });
    qs("#v142-ticket-search", card).addEventListener("input", function (event) {
      ticketState.filters.q = String(event.target.value || "");
      renderTicketList();
    });
    $("v142-ticket-refresh").addEventListener("click", function () { loadTickets(true); });
  }

  function ticketMatches(t) {
    var f = ticketState.filters;
    if (f.read === "unread" && t.isRead) { return false; }
    if (f.read === "read" && !t.isRead) { return false; }
    if (f.process !== "all" && t.status !== f.process) { return false; }
    if (f.reply === "unreplied" && t.replied) { return false; }
    if (f.reply === "replied" && !t.replied) { return false; }
    var q = f.q.trim().toLowerCase();
    if (!q) { return true; }
    return [t.id, t.uid, t.email, t.nickname, t.issue].join(" ").toLowerCase().indexOf(q) >= 0;
  }

  function renderTicketList() {
    var box = $("v142-ticket-list");
    if (!box) { return; }
    var items = ticketState.items.filter(ticketMatches);
    $("v142-ticket-total").textContent = String(items.length);
    box.textContent = "";
    if (!items.length) {
      var empty = document.createElement("div");
      empty.className = "v142-empty";
      empty.textContent = ticketState.items.length ? "没有符合当前筛选条件的工单，换个条件试试" : "还没有工单，等用户提交反馈后会出现在这里。";
      box.appendChild(empty);
      return;
    }
    items.forEach(function (t) {
      var row = document.createElement("button");
      row.type = "button";
      row.className = "v142-ticket-row" + (t.isRead ? "" : " is-unread");
      row.setAttribute("data-ticket-id", t.id);
      var badges =
        '<span class="v142-badge ' + (t.isRead ? "is-muted" : "is-info") + '">' + (t.isRead ? "已读" : "未读") + "</span>" +
        '<span class="v142-badge ' + (t.status === "resolved" ? "is-ok" : t.status === "ignored" ? "is-muted" : "is-warn") + '">' +
          esc(PROCESS_LABELS[t.status] || "待处理") + "</span>" +
        '<span class="v142-badge ' + (t.replied ? "is-ok" : "") + '">' + (t.replied ? "已回复" : "未回复") + "</span>";
      row.innerHTML =
        '<div class="v142-ticket-top">' +
        '  <span class="v142-ticket-id">工单 #' + esc(t.id) + "</span>" +
        '  <span class="v142-ticket-time">' + esc(shortTime(t.createdAt)) + "</span>" +
        "</div>" +
        '<p class="v142-ticket-user">UID #' + esc(String(t.uid)) + " · " + esc(t.email || "（未提供邮箱）") +
          (t.nickname ? " · " + esc(t.nickname) : "") + "</p>" +
        '<p class="v142-ticket-preview">' + esc(t.issue || "（无内容）") + "</p>" +
        '<div class="v142-ticket-badges">' + badges + "</div>";
      row.addEventListener("click", function () { openChat(t.id); });
      box.appendChild(row);
    });
  }

  function loadTickets(force) {
    var box = $("v142-ticket-list");
    if (!box) { return Promise.resolve(); }
    return api("/api/admin/feedback").then(function (data) {
      var rows = Array.isArray(data.feedback) ? data.feedback : [];
      ticketState.items = rows.map(normalizeTicket);
      renderTicketList();
      loadLogs();
      if (force) { toast("工单已刷新"); }
    }).catch(function (error) {
      box.textContent = "";
      var empty = document.createElement("div");
      empty.className = "v142-empty";
      empty.textContent = "工单加载失败：" + (error && error.message ? error.message : "请稍后重试");
      box.appendChild(empty);
      toast(error.message || "工单加载失败", true);
    });
  }

  /* ---------------- 聊天窗 ---------------- */
  function buildChatModal() {
    if ($("v142-chat-modal")) { return; }
    var modal = document.createElement("div");
    modal.className = "v142-modal";
    modal.id = "v142-chat-modal";
    modal.hidden = true;
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.innerHTML =
      '<div class="v142-modal-backdrop" data-v142-close="chat"></div>' +
      '<div class="v142-modal-dialog v142-chat">' +
      '  <div class="v142-modal-head v142-chat-head">' +
      '    <div><h2 class="v142-modal-title" id="v142-chat-title">工单对话</h2>' +
      '      <p class="v142-modal-sub" id="v142-chat-sub"></p></div>' +
      '    <div class="v142-chat-actions">' +
      '      <select id="v142-chat-status" aria-label="设置处理状态">' +
      '        <option value="pending">待处理</option>' +
      '        <option value="resolved">已解决</option>' +
      '        <option value="ignored">已忽略</option>' +
      "      </select>" +
      '      <div class="v142-phrase-wrap">' +
      '        <button class="v142-btn" type="button" id="v142-phrase-btn">插入快捷语录</button>' +
      '        <div class="v142-phrases" id="v142-phrases" hidden></div>' +
      "      </div>" +
      '      <button class="v142-btn" type="button" id="v142-log-btn">编写问题日志</button>' +
      '      <button class="v142-modal-close" type="button" data-v142-close="chat" aria-label="关闭对话">' +
      '        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"></path></svg>' +
      "      </button>" +
      "    </div>" +
      "  </div>" +
      '  <div class="v142-chat-body" id="v142-chat-body"></div>' +
      '  <div class="v142-chat-foot">' +
      '    <textarea class="v142-chat-input" id="v142-chat-input" placeholder="输入回复内容…（Ctrl + Enter 发送）" aria-label="回复内容"></textarea>' +
      '    <div class="v142-chat-tools">' +
      '      <label class="v142-btn v142-chat-attach" for="v142-chat-file">选择图片' +
      '        <input type="file" id="v142-chat-file" accept="image/*" aria-label="选择回复图片"></label>' +
      '      <img class="v142-chat-shot" id="v142-chat-shot" alt="待发送图片预览" hidden>' +
      '      <label class="v142-chat-email"><input type="checkbox" id="v142-chat-email"> 同时发送邮件通知用户</label>' +
      '      <button class="v142-btn is-ghost" type="button" id="v142-chat-clear">清空</button>' +
      '      <button class="v142-btn is-primary" type="button" id="v142-chat-send">发送回复</button>' +
      "    </div>" +
      "  </div>" +
      "</div>";
    document.body.appendChild(modal);

    var phraseBox = $("v142-phrases");
    $("v142-phrase-btn").addEventListener("click", function () { renderPhrasePanel(); phraseBox.hidden = !phraseBox.hidden; });
    $("v142-chat-file").addEventListener("change", function (event) {
      var file = event.target.files && event.target.files[0];
      if (!file) { return; }
      if (file.size > 2 * 1024 * 1024) { toast("图片请压到 2MB 以内", true); event.target.value = ""; return; }
      ticketState.imageFile = file;
      var reader = new FileReader();
      reader.onload = function () {
        ticketState.imageData = String(reader.result || "");
        var shot = $("v142-chat-shot");
        shot.src = ticketState.imageData;
        shot.hidden = false;
      };
      reader.readAsDataURL(file);
    });
    $("v142-chat-clear").addEventListener("click", function () {
      $("v142-chat-input").value = "";
      ticketState.imageData = "";
      $("v142-chat-file").value = "";
      $("v142-chat-shot").hidden = true;
    });
    $("v142-chat-send").addEventListener("click", sendReply);
    $("v142-chat-input").addEventListener("keydown", function (event) {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); sendReply(); }
    });
    $("v142-chat-status").addEventListener("change", function (event) { setTicketStatus(event.target.value); });
    $("v142-log-btn").addEventListener("click", openLogModal);
    modal.addEventListener("click", function (event) {
      if (event.target.closest('[data-v142-close="chat"]')) { closeModal("v142-chat-modal"); }
      else if (!event.target.closest(".v142-phrase-wrap")) { phraseBox.hidden = true; }
    });
  }

  function currentTicket() {
    return ticketState.items.find(function (t) { return t.id === ticketState.currentId; }) || null;
  }
  function renderChat() {
    var ticket = currentTicket();
    var body = $("v142-chat-body");
    if (!ticket || !body) { return; }
    $("v142-chat-title").textContent = "工单 #" + ticket.id + " · 对话";
    $("v142-chat-sub").textContent = "UID #" + ticket.uid + " · " + (ticket.email || "未提供邮箱") +
      (ticket.nickname ? " · " + ticket.nickname : "") + " · 提交于 " + shortTime(ticket.createdAt);
    $("v142-chat-status").value = ticket.status;
    body.textContent = "";
    // 原始问题存在主记录里，对话流接口只返回 feedback_replies：
    // 所以先固定画一条用户气泡，再把对话流里的重复项跳过。
    var display = [{
      role: "user",
      text: ticket.issue || "",
      image: ticket.image || "",
      time: shortTime(ticket.createdAt)
    }];
    ticket.messages.forEach(function (m) {
      if (m.role === "user" && (m.text || "") === (ticket.issue || "")) { return; }
      display.push(m);
    });
    if (!display.length) {
      var empty = document.createElement("p");
      empty.className = "v142-chat-empty";
      empty.textContent = "还没有对话内容，先发一条回复吧。";
      body.appendChild(empty);
      return;
    }
    display.forEach(function (m) {
      var rowEl = document.createElement("div");
      rowEl.className = "v142-bubble-row " + (m.role === "admin" ? "is-admin" : "is-user");
      var bubble = document.createElement("div");
      bubble.className = "v142-bubble";
      if (m.text) { bubble.appendChild(document.createTextNode(m.text)); }
      if (m.image) {
        var img = document.createElement("img");
        img.src = m.image;
        img.alt = m.role === "admin" ? "管理员回复截图" : "用户反馈截图";
        bubble.appendChild(img);
      }
      var time = document.createElement("span");
      time.className = "v142-bubble-time";
      time.textContent = (m.role === "admin" ? "管理员" : "用户") + " · " + (m.time || "刚刚") + (m.local ? " · 本机保存" : "");
      bubble.appendChild(time);
      rowEl.appendChild(bubble);
      body.appendChild(rowEl);
    });
    body.scrollTop = body.scrollHeight;
  }
  function repliesToMessages(replies) {
    return (replies || []).map(function (r) {
      return {
        role: r.sender_type === "admin" ? "admin" : "user",
        text: r.content || "",
        image: r.image_url || "",
        time: shortTime(r.created_at),
        local: false
      };
    });
  }

  function openChat(id) {
    buildChatModal();
    ticketState.currentId = String(id);
    var ticket = currentTicket();
    if (!ticket) { return; }
    ticketState.imageData = "";
    ticketState.imageFile = null;
    $("v142-chat-input").value = "";
    $("v142-chat-file").value = "";
    $("v142-chat-shot").hidden = true;
    $("v142-phrases").hidden = true;
    openModal("v142-chat-modal");
    renderChat();

    // 真实详情接口：主反馈 + 全部对话；调用即把 read_status 置 1
    api("/api/admin/feedback/" + encodeURIComponent(ticket.id) + "/detail").then(function (data) {
      if (ticketState.currentId !== String(id)) { return; }
      var fb = data.feedback || null;
      if (fb) {
        ticket.status = PROCESS_FROM_INT[Number(fb.process_status)] || ticket.status;
        ticket.replied = Number(fb.reply_status) === 1 || ticket.replied;
        ticket.issue = fb.issue_description || ticket.issue;
        ticket.image = fb.image_path || ticket.image;
        ticket.meta.status = "";
      }
      if (Array.isArray(data.replies) && data.replies.length) {
        ticket.messages = repliesToMessages(data.replies);
        ticket.replied = data.replies.some(function (r) { return r.sender_type === "admin"; });
      }
      ticket.isRead = true;
      ticket.meta.is_read = true;
      saveMeta(ticket.id, ticket.meta);
      renderChat();
      renderTicketList();
    }).catch(function () {
      // 详情接口不可用：退回本地已读 + 列表里的 admin_reply
      if (!ticket.isRead) {
        ticket.isRead = true;
        ticket.meta.is_read = true;
        saveMeta(ticket.id, ticket.meta);
        api("/api/admin/feedback/" + encodeURIComponent(ticket.id) + "/read", jsonOptions("PUT", { is_read: true }))
          .catch(function () { /* 接口不可用 */ });
      }
      renderChat();
      renderTicketList();
    });
  }

  /** 图片先走 /api/upload 落盘换 URL（回复接口只收 URL，不收 dataURL） */
  function uploadChatImage() {
    var file = ticketState.imageFile;
    if (!file) { return Promise.resolve(""); }
    var form = new FormData();
    form.append("file", file, file.name || "reply.png");
    return window.fetch("/api/upload", { method: "POST", body: form }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok || !data.url) { throw new Error(data.error || "图片上传失败"); }
        return String(data.url);
      });
    });
  }
  function sendReply() {
    var ticket = currentTicket();
    if (!ticket) { return; }
    var input = $("v142-chat-input");
    var text = String(input.value || "").trim();
    var localImage = ticketState.imageData;
    if (!text && !ticketState.imageFile) { toast("写点内容或选张图片再发送", true); return; }
    var sendBtn = $("v142-chat-send");
    sendBtn.disabled = true;

    // 图片先落盘换 URL：回复接口只接受 ≤500 字的图片地址，不收 dataURL
    uploadChatImage().then(function (imageUrl) {
      var emailChk = $("v142-chat-email");
      var sendEmail = !!(emailChk && emailChk.checked);
      return api("/api/admin/feedback/" + encodeURIComponent(ticket.id) + "/reply",
        jsonOptions("POST", { content: text, image_url: imageUrl, send_email: sendEmail }))
        .then(function () { return imageUrl; });
    }).then(function (imageUrl) {
      input.value = "";
      ticketState.imageData = "";
      ticketState.imageFile = null;
      $("v142-chat-file").value = "";
      $("v142-chat-shot").hidden = true;
      sendBtn.disabled = false;
      ticket.replied = true;
      // 以服务端对话流为准重渲染，避免本地消息和服务端重复
      return api("/api/admin/feedback/" + encodeURIComponent(ticket.id) + "/detail").then(function (data) {
        if (Array.isArray(data.replies)) { ticket.messages = repliesToMessages(data.replies); }
        renderChat();
        loadTickets(false);
        toast("回复已发送，工单已标记为「已回复」");
      }).catch(function () {
        ticket.messages.push({ role: "admin", text: text, image: imageUrl, time: shortTime(nowStamp()) });
        renderChat();
        renderTicketList();
        toast("回复已发送，工单已标记为「已回复」");
      });
    }).catch(function (error) {
      sendBtn.disabled = false;
      if (!text) { toast((error && error.message) || "图片上传失败，换一张试试", true); return; }
      // 接口不可用时保留本地乐观记录，绝不吞掉用户写的内容
      ticket.messages.push({ role: "admin", text: text, image: localImage, time: shortTime(nowStamp()), local: true });
      ticket.replied = true;
      ticket.meta.replied = true;
      saveMeta(ticket.id, ticket.meta);
      input.value = "";
      renderChat();
      renderTicketList();
      toast("回复已保存在本机；后端接口暂时不可用", false);
    });
  }
  function setTicketStatus(value) {
    var ticket = currentTicket();
    if (!ticket) { return; }
    ticket.status = value;
    ticket.meta.status = value;
    saveMeta(ticket.id, ticket.meta);
    renderChat();
    renderTicketList();
    api("/api/admin/feedback/" + encodeURIComponent(ticket.id) + "/status", jsonOptions("PUT", { status: value }))
      .then(function (data) {
        var fb = data && data.feedback;
        if (fb) {
          ticket.status = PROCESS_FROM_INT[Number(fb.process_status)] || value;
          ticket.meta.status = "";
          saveMeta(ticket.id, ticket.meta);
        }
        renderChat();
        renderTicketList();
        toast("处理状态已改为「" + (PROCESS_LABELS[value] || value) + "」");
      })
      .catch(function () {
        toast("处理状态已改到本机；后端接口暂时不可用", false);
      });
  }

  /* ---------------- 快捷语录管理（对接后端 /api/admin/quick-replies） ---------------- */
  function renderPhrasePanel() {
    var box = $("v142-phrases");
    if (!box) { return; }
    box.textContent = "";
    api("/api/admin/quick-replies").then(function (data) {
      var items = Array.isArray(data.replies) ? data.replies : [];
      box.textContent = "";
      if (!items.length) {
        var empty = document.createElement("div");
        empty.className = "v142-phrase-empty";
        empty.textContent = "还没有快捷语录，在下方新增一条吧。";
        box.appendChild(empty);
      }
      items.forEach(function (item) {
        var row = document.createElement("div");
        row.className = "v142-phrase-item";
        var fill = document.createElement("button");
        fill.type = "button";
        fill.className = "v142-phrase-text";
        fill.textContent = item.content;
        fill.title = "点击填入回复框";
        fill.addEventListener("click", function () {
          var input = $("v142-chat-input");
          if (!input) { return; }
          input.value = input.value.trim() ? input.value.trim() + "\n" + item.content : item.content;
          box.hidden = true;
          input.focus();
        });
        var del = document.createElement("button");
        del.type = "button";
        del.className = "v142-btn is-danger v142-phrase-del";
        del.textContent = "删除";
        del.addEventListener("click", function () { deleteQuickReply(item.id); });
        row.appendChild(fill);
        row.appendChild(del);
        box.appendChild(row);
      });
      // 新增行
      var addRow = document.createElement("div");
      addRow.className = "v142-phrase-add";
      var input = document.createElement("input");
      input.id = "v142-phrase-new";
      input.type = "text";
      input.placeholder = "新增快捷语录…";
      input.maxLength = 500;
      var addBtn = document.createElement("button");
      addBtn.type = "button";
      addBtn.className = "v142-btn is-primary";
      addBtn.textContent = "新增";
      addBtn.addEventListener("click", addQuickReply);
      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter") { event.preventDefault(); addQuickReply(); }
      });
      addRow.appendChild(input);
      addRow.appendChild(addBtn);
      box.appendChild(addRow);
    }).catch(function () {
      box.textContent = "";
      var fail = document.createElement("div");
      fail.className = "v142-phrase-empty";
      fail.textContent = "语录加载失败，请刷新重试。";
      box.appendChild(fail);
    });
  }
  function addQuickReply() {
    var input = $("v142-phrase-new");
    var text = String(input ? input.value || "" : "").trim();
    if (!text) { toast("先写点内容再新增", true); return; }
    api("/api/admin/quick-replies", jsonOptions("POST", { content: text })).then(function () {
      toast("已新增快捷语录");
      renderPhrasePanel();
    }).catch(function (error) {
      toast((error && error.message) || "新增失败", true);
    });
  }
  function deleteQuickReply(id) {
    api("/api/admin/quick-replies/" + encodeURIComponent(id), { method: "DELETE" }).then(function () {
      toast("已删除快捷语录");
      renderPhrasePanel();
    }).catch(function (error) {
      toast((error && error.message) || "删除失败", true);
    });
  }

  /* ---------------- 问题日志 ---------------- */
  function buildLogModal() {
    if ($("v142-log-modal")) { return; }
    var modal = document.createElement("div");
    modal.className = "v142-modal";
    modal.id = "v142-log-modal";
    modal.hidden = true;
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.innerHTML =
      '<div class="v142-modal-backdrop" data-v142-close="log"></div>' +
      '<div class="v142-modal-dialog">' +
      '  <div class="v142-modal-head"><div>' +
      '    <h2 class="v142-modal-title">编写问题日志</h2>' +
      '    <p class="v142-modal-sub">UID、时间与工单号已自动带入，补上结论和内容即可归档。</p>' +
      '  </div><button class="v142-modal-close" type="button" data-v142-close="log" aria-label="关闭问题日志">' +
      '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"></path></svg>' +
      "  </button></div>" +
      '  <div class="v142-modal-body">' +
      '    <div class="v142-field-grid">' +
      '      <div class="v142-field"><label for="v142-log-uid">UID</label><input id="v142-log-uid" readonly></div>' +
      '      <div class="v142-field"><label for="v142-log-time">时间</label><input id="v142-log-time" readonly></div>' +
      '      <div class="v142-field"><label for="v142-log-ticket">工单号</label><input id="v142-log-ticket" readonly></div>' +
      "    </div>" +
      '    <div class="v142-field"><label for="v142-log-result">处理结论</label>' +
      '      <select id="v142-log-result"><option value="resolved">已解决</option><option value="unresolved" selected>未解决</option></select></div>' +
      '    <div class="v142-field"><label for="v142-log-content">问题内容</label>' +
      '      <textarea id="v142-log-content" placeholder="写清楚现象、原因和处理动作…"></textarea></div>' +
      '    <p class="v142-form-error" id="v142-log-error" hidden></p>' +
      "  </div>" +
      '  <div class="v142-modal-foot">' +
      '    <button class="v142-btn" type="button" data-v142-close="log">取消</button>' +
      '    <button class="v142-btn is-primary" type="button" id="v142-log-save">保存日志</button>' +
      "  </div>" +
      "</div>";
    document.body.appendChild(modal);
    modal.addEventListener("click", function (event) {
      if (event.target.closest('[data-v142-close="log"]')) { closeModal("v142-log-modal"); }
    });
    $("v142-log-save").addEventListener("click", saveLog);
  }
  function openLogModal() {
    buildLogModal();
    var ticket = currentTicket();
    $("v142-log-uid").value = ticket ? "UID #" + ticket.uid : "—";
    $("v142-log-time").value = nowStamp();
    $("v142-log-ticket").value = ticket ? "#" + ticket.id : "—";
    $("v142-log-content").value = "";
    $("v142-log-error").hidden = true;
    openModal("v142-log-modal");
    window.setTimeout(function () { $("v142-log-content").focus(); }, 60);
  }
  function normalizeLog(raw) {
    var result = typeof raw.result === "string" && raw.result
      ? raw.result
      : (Number(raw.status) === 1 ? "已解决" : "未解决");
    return {
      id: raw.id != null ? String(raw.id) : "",
      uid: raw.user_uid != null ? raw.user_uid : (raw.uid != null ? raw.uid : "—"),
      ticket_id: raw.feedback_id != null ? String(raw.feedback_id) : (raw.ticket_id != null ? String(raw.ticket_id) : "—"),
      created_at: raw.created_at || "",
      result: result,
      content: raw.content || ""
    };
  }

  function loadLogs() {
    // v0.14.3.1：筛选条件透传后端 GET /api/admin/problem-logs?status=0|1
    var query = logState.filter === "all"
      ? ""
      : "?status=" + encodeURIComponent(logState.filter);
    return api("/api/admin/problem-logs" + query).then(function (data) {
      var rows = Array.isArray(data.logs) ? data.logs : [];
      logState.items = rows.map(normalizeLog);
      renderLogList();
    }).catch(function () {
      // 接口不可用：只展示本机归档过的日志
      logState.items = store().logs.filter(function (l) { return l.local; });
      renderLogList();
    });
  }

  function logMatchesFilter(log) {
    if (logState.filter === "all") { return true; }
    var wanted = logState.filter === "1" ? "已解决" : "未解决";
    return log.result === wanted;
  }

  function syncLogFilterHint() {
    var hint = $("v142-log-filter-hint");
    if (!hint) { return; }
    hint.textContent = logState.filter === "all"
      ? "显示全部日志"
      : (logState.filter === "1" ? "仅显示已解决" : "仅显示未解决");
  }

  function findLog(id) {
    var items = logState.items || store().logs;
    for (var i = 0; i < items.length; i++) {
      if (String(items[i].id) === String(id)) { return items[i]; }
    }
    return null;
  }

  /* ---------- v0.14.3.1：日志详情磨砂 Modal + 状态流转 ---------- */
  function buildLogDetailModal() {
    if ($("v142-log-detail-modal")) { return; }
    var modal = document.createElement("div");
    modal.className = "v142-modal";
    modal.id = "v142-log-detail-modal";
    modal.hidden = true;
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "v142-log-detail-title");
    modal.innerHTML =
      '<div class="v142-modal-backdrop" data-v142-log-detail-close></div>' +
      '<div class="v142-modal-dialog" style="width:min(560px, calc(100vw - 32px));">' +
      '  <div class="v142-modal-head"><div>' +
      '    <h2 class="v142-modal-title" id="v142-log-detail-title">日志详情</h2>' +
      '    <p class="v142-modal-sub">完整日志内容与处理状态</p>' +
      '  </div><button class="v142-modal-close" type="button" data-v142-log-detail-close aria-label="关闭日志详情">' +
      '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"></path></svg>' +
      "  </button></div>" +
      '  <div class="v142-modal-body">' +
      '    <p class="v142-log-meta" id="v142-log-detail-meta"></p>' +
      '    <p class="v142-log-detail-badge-row"><span class="v142-badge" id="v142-log-detail-badge"></span></p>' +
      '    <div class="v142-log-content v142-log-detail-text" id="v142-log-detail-content"></div>' +
      "  </div>" +
      '  <div class="v142-modal-foot">' +
      '    <button class="v142-btn" type="button" data-v142-log-detail-close>关闭</button>' +
      '    <button class="v142-btn is-primary" type="button" id="v142-log-toggle">标记为已解决</button>' +
      "  </div>" +
      "</div>";
    document.body.appendChild(modal);
    modal.addEventListener("click", function (event) {
      if (event.target.closest("[data-v142-log-detail-close]")) {
        closeModal("v142-log-detail-modal");
      }
    });
    $("v142-log-toggle").addEventListener("click", toggleLogStatus);
  }

  function paintLogDetail(log) {
    $("v142-log-detail-title").textContent = "日志 #" + log.id;
    $("v142-log-detail-meta").textContent =
      "UID #" + log.uid + " · 工单 #" + log.ticket_id + " · " + (log.created_at || "—");
    var badge = $("v142-log-detail-badge");
    badge.textContent = log.result;
    badge.className = "v142-badge " + (log.result === "已解决" ? "is-ok" : "is-warn");
    $("v142-log-detail-content").textContent = log.content || "（无内容）";
    $("v142-log-toggle").textContent = log.result === "已解决" ? "标记为未解决" : "标记为已解决";
  }

  function openLogDetail(id) {
    var log = findLog(id);
    if (!log) { return; }
    buildLogDetailModal();
    logState.currentId = log.id;
    paintLogDetail(log);
    openModal("v142-log-detail-modal");
  }

  function toggleLogStatus() {
    var log = findLog(logState.currentId);
    if (!log) { return; }
    var next = log.result === "已解决" ? 0 : 1;
    var btn = $("v142-log-toggle");
    btn.disabled = true;
    api("/api/admin/problem-logs/" + encodeURIComponent(String(log.id)),
        jsonOptions("PUT", { status: next }))
      .then(function (data) {
        btn.disabled = false;
        var saved = normalizeLog(data.log || { id: log.id, status: next });
        // 先本地同步 → 徽标与下方列表立刻更新，再按当前筛选重拉一次
        logState.items = (logState.items || []).map(function (item) {
          return String(item.id) === String(log.id) ? saved : item;
        });
        paintLogDetail(saved);
        renderLogList();
        toast(next === 1 ? "已标记为已解决" : "已标记为未解决");
        return loadLogs();
      })
      .catch(function (error) {
        btn.disabled = false;
        toast((error && error.message) || "状态更新失败", true);
      });
  }

  function saveLog() {
    var ticket = currentTicket();
    var content = String($("v142-log-content").value || "").trim();
    var error = $("v142-log-error");
    if (!content) { error.textContent = "先写点问题内容再保存"; error.hidden = false; return; }
    error.hidden = true;
    var result = $("v142-log-result").value === "unresolved" ? "未解决" : "已解决";
    var payload = {
      content: content,
      result: result,
      feedback_id: ticket ? Number(ticket.id) : null,
      user_uid: ticket ? Number(ticket.uid) || 0 : 0
    };
    $("v142-log-save").disabled = true;
    api("/api/admin/problem-logs", jsonOptions("POST", payload)).then(function (data) {
      $("v142-log-save").disabled = false;
      var saved = normalizeLog(data.log || payload);
      logState.items = [saved].concat(logState.items || []);
      renderLogList();
      closeModal("v142-log-modal");
      toast("问题日志已归档");
    }).catch(function () {
      $("v142-log-save").disabled = false;
      // 接口不可用：本机留档，绝不丢内容
      var data2 = store();
      data2.logs.unshift({
        id: "L" + Date.now().toString(36).toUpperCase(),
        uid: ticket ? ticket.uid : "—",
        ticket_id: ticket ? ticket.id : "—",
        created_at: nowStamp(),
        result: result,
        content: content,
        local: true
      });
      writeStore(data2);
      logState.items = null;
      renderLogList();
      closeModal("v142-log-modal");
      toast("问题日志已保存在本机；后端接口暂时不可用", false);
    });
  }
  function renderLogList() {
    var box = $("v142-log-list");
    if (!box) { return; }
    var all = logState.items || store().logs;
    var items = all.filter(logMatchesFilter);
    $("v142-log-total").textContent = String(items.length);
    syncLogFilterHint();
    box.textContent = "";
    if (!items.length) {
      var empty = document.createElement("div");
      empty.className = "v142-empty";
      empty.textContent = all.length
        ? "当前筛选下没有日志，切回「全部」看看。"
        : "还没有问题日志，在工单对话里点「编写问题日志」就能记一条。";
      box.appendChild(empty);
      return;
    }
    items.forEach(function (log) {
      var row = document.createElement("article");
      row.className = "v142-log-row is-clickable";
      row.setAttribute("role", "button");
      row.setAttribute("tabindex", "0");
      row.setAttribute("data-log-id", String(log.id));
      row.innerHTML =
        '<div class="v142-log-head">' +
        '  <span class="v142-ticket-id">日志 #' + esc(log.id) + "</span>" +
        '  <span class="v142-badge ' + (log.result === "已解决" ? "is-ok" : "is-warn") + '">' + esc(log.result) + "</span>" +
        "</div>" +
        '<p class="v142-log-meta">UID #' + esc(String(log.uid)) + " · 工单 #" + esc(String(log.ticket_id)) +
          " · " + esc(log.created_at) + "</p>" +
        '<p class="v142-log-content"></p>';
      qs(".v142-log-content", row).textContent = log.content;
      row.addEventListener("click", function () { openLogDetail(log.id); });
      row.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openLogDetail(log.id);
        }
      });
      box.appendChild(row);
    });
    var hook = ticketState.searchHooks.logs;
    if (hook) { hook.apply(); }
  }
  function bindLogFilter() {
    var seg = $("v142-log-seg");
    if (!seg || seg.getAttribute("data-bound") === "1") { return; }
    seg.setAttribute("data-bound", "1");
    seg.addEventListener("click", function (event) {
      var btn = event.target.closest("button[data-log-filter]");
      if (!btn) { return; }
      var value = btn.getAttribute("data-log-filter");
      if (value === logState.filter) { return; }
      logState.filter = value;
      Array.prototype.slice.call(seg.querySelectorAll("button")).forEach(function (b) {
        b.classList.toggle("is-active", b === btn);
      });
      loadLogs();
    });
  }

  function buildLogPane() {
    // v0.14.3.1：模板直出的「全部 / 未解决 / 已解决」筛选栏
    bindLogFilter();
    var main = qs("main.admin-page") || qs("main");
    if (!main) { return; }
    // pane 由 admin.html 模板提供；这里只负责挂搜索框（模板直出，避免 JS 未就绪时 Tab 空白）
    if ($("pane-problem-logs")) {
      ticketState.searchHooks.logs = attachListSearch("#pane-problem-logs", "#v142-log-list", "搜索日志编号 / UID / 工单号");
      return;
    }
    var pane = document.createElement("section");
    pane.id = "pane-problem-logs";
    pane.hidden = true;
    pane.innerHTML =
      '<div class="admin-card">' +
      '  <div class="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-2">' +
      '    <h2 class="admin-card-title mb-0">问题日志 <span class="badge text-bg-secondary" id="v142-log-total">0</span></h2>' +
      "  </div>" +
      '  <p class="admin-hint mb-3">从工单对话里归档的问题记录，按写入时间倒序。</p>' +
      '  <div class="v142-filter-bar"><div class="v142-filter-group">' +
      '    <span class="v142-filter-label">状态</span>' +
      '    <div class="v142-seg" id="v142-log-seg">' +
      '      <button type="button" data-log-filter="all" class="is-active">全部</button>' +
      '      <button type="button" data-log-filter="0">未解决</button>' +
      '      <button type="button" data-log-filter="1">已解决</button>' +
      "    </div></div></div>" +
      '  <div class="v142-log-list" id="v142-log-list"></div>' +
      "</div>";
    main.appendChild(pane);
    ticketState.searchHooks.logs = attachListSearch("#pane-problem-logs", "#v142-log-list", "搜索日志编号 / UID / 工单号");
    bindLogFilter();
  }

  /* ---------------- 弹层开关 / Esc ---------------- */
  var lastFocus = null;
  function openModal(id) {
    var modal = $(id);
    if (!modal) { return; }
    lastFocus = document.activeElement;
    modal.hidden = false;
    void modal.offsetWidth;
    modal.classList.add("is-open");
  }
  function closeModal(id) {
    var modal = $(id);
    if (!modal || modal.hidden) { return; }
    modal.classList.remove("is-open");
    modal.hidden = true;
    if (lastFocus && typeof lastFocus.focus === "function") {
      try { lastFocus.focus({ preventScroll: true }); } catch (error) { lastFocus.focus(); }
    }
    lastFocus = null;
  }

  /* ---------------- 启动 ---------------- */
  function bootAdmin() {
    bootGate();
    buildTicketPane();
    buildLogPane();
    ticketState.searchHooks.users = attachListSearch("#pane-users", "#user-list", "搜索 UID / 邮箱 / 昵称");
    ticketState.searchHooks.tips = attachListSearch("#pane-tips", "#tip-list", "搜索文案编号 / 场景 / 内容");
    ticketState.searchHooks.notices = attachListSearch("#pane-notices", "#notice-list", "搜索公告编号 / 标题 / 内容");
    ticketState.searchHooks.brain = attachListSearch("#pane-ai-brain", "#feedback-list", "搜索反馈编号 / 内容");
    loadTickets(false);
    loadLogs();
    // 内联脚本的 Tab 切换会异步填充列表，延迟再挂一次搜索过滤
    window.setTimeout(function () {
      Object.keys(ticketState.searchHooks).forEach(function (key) {
        var hook = ticketState.searchHooks[key];
        if (hook && typeof hook.apply === "function") { hook.apply(); }
      });
    }, 1200);
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") { return; }
      if ($("v142-log-detail-modal") && !$("v142-log-detail-modal").hidden) {
        closeModal("v142-log-detail-modal"); return;
      }
      if ($("v142-log-modal") && !$("v142-log-modal").hidden) { closeModal("v142-log-modal"); return; }
      if ($("v142-chat-modal") && !$("v142-chat-modal").hidden) { closeModal("v142-chat-modal"); }
    }, true);
  }

  /* ---------------- 管理员权限：已并入「用户管理」内联脚本（v0.14.2 重构） ----------------
   * 独立「权限管理」Tab 与这里的 v142-perm-* 面板逻辑已移除，
   * 管理员名单 / 设为 / 移除统一由 admin.html 的 pane-users 处理。 */

  window.__v0142Admin = {
    identity: function () { return window.__v0142Identity || null; },
    loadTickets: loadTickets,
    state: ticketState,
    store: store,
    openChat: openChat,
    setTicketStatus: setTicketStatus,
    saveLog: saveLog,
    // v0.14.3.1：日志筛选 / 详情弹窗，方便在控制台或自动化里直接驱动
    loadLogs: loadLogs,
    openLogDetail: openLogDetail,
    setLogFilter: function (value) {
      logState.filter = value;
      var seg = $("v142-log-seg");
      if (seg) {
        Array.prototype.slice.call(seg.querySelectorAll("button")).forEach(function (b) {
          b.classList.toggle("is-active", b.getAttribute("data-log-filter") === value);
        });
      }
      return loadLogs();
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootAdmin);
  } else {
    bootAdmin();
  }
})();
