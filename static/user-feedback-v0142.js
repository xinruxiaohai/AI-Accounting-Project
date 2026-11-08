/* =====================================================================
 * 智汇账 v0.14.2 · 用户端前端（仅 index.html 加载）
 *
 * 模块二：系统设置 →「权限管理」面板（仅管理员可见）
 * 模块四：反馈表单抄送邮箱、我的反馈对话流 / 追加补充、状态收敛为
 *         「已回复 / 未回复」、编号列表搜索框
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
   * 模块二：权限管理面板
   * ================================================================== */
  var permState = { admins: [], isAdmin: false, pending: null, search: "" };

  function seedAdmins(user) {
    var data = store();
    if (Array.isArray(data.admins) && data.admins.length) { return data.admins; }
    var seed = [{ uid: 1, email: "（内置超级管理员）", builtin: true }];
    if (user && Number(user.id) === 1 && user.email) { seed[0].email = user.email; }
    data.admins = seed;
    writeStore(data);
    return seed;
  }

  function loadAdmins(user) {
    return api("/api/admin/admins").then(function (data) {
      if (Array.isArray(data.admins)) { return data.admins; }
      throw new Error("bad payload");
    }).catch(function () {
      // 约定接口未上线：尝试读后台用户列表，再退回本机种子
      return api("/api/admin/users").then(function (data) {
        var users = Array.isArray(data.users) ? data.users : [];
        return users.filter(function (u) { return u.is_admin || Number(u.id) === 1; })
          .map(function (u) { return { uid: u.id, email: u.email || "（未提供邮箱）", builtin: Number(u.id) === 1 }; });
      }).catch(function () { return seedAdmins(user); });
    }).then(function (admins) {
      permState.admins = admins.map(function (a) {
        return { uid: Number(a.uid != null ? a.uid : a.id), email: a.email || "（未提供邮箱）", builtin: Number(a.uid != null ? a.uid : a.id) === 1 };
      });
      // uid=1 必须永远在列且不可移除
      if (!permState.admins.some(function (a) { return a.uid === 1; })) {
        permState.admins.unshift({ uid: 1, email: "（内置超级管理员）", builtin: true });
      }
      permState.admins.sort(function (a, b) { return a.uid - b.uid; });
      renderAdmins();
    });
  }

  function renderAdmins() {
    var box = $("v142-admin-list");
    if (!box) { return; }
    var q = permState.search.trim().toLowerCase();
    var rows = permState.admins.filter(function (a) {
      return !q || (String(a.uid) + " " + a.email).toLowerCase().indexOf(q) >= 0;
    });
    $("v142-admin-total").textContent = String(rows.length);
    box.textContent = "";
    if (!rows.length) {
      var empty = document.createElement("div");
      empty.className = "v142-empty";
      empty.textContent = q ? "没有匹配的管理员，换个关键词试试" : "还没有管理员记录。";
      box.appendChild(empty);
      return;
    }
    rows.forEach(function (admin) {
      var row = document.createElement("div");
      row.className = "v142-perm-row" + (admin.uid === 1 ? " is-super" : "");
      row.setAttribute("data-admin-uid", String(admin.uid));
      // 按邮箱新增时后端还没分配 UID，不能拿时间戳假冒编号
      var uidLabel = admin.pending ? "UID 待分配" : "UID #" + admin.uid;
      row.innerHTML =
        '<div class="v142-perm-main">' +
        '  <div class="v142-perm-line">' +
        '    <span class="v142-perm-uid">' + esc(uidLabel) + "</span>" +
        '    <span class="v142-perm-email"></span>' +
        "  </div>" +
        '  <p class="v142-perm-sub">' + (admin.uid === 1 ? "内置超级管理员 · 不可移除" : "管理员") + "</p>" +
        "</div>" +
        '<div class="v142-perm-actions">' +
        '  <button class="v142-btn is-danger" type="button" data-perm-action="remove"' +
        (admin.uid === 1 ? " disabled title=\"内置超级管理员不可移除\"" : "") + ">移除</button>" +
        "</div>";
      // 邮箱用 textContent，避免未净化内容进 DOM
      var emailEl = row.querySelector(".v142-perm-email");
      emailEl.textContent = admin.email;
      row.querySelector('[data-perm-action="remove"]').addEventListener("click", function () {
        if (admin.uid === 1) { return; }
        openPasswordModal("remove", admin);
      });
      box.appendChild(row);
    });
  }

  function buildPasswordModal() {
    if ($("v142-perm-pwd-modal")) { return; }
    var modal = document.createElement("div");
    modal.className = "v142-modal";
    modal.id = "v142-perm-pwd-modal";
    modal.hidden = true;
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.innerHTML =
      '<div class="v142-modal-backdrop" data-v142-close="perm"></div>' +
      '<div class="v142-modal-dialog">' +
      '  <div class="v142-modal-head"><div>' +
      '    <h2 class="v142-modal-title" id="v142-perm-pwd-title">验证身份</h2>' +
      '    <p class="v142-modal-sub" id="v142-perm-pwd-sub">敏感操作前先输入访问密码。</p>' +
      '  </div><button class="v142-modal-close" type="button" data-v142-close="perm" aria-label="关闭验证">' +
      '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"></path></svg>' +
      "  </button></div>" +
      '  <div class="v142-modal-body">' +
      '    <div class="v142-field" id="v142-perm-target-field" hidden>' +
      '      <label for="v142-perm-target">新管理员 UID 或邮箱</label>' +
      '      <input id="v142-perm-target" type="text" maxlength="120" placeholder="填邮箱，或纯数字 UID">' +
      "    </div>" +
      '    <div class="v142-field"><label for="v142-perm-password">登录密码</label>' +
      '      <input id="v142-perm-password" type="password" maxlength="64" autocomplete="current-password" placeholder="输入你的登录密码"></div>' +
      '    <p class="v142-form-error" id="v142-perm-pwd-error" hidden></p>' +
      '    <p class="v142-perm-note" id="v142-perm-pwd-note"></p>' +
      "  </div>" +
      '  <div class="v142-modal-foot">' +
      '    <button class="v142-btn" type="button" data-v142-close="perm">取消</button>' +
      '    <button class="v142-btn is-primary" type="button" id="v142-perm-pwd-confirm">确认</button>' +
      "  </div>" +
      "</div>";
    document.body.appendChild(modal);
    modal.addEventListener("click", function (event) {
      if (event.target.closest('[data-v142-close="perm"]')) { closeModal("v142-perm-pwd-modal"); }
    });
    $("v142-perm-pwd-confirm").addEventListener("click", confirmPassword);
    $("v142-perm-password").addEventListener("keydown", function (event) {
      if (event.key === "Enter") { event.preventDefault(); confirmPassword(); }
    });
  }

  function openPasswordModal(action, admin) {
    buildPasswordModal();
    permState.pending = { action: action, admin: admin || null };
    $("v142-perm-pwd-title").textContent = action === "add" ? "添加管理员" : "移除管理员";
    $("v142-perm-pwd-sub").textContent = action === "add"
      ? "填写要添加的管理员，再输入你本人的登录密码确认。"
      : "即将移除 " + (admin && admin.pending ? "（UID 待分配）" : "UID #" + (admin ? admin.uid : "")) + "，输入你本人的登录密码确认。";
    $("v142-perm-target-field").hidden = action !== "add";
    $("v142-perm-target").value = "";
    $("v142-perm-password").value = "";
    $("v142-perm-pwd-error").hidden = true;
    $("v142-perm-pwd-note").textContent =
      "这里校验的是你的登录密码（不是站点访问密码）；后端会按当前登录账号核对，密码不会保存。";
    openModal("v142-perm-pwd-modal");
    window.setTimeout(function () { $(action === "add" ? "v142-perm-target" : "v142-perm-password").focus(); }, 60);
  }

  function confirmPassword() {
    var pending = permState.pending;
    if (!pending) { return; }
    var password = String($("v142-perm-password").value || "");
    var error = $("v142-perm-pwd-error");
    var target = String($("v142-perm-target").value || "").trim();
    function fail(message) { error.textContent = message; error.hidden = false; }
    if (!password) { fail("请输入访问密码"); return; }
    if (pending.action === "add" && !target) { fail("填一下新管理员的 UID 或邮箱"); return; }
    error.hidden = true;
    $("v142-perm-pwd-confirm").disabled = true;
    // 密码交给后端「操作者登录密码」校验：前端只负责传，不落任何存储
    applyPermission(pending, target, password)
      .then(function () {
        $("v142-perm-pwd-confirm").disabled = false;
        closeModal("v142-perm-pwd-modal");
        permState.pending = null;
        renderAdmins();
      })
      .catch(function (err) {
        $("v142-perm-pwd-confirm").disabled = false;
        fail((err && err.message) || "密码不正确");
      });
  }

  /** 接口不存在（后端没实现）与业务错误要区分开：前者降级本机，后者如实报错 */
  function isMissingEndpoint(error) {
    var message = String((error && error.message) || "");
    return /接口不存在|HTTP 404|HTTP 405|网络连接失败|Failed to fetch/i.test(message);
  }

  function applyAdminList(list) {
    if (!Array.isArray(list)) { return false; }
    permState.admins = list.map(function (a) {
      var uid = Number(a.uid != null ? a.uid : a.id);
      return {
        uid: uid,
        email: a.email || "（未提供邮箱）",
        pending: false,
        builtin: a.builtin === true || uid === 1
      };
    });
    permState.admins.sort(function (a, b) { return a.uid - b.uid; });
    var data = store();
    data.admins = permState.admins.slice();
    writeStore(data);
    return true;
  }

  function localAdmins() {
    var data = store();
    if (!Array.isArray(data.admins)) { data.admins = permState.admins.slice(); }
    return data;
  }

  /** 指令路径：后端会核对「操作者本人登录密码」；缺失时回退到只靠 RBAC 的别名路径 */
  function addAdminRequest(target, password) {
    var isNumeric = /^\d+$/.test(target);
    var payload = { password: password };
    if (isNumeric) { payload.uid = Number(target); } else { payload.email = target; }
    return api("/api/admin/admins/add", jsonOptions("POST", payload)).catch(function (error) {
      if (!isMissingEndpoint(error)) { throw error; }
      return api("/api/admin/admins", jsonOptions("POST", isNumeric ? { uid: Number(target) } : { email: target }));
    });
  }

  function removeAdminRequest(uid, password) {
    return api("/api/admin/admins/remove", jsonOptions("POST", { uid: Number(uid), password: password }))
      .catch(function (error) {
        if (!isMissingEndpoint(error)) { throw error; }
        return api("/api/admin/admins/" + encodeURIComponent(uid), { method: "DELETE" });
      });
  }

  function applyPermission(pending, target, password) {
    if (pending.action === "remove") {
      var uid = Number(pending.admin.uid);
      if (uid === 1) { return Promise.reject(new Error("UID 1 是内置超级管理员，不能移除")); }
      return removeAdminRequest(uid, password).then(function (data) {
        if (!applyAdminList(data && data.admins)) {
          var box = localAdmins();
          box.admins = box.admins.filter(function (a) { return Number(a.uid) !== uid; });
          writeStore(box);
          permState.admins = box.admins;
        }
        toast("已移除 UID #" + uid);
      });
    }

    var isNumeric = /^\d+$/.test(target);
    if (isNumeric && Number(target) === 1) { return Promise.reject(new Error("UID 1 是内置超级管理员，不用重复添加")); }
    return addAdminRequest(target, password).then(function (data) {
      if (!applyAdminList(data && data.admins)) {
        var box = localAdmins();
        box.admins.push({ uid: Date.now(), email: target, pending: !isNumeric });
        writeStore(box);
        permState.admins = box.admins;
      }
      toast("已添加 " + target);
    });
  }

  function bootPermissions(identity) {
    permState.isAdmin = !!identity.isAdmin;
    var tab = document.querySelector('[data-settings-tab="permissions"]');
    if (tab) { tab.hidden = !identity.isAdmin; }
    if (!identity.isAdmin) { return; }
    // 移动端 Tab 条是横向滚动的，点开后把当前 Tab 滚进可视区
    if (tab) {
      tab.addEventListener("click", function () {
        window.setTimeout(function () {
          try { tab.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" }); }
          catch (error) { /* 老浏览器不支持参数对象时忽略 */ }
        }, 40);
      });
    }
    loadAdmins(identity.user);
    var addBtn = $("v142-admin-add");
    if (addBtn) { addBtn.addEventListener("click", function () { openPasswordModal("add", null); }); }
    var search = $("v142-admin-search");
    if (search) {
      search.addEventListener("input", function (event) {
        permState.search = String(event.target.value || "");
        renderAdmins();
      });
    }
  }

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
    checkIdentity().then(function (identity) {
      window.__v0142Identity = identity;
      bootPermissions(identity);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") { return; }
      if ($("v142-perm-pwd-modal") && !$("v142-perm-pwd-modal").hidden) { closeModal("v142-perm-pwd-modal"); return; }
      if ($("v142-user-chat-modal") && !$("v142-user-chat-modal").hidden) { closeModal("v142-user-chat-modal"); }
    }, true);
  }

  window.__v0142User = {
    identity: function () { return window.__v0142Identity || null; },
    openUserChat: openUserChat,
    permState: permState,
    loadAdmins: loadAdmins,
    openPasswordModal: openPasswordModal,
    renderAdmins: renderAdmins
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
