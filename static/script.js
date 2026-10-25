// 前端逻辑：三张统计卡片 + 记一笔/编辑 + 删除 + 账户筛选 + 账户管理弹窗
const formTitle = document.getElementById("form-title");
const amountInput = document.getElementById("amount");
const categoryInput = document.getElementById("category");
const accountInput = document.getElementById("account");
const dateInput = document.getElementById("date");
const noteInput = document.getElementById("note");
const submitBtn = document.getElementById("submit-btn");
const cancelBtn = document.getElementById("cancel-btn");
const recordList = document.getElementById("record-list");
const emptyTip = document.getElementById("empty-tip");
const filterAccount = document.getElementById("filter-account");
const accountList = document.getElementById("account-list");

const statIncome = document.getElementById("stat-income");
const statExpense = document.getElementById("stat-expense");
const statBalance = document.getElementById("stat-balance");

// null = 正在新增；数字 = 正在编辑这条 id
let editingId = null;

// 账户管理弹窗用一个实例反复 show，不要每次点击都 new
const accountModalEl = document.getElementById("account-modal");
const accountModal = window.bootstrap ? new bootstrap.Modal(accountModalEl) : null;

// 金额统一格式化成 ¥12.50；负数显示成 -¥773.23 而不是 ¥-773.23
function money(n) {
  const v = Number(n) || 0;
  return (v < 0 ? "-" : "") + "¥" + Math.abs(v).toFixed(2);
}

// 带收支符号的金额：收入 +¥10.00，支出 -¥10.00
function signedMoney(amount, type) {
  return (type === "income" ? "+" : "-") + money(amount);
}

// 今天的本地日期，格式 YYYY-MM-DD（toLocaleDateString 的 sv-SE 正好是这个格式）
function todayString() {
  return new Date().toLocaleDateString("sv-SE");
}

// 当前选中的收支类型
function currentType() {
  const checked = document.querySelector('input[name="record-type"]:checked');
  return checked ? checked.value : "expense";
}

// ---------- 统计卡片 ----------
async function loadStatistics() {
  const resp = await fetch("/api/statistics");
  const s = await resp.json();

  statIncome.textContent = money(s.income_total);
  statExpense.textContent = money(s.expense_total);
  statBalance.textContent = money(s.balance_total);

  // 余额为负显示红色，非负显示蓝色 —— 换 class 而不是改 style，样式仍由 CSS 管
  statBalance.className =
    "stat-number " + (Number(s.balance_total) < 0 ? "text-danger" : "text-primary");
}

// ---------- 账户 ----------
// 把账户列表同步到三个地方：筛选下拉框、表单的账户下拉框、账户管理弹窗
function syncAccountOptions(names) {
  // 记住当前选中值，重建后尽量还原，避免刷新把用户的选择冲掉
  const filterValue = filterAccount.value;
  const accountValue = accountInput.value;

  filterAccount.innerHTML = "";
  const all = document.createElement("option");
  all.value = "";
  all.textContent = "全部账户";
  filterAccount.appendChild(all);

  accountInput.innerHTML = "";

  names.forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    filterAccount.appendChild(opt);

    const opt2 = document.createElement("option");
    opt2.value = name;
    opt2.textContent = name;
    accountInput.appendChild(opt2);
  });

  filterAccount.value = names.includes(filterValue) ? filterValue : "";
  accountInput.value = names.includes(accountValue) ? accountValue : names[0] || "";
}

// 渲染账户管理弹窗里的每一行
function renderAccountRows(accounts) {
  accountList.innerHTML = "";

  accounts.forEach((a) => {
    const tr = document.createElement("tr");

    const nameTd = document.createElement("td");
    nameTd.textContent = a.name;
    tr.appendChild(nameTd);

    // 余额为负也标红，和顶部卡片保持一致
    const balTd = document.createElement("td");
    balTd.textContent = money(a.balance);
    balTd.className = Number(a.balance) < 0 ? "text-danger fw-semibold" : "fw-semibold";
    tr.appendChild(balTd);

    const inputTd = document.createElement("td");
    const input = document.createElement("input");
    input.type = "number";
    input.step = "0.01";
    input.className = "form-control form-control-sm";
    input.value = a.balance;
    inputTd.appendChild(input);
    tr.appendChild(inputTd);

    const btnTd = document.createElement("td");
    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "btn btn-sm btn-outline-primary w-100";
    saveBtn.textContent = "保存";
    saveBtn.addEventListener("click", () => saveBalance(a.name, input, saveBtn));
    btnTd.appendChild(saveBtn);
    tr.appendChild(btnTd);

    accountList.appendChild(tr);
  });
}

// 手动改某个账户的余额
async function saveBalance(name, input, btn) {
  const balance = Number(input.value);
  if (Number.isNaN(balance)) {
    alert("请输入数字");
    return;
  }

  btn.disabled = true;
  try {
    const resp = await fetch(`/api/accounts/${encodeURIComponent(name)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ balance: balance }),
    });

    if (!resp.ok) {
      const err = await resp.json();
      alert("修改失败：" + (err.error || resp.status));
      return;
    }

    // 不弹 alert，改成按钮上闪一下"已保存"，操作更顺
    btn.textContent = "已保存";
    await loadAccounts();
    await loadStatistics();
    setTimeout(() => {
      btn.textContent = "保存";
    }, 1200);
  } catch (e) {
    alert("网络错误：" + e.message);
  } finally {
    btn.disabled = false;
  }
}

// 拉账户列表，同时喂给下拉框和弹窗
async function loadAccounts() {
  const resp = await fetch("/api/accounts");
  const data = await resp.json();
  const names = data.accounts.map((a) => a.name);
  syncAccountOptions(names);
  renderAccountRows(data.accounts);
}

// ---------- 账目列表 ----------
// 处理「记录里的分类/账户不在下拉选项里」的情况（比如老数据里的"卫浴"）
function ensureOption(select, value) {
  if (!value) {
    return;
  }
  const exists = Array.from(select.options).some((o) => o.value === value);
  if (!exists) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = value;
    // 打上标记，退出编辑时清掉，不让临时值污染下拉列表
    opt.dataset.temp = "1";
    select.appendChild(opt);
  }
  select.value = value;
}

// 清掉 ensureOption 临时加进去的选项
function clearTempOptions(select) {
  Array.from(select.querySelectorAll('option[data-temp="1"]')).forEach((o) => o.remove());
}

// 造一个表格单元格，用 textContent 赋值，避免备注里的特殊字符破坏页面
function cell(text, className) {
  const td = document.createElement("td");
  if (className) {
    td.className = className;
  }
  td.textContent = text;
  return td;
}

// 从后端拿列表，渲染成表格行（顺序由后端 SQL 决定，前端不重排）
async function loadRecords() {
  const account = filterAccount.value;
  const url = account ? `/api/records?account=${encodeURIComponent(account)}` : "/api/records";

  const resp = await fetch(url);
  const data = await resp.json();
  recordList.innerHTML = "";

  if (data.count === 0) {
    emptyTip.textContent = account ? `「${account}」还没有记录` : "还没有记录，先记一笔吧";
    emptyTip.classList.remove("d-none");
    return;
  }
  emptyTip.classList.add("d-none");

  data.records.forEach((r) => {
    const tr = document.createElement("tr");
    const isIncome = r.type === "income";

    tr.appendChild(cell(r.date));

    // 类型用 Bootstrap 徽章区分，一眼能看出是收还是支
    const typeBadge = document.createElement("span");
    typeBadge.className = "badge " + (isIncome ? "bg-success" : "bg-danger");
    typeBadge.textContent = isIncome ? "收入" : "支出";
    const typeTd = document.createElement("td");
    typeTd.appendChild(typeBadge);
    tr.appendChild(typeTd);

    tr.appendChild(cell(r.category));
    tr.appendChild(cell(r.account));

    // 支出是负数，收入是正数，和余额的算法对得上
    tr.appendChild(
      cell(signedMoney(r.amount, r.type), "text-end fw-semibold " + (isIncome ? "text-success" : "text-danger"))
    );
    tr.appendChild(cell(r.note || "—", "text-muted"));

    const actions = document.createElement("td");
    actions.className = "text-end";

    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "btn btn-sm btn-warning me-2";
    editBtn.textContent = "编辑";
    editBtn.addEventListener("click", () => startEdit(r));

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "btn btn-sm btn-danger";
    delBtn.textContent = "删除";
    delBtn.addEventListener("click", () => handleDelete(r.id));

    actions.appendChild(editBtn);
    actions.appendChild(delBtn);
    tr.appendChild(actions);

    recordList.appendChild(tr);
  });
}

// ---------- 新增 / 编辑 ----------
// 新增和编辑共用一套表单，提交时按 editingId 决定发 POST 还是 PUT
async function handleSubmit() {
  const amount = Number(amountInput.value);
  if (!amount || amount <= 0) {
    alert("请输入大于 0 的金额");
    return;
  }

  const payload = {
    amount: amount,
    category: categoryInput.value,
    account: accountInput.value,
    date: dateInput.value || todayString(),
    note: noteInput.value.trim(),
    type: currentType(),
  };

  const isEdit = editingId !== null;
  const url = isEdit ? `/api/records/${editingId}` : "/api/records";

  submitBtn.disabled = true;
  try {
    const resp = await fetch(url, {
      method: isEdit ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      // 后端 400/404 时会返回 {"error": "..."}，直接弹给用户看
      const err = await resp.json();
      alert((isEdit ? "修改失败：" : "记账失败：") + (err.error || resp.status));
      return;
    }

    alert(isEdit ? "修改成功" : "记账成功");
    resetForm();
    await refresh();
  } catch (e) {
    alert("网络错误：" + e.message);
  } finally {
    // 不管成功失败都把按钮恢复可点，否则一次失败就再也点不动
    submitBtn.disabled = false;
  }
}

// 点某一行的「编辑」：把该行数据回填到表单，按钮切成「保存修改」
function startEdit(record) {
  clearTempOptions(categoryInput);
  clearTempOptions(accountInput);

  editingId = record.id;
  amountInput.value = record.amount;
  ensureOption(categoryInput, record.category);
  ensureOption(accountInput, record.account);
  dateInput.value = record.date;
  noteInput.value = record.note || "";

  // 回填收支类型（点住对应的 radio）
  const typeRadio = document.getElementById(
    record.type === "income" ? "type-income" : "type-expense"
  );
  typeRadio.checked = true;

  formTitle.textContent = `正在编辑 #${record.id}`;
  submitBtn.textContent = "保存修改";
  submitBtn.className = "btn btn-success";
  cancelBtn.classList.remove("d-none");

  // 表单在页面上方，滚回去让用户看见回填结果
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// 把表单恢复成「新增」状态
function resetForm() {
  editingId = null;

  amountInput.value = "";
  noteInput.value = "";
  dateInput.value = todayString();
  document.getElementById("type-expense").checked = true;

  clearTempOptions(categoryInput);
  clearTempOptions(accountInput);
  categoryInput.selectedIndex = 0;
  accountInput.selectedIndex = 0;

  formTitle.textContent = "记一笔";
  submitBtn.textContent = "记一笔";
  submitBtn.className = "btn btn-primary";
  cancelBtn.classList.add("d-none");
}

// 删除一条记录：先确认，再发 DELETE，成功后刷新
async function handleDelete(id) {
  if (!confirm("确定删除这条记录吗？删除后无法恢复")) {
    return;
  }
  try {
    const resp = await fetch(`/api/records/${id}`, { method: "DELETE" });
    if (!resp.ok) {
      const err = await resp.json();
      alert("删除失败：" + (err.error || resp.status));
      return;
    }
    // 删的正好是正在编辑的那条，就把表单退回新增状态
    if (editingId === id) {
      resetForm();
    }
    await refresh();
  } catch (e) {
    alert("网络错误：" + e.message);
  }
}

// ---------- 刷新 ----------
// 卡片、表格、账户三处一起刷新，避免数字互相打架
async function refresh() {
  await Promise.all([loadStatistics(), loadAccounts(), loadRecords()]);
}

submitBtn.addEventListener("click", handleSubmit);
cancelBtn.addEventListener("click", resetForm);

// 切换筛选账户就重新拉列表，不动统计卡片（统计卡是全局的，不跟着筛）
filterAccount.addEventListener("change", loadRecords);

// 账户管理弹窗
document.getElementById("manage-accounts-btn").addEventListener("click", () => {
  if (accountModal) {
    accountModal.show();
  } else {
    alert("Bootstrap 脚本没加载成功，弹窗打不开");
  }
});

// 页面一打开就拉数据
refresh();
