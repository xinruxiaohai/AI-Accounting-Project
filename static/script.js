"use strict";

/*
 * AI记账管家 · 前端逻辑（v0.06）
 *
 * 这一版在 v0.05 的基础上加了四件事：
 *   1. 金额框支持算式（math.js 本地计算，保存时 amount 存结果、formula 存原式）
 *   2. 记账弹窗支持「转账」：隐藏分类，显示转入账户与手续费
 *   3. 所有 alert() 换成页面顶部的 Toast 轻提示
 *   4. 资产页「在此账户下记一笔」只预选账户，不再把账户锁死
 */

/* ==================== 常量 ==================== */

const PAGE_TITLES = {
  home: "首页",
  calendar: "日历",
  assets: "资产",
  profile: "我的",
};

const TYPE_LABELS = {
  expense: "支出",
  income: "收入",
  transfer: "转账",
};

const TYPE_BADGES = {
  expense: '<span class="badge bg-danger">支出</span>',
  income: '<span class="badge bg-success">收入</span>',
  transfer: '<span class="badge bg-info text-dark">转账</span>',
};

/* ==================== 小工具 ==================== */

function $(id) {
  return document.getElementById(id);
}

function cents(value) {
  // 统一四舍五入到分，避免 78.19999999999999 这种浮点尾巴跑到界面上
  return Math.round(Number(value || 0) * 100) / 100;
}

function money(value) {
  const number = cents(value);
  const sign = number < 0 ? "-" : "";
  return sign + "¥" + Math.abs(number).toFixed(2);
}

function escapeHtml(text) {
  return String(text === null || text === undefined ? "" : text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function displayDate(value) {
  // 后端已经统一成「YYYY-MM-DD HH:MM」，这里只兜底
  const text = String(value || "").trim();
  if (text.length === 10) {
    return text + " 00:00";
  }
  return text.slice(0, 16);
}

function toInputValue(value) {
  // datetime-local 需要「YYYY-MM-DDTHH:MM」
  return displayDate(value).replace(" ", "T");
}

function nowInputValue() {
  const now = new Date();
  const pad = (number) => String(number).padStart(2, "0");
  return (
    now.getFullYear() +
    "-" +
    pad(now.getMonth() + 1) +
    "-" +
    pad(now.getDate()) +
    "T" +
    pad(now.getHours()) +
    ":" +
    pad(now.getMinutes())
  );
}

function todayText() {
  return nowInputValue().slice(0, 10);
}

/* ==================== Toast 轻提示 ==================== */

function toast(message, type) {
  const stack = $("toast-stack");
  if (!stack) {
    return;
  }
  const item = document.createElement("div");
  item.className = "toast-item " + (type === "error" ? "toast-error" : "toast-success");
  item.textContent = String(message || "");
  stack.appendChild(item);

  // 先插进 DOM 再加 show，才有从上面滑下来的动画
  requestAnimationFrame(function () {
    item.classList.add("show");
  });

  setTimeout(function () {
    item.classList.remove("show");
    setTimeout(function () {
      if (item.parentNode) {
        item.parentNode.removeChild(item);
      }
    }, 260);
  }, 2400);
}

/* ==================== 表单防呆：字段错误提示 ==================== */

/** 必填标记，和 style.css 的 .req 配套 */
const REQ_MARK = '<span class="req">*</span>';

/** 找到字段所属的表单块，错误文案挂在它下面 */
function fieldHolder(field) {
  if (!field) {
    return null;
  }
  return (
    field.closest(".col-6, .col-12, .mb-3, .category-add-wrap, .category-add, .panel-tools") ||
    field.parentNode
  );
}

function setFieldError(field, message) {
  if (!field) {
    return;
  }
  const holder = fieldHolder(field);
  field.classList.add("is-invalid");
  field.setAttribute("aria-invalid", "true");

  let tip = holder.querySelector('.field-error[data-for="' + field.id + '"]');
  if (!tip) {
    tip = document.createElement("div");
    tip.className = "field-error";
    tip.setAttribute("data-for", field.id);
    holder.appendChild(tip);
  }
  tip.textContent = message;
}

function clearFieldError(field) {
  if (!field) {
    return;
  }
  field.classList.remove("is-invalid");
  field.removeAttribute("aria-invalid");
  const holder = fieldHolder(field);
  if (!holder) {
    return;
  }
  const tip = holder.querySelector('.field-error[data-for="' + field.id + '"]');
  if (tip) {
    tip.remove();
  }
}

function clearFormErrors(scope) {
  if (!scope) {
    return;
  }
  scope.querySelectorAll(".is-invalid").forEach(function (element) {
    element.classList.remove("is-invalid");
    element.removeAttribute("aria-invalid");
  });
  scope.querySelectorAll(".field-error").forEach(function (element) {
    element.remove();
  });
}

/**
 * 统一处理校验结果：先清掉旧红框，再把每条问题标到对应字段，
 * 用 Toast 说第一条并聚焦第一个出错的框。
 * 返回 true 表示「有错，已拦截」。
 */
function reportIssues(scope, issues) {
  clearFormErrors(scope);
  if (!issues.length) {
    return false;
  }

  issues.forEach(function (issue) {
    setFieldError(issue.field, issue.message);
  });

  const first = issues[0];
  const extra = issues.length > 1 ? "（另有 " + (issues.length - 1) + " 项待完善）" : "";
  toast(first.message + extra, "error");
  if (first.field && typeof first.field.focus === "function") {
    first.field.focus();
  }
  return true;
}

/* ==================== 表单防呆：并发锁 + 按钮 Loading ==================== */

// 正在进行的动作：同一个 key 重复触发直接忽略，防止狂点重复提交
const pendingActions = new Set();

function lockAction(key) {
  if (pendingActions.has(key)) {
    return false;
  }
  pendingActions.add(key);
  return true;
}

function unlockAction(key) {
  pendingActions.delete(key);
}

/**
 * 按钮里的转圈：不禁用按钮（Bootstrap 的 disabled 样式会发灰），
 * 只把内容换成 Spinner + 文案；真正的防重复交给 lockAction()。
 */
function setButtonBusy(button, busy, busyText) {
  if (!button) {
    return;
  }

  if (busy) {
    if (button.dataset.idleHtml === undefined) {
      button.dataset.idleHtml = button.innerHTML;
    }
    button.classList.add("is-busy");
    button.setAttribute("aria-busy", "true");
    button.innerHTML =
      '<span class="btn-spinner" aria-hidden="true"></span><span>' +
      escapeHtml(busyText || "保存中…") +
      "</span>";
    return;
  }

  button.classList.remove("is-busy");
  button.removeAttribute("aria-busy");
  if (button.dataset.idleHtml !== undefined) {
    button.innerHTML = button.dataset.idleHtml;
    delete button.dataset.idleHtml;
  }
}

/* ==================== 表格骨架屏 / 空状态 ==================== */

const SKELETON_WIDTHS = [38, 26, 52, 34, 44, 62, 30];

function emptyStateInner(hint) {
  return (
    '<div class="empty-state">' +
    '<svg class="empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M3.5 7.5 12 3l8.5 4.5v9L12 21l-8.5-4.5z"></path>' +
    '<path d="M3.5 7.5 12 12l8.5-4.5M12 12v9"></path>' +
    "</svg>" +
    '<div class="empty-title">暂无数据</div>' +
    (hint ? '<div class="empty-text">' + escapeHtml(hint) + "</div>" : "") +
    "</div>"
  );
}

/** 表格里的空数据行：图标 + 暂无数据 + 一句引导 */
function emptyStateHtml(colspan, hint) {
  return (
    '<tr><td colspan="' + colspan + '" class="empty-cell">' + emptyStateInner(hint) + "</td></tr>"
  );
}

/** 非表格区域（账户卡片）的空数据块 */
function emptyBlockHtml(hint) {
  return '<div class="empty-block">' + emptyStateInner(hint) + "</div>";
}

function skeletonRowsHtml(colspan, rows) {
  let html = "";
  for (let r = 0; r < rows; r += 1) {
    let cells = "";
    for (let c = 0; c < colspan; c += 1) {
      cells +=
        '<td><span class="sk-line" style="width:' +
        SKELETON_WIDTHS[c % SKELETON_WIDTHS.length] +
        '%"></span></td>';
    }
    html += '<tr class="skeleton-row">' + cells + "</tr>";
  }
  return html;
}

/**
 * 表格加载骨架：延迟 120ms 才插入，本地接口很快时不会闪一下。
 * 返回的收尾函数：请求出错没来得及渲染时，把骨架换成失败提示，避免永远转圈。
 */
function beginTableLoad(tbody, colspan, rows) {
  if (!tbody) {
    return function () {};
  }
  const timer = setTimeout(function () {
    tbody.innerHTML = skeletonRowsHtml(colspan, rows || 5);
    tbody.setAttribute("aria-busy", "true");
  }, 120);

  return function () {
    clearTimeout(timer);
    tbody.removeAttribute("aria-busy");
    if (tbody.querySelector(".skeleton-row")) {
      tbody.innerHTML = emptyStateHtml(colspan, "数据加载失败，请稍后重试");
    }
  };
}

function groupsSkeletonHtml() {
  let cards = "";
  for (let i = 0; i < 4; i += 1) {
    cards +=
      '<div class="account-card is-skeleton">' +
      '<span class="sk-line" style="width:55%"></span>' +
      '<span class="sk-line sk-line-lg" style="width:80%"></span>' +
      "</div>";
  }
  return (
    '<div class="account-group">' +
    '<div class="account-group-head"><span class="sk-line" style="width:80px"></span></div>' +
    '<div class="account-cards">' +
    cards +
    "</div></div>"
  );
}

/** 账户卡片区的骨架屏，收尾逻辑和表格一致 */
function beginGroupsLoad(box) {
  if (!box) {
    return function () {};
  }
  const timer = setTimeout(function () {
    box.innerHTML = groupsSkeletonHtml();
    box.setAttribute("aria-busy", "true");
  }, 120);

  return function () {
    clearTimeout(timer);
    box.removeAttribute("aria-busy");
    if (box.querySelector(".is-skeleton")) {
      box.innerHTML = emptyBlockHtml("账户加载失败，请刷新重试");
    }
  };
}

/* ==================== 快捷键：弹窗内 Enter 提交 ==================== */
/* Esc 关闭由 Bootstrap 的 data-bs-keyboard 负责，这里只补「回车提交」 */

function bindEnterSubmit(modalElement, handler) {
  if (!modalElement) {
    return;
  }
  modalElement.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" || event.isComposing || event.keyCode === 229) {
      return;
    }
    const target = event.target;
    if (!target) {
      return;
    }
    const tag = String(target.tagName || "").toLowerCase();
    // 下拉框回车是选选项、textarea 回车要换行、按钮回车是它自己的事
    if (tag === "select" || tag === "textarea" || tag === "button" || tag === "a") {
      return;
    }
    event.preventDefault();
    handler();
  });
}

/** 输入 / 切换选项时，把这个字段的红框清掉 */
function bindErrorClearing(scope) {
  if (!scope) {
    return;
  }
  scope.querySelectorAll(".form-control, .form-select").forEach(function (field) {
    field.addEventListener("input", function () {
      clearFieldError(field);
    });
    field.addEventListener("change", function () {
      clearFieldError(field);
    });
  });
}

/**
 * Esc 关闭弹窗。
 * Bootstrap 只在自己身上监听 keydown，焦点还在「+ 记一笔」按钮上时收不到；
 * 这里在 document 上兜一层，保证弹窗开着时按 Esc 一定关。
 */
function bindEscClose(modalElement, instance) {
  if (!modalElement || !instance) {
    return;
  }
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape" || event.isComposing) {
      return;
    }
    if (!modalElement.classList.contains("show")) {
      return;
    }
    event.preventDefault();
    instance.hide();
  });
}

/* ==================== 请求封装 ==================== */

async function api(path, options) {
  const response = await fetch(path, options);
  let data = null;
  try {
    data = await response.json();
  } catch (error) {
    data = null;
  }
  if (!response.ok) {
    const message = (data && data.error) || "请求失败（HTTP " + response.status + "）";
    throw new Error(message);
  }
  return data;
}

function jsonOptions(method, body) {
  return {
    method: method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

/* ==================== 全局状态 ==================== */

const state = {
  categories: [],
  accountGroups: [],
  accounts: [],
  allRecords: [],
  detailAccount: "",
  detailRecords: [],
  editingId: null,
  presetAccount: "",
  // 日历：模式、当前年月、选中的某一天、日历专用的全量账单（不受账户筛选影响）
  calMode: "month",
  calYear: new Date().getFullYear(),
  calMonth: new Date().getMonth(),
  calSelectedDate: "",
  calendarRecords: [],
};

let recordModal = null;
let accountModal = null;
let categoryModal = null;

/* ==================== 金额 / 公式 ==================== */

function looksLikeFormula(text) {
  return /[+\-*/()%^]/.test(text);
}

/**
 * 把金额框里的文字变成数字。
 * - 纯数字：直接用 Number，不经过 math.js（省得把 0.1+0.2 的浮点尾巴带进来）
 * - 算式：交给 math.js 算，算不出来就报错，绝不 eval
 */
function amountFromInput(raw) {
  const text = String(raw === null || raw === undefined ? "" : raw).trim();
  if (!text) {
    return { ok: false, message: "请填写金额" };
  }

  if (/^\d+(\.\d+)?$/.test(text)) {
    const value = Number(text);
    if (!Number.isFinite(value)) {
      return { ok: false, message: "金额不是合法数字" };
    }
    if (value <= 0) {
      return { ok: false, message: "金额必须大于 0" };
    }
    return { ok: true, value: cents(value), formula: "" };
  }

  if (!window.math) {
    return { ok: false, message: "计算库没加载成功，请刷新页面再试" };
  }

  let result = null;
  try {
    result = window.math.evaluate(text);
  } catch (error) {
    return { ok: false, message: "公式不完整，请把算式写完整" };
  }

  if (typeof result !== "number" || !Number.isFinite(result)) {
    return { ok: false, message: "公式算不出有效数字，请检查算式" };
  }
  if (result <= 0) {
    return { ok: false, message: "公式结果必须大于 0" };
  }
  return { ok: true, value: cents(result), formula: text };
}

function updateAmountHint() {
  const hint = $("amount-hint");
  if (!hint) {
    return;
  }
  const text = String($("amount").value || "").trim();

  // 空、纯数字、不带运算符：都不用打扰用户
  if (!text || !looksLikeFormula(text)) {
    hint.textContent = "";
    return;
  }

  // 边输边算：只有真的算出一个有效数字才显示「= ¥55.50」
  // 算不出来（25+ 这种还没输完、括号没闭合、写错了）就保持安静，
  // 真正的拦截放在 saveRecord() 里，用 Toast 提示。
  const value = evaluateQuietly(text);
  if (value === null) {
    hint.textContent = "";
    return;
  }
  hint.textContent = "= " + money(value);
}

/**
 * 静默求值：算不出来、结果不是数字、结果 <= 0 都返回 null，不产生任何提示。
 */
function evaluateQuietly(text) {
  if (!window.math) {
    return null;
  }
  let result = null;
  try {
    result = window.math.evaluate(text);
  } catch (error) {
    return null;
  }
  if (typeof result !== "number" || !Number.isFinite(result) || result <= 0) {
    return null;
  }
  return cents(result);
}

/* ==================== 类型（支出 / 收入 / 转账） ==================== */

function currentType() {
  const checked = document.querySelector('input[name="record-type"]:checked');
  return checked ? checked.value : "expense";
}

function setType(type) {
  const target = $("type-" + (type || "expense"));
  if (target) {
    target.checked = true;
  }
  applyTypeUi();
}

function isTransferType() {
  return currentType() === "transfer";
}

function applyTypeUi() {
  const transfer = isTransferType();

  // 转账没有分类概念：收支分类整块藏起来，换成转入账户和手续费
  $("category-col").classList.toggle("d-none", transfer);
  $("to-account-wrap").classList.toggle("d-none", !transfer);
  $("fee-wrap").classList.toggle("d-none", !transfer);
  $("account-label").innerHTML = (transfer ? "转出账户" : "账户") + REQ_MARK;

  // 切类型时把被藏起来那一组的红框清掉，免得下次显示还挂着旧错误
  if (transfer) {
    clearFieldError($("category"));
  } else {
    clearFieldError($("to-account"));
    clearFieldError($("fee"));
  }

  updateSubCategoryVisibility();
}

/* ==================== 分类 ==================== */

function findCategory(categoryId) {
  const id = Number(categoryId);
  for (let i = 0; i < state.categories.length; i += 1) {
    const top = state.categories[i];
    if (Number(top.id) === id) {
      return { node: top, parent: null };
    }
    for (let j = 0; j < top.children.length; j += 1) {
      if (Number(top.children[j].id) === id) {
        return { node: top.children[j], parent: top };
      }
    }
  }
  return null;
}

function childrenOf(parentId) {
  const id = Number(parentId);
  for (let i = 0; i < state.categories.length; i += 1) {
    if (Number(state.categories[i].id) === id) {
      return state.categories[i].children;
    }
  }
  return [];
}

function fillCategoryParent(selectedId) {
  const select = $("category");
  select.innerHTML = "";

  state.categories.forEach(function (top) {
    const option = document.createElement("option");
    option.value = String(top.id);
    option.textContent = top.name;
    select.appendChild(option);
  });

  if (selectedId !== undefined && selectedId !== null) {
    select.value = String(selectedId);
  }
}

function fillCategoryChild(parentId, selectedChildId) {
  const select = $("sub-category");
  const wrap = $("sub-category-wrap");
  select.innerHTML = "";

  const children = childrenOf(parentId);
  if (!children.length) {
    wrap.classList.add("d-none");
    updateSubCategoryVisibility();
    return;
  }

  // 空值表示「就记在一级分类上」，不一定非要选二级
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "不细分（记在 " + categoryNameOf(parentId) + "）";
  select.appendChild(placeholder);

  children.forEach(function (child) {
    const option = document.createElement("option");
    option.value = String(child.id);
    option.textContent = child.name;
    select.appendChild(option);
  });

  if (selectedChildId !== undefined && selectedChildId !== null && selectedChildId !== "") {
    select.value = String(selectedChildId);
  }

  updateSubCategoryVisibility();
}

function categoryNameOf(categoryId) {
  const found = findCategory(categoryId);
  return found ? found.node.name : "";
}

function updateSubCategoryVisibility() {
  const wrap = $("sub-category-wrap");
  const select = $("sub-category");
  const hasChildren = select.options.length > 0;
  wrap.classList.toggle("d-none", isTransferType() || !hasChildren);
}

function selectedCategoryId() {
  if (isTransferType()) {
    return null;
  }
  const child = $("sub-category");
  const wrap = $("sub-category-wrap");
  if (child && !wrap.classList.contains("d-none") && child.value) {
    return Number(child.value);
  }
  const parent = $("category");
  return parent && parent.value ? Number(parent.value) : null;
}

function categoryLabel(record) {
  if (record.type === "transfer") {
    return escapeHtml(record.account) + " → " + escapeHtml(record.to_account);
  }
  const name = escapeHtml(record.category || "");
  if (record.category_parent) {
    return escapeHtml(record.category_parent) + " / " + name;
  }
  return name;
}

function countRecordsByCategory() {
  const counts = {};
  state.allRecords.forEach(function (record) {
    if (record.category_id === null || record.category_id === undefined) {
      return;
    }
    const key = String(record.category_id);
    counts[key] = (counts[key] || 0) + 1;
  });
  return counts;
}

async function loadCategories() {
  const data = await api("/api/categories");
  state.categories = data.categories || [];

  fillCategoryParent($("category").value ? Number($("category").value) : null);
  fillCategoryChild($("category").value, $("sub-category").value);

  // 分类管理弹窗里的「父级」下拉
  const parentSelect = $("new-category-parent");
  const keep = parentSelect.value;
  parentSelect.innerHTML = '<option value="">作为一级分类</option>';
  state.categories.forEach(function (top) {
    const option = document.createElement("option");
    option.value = String(top.id);
    option.textContent = top.name;
    parentSelect.appendChild(option);
  });
  parentSelect.value = keep;

  renderCategoryTree();
}

function renderCategoryTree() {
  const list = $("category-tree");
  const counts = countRecordsByCategory();
  list.innerHTML = "";

  state.categories.forEach(function (top) {
    const item = document.createElement("li");
    item.innerHTML =
      categoryRowHtml(top, counts, true) +
      (top.children.length
        ? '<ul class="category-sub">' +
          top.children
            .map(function (child) {
              return "<li>" + categoryRowHtml(child, counts, false) + "</li>";
            })
            .join("") +
          "</ul>"
        : "");
    list.appendChild(item);
  });

  if (!state.categories.length) {
    list.innerHTML = '<li class="empty-cell">还没有分类</li>';
  }
}

function categoryRowHtml(category, counts, isTop) {
  const used = counts[String(category.id)] || 0;
  const tag = used ? '<span class="tag-count">' + used + " 笔</span>" : "";
  return (
    '<div class="category-row">' +
    '<span class="category-name">' +
    escapeHtml(category.name) +
    "</span>" +
    (isTop ? "" : '<span class="category-tip">二级</span>') +
    tag +
    '<button class="cat-del" type="button" data-del-category="' +
    category.id +
    '">删除</button>' +
    "</div>"
  );
}

/* ==================== 账户 ==================== */

function accountOptionsHtml(selectedName) {
  // 按大类用 <optgroup> 分组，避免 8 个账户平铺在一起看花眼
  return state.accountGroups
    .map(function (group) {
      const inner = group.accounts
        .map(function (account) {
          const selected = account.name === selectedName ? " selected" : "";
          return (
            '<option value="' +
            escapeHtml(account.name) +
            '"' +
            selected +
            ">" +
            escapeHtml(account.name) +
            "（" +
            money(account.balance) +
            "）</option>"
          );
        })
        .join("");
      if (!inner) {
        return "";
      }
      return '<optgroup label="' + escapeHtml(group.name) + '">' + inner + "</optgroup>";
    })
    .join("");
}

function fillAccountSelects() {
  const accountSelect = $("account");
  const keepAccount = accountSelect.value;
  accountSelect.innerHTML = accountOptionsHtml(keepAccount);

  // 筛选框多一个「全部账户」，并且不显示余额，免得下拉太宽
  const filter = $("filter-account");
  const keepFilter = filter.value;
  const plainOptions = state.accountGroups
    .map(function (group) {
      const inner = group.accounts
        .map(function (account) {
          return '<option value="' + escapeHtml(account.name) + '">' + escapeHtml(account.name) + "</option>";
        })
        .join("");
      if (!inner) {
        return "";
      }
      return '<optgroup label="' + escapeHtml(group.name) + '">' + inner + "</optgroup>";
    })
    .join("");
  filter.innerHTML = '<option value="">全部账户</option>' + plainOptions;
  filter.value = keepFilter;

  // 转入账户：全量账户，默认挑一个和转出账户不同的
  const toAccount = $("to-account");
  const keepTo = toAccount.value;
  toAccount.innerHTML = accountOptionsHtml(keepTo);
  if (!toAccount.value && state.accounts.length) {
    const firstOther = state.accounts.find(function (account) {
      return account.name !== accountSelect.value;
    });
    if (firstOther) {
      toAccount.value = firstOther.name;
    }
  }
}

function renderAccountGroups() {
  const box = $("account-groups");
  if (!state.accounts.length) {
    box.innerHTML = emptyBlockHtml("还没有账户，点右上角「+ 新增账户」建一个");
    return;
  }

  box.innerHTML = state.accountGroups
    .map(function (group) {
      const total = group.accounts.reduce(function (sum, account) {
        return sum + Number(account.balance || 0);
      }, 0);

      const cards = group.accounts
        .map(function (account) {
          const active = account.name === state.detailAccount ? " active" : "";
          const tone = Number(account.balance) < 0 ? " is-negative" : "";
          return (
            '<div class="account-card' +
            active +
            '" data-account="' +
            escapeHtml(account.name) +
            '">' +
            '<button class="account-card-del" type="button" data-del-account="' +
            escapeHtml(account.name) +
            '" title="删除账户">×</button>' +
            '<div class="account-card-name">' +
            escapeHtml(account.name) +
            "</div>" +
            '<div class="account-card-balance' +
            tone +
            '">' +
            money(account.balance) +
            "</div>" +
            "</div>"
          );
        })
        .join("");

      return (
        '<div class="account-group">' +
        '<div class="account-group-head">' +
        '<span class="account-group-name">' +
        escapeHtml(group.name) +
        "</span>" +
        '<span class="account-group-total">合计 ' +
        money(total) +
        "</span>" +
        "</div>" +
        '<div class="account-cards">' +
        cards +
        "</div>" +
        "</div>"
      );
    })
    .join("");
}

async function loadAccounts() {
  const finish = beginGroupsLoad($("account-groups"));
  try {
    const data = await api("/api/accounts");
    state.accounts = data.accounts || [];
    state.accountGroups = data.groups || [];

    fillAccountSelects();
    renderAccountGroups();

    // 选中的账户被删掉了，详情区要退回未选中状态
    if (state.detailAccount) {
      const stillThere = state.accounts.some(function (account) {
        return account.name === state.detailAccount;
      });
      if (!stillThere) {
        clearDetail();
      }
    }
  } finally {
    finish();
  }
}

function clearDetail() {
  state.detailAccount = "";
  state.detailRecords = [];
  $("detail-title").textContent = "账户流水";
  $("quick-add-btn").disabled = true;
  $("account-records").innerHTML = emptyStateHtml(6, "先在上方点一个账户，这里会显示它的流水");
}

async function selectAccount(name) {
  state.detailAccount = name;
  $("detail-title").textContent = name + " · 流水";
  $("quick-add-btn").disabled = false;
  renderAccountGroups();

  const finish = beginTableLoad($("account-records"), 6);
  try {
    const data = await api("/api/records?account=" + encodeURIComponent(name));
    state.detailRecords = data.records || [];
    renderAccountRecords();
  } finally {
    finish();
  }
}

/* ==================== 统计卡片 ==================== */

async function loadStatistics() {
  const data = await api("/api/statistics");
  $("stat-income").textContent = money(data.income_total);
  $("stat-expense").textContent = money(data.expense_total);

  const balance = $("stat-balance");
  balance.textContent = money(data.balance_total);
  // 余额是负的就说人话：红色提醒，别装作没事
  balance.className = Number(data.balance_total) < 0 ? "stat-number text-danger" : "stat-number text-primary";
}

/* ==================== 账单列表 ==================== */

function amountCellHtml(record) {
  if (record.type === "income") {
    return '<span class="text-success">+' + money(record.amount) + "</span>";
  }
  if (record.type === "transfer") {
    const fee = Number(record.fee || 0);
    const feeTip = fee > 0 ? '<div class="fee-note">含手续费 ' + money(fee) + "</div>" : "";
    return '<span class="text-danger">-' + money(record.amount) + "</span>" + feeTip;
  }
  return '<span class="text-danger">-' + money(record.amount) + "</span>";
}

function actionCellHtml(record) {
  return (
    '<button class="btn btn-sm btn-warning" type="button" data-action="edit" data-id="' +
    record.id +
    '">编辑</button>' +
    '<button class="btn btn-sm btn-danger ms-1" type="button" data-action="delete" data-id="' +
    record.id +
    '">删除</button>'
  );
}

function renderRecords() {
  const tbody = $("record-list");
  tbody.innerHTML = "";

  if (!state.allRecords.length) {
    tbody.innerHTML = emptyStateHtml(7, "还没有记录，点右上角「+ 记一笔」开始吧");
    return;
  }

  state.allRecords.forEach(function (record) {
    const row = document.createElement("tr");
    row.setAttribute("data-id", String(record.id));
    row.innerHTML =
      '<td class="col-time">' +
      escapeHtml(displayDate(record.date)) +
      "</td>" +
      '<td class="col-type">' +
      (TYPE_BADGES[record.type] || TYPE_BADGES.expense) +
      "</td>" +
      "<td>" +
      categoryLabel(record) +
      "</td>" +
      "<td>" +
      escapeHtml(record.account) +
      "</td>" +
      '<td class="text-end col-amount">' +
      amountCellHtml(record) +
      "</td>" +
      '<td class="note-cell">' +
      (record.note ? escapeHtml(record.note) : "-") +
      "</td>" +
      '<td class="text-end col-action">' +
      actionCellHtml(record) +
      "</td>";
    tbody.appendChild(row);
  });
}

function renderAccountRecords() {
  const tbody = $("account-records");
  tbody.innerHTML = "";

  if (!state.detailRecords.length) {
    tbody.innerHTML = emptyStateHtml(6, "这个账户还没有流水");
    return;
  }

  state.detailRecords.forEach(function (record) {
    const row = document.createElement("tr");
    row.setAttribute("data-id", String(record.id));
    row.innerHTML =
      '<td class="col-time">' +
      escapeHtml(displayDate(record.date)) +
      "</td>" +
      '<td class="col-type">' +
      (TYPE_BADGES[record.type] || TYPE_BADGES.expense) +
      "</td>" +
      "<td>" +
      categoryLabel(record) +
      "</td>" +
      '<td class="text-end col-amount">' +
      amountCellHtml(record) +
      "</td>" +
      '<td class="note-cell">' +
      (record.note ? escapeHtml(record.note) : "-") +
      "</td>" +
      '<td class="text-end col-action">' +
      actionCellHtml(record) +
      "</td>";
    tbody.appendChild(row);
  });
}

async function loadRecords() {
  const finish = beginTableLoad($("record-list"), 7);
  try {
    const account = $("filter-account").value;
    const query = account ? "?account=" + encodeURIComponent(account) : "";
    const data = await api("/api/records" + query);
    state.allRecords = data.records || [];

    renderRecords();
    renderCategoryTree();
  } finally {
    finish();
  }
}

async function refreshDetail() {
  if (!state.detailAccount) {
    return;
  }
  const finish = beginTableLoad($("account-records"), 6);
  try {
    const data = await api("/api/records?account=" + encodeURIComponent(state.detailAccount));
    state.detailRecords = data.records || [];
    renderAccountRecords();
  } finally {
    finish();
  }
}

/* ==================== 日历 ==================== */

/* ==================== 日历 ==================== */

function pad2(value) {
  return String(value).padStart(2, "0");
}

/** 账单归属的日期，统一成 YYYY-MM-DD */
function dateKeyOf(record) {
  return displayDate(record.date).slice(0, 10);
}

function monthPrefix(year, month) {
  return year + "-" + pad2(month + 1) + "-";
}

/** 一组账单的收入 / 支出 / 结余（转账不算收入也不算支出） */
function summarize(records) {
  let income = 0;
  let expense = 0;
  let transfer = 0;
  records.forEach(function (record) {
    const amount = Number(record.amount || 0);
    if (record.type === "income") {
      income += amount;
    } else if (record.type === "expense") {
      expense += amount;
    } else {
      transfer += amount;
    }
  });
  return {
    income: cents(income),
    expense: cents(expense),
    net: cents(income - expense),
    transfer: cents(transfer),
    count: records.length,
  };
}

function recordsOfMonth(year, month) {
  const prefix = monthPrefix(year, month);
  return state.calendarRecords.filter(function (record) {
    return dateKeyOf(record).indexOf(prefix) === 0;
  });
}

function recordsOfYear(year) {
  const prefix = year + "-";
  return state.calendarRecords.filter(function (record) {
    return dateKeyOf(record).indexOf(prefix) === 0;
  });
}

function recordsOfDay(key) {
  return state.calendarRecords.filter(function (record) {
    return dateKeyOf(record) === key;
  });
}

/** 按天汇总，给格子染色用 */
function dailySummaries(records) {
  const map = {};
  records.forEach(function (record) {
    const key = dateKeyOf(record);
    if (!map[key]) {
      map[key] = { income: 0, expense: 0 };
    }
    const amount = Number(record.amount || 0);
    if (record.type === "income") {
      map[key].income += amount;
    } else if (record.type === "expense") {
      map[key].expense += amount;
    }
  });
  Object.keys(map).forEach(function (key) {
    const item = map[key];
    item.income = cents(item.income);
    item.expense = cents(item.expense);
    item.net = cents(item.income - item.expense);
  });
  return map;
}

/** 顶部三张卡：收入 / 支出 / 结余 */
function renderCalendarStats(label, records) {
  const summary = summarize(records);
  $("cal-range-label").textContent = label;
  $("cal-stat-income").textContent = money(summary.income);
  $("cal-stat-expense").textContent = money(summary.expense);

  const net = $("cal-stat-net");
  net.textContent = money(summary.net);
  net.classList.remove("text-primary", "text-success", "text-danger");
  if (summary.net > 0) {
    net.classList.add("text-success");
  } else if (summary.net < 0) {
    net.classList.add("text-danger");
  } else {
    net.classList.add("text-primary");
  }
  return summary;
}

/** 表格一行（7 列），日历明细和首页列表共用同一套渲染规则 */
function listRowHtml(record) {
  return (
    '<td class="col-time">' +
    escapeHtml(displayDate(record.date)) +
    "</td>" +
    '<td class="col-type">' +
    (TYPE_BADGES[record.type] || TYPE_BADGES.expense) +
    "</td>" +
    "<td>" +
    categoryLabel(record) +
    "</td>" +
    "<td>" +
    escapeHtml(record.account) +
    "</td>" +
    '<td class="text-end col-amount">' +
    amountCellHtml(record) +
    "</td>" +
    '<td class="note-cell">' +
    (record.note ? escapeHtml(record.note) : "-") +
    "</td>" +
    '<td class="text-end col-action">' +
    actionCellHtml(record) +
    "</td>"
  );
}

function renderDayRecords(records, emptyText) {
  const tbody = $("day-records");
  if (!tbody) {
    return;
  }
  tbody.innerHTML = "";

  if (!records.length) {
    tbody.innerHTML = emptyStateHtml(7, emptyText);
    return;
  }

  // 同一天的账单按时间正序，看起来更符合直觉
  records
    .slice()
    .sort(function (a, b) {
      return String(displayDate(a.date)).localeCompare(String(displayDate(b.date)));
    })
    .forEach(function (record) {
      const row = document.createElement("tr");
      row.setAttribute("data-id", String(record.id));
      row.innerHTML = listRowHtml(record);
      tbody.appendChild(row);
    });
}

function setDetailHead(title, sub) {
  if ($("day-title")) {
    $("day-title").textContent = title;
  }
  if ($("day-sub")) {
    $("day-sub").textContent = sub;
  }
}

/* ==================== 日历热力图 ==================== */

// 纯色只留两个：正结余绿（#059669）、负结余红（#dc2626）
const HEAT_RGB = {
  plus: [5, 150, 105],
  minus: [220, 38, 38],
};
const HEAT_MIN_ALPHA = 0.12;
const HEAT_MAX_ALPHA = 0.85;
// 白字阈值：叠色后的相对亮度低于它，就认为底够深，文字转白
const HEAT_DEEP_LUMINANCE = 0.3;

/** sRGB 单通道线性化，算相对亮度用 */
function linearChannel(value) {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

/** 相对亮度（WCAG 公式），这里只用来比较「深不深」 */
function relativeLuminance(rgb) {
  return (
    0.2126 * linearChannel(rgb[0]) +
    0.7152 * linearChannel(rgb[1]) +
    0.0722 * linearChannel(rgb[2])
  );
}

/**
 * 当前视图里最大的 |结余|，热力深浅按它归一化。
 * 同样是 50 块，在「单日峰值 60」的月份里几乎是满色，
 * 在「单日峰值 5000」的月份里就只是浅浅一层——这样一个月内部的深浅才有可比性。
 */
function maxAbsNet(values) {
  let peak = 0;
  values.forEach(function (value) {
    const size = Math.abs(Number(value) || 0);
    if (size > peak) {
      peak = size;
    }
  });
  return peak;
}

/**
 * 一个格子的热力色：ratio = |结余| / 本视图峰值，越大颜色越深。
 * 返回 null 表示不上色（结余为 0，或整屏都没数据）。
 */
function heatTone(net, peak) {
  const amount = Number(net) || 0;
  if (!peak || amount === 0) {
    return null;
  }
  const ratio = Math.min(1, Math.abs(amount) / peak);
  const alpha = HEAT_MIN_ALPHA + (HEAT_MAX_ALPHA - HEAT_MIN_ALPHA) * ratio;
  const rgb = HEAT_RGB[amount > 0 ? "plus" : "minus"];
  // 半透明色实际叠在卡片白底上，按「白底 + alpha」估算真实亮度，决定文字黑白
  const blended = rgb.map(function (channel) {
    return 255 * (1 - alpha) + channel * alpha;
  });
  return {
    alpha: alpha,
    rgb: rgb,
    deep: relativeLuminance(blended) < HEAT_DEEP_LUMINANCE,
  };
}

/** 把热力色刷到格子 / 年卡上：背景色 + 深底时挂 is-deep 让文字转白 */
function paintHeat(cell, net, peak) {
  const tone = heatTone(net, peak);
  if (!tone) {
    return;
  }
  cell.classList.add("has-heat");
  if (tone.deep) {
    cell.classList.add("is-deep");
  }
  cell.style.backgroundColor =
    "rgba(" + tone.rgb.join(", ") + ", " + tone.alpha.toFixed(3) + ")";
}

/** 日格里的 收 / 支 / 结 三行（中屏只留结余、极小屏只留底色，由 CSS 控制） */
function dayFiguresHtml(info) {
  const netClass = info.net > 0 ? "is-plus" : info.net < 0 ? "is-minus" : "";
  return (
    '<span class="cal-figures">' +
    '<span class="cal-fig is-plus"><span class="cal-fig-label">收</span>' +
    money(info.income) +
    "</span>" +
    '<span class="cal-fig is-minus"><span class="cal-fig-label">支</span>' +
    money(info.expense) +
    "</span>" +
    '<span class="cal-fig is-net ' +
    netClass +
    '"><span class="cal-fig-label">结</span>' +
    (info.net > 0 ? "+" : "") +
    money(info.net) +
    "</span>" +
    "</span>"
  );
}

/** 月视图格子 */
function renderMonthCells() {
  const grid = $("calendar-grid");
  if (!grid) {
    return;
  }
  const year = state.calYear;
  const month = state.calMonth;
  const daily = dailySummaries(recordsOfMonth(year, month));
  // 本月单日峰值：所有格子共用一个基准，深浅才横向可比
  const peak = maxAbsNet(
    Object.keys(daily).map(function (key) {
      return daily[key].net;
    })
  );
  const todayKey = todayText();
  const firstDay = new Date(year, month, 1);
  const lead = (firstDay.getDay() + 6) % 7; // 周一开头
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  grid.innerHTML = "";

  for (let i = 0; i < lead; i += 1) {
    const blank = document.createElement("div");
    blank.className = "cal-cell is-empty";
    grid.appendChild(blank);
  }

  for (let day = 1; day <= daysInMonth; day += 1) {
    const key = year + "-" + pad2(month + 1) + "-" + pad2(day);
    const info = daily[key] || { income: 0, expense: 0, net: 0 };
    const weekday = (lead + day - 1) % 7; // 0=周一 … 5=周六, 6=周日

    // 底色不再看「有没有收入/支出」，只看当天结余的正负与大小（v0.06.1 起废弃斜切）
    let cls = "cal-cell";
    if (weekday >= 5) {
      cls += " is-weekend";
    }
    if (key === todayKey) {
      cls += " is-today";
    }
    if (key === state.calSelectedDate) {
      cls += " is-selected";
    }

    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = cls;
    cell.setAttribute("data-date", key);

    const hasData = info.income > 0 || info.expense > 0;
    let inner = '<span class="cal-day">' + day + "</span>";
    if (hasData) {
      inner += dayFiguresHtml(info);
    }
    cell.innerHTML = inner;
    // 结余正好为 0 时 paintHeat 内部会跳过，只留白底 + 三行 0
    paintHeat(cell, info.net, peak);
    grid.appendChild(cell);
  }

  // 补空格子，保证最后一行也是整 7 列
  while (grid.children.length % 7 !== 0) {
    const blank = document.createElement("div");
    blank.className = "cal-cell is-empty";
    grid.appendChild(blank);
  }

  $("calendar-title").textContent = year + " 年 " + (month + 1) + " 月";
}

/** 年视图：12 个月汇总格子，底色按 |单月结余| / 全年单月峰值 上热力色 */
function renderYearCells() {
  const grid = $("calendar-year-grid");
  if (!grid) {
    return;
  }
  grid.innerHTML = "";

  // 先把 12 个月都算出来：既用于取峰值，也避免下面重复统计
  const months = [];
  for (let month = 0; month < 12; month += 1) {
    months.push(summarize(recordsOfMonth(state.calYear, month)));
  }
  const peak = maxAbsNet(
    months.map(function (summary) {
      return summary.net;
    })
  );

  months.forEach(function (summary, month) {
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "year-cell" + (month === state.calMonth ? " is-current" : "");
    cell.setAttribute("data-month", String(month));
    cell.innerHTML =
      '<div class="year-head">' +
      state.calYear +
      " 年 " +
      (month + 1) +
      " 月</div>" +
      '<div class="year-line"><span>收入</span><strong class="is-plus">' +
      money(summary.income) +
      "</strong></div>" +
      '<div class="year-line"><span>支出</span><strong class="is-minus">' +
      money(summary.expense) +
      "</strong></div>" +
      '<div class="year-line"><span>结余</span><strong class="' +
      (summary.net < 0 ? "is-minus" : "is-plus") +
      '">' +
      (summary.net > 0 ? "+" : "") +
      money(summary.net) +
      "</strong></div>";
    paintHeat(cell, summary.net, peak);
    grid.appendChild(cell);
  });

  $("calendar-title").textContent = state.calYear + " 年";
}

/** 日历总渲染：负责月/年视图切换、三张卡、下方明细 */
function renderCalendar() {
  const monthView = $("calendar-month");
  const yearView = $("calendar-year");
  const yearButton = $("cal-year-btn");
  const byYear = state.calMode === "year";

  if (monthView) {
    monthView.classList.toggle("d-none", byYear);
  }
  if (yearView) {
    yearView.classList.toggle("d-none", !byYear);
  }
  if (yearButton) {
    yearButton.textContent = byYear ? "回到月历" : "按年查看";
    yearButton.classList.toggle("btn-primary", !byYear);
    yearButton.classList.toggle("btn-outline-primary", byYear);
  }

  if (byYear) {
    renderYearCells();
    const yearLabel = state.calYear + " 年";
    renderCalendarStats(yearLabel, recordsOfYear(state.calYear));
    const monthRecords = recordsOfMonth(state.calYear, state.calMonth);
    setDetailHead(
      state.calYear + " 年 " + (state.calMonth + 1) + " 月账单",
      "点上面任意月份，进入那个月的月视图"
    );
    renderDayRecords(monthRecords, "这个月还没有账单");
    return;
  }

  renderMonthCells();

  const monthLabel = state.calYear + " 年 " + (state.calMonth + 1) + " 月";
  if (state.calSelectedDate) {
    const dayRecords = recordsOfDay(state.calSelectedDate);
    renderCalendarStats(state.calSelectedDate, dayRecords);
    setDetailHead(state.calSelectedDate + " 的账单", "点日历上的其他日期可以切换");
    renderDayRecords(dayRecords, "这一天没有账单");
  } else {
    const monthRecords = recordsOfMonth(state.calYear, state.calMonth);
    renderCalendarStats(monthLabel, monthRecords);
    setDetailHead(monthLabel + " 账单", "点日历上的某一天，只看那一天的账单");
    renderDayRecords(monthRecords, "这个月还没有账单");
  }
}

/** 上 / 下一月（年视图下是上 / 下一年） */
function moveCalendar(delta) {
  if (state.calMode === "year") {
    state.calYear += delta;
    renderCalendar();
    return;
  }
  let year = state.calYear;
  let month = state.calMonth + delta;
  if (month < 0) {
    month = 11;
    year -= 1;
  } else if (month > 11) {
    month = 0;
    year += 1;
  }
  state.calYear = year;
  state.calMonth = month;
  state.calSelectedDate = "";
  renderCalendar();
}

/**
 * 顶部 << / >> ：按年快切（月视图里平移整年且保留月份，年视图里直接换年）。
 * 钳在 1970–2100，防手滑点到离谱年份后日历一片空白。
 */
function moveCalendarYear(delta) {
  const target = state.calYear + delta;
  if (target < 1970 || target > 2100) {
    return;
  }
  state.calYear = target;
  state.calSelectedDate = "";
  renderCalendar();
}

function selectCalendarDay(key) {
  state.calSelectedDate = key;
  renderCalendar();
}

function selectCalendarMonth(month) {
  state.calMonth = month;
  state.calMode = "month";
  state.calSelectedDate = "";
  renderCalendar();
}

function toggleCalendarMode() {
  state.calMode = state.calMode === "year" ? "month" : "year";
  renderCalendar();
}

/** 日历数据源：全量账单，不受首页账户筛选影响 */
async function loadCalendarRecords() {
  const finish = beginTableLoad($("day-records"), 7);
  try {
    const data = await api("/api/records");
    state.calendarRecords = data.records || [];
    renderCalendar();
  } finally {
    finish();
  }
}

/* ==================== 表单校验 ==================== */

/**
 * 记账表单：一边收集字段，一边记下不合格的项。
 * 校验只在提交时跑，输入过程中不弹任何红字（公式静默）。
 */
function collectRecordValues() {
  const issues = [];
  const type = currentType();
  const parsed = amountFromInput($("amount").value);

  const values = {
    type: type,
    amount: parsed.ok ? parsed.value : null,
    formula: parsed.formula || "",
    account: $("account").value,
    note: $("note").value.trim(),
    date: $("record-time").value,
    to_account: "",
    fee: 0,
    category_id: null,
  };

  if (!parsed.ok) {
    issues.push({ field: $("amount"), message: parsed.message });
  }
  if (!values.account) {
    issues.push({ field: $("account"), message: "请选择账户" });
  }
  if (!values.date) {
    issues.push({ field: $("record-time"), message: "请选择时间" });
  }

  if (type === "transfer") {
    values.to_account = $("to-account").value;
    if (!values.to_account) {
      issues.push({ field: $("to-account"), message: "请选择转入账户" });
    } else if (values.to_account === values.account) {
      issues.push({ field: $("to-account"), message: "转出与转入账户不能相同" });
    }

    const feeText = String($("fee").value || "").trim();
    const fee = Number(feeText === "" ? 0 : feeText);
    if (!Number.isFinite(fee) || fee < 0) {
      issues.push({ field: $("fee"), message: "手续费必须是不小于 0 的数字" });
    }
    values.fee = Number.isFinite(fee) && fee > 0 ? cents(fee) : 0;
  } else {
    values.category_id = selectedCategoryId();
    if (!values.category_id) {
      issues.push({
        field: $("category"),
        message: state.categories.length ? "请选择分类" : "还没有分类，先去「分类管理」添加一个",
      });
    }
  }

  return { issues: issues, values: values };
}

function collectAccountValues() {
  const issues = [];
  const name = $("new-account-name").value.trim();
  const group = $("new-account-group").value;
  const balanceText = String($("new-account-balance").value || "").trim();
  const balance = Number(balanceText === "" ? 0 : balanceText);

  if (!name) {
    issues.push({ field: $("new-account-name"), message: "请填写账户名称" });
  }
  if (!group) {
    issues.push({ field: $("new-account-group"), message: "请选择账户大类" });
  }
  if (!Number.isFinite(balance)) {
    issues.push({ field: $("new-account-balance"), message: "初始余额必须是数字" });
  }

  return {
    issues: issues,
    values: { name: name, group: group, balance: cents(Number.isFinite(balance) ? balance : 0) },
  };
}

function collectCategoryValues() {
  const issues = [];
  const name = $("new-category-name").value.trim();
  const parentValue = $("new-category-parent").value;

  if (!name) {
    issues.push({ field: $("new-category-name"), message: "请填写分类名称" });
  }

  return {
    issues: issues,
    values: { name: name, parentId: parentValue ? Number(parentValue) : null },
  };
}

/* ==================== 记账弹窗 ==================== */

function resetRecordForm() {
  state.editingId = null;
  state.presetAccount = "";
  // 上一次保存如果还卡在「保存中…」，先还原按钮，再复位文案
  setButtonBusy($("save-btn"), false);
  clearFormErrors($("record-modal"));
  $("record-modal-title").textContent = "记一笔";
  $("save-btn").textContent = "保存";
  $("amount").value = "";
  $("note").value = "";
  $("fee").value = "0";
  $("record-time").value = nowInputValue();
  $("amount-hint").textContent = "";
  $("amount-hint").classList.remove("is-error");

  fillCategoryParent(null);
  fillCategoryChild($("category").value, "");
  $("sub-category").value = "";

  setType("expense");
  if (state.accounts.length) {
    $("account").value = state.accounts[0].name;
  }
  fillAccountSelects();
}

function fillRecordForm(record) {
  // 金额：有公式就回显公式，让用户还能接着改算式
  $("amount").value = record.formula ? record.formula : String(cents(record.amount));
  updateAmountHint();

  $("record-time").value = toInputValue(record.date);
  $("note").value = record.note || "";
  $("account").value = record.account || $("account").value;

  if (record.type === "transfer") {
    $("fee").value = String(cents(record.fee || 0));
    if (record.to_account) {
      $("to-account").value = record.to_account;
    }
    $("category").value = String($("category").value);
    return;
  }

  // 分类：先定位到一级，再把二级选上
  const found = findCategory(record.category_id);
  if (found) {
    if (found.parent) {
      fillCategoryParent(found.parent.id);
      fillCategoryChild(found.parent.id, found.node.id);
    } else {
      fillCategoryParent(found.node.id);
      fillCategoryChild(found.node.id, "");
    }
  }
}

function openRecordModal(options) {
  resetRecordForm();

  const record = options && options.record ? options.record : null;
  if (record) {
    state.editingId = record.id;
    $("record-modal-title").textContent = "编辑记录 #" + record.id;
    $("save-btn").textContent = "保存修改";
    setType(record.type);
    fillRecordForm(record);
    applyTypeUi();
  } else {
    const presetAccount = options && options.account ? options.account : "";
    if (presetAccount) {
      // 快捷记账：只预选账户，不锁死，用户想改随时能改
      $("account").value = presetAccount;
      const other = state.accounts.find(function (account) {
        return account.name !== presetAccount;
      });
      if (other) {
        $("to-account").value = other.name;
      }
    }
  }

  if (recordModal) {
    recordModal.show();
  }
}

function closeRecordModal() {
  if (recordModal) {
    recordModal.hide();
  }
}

async function saveRecord() {
  // 1) 先校验：空项 / 写了一半的公式都在这里拦下来，用 Toast + 字段红框说清楚
  const check = collectRecordValues();
  if (reportIssues($("record-modal"), check.issues)) {
    return;
  }

  // 2) 并发锁：连点几下也只有第一次真的发请求
  if (!lockAction("record-save")) {
    return;
  }

  const values = check.values;
  const payload = {
    amount: values.amount,
    formula: values.formula,
    account: values.account,
    type: values.type,
    note: values.note,
  };
  if (values.date) {
    payload.date = values.date;
  }
  if (values.type === "transfer") {
    payload.to_account = values.to_account;
    payload.fee = values.fee;
  } else {
    payload.category_id = values.category_id;
  }

  // 3) 按钮内嵌 Spinner，不 disabled，避免按钮突然发灰
  const button = $("save-btn");
  setButtonBusy(button, true, "保存中…");
  try {
    if (state.editingId) {
      await api("/api/records/" + state.editingId, jsonOptions("PUT", payload));
      toast("已保存修改", "success");
    } else {
      await api("/api/records", jsonOptions("POST", payload));
      toast("记账成功", "success");
    }
    closeRecordModal();
    await refresh();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setButtonBusy(button, false);
    unlockAction("record-save");
  }
}

async function removeRecord(recordId) {
  if (!window.confirm("确定删除这条记录吗？删除后余额会一起退回去。")) {
    return;
  }
  const lockKey = "record-delete-" + recordId;
  if (!lockAction(lockKey)) {
    return;
  }
  try {
    await api("/api/records/" + recordId, { method: "DELETE" });
    toast("已删除", "success");
    await refresh();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    unlockAction(lockKey);
  }
}

function onRecordListClick(event) {
  const button = event.target.closest("[data-action]");
  if (!button) {
    return;
  }
  const recordId = Number(button.getAttribute("data-id"));
  if (button.getAttribute("data-action") === "edit") {
    const record =
      state.allRecords.find(function (item) {
        return item.id === recordId;
      }) ||
      state.detailRecords.find(function (item) {
        return item.id === recordId;
      }) ||
      state.calendarRecords.find(function (item) {
        return item.id === recordId;
      });
    if (record) {
      openRecordModal({ record: record });
    }
    return;
  }
  removeRecord(recordId);
}

/* ==================== 分类增删 ==================== */

async function addCategory() {
  const check = collectCategoryValues();
  if (reportIssues($("category-modal"), check.issues)) {
    return;
  }
  if (!lockAction("category-add")) {
    return;
  }

  const payload = { name: check.values.name };
  if (check.values.parentId) {
    payload.parent_id = check.values.parentId;
  }

  const button = $("add-category-btn");
  setButtonBusy(button, true, "添加中…");
  try {
    await api("/api/categories", jsonOptions("POST", payload));
    $("new-category-name").value = "";
    clearFormErrors($("category-modal"));
    toast("分类已添加", "success");
    await loadCategories();
    await loadRecords();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setButtonBusy(button, false);
    unlockAction("category-add");
  }
}

async function removeCategory(categoryId) {
  if (!window.confirm("删除这个分类？有子分类或已有账目时不允许删。")) {
    return;
  }
  const lockKey = "category-delete-" + categoryId;
  if (!lockAction(lockKey)) {
    return;
  }
  try {
    await api("/api/categories/" + categoryId, { method: "DELETE" });
    toast("分类已删除", "success");
    await loadCategories();
    await loadRecords();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    unlockAction(lockKey);
  }
}

/* ==================== 账户增删 ==================== */

async function addAccount() {
  const check = collectAccountValues();
  if (reportIssues($("account-modal"), check.issues)) {
    return;
  }
  if (!lockAction("account-add")) {
    return;
  }

  const button = $("save-account-btn");
  setButtonBusy(button, true, "保存中…");
  try {
    await api(
      "/api/accounts",
      jsonOptions("POST", {
        name: check.values.name,
        group_name: check.values.group,
        balance: check.values.balance,
      })
    );
    $("new-account-name").value = "";
    $("new-account-balance").value = "0";
    clearFormErrors($("account-modal"));
    toast("账户已添加", "success");
    if (accountModal) {
      accountModal.hide();
    }
    await refresh();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setButtonBusy(button, false);
    unlockAction("account-add");
  }
}

async function removeAccount(name) {
  if (!window.confirm("删除账户「" + name + "」？账户下还有账目时不允许删。")) {
    return;
  }
  const lockKey = "account-delete-" + name;
  if (!lockAction(lockKey)) {
    return;
  }
  try {
    await api("/api/accounts/" + encodeURIComponent(name), { method: "DELETE" });
    toast("账户已删除", "success");
    if (state.detailAccount === name) {
      clearDetail();
    }
    await refresh();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    unlockAction(lockKey);
  }
}

/* ==================== 切页 ==================== */

function switchPage(page) {
  const target = PAGE_TITLES[page] ? page : "home";
  $("page-title").textContent = PAGE_TITLES[target];

  document.querySelectorAll(".nav-item").forEach(function (item) {
    item.classList.toggle("active", item.getAttribute("data-page") === target);
  });
  document.querySelectorAll(".page").forEach(function (section) {
    section.classList.toggle("active", section.id === "page-" + target);
  });
}

/* ==================== 刷新 ==================== */

async function refresh() {
  await Promise.all([loadStatistics(), loadAccounts(), loadRecords(), loadCalendarRecords()]);
  await refreshDetail();
}

/* ==================== 事件绑定 ==================== */

function bindEvents() {
  // 顶部按钮
  $("add-record-btn").addEventListener("click", function () {
    openRecordModal({});
  });

  // 侧边栏
  document.querySelectorAll(".nav-item").forEach(function (item) {
    item.addEventListener("click", function (event) {
      event.preventDefault();
      switchPage(item.getAttribute("data-page"));
    });
  });

  // 类型切换
  document.querySelectorAll('input[name="record-type"]').forEach(function (radio) {
    radio.addEventListener("change", applyTypeUi);
  });

  // 金额公式实时计算
  $("amount").addEventListener("input", updateAmountHint);

  // 一级分类变了，二级跟着变
  $("category").addEventListener("change", function () {
    fillCategoryChild($("category").value, "");
  });

  // 账户筛选
  $("filter-account").addEventListener("change", function () {
    loadRecords().catch(function (error) {
      toast(error.message, "error");
    });
  });

  // 保存
  $("save-btn").addEventListener("click", saveRecord);

  // 弹窗内 Enter = 提交；Esc 关闭交给 Bootstrap 的 data-bs-keyboard
  $("record-form").addEventListener("submit", function (event) {
    event.preventDefault();
    saveRecord();
  });
  bindEnterSubmit($("record-modal"), saveRecord);
  bindEnterSubmit($("account-modal"), addAccount);
  bindEnterSubmit($("category-modal"), addCategory);

  // 一开始输入 / 切换选项，就把这个字段的红框清掉
  bindErrorClearing($("record-modal"));
  bindErrorClearing($("account-modal"));
  bindErrorClearing($("category-modal"));

  // 记账弹窗关掉时复位，免得下次打开还带着上次的编辑态
  const modalElement = $("record-modal");
  if (modalElement) {
    modalElement.addEventListener("hidden.bs.modal", resetRecordForm);
  }

  // 列表里的编辑 / 删除（事件委托，动态行也能响应）
  $("record-list").addEventListener("click", onRecordListClick);
  $("account-records").addEventListener("click", onRecordListClick);
  $("day-records").addEventListener("click", onRecordListClick);

  // 日历：上/下月（年视图里是上/下一年）、按年查看、点某天、点某月
  $("cal-prev").addEventListener("click", function () {
    moveCalendar(-1);
  });
  $("cal-next").addEventListener("click", function () {
    moveCalendar(1);
  });
  // << / >> 快切年份：月视图里整年平移，年视图里直接换年
  $("cal-prev-year").addEventListener("click", function () {
    moveCalendarYear(-1);
  });
  $("cal-next-year").addEventListener("click", function () {
    moveCalendarYear(1);
  });
  $("cal-year-btn").addEventListener("click", toggleCalendarMode);
  $("calendar-grid").addEventListener("click", function (event) {
    const cell = event.target.closest("[data-date]");
    if (cell) {
      selectCalendarDay(cell.getAttribute("data-date"));
    }
  });
  $("calendar-year-grid").addEventListener("click", function (event) {
    const cell = event.target.closest("[data-month]");
    if (cell) {
      selectCalendarMonth(Number(cell.getAttribute("data-month")));
    }
  });

  // 资产页：点卡片看流水、点 × 删账户
  $("account-groups").addEventListener("click", function (event) {
    const del = event.target.closest("[data-del-account]");
    if (del) {
      event.stopPropagation();
      removeAccount(del.getAttribute("data-del-account"));
      return;
    }
    const card = event.target.closest(".account-card");
    if (card) {
      selectAccount(card.getAttribute("data-account")).catch(function (error) {
        toast(error.message, "error");
      });
    }
  });

  // 快捷记账
  $("quick-add-btn").addEventListener("click", function () {
    if (!state.detailAccount) {
      toast("先点一个账户", "error");
      return;
    }
    openRecordModal({ account: state.detailAccount });
  });

  // 新增账户
  $("open-account-btn").addEventListener("click", function () {
    if (accountModal) {
      accountModal.show();
    }
  });
  $("save-account-btn").addEventListener("click", addAccount);

  // 分类管理
  $("open-category-btn").addEventListener("click", function () {
    if (categoryModal) {
      categoryModal.show();
    }
  });
  $("add-category-btn").addEventListener("click", addCategory);
  $("category-tree").addEventListener("click", function (event) {
    const button = event.target.closest("[data-del-category]");
    if (button) {
      removeCategory(Number(button.getAttribute("data-del-category")));
    }
  });
}

/* ==================== 启动 ==================== */

async function init() {
  const modalElement = $("record-modal");
  const accountElement = $("account-modal");
  const categoryElement = $("category-modal");
  if (window.bootstrap) {
    recordModal = new window.bootstrap.Modal(modalElement);
    accountModal = new window.bootstrap.Modal(accountElement);
    categoryModal = new window.bootstrap.Modal(categoryElement);
    bindEscClose(modalElement, recordModal);
    bindEscClose(accountElement, accountModal);
    bindEscClose(categoryElement, categoryModal);
  }

  bindEvents();

  try {
    await loadCategories();
    await refresh();
  } catch (error) {
    toast(error.message, "error");
  }

  switchPage("home");
}

document.addEventListener("DOMContentLoaded", init);
