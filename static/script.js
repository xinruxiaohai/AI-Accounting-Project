"use strict";

/*
 * AI记账管家 · 前端逻辑（v0.06.3）
 *
 * v0.06.3 在 v0.06.2 的三栏看板上补上蓝图里欠的三件：
 *   1. ECharts 支出分类饼图 + 近 30 天折线（本地 vendor，Toolbox 可存图）
 *   2. 右下悬浮球：本月预算剩余 + 快捷键面板（N / Ctrl+K / Esc）
 *   3. 账单分页（20/50/100/不分页）与滚动到底自动追加 20 条
 *
 * v0.06.2 完成的结构性重构：
 *   1. 首页变三栏 Dashboard：巨型本月支出卡 + 预算环 + 近 7 天分组卡片，右栏是日历
 *   2. 账单不再有行内「编辑 / 删除」按钮，整行点击弹出详情，操作收进详情弹窗（幽灵按钮）
 *   3. 深色模式（CSS 变量 + localStorage）、侧栏折叠、全局搜索、通知中心
 *   4. 日历热力图透明度上限降到 0.35，文字始终深色，不再出现白字混搭
 */

/* ==================== 常量 ==================== */

const PAGE_TITLES = {
  home: "首页",
  assets: "资产",
  profile: "我的",
};

// localStorage 键名集中在这里，避免各函数各写一份字符串
const LS_THEME = "ai-accounting-theme";
const LS_SIDEBAR = "ai-accounting-sidebar-collapsed";
const LS_BUDGET = "ai-accounting-budget";
const LS_NOTIFY_READ = "ai-accounting-notify-read-at";
// v0.06.3：账单列表每页条数（0 = 不分页，滚动到底自动追加）
const LS_PAGE_SIZE = "ai-accounting-page-size";
const PAGE_SIZE_OPTIONS = [20, 50, 100, 0];
const INFINITE_STEP = 20;
const DEFAULT_BUDGET = 3000;

// 饼图配色：蓝 / 橙 / 绿 / 红 / 紫 / 青 / 橘 / 灰，深浅色下都能看清
const PIE_COLORS = [
  "#2563eb",
  "#f59e0b",
  "#10b981",
  "#ef4444",
  "#8b5cf6",
  "#06b6d4",
  "#f97316",
  "#64748b",
];

// 预算环半径 52，周长 2πr，画进度时用
const BUDGET_RING_CIRCUMFERENCE = 326.73;

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

// 10 秒还没回来就当超时，给用户一个明确提示，而不是让按钮一直转圈
const REQUEST_TIMEOUT_MS = 10000;

async function api(path, options) {
  const controller = new AbortController();
  const timer = window.setTimeout(function () {
    controller.abort();
  }, REQUEST_TIMEOUT_MS);

  let response;
  try {
    response = await fetch(
      path,
      Object.assign({}, options, { signal: controller.signal })
    );
  } catch (error) {
    if (error && error.name === "AbortError") {
      throw new Error("请求超时（10 秒），请检查网络后重试");
    }
    if (error instanceof TypeError) {
      throw new Error("网络连接失败，请确认后端服务已启动");
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }

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
  // v0.06.2：全局搜索词、通知缓存、预算上限（预算同步存 localStorage）
  searchQuery: "",
  notifications: [],
  budget: DEFAULT_BUDGET,
  // 详情弹窗当前展示的账单 id，编辑 / 删除都以它为准
  detailRecordId: null,
  // v0.06.3：账单列表分页（0 = 不分页）与滚动加载进度
  pageSize: 20,
  pageIndex: 1,
  renderedCount: INFINITE_STEP,
  // v0.07：通讯录与当前选中的联系人
  contacts: [],
  selectedContactId: null,
};

let recordModal = null;
let accountModal = null;
let categoryModal = null;
let recordDetailModal = null;

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

function isDebtType() {
  return currentType() === "debt";
}

function applyTypeUi() {
  const transfer = isTransferType();
  const debt = isDebtType();

  // 转账、借贷都没有分类概念：分类整块藏起来
  $("category-col").classList.toggle("d-none", transfer || debt);
  $("to-account-wrap").classList.toggle("d-none", !transfer);
  $("fee-wrap").classList.toggle("d-none", !transfer);
  $("contact-col").classList.toggle("d-none", !debt);
  $("debt-direction-wrap").classList.toggle("d-none", !debt);
  // debts 表没有备注字段，借贷模式不显示备注，免得填了却没处存
  $("note-col").classList.toggle("d-none", debt);

  let label = "账户";
  if (transfer) {
    label = "转出账户";
  } else if (debt) {
    label = "资金账户";
  }
  $("account-label").innerHTML = label + REQ_MARK;

  // 切类型时把被藏起来那一组的红框清掉，免得下次显示还挂着旧错误
  if (transfer) {
    clearFieldError($("category"));
  } else {
    clearFieldError($("to-account"));
    clearFieldError($("fee"));
  }
  if (debt) {
    clearFieldError($("category"));
    fillContactSelect();
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
  wrap.classList.toggle("d-none", isTransferType() || isDebtType() || !hasChildren);
}

function selectedCategoryId() {
  if (isTransferType() || isDebtType()) {
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
    item.setAttribute("data-category-id", String(top.id));
    item.innerHTML =
      categoryRowHtml(top, counts, true) +
      (top.children.length
        ? '<ul class="category-sub" data-parent-id="' +
          top.id +
          '">' +
          top.children
            .map(function (child) {
              return (
                '<li data-category-id="' +
                child.id +
                '">' +
                categoryRowHtml(child, counts, false) +
                "</li>"
              );
            })
            .join("") +
          "</ul>"
        : "");
    list.appendChild(item);
  });

  if (!state.categories.length) {
    list.innerHTML = '<li class="empty-cell">还没有分类</li>';
    return;
  }

  // 一级分类树与每个二级分组都是独立拖拽区，顺序只在自己内部调换
  list.setAttribute("data-parent-id", "");
  initCategorySortable();
}

function categoryRowHtml(category, counts, isTop) {
  const used = counts[String(category.id)] || 0;
  const tag = used ? '<span class="tag-count">' + used + " 笔</span>" : "";
  return (
    '<div class="category-row">' +
    '<span class="drag-handle" title="按住拖动排序" aria-hidden="true">⋮⋮</span>' +
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

/* ---------- 拖拽排序（Sortable） ---------- */

// key -> Sortable 实例：重绘列表前先销毁旧的，否则同一节点会叠出一堆监听
const sortableInstances = {};

function mountSortable(key, element, options) {
  if (sortableInstances[key]) {
    sortableInstances[key].destroy();
    delete sortableInstances[key];
  }
  if (!element || typeof Sortable === "undefined") {
    return;
  }
  sortableInstances[key] = new Sortable(element, options);
}

/** 分类拖完立即写回后端；失败就重新加载，把 DOM 拉回真实顺序 */
function saveCategoryOrder(container, parentId) {
  const ids = Array.prototype.slice
    .call(container.querySelectorAll(":scope > li[data-category-id]"))
    .map(function (item) {
      return Number(item.getAttribute("data-category-id"));
    });
  api(
    "/api/categories/order",
    jsonOptions("PUT", { ids: ids, parent_id: parentId || null })
  )
    .then(function () {
      toast("分类顺序已保存", "success");
    })
    .catch(function (error) {
      toast(error.message, "error");
    })
    .then(function () {
      return loadCategories();
    });
}

function initCategorySortable() {
  const list = $("category-tree");
  if (!list) {
    return;
  }

  mountSortable("categories-top", list, {
    handle: ".drag-handle",
    animation: 150,
    ghostClass: "sortable-ghost",
    chosenClass: "sortable-chosen",
    onEnd: function (event) {
      saveCategoryOrder(event.to, null);
    },
  });

  Array.prototype.forEach.call(
    list.querySelectorAll("ul.category-sub"),
    function (subList) {
      const parentId = Number(subList.getAttribute("data-parent-id"));
      mountSortable("categories-" + parentId, subList, {
        handle: ".drag-handle",
        animation: 150,
        ghostClass: "sortable-ghost",
        chosenClass: "sortable-chosen",
        onEnd: function (event) {
          saveCategoryOrder(event.to, parentId);
        },
      });
    }
  );
}

/* ---------- 账户弹窗里的排序列表 ---------- */

function renderAccountSortList() {
  const list = $("account-sort-list");
  if (!list) {
    return;
  }

  if (!state.accounts.length) {
    list.innerHTML = '<li class="empty-cell">还没有账户</li>';
    return;
  }

  list.innerHTML = state.accounts
    .map(function (account) {
      return (
        '<li class="account-sort-item" data-account-name="' +
        escapeHtml(account.name) +
        '">' +
        '<span class="drag-handle" title="按住拖动排序" aria-hidden="true">⋮⋮</span>' +
        '<span class="account-sort-name">' +
        escapeHtml(account.name) +
        "</span>" +
        '<span class="account-sort-group">' +
        escapeHtml(account.group_name || "资金账户") +
        "</span>" +
        "</li>"
      );
    })
    .join("");

  mountSortable("account-sort", list, {
    handle: ".drag-handle",
    animation: 150,
    ghostClass: "sortable-ghost",
    chosenClass: "sortable-chosen",
    onEnd: function (event) {
      const names = Array.prototype.slice
        .call(event.to.querySelectorAll(":scope > li[data-account-name]"))
        .map(function (item) {
          return item.getAttribute("data-account-name");
        });
      api("/api/accounts/order", jsonOptions("PUT", { names: names }))
        .then(function () {
          toast("账户顺序已保存", "success");
        })
        .catch(function (error) {
          toast(error.message, "error");
        })
        .then(function () {
          return refresh();
        });
    },
  });
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
    renderAccountSortList();

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
  $("account-records").innerHTML = emptyStateHtml(5, "先在上方点一个账户，这里会显示它的流水");
}

async function selectAccount(name) {
  state.detailAccount = name;
  $("detail-title").textContent = name + " · 流水";
  $("quick-add-btn").disabled = false;
  renderAccountGroups();

  const finish = beginTableLoad($("account-records"), 5);
  try {
    const data = await api("/api/records?account=" + encodeURIComponent(name));
    state.detailRecords = data.records || [];
    renderAccountRecords();
  } finally {
    finish();
  }
}

/* ==================== 三栏看板：主卡 / 预算 / 近 7 天 ==================== */

/** 今天所在自然月的账单（主卡固定展示「本月」，不随日历导航变化） */
function currentMonthRecords() {
  const today = new Date();
  return recordsOfMonth(today.getFullYear(), today.getMonth());
}

/** 本月已过天数（含今天），算日均用；至少 1，避免除 0 */
function monthDaysElapsed() {
  return Math.max(1, new Date().getDate());
}

/** 中栏主卡：本月支出最大，收入 / 结余做陪衬 */
function renderHero() {
  const today = new Date();
  const summary = summarize(currentMonthRecords());

  const label = $("hero-month-label");
  if (label) {
    label.textContent = today.getFullYear() + " 年 " + (today.getMonth() + 1) + " 月";
  }

  if ($("hero-expense")) {
    $("hero-expense").textContent = money(summary.expense);
  }
  if ($("hero-income")) {
    $("hero-income").textContent = money(summary.income);
  }
  if ($("hero-net")) {
    $("hero-net").textContent = money(summary.net);
    $("hero-net").classList.toggle("is-negative", summary.net < 0);
  }
}

/** 预算上限：localStorage 里没有（或被改坏了）就用默认 3000 */
function readBudget() {
  const saved = Number(localStorage.getItem(LS_BUDGET));
  return Number.isFinite(saved) && saved > 0 ? saved : DEFAULT_BUDGET;
}

/** 预算卡：环形进度 + 日均 + 剩余日均额度。超支时进度条与数字标红 */
function renderBudget() {
  const summary = summarize(currentMonthRecords());
  const spent = summary.expense;
  const limit = state.budget;
  const ratio = limit > 0 ? Math.min(1, spent / limit) : 0;

  const arc = $("budget-ring-arc");
  if (arc) {
    // stroke-dashoffset 越小，画出来的圆弧越长：满额时偏移 0
    arc.setAttribute(
      "stroke-dashoffset",
      String(BUDGET_RING_CIRCUMFERENCE * (1 - ratio))
    );
  }

  if ($("budget-percent")) {
    $("budget-percent").textContent = Math.round(ratio * 100) + "%";
  }
  if ($("budget-spent")) {
    $("budget-spent").textContent = money(spent);
  }
  if ($("budget-limit")) {
    $("budget-limit").textContent = money(limit);
  }

  const today = new Date();
  const daysElapsed = monthDaysElapsed();
  const daysInMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate();
  const daysLeft = Math.max(0, daysInMonth - daysElapsed);

  const daily = spent / daysElapsed;
  const leftDaily = daysLeft > 0 ? Math.max(0, limit - spent) / daysLeft : 0;
  if ($("budget-daily")) {
    $("budget-daily").textContent = money(daily);
  }
  if ($("budget-left")) {
    $("budget-left").textContent = money(leftDaily);
  }

  const fill = $("budget-bar-fill");
  if (fill) {
    fill.style.width = Math.round(ratio * 100) + "%";
  }

  const card = document.querySelector(".budget-card");
  if (card) {
    card.classList.toggle("is-over", spent > limit);
  }
}

/* ==================== 数据可视化（ECharts，本地 vendor 引入） ==================== */

let pieChart = null;
let trendChart = null;

function isDarkMode() {
  return document.documentElement.getAttribute("data-theme") === "dark";
}

/** 图表用的文字 / 线条颜色，跟随深色模式 */
function chartPalette() {
  const dark = isDarkMode();
  return {
    text: dark ? "#cbd5e1" : "#475569",
    strong: dark ? "#e2e8f0" : "#1e293b",
    line: dark ? "#24334a" : "#e6ebf2",
    surface: dark ? "#131c2b" : "#ffffff",
    brand: dark ? "#3b82f6" : "#2563eb",
  };
}

/**
 * 本月支出按分类汇总。
 * 类别多于 8 个时，前 7 名单独成片，剩下的合并成「其他」，避免饼图碎成渣。
 */
function monthExpenseByCategory() {
  const now = new Date();
  const groups = {};
  let count = 0;
  recordsOfMonth(now.getFullYear(), now.getMonth()).forEach(function (record) {
    if (record.type !== "expense") {
      return;
    }
    const name = record.category || "未分类";
    groups[name] = (groups[name] || 0) + Number(record.amount || 0);
    count += 1;
  });

  let list = Object.keys(groups).map(function (name) {
    return { name: name, value: cents(groups[name]) };
  });
  list.sort(function (a, b) {
    return b.value - a.value;
  });

  if (list.length > 8) {
    const rest = list.slice(7).reduce(function (sum, item) {
      return sum + item.value;
    }, 0);
    list = list.slice(0, 7).concat([{ name: "其他", value: cents(rest) }]);
  }
  return { list: list, count: count };
}

/** 近 N 天每天的支出合计（没有账单的日子补 0，折线才连续） */
function dailyExpenseSeries(days) {
  const todayKey = todayText();
  const startKey = shiftDateKey(todayKey, -(days - 1));
  const totals = {};
  let total = 0;

  state.calendarRecords.forEach(function (record) {
    if (record.type !== "expense") {
      return;
    }
    const key = dateKeyOf(record);
    if (key < startKey || key > todayKey) {
      return;
    }
    const amount = Number(record.amount || 0);
    totals[key] = (totals[key] || 0) + amount;
    total += amount;
  });

  const labels = [];
  const values = [];
  for (let i = 0; i < days; i += 1) {
    const key = shiftDateKey(startKey, i);
    labels.push(key.slice(5).replace("-", "/"));
    values.push(cents(totals[key] || 0));
  }
  return { labels: labels, values: values, total: cents(total) };
}

/** Toolbox：保存图片 + 刷新（restore），按需求两件都开 */
function chartToolbox() {
  const palette = chartPalette();
  return {
    right: 4,
    top: 0,
    itemSize: 13,
    itemGap: 10,
    iconStyle: { borderColor: palette.text },
    feature: {
      saveAsImage: {
        title: "保存为图片",
        name: "AI记账管家-图表",
        pixelRatio: 2,
        backgroundColor: palette.surface,
      },
      restore: { title: "刷新图表" },
    },
  };
}

function pieOption(list, count) {
  const palette = chartPalette();
  const empty = !list.length;

  return {
    tooltip: {
      trigger: "item",
      formatter: function (params) {
        return (
          params.marker +
          params.name +
          "：" +
          money(params.value) +
          "（" +
          params.percent +
          "%）"
        );
      },
      backgroundColor: palette.surface,
      borderColor: palette.line,
      textStyle: { color: palette.strong },
    },
    toolbox: chartToolbox(),
    title: empty
      ? {
          text: "本月还没有支出记录",
          left: "center",
          top: "44%",
          textStyle: { color: palette.text, fontSize: 12, fontWeight: "normal" },
        }
      : undefined,
    color: PIE_COLORS,
    legend: {
      type: "scroll",
      bottom: 0,
      icon: "circle",
      itemWidth: 8,
      itemHeight: 8,
      textStyle: { color: palette.text, fontSize: 11 },
      pageIconColor: palette.text,
      pageTextStyle: { color: palette.text },
    },
    series: [
      {
        name: "本月支出",
        type: "pie",
        radius: ["40%", "66%"],
        center: ["50%", "42%"],
        avoidLabelOverlap: true,
        itemStyle: {
          borderColor: palette.surface,
          borderWidth: 2,
          borderRadius: 4,
        },
        label: {
          color: palette.text,
          fontSize: 11,
          formatter: "{b} {d}%",
        },
        labelLine: { length: 8, length2: 8, lineStyle: { color: palette.line } },
        emphasis: {
          label: { fontSize: 12, fontWeight: "bold", color: palette.strong },
          itemStyle: { shadowBlur: 10, shadowColor: "rgba(15, 23, 42, .2)" },
        },
        data: empty
          ? []
          : list.map(function (item, index) {
              return {
                name: item.name,
                value: item.value,
                itemStyle: { color: PIE_COLORS[index % PIE_COLORS.length] },
              };
            }),
      },
    ],
    graphic: empty
      ? []
      : [
          {
            type: "text",
            left: "center",
            top: "36%",
            style: {
              text: money(
                list.reduce(function (sum, item) {
                  return sum + item.value;
                }, 0)
              ),
              fill: palette.strong,
              fontSize: 15,
              fontWeight: 600,
            },
            silent: true,
          },
          {
            type: "text",
            left: "center",
            top: "45%",
            style: { text: count + " 笔支出", fill: palette.text, fontSize: 11 },
            silent: true,
          },
        ],
  };
}

function trendOption(series) {
  const palette = chartPalette();
  const empty = series.total <= 0;

  return {
    tooltip: {
      trigger: "axis",
      formatter: function (params) {
        const point = params[0] || {};
        return point.axisValue + "<br/>支出 " + money(point.value || 0);
      },
      backgroundColor: palette.surface,
      borderColor: palette.line,
      textStyle: { color: palette.strong },
    },
    toolbox: chartToolbox(),
    title: empty
      ? {
          text: "近 30 天还没有支出",
          left: "center",
          top: "44%",
          textStyle: { color: palette.text, fontSize: 12, fontWeight: "normal" },
        }
      : undefined,
    grid: { left: 8, right: 12, top: 22, bottom: 6, containLabel: true },
    xAxis: {
      type: "category",
      boundaryGap: false,
      data: series.labels,
      axisLine: { lineStyle: { color: palette.line } },
      axisTick: { show: false },
      axisLabel: {
        color: palette.text,
        fontSize: 10,
        interval: 4,
        formatter: function (value) {
          return value;
        },
      },
    },
    yAxis: {
      type: "value",
      splitNumber: 3,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: palette.text,
        fontSize: 10,
        formatter: function (value) {
          return value >= 1000 ? value / 1000 + "k" : value;
        },
      },
      splitLine: { lineStyle: { color: palette.line, type: "dashed" } },
    },
    series: [
      {
        name: "支出",
        type: "line",
        smooth: true,
        showSymbol: false,
        symbolSize: 6,
        data: series.values,
        lineStyle: { width: 2.2, color: palette.brand },
        itemStyle: { color: palette.brand },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: "rgba(37, 99, 235, .28)" },
            { offset: 1, color: "rgba(37, 99, 235, .02)" },
          ]),
        },
        emphasis: { focus: "series" },
      },
    ],
  };
}

/** 第一次真正画图时才 init，避免页面还没有数据就建实例 */
function initCharts() {
  if (!window.echarts) {
    return false;
  }
  const pieEl = $("chart-pie");
  const trendEl = $("chart-trend");
  if (!pieEl || !trendEl) {
    return false;
  }

  if (!pieChart) {
    pieChart = echarts.init(pieEl);
    // Toolbox 的「刷新」会把图回到初始 option，这里重新喂一次最新数据
    pieChart.on("restore", function () {
      renderCharts();
    });
  }
  if (!trendChart) {
    trendChart = echarts.init(trendEl);
    trendChart.on("restore", function () {
      renderCharts();
    });
  }
  watchChartResize();
  return true;
}

/**
 * 容器宽度变化时自己 resize。
 * 只靠 window.resize 不够：侧栏折叠、媒体查询换栏、窗口缩放后的回流都在
 * resize 事件之后才落定，图表会停在旧宽度上。
 */
let chartResizeObserver = null;
let chartResizeFrame = 0;

function watchChartResize() {
  if (chartResizeObserver || !("ResizeObserver" in window)) {
    return;
  }
  chartResizeObserver = new ResizeObserver(function () {
    window.cancelAnimationFrame(chartResizeFrame);
    chartResizeFrame = window.requestAnimationFrame(resizeCharts);
  });
  [pieChart, trendChart].forEach(function (chart) {
    if (chart && chart.getDom()) {
      chartResizeObserver.observe(chart.getDom());
    }
  });
}

function renderCharts() {
  if (!initCharts()) {
    return;
  }
  const pie = monthExpenseByCategory();
  const trend = dailyExpenseSeries(30);

  pieChart.setOption(pieOption(pie.list, pie.count), true);
  trendChart.setOption(trendOption(trend), true);

  if ($("charts-sub")) {
    $("charts-sub").textContent =
      "本月支出 " +
      pie.count +
      " 笔 · 近 30 天合计 " +
      money(trend.total);
  }
}

function resizeCharts() {
  [pieChart, trendChart].forEach(function (chart) {
    if (!chart) {
      return;
    }
    const dom = chart.getDom();
    // 首页被切走时容器宽 0，这时候 resize 会把画布压成 0，等它显示回来再量
    if (!dom || !dom.clientWidth) {
      return;
    }
    try {
      chart.resize();
    } catch (error) {
      // 容器被隐藏时 resize 可能失败，忽略即可
    }
  });
}

/* ---------- 全局搜索 ---------- */

/** 一条账单是否命中搜索词：分类名、备注、账户、金额、日期、类型都算 */
function matchesQuery(record, query) {
  if (!query) {
    return true;
  }
  const text = [
    record.category,
    record.note,
    record.account,
    record.to_account,
    String(record.amount),
    String(record.fee || 0),
    displayDate(record.date),
    TYPE_LABELS[record.type] || "",
  ]
    .join(" ")
    .toLowerCase();
  return text.indexOf(query) !== -1;
}

/** 首页「全部账单」表格用的数据：账户筛选由后端做，搜索在本地做 */
function filteredRecords() {
  const query = state.searchQuery.trim().toLowerCase();
  return state.allRecords.filter(function (record) {
    return matchesQuery(record, query);
  });
}

/* ---------- 近 7 天分组卡片 ---------- */

/** 在 YYYY-MM-DD 上加减天数，返回同样格式。不碰时区，纯字符串进 / 字符串出 */
function shiftDateKey(dateKey, delta) {
  const parts = dateKey.split("-").map(Number);
  const date = new Date(parts[0], parts[1] - 1, parts[2]);
  date.setDate(date.getDate() + delta);
  return (
    date.getFullYear() + "-" + pad2(date.getMonth() + 1) + "-" + pad2(date.getDate())
  );
}

function weekdayText(dateKey) {
  const parts = dateKey.split("-").map(Number);
  const names = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
  return names[new Date(parts[0], parts[1] - 1, parts[2]).getDay()];
}

/** 近 7 天里的一条账单（点击整行 → 详情弹窗） */
function recentRowHtml(record) {
  const timeText = displayDate(record.date).slice(11) || "00:00";
  const note = record.note
    ? '<span class="recent-note">' + escapeHtml(record.note) + "</span>"
    : "";
  return (
    '<button class="recent-row" type="button" data-id="' +
    record.id +
    '">' +
    '<span class="recent-meta">' +
    '<span class="recent-time">' +
    escapeHtml(timeText) +
    "</span>" +
    '<span class="recent-label">' +
    categoryLabel(record) +
    "</span>" +
    note +
    "</span>" +
    '<span class="recent-amount">' +
    amountCellHtml(record) +
    "</span>" +
    "</button>"
  );
}

/** 近 7 天账单：按天分组，今天 / 昨天优先，日期新的在上 */
function renderRecentGroups() {
  const box = $("recent-groups");
  if (!box) {
    return;
  }

  const query = state.searchQuery.trim().toLowerCase();
  const todayKey = todayText();
  const startKey = shiftDateKey(todayKey, -6);
  const yesterdayKey = shiftDateKey(todayKey, -1);

  const recent = state.calendarRecords.filter(function (record) {
    const key = dateKeyOf(record);
    return key >= startKey && key <= todayKey && matchesQuery(record, query);
  });

  const groups = [];
  const index = {};
  recent.forEach(function (record) {
    const key = dateKeyOf(record);
    if (!index[key]) {
      index[key] = { key: key, records: [] };
      groups.push(index[key]);
    }
    index[key].records.push(record);
  });
  groups.sort(function (a, b) {
    return b.key.localeCompare(a.key);
  });

  if ($("recent-summary")) {
    $("recent-summary").textContent = query
      ? "搜索「" + state.searchQuery.trim() + "」命中的近 7 天账单"
      : "近 7 天共 " + recent.length + " 笔，点任意一条看详情";
  }

  if (!groups.length) {
    box.innerHTML = emptyBlockHtml(
      query ? "近 7 天没有匹配的账单" : "近 7 天还没有记账，点右上角「+ 记一笔」"
    );
    return;
  }

  box.innerHTML = groups
    .map(function (group) {
      const summary = summarize(group.records);
      let dayLabel;
      if (group.key === todayKey) {
        dayLabel = "今天";
      } else if (group.key === yesterdayKey) {
        dayLabel = "昨天";
      } else {
        dayLabel = group.key.slice(5).replace("-", " 月 ") + " 日";
      }

      const rows = group.records
        .slice()
        .sort(function (a, b) {
          return String(displayDate(b.date)).localeCompare(String(displayDate(a.date)));
        })
        .map(recentRowHtml)
        .join("");

      return (
        '<section class="recent-group">' +
        '<div class="recent-group-head">' +
        '<span class="recent-day">' +
        dayLabel +
        "<em>" +
        group.key.slice(5) +
        " " +
        weekdayText(group.key) +
        "</em></span>" +
        '<span class="recent-day-total">支 ' +
        money(summary.expense) +
        " / 收 " +
        money(summary.income) +
        "</span>" +
        "</div>" +
        '<div class="recent-rows">' +
        rows +
        "</div>" +
        "</section>"
      );
    })
    .join("");
}

/** 数据都拉回来之后，一次性刷新三栏看板 */
function renderDashboard() {
  renderHero();
  renderBudget();
  renderCharts();
  renderRecentGroups();
  renderFab();
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

/**
 * v0.06.2：表格里的一行。整行可点 → 弹出「账单详情」，
 * 行末不再有实心黄 / 红的编辑删除按钮（痛点：满屏刺眼按钮 + 容易误触）。
 */
function recordRowHtml(record) {
  return (
    '<tr data-id="' +
    record.id +
    '" tabindex="0">' +
    '<td class="col-time">' +
    escapeHtml(displayDate(record.date)) +
    "</td>" +
    '<td class="col-type">' +
    (TYPE_BADGES[record.type] || TYPE_BADGES.expense) +
    "</td>" +
    "<td>" +
    categoryLabel(record) +
    "</td>" +
    '<td class="col-account">' +
    escapeHtml(record.account) +
    "</td>" +
    '<td class="text-end col-amount">' +
    amountCellHtml(record) +
    "</td>" +
    '<td class="note-cell" title="' +
    (record.note ? escapeHtml(record.note) : "") +
    '">' +
    (record.note ? escapeHtml(record.note) : "-") +
    "</td>" +
    "</tr>"
  );
}

/* ---------- 分页 / 滚动加载（v0.06.3） ---------- */

/** 每页条数：localStorage 里只认 20 / 50 / 100 / 0（0 = 不分页）；没存过就是 20 */
function readPageSize() {
  const raw = localStorage.getItem(LS_PAGE_SIZE);
  if (raw === null || raw === "") {
    return 20;
  }
  const saved = Number(raw);
  return PAGE_SIZE_OPTIONS.indexOf(saved) >= 0 ? saved : 20;
}

/** 搜索 / 切账户 / 换每页条数后回到第一页 */
function resetPaging() {
  state.pageIndex = 1;
  state.renderedCount = state.pageSize === 0 ? INFINITE_STEP : 0;
}

function pageCountOf(total) {
  if (!state.pageSize) {
    return 1;
  }
  return Math.max(1, Math.ceil(total / state.pageSize));
}

/** 页码按钮：首页、末页、当前页 ±1，中间用 … 省略 */
function pageButtonsHtml(pageCount) {
  const current = state.pageIndex;
  const wanted = [1, current - 1, current, current + 1, pageCount];
  const pages = [];
  wanted.forEach(function (number) {
    if (number >= 1 && number <= pageCount && pages.indexOf(number) === -1) {
      pages.push(number);
    }
  });
  pages.sort(function (a, b) {
    return a - b;
  });

  let html =
    '<button class="pager-btn" type="button" data-page="' +
    (current - 1) +
    '"' +
    (current <= 1 ? " disabled" : "") +
    ' aria-label="上一页">‹</button>';

  let previous = 0;
  pages.forEach(function (number) {
    if (previous && number - previous > 1) {
      html += '<span class="pager-ellipsis">…</span>';
    }
    html +=
      '<button class="pager-btn' +
      (number === current ? " is-active" : "") +
      '" type="button" data-page="' +
      number +
      '" aria-current="' +
      (number === current ? "page" : "false") +
      '">' +
      number +
      "</button>";
    previous = number;
  });

  html +=
    '<button class="pager-btn" type="button" data-page="' +
    (current + 1) +
    '"' +
    (current >= pageCount ? " disabled" : "") +
    ' aria-label="下一页">›</button>';

  return html;
}

function renderPager(total) {
  const info = $("pager-info");
  const pages = $("pager-pages");
  const sizeSelect = $("page-size");
  if (sizeSelect && Number(sizeSelect.value) !== state.pageSize) {
    sizeSelect.value = String(state.pageSize);
  }
  if (!info || !pages) {
    return;
  }

  // 一条都没有：只留「共 0 笔」，别摆一个空的第 1/1 页出来
  if (!total) {
    info.textContent = "共 0 笔";
    pages.innerHTML = "";
    return;
  }

  if (!state.pageSize) {
    const shown = Math.min(state.renderedCount, total);
    info.textContent =
      "共 " +
      total +
      " 笔 · 已展示 " +
      shown +
      " 笔" +
      (shown < total ? "（滚动到底自动加载）" : "");
    pages.innerHTML = "";
    return;
  }

  const pageCount = pageCountOf(total);
  state.pageIndex = Math.min(Math.max(1, state.pageIndex), pageCount);
  const start = total ? (state.pageIndex - 1) * state.pageSize + 1 : 0;
  const end = Math.min(total, state.pageIndex * state.pageSize);
  info.textContent =
    "共 " +
    total +
    " 笔 · 第 " +
    start +
    "–" +
    end +
    " 条 · " +
    state.pageIndex +
    "/" +
    pageCount +
    " 页";
  pages.innerHTML = pageButtonsHtml(pageCount);
}

function sentinelText(rendered, total) {
  const left = Math.max(0, total - rendered);
  return left
    ? "继续往下滚，自动加载剩余 " + left + " 条…"
    : "已经到底啦，共 " + total + " 笔";
}

function sentinelRowHtml(rendered, total) {
  return (
    '<tr class="sentinel-row"><td colspan="6" class="sentinel-cell" id="scroll-sentinel">' +
    sentinelText(rendered, total) +
    "</td></tr>"
  );
}

let recordObserver = null;

function stopRecordObserver() {
  if (recordObserver) {
    recordObserver.disconnect();
    recordObserver = null;
  }
}

/** 不分页模式：监听表格底部的哨兵行，进入视口就追加 20 条 */
function observeScrollSentinel() {
  const sentinel = $("scroll-sentinel");
  if (!sentinel || !("IntersectionObserver" in window)) {
    return;
  }
  stopRecordObserver();
  recordObserver = new IntersectionObserver(
    function (entries) {
      const hit = entries.some(function (entry) {
        return entry.isIntersecting;
      });
      if (hit) {
        appendMoreRecords();
      }
    },
    { rootMargin: "180px 0px", threshold: 0 }
  );
  recordObserver.observe(sentinel);
}

/**
 * 滚动兜底：某些环境（老浏览器 / 隐藏容器）IntersectionObserver 不触发，
 * 就在 scroll 事件里按哨兵行的位置判断一次，保证「滚到底自动加载」一定生效。
 */
function maybeAppendOnScroll() {
  if (state.pageSize !== 0) {
    return;
  }
  const sentinel = $("scroll-sentinel");
  if (!sentinel) {
    return;
  }
  const rect = sentinel.getBoundingClientRect();
  const viewport =
    window.innerHeight || document.documentElement.clientHeight || 0;
  if (viewport > 0 && rect.top - viewport < 160 && rect.bottom > -160) {
    appendMoreRecords();
  }
}

/** 追加下一批 20 条：只往表格尾部插，不重建已有行 */
function appendMoreRecords() {
  if (state.pageSize !== 0) {
    return;
  }
  const records = filteredRecords();
  const total = records.length;
  if (state.renderedCount >= total) {
    return;
  }
  const sentinel = $("scroll-sentinel");
  if (!sentinel) {
    return;
  }

  const nextCount = Math.min(total, state.renderedCount + INFINITE_STEP);
  const rowsHtml = records
    .slice(state.renderedCount, nextCount)
    .map(recordRowHtml)
    .join("");
  state.renderedCount = nextCount;

  const row = sentinel.closest("tr");
  if (row) {
    row.insertAdjacentHTML("beforebegin", rowsHtml);
    sentinel.textContent = sentinelText(nextCount, total);
  }

  renderPager(total);
  if (state.renderedCount >= total) {
    stopRecordObserver();
  }
}

function renderRecords() {
  const tbody = $("record-list");
  if (!tbody) {
    return;
  }

  // 搜索词在本地过滤，账户筛选已经由后端做过
  const records = filteredRecords();
  const query = state.searchQuery.trim();
  const total = records.length;

  if (!total) {
    stopRecordObserver();
    state.renderedCount = 0;
    tbody.innerHTML = query
      ? emptyStateHtml(6, "没有匹配「" + escapeHtml(query) + "」的账单，换个关键词试试")
      : emptyStateHtml(6, "还没有记录，点右上角「+ 记一笔」开始吧");
    renderPager(0);
    return;
  }

  // 不分页：先渲染 20 条，之后交给 IntersectionObserver 追加
  if (!state.pageSize) {
    state.renderedCount = Math.min(
      Math.max(state.renderedCount, INFINITE_STEP),
      total
    );
    tbody.innerHTML =
      records
        .slice(0, state.renderedCount)
        .map(recordRowHtml)
        .join("") + sentinelRowHtml(state.renderedCount, total);
    renderPager(total);
    observeScrollSentinel();
    return;
  }

  // 分页：只渲染当前页
  stopRecordObserver();
  const pageCount = pageCountOf(total);
  state.pageIndex = Math.min(Math.max(1, state.pageIndex), pageCount);
  const start = (state.pageIndex - 1) * state.pageSize;
  tbody.innerHTML = records
    .slice(start, start + state.pageSize)
    .map(recordRowHtml)
    .join("");
  renderPager(total);
}

/** 账户流水的一行（5 列：时间 / 类型 / 分类 / 金额 / 备注） */
function accountRowHtml(record) {
  return (
    '<tr data-id="' +
    record.id +
    '" tabindex="0">' +
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
    '<td class="note-cell" title="' +
    (record.note ? escapeHtml(record.note) : "") +
    '">' +
    (record.note ? escapeHtml(record.note) : "-") +
    "</td>" +
    "</tr>"
  );
}

function renderAccountRecords() {
  const tbody = $("account-records");
  if (!tbody) {
    return;
  }

  if (!state.detailRecords.length) {
    tbody.innerHTML = emptyStateHtml(5, "这个账户还没有流水");
    return;
  }

  tbody.innerHTML = state.detailRecords.map(accountRowHtml).join("");
}

async function loadRecords() {
  const finish = beginTableLoad($("record-list"), 6);
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
  const finish = beginTableLoad($("account-records"), 5);
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

/** 日历「当日明细」一行（4 列：时间 / 分类 / 金额 / 备注） */
function listRowHtml(record) {
  return (
    '<td class="col-time">' +
    escapeHtml(displayDate(record.date)) +
    "</td>" +
    "<td>" +
    categoryLabel(record) +
    "</td>" +
    '<td class="text-end col-amount">' +
    amountCellHtml(record) +
    "</td>" +
    '<td class="note-cell" title="' +
    (record.note ? escapeHtml(record.note) : "") +
    '">' +
    (record.note ? escapeHtml(record.note) : "-") +
    "</td>"
  );
}

function renderDayRecords(records, emptyText) {
  const tbody = $("day-records");
  if (!tbody) {
    return;
  }

  if (!records.length) {
    tbody.innerHTML = emptyStateHtml(4, emptyText);
    return;
  }

  // 同一天的账单按时间正序，看起来更符合直觉
  tbody.innerHTML = records
    .slice()
    .sort(function (a, b) {
      return String(displayDate(a.date)).localeCompare(String(displayDate(b.date)));
    })
    .map(function (record) {
      return '<tr data-id="' + record.id + '" tabindex="0">' + listRowHtml(record) + "</tr>";
    })
    .join("");
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
// v0.06.2：透明度上限压到 0.35。底色最深处也只是浅浅一层，
// 深色文字在任何格子上都看得清，不再出现「底色一深就把字刷白」的混搭。
const HEAT_MIN_ALPHA = 0.1;
const HEAT_MAX_ALPHA = 0.35;

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
  return {
    alpha: HEAT_MIN_ALPHA + (HEAT_MAX_ALPHA - HEAT_MIN_ALPHA) * ratio,
    rgb: HEAT_RGB[amount > 0 ? "plus" : "minus"],
  };
}

/** 把热力色刷到格子 / 年卡上。文字颜色始终交给 CSS（收绿、支红、结余深灰），不随底色反转 */
function paintHeat(cell, net, peak) {
  const tone = heatTone(net, peak);
  if (!tone) {
    return;
  }
  cell.classList.add("has-heat");
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
  } else if (type === "debt") {
    const contactId = Number($("contact-select").value);
    values.contact_id = Number.isFinite(contactId) && contactId > 0 ? contactId : null;
    values.debt_type = document.querySelector('input[name="debt-direction"]:checked').value;
    if (!values.contact_id) {
      issues.push({
        field: $("contact-select"),
        message: state.contacts.length
          ? "请选择联系人"
          : "还没有联系人，先去「我的 → 通讯录」添加一个",
      });
    }
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

/* ==================== 通讯录与借贷（v0.07 Step 2） ==================== */

let contactModal = null;
let editingContactId = null;
let pendingConfirmKey = "";

/** 危险操作不用 confirm 弹窗：第一次点给提示，3 秒内再点一次才真删 */
function askConfirm(key, message) {
  if (pendingConfirmKey === key) {
    pendingConfirmKey = "";
    return true;
  }
  pendingConfirmKey = key;
  toast(message + "，3 秒内再点一次确认", "error");
  window.setTimeout(function () {
    if (pendingConfirmKey === key) {
      pendingConfirmKey = "";
    }
  }, 3000);
  return false;
}

function contactById(contactId) {
  const id = Number(contactId);
  return state.contacts.find(function (contact) {
    return Number(contact.id) === id;
  }) || null;
}

function fillContactSelect() {
  const select = $("contact-select");
  if (!select) {
    return;
  }
  const keep = select.value;
  if (!state.contacts.length) {
    select.innerHTML = '<option value="">还没有联系人，先去「我的 → 通讯录」添加</option>';
    return;
  }
  select.innerHTML = state.contacts
    .map(function (contact) {
      const suffix = contact.identity ? " · " + escapeHtml(contact.identity) : "";
      return '<option value="' + contact.id + '">' + escapeHtml(contact.name) + suffix + "</option>";
    })
    .join("");
  if (keep) {
    select.value = keep;
  }
}

function renderContacts() {
  const list = $("contacts-list");
  if (!list) {
    return;
  }
  if (!state.contacts.length) {
    list.innerHTML = '<div class="empty-cell">通讯录还是空的，点上方「+ 新增联系人」把常来往的人记下来。</div>';
    $("contact-detail").innerHTML = '<div class="empty-cell">新增联系人后，这里会显示你们之间的借贷明细。</div>';
    return;
  }
  if (!contactById(state.selectedContactId)) {
    state.selectedContactId = state.contacts[0].id;
  }
  list.innerHTML = state.contacts
    .map(function (contact) {
      const active = Number(contact.id) === Number(state.selectedContactId);
      return (
        '<button type="button" class="contact-item' + (active ? " is-active" : "") +
        '" data-contact-id="' + contact.id + '">' +
        '<span class="contact-avatar">' + escapeHtml(String(contact.name || "?").slice(0, 1)) + "</span>" +
        '<span class="contact-main">' +
        '<span class="contact-name">' + escapeHtml(contact.name) + "</span>" +
        '<span class="contact-sub">' + escapeHtml(contact.identity || "未填写关系") + "</span>" +
        "</span>" +
        '<span class="contact-count">' + (contact.debt_count || 0) + " 笔</span>" +
        "</button>"
      );
    })
    .join("");
  renderContactDetail();
}

async function loadContacts() {
  try {
    const data = await api("/api/contacts");
    state.contacts = data.contacts || [];
  } catch (error) {
    state.contacts = [];
    toast("通讯录加载失败：" + error.message, "error");
  }
  fillContactSelect();
  renderContacts();
}

function debtRowHtml(debt) {
  const lend = debt.type === "lend";
  const paid = debt.status === "paid";
  return (
    '<div class="debt-row' + (paid ? " is-paid" : "") + '">' +
    '<div class="debt-main">' +
    '<span class="debt-dir ' + (lend ? "is-lend" : "is-borrow") + '">' + (lend ? "借出" : "借入") + "</span>" +
    '<span class="debt-amount">' + (lend ? "-" : "+") + money(debt.amount) + "</span>" +
    '<span class="debt-meta">' + escapeHtml(debt.date || "") + " · " + escapeHtml(debt.account || "") + "</span>" +
    '<span class="debt-status">' + (paid ? "已结清" : "未结清") + "</span>" +
    "</div>" +
    '<div class="debt-actions">' +
    '<button type="button" class="btn btn-light btn-sm" data-debt-action="toggle" data-debt-id="' + debt.id +
    '" data-debt-status="' + (paid ? "unpaid" : "paid") + '">' + (paid ? "撤销结清" : "标记结清") + "</button>" +
    '<button type="button" class="btn btn-outline-danger btn-sm" data-debt-action="delete" data-debt-id="' + debt.id +
    '">删除</button>' +
    "</div>" +
    "</div>"
  );
}

async function renderContactDetail() {
  const box = $("contact-detail");
  if (!box) {
    return;
  }
  const contact = contactById(state.selectedContactId);
  if (!contact) {
    box.innerHTML = '<div class="empty-cell">选中一个联系人，这里会显示你们之间的借贷明细。</div>';
    return;
  }
  box.innerHTML =
    '<div class="contact-head">' +
    '<div class="contact-head-main">' +
    '<span class="contact-avatar is-lg">' + escapeHtml(String(contact.name || "?").slice(0, 1)) + "</span>" +
    "<div>" +
    '<h3 class="contact-name-lg">' + escapeHtml(contact.name) + "</h3>" +
    '<p class="contact-meta">' + escapeHtml(contact.identity || "未填写关系") +
    (contact.phone ? " · 电话 " + escapeHtml(contact.phone) : "") +
    (contact.wechat ? " · 微信 " + escapeHtml(contact.wechat) : "") +
    "</p>" +
    "</div>" +
    "</div>" +
    '<div class="contact-head-actions">' +
    '<button type="button" class="btn btn-light btn-sm" data-contact-action="edit">编辑</button>' +
    '<button type="button" class="btn btn-outline-danger btn-sm" data-contact-action="delete">删除</button>' +
    "</div>" +
    "</div>" +
    '<div class="contact-debts"><div class="empty-cell">正在加载借贷记录…</div></div>';

  let debts = [];
  try {
    const data = await api("/api/debts?contact_id=" + encodeURIComponent(contact.id));
    debts = data.debts || [];
  } catch (error) {
    toast(error.message, "error");
  }
  // 用户可能在请求期间切到了别人，过期响应直接丢掉
  if (Number(state.selectedContactId) !== Number(contact.id)) {
    return;
  }
  const hold = box.querySelector(".contact-debts");
  if (!hold) {
    return;
  }
  if (!debts.length) {
    hold.innerHTML = '<div class="empty-cell">还没有和 TA 的借贷记录，点「记一笔 → 借贷」就能记上。</div>';
    return;
  }
  let receivable = 0;
  let payable = 0;
  debts.forEach(function (debt) {
    if (debt.status === "paid") {
      return;
    }
    if (debt.type === "lend") {
      receivable += Number(debt.amount) || 0;
    } else {
      payable += Number(debt.amount) || 0;
    }
  });
  hold.innerHTML =
    '<div class="debt-summary">' +
    '<span>待收 <b class="is-lend">' + money(receivable) + "</b></span>" +
    '<span>待还 <b class="is-borrow">' + money(payable) + "</b></span>" +
    '<span>合计 <b>' + money(receivable - payable) + "</b></span>" +
    "</div>" +
    debts.map(debtRowHtml).join("");
}

function openContactModal(contact) {
  editingContactId = contact ? contact.id : null;
  $("contact-modal-title").textContent = contact ? "编辑联系人" : "新增联系人";
  $("contact-name").value = contact ? contact.name : "";
  $("contact-identity").value = contact ? contact.identity || "" : "";
  $("contact-phone").value = contact ? contact.phone || "" : "";
  $("contact-wechat").value = contact ? contact.wechat || "" : "";
  clearFormErrors($("contact-modal"));
  if (!contactModal) {
    contactModal = new window.bootstrap.Modal($("contact-modal"));
  }
  contactModal.show();
  window.setTimeout(function () {
    $("contact-name").focus();
  }, 200);
}

async function saveContact() {
  const name = $("contact-name").value.trim();
  if (!name) {
    $("contact-name").classList.add("is-invalid");
    toast("联系人姓名不能为空", "error");
    return;
  }
  const payload = {
    name: name,
    identity: $("contact-identity").value.trim(),
    phone: $("contact-phone").value.trim(),
    wechat: $("contact-wechat").value.trim(),
  };
  const button = $("contact-save-btn");
  setButtonBusy(button, true, "保存中…");
  try {
    let saved = null;
    if (editingContactId) {
      saved = await api("/api/contacts/" + editingContactId, jsonOptions("PUT", payload));
      toast("联系人已更新", "success");
    } else {
      saved = await api("/api/contacts", jsonOptions("POST", payload));
      toast("联系人已添加", "success");
    }
    if (saved && saved.id) {
      state.selectedContactId = saved.id;
    }
    if (contactModal) {
      contactModal.hide();
    }
    await loadContacts();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setButtonBusy(button, false);
  }
}

async function deleteContact(contactId) {
  const contact = contactById(contactId);
  if (!contact) {
    return;
  }
  if (!askConfirm("contact-" + contactId, "删除联系人「" + contact.name + "」？")) {
    return;
  }
  try {
    await api("/api/contacts/" + contactId, { method: "DELETE" });
    toast("联系人已删除", "success");
    if (Number(state.selectedContactId) === Number(contactId)) {
      state.selectedContactId = null;
    }
    await loadContacts();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function toggleDebtStatus(debtId, status) {
  try {
    await api("/api/debts/" + debtId, jsonOptions("PUT", { status: status }));
    toast(status === "paid" ? "已标记结清" : "已撤销结清", "success");
    await loadContacts();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function deleteDebt(debtId) {
  if (!askConfirm("debt-" + debtId, "删除这条借贷记录？账户余额会一起退回")) {
    return;
  }
  try {
    await api("/api/debts/" + debtId, { method: "DELETE" });
    toast("借贷记录已删除，余额已回滚", "success");
    // refresh 会重新拉账户，资产页和首页余额一起回到删除后的值
    await refresh();
  } catch (error) {
    toast(error.message, "error");
  }
}

/** 借贷保存：POST /api/debts，后端在同一事务里改账户余额 */
async function saveDebt(values) {
  if (!lockAction("record-save")) {
    return;
  }
  const button = $("save-btn");
  setButtonBusy(button, true, "保存中…");
  const payload = {
    contact_id: values.contact_id,
    amount: values.amount,
    type: values.debt_type,
    account: values.account,
  };
  if (values.date) {
    payload.date = values.date;
  }
  try {
    await api("/api/debts", jsonOptions("POST", payload));
    toast(values.debt_type === "lend" ? "已借出，资金账户余额已扣减" : "已借入，资金账户余额已增加", "success");
    closeRecordModal();
    // refresh 内部已经包含 loadContacts，借贷条数也会一起刷新
    await refresh();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    setButtonBusy(button, false);
    unlockAction("record-save");
  }
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
  $("debt-lend").checked = true;
  fillContactSelect();
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
  // 借贷走 /api/debts 且自己加锁，必须在 records 的并发锁之前分流
  if (check.values.type === "debt") {
    await saveDebt(check.values);
    return;
  }

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
      // 新账目按时间倒序排在第一页，回到首页才看得见
      resetPaging();
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

/* ==================== 账单详情弹窗（v0.06.2） ==================== */

/** 从任意一份缓存里找账单：首页表格 / 账户流水 / 日历 / 近 7 天共用 */
function findRecordById(recordId) {
  const pools = [state.allRecords, state.detailRecords, state.calendarRecords];
  for (let i = 0; i < pools.length; i += 1) {
    const found = pools[i].find(function (item) {
      return item.id === recordId;
    });
    if (found) {
      return found;
    }
  }
  return null;
}

function detailRowHtml(key, valueHtml, extraClass) {
  return (
    '<span class="detail-key">' +
    key +
    "</span>" +
    '<span class="detail-val' +
    (extraClass ? " " + extraClass : "") +
    '">' +
    valueHtml +
    "</span>"
  );
}

/** 详情弹窗的正文：一条账单的全部字段 */
function buildDetailBody(record) {
  const amount = cents(record.amount);
  const sign = record.type === "income" ? "+" : record.type === "expense" ? "-" : "";
  let amountClass = "";
  if (record.type === "income") {
    amountClass = "is-plus";
  } else if (record.type === "expense") {
    amountClass = "is-minus";
  }

  let html = "";
  html += detailRowHtml("类型", TYPE_BADGES[record.type] || "-");
  html += detailRowHtml("金额", sign + money(amount), "is-amount " + amountClass);
  html += detailRowHtml("分类", categoryLabel(record));
  html += detailRowHtml("账户", escapeHtml(record.account || "-"));
  if (record.type === "transfer") {
    html += detailRowHtml("转入", escapeHtml(record.to_account || "-"));
    html += detailRowHtml("手续费", money(record.fee || 0));
  }
  html += detailRowHtml("时间", escapeHtml(displayDate(record.date)));
  html += detailRowHtml("备注", record.note ? escapeHtml(record.note) : "—");
  html += detailRowHtml("编号", "#" + record.id);
  html += '<span class="detail-tip">按 Esc 关闭，按 Enter 直接编辑这条账单</span>';
  return html;
}

function openRecordDetail(recordId) {
  const record = findRecordById(Number(recordId));
  if (!record) {
    toast("找不到这条账单，可能已经被删除了", "error");
    return;
  }
  state.detailRecordId = record.id;
  if ($("detail-body")) {
    $("detail-body").innerHTML = buildDetailBody(record);
  }
  if ($("record-detail-title")) {
    $("record-detail-title").textContent = "账单详情 #" + record.id;
  }
  if (recordDetailModal) {
    recordDetailModal.show();
  }
}

function closeRecordDetail() {
  if (recordDetailModal) {
    recordDetailModal.hide();
  }
}

/** Enter / 点「编辑」：关掉详情，直接进记账弹窗的编辑态 */
function editFromDetail() {
  const record = state.detailRecordId ? findRecordById(state.detailRecordId) : null;
  if (!record) {
    return;
  }
  closeRecordDetail();
  openRecordModal({ record: record });
}

function deleteFromDetail() {
  const recordId = state.detailRecordId;
  if (!recordId) {
    return;
  }
  // 先收起详情再确认，避免两层遮罩叠在一起
  closeRecordDetail();
  removeRecord(recordId);
}

/** 表格整行点击 → 详情；行内真有按钮时让它自己处理 */
function onRowClick(event) {
  if (event.target.closest("button, a, input, select, label")) {
    return;
  }
  const row = event.target.closest("tr[data-id]");
  if (!row) {
    return;
  }
  openRecordDetail(row.getAttribute("data-id"));
}

/** 键盘可达性：行有 tabindex，Enter / 空格也能打开详情 */
function onRowKeydown(event) {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  const row = event.target.closest("tr[data-id]");
  if (!row || event.target !== row) {
    return;
  }
  event.preventDefault();
  openRecordDetail(row.getAttribute("data-id"));
}

/** 近 7 天卡片列表：整条按钮就是一行账单 */
function onRecentClick(event) {
  const row = event.target.closest(".recent-row[data-id]");
  if (!row) {
    return;
  }
  openRecordDetail(row.getAttribute("data-id"));
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

  // 首页从隐藏变回可见时 ECharts 需要重新量一次容器宽度
  if (target === "home") {
    window.setTimeout(resizeCharts, 40);
  }
}

/* ==================== 主题（深色模式） ==================== */

function readTheme() {
  const saved = localStorage.getItem(LS_THEME);
  if (saved === "dark" || saved === "light") {
    return saved;
  }
  // 没存过就跟随系统
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function applyTheme(theme) {
  const dark = theme === "dark";
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  localStorage.setItem(LS_THEME, dark ? "dark" : "light");

  const moon = document.querySelector(".icon-moon");
  const sun = document.querySelector(".icon-sun");
  if (moon) {
    moon.classList.toggle("d-none", dark);
  }
  if (sun) {
    sun.classList.toggle("d-none", !dark);
  }

  // 提示文案统一用中性的「切换深色 / 浅色模式」（见 index.html），
  // 这里绝不 dispose / 重建 Tooltip：淡出过程中销毁实例会让 Bootstrap 的
  // _activeTrigger 变成 undefined，残留回调再调 _isWithActiveTrigger 就抛 TypeError。

  // 图表配色跟着换肤（还没初始化过就什么都不做，等 renderDashboard 再画）
  if (pieChart || trendChart) {
    renderCharts();
  }
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") === "dark";
  applyTheme(current ? "light" : "dark");
}

/* ==================== 侧栏折叠 ==================== */

function readSidebarPref() {
  const saved = localStorage.getItem(LS_SIDEBAR);
  return saved === "collapsed" || saved === "expanded" ? saved : "";
}

/** 用户手动选过就听用户的；没选过则 <1200px 自动收成纯图标 */
function applySidebar() {
  const pref = readSidebarPref();
  const collapsed = pref ? pref === "collapsed" : window.innerWidth < 1200;
  const app = $("app");
  if (app) {
    app.classList.toggle("is-collapsed", collapsed);
  }
  const button = $("sidebar-toggle");
  if (button) {
    button.setAttribute("aria-expanded", collapsed ? "false" : "true");
  }
}

function toggleSidebar() {
  const app = $("app");
  if (!app) {
    return;
  }
  const collapsed = app.classList.contains("is-collapsed");
  localStorage.setItem(LS_SIDEBAR, collapsed ? "expanded" : "collapsed");
  applySidebar();
}

/* ==================== 全局搜索 ==================== */

function onSearchInput() {
  const input = $("global-search");
  state.searchQuery = input ? input.value || "" : "";
  resetPaging();
  renderRecords();
  renderRecentGroups();
}

/* ==================== 预算 ==================== */

function editBudget() {
  const input = window.prompt("设置本月预算上限（元）", String(cents(state.budget)));
  if (input === null) {
    return;
  }
  const value = Number(String(input).trim());
  if (!Number.isFinite(value) || value <= 0) {
    toast("预算要填一个大于 0 的数字", "error");
    return;
  }
  state.budget = cents(value);
  localStorage.setItem(LS_BUDGET, String(state.budget));
  renderBudget();
  toast("本月预算已改为 " + money(state.budget), "success");
}

/* ==================== 右下角悬浮球（预算剩余 + 快捷键） ==================== */

let fabCloseTimer = null;

function renderFab() {
  const summary = summarize(currentMonthRecords());
  const spent = summary.expense;
  const limit = state.budget;
  const left = cents(limit - spent);
  const ratio = limit > 0 ? Math.min(1, spent / limit) : 0;

  if ($("fab-left")) {
    $("fab-left").textContent = money(left);
    $("fab-left").classList.toggle("is-negative", left < 0);
  }
  if ($("fab-spent")) {
    $("fab-spent").textContent = money(spent) + " / " + money(limit);
  }
  const fill = $("fab-fill");
  if (fill) {
    fill.style.width = Math.round(ratio * 100) + "%";
  }
  const fab = $("fab");
  if (fab) {
    fab.classList.toggle("is-over", spent > limit);
  }
}

function openFab() {
  const fab = $("fab");
  if (!fab) {
    return;
  }
  window.clearTimeout(fabCloseTimer);
  renderFab();
  fab.classList.add("is-open");
  if ($("fab-ball")) {
    $("fab-ball").setAttribute("aria-expanded", "true");
  }
  if ($("fab-panel")) {
    $("fab-panel").setAttribute("aria-hidden", "false");
  }
}

function closeFab() {
  const fab = $("fab");
  if (!fab || !fab.classList.contains("is-open")) {
    return;
  }
  fab.classList.remove("is-open");
  if ($("fab-ball")) {
    $("fab-ball").setAttribute("aria-expanded", "false");
  }
  if ($("fab-panel")) {
    $("fab-panel").setAttribute("aria-hidden", "true");
  }
}

/** 鼠标移出后留一点缓冲，方便从球滑进面板 */
function scheduleCloseFab() {
  window.clearTimeout(fabCloseTimer);
  fabCloseTimer = window.setTimeout(closeFab, 220);
}

function toggleFab() {
  const fab = $("fab");
  if (!fab) {
    return;
  }
  if (fab.classList.contains("is-open")) {
    closeFab();
  } else {
    openFab();
  }
}

/* ---------- 全局快捷键：N 记一笔、Ctrl + K 搜索 ---------- */

function isTypingTarget(target) {
  if (!target || !target.tagName) {
    return false;
  }
  const tag = String(target.tagName).toUpperCase();
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    target.isContentEditable === true
  );
}

function onGlobalKeydown(event) {
  const key = String(event.key || "").toLowerCase();

  // Ctrl / ⌘ + K：不管焦点在哪都跳到全局搜索
  if ((event.ctrlKey || event.metaKey) && key === "k") {
    event.preventDefault();
    const search = $("global-search");
    if (search) {
      search.focus();
      search.select();
    }
    return;
  }

  if (event.key === "Escape") {
    closeCtxMenu();
    if ($("fab")) {
      closeFab();
    }
  }

  if (event.ctrlKey || event.metaKey || event.altKey || isTypingTarget(event.target)) {
    return;
  }

  // N：记一笔（有弹窗开着就不抢，避免叠出第二个框）
  if (key === "n" && !document.querySelector(".modal.show")) {
    event.preventDefault();
    openRecordModal();
  }
}

/* ==================== 通知中心 ==================== */

function readReadIds() {
  try {
    const raw = JSON.parse(localStorage.getItem(LS_NOTIFY_READ) || "[]");
    return Array.isArray(raw) ? raw : [];
  } catch (error) {
    return [];
  }
}

function saveReadIds(ids) {
  // 只留最近 200 个，防止 localStorage 越攒越大
  localStorage.setItem(LS_NOTIFY_READ, JSON.stringify(ids.slice(-200)));
}

/**
 * 通知正文允许富文本（/admin 的编辑器产出），渲染前过一遍白名单：
 * 去掉 script / iframe / 事件属性 / javascript: 链接。
 */
function sanitizeNoticeHtml(html) {
  const text = String(html || "");
  if (!text) {
    return "";
  }
  const doc = new DOMParser().parseFromString("<div>" + text + "</div>", "text/html");
  const root = doc.body.firstChild;
  if (!root) {
    return "";
  }
  root
    .querySelectorAll("script, style, iframe, object, embed, link, meta, form, input, button")
    .forEach(function (node) {
      node.remove();
    });
  root.querySelectorAll("*").forEach(function (node) {
    Array.prototype.slice.call(node.attributes).forEach(function (attr) {
      const name = String(attr.name || "").toLowerCase();
      const value = String(attr.value || "").replace(/\s+/g, "").toLowerCase();
      if (name.indexOf("on") === 0) {
        node.removeAttribute(attr.name);
      } else if ((name === "href" || name === "src") && value.indexOf("javascript:") === 0) {
        node.removeAttribute(attr.name);
      }
    });
  });
  return root.innerHTML;
}

function notificationsUnreadCount() {
  const readIds = readReadIds();
  return (state.notifications || []).filter(function (item) {
    return readIds.indexOf(item.id) === -1;
  }).length;
}

function updateNotifyDot() {
  const dot = $("notify-dot");
  if (!dot) {
    return;
  }
  dot.classList.toggle("d-none", notificationsUnreadCount() === 0);
}

function renderNotifications() {
  const box = $("notification-list");
  if (!box) {
    return;
  }
  const list = state.notifications || [];
  if (!list.length) {
    box.innerHTML = emptyBlockHtml("还没有通知，管理员在 /admin 发布后会出现在这里");
    return;
  }

  const readIds = readReadIds();
  box.innerHTML = list
    .map(function (item) {
      const isNew = readIds.indexOf(item.id) === -1;
      const dateText = item.publish_date ? String(item.publish_date).slice(0, 16) : "";
      const content = sanitizeNoticeHtml(item.content);
      const cover = item.image_url
        ? '<img class="notice-cover" src="' +
          escapeHtml(item.image_url) +
          '" alt="通知配图" loading="lazy">'
        : "";

      return (
        '<article class="notice-item' +
        (isNew ? " is-new" : "") +
        '">' +
        '<div class="notice-item-head">' +
        '<span class="notice-title">' +
        escapeHtml(item.title) +
        "</span>" +
        '<span class="notice-date">' +
        escapeHtml(dateText) +
        "</span>" +
        "</div>" +
        (content ? '<div class="notice-content">' + content + "</div>" : "") +
        cover +
        "</article>"
      );
    })
    .join("");
}

async function loadNotifications() {
  try {
    const data = await api("/api/notifications");
    state.notifications = data.notifications || [];
  } catch (error) {
    state.notifications = [];
  }
  renderNotifications();
  updateNotifyDot();
}

function openNotifications() {
  const panel = $("notification-panel");
  const backdrop = $("notification-backdrop");
  if (panel) {
    panel.classList.add("is-open");
    panel.setAttribute("aria-hidden", "false");
  }
  if (backdrop) {
    backdrop.classList.remove("d-none");
    window.requestAnimationFrame(function () {
      backdrop.classList.add("is-open");
    });
  }
  renderNotifications();
  markNotificationsRead();
}

function closeNotifications() {
  const panel = $("notification-panel");
  const backdrop = $("notification-backdrop");
  if (panel) {
    panel.classList.remove("is-open");
    panel.setAttribute("aria-hidden", "true");
  }
  if (backdrop) {
    backdrop.classList.remove("is-open");
    window.setTimeout(function () {
      backdrop.classList.add("d-none");
    }, 220);
  }
}

/** 打开面板就算已读：红点消失，localStorage 记住 */
function markNotificationsRead() {
  const readIds = readReadIds();
  (state.notifications || []).forEach(function (item) {
    if (readIds.indexOf(item.id) === -1) {
      readIds.push(item.id);
    }
  });
  saveReadIds(readIds);
  updateNotifyDot();
}

/* ==================== 全站 Tooltip ==================== */

function initTooltips() {
  if (!window.bootstrap || !bootstrap.Tooltip) {
    return;
  }
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (element) {
    if (bootstrap.Tooltip.getInstance(element)) {
      return;
    }
    // 契约要求：悬停 0.5s 才出现，移开很快就收
    new bootstrap.Tooltip(element, {
      delay: { show: 500, hide: 80 },
      trigger: "hover focus",
    });
  });
}

function notifyComingSoon(name) {
  toast(name + "功能还在开发中，后续版本见", "success");
}

/**
 * 点掉的按钮立刻把它的 Tooltip 收起来。
 * 不处理的话：hover 触发的浮窗要等 hide 延时（还叠了 Bootstrap 的淡出），
 * 用户点了按钮，浮窗会「卡」在页面上好几秒，还会盖住刚打开的弹窗。
 */
function hideTooltipOf(element) {
  if (!element || !element.closest || !window.bootstrap || !bootstrap.Tooltip) {
    return;
  }
  const trigger = element.closest('[data-bs-toggle="tooltip"]');
  if (!trigger) {
    return;
  }
  const instance = bootstrap.Tooltip.getInstance(trigger);
  // tip 为空 = 这个实例还没弹过 / 刚被 dispose 又重建，此时它内部的状态还没建好，
  // 直接调 hide() 会在 Bootstrap 里抛 TypeError，所以先看一眼再说
  if (!instance || !instance.tip) {
    return;
  }
  try {
    instance.hide();
  } catch (error) {
    // 浮窗已经没了就无所谓，绝不能因为收提示把按钮点击搞崩
  }
}

/* ==================== 刷新 ==================== */

async function refresh() {
  // 首页三栏都靠这几份数据，拉完一起重绘，避免主卡先渲染出 0 再跳数字
  await Promise.all([loadAccounts(), loadRecords(), loadCalendarRecords(), loadContacts()]);
  await refreshDetail();
  renderDashboard();
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
    resetPaging();
    loadRecords().catch(function (error) {
      toast(error.message, "error");
    });
  });

  // 分页：换每页条数 / 点页码
  if ($("page-size")) {
    $("page-size").addEventListener("change", function (event) {
      const size = Number(event.target.value);
      state.pageSize = PAGE_SIZE_OPTIONS.indexOf(size) >= 0 ? size : 20;
      localStorage.setItem(LS_PAGE_SIZE, String(state.pageSize));
      resetPaging();
      renderRecords();
      renderPager(filteredRecords().length);
    });
  }
  if ($("pager-pages")) {
    $("pager-pages").addEventListener("click", function (event) {
      const button = event.target.closest("[data-page]");
      if (!button || button.disabled) {
        return;
      }
      const pageCount = pageCountOf(filteredRecords().length);
      const page = Number(button.getAttribute("data-page"));
      if (!Number.isFinite(page)) {
        return;
      }
      state.pageIndex = Math.min(Math.max(1, page), pageCount);
      renderRecords();
    });
  }

  // 悬浮球：悬停展开、移出收起；点击也能开合（触屏友好）
  if ($("fab")) {
    $("fab").addEventListener("mouseenter", openFab);
    $("fab").addEventListener("mouseleave", scheduleCloseFab);
    if ($("fab-ball")) {
      $("fab-ball").addEventListener("click", function (event) {
        event.stopPropagation();
        toggleFab();
      });
    }
    document.addEventListener("click", function (event) {
      if ($("fab") && !$("fab").contains(event.target)) {
        closeFab();
      }
    });
  }

  // 全局快捷键（N 记一笔、Ctrl + K 搜索）
  document.addEventListener("keydown", onGlobalKeydown);

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

  // v0.06.2：表格里不再有编辑 / 删除按钮，改成「点整行 → 详情弹窗」
  ["record-list", "account-records", "day-records"].forEach(function (id) {
    const tbody = $(id);
    if (tbody) {
      tbody.addEventListener("click", onRowClick);
      tbody.addEventListener("keydown", onRowKeydown);
    }
  });

  // 右键菜单只绑主账单表；账户流水与当日明细保留浏览器默认菜单
  if ($("record-list")) {
    $("record-list").addEventListener("contextmenu", function (event) {
      const row = event.target.closest("tr[data-id]");
      if (!row) {
        return;
      }
      event.preventDefault();
      openCtxMenu(event, recordById(Number(row.getAttribute("data-id"))));
    });
  }
  if ($("ctx-menu")) {
    $("ctx-menu").addEventListener("click", onCtxMenuClick);
    $("ctx-menu").addEventListener("keydown", function (event) {
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") {
        return;
      }
      event.preventDefault();
      const items = Array.prototype.slice.call(
        $("ctx-menu").querySelectorAll(".ctx-item")
      );
      const index = items.indexOf(document.activeElement);
      const next =
        event.key === "ArrowDown"
          ? (index + 1) % items.length
          : (index - 1 + items.length) % items.length;
      items[next].focus();
    });
  }
  // 点菜单外任意处 / 滚动页面 / 窗口失焦都收掉右键菜单
  document.addEventListener("click", function (event) {
    const menu = $("ctx-menu");
    if (menu && menu.classList.contains("is-open") && !event.target.closest("#ctx-menu")) {
      closeCtxMenu();
    }
  });
  window.addEventListener("scroll", closeCtxMenu, true);
  window.addEventListener("blur", closeCtxMenu);

  // 导出 CSV：顶栏与「我的」页两个入口共用一套下载逻辑
  ["export-btn", "export-btn-profile"].forEach(function (id) {
    const button = $(id);
    if (button) {
      button.addEventListener("click", function () {
        exportCsv(button);
      });
    }
  });

  // AI 快记：回车即提交一句话，后端解析成功会直接刷新看板与列表
  const aiForm = $("ai-quick-form");
  if (aiForm) {
    aiForm.addEventListener("submit", onAiQuickSubmit);
  }

  // 近 7 天卡片列表同样点一条弹详情
  if ($("recent-groups")) {
    $("recent-groups").addEventListener("click", onRecentClick);
  }

  // 详情弹窗底部两个幽灵按钮
  if ($("detail-edit-btn")) {
    $("detail-edit-btn").addEventListener("click", editFromDetail);
  }
  if ($("detail-delete-btn")) {
    $("detail-delete-btn").addEventListener("click", deleteFromDetail);
  }

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

  // 新增账户：先把「已有账户」排序列表按最新顺序重画，再开弹窗
  $("open-account-btn").addEventListener("click", function () {
    renderAccountSortList();
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

  /* ---------- v0.06.2 顶栏 / 侧栏 / 搜索 / 通知 / 预算 ---------- */

  if ($("theme-toggle")) {
    $("theme-toggle").addEventListener("click", toggleTheme);
  }

  if ($("sidebar-toggle")) {
    $("sidebar-toggle").addEventListener("click", toggleSidebar);
  }

  if ($("global-search")) {
    $("global-search").addEventListener("input", onSearchInput);
  }

  if ($("budget-edit-btn")) {
    $("budget-edit-btn").addEventListener("click", editBudget);
  }

  if ($("notification-btn")) {
    $("notification-btn").addEventListener("click", function () {
      openNotifications();
      // 打开时顺手拉一次最新，保证刚发布的通知能立刻看到
      loadNotifications().catch(function () {});
    });
  }
  if ($("notification-close")) {
    $("notification-close").addEventListener("click", closeNotifications);
  }
  if ($("notification-backdrop")) {
    $("notification-backdrop").addEventListener("click", closeNotifications);
  }

  // 侧栏底部两个占位图标
  if ($("sync-btn")) {
    $("sync-btn").addEventListener("click", function () {
      notifyComingSoon("云同步");
    });
  }
  if ($("settings-btn")) {
    $("settings-btn").addEventListener("click", function () {
      notifyComingSoon("设置");
    });
  }

  // 详情弹窗：Enter = 编辑（按钮 / 输入框自己的 Enter 不抢）
  const detailElement = $("record-detail-modal");
  if (detailElement) {
    detailElement.addEventListener("keydown", function (event) {
      if (event.key !== "Enter") {
        return;
      }
      const tag = String(event.target.tagName || "").toLowerCase();
      if (tag === "button" || tag === "textarea" || tag === "input" || tag === "select") {
        return;
      }
      event.preventDefault();
      editFromDetail();
    });
  }

  // Esc：先关通知面板（弹窗的 Esc 交给 Bootstrap data-bs-keyboard）
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") {
      return;
    }
    const panel = $("notification-panel");
    if (panel && panel.classList.contains("is-open")) {
      closeNotifications();
    }
  });

  // 窗口变窄 / 变宽：按 1200px 阈值自动折叠侧栏（用户手动选过则以用户为准），图表跟着重排
  window.addEventListener("resize", function () {
    applySidebar();
    resizeCharts();
  });

  // 不分页模式下，任何滚动容器滚动都检查一次哨兵行（IntersectionObserver 的兜底）
  window.addEventListener("scroll", maybeAppendOnScroll, true);

  // 点击任何带 Tooltip 的按钮：立刻收掉浮窗，绝不卡在屏幕上
  // 用捕获阶段，保证先收浮窗、再走按钮自己的逻辑（打开弹窗 / 切主题 / 折叠侧栏）
  document.addEventListener(
    "click",
    function (event) {
      hideTooltipOf(event.target);
      // 点击会让按钮获得焦点，hover/focus 触发可能在同一帧又把浮窗拉起来，收尾再收一次
      window.setTimeout(function () {
        hideTooltipOf(event.target);
      }, 0);
    },
    true
  );

  // 通讯录：展开 / 收起、新增、选中联系人、详情卡里的编辑与删除
  const toggleContacts = $("toggle-contacts-btn");
  if (toggleContacts) {
    toggleContacts.addEventListener("click", function () {
      const body = $("contacts-body");
      const collapsed = body.classList.toggle("d-none");
      toggleContacts.textContent = collapsed ? "查看通讯录" : "收起通讯录";
      if (!collapsed && !state.contacts.length) {
        loadContacts();
      }
    });
  }
  const addContact = $("add-contact-btn");
  if (addContact) {
    addContact.addEventListener("click", function () {
      $("contacts-body").classList.remove("d-none");
      if (toggleContacts) {
        toggleContacts.textContent = "收起通讯录";
      }
      openContactModal(null);
    });
  }
  const contactListBox = $("contacts-list");
  if (contactListBox) {
    contactListBox.addEventListener("click", function (event) {
      const item = event.target.closest("[data-contact-id]");
      if (!item) {
        return;
      }
      state.selectedContactId = Number(item.getAttribute("data-contact-id"));
      renderContacts();
    });
  }
  const contactDetailBox = $("contact-detail");
  if (contactDetailBox) {
    contactDetailBox.addEventListener("click", function (event) {
      const action = event.target.closest("[data-contact-action]");
      const debtButton = event.target.closest("[data-debt-action]");
      if (action) {
        const kind = action.getAttribute("data-contact-action");
        const contact = contactById(state.selectedContactId);
        if (!contact) {
          return;
        }
        if (kind === "edit") {
          openContactModal(contact);
        } else if (kind === "delete") {
          deleteContact(contact.id);
        }
        return;
      }
      if (debtButton) {
        const debtId = Number(debtButton.getAttribute("data-debt-id"));
        if (debtButton.getAttribute("data-debt-action") === "toggle") {
          toggleDebtStatus(debtId, debtButton.getAttribute("data-debt-status"));
        } else {
          deleteDebt(debtId);
        }
      }
    });
  }
  const contactSave = $("contact-save-btn");
  if (contactSave) {
    contactSave.addEventListener("click", saveContact);
  }
  $("contact-name").addEventListener("input", function () {
    clearFieldError($("contact-name"));
  });
  const contactElement = $("contact-modal");
  if (contactElement) {
    contactElement.addEventListener("hidden.bs.modal", function () {
      editingContactId = null;
      clearFormErrors(contactElement);
    });
  }
}

/* ==================== 版本 / 导出 / 网络 / 右键菜单（v0.06.3 终极补丁） ==================== */

let ctxRecordId = null;
let netBannerTimer = 0;

async function loadVersion() {
  try {
    const data = await api("/api/version");
    const version = String((data && data.version) || "").trim();
    if (!version) {
      return;
    }
    if ($("sidebar-version")) {
      $("sidebar-version").textContent = version + " · 开发中";
    }
    if ($("profile-version")) {
      $("profile-version").textContent = version;
    }
  } catch (error) {
    // 版本号读不到不影响任何功能，模板里的静态文字就是兜底
  }
}

/** AI 快记：一句话交给后端解析入库，成功后刷新看板与账单列表 */
async function onAiQuickSubmit(event) {
  event.preventDefault();
  const input = $("ai-quick-input");
  const button = $("ai-quick-btn");
  if (!input || !button) {
    return;
  }

  const text = input.value.trim();
  if (!text) {
    toast("先输入一句话，比如「昨天打车花了 30」", "error");
    input.focus();
    return;
  }
  if (button.disabled) {
    return;
  }

  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = "识别中";
  try {
    const data = await api("/api/records/ai", jsonOptions("POST", { text: text }));
    const record = (data && data.record) || {};
    const amount = Number(record.amount || 0);
    toast(
      "AI 已记账：" + (record.category || "未分类") + " ¥" + amount.toFixed(2),
      "success"
    );
    input.value = "";
    await refresh();
  } catch (error) {
    toast(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = originalLabel;
  }
}

/** 导出走 fetch + blob：接口报错时弹 Toast，而不是把整页导航到一段 JSON */
async function exportCsv(button) {
  const target = button || $("export-btn");
  if (target && target.disabled) {
    return;
  }
  if (target) {
    target.disabled = true;
  }
  try {
    const response = await fetch("/api/export");
    if (!response.ok) {
      throw new Error("导出失败（HTTP " + response.status + "）");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const stamp = new Date().toISOString().slice(0, 10);
    link.href = url;
    link.download = "AI记账管家-账单-" + stamp + ".csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 4000);
    toast("CSV 已开始下载（带 BOM，Excel 打开不乱码）", "success");
  } catch (error) {
    toast(error.message, "error");
  } finally {
    if (target) {
      target.disabled = false;
    }
  }
}

function showNetBanner(offline) {
  const banner = $("net-banner");
  if (!banner) {
    return;
  }
  window.clearTimeout(netBannerTimer);
  banner.classList.remove("is-visible", "is-offline", "is-online");
  banner.classList.add(offline ? "is-offline" : "is-online");
  banner.textContent = offline
    ? "网络已断开，看板数据暂时不会更新"
    : "网络已恢复，数据可以继续同步了";
  // 先撤掉 is-visible 再强制回流，断网→恢复这类连续切换才会重新播动画
  void banner.offsetWidth;
  banner.classList.add("is-visible");
  if (!offline) {
    netBannerTimer = window.setTimeout(function () {
      banner.classList.remove("is-visible");
    }, 2500);
  }
}

function watchNetwork() {
  window.addEventListener("offline", function () {
    showNetBanner(true);
  });
  window.addEventListener("online", function () {
    showNetBanner(false);
  });
  if (!navigator.onLine) {
    showNetBanner(true);
  }
}

function recordById(recordId) {
  return (state.allRecords || []).find(function (record) {
    return record.id === recordId;
  });
}

function openCtxMenu(event, record) {
  const menu = $("ctx-menu");
  if (!menu || !record) {
    return;
  }
  ctxRecordId = record.id;
  menu.classList.add("is-open");
  // 先量尺寸再定位：贴边弹出时整块翻到鼠标左侧/上方，不会被视口裁掉
  const rect = menu.getBoundingClientRect();
  const x = Math.min(event.clientX, window.innerWidth - rect.width - 12);
  const y = Math.min(event.clientY, window.innerHeight - rect.height - 12);
  menu.style.left = Math.max(12, x) + "px";
  menu.style.top = Math.max(12, y) + "px";

  const first = menu.querySelector(".ctx-item");
  if (first) {
    first.focus({ preventScroll: true });
  }
}

function closeCtxMenu() {
  const menu = $("ctx-menu");
  if (menu) {
    menu.classList.remove("is-open");
  }
  ctxRecordId = null;
}

function recordPlainText(record) {
  const typeLabel = TYPE_LABELS[record.type] || record.type;
  const category = record.parent_category
    ? record.parent_category + " / " + record.category
    : record.category;
  const amount = "¥" + Math.abs(Number(record.amount)).toFixed(2);
  const lines = [displayDate(record.date) + " · " + typeLabel];
  if (record.type === "transfer") {
    lines.push("转账：" + record.account + " → " + (record.to_account || ""));
    if (Number(record.fee)) {
      lines.push("手续费：¥" + Number(record.fee).toFixed(2));
    }
  } else {
    lines.push("分类：" + category);
    lines.push("账户：" + record.account);
  }
  lines.push((record.type === "income" ? "+" : "-") + amount);
  if (record.note) {
    lines.push("备注：" + record.note);
  }
  return lines.join("\n");
}

function copyRecordText(record) {
  const text = recordPlainText(record);
  const done = function () {
    toast("账单已复制到剪贴板", "success");
  };
  const fallback = function () {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (error) {
      ok = false;
    }
    area.remove();
    if (ok) {
      done();
    } else {
      toast("复制失败，浏览器不允许访问剪贴板", "error");
    }
  };

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(fallback);
  } else {
    fallback();
  }
}

function onCtxMenuClick(event) {
  const item = event.target.closest("[data-ctx-action]");
  if (!item || !ctxRecordId) {
    return;
  }
  const record = recordById(ctxRecordId);
  const action = item.getAttribute("data-ctx-action");
  closeCtxMenu();

  if (!record) {
    toast("这条账单已经不在了，刷新看看", "error");
    return;
  }
  if (action === "edit") {
    openRecordModal({ record: record });
  } else if (action === "copy") {
    copyRecordText(record);
  } else if (action === "delete") {
    removeRecord(record.id);
  }
}

function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) {
    return;
  }
  // file:// 打开时注册必然失败；只有 http(s) 才具备离线能力
  if (location.protocol !== "http:" && location.protocol !== "https:") {
    return;
  }
  const start = function () {
    navigator.serviceWorker
      .register("/service-worker.js", { scope: "/" })
      .catch(function () {
        // 离线缓存没装上不影响在线使用，静默处理
      });
  };
  // init 里拉首屏数据可能比 load 事件还慢，此时再等 load 就永远等不到了
  if (document.readyState === "complete") {
    start();
  } else {
    window.addEventListener("load", start);
  }
}

/* ==================== 启动 ==================== */

async function init() {
  const modalElement = $("record-modal");
  const accountElement = $("account-modal");
  const categoryElement = $("category-modal");
  const detailElement = $("record-detail-modal");
  if (window.bootstrap) {
    recordModal = new window.bootstrap.Modal(modalElement);
    accountModal = new window.bootstrap.Modal(accountElement);
    categoryModal = new window.bootstrap.Modal(categoryElement);
    if (detailElement) {
      recordDetailModal = new window.bootstrap.Modal(detailElement);
    }
    bindEscClose(modalElement, recordModal);
    bindEscClose(accountElement, accountModal);
    bindEscClose(categoryElement, categoryModal);
    if (detailElement && recordDetailModal) {
      bindEscClose(detailElement, recordDetailModal);
    }
  }

  // 主题 / 侧栏 / 预算 / 每页条数都从 localStorage 恢复，刷新页面不闪
  applyTheme(readTheme());
  state.budget = readBudget();
  state.pageSize = readPageSize();
  resetPaging();
  if ($("page-size")) {
    $("page-size").value = String(state.pageSize);
  }
  applySidebar();

  bindEvents();
  initTooltips();

  try {
    await loadCategories();
    await refresh();
  } catch (error) {
    toast(error.message, "error");
  }

  // 版本号 / 断网横幅 / Service Worker 都是「有就用」的能力，失败不能拦住看板
  loadVersion().catch(function () {});
  watchNetwork();
  registerServiceWorker();

  // 通知失败不该拦住整个看板，单独兜底
  loadNotifications().catch(function () {});

  switchPage("home");

  // manifest 快捷方式与 404 页的「去记一笔」都靠这个参数直达记账弹窗
  if (new URLSearchParams(window.location.search).get("action") === "new") {
    openRecordModal();
    window.history.replaceState(null, "", window.location.pathname);
  }
}

document.addEventListener("DOMContentLoaded", init);
