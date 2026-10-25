// 前端逻辑：提交一笔账 + 渲染历史列表
const amountInput = document.getElementById("amount");
const categoryInput = document.getElementById("category");
const noteInput = document.getElementById("note");
const submitBtn = document.getElementById("submit-btn");
const recordList = document.getElementById("record-list");

// 统一从后端拿一次列表，渲染到 <ul> 里
async function loadRecords() {
  const resp = await fetch("/api/records");
  const data = await resp.json();
  recordList.innerHTML = "";

  if (data.count === 0) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "还没有记录，先记一笔吧";
    recordList.appendChild(li);
    return;
  }

  // 后端按 id 倒序返回，最新的在最前面
  data.records.forEach((r) => {
    const li = document.createElement("li");
    // 用 textContent 而不是 innerHTML，避免备注里的特殊字符破坏页面
    li.textContent = `${r.date} ｜ ${r.category} ｜ ¥${Number(r.amount).toFixed(2)} ｜ ${r.note || "无备注"}`;
    recordList.appendChild(li);
  });
}

// 点“记一笔”：组 JSON 发给后端，成功后清空输入框并刷新列表
async function handleSubmit() {
  const amount = Number(amountInput.value);
  const category = categoryInput.value.trim();

  if (!amount || amount <= 0) {
    alert("请输入大于 0 的金额");
    return;
  }
  if (!category) {
    alert("请输入分类");
    return;
  }

  submitBtn.disabled = true;
  try {
    const resp = await fetch("/api/records", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        amount: amount,
        category: category,
        note: noteInput.value.trim(),
      }),
    });

    if (!resp.ok) {
      // 后端 400 时会返回 {"error": "..."}，直接弹给用户看
      const err = await resp.json();
      alert("记账失败：" + (err.error || resp.status));
      return;
    }

    alert("记账成功");
    amountInput.value = "";
    categoryInput.value = "";
    noteInput.value = "";
    await loadRecords();
  } catch (e) {
    alert("网络错误：" + e.message);
  } finally {
    // 不管成功失败都把按钮恢复可点，否则一次失败就再也点不动
    submitBtn.disabled = false;
  }
}

submitBtn.addEventListener("click", handleSubmit);

// 页面一打开就先把历史记录拉下来
loadRecords();
