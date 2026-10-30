/* v0.12 多用户前端：JWT 注入、登录/注册守卫、退出登录、账单导入预览。
 * 这个文件必须在 script.js 之前加载：它会包一层 window.fetch，
 * 之后页面里任何请求都会自动带 Authorization: Bearer <token>。
 */
(function () {
  "use strict";

  var TOKEN_KEY = "ai_accounting_token";
  var USER_KEY = "ai_accounting_user";
  var PUBLIC_AUTH_PATHS = ["/api/auth/login", "/api/auth/register", "/api/auth/sms-login"];

  var originalFetch = window.fetch ? window.fetch.bind(window) : null;

  function getToken() {
    try {
      return localStorage.getItem(TOKEN_KEY) || "";
    } catch (error) {
      return "";
    }
  }

  function getUser() {
    try {
      return JSON.parse(localStorage.getItem(USER_KEY) || "null");
    } catch (error) {
      return null;
    }
  }

  function saveSession(data) {
    try {
      localStorage.setItem(TOKEN_KEY, data.token || "");
      localStorage.setItem(USER_KEY, JSON.stringify(data.user || {}));
    } catch (error) {
      /* 隐私模式下 localStorage 可能不可用，登录态只保存在当前页 */
    }
  }

  function clearSession() {
    try {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    } catch (error) {
      /* 同上 */
    }
  }

  function isPublicAuthPath(url) {
    for (var i = 0; i < PUBLIC_AUTH_PATHS.length; i += 1) {
      if (url.indexOf(PUBLIC_AUTH_PATHS[i]) === 0) {
        return true;
      }
    }
    return false;
  }

  window.dshAuth = {
    token: getToken,
    user: getUser,
    logout: function () {
      clearSession();
      window.location.reload();
    },
  };

  if (originalFetch) {
    window.fetch = function (input, init) {
      init = init || {};
      var url = typeof input === "string" ? input : (input && input.url) || "";
      var headers = new Headers(init.headers || {});
      var token = getToken();
      if (token && !headers.has("Authorization")) {
        headers.set("Authorization", "Bearer " + token);
      }
      init.headers = headers;
      return originalFetch(input, init)
        .then(function (response) {
          if (response.status >= 500) {
            showFunnyToast("完蛋！后端工程师把咖啡洒在服务器上了，正在疯狂抢救中...");
          }
          if (response.status === 401 && url.indexOf("/api/") === 0 && !isPublicAuthPath(url)) {
          // 只对「没登录/登录过期」弹登录框；后台访问密码的 401 交给 access-guard 处理
          response
            .clone()
            .json()
            .then(function (body) {
              if (body && body.code === "auth_required") {
                showGate();
              }
            })
            .catch(function () {
              showGate();
            });
        }
          return response;
        })
        .catch(function (error) {
          showFunnyToast("哎呀，网线好像被小老鼠咬断了...");
          throw error;
        });
    };
  }

  /* ---------------- 登录 / 注册遮罩 ---------------- */

  var gateElement = null;
  var gateMode = "login";

  function buildGate() {
    if (gateElement) {
      return gateElement;
    }
    gateElement = document.createElement("div");
    gateElement.className = "auth-gate";
    gateElement.id = "auth-gate";
    gateElement.innerHTML =
      '<div class="auth-card">' +
        '<div class="auth-brand">' +
          '<span class="auth-logo">¥</span>' +
          "<h1>AI 记账</h1>" +
          "<p>登录后，账本数据只属于你</p>" +
        "</div>" +
        '<div class="auth-tabs">' +
          '<button type="button" data-auth-tab="login" class="is-active">登录</button>' +
          '<button type="button" data-auth-tab="register">注册</button>' +
        "</div>" +
        '<form id="auth-form" novalidate>' +
          '<label class="auth-label">邮箱' +
            '<input id="auth-email" class="form-control" type="email" autocomplete="email" placeholder="you@example.com">' +
          "</label>" +
          '<label class="auth-label">密码' +
            '<input id="auth-password" class="form-control" type="password" autocomplete="current-password" placeholder="至少 6 位">' +
          "</label>" +
          '<div class="auth-forgot"><button type="button" id="auth-forgot-btn">忘记密码？</button></div>' +
          '<label class="auth-label auth-phone" hidden>手机号（可选）' +
            '<input id="auth-phone" class="form-control" type="tel" autocomplete="tel" placeholder="用于以后找回密码">' +
          "</label>" +
          '<div class="auth-register-extra" hidden>' +
            '<label class="auth-label">昵称' +
              '<input id="auth-nickname" class="form-control" type="text" maxlength="20" placeholder="侧边栏显示的名字（不填就用邮箱前缀）">' +
            "</label>" +
            '<label class="auth-label">邮箱验证码' +
              '<span class="auth-code-row">' +
                '<input id="auth-code" class="form-control" type="text" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="6 位数字">' +
                '<button type="button" class="btn btn-outline-secondary auth-code-btn" id="auth-send-code">获取验证码</button>' +
              "</span>" +
            "</label>" +
            '<div class="auth-slider" id="auth-slider">' +
              '<span class="auth-slider-fill" id="auth-slider-fill"></span>' +
              '<span class="auth-slider-text" id="auth-slider-text">按住滑块，拖到最右侧解锁</span>' +
              '<span class="auth-slider-knob" id="auth-slider-knob" role="slider" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" tabindex="0">→</span>' +
            "</div>" +
          "</div>" +
          '<p class="auth-error" id="auth-error" hidden></p>' +
          '<button class="btn btn-primary w-100 auth-submit" type="submit" id="auth-submit">登录</button>' +
        "</form>" +
      "</div>";
    document.body.appendChild(gateElement);

    gateElement.addEventListener("click", function (event) {
      var tab = event.target.closest("[data-auth-tab]");
      if (!tab) {
        return;
      }
      switchMode(tab.getAttribute("data-auth-tab"));
    });

    gateElement.querySelector("#auth-form").addEventListener("submit", submitGate);
    var sendCodeButton = gateElement.querySelector("#auth-send-code");
    if (sendCodeButton) {
      sendCodeButton.addEventListener("click", sendEmailCode);
    }
    setupSlider();
    var forgotButton = gateElement.querySelector("#auth-forgot-btn");
    if (forgotButton) {
      forgotButton.addEventListener("click", openForgotModal);
    }
    return gateElement;
  }

  function switchMode(mode) {
    gateMode = mode === "register" ? "register" : "login";
    if (!gateElement) {
      return;
    }
    gateElement.querySelectorAll("[data-auth-tab]").forEach(function (tab) {
      tab.classList.toggle("is-active", tab.getAttribute("data-auth-tab") === gateMode);
    });
    gateElement.querySelector(".auth-phone").hidden = gateMode !== "register";
    var extra = gateElement.querySelector(".auth-register-extra");
    if (extra) {
      extra.hidden = gateMode !== "register";
    }
    resetSlider();
    var forgotBox = gateElement.querySelector(".auth-forgot");
    if (forgotBox) {
      forgotBox.hidden = gateMode !== "login";
      forgotBox.style.display = gateMode === "login" ? "" : "none";
    }
    gateElement.querySelector("#auth-submit").textContent = gateMode === "register" ? "注册并进入" : "登录";
    gateElement.querySelector("#auth-password").setAttribute(
      "autocomplete",
      gateMode === "register" ? "new-password" : "current-password"
    );
    var errorElement = gateElement.querySelector("#auth-error");
    errorElement.hidden = true;
  }

  function gateError(message) {
    if (!gateElement) {
      return;
    }
    var errorElement = gateElement.querySelector("#auth-error");
    errorElement.textContent = message || "";
    errorElement.hidden = !message;
  }

  async function submitGate(event) {
    event.preventDefault();
    if (!gateElement) {
      return;
    }
    var email = gateElement.querySelector("#auth-email").value.trim();
    var password = gateElement.querySelector("#auth-password").value;
    var phone = gateElement.querySelector("#auth-phone").value.trim();
    var nicknameInput = gateElement.querySelector("#auth-nickname");
    var nickname = nicknameInput ? nicknameInput.value.trim() : "";
    var button = gateElement.querySelector("#auth-submit");

    if (!email || !password) {
      gateError("邮箱和密码都要填");
      return;
    }
    // v0.12.3：强密码只在注册/改密时校验；登录必须放行管理员这类历史短密码，
    // 否则管理员初始密码会被前端直接拦死（后端登录也不做强度校验）
    if (gateMode === "register") {
      if (password.length < 6) {
        gateError("密码至少 6 位");
        return;
      }
      var kinds = 0;
      if (/[0-9]/.test(password)) { kinds += 1; }
      if (/[A-Za-z]/.test(password)) { kinds += 1; }
      if (/[^0-9A-Za-z]/.test(password)) { kinds += 1; }
      if (kinds < 2) {
        gateError("密码需包含数字、字母、标点中的至少两种");
        return;
      }
    }

    var code = "";
    if (gateMode === "register") {
      if (!sliderUnlocked) {
        gateError("请先按住滑块拖到最右侧完成人机校验");
        return;
      }
      var codeInput = gateElement.querySelector("#auth-code");
      code = codeInput ? codeInput.value.trim() : "";
      if (!/^\d{6}$/.test(code)) {
        gateError("请先获取并填写 6 位邮箱验证码");
        return;
      }
    }

    button.disabled = true;
    button.textContent = gateMode === "register" ? "注册中…" : "登录中…";
    gateError("");
    try {
      var response = await originalFetch(
        gateMode === "register" ? "/api/auth/register" : "/api/auth/login",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(
            gateMode === "register"
              ? { email: email, password: password, phone: phone, nickname: nickname, code: code }
              : { email: email, password: password }
          ),
        }
      );
      var data = await response.json().catch(function () {
        return {};
      });
      if (!response.ok) {
        gateError(data.error || "登录失败，请稍后再试");
        return;
      }
      saveSession(data);
      // 重新加载：让 script.js 在带 Token 的状态下重新初始化所有数据
      window.location.reload();
    } catch (error) {
      gateError((error && error.message) || "网络异常，请重试");
    } finally {
      button.disabled = false;
      button.textContent = gateMode === "register" ? "注册并进入" : "登录";
    }
  }

  /* ---------------- v0.12.1：幽默异常兜底 ---------------- */

  var funnyToastElement = null;
  var funnyToastTimer = null;

  function showFunnyToast(message) {
    if (!funnyToastElement) {
      funnyToastElement = document.createElement("div");
      funnyToastElement.className = "funny-toast";
      funnyToastElement.setAttribute("role", "status");
      document.body.appendChild(funnyToastElement);
    }
    funnyToastElement.textContent = message;
    funnyToastElement.classList.add("is-show");
    if (funnyToastTimer) {
      window.clearTimeout(funnyToastTimer);
    }
    funnyToastTimer = window.setTimeout(function () {
      funnyToastElement.classList.remove("is-show");
    }, 4200);
  }

  /* ---------------- v0.12.3：滑块人机校验（原生 JS，不引第三方） ---------------- */

  var sliderUnlocked = false;
  var sliderState = null;

  function setupSlider() {
    if (!gateElement) {
      return;
    }
    var track = gateElement.querySelector("#auth-slider");
    var knob = gateElement.querySelector("#auth-slider-knob");
    var fill = gateElement.querySelector("#auth-slider-fill");
    var text = gateElement.querySelector("#auth-slider-text");
    if (!track || !knob || sliderState) {
      return;
    }
    sliderState = { dragging: false, max: 0 };

    function maxTravel() {
      return Math.max(0, track.clientWidth - knob.offsetWidth - 2);
    }

    function paint(offset) {
      sliderState.max = maxTravel();
      var ratio = sliderState.max ? offset / sliderState.max : 0;
      knob.style.transform = "translateX(" + offset + "px)";
      if (fill) {
        fill.style.width = ratio * 100 + "%";
      }
      knob.setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
    }

    function finish(offset) {
      var max = maxTravel();
      if (max && offset >= max * 0.96) {
        sliderUnlocked = true;
        knob.style.transform = "translateX(" + max + "px)";
        if (fill) { fill.style.width = "100%"; }
        if (text) {
          text.textContent = "已解锁，可以注册了";
          text.classList.add("is-done");
        }
        track.classList.add("is-unlocked");
      } else {
        resetSlider();
      }
    }

    knob.addEventListener("pointerdown", function (event) {
      if (sliderUnlocked) {
        return;
      }
      event.preventDefault();
      sliderState.dragging = true;
      knob.setPointerCapture(event.pointerId);
      track.classList.add("is-dragging");
    });

    knob.addEventListener("pointermove", function (event) {
      if (!sliderState.dragging) {
        return;
      }
      var rect = track.getBoundingClientRect();
      var max = maxTravel();
      var offset = Math.min(max, Math.max(0, event.clientX - rect.left - knob.offsetWidth / 2));
      paint(offset);
    });

    function release(event) {
      if (!sliderState.dragging) {
        return;
      }
      sliderState.dragging = false;
      track.classList.remove("is-dragging");
      var current = parseFloat(knob.style.transform.replace(/[^0-9.-]/g, "") || "0");
      finish(current);
    }

    knob.addEventListener("pointerup", release);
    knob.addEventListener("pointercancel", release);
    // 键盘也能解锁：方向键推到最右
    knob.addEventListener("keydown", function (event) {
      if (event.key === "ArrowRight" || event.key === "End") {
        event.preventDefault();
        finish(maxTravel());
      }
    });
  }

  function resetSlider() {
    sliderUnlocked = false;
    if (!gateElement) {
      return;
    }
    var track = gateElement.querySelector("#auth-slider");
    var knob = gateElement.querySelector("#auth-slider-knob");
    var fill = gateElement.querySelector("#auth-slider-fill");
    var text = gateElement.querySelector("#auth-slider-text");
    if (knob) { knob.style.transform = "translateX(0px)"; knob.setAttribute("aria-valuenow", "0"); }
    if (fill) { fill.style.width = "0%"; }
    if (text) { text.textContent = "按住滑块，拖到最右侧解锁"; text.classList.remove("is-done"); }
    if (track) { track.classList.remove("is-unlocked", "is-dragging"); }
  }

  async function sendEmailCode() {
    if (!gateElement) {
      return;
    }
    var email = gateElement.querySelector("#auth-email").value.trim();
    var button = gateElement.querySelector("#auth-send-code");
    if (!email) {
      gateError("先填邮箱再获取验证码");
      return;
    }
    button.disabled = true;
    button.textContent = "发送中…";
    gateError("");
    try {
      var response = await originalFetch("/api/auth/send-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email }),
      });
      var data = await response.json().catch(function () {
        return {};
      });
      if (!response.ok) {
        gateError(data.error || "验证码发送失败");
        button.disabled = false;
        button.textContent = "获取验证码";
        return;
      }
      // Mock 模式：验证码打印在后端控制台，这里只给提示，倒计时 60 秒
      var seconds = 60;
      button.textContent = seconds + "s 后重发";
      var timer = window.setInterval(function () {
        seconds -= 1;
        if (seconds <= 0) {
          window.clearInterval(timer);
          button.disabled = false;
          button.textContent = "获取验证码";
        } else {
          button.textContent = seconds + "s 后重发";
        }
      }, 1000);
      gateError("");
      showFunnyToast("验证码已发送：当前是 Mock 模式，请在后端控制台查看 6 位数字");
    } catch (error) {
      gateError("网络异常，验证码没发出去");
      button.disabled = false;
      button.textContent = "获取验证码";
    }
  }

  function showGate() {
    buildGate();
    gateElement.hidden = false;
    document.body.classList.add("auth-locked");
    var emailInput = gateElement.querySelector("#auth-email");
    if (emailInput) {
      window.setTimeout(function () {
        emailInput.focus();
      }, 80);
    }
  }

  function hideGate() {
    if (!gateElement) {
      return;
    }
    gateElement.hidden = true;
    document.body.classList.remove("auth-locked");
  }

  function verifySession() {
    if (!getToken()) {
      showGate();
      return;
    }
    originalFetch("/api/auth/me", {
      headers: { Authorization: "Bearer " + getToken() },
    })
      .then(function (response) {
        if (!response.ok) {
          clearSession();
          showGate();
          return;
        }
        return response.json().then(function (data) {
          if (data && data.user) {
            try {
              localStorage.setItem(USER_KEY, JSON.stringify(data.user));
            } catch (error) {
              /* 忽略 */
            }
          }
          updateSidebarUser();
          hideGate();
        });
      })
      .catch(function () {
        // 断网时不把用户踢下线，继续用本地 Token
        hideGate();
      });
  }

  /* ---------------- 退出登录：任何 [data-logout] 按钮 ---------------- */

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-logout]");
    if (!button) {
      return;
    }
    event.preventDefault();
    clearSession();
    window.location.reload();
  });

  /* ---------------- 账单导入 ---------------- */

  var importState = { items: [], source: "wechat", filename: "" };

  function setImportStatus(text, isError) {
    var element = document.getElementById("import-status");
    if (!element) {
      return;
    }
    element.textContent = text || "";
    element.classList.toggle("is-error", Boolean(isError));
  }

  function money(value) {
    var number = Number(value || 0);
    return "¥" + number.toFixed(2);
  }

  function typeLabel(value) {
    return value === "income" ? "收入" : value === "expense" ? "支出" : "其他";
  }

  function renderImportPreview() {
    var body = document.getElementById("import-preview-body");
    var wrap = document.getElementById("import-table-wrap");
    var summary = document.getElementById("import-summary");
    var count = document.getElementById("import-count");
    var confirmButton = document.getElementById("import-confirm-btn");
    if (!body || !wrap || !summary) {
      return;
    }
    var duplicates = importState.items.filter(function (item) {
      return item.is_duplicate;
    }).length;
    summary.hidden = false;
    summary.innerHTML =
      "共解析出 <strong>" + importState.items.length + "</strong> 条流水，" +
      (duplicates
        ? '其中 <strong class="import-dup">' + duplicates + "</strong> 条与最近 10 天账目疑似重复（已默认取消勾选）"
        : "没有发现重复账目");
    wrap.hidden = false;

    body.innerHTML = importState.items
      .map(function (item, index) {
        var checked = item.is_duplicate ? "" : " checked";
        return (
          '<tr class="' + (item.is_duplicate ? "is-duplicate" : "") + '" data-import-row="' + index + '">' +
            '<td><input type="checkbox" data-import-check="' + index + '"' + checked + "></td>" +
            "<td>" + escapeHtml(item.date) + "</td>" +
            "<td>" + typeLabel(item.type) + "</td>" +
            "<td>" + escapeHtml(item.category || "其他") + "</td>" +
            "<td>" + escapeHtml(item.account || "") + "</td>" +
            '<td class="text-end">' + money(item.amount) + "</td>" +
            "<td>" + escapeHtml(item.note || item.merchant || "") +
              (item.is_duplicate ? '<span class="import-dup-tag">疑似重复</span>' : "") +
            "</td>" +
          "</tr>"
        );
      })
      .join("");

    updateImportCount();
    if (confirmButton) {
      confirmButton.disabled = false;
    }
    if (count) {
      count.textContent = "";
    }
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function updateImportCount() {
    var count = document.getElementById("import-count");
    var body = document.getElementById("import-preview-body");
    if (!count || !body) {
      return;
    }
    var checked = body.querySelectorAll("[data-import-check]:checked").length;
    count.textContent = "已选择 " + checked + " / " + importState.items.length + " 条";
  }

  async function parseImportFile(file) {
    if (!file) {
      return;
    }
    var confirmButton = document.getElementById("import-confirm-btn");
    if (confirmButton) {
      confirmButton.disabled = true;
    }
    setImportStatus("正在解析 " + file.name + " …");
    var form = new FormData();
    form.append("file", file);
    try {
      var response = await fetch("/api/import/parse", { method: "POST", body: form });
      var data = await response.json().catch(function () {
        return {};
      });
      if (!response.ok) {
        setImportStatus(data.error || "解析失败，请确认文件格式", true);
        return;
      }
      importState.items = data.items || [];
      importState.source = data.source || "wechat";
      importState.filename = data.filename || "";
      setImportStatus(
        "识别为" + (importState.source === "alipay" ? "支付宝" : "微信") + "账单" +
          (data.skipped ? "，已跳过 " + data.skipped + " 条无效流水" : "")
      );
      renderImportPreview();
    } catch (error) {
      setImportStatus((error && error.message) || "网络异常，请重试", true);
    }
  }

  async function confirmImport() {
    var body = document.getElementById("import-preview-body");
    var confirmButton = document.getElementById("import-confirm-btn");
    if (!body || !importState.items.length) {
      return;
    }
    var selected = [];
    body.querySelectorAll("[data-import-check]").forEach(function (checkbox) {
      if (checkbox.checked) {
        var index = Number(checkbox.getAttribute("data-import-check"));
        if (importState.items[index]) {
          selected.push(importState.items[index]);
        }
      }
    });
    if (!selected.length) {
      setImportStatus("至少勾选一条流水再导入", true);
      return;
    }
    if (confirmButton) {
      confirmButton.disabled = true;
      confirmButton.textContent = "导入中…";
    }
    setImportStatus("正在写入 " + selected.length + " 条流水…");
    try {
      var response = await fetch("/api/import/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: importState.source,
          filename: importState.filename,
          items: selected,
        }),
      });
      var data = await response.json().catch(function () {
        return {};
      });
      if (!response.ok) {
        setImportStatus(data.error || "导入失败，请重试", true);
        return;
      }
      setImportStatus(
        "导入完成：成功 " + (data.imported || 0) + " 条" +
          (data.duplicated ? "，跳过重复 " + data.duplicated + " 条" : "") +
          (data.failed && data.failed.length ? "，失败 " + data.failed.length + " 条" : "")
      );
      if (typeof window.refresh === "function") {
        window.refresh().catch(function () {});
      }
      importState.items = [];
      document.getElementById("import-table-wrap").hidden = true;
      document.getElementById("import-summary").hidden = true;
      if (confirmButton) {
        confirmButton.textContent = "确认导入";
      }
    } catch (error) {
      setImportStatus((error && error.message) || "网络异常，请重试", true);
    } finally {
      if (confirmButton) {
        confirmButton.disabled = false;
        if (confirmButton.textContent === "导入中…") {
          confirmButton.textContent = "确认导入";
        }
      }
    }
  }

  function initImportUi() {
    var triggers = [
      document.getElementById("import-bill-btn"),
      document.getElementById("profile-import-btn"),
    ].filter(Boolean);
    var modalElement = document.getElementById("import-modal");
    if (!triggers.length || !modalElement) {
      return;
    }
    var modal = null;
    function showModal() {
      if (window.bootstrap && window.bootstrap.Modal) {
        modal = modal || new window.bootstrap.Modal(modalElement);
        modal.show();
      } else {
        modalElement.classList.add("show");
        modalElement.style.display = "block";
      }
    }

    triggers.forEach(function (trigger) {
      trigger.addEventListener("click", function (event) {
        event.preventDefault();
        showModal();
      });
    });

    var fileInput = document.getElementById("import-file");
    var pickButton = document.getElementById("import-pick-btn");
    var dropZone = document.getElementById("import-drop");

    if (pickButton && fileInput) {
      pickButton.addEventListener("click", function () {
        fileInput.click();
      });
    }
    if (dropZone && fileInput) {
      dropZone.addEventListener("click", function (event) {
        if (event.target !== fileInput) {
          fileInput.click();
        }
      });
      ["dragenter", "dragover"].forEach(function (name) {
        dropZone.addEventListener(name, function (event) {
          event.preventDefault();
          dropZone.classList.add("is-dragover");
        });
      });
      ["dragleave", "drop"].forEach(function (name) {
        dropZone.addEventListener(name, function (event) {
          event.preventDefault();
          dropZone.classList.remove("is-dragover");
        });
      });
      dropZone.addEventListener("drop", function (event) {
        var file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
        parseImportFile(file);
      });
    }
    if (fileInput) {
      fileInput.addEventListener("change", function () {
        parseImportFile(fileInput.files && fileInput.files[0]);
      });
    }

    var selectAll = document.getElementById("import-select-all");
    if (selectAll) {
      selectAll.addEventListener("change", function () {
        var body = document.getElementById("import-preview-body");
        if (!body) {
          return;
        }
        body.querySelectorAll("[data-import-check]").forEach(function (checkbox) {
          checkbox.checked = selectAll.checked;
        });
        updateImportCount();
      });
    }

    var previewBody = document.getElementById("import-preview-body");
    if (previewBody) {
      previewBody.addEventListener("change", function (event) {
        if (event.target.closest("[data-import-check]")) {
          updateImportCount();
        }
      });
    }

    var confirmButton = document.getElementById("import-confirm-btn");
    if (confirmButton) {
      confirmButton.addEventListener("click", function () {
        confirmImport();
      });
    }
  }

  /* ---------------- v0.12.2：侧栏昵称 ---------------- */

  function updateSidebarUser() {
    var slot = document.getElementById("sidebar-user-name");
    if (!slot) {
      return;
    }
    var user = getUser() || {};
    var name = user.nickname || (user.email ? String(user.email).split("@")[0] : "");
    if (!name) {
      slot.hidden = true;
      return;
    }
    // v0.12.5：昵称旁边显示 UID，验证 1-9 号预留逻辑
    var uidText = user.id === undefined || user.id === null ? "" : "UID " + user.id;
    slot.innerHTML =
      '<span class="sidebar-nickname"></span>' +
      (uidText ? '<span class="sidebar-uid">' + uidText + "</span>" : "");
    slot.querySelector(".sidebar-nickname").textContent = name;
    slot.title = (user.email || "") + (uidText ? " · " + uidText : "");
    slot.hidden = false;
  }

  function setSettingsMessage(elementId, message, ok) {
    var element = document.getElementById(elementId);
    if (!element) {
      return;
    }
    element.textContent = message || "";
    element.hidden = !message;
    element.classList.toggle("is-ok", !!ok);
  }

  function bindSettingsTabs() {
    var tabs = Array.prototype.slice.call(
      document.querySelectorAll("[data-settings-tab]")
    );
    if (!tabs.length) {
      return;
    }
    var personalPane = document.getElementById("settings-pane-personal");
    var accountPane = document.getElementById("settings-pane-account");
    var personalFooter = document.getElementById("settings-footer-personal");
    var accountClose = document.getElementById("settings-account-close");

    function showPane(name) {
      var isAccount = name === "account";
      tabs.forEach(function (tab) {
        var active = tab.getAttribute("data-settings-tab") === name;
        tab.classList.toggle("is-active", active);
        tab.setAttribute("aria-selected", active ? "true" : "false");
      });
      if (personalPane) { personalPane.hidden = isAccount; }
      if (accountPane) { accountPane.hidden = !isAccount; }
      if (personalFooter) { personalFooter.classList.toggle("d-none", isAccount); }
      if (accountClose) { accountClose.classList.toggle("d-none", !isAccount); }
      if (isAccount) {
        fillAccountPane();
      }
    }

    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        showPane(tab.getAttribute("data-settings-tab"));
      });
    });
  }

  function fillAccountPane() {
    var user = getUser() || {};
    var emailLabel = document.getElementById("settings-account-email");
    if (emailLabel) {
      var uid = user.id === undefined || user.id === null ? "—" : user.id;
      emailLabel.textContent = "当前账号：" + (user.email || "—") + " · UID：" + uid;
    }
    var nicknameInput = document.getElementById("settings-nickname");
    if (nicknameInput && !nicknameInput.value) {
      nicknameInput.value = user.nickname || "";
    }
    var resetEmail = document.getElementById("reset-password-email");
    if (resetEmail && !resetEmail.value && user.email) {
      resetEmail.value = user.email;
    }
  }

  function saveNickname() {
    var input = document.getElementById("settings-nickname");
    if (!input) {
      return;
    }
    setSettingsMessage("settings-nickname-error", "");
    fetch("/api/auth/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nickname: input.value.trim() }),
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { ok: response.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          setSettingsMessage("settings-nickname-error", result.data.error || "保存失败");
          return;
        }
        var user = result.data.user || {};
        try {
          localStorage.setItem(USER_KEY, JSON.stringify(user));
        } catch (error) {
          /* 忽略 */
        }
        updateSidebarUser();
        showFunnyToast("昵称已保存");
      })
      .catch(function () {
        setSettingsMessage("settings-nickname-error", "网络异常，请重试");
      });
  }

  function changePassword() {
    var oldInput = document.getElementById("change-old-password");
    var newInput = document.getElementById("change-new-password");
    var confirmInput = document.getElementById("change-confirm-password");
    if (!oldInput || !newInput || !confirmInput) {
      return;
    }
    var oldPassword = oldInput.value;
    var newPassword = newInput.value;
    var confirmPassword = confirmInput.value;
    setSettingsMessage("change-password-error", "");
    if (!oldPassword || !newPassword) {
      setSettingsMessage("change-password-error", "旧密码和新密码都要填");
      return;
    }
    if (newPassword !== confirmPassword) {
      setSettingsMessage("change-password-error", "两次输入的新密码不一致");
      return;
    }
    fetch("/api/auth/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        old_password: oldPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      }),
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { ok: response.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          setSettingsMessage("change-password-error", result.data.error || "修改失败");
          return;
        }
        oldInput.value = "";
        newInput.value = "";
        confirmInput.value = "";
        var modalElement = document.getElementById("change-password-modal");
        if (modalElement && window.bootstrap) {
          var instance = window.bootstrap.Modal.getInstance(modalElement);
          if (instance) {
            instance.hide();
          }
        }
        showFunnyToast("密码已更新，下次请用新密码登录");
      })
      .catch(function () {
        setSettingsMessage("change-password-error", "网络异常，请重试");
      });
  }

  function sendResetCode() {
    var emailInput = document.getElementById("reset-password-email");
    var button = document.getElementById("reset-password-send-code");
    if (!emailInput || !button) {
      return;
    }
    var email = emailInput.value.trim();
    if (!email) {
      setSettingsMessage("reset-password-error", "先填注册邮箱");
      return;
    }
    button.disabled = true;
    button.textContent = "发送中…";
    fetch("/api/auth/send-code", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email, purpose: "reset" }),
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { ok: response.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          setSettingsMessage("reset-password-error", result.data.error || "发送失败");
          button.disabled = false;
          button.textContent = "发送验证码";
          return;
        }
        setSettingsMessage("reset-password-error", "验证码已发送（Mock 模式：请查看后端控制台）", true);
        var seconds = 60;
        button.textContent = seconds + "s 后重发";
        var timer = window.setInterval(function () {
          seconds -= 1;
          if (seconds <= 0) {
            window.clearInterval(timer);
            button.disabled = false;
            button.textContent = "发送验证码";
            return;
          }
          button.textContent = seconds + "s 后重发";
        }, 1000);
      })
      .catch(function () {
        setSettingsMessage("reset-password-error", "网络异常，请重试");
        button.disabled = false;
        button.textContent = "发送验证码";
      });
  }

  function resetPassword() {
    var emailInput = document.getElementById("reset-password-email");
    var codeInput = document.getElementById("reset-password-code");
    var passwordInput = document.getElementById("reset-password-new");
    var confirmInput = document.getElementById("reset-password-confirm");
    if (!emailInput || !codeInput || !passwordInput || !confirmInput) {
      return;
    }
    setSettingsMessage("reset-password-error", "");
    var code = codeInput.value.trim();
    if (!/^\d{6}$/.test(code)) {
      setSettingsMessage("reset-password-error", "请填 6 位邮箱验证码");
      return;
    }
    if (passwordInput.value !== confirmInput.value) {
      setSettingsMessage("reset-password-error", "两次输入的新密码不一致");
      return;
    }
    fetch("/api/auth/reset-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: emailInput.value.trim(),
        code: code,
        new_password: passwordInput.value,
        confirm_password: confirmInput.value,
      }),
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { ok: response.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          setSettingsMessage("reset-password-error", result.data.error || "重置失败");
          return;
        }
        codeInput.value = "";
        passwordInput.value = "";
        confirmInput.value = "";
        setSettingsMessage("reset-password-error", "密码已重置，请用新密码登录", true);
      })
      .catch(function () {
        setSettingsMessage("reset-password-error", "网络异常，请重试");
      });
  }

  function initAccountSettings() {
    bindSettingsTabs();
    var nicknameButton = document.getElementById("settings-nickname-save");
    if (nicknameButton) {
      nicknameButton.addEventListener("click", saveNickname);
    }
    var changeSubmit = document.getElementById("change-password-submit");
    if (changeSubmit) {
      changeSubmit.addEventListener("click", changePassword);
    }
    var changeModal = document.getElementById("change-password-modal");
    if (changeModal) {
      changeModal.addEventListener("shown.bs.modal", function () {
        ["change-old-password", "change-new-password", "change-confirm-password"].forEach(function (id) {
          var input = document.getElementById(id);
          if (input) {
            input.value = "";
          }
        });
        setSettingsMessage("change-password-error", "");
      });
    }
    var sendButton = document.getElementById("reset-password-send-code");
    if (sendButton) {
      sendButton.addEventListener("click", sendResetCode);
    }
    var resetButton = document.getElementById("reset-password-submit");
    if (resetButton) {
      resetButton.addEventListener("click", resetPassword);
    }
    var forgotLink = document.getElementById("settings-forgot-link");
    var resetModal = document.getElementById("reset-password-modal");
    if (forgotLink && resetModal) {
      // 打开独立 Modal 时把当前账号邮箱带进去，省得手输
      forgotLink.addEventListener("click", function () {
        window.setTimeout(function () {
          var emailInput = document.getElementById("reset-password-email");
          var user = getUser() || {};
          if (emailInput && !emailInput.value && user.email) {
            emailInput.value = user.email;
          }
          setSettingsMessage("reset-password-error", "");
        }, 220);
      });
    }
    if (resetModal) {
      resetModal.addEventListener("shown.bs.modal", function () {
        var emailInput = document.getElementById("reset-password-email");
        var user = getUser() || {};
        if (emailInput && !emailInput.value && user.email) {
          emailInput.value = user.email;
        }
      });
    }
    var modal = document.getElementById("settings-modal");
    if (modal) {
      modal.addEventListener("shown.bs.modal", fillAccountPane);
    }
  }

  /* ---------------- v0.12.3：登录页「忘记密码」---------------- */

  var forgotElement = null;

  function buildForgotModal() {
    if (forgotElement) {
      return forgotElement;
    }
    forgotElement = document.createElement("div");
    forgotElement.className = "auth-forgot-mask";
    forgotElement.id = "auth-forgot-mask";
    forgotElement.innerHTML =
      '<div class="auth-forgot-card" role="dialog" aria-modal="true" aria-labelledby="forgot-title">' +
        '<h2 id="forgot-title">找回密码</h2>' +
        '<p class="auth-forgot-sub">输入注册邮箱，验证码由后端生成（Mock 模式，会打印在后端控制台）。</p>' +
        '<label class="auth-label">邮箱' +
          '<input id="forgot-email" class="form-control" type="email" autocomplete="email" placeholder="注册时用的邮箱">' +
        "</label>" +
        '<label class="auth-label">邮箱验证码' +
          '<span class="auth-code-row">' +
            '<input id="forgot-code" class="form-control" type="text" inputmode="numeric" maxlength="6" placeholder="6 位数字">' +
            '<button type="button" class="btn btn-outline-secondary auth-code-btn" id="forgot-send">获取验证码</button>' +
          "</span>" +
        "</label>" +
        '<label class="auth-label">新密码' +
          '<input id="forgot-password" class="form-control" type="password" autocomplete="new-password" placeholder="至少 6 位，含两种字符">' +
        "</label>" +
        '<label class="auth-label">确认新密码' +
          '<input id="forgot-confirm" class="form-control" type="password" autocomplete="new-password" placeholder="再输一次">' +
        "</label>" +
        '<p class="auth-error" id="forgot-error" hidden></p>' +
        '<div class="auth-forgot-actions">' +
          '<button type="button" class="btn btn-light" id="forgot-cancel">取消</button>' +
          '<button type="button" class="btn btn-primary" id="forgot-submit">重置密码</button>' +
        "</div>" +
      "</div>";
    document.body.appendChild(forgotElement);

    forgotElement.addEventListener("click", function (event) {
      if (event.target === forgotElement) {
        closeForgotModal();
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && forgotElement && forgotElement.classList.contains("is-open")) {
        closeForgotModal();
      }
    });
    forgotElement.querySelector("#forgot-cancel").addEventListener("click", closeForgotModal);
    forgotElement.querySelector("#forgot-send").addEventListener("click", forgotSendCode);
    forgotElement.querySelector("#forgot-submit").addEventListener("click", forgotSubmit);
    return forgotElement;
  }

  function forgotMessage(message, ok) {
    if (!forgotElement) {
      return;
    }
    var box = forgotElement.querySelector("#forgot-error");
    box.textContent = message || "";
    box.hidden = !message;
    box.classList.toggle("is-ok", Boolean(ok));
  }

  function openForgotModal() {
    buildForgotModal();
    var emailInput = forgotElement.querySelector("#forgot-email");
    if (gateElement && emailInput && !emailInput.value) {
      emailInput.value = gateElement.querySelector("#auth-email").value.trim();
    }
    forgotMessage("");
    forgotElement.classList.add("is-open");
    window.setTimeout(function () {
      if (emailInput) {
        emailInput.focus();
      }
    }, 60);
  }

  function closeForgotModal() {
    if (forgotElement) {
      forgotElement.classList.remove("is-open");
    }
  }

  async function forgotSendCode() {
    var email = forgotElement.querySelector("#forgot-email").value.trim();
    var button = forgotElement.querySelector("#forgot-send");
    if (!email) {
      forgotMessage("先填注册邮箱");
      return;
    }
    button.disabled = true;
    button.textContent = "发送中…";
    forgotMessage("");
    try {
      var response = await originalFetch("/api/auth/send-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email, purpose: "reset" }),
      });
      var data = await response.json().catch(function () {
        return {};
      });
      if (!response.ok) {
        forgotMessage(data.error || "验证码发送失败");
        button.disabled = false;
        button.textContent = "获取验证码";
        return;
      }
      var remain = 60;
      button.textContent = remain + "s 后重发";
      var timer = window.setInterval(function () {
        remain -= 1;
        if (remain <= 0) {
          window.clearInterval(timer);
          button.disabled = false;
          button.textContent = "获取验证码";
        } else {
          button.textContent = remain + "s 后重发";
        }
      }, 1000);
      forgotMessage("验证码已生成（Mock：请看后端控制台）", true);
    } catch (error) {
      forgotMessage((error && error.message) || "网络异常，请重试");
      button.disabled = false;
      button.textContent = "获取验证码";
    }
  }

  async function forgotSubmit() {
    var email = forgotElement.querySelector("#forgot-email").value.trim();
    var code = forgotElement.querySelector("#forgot-code").value.trim();
    var password = forgotElement.querySelector("#forgot-password").value;
    var confirm = forgotElement.querySelector("#forgot-confirm").value;
    var button = forgotElement.querySelector("#forgot-submit");
    if (!email || !/^\d{6}$/.test(code)) {
      forgotMessage("邮箱和 6 位验证码都要填");
      return;
    }
    if (password !== confirm) {
      forgotMessage("两次输入的新密码不一致");
      return;
    }
    button.disabled = true;
    button.textContent = "重置中…";
    forgotMessage("");
    try {
      var response = await originalFetch("/api/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: email,
          code: code,
          new_password: password,
          confirm_password: confirm,
        }),
      });
      var data = await response.json().catch(function () {
        return {};
      });
      if (!response.ok) {
        forgotMessage(data.error || "重置失败，请检查验证码");
        return;
      }
      forgotMessage("密码已重置，请用新密码登录", true);
      if (gateElement) {
        gateElement.querySelector("#auth-email").value = email;
        gateElement.querySelector("#auth-password").value = "";
      }
      window.setTimeout(closeForgotModal, 1200);
    } catch (error) {
      forgotMessage((error && error.message) || "网络异常，请重试");
    } finally {
      button.disabled = false;
      button.textContent = "重置密码";
    }
  }

  function boot() {
    verifySession();
    initImportUi();
    updateSidebarUser();
    initAccountSettings();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();