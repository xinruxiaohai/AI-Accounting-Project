/**
 * v0.13.0 图表看板（独立脚本，依赖 script.js 暴露的 state / api / money / escapeHtml）
 *
 * 布局：左侧二级子菜单（收支总览 / 极值趋势 / 汇总表）
 *      顶部 年 / 季 / 月 / 周 + 左右切换
 *      三段内容：三列大数字、带极值辅助线的渐变折线、日期汇总表
 *
 * 只读 /api/records 的本地缓存，不新增后端接口；深浅色都从 chartPalette() 取色。
 */
(function () {
  "use strict";

  var PERIOD_UNITS = {
    year: "年",
    quarter: "季",
    month: "月",
    week: "周",
  };

  var SERIES_META = {
    expense: { key: "expense", label: "支出", color: "#f97316", net: false },
    income: { key: "income", label: "收入", color: "#10b981", net: false },
    net: { key: "net", label: "结余", color: "#6366f1", net: true },
  };

  var pageState = {
    period: "month",
    anchor: new Date(),
    series: "expense",
    chart: null,
    records: null,
    loading: false,
  };

  function $(id) {
    return document.getElementById(id);
  }

  function pad2(value) {
    return String(value).padStart(2, "0");
  }

  function isoDate(date) {
    return date.getFullYear() + "-" + pad2(date.getMonth() + 1) + "-" + pad2(date.getDate());
  }

  function hexToRgba(hex, alpha) {
    var value = String(hex || "").replace("#", "");
    if (value.length === 3) {
      value = value[0] + value[0] + value[1] + value[1] + value[2] + value[2];
    }
    if (value.length !== 6) {
      return "rgba(37, 99, 235, " + alpha + ")";
    }
    var r = parseInt(value.slice(0, 2), 16);
    var g = parseInt(value.slice(2, 4), 16);
    var b = parseInt(value.slice(4, 6), 16);
    return "rgba(" + r + ", " + g + ", " + b + ", " + alpha + ")";
  }

  function moneySafe(value) {
    if (typeof window.money === "function") {
      return window.money(value);
    }
    return "¥" + Number(value || 0).toFixed(2);
  }

  function startOfWeek(date) {
    var copy = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    var day = copy.getDay() === 0 ? 7 : copy.getDay();
    copy.setDate(copy.getDate() - (day - 1));
    return copy;
  }

  /** 当前周期范围：返回 {start, end, label, buckets:[{key,label,monthIndex?,date?}]} */
  function periodRange(period, anchor) {
    var buckets = [];
    var start;
    var end;
    var label;
    var i;

    if (period === "year") {
      start = new Date(anchor.getFullYear(), 0, 1);
      end = new Date(anchor.getFullYear(), 11, 31);
      for (i = 0; i < 12; i += 1) {
        buckets.push({ key: "m" + (i + 1), label: i + 1 + "月", monthIndex: i });
      }
      label = anchor.getFullYear() + " 年";
    } else if (period === "quarter") {
      var quarter = Math.floor(anchor.getMonth() / 3);
      start = new Date(anchor.getFullYear(), quarter * 3, 1);
      end = new Date(anchor.getFullYear(), quarter * 3 + 3, 0);
      for (i = 0; i < 3; i += 1) {
        var monthIndex = quarter * 3 + i;
        buckets.push({
          key: "m" + (monthIndex + 1),
          label: monthIndex + 1 + "月",
          monthIndex: monthIndex,
        });
      }
      label = anchor.getFullYear() + " 年第 " + (quarter + 1) + " 季度";
    } else if (period === "week") {
      start = startOfWeek(anchor);
      end = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 6);
      var weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
      for (i = 0; i < 7; i += 1) {
        var day = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
        buckets.push({ key: isoDate(day), label: weekdays[i], date: day });
      }
      label =
        pad2(start.getMonth() + 1) +
        "-" +
        pad2(start.getDate()) +
        " ~ " +
        pad2(end.getMonth() + 1) +
        "-" +
        pad2(end.getDate()) +
        " 周";
    } else {
      start = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
      end = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0);
      for (i = 1; i <= end.getDate(); i += 1) {
        buckets.push({
          key: anchor.getFullYear() + "-" + pad2(anchor.getMonth() + 1) + "-" + pad2(i),
          label: String(i),
          date: new Date(anchor.getFullYear(), anchor.getMonth(), i),
        });
      }
      label = anchor.getFullYear() + " 年 " + (anchor.getMonth() + 1) + " 月";
    }
    return { start: start, end: end, label: label, buckets: buckets };
  }

  function shiftAnchor(period, anchor, step) {
    var next = new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate());
    if (period === "year") {
      next.setFullYear(next.getFullYear() + step);
    } else if (period === "quarter") {
      next.setMonth(next.getMonth() + step * 3);
    } else if (period === "week") {
      next.setDate(next.getDate() + step * 7);
    } else {
      next.setMonth(next.getMonth() + step);
    }
    return next;
  }

  function recordDateText(record) {
    var raw = String(record.date || record.created_at || "");
    return raw.slice(0, 10);
  }

  /** 把账目按当前周期分桶汇总 */
  function aggregate(records, range) {
    var buckets = range.buckets.map(function (bucket) {
      return {
        key: bucket.key,
        label: bucket.label,
        monthIndex: bucket.monthIndex,
        date: bucket.date,
        expense: 0,
        income: 0,
      };
    });
    var startIso = isoDate(range.start);
    var endIso = isoDate(range.end);

    records.forEach(function (record) {
      if (!record || (record.type !== "expense" && record.type !== "income")) {
        return;
      }
      var dateText = recordDateText(record);
      if (!dateText || dateText < startIso || dateText > endIso) {
        return;
      }
      var amount = Number(record.amount || 0);
      var target = null;
      if (pageState.period === "year" || pageState.period === "quarter") {
        var month = Number(dateText.slice(5, 7)) - 1;
        target = buckets.find(function (bucket) {
          return bucket.monthIndex === month;
        });
      } else {
        target = buckets.find(function (bucket) {
          return bucket.key === dateText;
        });
      }
      if (!target) {
        return;
      }
      if (record.type === "income") {
        target.income += amount;
      } else {
        target.expense += amount;
      }
    });

    buckets.forEach(function (bucket) {
      bucket.net = Number((bucket.income - bucket.expense).toFixed(2));
    });
    return buckets;
  }

  function totalsOf(buckets) {
    var expense = 0;
    var income = 0;
    buckets.forEach(function (bucket) {
      expense += bucket.expense;
      income += bucket.income;
    });
    return {
      expense: Number(expense.toFixed(2)),
      income: Number(income.toFixed(2)),
      net: Number((income - expense).toFixed(2)),
    };
  }

  function seriesValuesOf(buckets, key) {
    return buckets.map(function (bucket) {
      return key === "net" ? bucket.net : key === "income" ? bucket.income : bucket.expense;
    });
  }

  function renderOverview(totals) {
    var expenseEl = $("chart-total-expense");
    var incomeEl = $("chart-total-income");
    var netEl = $("chart-total-net");
    if (expenseEl) {
      expenseEl.textContent = moneySafe(totals.expense);
    }
    if (incomeEl) {
      incomeEl.textContent = moneySafe(totals.income);
    }
    if (netEl) {
      netEl.textContent = moneySafe(totals.net);
      netEl.classList.toggle("is-negative", totals.net < 0);
    }
  }

  function trendOption(buckets, seriesKey) {
    var palette = typeof chartPalette === "function" ? chartPalette() : {};
    var meta = SERIES_META[seriesKey] || SERIES_META.expense;
    var labels = buckets.map(function (bucket) {
      return bucket.label;
    });
    var values = seriesValuesOf(buckets, seriesKey);
    var nonZero = values.filter(function (value) {
      return value !== null && value !== undefined;
    });
    var max = nonZero.length ? Math.max.apply(null, nonZero) : 0;
    var min = nonZero.length ? Math.min.apply(null, nonZero) : 0;
    var sum = nonZero.reduce(function (acc, value) {
      return acc + value;
    }, 0);
    var avg = nonZero.length ? sum / nonZero.length : 0;
    var textColor = palette.text || "#475569";
    var strongColor = palette.strong || "#1e293b";
    var gridLine = palette.line || "#e6ebf2";

    // 折线：渐变填充 + 圆点；净值为负时用另一套提示色
    var seriesColor = meta.color;
    var areaTop = hexToRgba(seriesColor, 0.28);
    var areaBottom = hexToRgba(seriesColor, 0.02);

    return {
      animationDuration: 520,
      grid: { left: 12, right: 22, top: 26, bottom: 8, containLabel: true },
      tooltip: {
        trigger: "axis",
        backgroundColor: palette.surface || "#ffffff",
        borderColor: gridLine,
        borderWidth: 1,
        textStyle: { color: strongColor, fontSize: 12 },
        axisPointer: { type: "line", lineStyle: { color: gridLine, type: "dashed" } },
        formatter: function (params) {
          if (!params || !params.length) {
            return "";
          }
          var point = params[0];
          return (
            "<div style='font-weight:600;margin-bottom:4px'>" +
            point.axisValue +
            "</div>" +
            meta.label +
            "：" +
            moneySafe(point.value)
          );
        },
      },
      xAxis: {
        type: "category",
        data: labels,
        boundaryGap: false,
        axisLine: { lineStyle: { color: gridLine } },
        axisTick: { show: false },
        axisLabel: {
          color: textColor,
          fontSize: 11,
          hideOverlap: true,
          interval: "auto",
        },
      },
      yAxis: {
        type: "value",
        splitLine: { lineStyle: { color: gridLine, type: "dashed" } },
        axisLabel: {
          color: textColor,
          fontSize: 11,
          formatter: function (value) {
            return Math.abs(value) >= 10000 ? value / 10000 + "w" : String(value);
          },
        },
      },
      series: [
        {
          name: meta.label,
          type: "line",
          smooth: 0.32,
          showSymbol: false,
          symbolSize: 7,
          data: values,
          lineStyle: { width: 2.4, color: seriesColor },
          itemStyle: { color: seriesColor, borderColor: palette.surface || "#fff", borderWidth: 2 },
          emphasis: { focus: "series", scale: 1.4 },
          areaStyle: {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: areaTop },
                { offset: 1, color: areaBottom },
              ],
            },
          },
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { type: "dashed", width: 1.2 },
            label: {
              color: textColor,
              fontSize: 10,
              formatter: function (params) {
                return params.name + "  " + moneySafe(params.value);
              },
            },
            data: [
              {
                type: "max",
                name: "最高",
                lineStyle: { color: "#f43f5e" },
                label: { color: "#f43f5e", position: "insideEndTop" },
              },
              {
                type: "min",
                name: "最低",
                lineStyle: { color: "#0ea5e9" },
                label: { color: "#0ea5e9", position: "insideEndBottom" },
              },
              {
                yAxis: Number(avg.toFixed(2)),
                name: "均值",
                lineStyle: { color: "#a855f7" },
                label: { color: "#a855f7", position: "insideStartTop" },
              },
            ],
          },
        },
      ],
      graphic: nonZero.length
        ? []
        : [
            {
              type: "text",
              left: "center",
              top: "middle",
              style: { text: "这段时间还没有收支记录", fill: textColor, fontSize: 12 },
            },
          ],
    };
  }

  function renderTrend(buckets) {
    var element = $("chart-trend-main");
    if (!element || typeof window.echarts === "undefined") {
      return;
    }
    if (!pageState.chart) {
      pageState.chart = window.echarts.init(element, null, { renderer: "canvas" });
    }
    pageState.chart.resize();
    pageState.chart.setOption(trendOption(buckets, pageState.series), true);
  }

  function renderSummary(buckets, range) {
    var body = $("chart-summary-body");
    var sub = $("chart-summary-sub");
    if (!body) {
      return;
    }
    if (sub) {
      sub.textContent = range.label;
    }
    var rows = buckets;
    if (pageState.period === "month" || pageState.period === "week") {
      var filled = buckets.filter(function (bucket) {
        return bucket.expense || bucket.income;
      });
      rows = filled.length ? filled : buckets.slice(0, 0);
    }
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="4" class="empty-cell">这段时间还没有收支记录</td></tr>';
      return;
    }
    var totals = totalsOf(buckets);
    var html = rows
      .map(function (bucket) {
        var label = bucket.label;
        if (bucket.date && pageState.period !== "week") {
          label = pad2(bucket.date.getMonth() + 1) + "-" + pad2(bucket.date.getDate());
        }
        return (
          "<tr>" +
          "<td>" +
          label +
          "</td>" +
          "<td class=\"text-end is-income\">" +
          (bucket.income ? moneySafe(bucket.income) : "—") +
          "</td>" +
          "<td class=\"text-end is-expense\">" +
          (bucket.expense ? moneySafe(bucket.expense) : "—") +
          "</td>" +
          "<td class=\"text-end " +
          (bucket.net < 0 ? "is-negative" : "") +
          '">' +
          moneySafe(bucket.net) +
          "</td>" +
          "</tr>"
        );
      })
      .join("");
    body.innerHTML =
      html +
      '<tr class="chart-summary-total">' +
      "<td>合计</td>" +
      '<td class="text-end is-income">' +
      moneySafe(totals.income) +
      "</td>" +
      '<td class="text-end is-expense">' +
      moneySafe(totals.expense) +
      "</td>" +
      '<td class="text-end ' +
      (totals.net < 0 ? "is-negative" : "") +
      '">' +
      moneySafe(totals.net) +
      "</td>" +
      "</tr>";
  }

  function renderPeriodLabel(range) {
    var label = $("chart-period-label");
    if (label) {
      label.textContent = range.label;
    }
  }

  function syncPeriodButtons() {
    var buttons = document.querySelectorAll("[data-chart-period]");
    Array.prototype.forEach.call(buttons, function (button) {
      button.classList.toggle(
        "active",
        button.getAttribute("data-chart-period") === pageState.period
      );
    });
  }

  function syncSeriesButtons() {
    var buttons = document.querySelectorAll("[data-chart-series]");
    Array.prototype.forEach.call(buttons, function (button) {
      button.classList.toggle(
        "active",
        button.getAttribute("data-chart-series") === pageState.series
      );
    });
  }

  function renderAll() {
    var records = pageState.records || [];
    var range = periodRange(pageState.period, pageState.anchor);
    var buckets = aggregate(records, range);
    renderPeriodLabel(range);
    renderOverview(totalsOf(buckets));
    renderTrend(buckets);
    renderSummary(buckets, range);
    syncPeriodButtons();
    syncSeriesButtons();
  }

  /** script.js 的 state 是全局词法变量（const），只能按名字取，不在 window 上 */
  function cachedRecords() {
    try {
      if (typeof state !== "undefined" && state && Array.isArray(state.allRecords)) {
        return state.allRecords;
      }
    } catch (error) {
      return null;
    }
    return null;
  }

  async function loadRecords(force) {
    if (!force && Array.isArray(pageState.records)) {
      return pageState.records;
    }
    var cached = cachedRecords();
    if (cached && cached.length) {
      pageState.records = cached;
      return pageState.records;
    }
    if (typeof window.api === "function") {
      var data = await window.api("/api/records");
      pageState.records = (data && data.records) || [];
    } else {
      pageState.records = [];
    }
    return pageState.records;
  }

  function recordsReady() {
    return Array.isArray(pageState.records) && pageState.records.length > 0;
  }

  async function renderChartsPage(force) {
    if (pageState.loading) {
      return;
    }
    pageState.loading = true;
    var body = $("chart-summary-body");
    if (body && force && !recordsReady()) {
      body.innerHTML = '<tr><td colspan="4" class="empty-cell">正在加载…</td></tr>';
    }
    try {
      var records = await loadRecords(force);
      if (!records.length) {
        pageState.records = records;
      }
      renderAll();
    } catch (error) {
      if (body) {
        body.innerHTML = '<tr><td colspan="4" class="empty-cell">图表加载失败，请稍后重试</td></tr>';
      }
      if (typeof window.toast === "function") {
        window.toast((error && error.message) || "图表加载失败", "error");
      }
    } finally {
      pageState.loading = false;
    }
  }

  function scrollToCard(section) {
    var map = {
      overview: "chart-overview",
      trend: "chart-trend-card",
      summary: "chart-summary-card",
    };
    var target = $(map[section] || "chart-overview");
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  function bind() {
    var prev = $("chart-prev");
    var next = $("chart-next");
    if (prev) {
      prev.addEventListener("click", function () {
        pageState.anchor = shiftAnchor(pageState.period, pageState.anchor, -1);
        renderAll();
      });
    }
    if (next) {
      next.addEventListener("click", function () {
        pageState.anchor = shiftAnchor(pageState.period, pageState.anchor, 1);
        renderAll();
      });
    }

    document.addEventListener("click", function (event) {
      var periodButton = event.target.closest("[data-chart-period]");
      if (periodButton) {
        var period = periodButton.getAttribute("data-chart-period");
        if (period !== pageState.period) {
          pageState.period = period;
          // 切换维度回到「当前时间」，避免在去年 12 月切到周看到诡异的空窗
          pageState.anchor = new Date();
          // 数据已经在本地就直接重绘，不必再走一次「正在加载」的闪屏
          if (recordsReady()) {
            renderAll();
          } else {
            renderChartsPage(true);
          }
        }
        return;
      }
      var seriesButton = event.target.closest("[data-chart-series]");
      if (seriesButton) {
        pageState.series = seriesButton.getAttribute("data-chart-series");
        renderAll();
        return;
      }
      var subnavButton = event.target.closest("[data-chart-section]");
      if (subnavButton) {
        Array.prototype.forEach.call(
          document.querySelectorAll("[data-chart-section]"),
          function (item) {
            item.classList.toggle("active", item === subnavButton);
          }
        );
        scrollToCard(subnavButton.getAttribute("data-chart-section"));
      }
    });

    window.addEventListener("resize", function () {
      if (pageState.chart && $("page-charts") && $("page-charts").classList.contains("active")) {
        pageState.chart.resize();
      }
    });

    // 深浅色切换后 ECharts 的配色得重算一遍
    if (window.MutationObserver) {
      var observer = new MutationObserver(function () {
        if (pageState.chart) {
          renderAll();
        }
      });
      observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["data-theme"],
      });
    }

    if (typeof window.addEventListener === "function") {
      window.addEventListener("records:changed", function () {
        if ($("page-charts") && $("page-charts").classList.contains("active")) {
          renderChartsPage(true);
        }
      });
    }
  }

  window.renderChartsPage = renderChartsPage;
  window.reloadChartsPage = function () {
    pageState.records = null;
    return renderChartsPage(true);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
