"use strict";

/*
 * AI记账管家 · 投资看板（v0.13.4-DEV）
 *
 * 为什么独立成文件：script.js 已经 1.1 万行，投资看板是一块完整的子模块，
 * 沿用 charts-v013.js 的先例（按功能独立文件 + window.* 暴露入口）。
 * script.js 只保留三处钩子（selectAccount / clearDetail 分支 + state.invest）。
 *
 * 依赖 script.js 已经定义好的公共设施（都是同页面的经典脚本，可直接引用）：
 *   api() / money() / cents() / escapeHtml() / toast() / state /
 *   setAmountAnimated() / feedGroupsHtml() / feedEmptyHtml() / balanceSnapshots() /
 *   isCollapsed() / toggleCollapseState() / userScopedKey() / setFieldError() /
 *   reportIssues() / hideModalSafe() / confirmAction() / entityIconHtml()
 *
 * 三条纪律（HANDOFF 已知坑）：
 *   1. 双 Tab 只切 .is-active，绝不重建 pane DOM —— 否则 event.target 被摘出文档，
 *      外部点击监听会误收浮层；
 *   2. 折叠 key 用实体 id 派生（platform:<id>），禁用数组下标；
 *   3. 全站禁用 alert()，统一 toast() / confirmAction()。
 */

/* ==================== 常量 ==================== */

// 代码搜索防抖时长（与 script.js 的 SEARCH_DEBOUNCE_MS 风格一致）
const INVEST_SEARCH_DEBOUNCE_MS = 500;
// 少于 1 个字不触发搜索
const INVEST_SEARCH_MIN_LEN = 1;
// 候选下拉最多 8 条（HANDOFF 交互纪律）
const INVEST_MAX_CANDIDATES = 8;

// 平台折叠态的 localStorage 键（写入前会过 userScopedKey 做用户隔离）
const LS_INVEST_PLATFORM_COLLAPSE = "ai-accounting-invest-platform-collapse";
// 流水折叠沿用账单流的会话级键（script.js 里叫 LS_FEED_COLLAPSE）
const INVEST_FEED_COLLAPSE_FALLBACK = "ai-accounting-feed-collapse-v1";

// 双 Tab 定义：顺序即 DOM 顺序，holdings 必须是第一个（默认展示持仓）
const INVEST_TABS = [
  { id: "holdings", label: "持仓" },
  { id: "ledger", label: "流水" },
];
const INVEST_DEFAULT_TAB = "holdings";

const INVEST_ASSET_TYPES = ["fund", "stock", "bond", "gold", "cash", "other"];
const INVEST_ASSET_LABELS = {
  fund: "基金",
  stock: "股票",
  bond: "债券",
  gold: "黄金",
  cash: "现金",
  other: "其它",
};

const INVEST_DCA_FREQUENCIES = ["weekly", "biweekly", "monthly", "quarterly"];
const INVEST_DCA_LABELS = {
  weekly: "每周",
  biweekly: "每两周",
  monthly: "每月",
  quarterly: "每季",
};

// 平台占位名（后端迁移步 9 会给每个投资账户预置同名平台）
const INVEST_PLATFORM_DEFAULT = "默认";

// 当日盈亏占位值：后端未接行情时恒为 available:false，前端就渲染这一串灰字。
// 金额与百分比各自独立节点，将来只改 textContent 即可接真实行情。
const INVEST_DAY_PL_PLACEHOLDER = { amount: "+0.00", percent: "(0.00%)" };

// 数据不可用时显示的占位：宁给「—」，也不给一个假的 ¥0.00
const INVEST_UNKNOWN_AMOUNT = "—";

const INVEST_CHEVRON =
  '<svg class="invest-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="m6 9 6 6 6-6"></path></svg>';

/* ==================== v0.13.3 联调用 Mock 数据 ====================
 *
 * 后端 /api/invest/* 由另一位同事并行施工。为了让 UI 在接口就绪前就能跑起来，
 * 这里内置一份**只供自测**的 Mock：只有 window.INVEST_DEV_MOCK 为真、
 * 且真实接口报错（404 / 501 / 连接失败）时才回落，**正常情况下完全不参与渲染**。
 * 后端联调通过后可整段删除，不影响任何线上逻辑。
 */

const INVEST_MOCK_SECURITIES = [
  { ticker: "005827", name: "易方达蓝筹精选", asset_type: "fund", price: 0, source: "mock" },
  { ticker: "110022", name: "易方达消费行业股票", asset_type: "fund", price: 0, source: "mock" },
  { ticker: "161725", name: "招商中证白酒指数", asset_type: "fund", price: 0, source: "mock" },
  { ticker: "000961", name: "天弘沪深300ETF联接A", asset_type: "fund", price: 0, source: "mock" },
  { ticker: "270042", name: "广发纳斯达克100指数", asset_type: "fund", price: 0, source: "mock" },
  { ticker: "003096", name: "中欧医疗健康混合C", asset_type: "fund", price: 0, source: "mock" },
  { ticker: "001714", name: "工银文体产业股票A", asset_type: "fund", price: 0, source: "mock" },
  { ticker: "519674", name: "银河创新成长混合", asset_type: "fund", price: 0, source: "mock" },
  { ticker: "600519", name: "贵州茅台", asset_type: "stock", price: 0, source: "mock" },
  { ticker: "000858", name: "五粮液", asset_type: "stock", price: 0, source: "mock" },
  { ticker: "601318", name: "中国平安", asset_type: "stock", price: 0, source: "mock" },
  { ticker: "600036", name: "招商银行", asset_type: "stock", price: 0, source: "mock" },
  { ticker: "300750", name: "宁德时代", asset_type: "stock", price: 0, source: "mock" },
  { ticker: "007339", name: "易方达中短债债券A", asset_type: "bond", price: 0, source: "mock" },
  { ticker: "000187", name: "华安沪深300增强债", asset_type: "bond", price: 0, source: "mock" },
];

const INVEST_MOCK_STORE = {
  seq: 100,
  boards: {},
};

/**
 * 本地 Mock 数据的开关。
 *
 * v0.13.3 T05：**默认关闭**。只有显式开启才生效——URL 带 `?investMock=1`、
 * localStorage 里 `ai-accounting-invest-dev-mock === "1"`，或测试脚本直接置
 * `window.INVEST_DEV_MOCK = true`。
 *
 * 关闭时任何真实接口报错都会原样弹 Toast，**绝不静默回落成本地假数据**，
 * 否则用户会看到「成功」但实际没落库（T05 明确的红线）。
 */
function investMockEnabled() {
  if (window.INVEST_DEV_MOCK === true) {
    return true;
  }
  try {
    if (String(window.location.search || "").indexOf("investMock=1") >= 0) {
      return true;
    }
    if (window.localStorage.getItem("ai-accounting-invest-dev-mock") === "1") {
      return true;
    }
  } catch (error) {
    // 隐私模式下 localStorage 可能不可读，按「未开启」处理最安全
  }
  return false;
}

function investMockSearch(keyword) {
  const text = String(keyword || "").trim().toLowerCase();
  if (!text) {
    return [];
  }
  const hits = INVEST_MOCK_SECURITIES.filter(function (item) {
    return (
      item.ticker.toLowerCase().indexOf(text) >= 0 ||
      item.name.toLowerCase().indexOf(text) >= 0
    );
  });
  // 代码精确命中优先
  hits.sort(function (a, b) {
    const aExact = a.ticker.toLowerCase() === text ? 0 : 1;
    const bExact = b.ticker.toLowerCase() === text ? 0 : 1;
    return aExact - bExact;
  });
  return hits.slice(0, INVEST_MAX_CANDIDATES);
}

function investMockBoard(accountName) {
  const key = String(accountName || "");
  if (INVEST_MOCK_STORE.boards[key]) {
    return INVEST_MOCK_STORE.boards[key];
  }
  INVEST_MOCK_STORE.seq += 1;
  const seed = INVEST_MOCK_STORE.seq;
  const board = {
    account: {
      name: key,
      type: "investment",
      balance: 18200,
      cash_label: "可用资金",
    },
    total_market_value: 0,
    total_cost: 0,
    day_pl: { amount: 0, percent: 0, available: false },
    platforms: [
      {
        id: seed * 10 + 1,
        name: INVEST_PLATFORM_DEFAULT,
        market_value: 0,
        holdings: [
          {
            id: seed * 100 + 1,
            platform_id: seed * 10 + 1,
            ticker: "005827",
            name: "易方达蓝筹精选",
            asset_type: "fund",
            shares: 1200,
            cost_price: 1.86,
            current_price: 0,
            cost_total: 2232,
            market_value: 2232,
          },
          {
            id: seed * 100 + 2,
            platform_id: seed * 10 + 1,
            ticker: "",
            name: "余额宝活期理财",
            asset_type: "cash",
            shares: 5000,
            cost_price: 1,
            current_price: 0,
            cost_total: 5000,
            market_value: 5000,
          },
        ],
      },
      {
        id: seed * 10 + 2,
        name: "蚂蚁财富",
        market_value: 0,
        holdings: [
          {
            id: seed * 100 + 3,
            platform_id: seed * 10 + 2,
            ticker: "000961",
            name: "天弘沪深300ETF联接A",
            asset_type: "fund",
            shares: 3200,
            cost_price: 1.542,
            current_price: 0,
            cost_total: 4934.4,
            market_value: 4934.4,
          },
          {
            id: seed * 100 + 4,
            platform_id: seed * 10 + 2,
            ticker: "600519",
            name: "贵州茅台",
            asset_type: "stock",
            shares: 10,
            cost_price: 1520,
            current_price: 0,
            cost_total: 15200,
            market_value: 15200,
          },
        ],
      },
      {
        id: seed * 10 + 3,
        name: "天天基金",
        market_value: 0,
        holdings: [
          {
            id: seed * 100 + 5,
            platform_id: seed * 10 + 3,
            ticker: "161725",
            name: "招商中证白酒指数",
            asset_type: "fund",
            shares: 860,
            cost_price: 0.9135,
            current_price: 0,
            cost_total: 785.61,
            market_value: 785.61,
          },
        ],
      },
    ],
  };
  investRecalcBoard(board);
  INVEST_MOCK_STORE.boards[key] = board;
  return board;
}

function investRecalcBoard(board) {
  let total = 0;
  let cost = 0;
  (board.platforms || []).forEach(function (platform) {
    let platformValue = 0;
    (platform.holdings || []).forEach(function (holding) {
      holding.market_value = investHoldingMarketValue(holding);
      platformValue += holding.market_value;
      cost += Number(holding.cost_total || 0);
    });
    platform.market_value = cents(platformValue);
    total += platformValue;
  });
  board.total_market_value = cents(total);
  board.total_cost = cents(cost);
  return board;
}

/* ==================== 会话内状态 ==================== */

const invest = {
  accountName: "",
  board: null,
  platforms: [],
  ledgerRecords: [],
  ledgerLoaded: false,
  loading: false,
  // 每次拉取自增，回来时对不上就丢弃（快速切账户时的竞态保护）
  requestSeq: 0,
  // 防抖定时器与搜索序号
  searchTimer: null,
  searchSeq: 0,
  candidates: [],
  // 这次候选是不是「东财不可用 → 本地字典兜底」来的，兜底时要在下拉里说清楚
  searchFallback: false,
  searchNotice: "",
  // 弹窗里已选中的平台
  modalPlatformId: 0,
  // 份额是不是"自动算的"：true=跟着金额/单价走，false=用户手填过
  sharesAuto: true,
};

/* ==================== 小工具 ==================== */

/** state 是 script.js 里的顶层 const，理论上直接可读；这里兜一层，脚本顺序异常时不至于整页报错 */
function investState() {
  return typeof state === "object" && state ? state : {};
}

function investActiveTab() {
  const holder = investState().invest || {};
  const tab = String(holder.activeTab || INVEST_DEFAULT_TAB);
  return tab === "ledger" ? "ledger" : "holdings";
}

function investSetActiveTab(tab) {
  const next = tab === "ledger" ? "ledger" : "holdings";
  const holder = investState();
  if (!holder.invest) {
    holder.invest = { accountName: "", activeTab: INVEST_DEFAULT_TAB };
  }
  holder.invest.activeTab = next;
  return next;
}

function investBoardEl() {
  return document.getElementById("invest-board");
}

function investEl(id) {
  return document.getElementById(id);
}

function investText(value) {
  return escapeHtml(value === null || value === undefined ? "" : value);
}

/** 数量为 0 / NaN 时统一回落 0，避免 NaN 串进 DOM */
function investNumber(value, fallback) {
  const n = Number(value);
  const base = Number.isFinite(fallback) ? fallback : 0;
  return Number.isFinite(n) ? n : base;
}

/**
 * 份额文案：整数不带小数，非整数最多 4 位并去掉尾随零。
 *
 * 确认卡（AI 建仓）与看板持仓行共用这一个出口 —— 两处曾各写一份 `toFixed(4)`，
 * 导致同一份持仓在 AI 路径和手动路径下精度不一致（v0.13.3 QA）。
 * 用 toFixed 而非 Number()，避免大额数字被转成科学计数法。
 */
function investSharesText(raw) {
  const value = Number(raw || 0);
  if (!Number.isFinite(value) || Math.abs(value) < 1e-9) {
    return "0";
  }
  const text = value.toFixed(4);
  if (text.indexOf(".") < 0) {
    return text;
  }
  // 先去尾随零，再把可能剩下的小数点一并去掉：100.0000 → 100，333.3300 → 333.33
  return text.replace(/0+$/, "").replace(/\.$/, "");
}

/** 市值：服务端已算好就直接读，缺了才在前端补一次（price 回落 cost_price，与后端 D8 同口径） */
function investHoldingMarketValue(holding) {
  const raw = Number(holding && holding.market_value);
  if (Number.isFinite(raw)) {
    return cents(raw);
  }
  const shares = investNumber(holding.shares, 0);
  const current = investNumber(holding.current_price, 0);
  const cost = investNumber(holding.cost_price, 0);
  const price = current > 0 ? current : cost;
  return cents(shares * price);
}

function investAssetLabel(assetType) {
  return INVEST_ASSET_LABELS[assetType] || INVEST_ASSET_LABELS.other;
}

function investTotalMarketValue(board) {
  const raw = Number(board && board.total_market_value);
  if (Number.isFinite(raw)) {
    return cents(raw);
  }
  let total = 0;
  ((board && board.platforms) || []).forEach(function (platform) {
    (platform.holdings || []).forEach(function (holding) {
      total += investHoldingMarketValue(holding);
    });
  });
  return cents(total);
}

/** 当日盈亏：后端 available=false（本期恒定）就渲染占位灰字，绝不编造数字 */
function investDayPl(board) {
  const raw = (board && board.day_pl) || {};
  const available = Boolean(raw.available);
  if (!available) {
    return {
      available: false,
      amountText: INVEST_DAY_PL_PLACEHOLDER.amount,
      percentText: INVEST_DAY_PL_PLACEHOLDER.percent,
    };
  }
  const amount = investNumber(raw.amount, 0);
  const percent = investNumber(raw.percent, 0);
  return {
    available: true,
    amountText: (amount >= 0 ? "+" : "-") + money(Math.abs(amount)).slice(1),
    percentText: "(" + (percent >= 0 ? "+" : "-") + Math.abs(percent).toFixed(2) + "%)",
  };
}

function investFeedCollapseKey() {
  // script.js 的 LS_FEED_COLLAPSE 是顶层 const，同页面经典脚本可直接读到；读不到就用同值兜底
  try {
    if (typeof LS_FEED_COLLAPSE === "string" && LS_FEED_COLLAPSE) {
      return LS_FEED_COLLAPSE;
    }
  } catch (error) {
    // 极端情况（脚本被改成 module）走兜底值
  }
  return INVEST_FEED_COLLAPSE_FALLBACK;
}

function investPlatformCollapseKey() {
  return userScopedKey(LS_INVEST_PLATFORM_COLLAPSE);
}

function investIsPlatformCollapsed(platformId) {
  return isCollapsed(investPlatformCollapseKey(), "platform:" + platformId);
}

function investTogglePlatform(platformId) {
  toggleCollapseState(investPlatformCollapseKey(), "platform:" + platformId);
}

/* ==================== 数据拉取 ==================== */

/**
 * 读接口：显式开了 Mock 才走本地数据，**不做「真实失败 → 静默回落」**。
 * 写接口（POST / DELETE holdings）一律走真实接口，任何失败都原样弹 Toast。
 */
async function investFetchBoard(accountName) {
  if (investMockEnabled()) {
    return investMockBoard(accountName);
  }
  return await api("/api/invest/board?account=" + encodeURIComponent(accountName));
}

async function investFetchPlatforms() {
  if (investMockEnabled()) {
    const board = invest.board || investMockBoard(invest.accountName);
    return (board.platforms || []).map(function (platform) {
      return { id: platform.id, name: platform.name };
    });
  }
  const data = await api("/api/invest/platforms?account=" + encodeURIComponent(invest.accountName));
  return data.platforms || [];
}

async function investFetchLedger() {
  const data = await api("/api/records?account=" + encodeURIComponent(invest.accountName));
  return data.records || [];
}

/**
 * 标的研究索：**永远走后端联网查东财**。
 *
 * v0.13.4：搜索不再读本地字典——本地字典收录不全，只留作后端断网时的兜底，
 * 以后单独做成「自动补全标的资料」的功能。所以这里连 `investMockEnabled()`
 * 的分支都去掉了：曾经开着 `?investMock=1` 调试标志的浏览器会一直只搜字典，
 * 表现出来就是「输入中文名搜不到」。
 *
 * @returns {Promise<{items: Array, fallback: boolean, notice: string}>}
 */
async function investSearchSecurities(keyword) {
  const data = await api(
    "/api/invest/search?keyword=" + encodeURIComponent(keyword) + "&limit=" + INVEST_MAX_CANDIDATES
  );
  return {
    items: data.items || [],
    fallback: data.fallback === true || (data.items || []).some(function (item) {
      return item && item.source === "mock";
    }),
    notice: data.notice || "",
  };
}

/* ==================== 骨架与渲染 ==================== */

/** 看板骨架：不等数据先立起来，用户点完立刻有东西看 */
function investRenderSkeleton(accountName) {
  const tabs = INVEST_TABS.map(function (item) {
    const active = item.id === investActiveTab() ? " is-active" : "";
    return (
      '<button class="invest-tab' +
      active +
      '" type="button" role="tab" data-invest-tab="' +
      item.id +
      '" aria-selected="' +
      (active ? "true" : "false") +
      '">' +
      item.label +
      "</button>"
    );
  }).join("");

  const board = investBoardEl();
  if (!board) {
    return;
  }
  board.innerHTML =
    '<div class="invest-hero">' +
    '<div class="invest-hero-main">' +
    '<div class="invest-hero-stat">' +
    '<span class="invest-hero-label">总市值</span>' +
    '<strong class="invest-hero-value" id="invest-total-value">¥0.00</strong>' +
    "</div>" +
    '<div class="invest-hero-stat is-cash">' +
    '<span class="invest-hero-label" id="invest-cash-label">可用资金</span>' +
    '<strong class="invest-hero-cash" id="invest-cash-line">¥0.00</strong>' +
    "</div>" +
    "</div>" +
    '<div class="invest-hero-pl" id="invest-day-pl" title="暂未接入实时行情">' +
    '<span class="invest-pl-label">当日盈亏</span>' +
    '<span class="invest-pl-line">' +
    '<span class="invest-pl-amount" id="invest-day-pl-amount">' +
    INVEST_DAY_PL_PLACEHOLDER.amount +
    "</span>" +
    '<span class="invest-pl-percent" id="invest-day-pl-percent">' +
    INVEST_DAY_PL_PLACEHOLDER.percent +
    "</span>" +
    "</span>" +
    "</div>" +
    "</div>" +
    '<div class="invest-tabs" id="invest-tabs" role="tablist" aria-label="投资看板视图">' +
    tabs +
    '<span class="invest-tabs-tools">' +
    '<button class="btn btn-sm btn-primary" type="button" id="invest-add-btn">+ 新建持仓</button>' +
    '<button class="btn btn-sm btn-light" type="button" id="invest-refresh-btn">刷新</button>' +
    "</span>" +
    "</div>" +
    // v0.13.3：决策 B 下买入 / 清仓都不写 records，账单页翻不到，这是最容易被
    // 追问「我的钱去哪了」的地方。静态说明一句，不新增交互。
    '<p class="invest-board-note">买基金、清仓退款只影响这里的持仓和可用资金，不计入收支统计，账单页查不到。</p>' +
    '<div class="invest-pane" id="invest-pane-holdings" data-invest-pane="holdings" role="tabpanel">' +
    '<div class="invest-loading">正在加载持仓…</div>' +
    "</div>" +
    '<div class="invest-pane bill-feed bill-feed-scroll" id="invest-pane-ledger" data-invest-pane="ledger" role="tabpanel">' +
    '<div class="invest-loading">切到【流水】后加载</div>' +
    "</div>";

  investApplyTab(investActiveTab());
  investSetAccountTitle(accountName);
}

function investSetAccountTitle(accountName) {
  const title = investEl("detail-title");
  if (title) {
    title.textContent = accountName + " · 投资看板";
  }
}

/** 只切 .is-active，不动 DOM 结构（HANDOFF 已知坑：重建会摘掉 event.target） */
function investApplyTab(tab) {
  const active = tab === "ledger" ? "ledger" : "holdings";
  const tabs = investEl("invest-tabs");
  if (tabs) {
    tabs.querySelectorAll("[data-invest-tab]").forEach(function (button) {
      const on = button.getAttribute("data-invest-tab") === active;
      button.classList.toggle("is-active", on);
      button.setAttribute("aria-selected", on ? "true" : "false");
    });
  }
  const holdings = investEl("invest-pane-holdings");
  const ledger = investEl("invest-pane-ledger");
  if (holdings) {
    holdings.classList.toggle("is-active", active === "holdings");
  }
  if (ledger) {
    ledger.classList.toggle("is-active", active === "ledger");
  }
}

function investRenderHero(board) {
  const account = board.account || {};
  const total = investTotalMarketValue(board);
  const valueEl = investEl("invest-total-value");
  if (valueEl) {
    if (investState().amountHidden) {
      valueEl.textContent = "¥••••";
    } else {
      setAmountAnimated("invest-total:" + invest.accountName, valueEl, total);
    }
  }
  const cashEl = investEl("invest-cash-line");
  const cashLabelEl = investEl("invest-cash-label");
  if (cashLabelEl) {
    cashLabelEl.textContent = account.cash_label || "可用资金";
  }
  if (cashEl) {
    const balance = investNumber(account.balance, 0);
    cashEl.textContent = investState().amountHidden ? "¥••••" : money(balance);
    // 可用资金为 0 时给一句能点的引导，避免"钱去哪了"的疑虑
    cashEl.classList.toggle("is-zero", !investState().amountHidden && balance <= 0);
  }
  const pl = investDayPl(board);
  const amountEl = investEl("invest-day-pl-amount");
  const percentEl = investEl("invest-day-pl-percent");
  const wrapEl = investEl("invest-day-pl");
  if (amountEl) {
    amountEl.textContent = pl.amountText;
  }
  if (percentEl) {
    percentEl.textContent = pl.percentText;
  }
  if (wrapEl) {
    wrapEl.classList.toggle("is-placeholder", !pl.available);
    wrapEl.classList.toggle("is-up", pl.available && pl.amountText.indexOf("+") === 0);
    wrapEl.classList.toggle("is-down", pl.available && pl.amountText.indexOf("-") === 0);
    wrapEl.setAttribute(
      "title",
      pl.available ? "当日盈亏（已接入行情）" : "暂未接入实时行情"
    );
  }
}

/**
 * 接口失败时的 Hero 态：显示「—」而不是 ¥0.00。
 *
 * v0.13.3：账户实际有 ¥28,500，接口一失败顶部大数字却显示 ¥0.00，
 * 很容易被误读成"我这个账户没钱了"。数字是"不知道"的时候就该说不知道。
 */
function investRenderHeroUnknown() {
  const valueEl = investEl("invest-total-value");
  if (valueEl) {
    valueEl.textContent = INVEST_UNKNOWN_AMOUNT;
  }
  const cashEl = investEl("invest-cash-line");
  if (cashEl) {
    cashEl.textContent = "可用资金 " + INVEST_UNKNOWN_AMOUNT;
  }
  const amountEl = investEl("invest-day-pl-amount");
  if (amountEl) {
    amountEl.textContent = INVEST_UNKNOWN_AMOUNT;
  }
  const percentEl = investEl("invest-day-pl-percent");
  if (percentEl) {
    percentEl.textContent = "";
  }
  const wrapEl = investEl("invest-day-pl");
  if (wrapEl) {
    wrapEl.classList.add("is-placeholder");
    wrapEl.classList.remove("is-up", "is-down");
    wrapEl.setAttribute("title", "持仓加载失败，暂无数据");
  }
}

/**
 * 单个持仓行的 HTML。
 *
 * @param {object} holding 持仓数据
 * @param {boolean} plAvailable 后端是否真的接了行情。false 时浮动盈亏恒等于
 *   「成本 vs 用成本价假算的市值」，永远是 0.00% —— 那是凑出来的数字，必须显示「—」。
 *   注意：本函数被 Array.map 调用时会收到 (item, index, array)，务必用匿名函数包一层再传参。
 */
function investHoldingRowHtml(holding, plAvailable) {
  const name = investText(holding.name);
  const ticker = String(holding.ticker || "").trim();
  const hasTicker = ticker.length > 0;
  const shares = investNumber(holding.shares, 0);
  const costPrice = investNumber(holding.cost_price, 0);
  const marketValue = investHoldingMarketValue(holding);
  const costTotal = investNumber(holding.cost_total, 0);
  // 成本口径的浮动盈亏（不是当日盈亏），与后端 cost_total / market_value 同源
  const profit = cents(marketValue - costTotal);
  const profitPercent =
    costTotal > 0 ? cents((profit / costTotal) * 100) : 0;

  return (
    '<div class="invest-holding" data-holding="' +
    investText(holding.id) +
    '" data-platform="' +
    investText(holding.platform_id) +
    '">' +
    '<span class="invest-holding-main">' +
    '<span class="invest-holding-name">' +
    name +
    (hasTicker
      ? '<span class="invest-holding-ticker" title="代码 ' +
        investText(ticker) +
        '">' +
        investText(ticker) +
        "</span>"
      : "") +
    "</span>" +
    '<span class="invest-holding-sub">' +
    investSharesText(shares) +
    " 份 · 成本 " +
    money(costPrice) +
    " · " +
    investAssetLabel(holding.asset_type) +
    "</span>" +
    "</span>" +
    '<span class="invest-holding-right">' +
    '<span class="invest-holding-value">' +
    (investState().amountHidden ? "¥••••" : money(marketValue)) +
    "</span>" +
    // v0.13.3 U2：原来这一块是把「当日盈亏」占位塞在每一行里，和下面的浮动盈亏
    // 形成两组 0.00% 并排；而当日盈亏是**账户级**指标，顶部 Hero 已经有了，
    // 行内重复没有信息增量，删掉。金额与百分比之间统一加一个空格，和顶部写法一致。
    '<span class="invest-holding-cost' +
    (plAvailable === false ? "" : profit > 0 ? " is-up" : profit < 0 ? " is-down" : "") +
    '" title="相对成本的浮动盈亏">' +
    (plAvailable === false
      ? INVEST_UNKNOWN_AMOUNT
      : (profit >= 0 ? "+" : "-") +
        money(Math.abs(profit)) +
        " (" +
        (profit >= 0 ? "+" : "-") +
        Math.abs(profitPercent).toFixed(2) +
        "%)") +
    "</span>" +
    '<span class="invest-holding-ops">' +
    '<button class="invest-holding-del" type="button" data-del-holding="' +
    investText(holding.id) +
    '" title="删除持仓（资金退回可用）">删除</button>' +
    "</span>" +
    "</span></div>"
  );
}

function investPlatformHtml(platform, plAvailable) {
  const id = String(platform.id);
  const holdings = platform.holdings || [];
  const collapsed = investIsPlatformCollapsed(platform.id);
  const platformValue = Number.isFinite(Number(platform.market_value))
    ? cents(platform.market_value)
    : holdings.reduce(function (sum, item) {
        return sum + investHoldingMarketValue(item);
      }, 0);

  // 不能用 holdings.map(investHoldingRowHtml)：那样第二个参数会被 map 填成数组下标
  const rows = holdings.length
    ? holdings
        .map(function (holding) {
          return investHoldingRowHtml(holding, plAvailable);
        })
        .join("")
    : '<div class="invest-platform-empty">这个平台下还没有持仓，点右上角「+ 新建持仓」</div>';

  return (
    '<div class="invest-platform' +
    (collapsed ? " is-collapsed" : "") +
    '" data-platform="' +
    investText(id) +
    '">' +
    '<div class="invest-platform-head" data-platform-toggle="' +
    investText(id) +
    '" role="button" tabindex="0" aria-expanded="' +
    (collapsed ? "false" : "true") +
    '">' +
    '<span class="invest-platform-name">' +
    investText(platform.name) +
    "</span>" +
    '<span class="invest-platform-meta">' +
    '<span class="invest-platform-count">' +
    holdings.length +
    " 个持仓</span>" +
    '<span class="invest-platform-value">' +
    (investState().amountHidden ? "¥••••" : money(platformValue)) +
    "</span>" +
    "</span>" +
    INVEST_CHEVRON +
    "</div>" +
    '<div class="invest-platform-body">' +
    rows +
    "</div></div>"
  );
}

function investRenderHoldings(board) {
  const pane = investEl("invest-pane-holdings");
  if (!pane) {
    return;
  }
  const platforms = board.platforms || [];
  /*
   * v0.13.3 T05：后端新建投资账户会**自动预建一个空的「默认」平台**，
   * 所以「刚建的投资账户」拿到的是 platforms:[{name:"默认", holdings:[]}] 而不是 []。
   * 空态必须按「所有平台的持仓加起来是不是 0」判断，否则新账户会显示一个空的
   * 「默认」分组，而不是「还没有持仓」的引导文案。
   */
  const holdingCount = platforms.reduce(function (sum, platform) {
    return sum + ((platform.holdings || []).length);
  }, 0);
  if (holdingCount === 0) {
    pane.innerHTML =
      '<div class="invest-empty">' +
      '<div class="invest-empty-art" aria-hidden="true">' +
      '<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M8 34l10-9 7 6 15-16"/>' +
      '<path d="M8 40h32"/>' +
      "</svg></div>" +
      '<p class="invest-empty-title">还没有持仓</p>' +
      '<p class="invest-empty-hint">先填「投入金额」，填了成本单价会自动算出份额；' +
      "扣款来源选现金或微信，钱会先转入这个投资账户再买入。</p>" +
      '<button type="button" class="btn btn-sm btn-primary invest-empty-btn" data-invest-empty-add>+ 新建第一笔持仓</button>' +
      '<p class="invest-empty-note">买基金、清仓退款只影响这里的持仓和可用资金，不计入收支统计。</p>' +
      "</div>";
    return;
  }
  const total = investTotalMarketValue(board);
  // U2：行内的浮动盈亏要不要显示真实百分比，取决于后端有没有真的接行情；
  // 没接的时候 market_value 是用 cost_price 假算的，盈亏恒为 0.00%（凑出来的）。
  const plAvailable = Boolean(((board || {}).day_pl || {}).available);
  const cost = Number.isFinite(Number(board.total_cost))
    ? cents(board.total_cost)
    : (board.platforms || []).reduce(function (sum, platform) {
        return (
          sum +
          (platform.holdings || []).reduce(function (inner, holding) {
            return inner + investNumber(holding.cost_total, 0);
          }, 0)
        );
      }, 0);
  const profit = cents(total - cost);

  pane.innerHTML =
    '<div class="invest-summary">' +
    '<span class="invest-summary-item">总市值 <strong>' +
    (investState().amountHidden ? "¥••••" : money(total)) +
    "</strong></span>" +
    '<span class="invest-summary-item">投入成本 <strong>' +
    (investState().amountHidden ? "¥••••" : money(cost)) +
    "</strong></span>" +
    '<span class="invest-summary-item">浮动盈亏 <strong class="' +
    (profit > 0 ? "is-up" : profit < 0 ? "is-down" : "") +
    '">' +
    (investState().amountHidden
      ? "¥••••"
      : (profit >= 0 ? "+" : "-") + money(Math.abs(profit))) +
    "</strong></span>" +
    "</div>" +
    '<div class="invest-platforms" id="invest-platforms">' +
    // 同样不能用 platforms.map(investPlatformHtml)：第二个参数会被填成下标
    platforms
      .map(function (platform) {
        return investPlatformHtml(platform, plAvailable);
      })
      .join("") +
    "</div>";
}

function investRenderLedger() {
  const pane = investEl("invest-pane-ledger");
  if (!pane) {
    return;
  }
  if (!invest.ledgerRecords.length) {
    pane.innerHTML = feedEmptyHtml("这个账户还没有流水");
    return;
  }
  const ordered = invest.ledgerRecords.slice().sort(function (a, b) {
    return String(b.date || "").localeCompare(String(a.date || ""));
  });
  try {
    pane.innerHTML = feedGroupsHtml(ordered, balanceSnapshots(ordered), {
      empty: "这个账户还没有流水",
    });
  } catch (error) {
    // balanceSnapshots 依赖 state.accounts；账户还没加载完时退化为不带余额快照
    pane.innerHTML = feedGroupsHtml(ordered, {}, { empty: "这个账户还没有流水" });
  }
}

async function investLoadLedger(force) {
  if (invest.ledgerLoaded && !force) {
    investRenderLedger();
    return;
  }
  const pane = investEl("invest-pane-ledger");
  if (pane && !invest.ledgerLoaded) {
    pane.innerHTML = '<div class="invest-loading">正在加载流水…</div>';
  }
  try {
    invest.ledgerRecords = await investFetchLedger();
    invest.ledgerLoaded = true;
    investRenderLedger();
  } catch (error) {
    if (pane) {
      pane.innerHTML = feedEmptyHtml("流水加载失败：" + (error && error.message ? error.message : "请稍后重试"));
    }
  }
}

/* ==================== 双 Tab 切换 ==================== */

/**
 * 切换视图：只切 .is-active，不重建任何 pane DOM。
 * 流水 pane 首次激活时懒加载一次，之后命中缓存只切 class。
 */
function switchInvestTab(tab) {
  const next = tab === "ledger" ? "ledger" : "holdings";
  investSetActiveTab(next);
  investApplyTab(next);
  if (next === "ledger") {
    investLoadLedger(false).catch(function () {
      // 失败提示已在内部渲染
    });
  }
}

/* ==================== 看板主入口 ==================== */

/**
 * 渲染投资看板。
 * @param {string} accountName 投资账户名（accounts.type === 'investment'）
 */
async function renderInvestBoard(accountName) {
  const board = investBoardEl();
  if (!board) {
    return;
  }
  invest.accountName = accountName;
  const holder = investState();
  if (holder.invest) {
    holder.invest.accountName = accountName;
  }
  invest.ledgerLoaded = false;
  invest.ledgerRecords = [];
  invest.board = null;
  invest.platforms = [];

  board.hidden = false;
  investRenderSkeleton(accountName);

  const seq = invest.requestSeq + 1;
  invest.requestSeq = seq;

  try {
    const data = await investFetchBoard(accountName);
    // 期间用户切了别的账户 → 丢弃这次结果
    if (seq !== invest.requestSeq || invest.accountName !== accountName) {
      return;
    }
    invest.board = data;
    invest.platforms = data.platforms || [];
    investRenderHero(data);
    investRenderHoldings(data);
    // 当前就在流水 Tab 时（比如刷新后仍停在流水）顺手补一次
    if (investActiveTab() === "ledger") {
      await investLoadLedger(true);
    }
  } catch (error) {
    if (seq !== invest.requestSeq || invest.accountName !== accountName) {
      return;
    }
    investRenderHoldings({ platforms: [], total_market_value: 0, total_cost: 0 });
    // v0.13.3：拉不到数据时金额是"不知道"，不是"0"——显示 ¥0.00 会被误读成账户没钱
    investRenderHeroUnknown();
    const pane = investEl("invest-pane-holdings");
    if (pane) {
      pane.innerHTML =
        '<div class="invest-empty"><p class="invest-empty-title">持仓加载失败</p>' +
        '<p class="invest-empty-hint">' +
        investText(error && error.message ? error.message : "请稍后重试") +
        "</p></div>";
    }
  }
}

/** 账户列表变了（改名 / 删除 / 新增）：账户没了就收起看板，还在就刷新 */
function investOnAccountsChanged() {
  if (!invest.accountName) {
    return;
  }
  const stillThere = (investState().accounts || []).some(function (account) {
    return account.name === invest.accountName;
  });
  if (!stillThere) {
    investResetBoard();
    return;
  }
  if (investActiveTab() === "ledger") {
    investLoadLedger(true).catch(function () {
      // 忽略：失败提示已在内部渲染
    });
  }
}

/** 账目变了（记一笔 / 转账 / 删除）：只刷新当前可见的那个视图 */
function investOnRecordChanged() {
  if (!invest.accountName) {
    return;
  }
  if (investActiveTab() === "ledger") {
    investLoadLedger(true).catch(function () {
      // 忽略
    });
  } else {
    renderInvestBoard(invest.accountName).catch(function () {
      // 忽略
    });
  }
}

/** 收起看板：隐藏容器并把内部缓存清干净 */
function investResetBoard() {
  const board = investBoardEl();
  if (board) {
    board.hidden = true;
  }
  invest.accountName = "";
  invest.board = null;
  invest.platforms = [];
  invest.ledgerRecords = [];
  invest.ledgerLoaded = false;
  const holder = investState();
  if (holder.invest) {
    holder.invest.accountName = "";
  }
}

/* ==================== 删除持仓（清仓撤销） ==================== */

/**
 * 按持仓 id 从当前看板缓存里取成本总额（废弃退款用）。
 * 缓存里找不到就返回 0 —— 调用方会退回不带金额的文案，不编数字。
 * @param {number|string} holdingId 持仓 id
 * @returns {number} 该持仓的成本总额（元，两位小数）
 */
function investHoldingCostTotal(holdingId) {
  const target = String(holdingId);
  let total = 0;
  (invest.platforms || []).forEach(function (platform) {
    (platform.holdings || []).forEach(function (holding) {
      if (String(holding.id) === target) {
        total = Number.isFinite(Number(holding.cost_total))
          ? Number(holding.cost_total)
          : 0;
      }
    });
  });
  return cents(total);
}

async function investDeleteHolding(holdingId) {
  const id = Number(holdingId);
  if (!Number.isFinite(id) || id <= 0) {
    return;
  }
  // v0.13.3：决策 B 下删除持仓**不写 records**（QA 实测 records 19→19）。
  // 旧文案写「并记一笔收入」是在承诺一个不存在的东西，改成如实描述退多少钱。
  const refund = investHoldingCostTotal(id);
  const ok = await confirmAction({
    title: "删除持仓",
    text:
      refund > 0
        // money() 自带「¥」前缀，这里不能再手写一个，否则渲染成「¥¥100.00」
        ? "删除后按成本价退回 " + money(refund) + " 到账户可用资金，这笔不会出现在账单收支里。确定继续吗？"
        : "删除后按成本价退回对应金额到账户可用资金，这笔不会出现在账单收支里。确定继续吗？",
    confirmText: "确认删除",
  });
  if (!ok) {
    return;
  }
  try {
    // 删除（清仓退款）也是写操作，一律走真实接口，失败原样报错
    await api("/api/invest/holdings/" + id, { method: "DELETE" });
    toast("已删除持仓，资金已退回可用资金", "success");
    await renderInvestBoard(invest.accountName);
    if (typeof refresh === "function") {
      refresh().catch(function () {
        // 资产页整体刷新失败不影响看板
      });
    }
  } catch (error) {
    toast(error && error.message ? error.message : "删除失败", "error");
  }
}

/* ==================== 新建持仓弹窗 ==================== */

let holdingModalInstance = null;

function investHoldingModalEl() {
  return investEl("holding-modal");
}

function investHoldingModal() {
  const element = investHoldingModalEl();
  if (!element || !window.bootstrap) {
    return null;
  }
  if (!holdingModalInstance) {
    holdingModalInstance = window.bootstrap.Modal.getOrCreateInstance(element);
  }
  return holdingModalInstance;
}

/** 打开弹窗：填平台下拉、重置表单 */
async function openHoldingModal() {
  if (!invest.accountName) {
    toast("请先在左侧选一个投资账户", "warn");
    return;
  }
  const modal = investHoldingModal();
  if (!modal) {
    toast("弹窗组件未就绪，请刷新页面重试", "error");
    return;
  }
  investResetHoldingForm();
  investFillSourceSelect();
  modal.show();
  investFillPlatformSelect([]);
  // 这里必须传 DOM 元素：modal 是 bootstrap 实例，没有 querySelectorAll。
  investEnhanceSelects(investHoldingModalEl());
  try {
    const platforms = await investFetchPlatforms();
    invest.platforms = platforms;
    investFillPlatformSelect(platforms);
  } catch (error) {
    const select = investEl("holding-platform");
    if (select) {
      select.innerHTML =
        '<option value="0">（后端未就绪，将落到「' + INVEST_PLATFORM_DEFAULT + '」平台）</option>';
    }
  }
}

function investFillPlatformSelect(platforms) {
  const select = investEl("holding-platform");
  if (!select) {
    return;
  }
  const list = Array.isArray(platforms) ? platforms : [];
  if (!list.length) {
    select.innerHTML =
      '<option value="0">' + INVEST_PLATFORM_DEFAULT + "（自动创建）</option>";
    select.value = "0";
    return;
  }
  select.innerHTML = list
    .map(function (platform) {
      return (
        '<option value="' +
        investText(platform.id) +
        '">' +
        investText(platform.name) +
        "</option>"
      );
    })
    .join("");
  select.value = String(list[0].id);
  investRefreshSelectLabels();
}

/**
 * 扣款来源下拉：列出所有普通账户（现金 / 微信 / 银行卡…），
 * 投资账户自身不算来源（把钱从自己转给自己没有意义）。
 */
function investFillSourceSelect() {
  const select = investEl("holding-source");
  if (!select) {
    return;
  }
  const accounts = (typeof state !== "undefined" && Array.isArray(state.accounts)
    ? state.accounts
    : []
  ).filter(function (account) {
    const type = String((account && account.type) || "normal");
    return type !== "investment" && account && account.name !== invest.accountName;
  });
  const current = invest.accountName;
  const options = ['<option value="">投资账户可用资金</option>'];
  accounts.forEach(function (account) {
    const name = String(account.name || "");
    if (!name || name === current) {
      return;
    }
    const balance = investNumber(account.balance, 0);
    options.push(
      '<option value="' +
        investText(name) +
        '">' +
        investText(name) +
        "（" +
        money(balance) +
        "）</option>"
    );
  });
  select.innerHTML = options.join("");
  select.value = "";
  investRefreshSelectLabels();
}

function investResetHoldingForm() {
  const scope = investHoldingModalEl();
  if (scope && typeof clearFormErrors === "function") {
    clearFormErrors(scope);
  }
  const pairs = [
    ["holding-ticker", ""],
    ["holding-name", ""],
    ["holding-asset-type", "fund"],
    ["holding-shares", ""],
    ["holding-price", ""],
    ["holding-amount", ""],
    ["holding-dca-amount", ""],
    ["holding-dca-frequency", "monthly"],
    ["holding-dca-next", ""],
    ["holding-source", ""],
  ];
  pairs.forEach(function (pair) {
    const field = investEl(pair[0]);
    if (field) {
      field.value = pair[1];
    }
  });
  const dca = investEl("holding-dca-on");
  if (dca) {
    dca.checked = false;
  }
  invest.sharesAuto = true;
  investSyncAmounts("reset");
  investApplyDca();
  investRefreshSelectLabels();
  investHideCandidates();
  invest.candidates = [];
}

/* ---------- 金额 ↔ 份额 ↔ 单价 三方联动 ---------- */

/**
 * 读一个输入框里的数字，空串 / 非法值一律返回 NaN。
 * @param {string} id 输入框 id
 * @returns {number} 解析后的数字，或 NaN
 */
function investFieldNumber(id) {
  const field = investEl(id);
  const raw = String((field && field.value) || "").trim();
  if (!raw) {
    return NaN;
  }
  const value = Number(raw);
  return Number.isFinite(value) && value >= 0 ? value : NaN;
}

/** 金额 ÷ 单价 = 份额，保留 4 位（基金份额常见精度） */
function investSharesFromAmount(amount, price) {
  if (!(amount > 0) || !(price > 0)) {
    return NaN;
  }
  return Math.round((amount / price) * 10000) / 10000;
}

/**
 * 三方联动：改哪个就按哪个当"主输入"，另外两个跟着算。
 *
 * @param {"amount"|"price"|"shares"|"reset"} source 用户刚改的那个字段
 */
function investSyncAmounts(source) {
  const amountField = investEl("holding-amount");
  const priceField = investEl("holding-price");
  const sharesField = investEl("holding-shares");
  const amount = investFieldNumber("holding-amount");
  const price = investFieldNumber("holding-price");
  let shares = investFieldNumber("holding-shares");
  const hint = investEl("holding-calc-hint");
  const tag = investEl("holding-shares-tag");

  if (source === "reset") {
    invest.sharesAuto = true;
  } else if (source === "shares") {
    // 手填份额 → 反推金额
    invest.sharesAuto = false;
    if (shares > 0 && price > 0 && amountField) {
      const next = cents(shares * price);
      amountField.value = next ? next.toFixed(2) : "";
    }
  } else if (source === "amount" || source === "price") {
    if (invest.sharesAuto !== false || source === "price") {
      const next = investSharesFromAmount(amount, price);
      if (Number.isFinite(next) && sharesField) {
        sharesField.value = next ? String(next) : "";
        shares = next;
      }
      invest.sharesAuto = true;
    }
  }

  if (tag) {
    tag.textContent = invest.sharesAuto === false ? "手填" : "自动";
    tag.classList.toggle("is-manual", invest.sharesAuto === false);
  }
  if (hint) {
    if (!(amount > 0)) {
      hint.textContent = "先填投入金额，填了成本单价就会自动算出份额。";
    } else if (!(price > 0)) {
      hint.textContent = "再填一个成本单价，就能自动算出份额。";
    } else if (invest.sharesAuto === false && shares > 0) {
      hint.textContent =
        "已按手填份额反推金额：份额 " +
        shares +
        " × 单价 " +
        price.toFixed(4) +
        " = ¥" +
        cents(shares * price).toFixed(2);
    } else {
      hint.textContent =
        "¥" +
        amount.toFixed(2) +
        " ÷ ¥" +
        price.toFixed(4) +
        " = " +
        (Number.isFinite(shares) ? shares : 0) +
        " 份（份额可手动覆盖）";
    }
  }
}

/* ---------- 定投：下次扣款日（跳过周末） ---------- */

const INVEST_WEEK_LABELS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

/**
 * 把某个日期往后顺延到工作日（周六 → 下周一，周日 → 下周一）。
 * @param {Date} date 原始日期
 * @returns {Date} 工作日
 */
function investToWorkday(date) {
  const next = new Date(date.getTime());
  const day = next.getDay();
  if (day === 6) {
    next.setDate(next.getDate() + 2);
  } else if (day === 0) {
    next.setDate(next.getDate() + 1);
  }
  return next;
}

/**
 * 按频率推算下一次扣款日：从今天往后推一个周期，再顺延到工作日。
 *
 * @param {string} frequency weekly / biweekly / monthly / quarterly
 * @returns {string} YYYY-MM-DD
 */
function investNextDcaDate(frequency) {
  const today = new Date();
  const base = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const next = new Date(base.getTime());
  if (frequency === "weekly") {
    next.setDate(next.getDate() + 7);
  } else if (frequency === "biweekly") {
    next.setDate(next.getDate() + 14);
  } else if (frequency === "quarterly") {
    next.setMonth(next.getMonth() + 3);
  } else {
    next.setMonth(next.getMonth() + 1);
  }
  return investDateInputValue(investToWorkday(next));
}

/** Date → YYYY-MM-DD（本地时区，不用 toISOString 以免时区偏移） */
function investDateInputValue(date) {
  const pad = function (num) {
    return (num < 10 ? "0" : "") + num;
  };
  return (
    date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate())
  );
}

/**
 * `2026-11-05 (周四)` 这种带星期的人话格式。
 * @param {string} value YYYY-MM-DD
 * @returns {string} 带星期的标签，解析失败时原样返回
 */
function investDateHumanLabel(value) {
  const text = String(value || "");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) {
    return "";
  }
  const parts = text.split("-").map(Number);
  const date = new Date(parts[0], parts[1] - 1, parts[2]);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return text + " (" + INVEST_WEEK_LABELS[date.getDay()] + ")";
}

/** 把日期框的值同步成带星期的小字提示，周末会标注顺延 */
function investSyncDcaDateLabel() {
  const field = investEl("holding-dca-next");
  const label = investEl("holding-dca-next-label");
  if (!field || !label) {
    return;
  }
  const value = String(field.value || "").trim();
  if (!value) {
    label.textContent = "留空则按频率自动推算，落在周末会顺延到周一。";
    label.classList.remove("is-shifted");
    return;
  }
  const parts = value.split("-").map(Number);
  const date = new Date(parts[0], parts[1] - 1, parts[2]);
  const human = investDateHumanLabel(value);
  if (date.getDay() === 0 || date.getDay() === 6) {
    label.textContent = human + " 是周末，实际会顺延到 " + investDateInputValue(investToWorkday(date));
    label.classList.add("is-shifted");
  } else {
    label.textContent = human;
    label.classList.remove("is-shifted");
  }
}

function investApplyDca() {
  const on = !!(investEl("holding-dca-on") || {}).checked;
  const box = investEl("holding-dca-box");
  if (box) {
    box.classList.toggle("is-active", on);
  }
  if (!on) {
    return;
  }
  const field = investEl("holding-dca-next");
  const frequencyField = investEl("holding-dca-frequency");
  if (field && !String(field.value || "").trim()) {
    field.value = investNextDcaDate((frequencyField && frequencyField.value) || "monthly");
  }
  investSyncDcaDateLabel();
}

/* ---------- 自定义下拉：深色模式下原生 select 的白底会刺眼 ---------- */

/**
 * 把 select[data-inv-select] 升级成按钮 + 面板的自定义下拉。
 *
 * 原生 <select> 在 Windows 深色模式下，展开的选项列表由系统绘制，
 * CSS 改不动，白底会直接糊在深色弹窗上。这里保留原生 select 作为
 * **唯一数据源**（所有既有代码读 .value 都不受影响），只是把它藏起来，
 * 视觉层换成可以完全控制的按钮 + 面板。
 *
 * @param {Element} select 原生下拉
 */
function investEnhanceSelect(select) {
  if (!select || select.dataset.invEnhanced === "1") {
    if (select) {
      investRefreshSelectLabel(select);
    }
    return;
  }
  select.dataset.invEnhanced = "1";
  select.classList.add("inv-select-native");
  select.setAttribute("tabindex", "-1");

  const wrap = document.createElement("div");
  wrap.className = "inv-select";

  const button = document.createElement("button");
  button.type = "button";
  button.className = "inv-select-btn";
  button.setAttribute("aria-haspopup", "listbox");
  button.setAttribute("aria-expanded", "false");
  button.innerHTML =
    '<span class="inv-select-value"></span>' +
    '<svg class="inv-select-chevron" viewBox="0 0 16 16" fill="none" stroke="currentColor" ' +
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6l4 4 4-4"/></svg>';

  const panel = document.createElement("div");
  panel.className = "inv-select-panel";
  panel.innerHTML = '<div class="inv-select-list" role="listbox"></div>';

  wrap.appendChild(button);
  wrap.appendChild(panel);
  select.parentNode.insertBefore(wrap, select.nextSibling);

  button.addEventListener("click", function (event) {
    event.preventDefault();
    event.stopPropagation();
    const open = !wrap.classList.contains("is-open");
    investCloseSelects();
    if (!open) {
      return;
    }
    investRenderSelectPanel(select, wrap);
    wrap.classList.add("is-open");
    button.setAttribute("aria-expanded", "true");
  });

  panel.addEventListener("click", function (event) {
    const option = event.target.closest("[data-inv-value]");
    if (!option) {
      return;
    }
    event.stopPropagation();
    const value = option.getAttribute("data-inv-value");
    if (select.value !== value) {
      select.value = value;
      select.dispatchEvent(new Event("input", { bubbles: true }));
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
    investRefreshSelectLabel(select);
    investCloseSelects();
  });

  investRefreshSelectLabel(select);
}

/** 用当前 select 的 options 重建面板内容 */
function investRenderSelectPanel(select, wrap) {
  const list = wrap.querySelector(".inv-select-list");
  if (!list) {
    return;
  }
  list.innerHTML = Array.prototype.map
    .call(select.options, function (option) {
      const active = option.value === select.value ? " is-active" : "";
      return (
        '<button type="button" class="inv-select-item' +
        active +
        '" role="option" aria-selected="' +
        (option.value === select.value ? "true" : "false") +
        '" data-inv-value="' +
        investText(option.value) +
        '">' +
        investText(option.textContent) +
        "</button>"
      );
    })
    .join("");
}

/** 收起所有面板 */
function investCloseSelects() {
  document.querySelectorAll(".inv-select.is-open").forEach(function (wrap) {
    wrap.classList.remove("is-open");
    const btn = wrap.querySelector(".inv-select-btn");
    if (btn) {
      btn.setAttribute("aria-expanded", "false");
    }
  });
}

/** 把 select 当前选中项的文字同步到按钮上 */
function investRefreshSelectLabel(select) {
  if (!select || select.dataset.invEnhanced !== "1") {
    return;
  }
  const wrap = select.nextElementSibling;
  if (!wrap || !wrap.classList.contains("inv-select")) {
    return;
  }
  const text = wrap.querySelector(".inv-select-value");
  const option =
    select.options[select.selectedIndex] || (select.options.length ? select.options[0] : null);
  if (text) {
    text.textContent = option ? String(option.textContent) : "";
    text.classList.toggle("is-placeholder", !select.value);
  }
}

function investEnhanceSelects(root) {
  const scope = root || document;
  scope.querySelectorAll("select[data-inv-select]").forEach(investEnhanceSelect);
}

function investRefreshSelectLabels() {
  document.querySelectorAll("select[data-inv-select]").forEach(investRefreshSelectLabel);
}

/* ---------- 代码搜索：500ms 防抖 ---------- */

/**
 * 输入防抖：连续输入只在最后一次停手 500ms 后发一次请求。
 * @param {string} keyword 当前输入框内容
 */
function scheduleTickerSearch(keyword) {
  if (invest.searchTimer) {
    window.clearTimeout(invest.searchTimer);
    invest.searchTimer = null;
  }
  const text = String(keyword || "").trim();
  if (text.length < INVEST_SEARCH_MIN_LEN) {
    invest.candidates = [];
    investHideCandidates();
    return;
  }
  invest.searchTimer = window.setTimeout(function () {
    invest.searchTimer = null;
    runTickerSearch(text);
  }, INVEST_SEARCH_DEBOUNCE_MS);
}

async function runTickerSearch(keyword) {
  const seq = invest.searchSeq + 1;
  invest.searchSeq = seq;
  invest.searchFallback = false;
  invest.searchNotice = "";
  try {
    const result = await investSearchSecurities(keyword);
    if (seq !== invest.searchSeq) {
      return; // 已有更新的搜索发起
    }
    invest.candidates = result.items.slice(0, INVEST_MAX_CANDIDATES);
    invest.searchFallback = result.fallback;
    invest.searchNotice = result.notice;
    investRenderCandidates(invest.candidates);
  } catch (error) {
    if (seq !== invest.searchSeq) {
      return;
    }
    // 以前是静默隐藏候选框，用户只看到「打了字没反应」；现在把失败原因摆出来
    invest.candidates = [];
    investRenderCandidates([], "搜索失败，请检查网络后重试");
  }
}

/**
 * 渲染候选下拉。
 * @param {Array} items 候选标的
 * @param {string} [emptyHint] 空结果 / 失败时的提示文案
 */
function investRenderCandidates(items, emptyHint) {
  const box = investEl("holding-candidates");
  if (!box) {
    return;
  }
  if (!items.length) {
    box.innerHTML =
      '<div class="invest-candidate is-empty">' +
      investText(emptyHint || "没有匹配的标的，可直接手填名称") +
      "</div>";
    box.classList.add("show");
    return;
  }
  const noteHtml =
    invest.searchFallback && invest.searchNotice
      ? '<div class="invest-candidate is-empty">' + investText(invest.searchNotice) + "</div>"
      : "";
  box.innerHTML =
    noteHtml +
    items
    .map(function (item, index) {
      return (
        '<div class="invest-candidate" role="button" tabindex="0" data-candidate-index="' +
        index +
        '">' +
        '<span class="invest-candidate-ticker">' +
        investText(item.ticker || "—") +
        "</span>" +
        '<span class="invest-candidate-name">' +
        investText(item.name) +
        "</span>" +
        '<span class="invest-candidate-type">' +
        investAssetLabel(item.asset_type) +
        "</span>" +
        "</div>"
      );
    })
    .join("");
  box.classList.add("show");
}

function investHideCandidates() {
  const box = investEl("holding-candidates");
  if (box) {
    box.classList.remove("show");
    box.innerHTML = "";
  }
}

function investPickCandidate(index) {
  const item = invest.candidates[index];
  if (!item) {
    return;
  }
  const ticker = investEl("holding-ticker");
  const name = investEl("holding-name");
  const assetType = investEl("holding-asset-type");
  const price = investEl("holding-price");
  if (ticker) {
    ticker.value = item.ticker || "";
  }
  if (name) {
    name.value = item.name || "";
  }
  if (assetType && INVEST_ASSET_TYPES.indexOf(item.asset_type) >= 0) {
    assetType.value = item.asset_type;
  }
  if (price && Number(item.price) > 0) {
    price.value = Number(item.price).toFixed(4);
  }
  investHideCandidates();
  if (typeof clearFieldError === "function") {
    clearFieldError(name);
  }
  investRefreshSelectLabels();
  // 选中候选就把「金额 ÷ 新单价」重算一遍，并把光标送到还没填的金额框
  invest.sharesAuto = true;
  investSyncAmounts("price");
  const amountField = investEl("holding-amount");
  if (amountField && !String(amountField.value || "").trim()) {
    amountField.focus();
  }
}

/* ---------- 提交 ---------- */

/**
 * 把后端的中文报错映射到弹窗里的具体字段。
 *
 * 以前只认 "已存在" 这一个词，而 `_invest_status()` 判 409 用的是「已有/同名/还有」，
 * 余额不足、名称超长等也都没落框 —— QA 实测 `nameError=null`，弹窗里一个红字都没有。
 *
 * 映射不上时返回 null（只弹 Toast）：宁可少标一处，也不把一个不相干的报错
 * 挂到无关的输入框上误导用户。
 *
 * @param {string} message 后端原始报错
 * @returns {HTMLElement|null} 应该标红的那个字段
 */
function investErrorField(message) {
  const text = String(message || "");
  const name = investEl("holding-name");
  if (
    text.indexOf("请填写标的名称") >= 0 ||
    text.indexOf("标的名称不能超过") >= 0 ||
    text.indexOf("已有") >= 0 ||
    text.indexOf("同名") >= 0 ||
    text.indexOf("已存在") >= 0
  ) {
    return name;
  }
  if (text.indexOf("可用资金不足") >= 0 || text.indexOf("余额不足") >= 0) {
    // 钱不够一律指到金额框（份额是自动算出来的，不该背这个锅）
    return investEl("holding-amount");
  }
  if (text.indexOf("扣款来源") >= 0) {
    return investEl("holding-source");
  }
  if (text.indexOf("工作") >= 0) {
    return investEl("holding-dca-next");
  }
  if (text.indexOf("份额") >= 0) {
    return investEl("holding-shares");
  }
  if (text.indexOf("单价") >= 0) {
    return investEl("holding-price");
  }
  if (text.indexOf("平台") >= 0) {
    return investEl("holding-platform");
  }
  if (text.indexOf("定投") >= 0 || text.indexOf("每期金额") >= 0) {
    return investEl("holding-dca-amount");
  }
  return null;
}

function investCollectHoldingPayload() {
  const scope = investHoldingModalEl();
  const issues = [];
  const nameField = investEl("holding-name");
  const name = String((nameField && nameField.value) || "").trim();
  if (!name) {
    issues.push({ field: nameField, message: "请填写标的名称" });
  }
  if (name.length > 40) {
    issues.push({ field: nameField, message: "标的名称不能超过 40 个字" });
  }

  // 金额优先：金额必填，份额可手填也可由 金额 ÷ 单价 算出来。
  const amountField = investEl("holding-amount");
  const priceField = investEl("holding-price");
  const sharesField = investEl("holding-shares");
  let amount = investFieldNumber("holding-amount");
  let price = investFieldNumber("holding-price");
  let shares = investFieldNumber("holding-shares");

  if (!Number.isFinite(amount) || amount <= 0) {
    issues.push({ field: amountField, message: "投入金额必须大于 0" });
  }
  if (Number.isFinite(price) && price <= 0) {
    price = NaN;
  }
  if (Number.isFinite(shares) && shares <= 0) {
    shares = NaN;
  }
  // 单价留空：按 1.0000 记账（老口径 D7，只给金额也能保存）
  if (!Number.isFinite(price)) {
    price = 1;
  }
  // 份额留空：金额 ÷ 单价
  if (!Number.isFinite(shares)) {
    shares = investSharesFromAmount(amount, price);
    if (!Number.isFinite(shares) || shares <= 0) {
      shares = amount;
    }
  }
  if (Number.isFinite(amount) && Number.isFinite(shares) && Number.isFinite(price)) {
    // 金额与 份额×单价 对齐，避免小数误差导致可用资金差几厘
    const implied = cents(shares * price);
    if (implied > 0) {
      amount = implied;
    }
  }

  let dca = null;
  if (!!(investEl("holding-dca-on") || {}).checked) {
    const dcaAmountField = investEl("holding-dca-amount");
    const dcaAmount = Number(String((dcaAmountField && dcaAmountField.value) || "").trim());
    if (!Number.isFinite(dcaAmount) || dcaAmount <= 0) {
      issues.push({ field: dcaAmountField, message: "定投每期金额必须大于 0" });
    }
    const frequencyField = investEl("holding-dca-frequency");
    const frequency = String((frequencyField && frequencyField.value) || "monthly");
    if (INVEST_DCA_FREQUENCIES.indexOf(frequency) < 0) {
      issues.push({ field: frequencyField, message: "定投频率不合法" });
    }
    const nextField = investEl("holding-dca-next");
    let nextDate = String((nextField && nextField.value) || "").trim();
    if (nextDate && !/^\d{4}-\d{2}-\d{2}$/.test(nextDate)) {
      issues.push({ field: nextField, message: "下次扣款日期须为 YYYY-MM-DD" });
    }
    if (!nextDate) {
      nextDate = investNextDcaDate(frequency);
    } else {
      // 用户挑到周末就顺延到周一，前端先纠正一次，后端还会校验
      const picked = nextDate.split("-").map(Number);
      const pickedDate = new Date(picked[0], picked[1] - 1, picked[2]);
      if (pickedDate.getDay() === 0 || pickedDate.getDay() === 6) {
        nextDate = investDateInputValue(investToWorkday(pickedDate));
      }
    }
    dca = { amount: cents(dcaAmount), frequency: frequency, next_date: nextDate };
  }

  if (typeof reportIssues === "function" && reportIssues(scope, issues)) {
    return null;
  }

  const platformSelect = investEl("holding-platform");
  const platformId = Number((platformSelect && platformSelect.value) || 0);
  const tickerField = investEl("holding-ticker");
  const assetField = investEl("holding-asset-type");
  const sourceSelect = investEl("holding-source");

  return {
    account: invest.accountName,
    platform_id: Number.isFinite(platformId) && platformId > 0 ? platformId : undefined,
    ticker: String((tickerField && tickerField.value) || "").trim(),
    name: name,
    asset_type: String((assetField && assetField.value) || "fund"),
    shares: shares,
    cost_price: price,
    amount: amount,
    source_account: String((sourceSelect && sourceSelect.value) || "").trim(),
    dca: dca,
  };
}

async function submitHolding() {
  const payload = investCollectHoldingPayload();
  if (!payload) {
    return;
  }
  if (!lockAction("invest-create-holding")) {
    return;
  }
  const button = investEl("holding-save-btn");
  const original = button ? button.textContent : "";
  if (button) {
    button.disabled = true;
    button.textContent = "保存中…";
  }
  try {
    // 写库永远走真实接口（T05：不允许静默回落成本地假数据，否则用户看到"成功"实际没落库）
    const data = await api("/api/invest/holdings", jsonOptions("POST", payload));
    // 后端对同平台同名标的是「加权加仓」，不返 409：added=true 表示加仓，false 表示新建
    const added = Boolean(data && data.added === true);
    const shownName = (data && data.holding && data.holding.name) || payload.name;
    toast(added ? "已加仓，份额与成本已更新：" + shownName : "建仓成功：" + shownName, "success");
    const modal = investHoldingModal();
    if (modal) {
      hideModalSafe(modal, investHoldingModalEl());
    }
    await renderInvestBoard(invest.accountName);
    if (typeof refresh === "function") {
      refresh().catch(function () {
        // 资产页整体刷新失败不影响看板
      });
    }
  } catch (error) {
    const raw = error && error.message ? String(error.message) : "";
    const message = investFriendlyError(error, "建仓");
    // U1：后端返回的中文报错要落到**具体字段下方**的红字上，不能只有一个 2 秒 Toast。
    // Toast 同时保留 —— 双通道，不是替换：用户可能正盯着页面别处。
    const field = investErrorField(raw);
    if (field && typeof setFieldError === "function") {
      setFieldError(field, message);
      if (typeof field.focus === "function") {
        field.focus();
      }
    }
    toast(message, "error");
  } finally {
    unlockAction("invest-create-holding");
    if (button) {
      button.disabled = false;
      button.textContent = original || "保存";
    }
  }
}

/* ==================== 事件绑定 ==================== */

function investBindBoardEvents() {
  const board = investBoardEl();
  if (!board) {
    return;
  }

  board.addEventListener("click", function (event) {
    const tab = event.target.closest("[data-invest-tab]");
    if (tab) {
      switchInvestTab(tab.getAttribute("data-invest-tab"));
      return;
    }
    const addBtn = event.target.closest("#invest-add-btn, [data-invest-empty-add]");
    if (addBtn) {
      openHoldingModal();
      return;
    }
    const refreshBtn = event.target.closest("#invest-refresh-btn");
    if (refreshBtn) {
      if (investActiveTab() === "ledger") {
        investLoadLedger(true).catch(function () {
          // 忽略
        });
      } else {
        renderInvestBoard(invest.accountName).catch(function () {
          // 忽略
        });
      }
      return;
    }
    const delBtn = event.target.closest("[data-del-holding]");
    if (delBtn) {
      event.stopPropagation();
      investDeleteHolding(delBtn.getAttribute("data-del-holding"));
      return;
    }
    const head = event.target.closest("[data-platform-toggle]");
    if (head) {
      investTogglePlatform(Number(head.getAttribute("data-platform-toggle")));
      // 只切父级 .is-collapsed，不重建平台内 DOM（同 Tab 纪律）
      const wrap = head.closest(".invest-platform");
      if (wrap) {
        wrap.classList.toggle(
          "is-collapsed",
          investIsPlatformCollapsed(Number(head.getAttribute("data-platform-toggle")))
        );
        head.setAttribute(
          "aria-expanded",
          wrap.classList.contains("is-collapsed") ? "false" : "true"
        );
      }
      return;
    }
    // 流水 pane 复用账单流的三级折叠（年 / 月 / 日）
    const feedHeader = event.target.closest("[data-collapse]");
    if (feedHeader && event.target.closest("#invest-pane-ledger")) {
      toggleCollapseState(investFeedCollapseKey(), feedHeader.getAttribute("data-collapse-key"));
      investRenderLedger();
    }
  });

  board.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" && event.key !== " " && event.key !== "Spacebar") {
      return;
    }
    const head = event.target.closest("[data-platform-toggle]");
    if (!head) {
      return;
    }
    event.preventDefault();
    head.click();
  });
}

function investBindModalEvents() {
  const modal = investHoldingModalEl();
  if (!modal) {
    return;
  }
  investEnhanceSelects(modal);
  // 点面板外面把自定义下拉收起来（和分类浮层同样的坑：别在 handler 里重建 DOM）
  document.addEventListener("click", function (event) {
    if (event.target && !event.target.closest(".inv-select")) {
      investCloseSelects();
    }
  });

  modal.addEventListener("click", function (event) {
    const candidate = event.target.closest("[data-candidate-index]");
    if (candidate) {
      investPickCandidate(Number(candidate.getAttribute("data-candidate-index")));
      return;
    }
    if (event.target.closest("#holding-save-btn")) {
      submitHolding();
    }
  });

  modal.addEventListener("input", function (event) {
    // U1：改动哪个字段就把哪个字段的红字撤掉，不用等到下次提交才刷新
    if (event.target && event.target.id && typeof clearFieldError === "function") {
      clearFieldError(event.target);
    }
    if (event.target && event.target.id === "holding-ticker") {
      scheduleTickerSearch(event.target.value);
    }
    // 金额 / 单价 / 份额 三方联动：只认用户刚动的那一个当主输入
    if (event.target && event.target.id === "holding-amount") {
      investSyncAmounts("amount");
    }
    if (event.target && event.target.id === "holding-price") {
      investSyncAmounts("price");
    }
    if (event.target && event.target.id === "holding-shares") {
      investSyncAmounts("shares");
    }
  });

  modal.addEventListener("change", function (event) {
    // 下拉 / 单选也走 input 之外的 change，这里同样清红字
    if (event.target && event.target.id && typeof clearFieldError === "function") {
      clearFieldError(event.target);
    }
    if (event.target && event.target.id === "holding-dca-on") {
      investApplyDca();
    }
    if (event.target && event.target.id === "holding-dca-frequency") {
      // 换频率就重算下次扣款日（用户手动改过的日期以用户为准，这里只在为空时补）
      const field = investEl("holding-dca-next");
      if (field && !String(field.value || "").trim()) {
        field.value = investNextDcaDate(event.target.value);
      }
      investSyncDcaDateLabel();
    }
    if (event.target && event.target.id === "holding-dca-next") {
      investSyncDcaDateLabel();
    }
  });

  // 候选下拉里的 Enter / Esc 键盘操作
  modal.addEventListener("keydown", function (event) {
    const box = investEl("holding-candidates");
    if (event.key === "Escape") {
      investHideCandidates();
      return;
    }
    if (
      event.key === "Enter" &&
      box &&
      box.classList.contains("show") &&
      invest.candidates.length
    ) {
      event.preventDefault();
      investPickCandidate(0);
      return;
    }
    // 弹窗内 Enter 提交（输入框在候选关闭时）
    if (event.key === "Enter" && event.target && event.target.tagName !== "BUTTON") {
      event.preventDefault();
      submitHolding();
    }
  });

  // 点弹窗空白处收起候选下拉（不用全局 document 监听，避免摘 DOM 后误收）
  modal.addEventListener("mousedown", function (event) {
    if (!event.target.closest(".invest-search-wrap")) {
      investHideCandidates();
    }
  });

  // U4：弹窗一打开，焦点落在第一个输入框（代码），进来就能直接打字。
  // Bootstrap 的 autofocus 在 tabindex="-1" 的容器上不稳定，所以自己来一次。
  modal.addEventListener("shown.bs.modal", function () {
    if (typeof clearFormErrors === "function") {
      clearFormErrors(modal);
    }
    const first = investEl("holding-ticker");
    if (first && !first.disabled) {
      // 延后一帧：Modal 动画期间抢焦点会被 Bootstrap 强行拉回对话框，导致焦点丢失
      window.setTimeout(function () {
        if (first.isConnected && modal.classList.contains("show")) {
          first.focus();
        }
      }, 60);
    }
  });
}

function investBindGlobalEsc() {
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape" || event.isComposing) {
      return;
    }
    const modal = investHoldingModalEl();
    if (modal && modal.classList.contains("show")) {
      investHideCandidates();
      const instance = investHoldingModal();
      if (instance) {
        instance.hide();
      }
    }
  });
}

/* ==================== v0.13.3：AI 投资建仓确认卡（T03） ====================
 *
 * SSE 事件序列：thinking → extracting_amount → resolving_invest → need_confirm。
 * 后端推到 need_confirm 就停，**此时没有写任何库**。
 * 用户点「确认建仓」后由前端直接 POST /api/invest/holdings ——
 * 与手动新建持仓弹窗**同一个入账口**（设计 D10），AI 不另开一条写库路径。
 */

/**
 * 确认卡默认选中哪个投资账户。
 *
 * 优先级：用户当前正打开的账户（且它是投资账户）> AI 给的那个 > 第一个投资账户。
 * v0.13.3：以前直接拿 AI 回填的 `parsed.account`，而它是后端兜的「第一个投资账户」，
 * 与用户当前所在的账户无关 —— QA 实测「正开着 QA3闭环户，卡上默认却是余额宝」。
 *
 * @param {string} suggested AI 归一化给出的账户名
 * @param {Array<string>} accounts 该用户的投资账户名列表
 * @returns {string} 应当默认选中的账户名；没有投资账户时返回空串
 */
function investPreferredAccount(suggested, accounts) {
  const list = (accounts || []).filter(Boolean);
  if (!list.length) {
    return String(suggested || "").trim();
  }
  let opened = "";
  try {
    // state 是 script.js 的顶层 const，经典脚本里可直接读；读不到就跳过这条优先级
    if (typeof state !== "undefined" && state) {
      opened = String(state.detailAccount || "").trim();
    }
  } catch (error) {
    opened = "";
  }
  if (opened && list.indexOf(opened) >= 0) {
    return opened;
  }
  const candidate = String(suggested || "").trim();
  if (candidate && list.indexOf(candidate) >= 0) {
    return candidate;
  }
  return list[0];
}

/**
 * AI 投资建仓确认卡入口，由 script.js 的 runAiStream 在收到 need_confirm 时调用。
 * @param {object} bubble script.js 的气泡对象
 * @param {string} text 用户原始输入（取消时塞回输入框）
 * @param {object} payload SSE 事件体：{status, action, parsed, candidates}
 */
function handleInvestConfirm(bubble, text, payload) {
  if (!bubble || bubble.removed || !bubble.element) {
    return;
  }
  const parsed = (payload && payload.parsed) || {};
  const accounts = (parsed.invest_accounts || []).filter(Boolean);
  // v0.13.3：默认账户必须是"用户当前正打开的那个"，而不是 AI 顺手挑的第一个。
  // 否则用户明明在 A 账户里说「买入 1000」，卡上却默认选中 B 账户，极易建错地方扣错钱。
  const preferredAccount = investPreferredAccount(parsed.account, accounts);
  if (!preferredAccount) {
    if (typeof bubbleFinish === "function") {
      bubbleFinish(bubble, {
        title: "无法建仓",
        message: "还没有投资账户，请先在账户管理里把某个账户设为投资账户",
        error: true,
      });
    }
    if (typeof restoreAiInput === "function") {
      restoreAiInput(text);
    }
    return;
  }

  const main = bubble.element.querySelector(".bubble-main");
  if (!main || main.querySelector(".invest-confirm")) {
    return;
  }

  const titleElement = bubble.element.querySelector(".bubble-title");
  if (titleElement) {
    titleElement.textContent = "确认建仓";
  }
  // 有确认卡的气泡必须常驻，三秒淡出会把按钮带走
  bubble.noFade = true;
  if (bubble.countdownTimer) {
    window.clearTimeout(bubble.countdownTimer);
    bubble.countdownTimer = null;
  }
  const progress = bubble.element.querySelector(".bubble-progress");
  if (progress) {
    progress.classList.add("d-none");
  }
  if (typeof bubbleWriteText === "function") {
    bubbleWriteText(bubble, "AI 识别出这是一笔投资买入，请核对后建仓", false);
  }

  const card = document.createElement("div");
  card.className = "invest-confirm";
  card.setAttribute("data-locked", "0");
  card.innerHTML =
    '<div class="invest-confirm-rows">' +
    investConfirmRow("标的", investText(parsed.invest_name || "—")) +
    investConfirmRow("代码", investText(parsed.ticker || "—")) +
    investAccountRow(preferredAccount, accounts) +
    investConfirmRow("金额", money(parsed.amount || 0)) +
    // 单价是 D7 占位（price_assumed）时不显示「单价 ¥1.00」：那不是真实净值，
    // 显示出来会被当成"这只基金 1 块钱一股"，改说清楚口径。
    investConfirmRow(
      "份额",
      investSharesText(parsed.shares) +
        " 份" +
        (parsed.price_assumed ? "" : "（单价 " + money(parsed.price || 0) + "）")
    ) +
    "</div>" +
    (parsed.price_assumed
      ? '<p class="invest-confirm-note">没识别出单价，按「份额 = 金额」记录；以后可在持仓里改份额</p>'
      : "") +
    '<div class="invest-confirm-actions">' +
    '<button type="button" class="invest-confirm-ok">确认建仓</button>' +
    '<button type="button" class="invest-confirm-cancel">取消</button>' +
    "</div>" +
    '<p class="invest-confirm-error" hidden></p>';
  main.appendChild(card);

  // 气泡浮在页面底部：卡内点击不能触发「打开账单详情」，也不能被全局快捷键截走
  ["click", "mousedown", "keydown"].forEach(function (type) {
    card.addEventListener(type, function (event) {
      event.stopPropagation();
    });
  });

  const okButton = card.querySelector(".invest-confirm-ok");
  const cancelButton = card.querySelector(".invest-confirm-cancel");
  const errorElement = card.querySelector(".invest-confirm-error");

  okButton.addEventListener("click", function () {
    submitAiInvestConfirm(bubble, parsed, card, okButton, errorElement);
  });
  cancelButton.addEventListener("click", function () {
    card.setAttribute("data-locked", "1");
    if (typeof bubbleFinish === "function") {
      bubbleFinish(bubble, {
        title: "已取消建仓",
        message: "这笔买入没有保存，原文已放回输入框",
        error: true,
      });
    }
    if (typeof restoreAiInput === "function") {
      restoreAiInput(text);
    }
  });
}

function investConfirmRow(label, value) {
  return (
    '<div class="invest-confirm-row"><span class="invest-confirm-label">' +
    investText(label) +
    '</span><span class="invest-confirm-value">' +
    value +
    "</span></div>"
  );
}

/** 账户行：只有一个投资账户就显示文本，有多个才给下拉，让用户能改 */
function investAccountRow(current, accounts) {
  const list = (accounts || []).filter(Boolean);
  if (list.length <= 1) {
    return investConfirmRow("账户", investText(current || list[0] || "—"));
  }
  const options = list
    .map(function (name) {
      return (
        '<option value="' +
        investText(name) +
        '"' +
        (name === current ? " selected" : "") +
        ">" +
        investText(name) +
        "</option>"
      );
    })
    .join("");
  return (
    '<div class="invest-confirm-row"><span class="invest-confirm-label">账户</span>' +
    '<select class="invest-confirm-account" aria-label="建仓账户">' +
    options +
    "</select></div>"
  );
}

/**
 * 确认建仓：走 POST /api/invest/holdings（与手动弹窗同一个入账口）。
 *
 * 防重复扣款三重保险：
 *   1) card 上的 data-locked 在**任何 await 之前**同步置位，连点第二次直接 return；
 *   2) lockAction() 并发锁（script.js），跨调用也只放行一次；
 *   3) 按钮 setButtonBusy 置灰，视觉上不再可点。
 */
async function submitAiInvestConfirm(bubble, parsed, card, button, errorElement) {
  if (card.getAttribute("data-locked") === "1") {
    return;
  }
  card.setAttribute("data-locked", "1");

  const select = card.querySelector(".invest-confirm-account");
  // 只有一个投资账户时 investAccountRow 渲染的是纯文本（没有 select），这时必须
  // 回落到 investPreferredAccount 算出的那个，否则单账户场景会退成 AI 给的账户名。
  const account = String(
    (select && select.value) ||
      investPreferredAccount(parsed.account, (parsed.invest_accounts || []).filter(Boolean)) ||
      ""
  ).trim();
  if (!account) {
    card.setAttribute("data-locked", "0");
    investConfirmError(errorElement, "请先选择一个投资账户");
    return;
  }

  if (typeof lockAction === "function" && !lockAction("invest-ai-confirm")) {
    return;
  }
  const original = button ? button.textContent : "";
  if (button && typeof setButtonBusy === "function") {
    setButtonBusy(button, true, "建仓中…");
  } else if (button) {
    button.disabled = true;
  }

  const amount = cents(parsed.amount || 0);
  const body = {
    account: account,
    ticker: String(parsed.ticker || "").trim(),
    name: String(parsed.invest_name || "").trim(),
    asset_type: String(parsed.asset_type || "fund"),
    shares: Number(parsed.shares || 0),
    cost_price: Number(parsed.price || 0),
    amount: amount,
  };
  // platform_id 只有确认存在时才传，否则让后端自动落「默认」平台（D：一个持仓必属某平台）

  try {
    // 写库永远走真实接口：AI 确认与手动建仓是**同一个入账口**，不另开旁路
    const data = await api("/api/invest/holdings", jsonOptions("POST", body));
    const added = Boolean(data && data.added === true);

    if (typeof toast === "function") {
      toast(
        added ? "已加仓，份额与成本已更新：" + body.name : "建仓成功：" + body.name,
        "success"
      );
    }
    // 建仓成功就把卡片锁死：按钮置灰 + 加 .is-done，杜绝「成功后又点一次」的二次扣款
    card.classList.add("is-done");
    card.querySelectorAll("button, select").forEach(function (control) {
      control.disabled = true;
    });
    if (typeof bubbleFinish === "function") {
      bubbleFinish(bubble, {
        title: "建仓成功",
        message: body.name + " 已买入 " + money(amount) + "，可用资金已扣减",
      });
    }
    if (typeof refresh === "function") {
      refresh().catch(function () {
        // 资产页整体刷新失败不影响本次建仓结果
      });
    }
    if (typeof window.investOnRecordChanged === "function") {
      window.investOnRecordChanged();
    }
  } catch (error) {
    const message = investFriendlyError(error, "建仓");
    // 可用资金不足要留着卡让用户改账户/金额，其余错误直接收尾
    investConfirmError(errorElement, message);
    card.setAttribute("data-locked", "0");
    if (typeof toast === "function") {
      toast(message, "error");
    }
  } finally {
    if (typeof unlockAction === "function") {
      unlockAction("invest-ai-confirm");
    }
    if (button && typeof setButtonBusy === "function") {
      setButtonBusy(button, false);
    } else if (button) {
      button.disabled = false;
    }
    if (button && original) {
      button.textContent = original;
    }
  }
}

/**
 * 把 fetch / 网络的原始英文报错换成用户看得懂的中文，**并说明钱有没有动**。
 *
 * 业务类报错（可用资金不足 / 不是投资账户 / 名称超长…）后端已经是我们自己的中文，
 * 原样透传，不加工 —— 那类文案里带着用户要照着改的具体数字。
 *
 * @param {Error} error 抛出的错误
 * @param {string} action 动作名，用于拼兜底文案（"建仓" / "删除"）
 * @returns {string} 可直接展示给用户看的文案
 */
function investFriendlyError(error, action) {
  const raw = error && error.message ? String(error.message) : "";
  const label = action || "操作";
  if (!raw) {
    return label + "失败，请稍后重试";
  }
  // 网络层才有的指纹；命中时明确告诉用户"没扣钱"，避免他以为钱没了又点一次
  if (
    raw.indexOf("Failed to fetch") >= 0 ||
    raw.indexOf("NetworkError") >= 0 ||
    raw.indexOf("network") >= 0 ||
    raw.indexOf("timeout") >= 0
  ) {
    return "网络不太稳定，这次没有扣款，可以再试一次";
  }
  return raw;
}

function investConfirmError(element, message) {
  if (!element) {
    return;
  }
  element.hidden = false;
  element.textContent = message;
}

/* ==================== 对外入口 ==================== */

window.renderInvestBoard = renderInvestBoard;
window.investOnAccountsChanged = investOnAccountsChanged;
window.investOnRecordChanged = investOnRecordChanged;
window.openHoldingModal = openHoldingModal;
window.switchInvestTab = switchInvestTab;
window.investResetBoard = investResetBoard;
window.handleInvestConfirm = handleInvestConfirm;
window.isInvestmentAccount = isInvestmentAccount;

/**
 * 判断一个账户是不是投资账户。
 * 唯一开关是 accounts.type === 'investment'（设计 D1）。
 * 后端还没下发 type 字段时（联调期），退化为按 group_name==='投资账户' 判定，
 * 与迁移步 2 的回填口径一致，避免联调期看板打不开。
 */
function isInvestmentAccount(account) {
  if (!account) {
    return false;
  }
  if (account.type !== undefined && account.type !== null && account.type !== "") {
    return account.type === "investment";
  }
  return account.group_name === "投资账户";
}

investBindBoardEvents();
investBindModalEvents();
investBindGlobalEsc();
