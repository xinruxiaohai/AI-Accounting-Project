/* =====================================================================
   AI记账管家 · 前端逻辑（v0.05）
   页面结构见 templates/index.html，样式见 static/style.css
   ===================================================================== */

/* ===================== 常量与小工具 ===================== */

// 四个页面的标题，切页时同步到顶部栏
const PAGE_TITLES = {
  home: "首页",
  calendar: "日历",
  assets: "资产",
  profile: "我的",
};

// 一个简写：$("#id") 比 document.getElementById 短
const $ = (selector) => document.querySelector(selector);

// 全局状态都放这里，避免到处散落变量
const state = {
  categories: [],      // 两级分类树：[{id, name, parent_id, children: []}]
  accounts: [],        // 账户平铺列表：[{name, balance, group_name}]
  groups: [],          // 账户按大类分组：[{name: "资金账户", accounts: []}]
  allRecords: [],      // 首页当前的账目（受筛选影响）
  editingId: null,     // 正在编辑的账目 id；null 表示新增
  detailAccount: null, // 资产页选中的账户名
  lockedAccount: null, // 快捷记账时锁定的账户名
};

// 编辑时按 id 找回原始记录，不用再去接口查一次
const recordCache = new Map();

// 金额显示：负数显示成 -¥12.30，而不是 ¥-12.30
function money(value) {
  const number = Number(value) || 0;
  const text = Math.abs(number).toFixed(2);
  return (number < 0 ? "-¥" : "¥") + text;
}

// 带正负号的金额：收入 +¥，支出 -¥
function signedMoney(amount, type) {
  const sign = type === "income" ? "+¥" : "-¥";
  return sign + Number(amount).toFixed(2);
}

// 时间统一显示成「YYYY-MM-DD HH:MM」
function displayDate(value) {
  return value ? String(value) : "";
}

// datetime-local 需要「YYYY-MM-DDTHH:MM」，库里存的是空格分隔，转换一下
function toInputValue(value) {
  return String(value || "").replace(" ", "T").slice(0, 16);
}

// 取「现在」并转成 datetime-local 的格式（用本地时区，不用 toISOString，否则差 8 小时）
function nowInputValue() {
  const now = new Date();
  const pad = (number) => String(number).padStart(2, "0");
  return (
    now.getFullYear() +
    "-" + pad(now.getMonth() + 1) +
    "-" + pad(now.getDate()) +
    "T" + pad(now.getHours()) +
    ":" + pad(now.getMinutes())
  );
}

// 备注、账户名可能有尖括号，塞进 innerHTML 前必须转义，否则会破坏结构
function escapeHtml(text) {
  return String(text == null ? "" : text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// 分类显示：二级分类显示成「餐饮 / 早餐」
function categoryLabel(record) {
  if (record.category_parent && record.category_parent !== record.category) {
    return record.category_parent + " / " + record.category;
  }
  return record.category || "";
}

// 记账弹窗里当前选的是收入还是支出
function currentType() {
  const checked = document.querySelector('input[name="record-type"]:checked');
  return checked ? checked.value : "expense";
}

// 反向操作：编辑时把类型按钮切到记录本来的类型
function setType(type) {
  const target = $("#" + (type === "income" ? "type-income" : "type-expense"));
  if (target) {
    target.checked = true;
  }
}

/* ===================== 请求封装 ===================== */

// 所有接口调用走这里：出错时后端会给 {error: "..."}，直接抛出来给调用方 alert
async function api(path, options) {
  const response = await fetch(path, options);
  let data = {};
  try {
    data = await response.json();
  } catch (error) {
    data = {};
  }
  if (!response.ok) {
    throw new Error(data.error || "请求失败（HTTP " + response.status + "）");
  }
  return data;
}

// POST / PUT 都发 JSON，这里统一带上请求头
function jsonOptions(method, body) {
  return {
    method: method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

/* ===================== 弹窗对象 ===================== */

// Bootstrap 的 bundle 已经加载过了，这里直接用它包一层
const recordModal = new bootstrap.Modal($("#record-modal"));
const accountModal = new bootstrap.Modal($("#account-modal"));
const categoryModal = new bootstrap.Modal($("#category-modal"));

/* ===================== 分类：级联下拉 + 分类树 ===================== */

// 把分类树填进「一级分类」下拉框，value 用分类 id
function fillCategoryParent() {
  const select = $("#category");
  const previous = select.value;
  select.innerHTML = state.categories
    .map((top) => `<option value="${top.id}">${escapeHtml(top.name)}</option>`)
    .join("");
  if (state.categories.some((top) => String(top.id) === previous)) {
    select.value = previous;
  }
  fillCategoryChild();
}

// 选了一级分类后，决定要不要显示二级下拉框
function fillCategoryChild() {
  const wrap = $("#sub-category-wrap");
  const select = $("#sub-category");
  const parent = state.categories.find(
    (top) => String(top.id) === $("#category").value
  );
  const children = parent ? parent.children : [];

  if (!children.length) {
    // 这个一级分类下面没有二级分类，把下拉框藏起来，提交时用一级分类 id
    wrap.classList.add("d-none");
    select.innerHTML = "";
    return;
  }

  const previous = select.value;
  wrap.classList.remove("d-none");
  select.innerHTML =
    '<option value="">不细分</option>' +
    children
      .map((child) => `<option value="${child.id}">${escapeHtml(child.name)}</option>`)
      .join("");
  if (children.some((child) => String(child.id) === previous)) {
    select.value = previous;
  }
}

// 当前选中的分类 id：优先二级，没有二级就用一级
function selectedCategoryId() {
  return Number($("#sub-category").value || $("#category").value);
}

// 分类管理弹窗：树形展示 + 每个节点一个删除按钮
function renderCategoryTree() {
  const tree = $("#category-tree");

  if (!state.categories.length) {
    tree.innerHTML = '<li class="empty-hint">还没有分类</li>';
  } else {
    tree.innerHTML = state.categories
      .map((top) => {
        const children = top.children.length
          ? `<ul>${top.children
              .map(
                (child) => `
            <li>
              <div class="category-row">
                <span>${escapeHtml(child.name)}</span>
                <button class="cat-del" type="button" data-del-category="${child.id}">删除</button>
              </div>
            </li>`
              )
              .join("")}</ul>`
          : "";
        const hint = top.children.length
          ? '<span class="tag-count">' + top.children.length + " 个子分类</span>"
          : '<span class="tag-count">一级分类</span>';
        return `
        <li>
          <div class="category-row">
            <span>${escapeHtml(top.name)}${hint}</span>
            <button class="cat-del" type="button" data-del-category="${top.id}">删除</button>
          </div>
          ${children}
        </li>`;
      })
      .join("");
  }

  // 新增表单里的「父级」下拉：留空 = 一级分类
  const parentSelect = $("#new-category-parent");
  parentSelect.innerHTML =
    '<option value="">作为一级分类</option>' +
    state.categories
      .map((top) => `<option value="${top.id}">${escapeHtml(top.name)}</option>`)
      .join("");
}

// 拉分类树，然后刷新级联下拉和分类管理弹窗
async function loadCategories() {
  const data = await api("/api/categories");
  state.categories = data.categories || [];
  fillCategoryParent();
  renderCategoryTree();
}

/* ===================== 账户：optgroup 下拉 + 卡片 ===================== */

// 生成 <optgroup> 分组的账户选项。withBalance=true 时在名字后面带上余额
function accountOptionsHtml(selected, withBalance) {
  const groups = state.groups.filter((group) => group.accounts.length);
  return groups
    .map((group) => {
      const options = group.accounts
        .map((account) => {
          const label = withBalance
            ? account.name + "（" + money(account.balance) + "）"
            : account.name;
          const isSelected = account.name === selected ? " selected" : "";
          return `<option value="${escapeHtml(account.name)}"${isSelected}>${escapeHtml(label)}</option>`;
        })
        .join("");
      return `<optgroup label="${escapeHtml(group.name)}">${options}</optgroup>`;
    })
    .join("");
}

// 重建记账弹窗里的账户下拉 + 首页的账户筛选下拉
function fillAccountSelects() {
  const recordSelect = $("#account");
  const keep = state.lockedAccount || recordSelect.value;
  recordSelect.innerHTML = accountOptionsHtml(keep, true);
  if (keep) {
    recordSelect.value = keep;
  }
  // 快捷记账时账户锁定，用户不能改
  recordSelect.disabled = Boolean(state.lockedAccount);

  const filter = $("#filter-account");
  const keepFilter = filter.value;
  filter.innerHTML =
    '<option value="">全部账户</option>' + accountOptionsHtml(keepFilter, false);
  if (keepFilter && state.accounts.some((account) => account.name === keepFilter)) {
    filter.value = keepFilter;
  }
}

// 资产页：按大类渲染账户卡片
function renderAccountGroups() {
  const box = $("#account-groups");

  if (!state.groups.length) {
    box.innerHTML = '<p class="empty-hint">还没有账户</p>';
    return;
  }

  box.innerHTML = state.groups
    .map((group) => {
      const total = group.accounts.reduce(
        (sum, account) => sum + Number(account.balance),
        0
      );
      const cards = group.accounts.length
        ? group.accounts
            .map(
              (account) => `
          <div class="account-card${account.name === state.detailAccount ? " active" : ""}" data-account="${escapeHtml(account.name)}">
            <button class="account-card-del" type="button" data-del-account="${escapeHtml(account.name)}" title="删除账户">×</button>
            <div class="account-card-name">${escapeHtml(account.name)}</div>
            <div class="account-card-balance${Number(account.balance) < 0 ? " text-danger" : ""}">${money(account.balance)}</div>
          </div>`
            )
            .join("")
        : '<p class="empty-hint">这一类还没有账户</p>';

      return `
      <div class="account-group">
        <div class="account-group-head">
          <span>${escapeHtml(group.name)}</span>
          <span class="account-group-total">${money(total)}</span>
        </div>
        <div class="account-cards">${cards}</div>
      </div>`;
    })
    .join("");
}

// 拉账户列表，刷新下拉框和资产页卡片
async function loadAccounts() {
  const data = await api("/api/accounts");
  state.accounts = data.accounts || [];
  state.groups = data.groups || [];

  // 选中的账户被删掉了，就把详情区复位
  if (state.detailAccount && !state.accounts.some((account) => account.name === state.detailAccount)) {
    state.detailAccount = null;
    $("#detail-title").textContent = "账户流水";
    $("#quick-add-btn").disabled = true;
    $("#account-records").innerHTML =
      '<tr><td colspan="6" class="empty-cell">先在上方点一个账户，这里会显示它的流水</td></tr>';
  }

  fillAccountSelects();
  renderAccountGroups();
}

/* ===================== 统计卡片 ===================== */

async function loadStatistics() {
  const data = await api("/api/statistics");

  $("#stat-income").textContent = money(data.income_total);
  $("#stat-expense").textContent = money(data.expense_total);

  // 总余额为负时用红色，提醒"欠着钱"
  const balance = Number(data.balance_total) || 0;
  const balanceNode = $("#stat-balance");
  balanceNode.textContent = money(balance);
  balanceNode.className = "stat-number " + (balance < 0 ? "text-danger" : "text-primary");
}

/* ===================== 账目：首页表格 + 资产页流水 ===================== */

// 首页表格的每一行
function renderRecords(records) {
  const tbody = $("#record-list");
  records.forEach((record) => recordCache.set(record.id, record));

  if (!records.length) {
    tbody.innerHTML =
      '<tr><td colspan="7" class="empty-cell">还没有记录，点右上角「+ 记一笔」开始吧</td></tr>';
    return;
  }

  tbody.innerHTML = records
    .map((record) => {
      const isIncome = record.type === "income";
      return `
      <tr data-id="${record.id}">
        <td class="col-time">${escapeHtml(displayDate(record.date))}</td>
        <td class="col-type"><span class="badge ${isIncome ? "bg-success" : "bg-danger"}">${isIncome ? "收入" : "支出"}</span></td>
        <td>${escapeHtml(categoryLabel(record))}</td>
        <td class="col-account">${escapeHtml(record.account)}</td>
        <td class="text-end col-amount ${isIncome ? "text-success" : "text-danger"}">${signedMoney(record.amount, record.type)}</td>
        <td class="note-cell">${escapeHtml(record.note || "")}</td>
        <td class="text-end col-action">
          <button class="btn btn-sm btn-link p-0 me-2" type="button" data-action="edit">编辑</button>
          <button class="btn btn-sm btn-link p-0 text-danger" type="button" data-action="delete">删除</button>
        </td>
      </tr>`;
    })
    .join("");
}

// 资产页下方的账户专属流水（没有"账户"列，因为整张表就是一个账户）
function renderAccountRecords(records) {
  const tbody = $("#account-records");
  records.forEach((record) => recordCache.set(record.id, record));

  if (!records.length) {
    tbody.innerHTML =
      '<tr><td colspan="6" class="empty-cell">这个账户还没有记录</td></tr>';
    return;
  }

  tbody.innerHTML = records
    .map((record) => {
      const isIncome = record.type === "income";
      return `
      <tr data-id="${record.id}">
        <td class="col-time">${escapeHtml(displayDate(record.date))}</td>
        <td class="col-type"><span class="badge ${isIncome ? "bg-success" : "bg-danger"}">${isIncome ? "收入" : "支出"}</span></td>
        <td>${escapeHtml(categoryLabel(record))}</td>
        <td class="text-end col-amount ${isIncome ? "text-success" : "text-danger"}">${signedMoney(record.amount, record.type)}</td>
        <td class="note-cell">${escapeHtml(record.note || "")}</td>
        <td class="text-end col-action">
          <button class="btn btn-sm btn-link p-0 me-2" type="button" data-action="edit">编辑</button>
          <button class="btn btn-sm btn-link p-0 text-danger" type="button" data-action="delete">删除</button>
        </td>
      </tr>`;
    })
    .join("");
}

// 拉首页账目（带账户筛选），同时刷新日历
async function loadRecords() {
  const account = $("#filter-account").value;
  const query = account ? "?account=" + encodeURIComponent(account) : "";
  const data = await api("/api/records" + query);

  state.allRecords = data.records || [];
  renderRecords(state.allRecords);
  renderCalendar(state.allRecords);
}

// 选中某个账户：卡片高亮 + 下方显示它的流水
async function selectAccount(name) {
  state.detailAccount = name;
  renderAccountGroups();

  $("#detail-title").textContent = name + " · 流水";
  $("#quick-add-btn").disabled = false;

  const data = await api("/api/records?account=" + encodeURIComponent(name));
  renderAccountRecords(data.records || []);
}

/* ===================== 日历 ===================== */

// 用当月每天的支出合计画网格，周一排第一
function renderCalendar(records) {
  const grid = $("#calendar-grid");
  const title = $("#calendar-title");
  const today = new Date();
  const year = today.getFullYear();
  const month = today.getMonth() + 1;
  const daysInMonth = new Date(year, month, 0).getDate();
  // JS 的 getDay() 里周日是 0，这里换算成「周一 = 0」
  const firstWeekday = (new Date(year, month - 1, 1).getDay() + 6) % 7;

  const sums = {};
  records.forEach((record) => {
    if (record.type !== "expense") {
      return; // 日历只统计支出
    }
    const text = String(record.date);
    if (Number(text.slice(0, 4)) === year && Number(text.slice(5, 7)) === month) {
      const day = Number(text.slice(8, 10));
      sums[day] = (sums[day] || 0) + Number(record.amount);
    }
  });

  title.textContent = year + " 年 " + month + " 月支出";

  const cells = [];
  for (let i = 0; i < firstWeekday; i += 1) {
    cells.push('<div class="cal-cell is-empty"></div>');
  }
  for (let day = 1; day <= daysInMonth; day += 1) {
    const isToday = day === today.getDate();
    const sum = sums[day];
    cells.push(`
      <div class="cal-cell${isToday ? " is-today" : ""}">
        <span class="cal-day">${day}</span>
        ${sum ? '<span class="cal-sum">' + money(-sum) + "</span>" : ""}
      </div>`);
  }
  // 补到 7 的倍数，最后一行不会缺角
  while (cells.length % 7 !== 0) {
    cells.push('<div class="cal-cell is-empty"></div>');
  }
  grid.innerHTML = cells.join("");
}

/* ===================== 记账弹窗 ===================== */

// 打开弹窗。options 可以带 {record} 进入编辑，或 {account} 锁定账户
function openRecordModal(options) {
  const settings = options || {};
  resetRecordForm();

  if (settings.record) {
    fillRecordForm(settings.record);
  }
  if (settings.account) {
    lockAccount(settings.account);
  }
  recordModal.show();
}

// 表单复位：新增状态
function resetRecordForm() {
  state.editingId = null;
  state.lockedAccount = null;

  $("#record-modal-title").textContent = "记一笔";
  $("#save-btn").textContent = "保存";
  $("#amount").value = "";
  $("#note").value = "";
  $("#record-time").value = nowInputValue();
  setType("expense");

  const accountSelect = $("#account");
  accountSelect.disabled = false;

  // 分类回到第一项
  if (state.categories.length) {
    $("#category").value = String(state.categories[0].id);
  }
  fillCategoryChild();
}

// 编辑时把记录回填到表单
function fillRecordForm(record) {
  state.editingId = record.id;

  $("#record-modal-title").textContent = "编辑记录 #" + record.id;
  $("#save-btn").textContent = "保存修改";
  $("#amount").value = record.amount;
  $("#note").value = record.note || "";
  $("#record-time").value = toInputValue(record.date);
  setType(record.type);

  // 二级分类：先选它的一级父级，再选它自己
  if (record.category_parent) {
    const parent = state.categories.find((top) => top.name === record.category_parent);
    if (parent) {
      $("#category").value = String(parent.id);
      fillCategoryChild();
      $("#sub-category").value = String(record.category_id);
    }
  } else if (record.category_id) {
    $("#category").value = String(record.category_id);
    fillCategoryChild();
  }

  const accountSelect = $("#account");
  accountSelect.value = record.account;
}

// 快捷记账：账户锁定成当前卡片
function lockAccount(name) {
  state.lockedAccount = name;
  const accountSelect = $("#account");
  accountSelect.value = name;
  accountSelect.disabled = true; // disabled 的 select 用户点不动，但 .value 还能正常读
}

// 保存：有 editingId 走 PUT，没有走 POST
async function saveRecord() {
  const amount = Number($("#amount").value);
  if (!amount || amount <= 0) {
    alert("请填写大于 0 的金额");
    return;
  }
  const account = $("#account").value;
  if (!account) {
    alert("请选择账户");
    return;
  }

  const payload = {
    amount: amount,
    category_id: selectedCategoryId(),
    account: account,
    type: currentType(),
    date: $("#record-time").value || nowInputValue(),
    note: $("#note").value.trim(),
  };

  const saveButton = $("#save-btn");
  saveButton.disabled = true;
  try {
    if (state.editingId) {
      await api("/api/records/" + state.editingId, jsonOptions("PUT", payload));
    } else {
      await api("/api/records", jsonOptions("POST", payload));
    }
    recordModal.hide();
    await refresh();
  } catch (error) {
    alert(error.message);
  } finally {
    saveButton.disabled = false;
  }
}

// 删除一条账目
async function removeRecord(recordId) {
  if (!confirm("确定删除这条记录吗？")) {
    return;
  }
  try {
    await api("/api/records/" + recordId, { method: "DELETE" });
    await refresh();
  } catch (error) {
    alert(error.message);
  }
}

// 表格里的「编辑 / 删除」：事件委托，行是动态渲染的也能点到
function onRecordListClick(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) {
    return;
  }
  const row = button.closest("tr[data-id]");
  if (!row) {
    return;
  }
  const recordId = Number(row.dataset.id);
  if (button.dataset.action === "edit") {
    const record = recordCache.get(recordId);
    if (record) {
      openRecordModal({ record: record });
    }
  } else if (button.dataset.action === "delete") {
    removeRecord(recordId);
  }
}

/* ===================== 分类管理弹窗 ===================== */

// 新增分类：名字 + 可选父级
async function addCategory() {
  const nameInput = $("#new-category-name");
  const name = nameInput.value.trim();
  if (!name) {
    alert("请填写分类名称");
    return;
  }
  const parentValue = $("#new-category-parent").value;
  const body = { name: name };
  if (parentValue) {
    body.parent_id = Number(parentValue);
  }

  try {
    await api("/api/categories", jsonOptions("POST", body));
    nameInput.value = "";
    await loadCategories();
    // 新建的分类可能带着新的二级分类，记账弹窗的级联下拉也要更新
    fillCategoryParent();
  } catch (error) {
    alert(error.message);
  }
}

// 删除分类：有子分类或还有账目在用时后端会拒绝，把原因弹出来
async function removeCategory(categoryId) {
  if (!confirm("确定删除这个分类吗？")) {
    return;
  }
  try {
    await api("/api/categories/" + categoryId, { method: "DELETE" });
    await loadCategories();
    fillCategoryParent();
  } catch (error) {
    alert(error.message);
  }
}

/* ===================== 账户管理 ===================== */

// 新增账户：名称 + 大类 + 初始余额
async function addAccount() {
  const nameInput = $("#new-account-name");
  const name = nameInput.value.trim();
  if (!name) {
    alert("请填写账户名称");
    return;
  }
  const balance = Number($("#new-account-balance").value) || 0;

  try {
    await api(
      "/api/accounts",
      jsonOptions("POST", {
        name: name,
        group_name: $("#new-account-group").value,
        balance: balance,
      })
    );
    nameInput.value = "";
    $("#new-account-balance").value = "0";
    accountModal.hide();
    await loadAccounts();
    await loadStatistics();
  } catch (error) {
    alert(error.message);
  }
}

// 删除账户：还有账目挂在这个账户下时后端会拒绝
async function removeAccount(name) {
  if (!confirm("确定删除账户「" + name + "」吗？")) {
    return;
  }
  try {
    await api("/api/accounts/" + encodeURIComponent(name), { method: "DELETE" });
    await loadAccounts();
    await loadStatistics();
  } catch (error) {
    alert(error.message);
  }
}

/* ===================== 切页 ===================== */

function switchPage(name) {
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.page === name);
  });
  document.querySelectorAll(".page").forEach((page) => {
    page.classList.toggle("active", page.id === "page-" + name);
  });
  $("#page-title").textContent = PAGE_TITLES[name] || "首页";

  // 第一次进资产页时，账户卡片已经在 loadAccounts 里渲染好了
  if (name === "assets") {
    renderAccountGroups();
  }
  if (name === "calendar") {
    renderCalendar(state.allRecords);
  }
}

/* ===================== 统一刷新 ===================== */

// 三个请求并行发，比一个个等快；改完账目后调用它，卡片和表格一起更新
async function refresh() {
  await Promise.all([loadStatistics(), loadAccounts(), loadRecords()]);

  // 资产页正开着某个账户的流水，也要跟着刷新
  if (state.detailAccount) {
    await selectAccount(state.detailAccount);
  }
}

/* ===================== 事件绑定与启动 ===================== */

function bindEvents() {
  // 侧边栏切页
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", (event) => {
      event.preventDefault();
      switchPage(item.dataset.page);
    });
  });

  // 顶部「+ 记一笔」：打开空白表单
  $("#add-record-btn").addEventListener("click", () => openRecordModal(null));

  // 记账弹窗：切换一级分类时联动二级
  $("#category").addEventListener("change", fillCategoryChild);
  $("#save-btn").addEventListener("click", saveRecord);

  // 弹窗关掉后复位，下次打开不会残留上一次填的内容
  $("#record-modal").addEventListener("hidden.bs.modal", resetRecordForm);

  // 首页账户筛选
  $("#filter-account").addEventListener("change", () => {
    loadRecords().catch((error) => alert(error.message));
  });

  // 表格的编辑 / 删除（事件委托，两个表格共用一套逻辑）
  $("#record-list").addEventListener("click", onRecordListClick);
  $("#account-records").addEventListener("click", onRecordListClick);

  // 资产页：点卡片选账户、点小叉删账户
  $("#account-groups").addEventListener("click", (event) => {
    const deleteButton = event.target.closest("button[data-del-account]");
    if (deleteButton) {
      // 点的是删除：不要再触发下面的选中逻辑
      event.stopPropagation();
      removeAccount(deleteButton.dataset.delAccount);
      return;
    }
    const card = event.target.closest(".account-card");
    if (card) {
      selectAccount(card.dataset.account).catch((error) => alert(error.message));
    }
  });

  // 资产页的快捷记账：账户锁定为当前选中账户
  $("#quick-add-btn").addEventListener("click", () => {
    if (!state.detailAccount) {
      return;
    }
    openRecordModal({ account: state.detailAccount });
  });

  // 账户弹窗
  $("#open-account-btn").addEventListener("click", () => {
    $("#new-account-name").value = "";
    $("#new-account-balance").value = "0";
    accountModal.show();
  });
  $("#save-account-btn").addEventListener("click", addAccount);

  // 分类管理弹窗
  $("#open-category-btn").addEventListener("click", () => {
    renderCategoryTree();
    categoryModal.show();
  });
  $("#add-category-btn").addEventListener("click", addCategory);
  $("#category-tree").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-del-category]");
    if (button) {
      removeCategory(Number(button.dataset.delCategory));
    }
  });
}

async function init() {
  bindEvents();
  try {
    // 分类要先拿到，记账弹窗的级联下拉才知道有哪些二级分类
    await loadCategories();
    await refresh();
  } catch (error) {
    alert("加载数据失败：" + error.message);
  }
}

// 脚本放在 body 末尾，DOM 已经就绪；用 DOMContentLoaded 兜底，顺序更稳
document.addEventListener("DOMContentLoaded", init);
