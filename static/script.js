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
    return { ok: false, message: "公式写错了：" + (error && error.message ? error.message : "无法计算") };
  }

  if (typeof result !== "number" || !Number.isFinite(result)) {
    return { ok: false, message: "公式算不出有效数字" };
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

  // 纯数字不用打扰用户，只在有运算符时才显示「= 56.00」
  if (!text || !looksLikeFormula(text)) {
    hint.textContent = "";
    hint.classList.remove("is-error");
    return;
  }

  const parsed = amountFromInput(text);
  if (parsed.ok) {
    hint.textContent = "= " + money(parsed.value);
    hint.classList.remove("is-error");
  } else {
    hint.textContent = parsed.message;
    hint.classList.add("is-error");
  }
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
  $("account-label").textContent = transfer ? "转出账户" : "账户";

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
    box.innerHTML = '<p class="empty-cell">还没有账户，点右上角「+ 新增账户」建一个</p>';
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
}

function clearDetail() {
  state.detailAccount = "";
  state.detailRecords = [];
  $("detail-title").textContent = "账户流水";
  $("quick-add-btn").disabled = true;
  $("account-records").innerHTML =
    '<tr><td colspan="6" class="empty-cell">先在上方点一个账户，这里会显示它的流水</td></tr>';
}

async function selectAccount(name) {
  state.detailAccount = name;
  $("detail-title").textContent = name + " · 流水";
  $("quick-add-btn").disabled = false;
  renderAccountGroups();

  const data = await api("/api/records?account=" + encodeURIComponent(name));
  state.detailRecords = data.records || [];
  renderAccountRecords();
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
    tbody.innerHTML =
      '<tr id="empty-row"><td colspan="7" class="empty-cell">还没有记录，点右上角「+ 记一笔」开始吧</td></tr>';
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
    tbody.innerHTML = '<tr><td colspan="6" class="empty-cell">这个账户还没有流水</td></tr>';
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
  const account = $("filter-account").value;
  const query = account ? "?account=" + encodeURIComponent(account) : "";
  const data = await api("/api/records" + query);
  state.allRecords = data.records || [];

  renderRecords();
  renderCalendar();
  renderCategoryTree();
}

async function refreshDetail() {
  if (!state.detailAccount) {
    return;
  }
  const data = await api("/api/records?account=" + encodeURIComponent(state.detailAccount));
  state.detailRecords = data.records || [];
  renderAccountRecords();
}

/* ==================== 日历 ==================== */

function renderCalendar() {
  const grid = $("calendar-grid");
  const title = $("calendar-title");
  grid.innerHTML = "";

  const today = new Date();
  const year = today.getFullYear();
  const month = today.getMonth();
  title.textContent = year + " 年 " + (month + 1) + " 月支出";

  // 每天的支出合计（转账不算支出，跳过）
  const daily = {};
  state.allRecords.forEach(function (record) {
    if (record.type !== "expense") {
      return;
    }
    const key = displayDate(record.date).slice(0, 10);
    daily[key] = (daily[key] || 0) + Number(record.amount || 0);
  });

  const firstDay = new Date(year, month, 1);
  // JS 里周日是 0，日历从周一开始，所以要 (getDay() + 6) % 7
  const lead = (firstDay.getDay() + 6) % 7;
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const todayKey = todayText();

  let cellIndex = 0;
  for (let i = 0; i < lead; i += 1) {
    const cell = document.createElement("div");
    cell.className = "cal-cell is-empty";
    grid.appendChild(cell);
    cellIndex += 1;
  }

  for (let day = 1; day <= daysInMonth; day += 1) {
    const pad = String(day).padStart(2, "0");
    const key = year + "-" + String(month + 1).padStart(2, "0") + "-" + pad;
    const cell = document.createElement("div");
    cell.className = "cal-cell" + (key === todayKey ? " is-today" : "");

    const total = daily[key] || 0;
    cell.innerHTML =
      '<div class="cal-day">' +
      day +
      "</div>" +
      (total > 0 ? '<div class="cal-sum">' + money(total) + "</div>" : "");
    grid.appendChild(cell);
    cellIndex += 1;
  }

  // 补空格子，让最后一行也是整整齐齐的 7 列
  while (cellIndex % 7 !== 0) {
    const cell = document.createElement("div");
    cell.className = "cal-cell is-empty";
    grid.appendChild(cell);
    cellIndex += 1;
  }
}

/* ==================== 记账弹窗 ==================== */

function resetRecordForm() {
  state.editingId = null;
  state.presetAccount = "";
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
  const parsed = amountFromInput($("amount").value);
  if (!parsed.ok) {
    toast(parsed.message, "error");
    $("amount").focus();
    return;
  }

  const account = $("account").value;
  if (!account) {
    toast("请先选一个账户", "error");
    return;
  }

  const payload = {
    amount: parsed.value,
    formula: parsed.formula,
    account: account,
    type: currentType(),
    note: $("note").value.trim(),
  };

  const dateValue = $("record-time").value;
  if (dateValue) {
    payload.date = dateValue;
  }

  if (payload.type === "transfer") {
    const toAccount = $("to-account").value;
    if (!toAccount) {
      toast("请选择转入账户", "error");
      return;
    }
    if (toAccount === account) {
      toast("转出账户和转入账户不能是同一个", "error");
      return;
    }
    const feeText = String($("fee").value || "").trim();
    const fee = Number(feeText === "" ? 0 : feeText);
    if (!Number.isFinite(fee) || fee < 0) {
      toast("手续费必须是不小于 0 的数字", "error");
      return;
    }
    payload.to_account = toAccount;
    payload.fee = cents(fee);
  } else {
    const categoryId = selectedCategoryId();
    if (!categoryId) {
      toast("请选择分类", "error");
      return;
    }
    payload.category_id = categoryId;
  }

  const button = $("save-btn");
  button.disabled = true;
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
    button.disabled = false;
  }
}

async function removeRecord(recordId) {
  if (!window.confirm("确定删除这条记录吗？删除后余额会一起退回去。")) {
    return;
  }
  try {
    await api("/api/records/" + recordId, { method: "DELETE" });
    toast("已删除", "success");
    await refresh();
  } catch (error) {
    toast(error.message, "error");
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
  const name = $("new-category-name").value.trim();
  if (!name) {
    toast("请填写分类名称", "error");
    return;
  }
  const parentValue = $("new-category-parent").value;
  const payload = { name: name };
  if (parentValue) {
    payload.parent_id = Number(parentValue);
  }

  try {
    await api("/api/categories", jsonOptions("POST", payload));
    $("new-category-name").value = "";
    toast("分类已添加", "success");
    await loadCategories();
    await loadRecords();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function removeCategory(categoryId) {
  if (!window.confirm("删除这个分类？有子分类或已有账目时不允许删。")) {
    return;
  }
  try {
    await api("/api/categories/" + categoryId, { method: "DELETE" });
    toast("分类已删除", "success");
    await loadCategories();
    await loadRecords();
  } catch (error) {
    toast(error.message, "error");
  }
}

/* ==================== 账户增删 ==================== */

async function addAccount() {
  const name = $("new-account-name").value.trim();
  if (!name) {
    toast("请填写账户名称", "error");
    return;
  }
  const group = $("new-account-group").value;
  const balanceText = String($("new-account-balance").value || "").trim();
  const balance = Number(balanceText === "" ? 0 : balanceText);
  if (!Number.isFinite(balance)) {
    toast("初始余额必须是数字", "error");
    return;
  }

  try {
    await api(
      "/api/accounts",
      jsonOptions("POST", { name: name, group_name: group, balance: cents(balance) })
    );
    $("new-account-name").value = "";
    $("new-account-balance").value = "0";
    toast("账户已添加", "success");
    if (accountModal) {
      accountModal.hide();
    }
    await refresh();
  } catch (error) {
    toast(error.message, "error");
  }
}

async function removeAccount(name) {
  if (!window.confirm("删除账户「" + name + "」？账户下还有账目时不允许删。")) {
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
  await Promise.all([loadStatistics(), loadAccounts(), loadRecords()]);
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

  // 记账弹窗关掉时复位，免得下次打开还带着上次的编辑态
  const modalElement = $("record-modal");
  if (modalElement) {
    modalElement.addEventListener("hidden.bs.modal", resetRecordForm);
  }

  // 列表里的编辑 / 删除（事件委托，动态行也能响应）
  $("record-list").addEventListener("click", onRecordListClick);
  $("account-records").addEventListener("click", onRecordListClick);

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
