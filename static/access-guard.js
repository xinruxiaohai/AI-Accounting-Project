/* ==================================================================
 * AI记账管家 · 全站访问密码（v0.11.1）
 *
 * 职责一：给所有 /api/ 请求自动带上 X-Access-Token。
 * 职责二：没设密码时完全透明；设了密码就盖一层全屏遮罩，验证通过后
 *         把 token + 验证时间写进 localStorage，刷新页只要没超时就不弹。
 * 职责三：超时到点立刻重新上锁（阻断查看和操作），并对外暴露
 *         DSHAccess.isFresh()/verifyPassword()，供后台「改密码要 5 分钟内验证」
 *         那条规则判断。
 * ================================================================== */
(function () {
  "use strict";

  var STORE_KEY = {
    token: "dsh.accessToken",
    verifiedAt: "dsh.accessVerifiedAt",
    timeout: "dsh.accessTimeoutMinutes"
  };

  // 后台敏感操作（改密码 / 删密码 / 调超时）要求 5 分钟内验证过密码
  var FRESH_MINUTES = 5;

  var config = { protected: false, timeout_minutes: 60, password_count: 0 };
  var overlay = null;
  var inputEl = null;
  var errorEl = null;
  var submitEl = null;
  var hintEl = null;
  var verifying = false;
  var expiryTimer = null;
  var nativeFetch = window.fetch ? window.fetch.bind(window) : null;

  function number(value, fallback) {
    var parsed = Number(value);
    return isFinite(parsed) ? parsed : fallback;
  }

  function readToken() {
    try {
      return window.localStorage.getItem(STORE_KEY.token) || "";
    } catch (error) {
      return "";
    }
  }

  function readVerifiedAt() {
    try {
      return number(window.localStorage.getItem(STORE_KEY.verifiedAt), 0);
    } catch (error) {
      return 0;
    }
  }

  function readTimeout() {
    try {
      var stored = number(window.localStorage.getItem(STORE_KEY.timeout), 0);
      return stored > 0 ? stored : number(config.timeout_minutes, 60);
    } catch (error) {
      return number(config.timeout_minutes, 60);
    }
  }

  function storeVerified(token, timeoutMinutes) {
    try {
      window.localStorage.setItem(STORE_KEY.token, token || "");
      window.localStorage.setItem(STORE_KEY.verifiedAt, String(Date.now()));
      window.localStorage.setItem(STORE_KEY.timeout, String(timeoutMinutes || 60));
    } catch (error) {
      /* 隐身模式下写不进 localStorage：当前页面照常可用，刷新会再问一次 */
    }
  }

  function clearVerified() {
    try {
      window.localStorage.removeItem(STORE_KEY.token);
      window.localStorage.removeItem(STORE_KEY.verifiedAt);
    } catch (error) {
      /* ignore */
    }
  }

  /** 剩余有效秒数；已超时返回 0 */
  function remainingSeconds() {
    if (!config.protected) {
      return Infinity;
    }
    var ageSeconds = (Date.now() - readVerifiedAt()) / 1000;
    var left = readTimeout() * 60 - ageSeconds;
    return left > 0 ? left : 0;
  }

  function isValid() {
    if (!config.protected) {
      return true;
    }
    return !!readToken() && remainingSeconds() > 0;
  }

  /** 距离上次验证是否还在 minutes 分钟以内（后台敏感操作用） */
  function isFresh(minutes) {
    if (!config.protected) {
      return true;
    }
    var limit = number(minutes, FRESH_MINUTES) * 60000;
    return !!readToken() && Date.now() - readVerifiedAt() <= limit;
  }

  function humanizeLeft() {
    var left = remainingSeconds();
    if (!isFinite(left)) {
      return "";
    }
    var minutes = Math.ceil(left / 60);
    if (minutes <= 1) {
      return "不到 1 分钟";
    }
    if (minutes < 60) {
      return minutes + " 分钟";
    }
    var hours = Math.floor(minutes / 60);
    var rest = minutes % 60;
    return hours + " 小时" + (rest ? " " + rest + " 分钟" : "");
  }

  /* ---------------- 遮罩层 ---------------- */

  function buildOverlay() {
    var mask = document.createElement("div");
    mask.className = "access-overlay";
    mask.id = "access-overlay";
    mask.setAttribute("role", "dialog");
    mask.setAttribute("aria-modal", "true");
    mask.innerHTML =
      '<div class="access-card">' +
      '  <div class="access-badge">' +
      '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
      '         stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      "      <rect x=\"4\" y=\"10\" width=\"16\" height=\"10\" rx=\"2\"></rect>" +
      "      <path d=\"M8 10V7a4 4 0 0 1 8 0v3\"></path>" +
      "    </svg>" +
      "  </div>" +
      '  <h2 class="access-title">本站已设置访问密码</h2>' +
      '  <p class="access-sub" id="access-sub">输入密码后才能查看账本与操作。</p>' +
      '  <form class="access-form" id="access-form" autocomplete="off">' +
      '    <input class="access-input" id="access-input" type="password" ' +
      '           placeholder="输入访问密码" autocomplete="current-password" maxlength="64">' +
      '    <p class="access-error" id="access-error" hidden></p>' +
      '    <button class="access-btn" id="access-submit" type="submit">解锁</button>' +
      "  </form>" +
      '  <p class="access-foot" id="access-foot"></p>' +
      "</div>";
    document.body.appendChild(mask);

    overlay = mask;
    inputEl = mask.querySelector("#access-input");
    errorEl = mask.querySelector("#access-error");
    submitEl = mask.querySelector("#access-submit");
    hintEl = mask.querySelector("#access-sub");
    mask.querySelector("#access-foot").textContent =
      "验证通过后 " + readTimeout() + " 分钟内免密，超时会自动重新上锁。";

    mask.querySelector("#access-form").addEventListener("submit", function (event) {
      event.preventDefault();
      submit();
    });

    inputEl.addEventListener("input", function () {
      errorEl.hidden = true;
      inputEl.classList.remove("is-invalid");
    });
  }

  function showOverlay(message) {
    if (!config.protected) {
      return;
    }
    if (!overlay) {
      buildOverlay();
    }
    if (message) {
      errorEl.textContent = message;
      errorEl.hidden = false;
    }
    if (hintEl) {
      hintEl.textContent =
        "本站已设置访问密码，共 " + number(config.password_count, 1) + " 个可用密码；输入任意一个即可解锁。";
    }
    overlay.classList.add("is-show");
    document.documentElement.classList.add("access-locked");
    window.setTimeout(function () {
      if (inputEl) {
        inputEl.value = "";
        inputEl.focus();
      }
    }, 120);
  }

  function hideOverlay() {
    if (overlay) {
      overlay.classList.remove("is-show");
    }
    document.documentElement.classList.remove("access-locked");
  }

  function setBusy(busy) {
    verifying = busy;
    if (submitEl) {
      submitEl.disabled = busy;
      submitEl.textContent = busy ? "验证中…" : "解锁";
    }
  }

  function submit() {
    if (verifying) {
      return;
    }
    var password = inputEl ? String(inputEl.value || "") : "";
    if (!password) {
      errorEl.textContent = "请输入访问密码";
      errorEl.hidden = false;
      return;
    }
    setBusy(true);
    nativeFetch("/api/access/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: password })
    })
      .then(function (response) {
        return response.json().catch(function () {
          return {};
        }).then(function (data) {
          if (!response.ok) {
            throw new Error(data.error || "密码不正确");
          }
          return data;
        });
      })
      .then(function (data) {
        storeVerified(data.token, data.timeout_minutes || config.timeout_minutes);
        setBusy(false);
        hideOverlay();
        // 刚解锁时页面上的数据请求都还是 401 的空壳，直接刷新一遍最干净
        window.location.reload();
      })
      .catch(function (error) {
        setBusy(false);
        errorEl.textContent = (error && error.message) || "密码不正确，请重新输入";
        errorEl.hidden = false;
        inputEl.classList.add("is-invalid");
        if (inputEl) {
          inputEl.select();
        }
        if (overlay) {
          overlay.classList.remove("access-shake");
          void overlay.offsetWidth; // 强制重排，让抖动动画可以连续触发
          overlay.classList.add("access-shake");
        }
      });
  }

  /** 供后台设置面板用：当场验证一次当前密码，成功后顺带刷新 token 时间 */
  function verifyPassword(password) {
    return nativeFetch("/api/access/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: String(password || "") })
    }).then(function (response) {
      return response.json().catch(function () {
        return {};
      }).then(function (data) {
        if (!response.ok) {
          throw new Error(data.error || "密码不正确");
        }
        storeVerified(data.token, data.timeout_minutes || config.timeout_minutes);
        return data;
      });
    });
  }

  /* ---------------- fetch 拦截：自动带 token ---------------- */

  function withToken(input, init) {
    if (!readToken()) {
      return [input, init];
    }
    var url = typeof input === "string" ? input : (input && input.url) || "";
    if (url.indexOf("/api/") === -1) {
      return [input, init];
    }

    var options = init ? Object.assign({}, init) : {};
    var headers;
    if (options.headers instanceof Headers) {
      headers = new Headers(options.headers);
    } else if (Array.isArray(options.headers)) {
      headers = new Headers(options.headers);
    } else {
      headers = new Headers(options.headers || {});
    }
    headers.set("X-Access-Token", readToken());
    options.headers = headers;
    return [input, options];
  }

  if (nativeFetch) {
    window.fetch = function (input, init) {
      var args = withToken(input, init);
      return nativeFetch(args[0], args[1]).then(function (response) {
        if (response.status === 401 && config.protected) {
          // 只认后端明确说「需要输入访问密码」的那种 401：
          // 设置面板的 reauth_required 要让后台自己弹框，不能直接盖上遮罩
          response
            .clone()
            .json()
            .then(function (data) {
              if (data && data.code === "access_required") {
                clearVerified();
                showOverlay("验证已过期，请重新输入访问密码");
              }
            })
            .catch(function () {
              /* 401 但响应不是 JSON：不动，交给业务层处理 */
            });
        }
        return response;
      });
    };
  }

  /* ---------------- 启动 ---------------- */

  function startExpiryWatch() {
    if (expiryTimer) {
      window.clearInterval(expiryTimer);
    }
    expiryTimer = window.setInterval(function () {
      if (!config.protected) {
        return;
      }
      if (!isValid()) {
        showOverlay("验证已超时，请重新输入访问密码");
        return;
      }
      if (hintEl && overlay && overlay.classList.contains("is-show")) {
        hintEl.textContent = "本次验证还剩 " + humanizeLeft() + "。";
      }
    }, 15000);
  }

  function boot() {
    if (!nativeFetch) {
      return;
    }
    nativeFetch("/api/access/config", { headers: { Accept: "application/json" } })
      .then(function (response) {
        return response.json();
      })
      .then(function (data) {
        config = {
          protected: !!(data && data.protected),
          timeout_minutes: number(data && data.timeout_minutes, 60),
          password_count: number(data && data.password_count, 0)
        };
        if (!config.protected) {
          clearVerified();
          return;
        }
        if (isValid()) {
          return;
        }
        clearVerified();
        showOverlay("");
        startExpiryWatch();
      })
      .catch(function () {
        /* 拿不到配置（后端没起）：不锁，避免把用户挡在门外 */
      });
  }

  // 对外接口：后台设置面板拿它做「5 分钟内免密」判断
  window.DSHAccess = {
    config: function () {
      return config;
    },
    isValid: isValid,
    isFresh: isFresh,
    remainingSeconds: remainingSeconds,
    verifyPassword: verifyPassword,
    lock: function (message) {
      clearVerified();
      showOverlay(message || "");
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
