/* ============================================================
   AI记账管家 · 前端业务逻辑
   ------------------------------------------------------------
   只做三件事：
   1. 把后端接口拿到的数据填进页面（卡片 / 表格 / 资产页 / 日历）
   2. 把用户操作（记一笔 / 编辑 / 删除 / 改余额）变成对应的接口请求
   3. 每次写操作成功后重新拉一次数据，做到「不刷新页面数字也变」
   ============================================================ */

/* ---------------- 全局状态 ---------------- */

// null = 新增；数字 = 正在编辑的那条记录的 id
let editingId = null;

// 最近一次拉到的账目，日历页和编辑回填都从这里取，避免再请求一次
let allRecords = [];

// Bootstrap 弹窗实例，第一次用时才创建
let recordModal = null;

// 侧边栏菜单对应的页面标题
const PAGE_TITLES = { home: "首页", calendar: "日历", assets: "资产", profile: "我的" };

/* ---------------- 小工具 ---------------- */

function $(id) {
  return document.getElementById(id);
}

// 数字 -> "¥12.30" / "-¥773.23"（负号放在最前面，不是 ¥-773）
function money(value) {
  const num = Number(value) || 0;
  const sign = num < 0 ? "-" : "";
  return sign + "¥" + Math.abs(num).toFixed(2);
}

// 带收支符号的金额：收入 +¥ / 支出 -¥
function signedMoney(amount, type) {
  const abs = Math.abs(Number(amount) || 0).toFixed(2);
  return (type === "income" ? "+¥" : "-¥") + abs;
}

// "2026-10-25 00:00" -> "2026-10-25 00:00"；顺带把可能出现的 T 换成空格
function displayDate(value) {
  return String(value || "").replace("T", " ");
}

// "2026-10-25 00:00" -> "2026-10-25T00:00"（datetime-local 只认这种格式）
function toInputValue(value) {
  const text = String(value || "").replace(" ", "T");
  return text.length >= 16 ? text.slice(0, 16) : text;
}

// 客户端当前时间，格式和 datetime-local 对齐
function nowInputValue() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return (
    d.getFullYear() +
    "-" + pad(d.getMonth() + 1) +
    "-" + pad(d.getDate()) +
    "T" + pad(d.getHours()) +
    ":" + pad(d.getMinutes())
  );
}

// 拼 HTML 时把用户输入转义，避免备注里带 < > 把表格撑坏
function escapeHtml(text) {
  return String(text == null ? "" : text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// 读当前选中的收支类型
function currentType() {
  const checked = document.querySelector('input[name="record-type"]:checked');
  return checked ? checked.value : "expense";
}

// 设置收支类型（编辑回填时用）
function setType(type) {
  const el = $("type-" + (type === "income" ? "income" : "expense"));
  if (el) {
    el.checked = true;
  }
}

// 下拉框里没有这个值就临时补一项，否则 select.value = xxx 会静默失败
function ensureOption(select, value) {
  if (!select || !value) return;
  const exists = Array.prototype.some.call(select.options, function (opt) {
    return opt.value === value;
  });
  if (exists) return;

  const opt = document.createElement("option");
  opt.value = value;
  opt.textContent = value;
  opt.setAttribute("data-temp", "1");
  select.appendChild(opt);
}

// 清掉临时补的项，避免编辑一条「卫浴」之后下拉框里永远多一个「卫浴」
function clearTempOptions(select) {
  if (!select) return;
  const temps = select.querySelectorAll('option[data-temp="1"]');
  Array.prototype.forEach.call(temps, function (opt) {
    opt.remove();
  });
}

/* ---------------- 数据加载 ---------------- */

// 三张统计卡片
async function loadStatistics() {
  const res = await fetch("/api/statistics");
  const data = await res.json();

  $("stat-income").textContent = money(data.income_total);
  $("stat-expense").textContent = money(data.expense_total);

  const balanceEl = $("stat-balance");
  const balance = Number(data.balance_total) || 0;
  balanceEl.textContent = money(balance);
  // 余额为负时变红，其他情况回到主题蓝
  balanceEl.classList.toggle("text-danger", balance < 0);
  balanceEl.classList.toggle("text-primary", balance >= 0);
}

// 账户列表：资产页的表格 + 两个下拉框的选项一起更新
async function loadAccounts() {
  const res = await fetch("/api/accounts");
  const data = await res.json();
  const accounts = data.accounts || [];

  renderAccountRows(accounts);
  syncAccountOptions(accounts.map((a) => a.name));
}

// 资产页：每个账户一行，带一个输入框和一个保存按钮
function renderAccountRows(accounts) {
  const tbody = $("account-list");
  if (!tbody) return;

  if (!accounts.length) {
    tbody.innerHTML = '<tr><td colspan="3" class="empty-cell">还没有账户</td></tr>';
    return;
  }

  tbody.innerHTML = accounts
    .map(function (account) {
      const name = escapeHtml(account.name);
      const negative = Number(account.balance) < 0;
      return (
        '<tr>' +
        '<td class="fw-semibold">' + name + "</td>" +
        '<td class="text-end ' + (negative ? "text-danger" : "text-body") + '">' +
        money(account.balance) +
        "</td>" +
        '<td class="text-end">' +
        '<div class="balance-editor">' +
        '<input class="form-control form-control-sm balance-input" type="number" step="0.01" ' +
        'data-account="' + name + '" value="' + (Number(account.balance) || 0).toFixed(2) + '">' +
        '<button class="btn btn-sm btn-outline-primary" data-save-account="' + name + '">保存</button>' +
        "</div>" +
        "</td>" +
        "</tr>"
      );
    })
    .join("");
}

// 用真实的账户名重建两个下拉框，尽量保留用户当前选中的值
function syncAccountOptions(names) {
  const selects = [$("account"), $("filter-account")];
  selects.forEach(function (select) {
    if (!select) return;
    const previous = select.value;

    // 清空后重建：第一个选项是「全部账户」（只有筛选框有）
    const keepCurrent = select.id === "filter-account";
    const first = keepCurrent ? '<option value="">全部账户</option>' : "";
    select.innerHTML =
      first +
      names
        .map(function (name) {
          const safe = escapeHtml(name);
          return '<option value="' + safe + '">' + safe + "</option>";
        })
        .join("");

    if (previous && (names.indexOf(previous) >= 0 || keepCurrent)) {
      select.value = previous;
    }
  });
}

// 账单列表（支持按账户筛选）
async function loadRecords() {
  const filter = $("filter-account");
  const account = filter ? filter.value : "";
  const url = account
    ? "/api/records?account=" + encodeURIComponent(account)
    : "/api/records";

  const res = await fetch(url);
  const data = await res.json();
  allRecords = data.records || [];

  renderRecords(allRecords, account);
  renderCalendar(allRecords);
}

// 表格主体
function renderRecords(records, account) {
  const tbody = $("record-list");
  if (!tbody) return;

  if (!records.length) {
    const text = account
      ? "「" + escapeHtml(account) + "」还没有记录"
      : "还没有记录，点右上角「+ 记一笔」开始吧";
    tbody.innerHTML = '<tr><td colspan="7" class="empty-cell">' + text + "</td></tr>";
    return;
  }

  tbody.innerHTML = records
    .map(function (record) {
      const isIncome = record.type === "income";
      return (
        '<tr data-id="' + record.id + '">' +
        '<td class="col-time">' + escapeHtml(displayDate(record.date)) + "</td>" +
        '<td><span class="badge ' + (isIncome ? "bg-success" : "bg-danger") + '">' +
        (isIncome ? "收入" : "支出") + "</span></td>" +
        "<td>" + escapeHtml(record.category) + "</td>" +
        "<td>" + escapeHtml(record.account) + "</td>" +
        '<td class="text-end col-amount ' + (isIncome ? "text-success" : "text-danger") + '">' +
        signedMoney(record.amount, record.type) + "</td>" +
        '<td class="note-cell">' + escapeHtml(record.note || "—") + "</td>" +
        '<td class="text-end">' +
        '<button class="btn btn-sm btn-outline-warning me-1" data-action="edit" data-id="' + record.id + '">编辑</button>' +
        '<button class="btn btn-sm btn-outline-danger" data-action="delete" data-id="' + record.id + '">删除</button>' +
        "</td>" +
        "</tr>"
      );
    })
    .join("");
}

// 日历：当月网格，每格写当天支出合计（数据直接复用 allRecords，不额外请求）
function renderCalendar(records) {
  const grid = $("calendar-grid");
  if (!grid) return;

  const today = new Date();
  const year = today.getFullYear();
  const month = today.getMonth(); // 0 = 一月
  const firstDay = new Date(year, month, 1);
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  // 周一作为一周第一天：getDay() 里周日是 0，换算成 0~6
  const lead = (firstDay.getDay() + 6) % 7;

  // 先按日期把支出加起来
  const dailyExpense = {};
  records.forEach(function (record) {
    if (record.type !== "expense") return;
    const day = String(record.date).slice(0, 10);
    dailyExpense[day] = (dailyExpense[day] || 0) + (Number(record.amount) || 0);
  });

  const pad = (n) => String(n).padStart(2, "0");
  const todayKey = year + "-" + pad(month + 1) + "-" + pad(today.getDate());

  const cells = [];
  for (let i = 0; i < lead; i++) {
    cells.push('<div class="cal-cell is-empty"></div>');
  }

  for (let day = 1; day <= daysInMonth; day++) {
    const key = year + "-" + pad(month + 1) + "-" + pad(day);
    const sum = dailyExpense[key];
    cells.push(
      '<div class="cal-cell' + (key === todayKey ? " is-today" : "") + '">' +
      '<span class="cal-day">' + day + "</span>" +
      (sum ? '<span class="cal-sum">' + money(-sum) + "</span>" : "") +
      "</div>"
    );
  }

  grid.innerHTML = cells.join("");
  $("calendar-title").textContent = year + " 年 " + (month + 1) + " 月支出";
}

/* ---------------- 弹窗 ---------------- */

function getRecordModal() {
  if (!recordModal && window.bootstrap) {
    recordModal = window.bootstrap.Modal.getOrCreateInstance($("record-modal"));
  }
  return recordModal;
}

function openRecordModal() {
  const modal = getRecordModal();
  if (modal) {
    modal.show();
  } else {
    alert("弹窗组件还没加载好，刷新一下页面再试");
  }
}

function closeRecordModal() {
  const modal = getRecordModal();
  if (modal) {
    modal.hide();
  }
}

// 把表单恢复成「新增」状态
function resetForm() {
  editingId = null;

  $("amount").value = "";
  $("note").value = "";
  setType("expense");
  clearTempOptions($("category"));
  clearTempOptions($("account"));
  $("record-time").value = nowInputValue();

  $("record-modal-title").textContent = "记一笔";
  $("save-btn").textContent = "保存";
}

// 点「编辑」：把这条记录回填到弹窗里，并切到「保存修改」模式
function startEdit(id) {
  const record = allRecords.filter(function (r) {
    return Number(r.id) === Number(id);
  })[0];
  if (!record) return;

  editingId = record.id;

  setType(record.type);
  $("amount").value = (Number(record.amount) || 0).toFixed(2);

  ensureOption($("category"), record.category);
  $("category").value = record.category;

  ensureOption($("account"), record.account);
  $("account").value = record.account;

  $("record-time").value = toInputValue(record.date);
  $("note").value = record.note || "";

  $("record-modal-title").textContent = "编辑记录 #" + record.id;
  $("save-btn").textContent = "保存修改";

  openRecordModal();
}

// 点「保存」：editingId 有值就 PUT，否则 POST
async function saveRecord() {
  const payload = {
    type: currentType(),
    amount: Number($("amount").value),
    category: $("category").value,
    account: $("account").value,
    date: $("record-time").value, // "2026-10-26T14:30"
    note: $("note").value.trim(),
  };

  // 只拦最明显的错误，详细规则以后端为准
  if (!payload.amount || payload.amount <= 0) {
    alert("金额必须是大于 0 的数字");
    return;
  }
  if (!payload.date) {
    alert("请选择时间");
    return;
  }

  const button = $("save-btn");
  const isEdit = editingId !== null;
  button.disabled = true;

  try {
    const res = await fetch(isEdit ? "/api/records/" + editingId : "/api/records", {
      method: isEdit ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(function () {
      return {};
    });

    if (!res.ok) {
      alert(data.error || "保存失败，请检查输入");
      return;
    }

    closeRecordModal();
    resetForm();
    await refresh(); // 不刷新页面，卡片和表格自己更新
  } catch (err) {
    console.error(err);
    alert("网络异常，保存失败");
  } finally {
    button.disabled = false;
  }
}

// 点「删除」
async function removeRecord(id) {
  const record = allRecords.filter(function (r) {
    return Number(r.id) === Number(id);
  })[0];
  const label = record ? displayDate(record.date) + " 的这条记录" : "这条记录";

  if (!confirm("确定删除" + label + "吗？删除后余额会一起回滚。")) {
    return;
  }

  const res = await fetch("/api/records/" + id, { method: "DELETE" });
  if (!res.ok) {
    const data = await res.json().catch(function () {
      return {};
    });
    alert(data.error || "删除失败");
    return;
  }

  await refresh();
}

// 资产页：把某个账户的余额改成输入框里的值
async function saveAccountBalance(name, button) {
  let input = null;
  const inputs = document.querySelectorAll(".balance-input");
  Array.prototype.forEach.call(inputs, function (el) {
    if (el.dataset.account === name) input = el;
  });
  if (!input) return;

  const balance = Number(input.value);
  if (input.value === "" || Number.isNaN(balance)) {
    alert("余额必须是数字");
    return;
  }

  button.disabled = true;
  button.textContent = "保存中…";

  try {
    const res = await fetch("/api/accounts/" + encodeURIComponent(name), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ balance: balance }),
    });
    const data = await res.json().catch(function () {
      return {};
    });

    if (!res.ok) {
      alert(data.error || "保存失败");
      button.disabled = false;
      button.textContent = "保存";
      return;
    }

    // 余额变了，总余额卡片也要跟着变
    await refresh();
  } catch (err) {
    console.error(err);
    alert("网络异常，保存失败");
    button.disabled = false;
    button.textContent = "保存";
  }
}

/* ---------------- 事件绑定 ---------------- */

// 侧边栏切页
function bindSidebar() {
  const items = document.querySelectorAll(".nav-item");

  Array.prototype.forEach.call(items, function (item) {
    item.addEventListener("click", function (event) {
      event.preventDefault();

      Array.prototype.forEach.call(items, function (other) {
        other.classList.remove("active");
      });
      item.classList.add("active");

      const page = item.dataset.page;
      Array.prototype.forEach.call(document.querySelectorAll(".page"), function (section) {
        section.classList.remove("active");
      });

      const target = $("page-" + page);
      if (target) target.classList.add("active");
      $("page-title").textContent = PAGE_TITLES[page] || "";
    });
  });
}

// 表格里的「编辑 / 删除」是动态生成的，用事件委托，绑一次就够
function onRecordListClick(event) {
  const target = event.target;
  if (!target || typeof target.closest !== "function") return;

  const button = target.closest("button[data-action]");
  if (!button) return;

  const id = Number(button.dataset.id);
  if (button.dataset.action === "edit") {
    startEdit(id);
  } else if (button.dataset.action === "delete") {
    removeRecord(id);
  }
}

// 资产页的「保存」同理，用事件委托
function onAccountListClick(event) {
  const target = event.target;
  if (!target || typeof target.closest !== "function") return;

  const button = target.closest("button[data-save-account]");
  if (!button) return;

  saveAccountBalance(button.dataset.saveAccount, button);
}

// 一次刷新：卡片 + 账户 + 账单（日历跟着账单走）
async function refresh() {
  await Promise.all([loadStatistics(), loadAccounts(), loadRecords()]);
}

function init() {
  bindSidebar();

  // 顶部「+ 记一笔」：只是打开弹窗，表单是空的
  const addButton = document.querySelector('[data-bs-target="#record-modal"]');
  if (addButton) {
    addButton.addEventListener("click", function () {
      if (editingId !== null) resetForm();
      $("record-modal-title").textContent = "记一笔";
      $("save-btn").textContent = "保存";
    });
  }

  $("save-btn").addEventListener("click", saveRecord);

  // 弹窗关掉（保存成功、取消、点遮罩、按 Esc）时都复位表单，避免下次带着上次的编辑状态
  $("record-modal").addEventListener("hidden.bs.modal", resetForm);

  $("record-list").addEventListener("click", onRecordListClick);
  $("account-list").addEventListener("click", onAccountListClick);

  const filter = $("filter-account");
  if (filter) {
    filter.addEventListener("change", loadRecords);
  }

  refresh().catch(function (err) {
    console.error(err);
  });
}

document.addEventListener("DOMContentLoaded", init);
