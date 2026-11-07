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

  /* ---------------- 登录页 Canvas 粒子背景（v0.13.8） ---------------- */
  function initAuthBackground() {
    var canvas = document.getElementById("auth-bg-canvas");
    if (!canvas) {
      return;
    }
    // 尊重「减少动态效果」：隐藏画布，保留 CSS 渐变兜底
    var reduceMotion = window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) {
      canvas.style.display = "none";
      return;
    }

    var ctx = canvas.getContext("2d");
    var gate = document.getElementById("auth-gate") || document.body;
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var W = 0, H = 0, particles = [], rafId = null;
    var mouse = { x: -9999, y: -9999 };
    var COLORS = ["#60a5fa", "#34d399", "#22d3ee", "#818cf8"];
    var MAX_DIST = 130;

    function resize() {
      W = gate.clientWidth || window.innerWidth;
      H = gate.clientHeight || window.innerHeight;
      canvas.width = Math.floor(W * dpr);
      canvas.height = Math.floor(H * dpr);
      canvas.style.width = W + "px";
      canvas.style.height = H + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      buildParticles();
    }

    function buildParticles() {
      // 粒子数随视口面积缩放：约每 10000px² 一个，限制在 28~120
      var count = Math.max(28, Math.min(120, Math.floor((W * H) / 10000)));
      particles = [];
      for (var i = 0; i < count; i += 1) {
        particles.push({
          x: Math.random() * W,
          y: Math.random() * H,
          vx: (Math.random() - 0.5) * 0.35,
          vy: (Math.random() - 0.5) * 0.35,
          r: Math.random() * 1.6 + 1.2,
          c: COLORS[(Math.random() * COLORS.length) | 0]
        });
      }
    }

    function draw() {
      ctx.clearRect(0, 0, W, H);
      var i, p, dxm, dym, dm, f;
      for (i = 0; i < particles.length; i += 1) {
        p = particles[i];
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < 0 || p.x > W) p.vx *= -1;
        if (p.y < 0 || p.y > H) p.vy *= -1;
        // 鼠标轻微交互：靠近的粒子被轻轻推开
        dxm = p.x - mouse.x;
        dym = p.y - mouse.y;
        dm = Math.sqrt(dxm * dxm + dym * dym);
        if (dm < 110) {
          f = (110 - dm) / 110;
          p.x += (dxm / (dm || 1)) * f * 1.2;
          p.y += (dym / (dm || 1)) * f * 1.2;
        }
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.globalAlpha = 0.85;
        ctx.fillStyle = p.c;
        ctx.fill();
      }
      ctx.globalAlpha = 1;
      // 邻近粒子连线
      for (var a = 0; a < particles.length; a += 1) {
        for (var b = a + 1; b < particles.length; b += 1) {
          var pa = particles[a], pb = particles[b];
          var dx = pa.x - pb.x, dy = pa.y - pb.y;
          var d = Math.sqrt(dx * dx + dy * dy);
          if (d < MAX_DIST) {
            ctx.beginPath();
            ctx.moveTo(pa.x, pa.y);
            ctx.lineTo(pb.x, pb.y);
            ctx.strokeStyle = "rgba(148, 163, 184, " + (0.18 * (1 - d / MAX_DIST)) + ")";
            ctx.lineWidth = 1;
            ctx.stroke();
          }
        }
      }
      // 鼠标连线
      for (var k = 0; k < particles.length; k += 1) {
        var pk = particles[k];
        var dkx = pk.x - mouse.x, dky = pk.y - mouse.y;
        var dk = Math.sqrt(dkx * dkx + dky * dky);
        if (dk < MAX_DIST) {
          ctx.beginPath();
          ctx.moveTo(pk.x, pk.y);
          ctx.lineTo(mouse.x, mouse.y);
          ctx.strokeStyle = "rgba(96, 165, 250, " + (0.22 * (1 - dk / MAX_DIST)) + ")";
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      }
    }

    function loop() {
      rafId = window.requestAnimationFrame(loop);
      // 标签页隐藏或登录遮罩已收起时不绘制，避免空耗 CPU
      if (document.hidden || gate.hidden || canvas.offsetParent === null) {
        return;
      }
      draw();
    }

    gate.addEventListener("mousemove", function (e) {
      var rect = canvas.getBoundingClientRect();
      mouse.x = e.clientX - rect.left;
      mouse.y = e.clientY - rect.top;
    });
    gate.addEventListener("mouseleave", function () {
      mouse.x = -9999;
      mouse.y = -9999;
    });
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) {
        resize();
      }
    });

    resize();
    loop();
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
      '<canvas id="auth-bg-canvas"></canvas>' +
      '<div class="auth-card">' +
        '<div class="auth-brand">' +
          '<img class="auth-logo-img" id="auth-brand-logo" src="/static/images/logo-main.png" alt="智汇账">' +
          "<h1>智汇账</h1>" +
          "<p>您的 AI 资产管家 · 登录后账本只属于你</p>" +
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
          '<p class="auth-field-error" id="auth-password-error" hidden></p>' +
          // v0.13.5：确认密码只在注册视图出现，登录不渲染这一段（避免影响老用户登录）
          '<label class="auth-label auth-confirm" hidden>确认密码' +
            '<input id="auth-confirm-password" class="form-control" type="password" autocomplete="new-password" placeholder="再输入一次密码">' +
          "</label>" +
          '<p class="auth-field-error" id="auth-confirm-error" hidden></p>' +
          '<div class="auth-forgot"><button type="button" id="auth-forgot-btn">忘记密码？</button></div>' +
          '<label class="auth-label auth-phone" hidden>手机号（可选）' +
            '<input id="auth-phone" class="form-control" type="tel" autocomplete="tel" placeholder="用于以后找回密码">' +
          "</label>" +
          '<div class="auth-register-extra" hidden>' +
            '<label class="auth-label">昵称' +
              '<input id="auth-nickname" class="form-control" type="text" maxlength="20" placeholder="请输入您的昵称（选填）">' +
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
            '<p class="auth-lock-hint" id="auth-lock-hint">滑动解锁后，才能发送验证码和提交注册</p>' +
          "</div>" +
          '<p class="auth-error" id="auth-error" hidden></p>' +
          '<button class="btn btn-primary w-100 auth-submit" type="submit" id="auth-submit">登录</button>' +
        "</form>" +
      "</div>";
    document.body.appendChild(gateElement);
    // 登录页的品牌图标同样跟随「品牌图标主题」
    applyBrandLogo();
    // v0.13.8：登录页动态粒子背景（蓝绿粒子网络 + 鼠标轻交互）
    initAuthBackground();

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
    // v0.13.5：注册视图的实时反馈——密码强度/二次确认不一致即时变红
    var passwordField = gateElement.querySelector("#auth-password");
    if (passwordField) {
      passwordField.addEventListener("input", function () {
        if (gateMode !== "register") {
          return;
        }
        var message = this.value ? registerPasswordError(this.value) : "";
        setFieldError(this, gateElement.querySelector("#auth-password-error"), message);
        syncConfirmHint();
      });
    }
    var confirmField = gateElement.querySelector("#auth-confirm-password");
    if (confirmField) {
      confirmField.addEventListener("input", function () {
        if (gateMode !== "register") {
          return;
        }
        var passwordValue = gateElement.querySelector("#auth-password").value;
        var message = this.value && this.value !== passwordValue ? "两次输入的密码不一致" : "";
        setFieldError(this, gateElement.querySelector("#auth-confirm-error"), message);
      });
    }
    syncRegisterLock();
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
    // v0.13.5：确认密码只在注册视图显示；切回登录时清空，绝不参与登录校验
    var confirmLabel = gateElement.querySelector(".auth-confirm");
    if (confirmLabel) {
      confirmLabel.hidden = gateMode !== "register";
    }
    var confirmInput = gateElement.querySelector("#auth-confirm-password");
    if (confirmInput && gateMode !== "register") {
      confirmInput.value = "";
    }
    clearFieldErrors();
    resetSlider();
    var passwordInput = gateElement.querySelector("#auth-password");
    if (passwordInput) {
      passwordInput.placeholder = gateMode === "register" ? "至少 8 位，需含字母和数字" : "请输入密码";
    }
    syncRegisterLock();
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

  /* ---------------- v0.13.5：注册专属校验（登录一律不碰） ---------------- */

  // 注册密码规则：至少 8 位，且必须同时含字母和数字（纯数字直接拒绝）。
  function registerPasswordError(password) {
    if (!password) {
      return "请设置密码";
    }
    if (password.length < 8) {
      return "密码至少 8 位";
    }
    if (!/[A-Za-z]/.test(password) || !/[0-9]/.test(password)) {
      return "密码不能是纯数字，需同时包含字母和数字";
    }
    return "";
  }

  function setFieldError(input, errorElement, message) {
    if (input) {
      input.classList.toggle("is-invalid", Boolean(message));
    }
    if (errorElement) {
      errorElement.textContent = message || "";
      errorElement.hidden = !message;
    }
  }

  function clearFieldErrors() {
    if (!gateElement) {
      return;
    }
    setFieldError(gateElement.querySelector("#auth-password"), gateElement.querySelector("#auth-password-error"), "");
    setFieldError(
      gateElement.querySelector("#auth-confirm-password"),
      gateElement.querySelector("#auth-confirm-error"),
      ""
    );
  }

  // 滑块未解锁 → 发送验证码 / 注册并进入 都置灰并拦截（仅注册视图生效）。
  function syncRegisterLock() {
    if (!gateElement) {
      return;
    }
    var locked = gateMode === "register" && !sliderUnlocked;
    var sendButton = gateElement.querySelector("#auth-send-code");
    var submitButton = gateElement.querySelector("#auth-submit");
    var hint = gateElement.querySelector("#auth-lock-hint");
    if (sendButton) {
      var counting = sendButton.getAttribute("data-counting") === "1";
      sendButton.classList.toggle("is-locked", locked);
      sendButton.disabled = locked || counting;
      sendButton.setAttribute("aria-disabled", locked ? "true" : "false");
    }
    if (submitButton) {
      submitButton.classList.toggle("is-locked", locked);
      submitButton.disabled = locked;
      submitButton.setAttribute("aria-disabled", locked ? "true" : "false");
    }
    if (hint) {
      hint.hidden = !locked;
    }
  }

  // 密码改动后同步刷新「确认密码」的红字（只在用户已经填过时提示）
  function syncConfirmHint() {
    if (!gateElement) {
      return;
    }
    var confirmInput = gateElement.querySelector("#auth-confirm-password");
    if (!confirmInput) {
      return;
    }
    var passwordValue = gateElement.querySelector("#auth-password").value;
    var message = confirmInput.value && confirmInput.value !== passwordValue ? "两次输入的密码不一致" : "";
    setFieldError(confirmInput, gateElement.querySelector("#auth-confirm-error"), message);
  }

  function validateRegisterFields() {
    if (!gateElement) {
      return true;
    }
    var passwordInput = gateElement.querySelector("#auth-password");
    var confirmInput = gateElement.querySelector("#auth-confirm-password");
    var password = passwordInput ? passwordInput.value : "";
    var confirm = confirmInput ? confirmInput.value : "";
    var passwordError = registerPasswordError(password);
    setFieldError(passwordInput, gateElement.querySelector("#auth-password-error"), passwordError);
    var confirmError = "";
    if (!confirm) {
      confirmError = "请再输入一次密码";
    } else if (confirm !== password) {
      confirmError = "两次输入的密码不一致";
    }
    setFieldError(confirmInput, gateElement.querySelector("#auth-confirm-error"), confirmError);
    if (passwordError) {
      gateError(passwordError);
      return false;
    }
    if (confirmError) {
      gateError(confirmError);
      return false;
    }
    return true;
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
    // v0.13.5：强密码 + 二次确认 + 滑块只看注册视图。
    // 切到【登录】时这段完全不执行——历史账号只要非空就能发请求。
    if (gateMode === "register") {
      if (!validateRegisterFields()) {
        return;
      }
      if (!sliderUnlocked) {
        gateError("请先按住滑块拖到最右侧完成人机校验");
        return;
      }
    } else {
      clearFieldErrors();
    }

    var code = "";
    if (gateMode === "register") {
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
      button.textContent = gateMode === "register" ? "注册并进入" : "登录";
      syncRegisterLock();
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
        syncRegisterLock();
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
    syncRegisterLock();
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
    // v0.13.5：注册视图必须先解锁滑块，才允许发送验证码
    if (gateMode === "register" && !sliderUnlocked) {
      gateError("请先按住滑块拖到最右侧完成人机校验");
      return;
    }
    button.setAttribute("data-counting", "1");
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
        button.setAttribute("data-counting", "0");
        button.textContent = "获取验证码";
        syncRegisterLock();
        return;
      }
      // 真实发信（已配置 SMTP）或降级控制台（未配置），统一倒计时 60 秒
      var seconds = 60;
      button.textContent = seconds + "s 后重发";
      var timer = window.setInterval(function () {
        seconds -= 1;
        if (seconds <= 0) {
          window.clearInterval(timer);
          button.setAttribute("data-counting", "0");
          button.textContent = "获取验证码";
          syncRegisterLock();
        } else {
          button.textContent = seconds + "s 后重发";
        }
      }, 1000);
      gateError("");
      showFunnyToast(
        data && data.delivered
          ? "验证码已发送到邮箱，5 分钟内有效"
          : "验证码已生成：邮箱服务未配置，请在后端控制台查看 6 位数字"
      );
    } catch (error) {
      gateError("网络异常，验证码没发出去");
      button.setAttribute("data-counting", "0");
      button.textContent = "获取验证码";
      syncRegisterLock();
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

  /* ---------------- v0.13.6：品牌图标主题（侧边栏 + 登录页） ---------------- */

  var BRAND_LOGO_KEY = "ai-accounting-brand-logo";
  var BRAND_LOGO_FILES = [
    "logo-main.png",
    "logo-theme-1.png",
    "logo-theme-2.png",
    "logo-theme-3.png",
    "logo-theme-4.png",
    "logo-theme-5.png",
    "logo-theme-6.png",
    "logo-theme-7.png"
  ];
  var BRAND_LOGO_LABELS = [
    "默认 Logo",
    "主题 1",
    "主题 2",
    "主题 3",
    "主题 4",
    "主题 5",
    "主题 6",
    "主题 7"
  ];

  function brandLogoFile(file) {
    return BRAND_LOGO_FILES.indexOf(file) >= 0 ? file : BRAND_LOGO_FILES[0];
  }

  function brandLogoSrc(file) {
    return "/static/images/" + brandLogoFile(file);
  }

  function readBrandLogo() {
    try {
      return brandLogoFile(localStorage.getItem(BRAND_LOGO_KEY) || BRAND_LOGO_FILES[0]);
    } catch (error) {
      return BRAND_LOGO_FILES[0];
    }
  }

  function syncBrandLogoSelection() {
    var grid = document.getElementById("brand-logo-grid");
    if (!grid) {
      return;
    }
    var current = readBrandLogo();
    Array.prototype.forEach.call(grid.querySelectorAll("[data-brand-logo]"), function (option) {
      var active = option.getAttribute("data-brand-logo") === current;
      option.classList.toggle("is-active", active);
      option.setAttribute("aria-checked", active ? "true" : "false");
    });
  }

  /** 把选中的品牌图标同步到侧边栏与登录页；Favicon / PWA 图标固定 logo-main，不受影响 */
  function applyBrandLogo() {
    var src = brandLogoSrc(readBrandLogo());
    ["sidebar-brand-logo", "auth-brand-logo"].forEach(function (id) {
      var element = document.getElementById(id);
      if (element && element.getAttribute("src") !== src) {
        element.setAttribute("src", src);
      }
    });
    syncBrandLogoSelection();
  }

  function setBrandLogo(file) {
    try {
      localStorage.setItem(BRAND_LOGO_KEY, brandLogoFile(file));
    } catch (error) {
      /* 隐私模式下写不进去就只影响本次会话 */
    }
    applyBrandLogo();
  }

  /** 4 列 × 2 行网格；只在第一次打开设置时渲染，之后只切选中态 */
  function buildBrandLogoGrid() {
    var grid = document.getElementById("brand-logo-grid");
    if (!grid || grid.getAttribute("data-ready") === "1") {
      return;
    }
    grid.setAttribute("data-ready", "1");
    grid.innerHTML = BRAND_LOGO_FILES.map(function (file, index) {
      return (
        '<button type="button" class="brand-logo-option" data-brand-logo="' + file + '" ' +
        'role="radio" aria-checked="false" title="' + BRAND_LOGO_LABELS[index] + '" ' +
        'aria-label="' + BRAND_LOGO_LABELS[index] + '">' +
        '<img src="' + brandLogoSrc(file) + '" alt="' + BRAND_LOGO_LABELS[index] + '" loading="lazy">' +
        "</button>"
      );
    }).join("");
    grid.addEventListener("click", function (event) {
      var option = event.target.closest("[data-brand-logo]");
      if (!option) {
        return;
      }
      setBrandLogo(option.getAttribute("data-brand-logo"));
      if (typeof toast === "function") {
        toast("品牌图标已切换，侧边栏与登录页立即生效", "success");
      }
    });
    syncBrandLogoSelection();
  }

  window.ZHAccountBrandLogo = {
    files: BRAND_LOGO_FILES,
    labels: BRAND_LOGO_LABELS,
    read: readBrandLogo,
    apply: applyBrandLogo,
    set: setBrandLogo,
    src: brandLogoSrc,
    buildGrid: buildBrandLogoGrid
  };

  /* ---------------- v0.12.2：侧栏昵称 ---------------- */

  function displayName(user) {
    var name = (user && user.nickname) || ((user && user.email) ? String(user.email).split("@")[0] : "");
    // v0.13.6 防呆红线：昵称/邮箱前缀之外绝不再拼品牌名，只在两者都没有时兜底显示品牌
    return name || "智汇账";
  }

  function avatarLetter(user) {
    var text = displayName(user).trim();
    return (text ? text.slice(0, 1) : "A").toUpperCase();
  }

  function accountingDays(user) {
    var raw = user && user.created_at;
    if (!raw) {
      return 1;
    }
    var start = new Date(String(raw).replace(" ", "T"));
    if (isNaN(start.getTime())) {
      return 1;
    }
    var diff = Math.floor((Date.now() - start.getTime()) / 86400000);
    return Math.max(1, diff + 1);
  }

  function avatarUrlOf(user) {
    return user && user.avatar ? String(user.avatar) : "";
  }

  // 有自定义头像就显示图片，否则回退成昵称首字母色块。
  function applyAvatar(letterEl, imgEl, user) {
    var url = avatarUrlOf(user);
    if (letterEl) {
      letterEl.textContent = avatarLetter(user);
      letterEl.hidden = !!url;
    }
    if (imgEl) {
      if (url) {
        imgEl.src = url;
        imgEl.hidden = false;
      } else {
        imgEl.removeAttribute("src");
        imgEl.hidden = true;
      }
    }
  }

  function fillProfileModal(user) {
    var person = user || getUser() || {};
    var name = displayName(person);
    var letterEl = document.getElementById("profile-avatar");
    var avatarImg = document.getElementById("profile-avatar-img");
    applyAvatar(letterEl, avatarImg, person);
    var nameEl = document.getElementById("profile-name");
    if (nameEl) {
      nameEl.textContent = name;
    }
    var nickEl = document.getElementById("profile-nickname");
    if (nickEl) {
      nickEl.textContent = person.nickname || name;
    }
    var daysEl = document.getElementById("profile-days");
    if (daysEl) {
      daysEl.textContent = "记账第 " + accountingDays(person) + " 天";
    }
    var uidEl = document.getElementById("profile-uid");
    if (uidEl) {
      uidEl.textContent = person.id === undefined || person.id === null ? "—" : String(person.id);
    }
    var createdEl = document.getElementById("profile-created");
    if (createdEl) {
      createdEl.textContent = person.created_at ? String(person.created_at).slice(0, 10) : "—";
    }
    var bindEl = document.getElementById("profile-bind");
    if (bindEl) {
      bindEl.textContent = person.email || "未绑定";
    }
    var phoneEl = document.getElementById("profile-phone");
    if (phoneEl) {
      var phone = String(person.phone || "");
      phoneEl.textContent = phone ? phone.replace(/^(\d{3})\d{4}(\d{4})$/, "$1****$2") : "未绑定";
      phoneEl.classList.toggle("pc-muted", !phone);
    }
  }

  function updateSidebarUser() {
    var user = getUser() || {};
    var name = displayName(user);
    var nameEl = document.getElementById("sidebar-brand-name");
    if (nameEl) {
      nameEl.textContent = name;
    }
    applyAvatar(
      document.getElementById("sidebar-avatar-letter"),
      document.getElementById("sidebar-avatar-img"),
      user
    );
    var avatarBtn = document.getElementById("sidebar-avatar");
    if (avatarBtn) {
      var uidText = user.id === undefined || user.id === null ? "" : "UID " + user.id;
      avatarBtn.title = "个人中心" + (uidText ? " · " + uidText : "");
      avatarBtn.setAttribute("aria-label", "个人中心：" + name);
    }
    fillProfileModal(user);
  }

  function refreshProfileFromServer() {
    if (!getToken()) {
      return;
    }
    originalFetch("/api/auth/me", { headers: { Authorization: "Bearer " + getToken() } })
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (data) {
        if (data && data.user) {
          try {
            localStorage.setItem(USER_KEY, JSON.stringify(data.user));
          } catch (error) {
            /* 忽略 */
          }
          updateSidebarUser();
        }
      })
      .catch(function () {
        /* 离线时沿用本地缓存 */
      });
  }

  function copyUid() {
    var uidEl = document.getElementById("profile-uid");
    var text = uidEl ? uidEl.textContent : "";
    if (!text || text === "—") {
      return;
    }
    var done = function () {
      if (typeof toast === "function") {
        toast("UID 已复制", "success");
      }
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () {
        if (typeof toast === "function") {
          toast("复制失败，请手动选择", "error");
        }
      });
      return;
    }
    var input = document.createElement("input");
    input.value = text;
    document.body.appendChild(input);
    input.select();
    try {
      document.execCommand("copy");
      done();
    } catch (error) {
      /* 忽略 */
    }
    document.body.removeChild(input);
  }

  function openSettingsAt(tab, focusId) {
    var modalEl = document.getElementById("settings-modal");
    if (!modalEl || !window.bootstrap) {
      return;
    }
    var profileEl = document.getElementById("profile-modal");
    if (profileEl) {
      window.bootstrap.Modal.getOrCreateInstance(profileEl).hide();
    }
    var instance = window.bootstrap.Modal.getOrCreateInstance(modalEl);
    var once = function () {
      modalEl.removeEventListener("shown.bs.modal", once);
      var tabBtn = modalEl.querySelector('[data-settings-tab="' + tab + '"]');
      if (tabBtn) {
        tabBtn.click();
      }
      if (focusId) {
        var field = document.getElementById(focusId);
        if (field) {
          setTimeout(function () {
            field.focus();
          }, 120);
        }
      }
    };
    modalEl.addEventListener("shown.bs.modal", once);
    instance.show();
  }

  function uploadAvatar(file) {
    if (!file) {
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      if (typeof toast === "function") {
        toast("头像图片不能超过 5MB", "error");
      }
      return;
    }
    var token = getToken();
    var form = new FormData();
    form.append("file", file);
    if (typeof toast === "function") {
      toast("头像上传中…");
    }
    originalFetch("/api/auth/avatar/upload", {
      method: "POST",
      headers: { Authorization: "Bearer " + token },
      body: form,
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { ok: response.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok || !result.data.user) {
          throw new Error(result.data.error || "头像上传失败");
        }
        try {
          localStorage.setItem(USER_KEY, JSON.stringify(result.data.user));
        } catch (error) {
          /* 忽略 */
        }
        updateSidebarUser();
        if (typeof toast === "function") {
          toast("头像已更新", "success");
        }
      })
      .catch(function (error) {
        if (typeof toast === "function") {
          toast(error.message || "头像上传失败", "error");
        }
      });
  }

  /* ---------------- v0.13.6：头像大图预览（Lightbox） ---------------- */

  function avatarLightboxEl() {
    return document.getElementById("avatar-lightbox");
  }

  function openAvatarLightbox() {
    var box = avatarLightboxEl();
    if (!box) {
      return;
    }
    var user = getUser() || {};
    var url = avatarUrlOf(user);
    var img = document.getElementById("avatar-lightbox-img");
    var letter = document.getElementById("avatar-lightbox-letter");
    var save = document.getElementById("avatar-lightbox-save");
    var hint = document.getElementById("avatar-lightbox-hint");
    if (letter) {
      letter.textContent = avatarLetter(user);
    }
    if (img) {
      if (url) {
        img.setAttribute("src", url);
        img.hidden = false;
        if (letter) {
          letter.hidden = true;
        }
      } else {
        img.removeAttribute("src");
        img.hidden = true;
        if (letter) {
          letter.hidden = false;
        }
      }
    }
    if (save) {
      if (url) {
        // 走 <a download>：同源图片浏览器直接落盘，文件名固定「智汇账_我的头像.png」
        save.setAttribute("href", url);
        save.classList.remove("is-disabled");
        save.removeAttribute("aria-disabled");
      } else {
        save.removeAttribute("href");
        save.classList.add("is-disabled");
        save.setAttribute("aria-disabled", "true");
      }
    }
    if (hint) {
      hint.hidden = !!url;
    }
    box.hidden = false;
    box.setAttribute("aria-hidden", "false");
    document.body.classList.add("has-avatar-lightbox");
    var closeButton = document.getElementById("avatar-lightbox-close");
    if (closeButton) {
      closeButton.focus();
    }
  }

  function closeAvatarLightbox() {
    var box = avatarLightboxEl();
    if (!box || box.hidden) {
      return;
    }
    box.hidden = true;
    box.setAttribute("aria-hidden", "true");
    document.body.classList.remove("has-avatar-lightbox");
  }

  function openProfileModal() {
    var profileEl = document.getElementById("profile-modal");
    if (!profileEl || !window.bootstrap) {
      return;
    }
    fillProfileModal(getUser() || {});
    window.bootstrap.Modal.getOrCreateInstance(profileEl).show();
    refreshProfileFromServer();
  }

  function bindAvatarLightbox() {
    var box = avatarLightboxEl();
    if (!box || box.getAttribute("data-bound") === "1") {
      return;
    }
    box.setAttribute("data-bound", "1");
    box.addEventListener("click", function (event) {
      if (event.target.closest("[data-avatar-lightbox-close]")) {
        closeAvatarLightbox();
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !box.hidden) {
        closeAvatarLightbox();
      }
    });
    var changeButton = document.getElementById("avatar-lightbox-change");
    if (changeButton) {
      changeButton.addEventListener("click", function () {
        closeAvatarLightbox();
        var input = document.getElementById("profile-avatar-input");
        if (input) {
          input.click();
        }
      });
    }
    var profileButton = document.getElementById("avatar-lightbox-profile");
    if (profileButton) {
      // v0.13.7：Lightbox 里已去掉「个人中心」按钮，这里保留兼容旧缓存的兜底
      profileButton.addEventListener("click", function () {
        closeAvatarLightbox();
        openProfileModal();
      });
    }
  }

  function bindProfileUi() {
    var avatarBtn = document.getElementById("sidebar-avatar");
    var profileEl = document.getElementById("profile-modal");
    bindAvatarLightbox();
    if (avatarBtn) {
      // v0.13.7：交互降级——侧边栏头像只开个人中心，大图预览要进个人中心再点头像
      avatarBtn.addEventListener("click", openProfileModal);
    }
    if (profileEl && window.bootstrap) {
      profileEl.addEventListener("shown.bs.modal", function () {
        fillProfileModal(getUser() || {});
      });
    }
    var copyBtn = document.getElementById("profile-copy-uid");
    if (copyBtn) {
      copyBtn.addEventListener("click", copyUid);
    }

    // v0.12.7：头像点击上传 + 信息行跳转设置/提示
    var avatarPick = document.getElementById("profile-avatar-btn");
    var avatarInput = document.getElementById("profile-avatar-input");
    if (avatarPick && avatarInput) {
      avatarPick.addEventListener("click", openAvatarLightbox);
      avatarInput.addEventListener("change", function () {
        var file = avatarInput.files && avatarInput.files[0];
        avatarInput.value = "";
        uploadAvatar(file);
      });
    }
    if (profileEl) {
      profileEl.addEventListener("click", function (event) {
        var row = event.target.closest("[data-profile-action]");
        if (!row) {
          return;
        }
        var action = row.getAttribute("data-profile-action");
        if (action === "nickname") {
          openSettingsAt("personal", "settings-nickname");
        } else if (action === "email" || action === "phone") {
          openSettingsAt("account");
        } else if (action === "member") {
          if (typeof toast === "function") {
            toast("会员体系正在筹备中，先把账记明白更重要", "info");
          }
        } else if (action === "wechat" || action === "qq") {
          if (typeof toast === "function") {
            toast("微信 / QQ 绑定暂未开放，敬请期待", "info");
          }
        }
      });
      profileEl.addEventListener("keydown", function (event) {
        var row = event.target.closest && event.target.closest("[data-profile-action]");
        if (row && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          row.click();
        }
      });
    }
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
    // v0.14.0：通用 pane 切换——所有 [data-settings-tab] 对应
    // #settings-pane-<name>，不再写死 personal/account，help 也能正常显示。
    var tabs = Array.prototype.slice.call(
      document.querySelectorAll("[data-settings-tab]")
    );
    if (!tabs.length) {
      return;
    }
    var panes = Array.prototype.slice.call(
      document.querySelectorAll('[id^="settings-pane-"]')
    );
    var personalFooter = document.getElementById("settings-footer-personal");
    var accountClose = document.getElementById("settings-account-close");

    function showPane(name) {
      var isPersonal = name === "personal";
      var isAccount = name === "account";
      tabs.forEach(function (tab) {
        var active = tab.getAttribute("data-settings-tab") === name;
        tab.classList.toggle("is-active", active);
        tab.setAttribute("aria-selected", active ? "true" : "false");
      });
      panes.forEach(function (pane) {
        pane.hidden = pane.id !== "settings-pane-" + name;
      });
      // 底部按钮只属于 personal / account；help 两个都藏起来
      if (personalFooter) { personalFooter.classList.toggle("d-none", !isPersonal); }
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
    var forgotLink = document.getElementById("change-forgot-link");
    var resetModal = document.getElementById("reset-password-modal");
    var changeModalEl = document.getElementById("change-password-modal");
    if (forgotLink && resetModal) {
      forgotLink.addEventListener("click", function () {
        if (changeModalEl && window.bootstrap) {
          window.bootstrap.Modal.getOrCreateInstance(changeModalEl).hide();
        }
        window.setTimeout(function () {
          var emailInput = document.getElementById("reset-password-email");
          var user = getUser() || {};
          if (emailInput && !emailInput.value && user.email) {
            emailInput.value = user.email;
          }
          setSettingsMessage("reset-password-error", "");
          if (window.bootstrap) {
            window.bootstrap.Modal.getOrCreateInstance(resetModal).show();
          }
        }, 200);
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
    bindProfileUi();
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
      forgotMessage(
        data && data.delivered
          ? "验证码已发送到邮箱，5 分钟内有效"
          : "验证码已生成：邮箱服务未配置，请在后端控制台查看",
        true
      );
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
    // v0.13.6：先套品牌图标，避免侧边栏/登录页在首屏闪一下默认 Logo
    applyBrandLogo();
    verifySession();
    initImportUi();
    updateSidebarUser();
    // 启动即向服务端拉一次最新资料（含头像 / 昵称），保证服务重启后显示不丢
    refreshProfileFromServer();
    initAccountSettings();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();