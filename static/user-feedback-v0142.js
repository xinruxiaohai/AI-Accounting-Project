/* =====================================================================
 * 智汇账 v0.14.2 · 用户端前端（仅 index.html 加载）
 *
 * 模块二：**已于 v0.15.3 删除**（用户端不再有「权限管理」，管理员只在 /admin 后台）
 * 模块四：我的反馈对话流 / 追加补充、状态收敛为
 *         「已回复 / 未回复」、编号列表搜索框
 *         （v0.15 起「反馈表单抄送邮箱」开关已移除）
 *
 * ── 后端契约（本轮纪律：严禁改后端）──
 * 已存在的真实接口：
 *   GET  /api/auth/me            → { user }
 *   GET  /api/user-feedback      → { feedback: [...] }
 *   POST /api/access/verify      → { ok, token }   ← 权限操作的密码校验
 * 约定接口（缺失时静默降级到 localStorage，UI 仍可完整演示）：
 *   GET  /api/access/check-identity → { is_admin, user, admins }
 *   GET  /api/admin/admins         → { admins: [{ uid, email }] }
 *   POST /api/admin/admins         → { admin }
 *   DELETE /api/admin/admins/<uid>
 *   POST /api/feedback/<id>/messages → 用户追加补充
 *
 * 注意：前端门禁只是体验层，真正的越权拦截必须由后端完成。
 * ===================================================================== */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
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
  function toast(message, type) {
    if (typeof window.toast === "function") { window.toast(message, type || "info"); }
    else if (window.materialToast) { window.materialToast(message); }
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

  var STORE_KEY = "zh_v0142_user_store_v1";
  function readStore() {
    try { return JSON.parse(window.localStorage.getItem(STORE_KEY)) || {}; }
    catch (error) { return {}; }
  }
  function writeStore(data) {
    try { window.localStorage.setItem(STORE_KEY, JSON.stringify(data)); }
    catch (error) { /* ignore */ }
  }
  function store() {
    var data = readStore();
    if (!Array.isArray(data.admins)) { data.admins = null; }
    if (!data.supplements || typeof data.supplements !== "object") { data.supplements = {}; }
    return data;
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
      return api("/api/auth/me").then(function (data) {
        var user = data.user || {};
        return {
          isAdmin: user.is_admin === true || user.role === "admin" || Number(user.id) === 1,
          user: user,
          source: "auth/me"
        };
      }).catch(function () { return { isAdmin: false, user: null, source: "guest" }; });
    });
  }

  /* ==================================================================
   * v0.15.3：原「模块二 权限管理」整块删除（约 270 行）。
   * 用户端设置不再有权限入口，也不再请求 /api/admin/admins 拿管理员名单；
   * 管理员的增删只保留在 /admin 后台。普通用户与管理员看到的设置页完全一致。
   * ================================================================== */

  /* ==================================================================
   * 模块四：我的反馈 → 对话流 / 追加补充 / 列表搜索
   * ================================================================== */
  var flowState = { ticket: null, supplements: {}, messages: null };
  function ticketKey(t) { return String((t && t.id) || "local"); }

  function buildUserChatModal() {
    if ($("v142-user-chat-modal")) { return; }
    var modal = document.createElement("div");
    modal.className = "v142-modal";
    modal.id = "v142-user-chat-modal";
    modal.hidden = true;
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.innerHTML =
      '<div class="v142-modal-backdrop" data-v142-close="userchat"></div>' +
      '<div class="v142-modal-dialog v142-chat">' +
      '  <div class="v142-modal-head"><div>' +
      '    <h2 class="v142-modal-title" id="v142-user-chat-title">工单对话</h2>' +
      '    <p class="v142-modal-sub" id="v142-user-chat-sub"></p>' +
      '  </div><button class="v142-modal-close" type="button" data-v142-close="userchat" aria-label="关闭对话">' +
      '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"></path></svg>' +
      "  </button></div>" +
      '  <div class="v142-chat-body" id="v142-user-chat-body"></div>' +
      '  <div class="v142-chat-foot">' +
      '    <div class="v142-supplement" id="v142-user-supplement" hidden>' +
      '      <textarea id="v142-user-supplement-input" placeholder="补充一下你遇到的问题…" aria-label="追加补充内容"></textarea>' +
      '      <div class="v142-chat-tools">' +
      '        <button class="v142-btn" type="button" id="v142-user-supplement-cancel">收起</button>' +
      '        <button class="v142-btn is-primary" type="button" id="v142-user-supplement-send">发送补充</button>' +
      "      </div>" +
      "    </div>" +
      '    <button class="v142-btn is-primary" type="button" id="v142-user-append">追加补充</button>' +
      '    <p class="v142-uflow-note">补充内容会追加到对话里；后端接口就绪前保存在本机。</p>' +
      "  </div>" +
      "</div>";
    document.body.appendChild(modal);
    modal.addEventListener("click", function (event) {
      if (event.target.closest('[data-v142-close="userchat"]')) { closeModal("v142-user-chat-modal"); }
    });
    $("v142-user-append").addEventListener("click", function () {
      var box = $("v142-user-supplement");
      box.hidden = !box.hidden;
      if (!box.hidden) { $("v142-user-supplement-input").focus(); }
    });
    $("v142-user-supplement-cancel").addEventListener("click", function () {
      $("v142-user-supplement").hidden = true;
    });
    $("v142-user-supplement-send").addEventListener("click", sendSupplement);
  }

  function appendBubble(body, role, text, image, time) {
    var row = document.createElement("div");
    row.className = "v142-bubble-row " + (role === "admin" ? "is-admin" : "is-user");
    var bubble = document.createElement("div");
    bubble.className = "v142-bubble";
    if (text) { bubble.appendChild(document.createTextNode(text)); }
    if (image) {
      var img = document.createElement("img");
      img.src = image;
      img.alt = role === "admin" ? "官方回复截图" : "反馈截图";
      bubble.appendChild(img);
    }
    var stamp = document.createElement("span");
    stamp.className = "v142-bubble-time";
    stamp.textContent = (role === "admin" ? "官方" : "我") + " · " + (time || "刚刚");
    bubble.appendChild(stamp);
    row.appendChild(bubble);
    body.appendChild(row);
  }

  function renderUserChat() {
    var t = flowState.ticket;
    var body = $("v142-user-chat-body");
    if (!t || !body) { return; }
    $("v142-user-chat-title").textContent = "工单 #" + (t.id || "—") + " · 对话";
    $("v142-user-chat-sub").textContent = "提交于 " + shortTime(t.created) +
      " · " + (t.reply ? "已回复" : "未回复");
    body.textContent = "";
    // 原始问题来自主记录，对话流接口只返回 feedback_replies，所以先画它
    appendBubble(body, "user", t.issue || "", "", shortTime(t.created));
    var messages = flowState.messages;
    if (messages && messages.length) {
      // 服务端对话流（用户补充 + 官方回复）为准；首条若是同一段原文则去重
      var skipIssueOnce = true;
      messages.forEach(function (m) {
        if (skipIssueOnce && m.role === "user" && m.text === (t.issue || "")) {
          skipIssueOnce = false;
          return;
        }
        appendBubble(body, m.role, m.text, m.image, m.created_at);
      });
    } else {
      if (t.reply) { appendBubble(body, "admin", t.reply, "", ""); }
      (flowState.supplements[ticketKey(t)] || []).forEach(function (s) {
        appendBubble(body, "user", s.text, "", s.created_at);
      });
    }
    body.scrollTop = body.scrollHeight;
  }

  function loadUserMessages(ticket, done) {
    if (!ticket || !ticket.id) { done(); return; }
    api("/api/feedback/" + encodeURIComponent(ticket.id) + "/messages").then(function (data) {
      if (!Array.isArray(data.messages)) { return; }
      flowState.messages = data.messages.map(function (m) {
        return {
          role: m.sender_type === "admin" ? "admin" : "user",
          text: m.content || "",
          image: m.image_url || "",
          created_at: shortTime(m.created_at)
        };
      });
      if (flowState.messages.some(function (m) { return m.role === "admin"; })) {
        $("v142-user-chat-sub").textContent = "提交于 " + shortTime(ticket.created) + " · 已回复";
      }
    }).catch(function () {
      flowState.messages = null;
    }).then(function () { done(); });
  }

  function openUserChat(index) {
    var list = window.__v0142Tickets || [];
    var ticket = list[Number(index)];
    if (!ticket) { return; }
    buildUserChatModal();
    flowState.ticket = ticket;
    flowState.messages = null;
    var data = store();
    flowState.supplements = data.supplements || {};
    $("v142-user-supplement").hidden = true;
    $("v142-user-supplement-input").value = "";
    openModal("v142-user-chat-modal");
    renderUserChat();
    var wanted = ticketKey(ticket);
    loadUserMessages(ticket, function () {
      if (flowState.ticket && ticketKey(flowState.ticket) === wanted) { renderUserChat(); }
    });
  }

  function sendSupplement() {
    var t = flowState.ticket;
    if (!t) { return; }
    var input = $("v142-user-supplement-input");
    var text = String(input.value || "").trim();
    if (!text) { toast("先写点要补充的内容", "error"); return; }
    var key = ticketKey(t);
    if (!flowState.supplements[key]) { flowState.supplements[key] = []; }
    var item = { text: text, created_at: nowStamp() };
    flowState.supplements[key].push(item);
    var data = store();
    data.supplements = flowState.supplements;
    writeStore(data);
    input.value = "";
    $("v142-user-supplement").hidden = true;
    // 先本地回显，再用服务端对话流校正
    flowState.messages = null;
    renderUserChat();
    api("/api/feedback/" + encodeURIComponent(t.id || "0") + "/messages", jsonOptions("POST", { text: text }))
      .then(function () {
        loadUserMessages(t, function () {
          if (flowState.ticket && ticketKey(flowState.ticket) === key) { renderUserChat(); }
        });
      })
      .catch(function () {
        toast("补充已保存在本机；后端接口暂时不可用", "info");
      });
    toast("补充已追加到对话");
  }

  function bootUserFeedback() {
    var list = $("feedback-ticket-list");
    if (list) {
      list.addEventListener("click", function (event) {
        var card = event.target.closest(".ticket-card");
        if (card && card.dataset.ticketIndex !== undefined) { openUserChat(card.dataset.ticketIndex); }
      });
      list.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" && event.key !== " ") { return; }
        var card = event.target.closest(".ticket-card");
        if (!card) { return; }
        event.preventDefault();
        openUserChat(card.dataset.ticketIndex);
      });
    }
    var search = $("v142-user-ticket-search");
    if (search) {
      search.addEventListener("input", function (event) {
        var q = String(event.target.value || "").trim().toLowerCase();
        var cards = list ? list.querySelectorAll(".ticket-card") : [];
        Array.prototype.slice.call(cards).forEach(function (card) {
          var hit = !q || (card.textContent || "").toLowerCase().indexOf(q) >= 0;
          if (hit) { card.style.removeProperty("display"); }
          else { card.style.setProperty("display", "none", "important"); }
        });
        var count = $("v142-user-ticket-count");
        if (count) { count.textContent = q ? "筛选中：" + q : ""; }
      });
    }
  }

  /* ---------------- 弹层开关 ---------------- */
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

  function boot() {
    bootUserFeedback();
    /* v0.15.3：不再调 bootPermissions()——用户端没有权限面板，
       也就不会再请求 /api/admin/admins 把管理员账号与邮箱拉到浏览器里。 */
    checkIdentity().then(function (identity) {
      window.__v0142Identity = identity;
    });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") { return; }
      if ($("v142-user-chat-modal") && !$("v142-user-chat-modal").hidden) { closeModal("v142-user-chat-modal"); }
    }, true);
  }

  window.__v0142User = {
    identity: function () { return window.__v0142Identity || null; },
    openUserChat: openUserChat
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
