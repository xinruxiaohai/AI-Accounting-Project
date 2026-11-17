/* ============================================================
   BIZ-V0151 · 业务专项（JavaSrc 独立文件，2026-11-17）
   ------------------------------------------------------------
   月度结账单卡 / 周期账单模板（只提醒+手动生成）/ 报销进阶。
   本文件由 Agent G 新增，script.js 一个字节都没动——并行期与 F 零冲突。
   依赖 script.js 已加载的全局：api / $ / toast / state / money /
   escapeHtml / fillAccountSelect / loadNotifications（这里做包装）。
   ============================================================ */
(function () {
  "use strict";

  var BIZ = "BIZ-V0151";

  function byId(id) { return document.getElementById(id); }

  /* ---------- ① 月度结账单卡 ---------- */

  function monthShift(month, delta) {
    var y = parseInt(month.slice(0, 4), 10);
    var m = parseInt(month.slice(5, 7), 10) - 1 + delta;
    y += Math.floor(m / 12);
    m = ((m % 12) + 12) % 12;
    return y + "-" + String(m + 1).padStart(2, "0");
  }

  async function loadBizMonthly() {
    var box = byId("biz-month-body");
    if (!box) { return; }
    var input = byId("biz-month-input");
    var month = (input && input.value) || new Date().toISOString().slice(0, 7);
    if (input) { input.value = month; }
    try {
      var data = await api("/api/biz/monthly-settlement?month=" + encodeURIComponent(month));
      renderBizMonthly(box, data);
    } catch (err) {
      box.innerHTML = '<p class="feed-empty">' + escapeHtml(err.message || "加载失败") + "</p>";
    }
  }

  function renderBizMonthly(box, data) {
    var cats = data.categories || [];
    var max = 0;
    cats.forEach(function (c) { if (c.amount > max) { max = c.amount; } });
    var rows = cats.map(function (c) {
      var w = max > 0 ? Math.max(4, Math.round(c.amount / max * 100)) : 4;
      return '<div class="biz-cat-row">' +
        '<div class="biz-cat-top"><span>' + escapeHtml(c.name) + '</span>' +
        '<span class="biz-cat-amt">' + money(c.amount) + ' · ' + Number(c.pct).toFixed(1) + '%</span></div>' +
        '<div class="biz-cat-track"><div class="biz-cat-bar" style="width:' + w + '%"></div></div>' +
        "</div>";
    }).join("");

    var netCls = data.net >= 0 ? "amt-income" : "amt-expense";
    box.innerHTML =
      '<div class="biz-summary">' +
        '<div class="biz-sum-cell"><span>收入</span><strong class="amt-income">' + money(data.income) + '</strong></div>' +
        '<div class="biz-sum-cell"><span>支出</span><strong class="amt-expense">' + money(data.expense) + '</strong></div>' +
        '<div class="biz-sum-cell"><span>结余</span><strong class="' + netCls + '">' + money(data.net) + '</strong></div>' +
        '<div class="biz-sum-cell"><span>笔数</span><strong>' + Number(data.count || 0) + '</strong></div>' +
      "</div>" +
      (cats.length
        ? '<div class="biz-cats"><div class="biz-subtitle">支出分类占比</div>' + rows + "</div>"
        : '<p class="feed-empty">本月还没有收支账目</p>') +
      (data.available_months && data.available_months.length
        ? '<div class="biz-months-hint">已有账目月份：' +
          escapeHtml(data.available_months.slice(0, 12).join("、")) + "</div>"
        : "");
  }

  /* ---------- ② 周期账单模板 ---------- */

  var BIZ_ACCOUNTS = [];
  var BIZ_CATEGORIES = [];

  function fillBizSelects() {
    var acc = byId("biz-tpl-account");
    if (acc) {
      var cur = acc.value;
      acc.innerHTML = BIZ_ACCOUNTS.map(function (a) {
        return '<option value="' + escapeHtml(a.name) + '">' + escapeHtml(a.name) + "</option>";
      }).join("");
      if (cur) { acc.value = cur; }
    }
    var cat = byId("biz-tpl-category");
    if (cat) {
      cat.innerHTML = '<option value="">（默认分类）</option>' + BIZ_CATEGORIES.map(function (c) {
        return '<option value="' + c.id + '">' + escapeHtml(c.name) + "</option>";
      }).join("");
    }
    var day = byId("biz-tpl-day");
    if (day && !day.options.length) {
      var html = "";
      for (var d = 1; d <= 31; d++) {
        html += '<option value="' + d + '">' + d + " 号</option>";
      }
      day.innerHTML = html;
    }
  }

  async function loadBizTemplates() {
    var box = byId("biz-tpl-list");
    if (!box) { return; }
    try {
      BIZ_ACCOUNTS = (state.accounts || []).slice();
      BIZ_CATEGORIES = (state.categories || []).slice();
      fillBizSelects();
      var data = await api("/api/biz/recurring/templates");
      renderBizTemplates(box, data.templates || []);
    } catch (err) {
      box.innerHTML = '<p class="feed-empty">' + escapeHtml(err.message || "加载失败") + "</p>";
    }
  }

  function renderBizTemplates(box, templates) {
    if (!templates.length) {
      box.innerHTML = '<p class="feed-empty">还没有周期模板。点「新建模板」添加一个。</p>';
      return;
    }
    box.innerHTML = templates.map(function (t) {
      var typeLabel = t.record_type === "income" ? "收入" : "支出";
      var statusCls = t.is_active ? "biz-tpl-active" : "biz-tpl-off";
      var statusText = t.is_active ? "启用中" : "已停用";
      var posted = (t.last_posted_at || "").slice(0, 7) === new Date().toISOString().slice(0, 7);
      return '<div class="biz-tpl-item' + (t.is_active ? "" : " is-off") + '" data-id="' + t.id + '">' +
        '<div class="biz-tpl-main">' +
          '<span class="biz-tpl-name">' + escapeHtml(t.name) + '</span>' +
          '<span class="biz-tpl-meta">' + typeLabel + ' · ' + money(t.amount) +
            ' · 每月 ' + t.day_of_month + ' 号 · ' + escapeHtml(t.account || "未设账户") +
            ' · <span class="' + statusCls + '">' + statusText + '</span>' +
            (posted ? ' · 本月已生成' : " · 本月待生成") + "</span>" +
          (t.note ? '<span class="biz-tpl-note">' + escapeHtml(t.note) + "</span>" : "") +
        "</div>" +
        '<div class="biz-tpl-actions">' +
          '<button class="btn btn-sm btn-primary" type="button" data-act="gen"' +
            (t.is_active ? "" : " disabled") + '>生成账单</button>' +
          '<button class="btn btn-sm btn-outline-secondary" type="button" data-act="edit">编辑</button>' +
          '<button class="btn btn-sm btn-outline-secondary" type="button" data-act="toggle">' +
            (t.is_active ? "停用" : "启用") + "</button>" +
          '<button class="btn btn-sm btn-outline-danger" type="button" data-act="del">删除</button>' +
        "</div>" +
      "</div>";
    }).join("");
  }

  function openBizTplForm(tpl) {
    var form = byId("biz-tpl-form");
    if (!form) { return; }
    form.hidden = false;
    BIZ_ACCOUNTS = (state.accounts || []).slice();
    BIZ_CATEGORIES = (state.categories || []).slice();
    fillBizSelects();
    byId("biz-tpl-id").value = tpl ? String(tpl.id) : "";
    byId("biz-tpl-name").value = tpl ? (tpl.name || "") : "";
    byId("biz-tpl-type").value = tpl ? (tpl.record_type || "expense") : "expense";
    byId("biz-tpl-amount").value = tpl ? Number(tpl.amount || 0).toFixed(2) : "";
    byId("biz-tpl-day").value = tpl ? String(tpl.day_of_month || 1) : "1";
    byId("biz-tpl-account").value = tpl ? (tpl.account || "") : "";
    byId("biz-tpl-category").value = tpl && tpl.category_id ? String(tpl.category_id) : "";
    byId("biz-tpl-note").value = tpl ? (tpl.note || "") : "";
    byId("biz-tpl-name").focus();
  }

  function closeBizTplForm() {
    var form = byId("biz-tpl-form");
    if (form) { form.hidden = true; }
  }

  async function submitBizTpl(event) {
    event.preventDefault();
    var id = byId("biz-tpl-id").value;
    var payload = {
      name: byId("biz-tpl-name").value.trim(),
      record_type: byId("biz-tpl-type").value,
      amount: Number(byId("biz-tpl-amount").value),
      day_of_month: Number(byId("biz-tpl-day").value),
      account: byId("biz-tpl-account").value,
      category_id: byId("biz-tpl-category").value,
      note: byId("biz-tpl-note").value.trim(),
    };
    try {
      if (id) {
        await api("/api/biz/recurring/templates/" + encodeURIComponent(id), {
          method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        });
        toast("模板已更新", "success");
      } else {
        await api("/api/biz/recurring/templates", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        });
        toast("模板已创建", "success");
      }
      closeBizTplForm();
      await loadBizTemplates();
      refreshBizReminders();
    } catch (err) {
      toast(err.message || "保存失败", "error");
    }
  }

  async function bizTplAction(id, act, button) {
    var tplsUrl = "/api/biz/recurring/templates";
    try {
      if (act === "gen") {
        if (button) { button.disabled = true; }
        await api(tplsUrl + "/" + encodeURIComponent(id) + "/generate", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
        });
        toast("账单已手动生成，账户余额已联动", "success");
        if (typeof window.__zhRefresh === "function") {
          window.__zhRefresh("biz-generate");
        }
      } else if (act === "toggle") {
        var item2 = document.querySelector('.biz-tpl-item[data-id="' + id + '"]');
        var off = item2 && item2.classList.contains("is-off");
        await api(tplsUrl + "/" + encodeURIComponent(id), {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_active: off ? 1 : 0 }),
        });
        toast(off ? "模板已启用" : "模板已停用", "success");
      } else if (act === "del") {
        // 全站无原生弹窗：第一次点只提示，再点一次才真删（3 秒内有效）
        var key = "bizTplDel_" + id;
        if (!window.__bizDelArmed || window.__bizDelArmed !== key) {
          window.__bizDelArmed = key;
          toast("再点一次「删除」确认（不会删除已生成的账单）", "info");
          window.setTimeout(function () {
            if (window.__bizDelArmed === key) { window.__bizDelArmed = null; }
          }, 3000);
          return;
        }
        window.__bizDelArmed = null;
        await api(tplsUrl + "/" + encodeURIComponent(id), { method: "DELETE" });
        toast("模板已删除", "success");
      } else if (act === "edit") {
        var data = await api(tplsUrl);
        var found = (data.templates || []).find(function (t) { return String(t.id) === String(id); });
        if (found) { openBizTplForm(found); }
        return;
      }
      await loadBizTemplates();
      refreshBizReminders();
    } catch (err) {
      toast(err.message || "操作失败", "error");
    } finally {
      if (button && act === "gen") { button.disabled = false; }
    }
  }

  /* ---------- ③ 报销进阶 ---------- */

  async function loadBizReimb() {
    var box = byId("biz-reimb-list");
    if (!box) { return; }
    var contact = (byId("biz-reimb-contact") || {}).value || "";
    var status = (byId("biz-reimb-state") || {}).value || "all";
    try {
      var data = await api("/api/biz/reimbursements?contact_id=" + encodeURIComponent(contact) +
        "&status=" + encodeURIComponent(status));
      var sel = byId("biz-reimb-contact");
      if (sel) {
        var cur = sel.value;
        sel.innerHTML = '<option value="">全部报销人</option>' + (data.contacts || []).map(function (c) {
          return '<option value="' + c.id + '">' + escapeHtml(c.name) + "</option>";
        }).join("");
        sel.value = cur;
      }
      renderBizReimb(box, data.reimbursements || []);
    } catch (err) {
      box.innerHTML = '<p class="feed-empty">' + escapeHtml(err.message || "加载失败") + "</p>";
    }
  }

  function renderBizReimb(box, rows) {
    if (!rows.length) {
      box.innerHTML = '<p class="feed-empty">没有符合条件的报销记录</p>';
      return;
    }
    var stateLabel = { pending: "待报销", partial: "部分报销", done: "已报销完" };
    box.innerHTML = rows.map(function (r) {
      var pct = Math.max(0, Math.min(100, Number(r.reimburse_pct || 0)));
      var cls = r.reimburse_state === "done" ? "biz-done" :
                (r.reimburse_state === "partial" ? "biz-partial" : "biz-pending");
      return '<div class="biz-reimb-item">' +
        '<div class="biz-reimb-head"><span>' + escapeHtml(r.reimbursement_contact_name || "未指定报销人") +
          '</span><span class="biz-reimb-tag ' + cls + '">' +
          (stateLabel[r.reimburse_state] || "") + "</span></div>" +
        '<div class="biz-reimb-note">' + escapeHtml(r.note || r.category || "") +
          ' · ' + escapeHtml((r.date || "").slice(0, 10)) + " · " + money(r.amount) + "</div>" +
        '<div class="biz-reimb-track"><div class="biz-reimb-bar ' + cls +
          '" style="width:' + pct + '%"></div></div>' +
        '<div class="biz-reimb-nums"><span>应报 ' + money(r.reimburse_total) +
          '</span><span>已报 ' + money(r.reimburse_paid) +
          '</span><span>待报 ' + money(r.reimburse_remaining) +
          '</span><span>' + pct.toFixed(1) + "%</span></div>" +
      "</div>";
    }).join("");
  }

  function exportBizReimb() {
    var contact = (byId("biz-reimb-contact") || {}).value || "";
    var status = (byId("biz-reimb-state") || {}).value || "all";
    var url = "/api/biz/reimbursements/export?contact_id=" + encodeURIComponent(contact) +
      "&status=" + encodeURIComponent(status);
    var a = document.createElement("a");
    a.href = url;
    a.download = "";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    toast("报销记录 CSV 已开始下载", "success");
  }

  /* ---------- ④ 到期提醒合并进通知中心（包装，不改 script.js） ---------- */

  async function refreshBizReminders() {
    if (typeof loadNotifications !== "function") { return; }
    await loadNotifications();
  }

  function installReminderMerge() {
    var original = window.loadNotifications;
    if (typeof original !== "function" || original.__bizMerged) { return; }
    var merged = async function () {
      try {
        await original.apply(this, arguments);
        var data = await api("/api/biz/recurring/reminders");
        var due = data.notifications || [];
        if (due.length) {
          var seen = {};
          (state.notifications || []).forEach(function (n) { seen[String(n.id)] = true; });
          due.forEach(function (n) {
            if (!seen[String(n.id)]) { state.notifications.unshift(n); }
          });
          if (typeof renderNotifications === "function") { renderNotifications(); }
          if (typeof updateNotifyDot === "function") { updateNotifyDot(); }
        }
      } catch (err) {
        /* 提醒合并失败不影响主通知列表 */
      }
    };
    merged.__bizMerged = true;
    window.loadNotifications = merged;
  }

  /* ---------- 初始化 ---------- */

  function bindBiz() {
    var prev = byId("biz-month-prev");
    var next = byId("biz-month-next");
    var input = byId("biz-month-input");
    if (prev) { prev.addEventListener("click", function () {
      input.value = monthShift(input.value || new Date().toISOString().slice(0, 7), -1);
      loadBizMonthly();
    }); }
    if (next) { next.addEventListener("click", function () {
      input.value = monthShift(input.value || new Date().toISOString().slice(0, 7), 1);
      loadBizMonthly();
    }); }
    if (input) { input.addEventListener("change", loadBizMonthly); }

    var form = byId("biz-tpl-form");
    if (form) { form.addEventListener("submit", submitBizTpl); }
    var tplNew = byId("biz-tpl-new");
    if (tplNew) { tplNew.addEventListener("click", function () { openBizTplForm(null); }); }
    var tplCancel = byId("biz-tpl-cancel");
    if (tplCancel) { tplCancel.addEventListener("click", closeBizTplForm); }
    var list = byId("biz-tpl-list");
    if (list) { list.addEventListener("click", function (event) {
      var btn = event.target.closest("button[data-act]");
      if (!btn) { return; }
      var item = btn.closest(".biz-tpl-item");
      if (!item) { return; }
      bizTplAction(item.getAttribute("data-id"), btn.getAttribute("data-act"), btn);
    }); }

    var contact = byId("biz-reimb-contact");
    if (contact) { contact.addEventListener("change", loadBizReimb); }
    var stateSel = byId("biz-reimb-state");
    if (stateSel) { stateSel.addEventListener("change", loadBizReimb); }
    var exp = byId("biz-reimb-export");
    if (exp) { exp.addEventListener("click", exportBizReimb); }
  }

  function bootBiz() {
    if (!byId("biz-v0151-root")) { return; }
    installReminderMerge();
    bindBiz();
    var input = byId("biz-month-input");
    if (input && !input.value) { input.value = new Date().toISOString().slice(0, 7); }
    loadBizMonthly().catch(function () {});
    loadBizTemplates().catch(function () {});
    loadBizReimb().catch(function () {});
  }

  window.__bizV0151 = {
    reloadMonthly: loadBizMonthly,
    reloadTemplates: loadBizTemplates,
    reloadReimb: loadBizReimb,
    marker: BIZ,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootBiz);
  } else {
    bootBiz();
  }
})();
