/* ==========================================================================
 * v0.15.2 · Agent A · 移动端交互重构 —— 账户详情全屏二级页 + 移动端导航栈
 *
 * 背景（已核实的根因，不再重复排查）：
 *   - static/script.js:9034 在 #account-groups 上委托点击，命中行调 selectAccount(name)；
 *     selectAccount 把数据渲染进 #detail-title / #account-records / #account-balance-card /
 *     #invest-board，这些节点全在 templates/index.html 的 .assets-right 里。
 *   - static/style.css 的 @media (max-width:1023.98px) 把 .assets-split 两栏改成上下堆叠，
 *     于是「点账户」在手机上只是往页面下方滚出一块流水 —— 这就是「下方小窗口」的真相。
 *
 * 本文件的做法（不复制任何详情 DOM）：
 *   1) 给 #page-assets 加 .is-account-open，CSS 把现成的 .assets-right 变成 position:fixed 全屏层；
 *   2) 运行时插入 .stack-head（‹ 返回 + 账户名 + ⋯），#detail-title 原地不动；
 *   3) 打开即 history.pushState，系统返回键 / 页面返回按钮 / 左滑 三个入口统一收敛到 history.back()；
 *   4) 打开前记 scrollTop，关闭后精确恢复（±2px）。
 *
 * 零共用文件改动：selectAccount / switchPage 等是 function 声明（全局属性），
 * 这里用 window.selectAccount = ... 包装，script.js 一个字都不动。
 * ========================================================================== */
(function () {
  "use strict";

  /* 断点与 style.css:6268 的 @media (max-width:1023.98px) 完全一致：
     那条规则把两栏压成上下堆叠，也正是本模块要修的问题窗口。 */
  var STACK_QUERY = "(max-width: 1023.98px)";
  /* 必须与 mobile-stack-v0152.css 里的 --zhz-stack-ms 保持一致 */
  var STACK_ANIM_MS = 280;
  var HISTORY_STATE_KEY = "zhz";
  var HISTORY_STATE_VALUE = "account";

  var mq = window.matchMedia ? window.matchMedia(STACK_QUERY) : null;
  var reduceMq = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;

  var doc = document;
  var el = {};

  var stack = {
    ready: false,
    open: false,
    name: "",
    closing: false,
    /** 打开前记录的滚动位置 */
    scroll: { page: 0, main: 0, content: 0 },
    /** 关闭动画结束后要执行的动作（例如从「编辑账户」回列表展开行内表单） */
    afterClose: null,
    /** 最近一次「用户真的点了账户行」的时间戳，用于区分程序化 selectAccount 调用 */
    lastRowTap: 0,
    /** popstate 触发的打开，避免重复 push */
    fromPop: false,
    closeTimer: 0,
    fallbackTimer: 0,
    menuTimer: 0
  };

  function $(id) {
    return doc.getElementById(id);
  }

  function animDuration() {
    return reduceMq && reduceMq.matches ? 0 : STACK_ANIM_MS;
  }

  function isStackViewport() {
    return !!(mq && mq.matches);
  }

  function markTap() {
    stack.lastRowTap = Date.now();
  }

  function tapIsFresh() {
    return Date.now() - stack.lastRowTap < 900;
  }

  /* ======================================================================
   * 一、运行时插入的 DOM（栈头 + 操作菜单）
   * ====================================================================== */

  function buildStackHead() {
    var head = doc.createElement("div");
    head.className = "stack-head";
    /* 返回箭头是 CSS 画的，不引入任何图标资源，也不碰 F 的图标体系 */
    head.innerHTML =
      '<button class="stack-btn stack-back" type="button" aria-label="返回">' +
      '<span class="stack-back-icon" aria-hidden="true"></span>' +
      "</button>" +
      '<span class="stack-title" role="heading" aria-level="2"></span>' +
      '<button class="stack-btn stack-more" type="button" aria-label="更多操作"' +
      ' aria-haspopup="true" aria-expanded="false">' +
      '<span class="stack-more-dots" aria-hidden="true">\u22EF</span>' +
      "</button>";
    return head;
  }

  function buildMenu() {
    var menu = doc.createElement("div");
    menu.className = "stack-menu";
    menu.setAttribute("role", "menu");
    menu.innerHTML =
      '<button class="stack-menu-item" type="button" role="menuitem" data-stack-act="edit">编辑账户</button>' +
      '<button class="stack-menu-item" type="button" role="menuitem" data-stack-act="balance">修改余额</button>' +
      '<button class="stack-menu-item is-danger" type="button" role="menuitem" data-stack-act="delete">删除账户</button>';
    return menu;
  }

  /* ======================================================================
   * 二、滚动锁 / 恢复
   *
   * 为什么选 overflow:hidden 而不是 iOS 的 position:fixed 兜底：
   *   真正在滚的是 #page-assets（.page.active 自带 height:100%; overflow-y:auto），
   *   不是 body/html。position:fixed 兜底只对 body 滚动有效，套在这里必须改 body 定位再
   *   补一个占位元素，反而会把整页高度与滚动位置弄丢。对普通 div 滚动容器，
   *   overflow:hidden 在 iOS 13+ / Android Chrome 上都能可靠锁住手指滚动。
   * ====================================================================== */

  function lockScroll() {
    stack.scroll.page = el.page ? el.page.scrollTop : 0;
    stack.scroll.main = el.main ? el.main.scrollTop : 0;
    stack.scroll.content = el.content ? el.content.scrollTop : 0;
    if (el.page) {
      el.page.classList.add("is-stack-locked");
    }
  }

  function restoreScroll() {
    if (!el.page) {
      return;
    }
    el.page.classList.remove("is-stack-locked");
    el.page.scrollTop = stack.scroll.page;
    if (el.main) {
      el.main.scrollTop = stack.scroll.main;
    }
    if (el.content) {
      el.content.scrollTop = stack.scroll.content;
    }
    /* 解锁的那一帧浏览器可能还在结算布局，下一帧再对齐一次，保证 ±2px 内 */
    window.requestAnimationFrame(function () {
      if (!el.page || stack.open) {
        return;
      }
      if (Math.abs(el.page.scrollTop - stack.scroll.page) > 2) {
        el.page.scrollTop = stack.scroll.page;
      }
      if (el.main && Math.abs(el.main.scrollTop - stack.scroll.main) > 2) {
        el.main.scrollTop = stack.scroll.main;
      }
    });
  }

  /* ======================================================================
   * 三、打开 / 关闭二级页
   * ====================================================================== */

  function setTitle(name) {
    stack.name = String(name || "");
    if (el.head) {
      var title = el.head.querySelector(".stack-title");
      if (title) {
        title.textContent = stack.name;
      }
    }
    if (el.more) {
      el.more.setAttribute("aria-label", "更多操作：" + stack.name);
    }
  }

  /* 全局跑马灯（#global-marquee，z-index 7000，手机端 24px）固定贴顶，
     正文靠 body.has-global-marquee .app{padding-top} 让位；二级页是 fixed 层，
     吃不到那段 padding，所以实测高度写进 CSS 变量，由栈头的 padding-top 补上。 */
  function syncTopExtra() {
    var bar = $("global-marquee");
    var extra = 0;
    if (bar && !bar.hasAttribute("hidden")) {
      var rect = bar.getBoundingClientRect();
      if (rect.height > 0 && getComputedStyle(bar).display !== "none") {
        extra = Math.round(rect.height);
      }
    }
    /* 写在 :root 上而不是 #page-assets 上：二级页栈头、以及挂在 body 层的
       全屏弹窗（#record-detail-modal 等）都要吃到这一段，写在页节点上弹窗继承不到。 */
    doc.documentElement.style.setProperty("--zhz-stack-top-extra", extra + "px");
  }

  function openStack(name, options) {
    var opts = options || {};
    if (!el.page || !el.panel || !isStackViewport()) {
      return;
    }
    /* 已经在栈里：只更新标题，绝不重复入栈（连点两次账户 history.length 只 +1） */
    if (stack.open) {
      if (name) {
        setTitle(name);
      }
      return;
    }
    if (!name) {
      return;
    }

    stack.open = true;
    stack.closing = false;
    setTitle(name);
    syncTopExtra();

    /* 切页动效会给 #page-assets 挂 transform / will-change，
       一旦它是变换元素，就会成为 position:fixed 的包含块，inset:0 不再等于视口。
       点得快的时候（切页 300ms 内点账户）必须清掉，否则全屏层会错位。 */
    el.page.classList.remove("is-entering");

    lockScroll();
    doc.body.classList.add("zhz-stack-open");

    /* 入场：先关掉过渡加类（此时仍是 translateX(0)，不会闪），
       再瞬时置到 100%，下一帧交回 CSS 过渡滑到 0。 */
    el.panel.style.transition = "none";
    el.page.classList.add("is-account-open");
    el.panel.style.transform = "translateX(100%)";
    void el.panel.offsetWidth;
    el.panel.style.transition = "";
    el.panel.style.transform = "";

    /* 入栈：只在真的打开时压一层，popstate 前进/后退还原时不再压 */
    if (!opts.fromPop && !stack.fromPop) {
      try {
        window.history.pushState(
          { zhz: HISTORY_STATE_VALUE, name: stack.name },
          "",
          window.location.href
        );
      } catch (error) {
        /* 极端情况下（file:// 或沙箱）pushState 可能失败：
           此时依然要保证返回按钮可用，退化为直接关闭。 */
      }
    }
    stack.fromPop = false;
  }

  function closeStack(options) {
    var opts = options || {};
    if (!stack.open) {
      return;
    }
    var after = stack.afterClose;
    stack.afterClose = null;
    stack.open = false;
    stack.closing = true;
    closeMenu();

    var duration = animDuration();
    el.panel.style.transition = "";
    el.panel.style.transform = "translateX(100%)";

    function finish() {
      window.clearTimeout(stack.closeTimer);
      window.clearTimeout(stack.fallbackTimer);
      stack.closeTimer = 0;
      stack.fallbackTimer = 0;
      if (!el.page || !el.panel) {
        return;
      }
      /* 动画结束后才切回 static：过渡期间必须保持 fixed，否则会瞬间跳回原位 */
      el.panel.style.transition = "none";
      el.page.classList.remove("is-account-open");
      el.panel.style.transform = "";
      void el.panel.offsetWidth;
      el.panel.style.transition = "";
      doc.body.classList.remove("zhz-stack-open");
      stack.closing = false;
      restoreScroll();
      if (typeof after === "function") {
        after();
      }
    }

    if (duration <= 0) {
      finish();
    } else {
      stack.closeTimer = window.setTimeout(finish, duration + 20);
    }

    if (opts.restoreFocus) {
      /* 回到列表时把焦点还给刚点过的账户行，键盘用户不会掉到 body 上 */
      window.setTimeout(function () {
        var row = doc.querySelector(
          '#account-groups .account-row[data-account="' + cssEscape(stack.name) + '"]'
        );
        if (row) {
          row.focus({ preventScroll: true });
        }
      }, duration + 40);
    }
  }

  /* 关闭的唯一入口：一律走 history.back()，
     真正的收尾由 popstate 触发 —— 系统返回键与页面返回键走完全相同的代码路径。 */
  function requestClose() {
    if (!stack.open || stack.closing) {
      return;
    }
    window.history.back();
    /* 兜底：pushState 失败或浏览器没派发 popstate 时，别让用户卡在全屏页里 */
    window.clearTimeout(stack.fallbackTimer);
    stack.fallbackTimer = window.setTimeout(function () {
      stack.fallbackTimer = 0;
      if (stack.open) {
        closeStack();
      }
    }, 600);
  }

  function cssEscape(value) {
    var text = String(value == null ? "" : value);
    if (window.CSS && typeof window.CSS.escape === "function") {
      return window.CSS.escape(text);
    }
    return text.replace(/["\\]/g, "\\$&");
  }

  /* ======================================================================
   * 四、「⋯」菜单
   * ====================================================================== */

  function openMenu() {
    if (!el.menu || !el.more) {
      return;
    }
    var rect = el.more.getBoundingClientRect();
    el.menu.style.top = Math.round(rect.bottom + 6) + "px";
    el.menu.style.right = Math.max(8, Math.round(window.innerWidth - rect.right)) + "px";
    el.menu.classList.add("is-open");
    el.more.setAttribute("aria-expanded", "true");
  }

  function closeMenu() {
    if (!el.menu) {
      return;
    }
    el.menu.classList.remove("is-open");
    if (el.more) {
      el.more.setAttribute("aria-expanded", "false");
    }
  }

  function menuIsOpen() {
    return !!(el.menu && el.menu.classList.contains("is-open"));
  }

  function runMenuAction(action) {
    var name = stack.name;
    closeMenu();
    if (!name) {
      return;
    }
    if (action === "balance") {
      /* 既有弹窗（Bootstrap Modal，z-index 1055），已自带表单校验与平账逻辑 */
      if (typeof window.openBalanceAdjustModal === "function") {
        window.openBalanceAdjustModal(name);
      }
      return;
    }
    if (action === "edit") {
      /* 行内编辑表单长在左栏的账户行上，必须先退出二级页再展开，
         否则用户会在隐藏的左栏里改东西。 */
      stack.afterClose = function () {
        if (typeof window.startAccountEdit === "function") {
          window.startAccountEdit(name);
        }
        window.setTimeout(function () {
          var row = doc.querySelector(
            '#account-groups .account-row[data-account="' + cssEscape(name) + '"]'
          );
          if (row) {
            if (typeof row.scrollIntoView === "function") {
              row.scrollIntoView({ block: "center", behavior: "smooth" });
            }
            var input = row.querySelector(".account-edit-name");
            if (input) {
              input.focus({ preventScroll: true });
            }
          }
        }, 60);
      };
      requestClose();
      return;
    }
    if (action === "delete") {
      /* 走既有的 removeAccount：它内部就是 confirmAction（不是 alert/confirm），
         并且带了「账户下还有账目时不允许删」的后果说明与并发锁。 */
      if (typeof window.removeAccount === "function") {
        window.removeAccount(name);
      }
    }
  }

  /* ======================================================================
   * 五、事件绑定
   * ====================================================================== */

  function bindEvents() {
    if (el.back) {
      el.back.addEventListener("click", function (event) {
        event.preventDefault();
        requestClose();
      });
    }

    if (el.more) {
      el.more.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        if (menuIsOpen()) {
          closeMenu();
        } else {
          openMenu();
        }
      });
    }

    if (el.menu) {
      el.menu.addEventListener("click", function (event) {
        var item = event.target.closest("[data-stack-act]");
        if (!item) {
          return;
        }
        event.preventDefault();
        runMenuAction(item.getAttribute("data-stack-act"));
      });
    }

    /* 点菜单外任意位置收起（capture，避免被其他委托处理器 stopPropagation 掉） */
    doc.addEventListener(
      "pointerdown",
      function (event) {
        if (!menuIsOpen()) {
          return;
        }
        if (el.menu && el.menu.contains(event.target)) {
          return;
        }
        if (el.more && el.more.contains(event.target)) {
          return;
        }
        closeMenu();
      },
      true
    );

    doc.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") {
        return;
      }
      if (menuIsOpen()) {
        closeMenu();
        return;
      }
      if (stack.open) {
        requestClose();
      }
    });

    /* 滚动时菜单会跟内容脱节，直接收起 */
    if (el.panel) {
      el.panel.addEventListener(
        "scroll",
        function () {
          if (menuIsOpen()) {
            closeMenu();
          }
        },
        { passive: true }
      );
    }

    window.addEventListener("resize", function () {
      if (menuIsOpen()) {
        closeMenu();
      }
      if (stack.open) {
        syncTopExtra();
      }
      /* 拉宽到桌面尺寸：全屏层没有意义了，退回列表页 */
      if (stack.open && !isStackViewport()) {
        requestClose();
      }
    });

    if (mq) {
      var onChange = function () {
        if (stack.open && !isStackViewport()) {
          requestClose();
        }
      };
      if (typeof mq.addEventListener === "function") {
        mq.addEventListener("change", onChange);
      } else if (typeof mq.addListener === "function") {
        mq.addListener(onChange);
      }
    }

    /* 返回栈：popstate 是整个模块的「返回」真相源 */
    window.addEventListener("popstate", function (event) {
      var state = event.state;
      /* 浏览器「前进」回到账户详情这一层：按页面栈语义重新打开 */
      if (state && state[HISTORY_STATE_KEY] === HISTORY_STATE_VALUE) {
        if (!stack.open && isStackViewport() && state.name) {
          stack.fromPop = true;
          openStack(state.name, { fromPop: true });
        }
        return;
      }
      if (stack.open) {
        closeStack();
      }
    });

    /* 左滑返回：只在屏幕左缘起手、且水平位移明显大于垂直位移时才触发 */
    var swipe = null;
    if (el.panel) {
      el.panel.addEventListener(
        "pointerdown",
        function (event) {
          if (!stack.open || event.pointerType === "mouse") {
            return;
          }
          if (event.clientX > 32) {
            return;
          }
          swipe = { x: event.clientX, y: event.clientY };
        },
        { passive: true }
      );

      el.panel.addEventListener(
        "pointerup",
        function (event) {
          if (!swipe) {
            return;
          }
          var dx = event.clientX - swipe.x;
          var dy = Math.abs(event.clientY - swipe.y);
          swipe = null;
          if (dx > 72 && dy < 60 && dx > dy * 1.4) {
            requestClose();
          }
        },
        { passive: true }
      );

      el.panel.addEventListener("pointercancel", function () {
        swipe = null;
      });
    }
  }

  /* ======================================================================
   * 六、包装 selectAccount：只在「窄屏 + 用户真的点了账户行」时入栈
   *
   * 为什么要判断是不是用户点的行：
   *   程序化调用（新增账户后自动选中、删除后刷新等）不应该把用户强行推进二级页。
   * ====================================================================== */

  function wrapSelectAccount() {
    if (typeof window.selectAccount !== "function" || window.selectAccount.__zhzStackWrapped) {
      return;
    }
    var original = window.selectAccount;

    var wrapped = function (name) {
      var result = original.apply(this, arguments);
      if (isStackViewport() && name) {
        if (stack.open || tapIsFresh()) {
          openStack(String(name));
        }
      }
      return result;
    };
    wrapped.__zhzStackWrapped = true;
    window.selectAccount = wrapped;
  }

  /* ======================================================================
   * 七、初始化
   * ====================================================================== */

  function init() {
    if (stack.ready) {
      return;
    }
    el.page = $("page-assets");
    if (!el.page) {
      return;
    }
    el.panel = el.page.querySelector(".assets-right");
    el.left = el.page.querySelector(".assets-left");
    el.main = doc.querySelector(".main");
    el.content = doc.querySelector(".content");

    if (el.panel) {
      el.head = buildStackHead();
      el.panel.insertBefore(el.head, el.panel.firstChild);
      el.back = el.head.querySelector(".stack-back");
      el.more = el.head.querySelector(".stack-more");
    }

    el.menu = buildMenu();
    doc.body.appendChild(el.menu);

    /* 记录「这次点击来自账户行」：script.js 的行点击是 click 事件，
       pointerdown 一定先于它发生，用 900ms 的窗口判定足够宽松。 */
    doc.addEventListener(
      "pointerdown",
      function (event) {
        var row = event.target.closest
          ? event.target.closest("#account-groups .account-row")
          : null;
        if (row) {
          markTap();
        }
      },
      true
    );

    /* 键盘用户：账户行 Enter / Space 触发 click 时不经过 pointerdown */
    doc.addEventListener(
      "keydown",
      function (event) {
        if (event.key !== "Enter" && event.key !== " " && event.key !== "Spacebar") {
          return;
        }
        var row = event.target.closest
          ? event.target.closest("#account-groups .account-row")
          : null;
        if (row) {
          markTap();
        }
      },
      true
    );

    bindEvents();
    wrapSelectAccount();
    syncTopExtra();
    stack.ready = true;
  }

  if (doc.readyState === "loading") {
    doc.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  /* 登录后 script.js 会重建界面，若包装被覆盖则补一次（幂等） */
  window.addEventListener("load", function () {
    if (!stack.ready) {
      init();
    } else {
      wrapSelectAccount();
    }
  });

  /* 供验收脚本与后续模块复用（只读 + 单一入口，不对外暴露内部状态） */
  window.__zhzMobileStack = {
    isOpen: function () {
      return stack.open;
    },
    open: function (name) {
      openStack(name);
    },
    close: function () {
      requestClose();
    },
    isMobileStackViewport: isStackViewport,
    /* 只给验收脚本读的诊断信息，业务代码不要依赖 */
    _state: function () {
      return {
        ready: stack.ready,
        open: stack.open,
        closing: stack.closing,
        name: stack.name,
        fromPop: stack.fromPop,
        tapAge: stack.lastRowTap ? Date.now() - stack.lastRowTap : -1
      };
    }
  };
})();
