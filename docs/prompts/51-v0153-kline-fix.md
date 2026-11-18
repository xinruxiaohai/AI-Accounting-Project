# 51 · v0.15.3 K 线副图轴与 dataZoom 渲染异常修复 · Agent E

> 交付对象：Agent E（投资 K 线模块负责人）。
> 本文件与聊天里贴出的提示词同内容，agent 可自查细节。

---

## 〇、开工第一句必须自报

动手之前先回一句：

> 「我是 Agent E，本轮只修 K 线图渲染异常：副图成交量轴串刻度、dataZoom 与副图重叠。产出只涉及 static/invest-v0133.js 与 static/invest-kline-v0143.css。」

只要输出里开始出现 `CATEGORY_SEEDS`、`CATEGORY_ICON_RULES`、`data-mode`、`权限管理`、`BRAND_LOGO_LABELS`，就是串任务了，立刻停下说明。

---

## 一、必读（全部为绝对路径）

| 文件 | 作用 |
|---|---|
| `D:\Project\project01 AI-Accounting\docs\HANDOFF.md` | 「二、并行 Agent 协作声明」+ 已知坑 |
| `D:\Project\project01 AI-Accounting\static\invest-v0133.js` | K 线全部前端逻辑（3418 行） |
| `D:\Project\project01 AI-Accounting\static\invest-kline-v0143.css` | K 线弹窗样式（204 行） |
| `D:\Project\project01 AI-Accounting\invest_eastmoney.py` | 行情抓取（490 行 `fetch_kline`） |
| `D:\Project\project01 AI-Accounting\invest_mock.py` | 降级模拟曲线（298 行 `synthetic_kline`） |

---

## 二、根因（我已实证，**不要重复排查**）

用户截图：基金「易方达蓝筹精选混合 005827」K 线弹窗，主图价格轴 1.350~1.560 正常，**底部却出现 0 / 0.5 / 1 三个刻度**，成交量柱不可见，底部一个蓝色大矩形。用户描述是「偶尔」出现。

**这不是偶发渲染 bug，是「基金没有成交量」造成的确定性结果：**

1. 场外基金走的不是股票 K 线接口，而是净值曲线聚合 → `invest_eastmoney.py:435` `_aggregate_fund_nav()`，
   其返回的每一个 point 里 **`volume` 恒为 0**（第 445 行、第 486 行两处硬编码 `"volume": 0`）。
   响应里 `source` 为 `"eastmoney-fund"`（`invest_eastmoney.py:527`）。
2. 前端 `static/invest-v0133.js:2812` `investKlineOption(points)` **无条件**渲染成交量副图：
   - `grid[1]` 固定 `height: 54`、`bottom: 66`（第 2891~2894 行）→ 没有成交量也占着 54px，主图被压；
   - `yAxis[1]` 带 `scale: true`（第 2932 行）；
   - `series` 里 `bar` 用 `volumes`，而 `volumes` 由 `investKlineNum(point.volume)` 得来（第 2824 行），全为 0。
3. **全 0 数据 + `scale:true` → ECharts 自动把 min/max 算成 0~1，刻度就是 `0 / 0.5 / 1`。**
   这与用户截图底部那三个数字完全一致，是根因铁证。
4. 柱子高度 0 → 肉眼看是「没有成交量」；`dataZoom` slider（`bottom:14, height:20`，第 2957~2966 行）
   的 `fillerColor: rgba(67,56,202,0.12)` 在副图占位被压到时表现为底部那块蓝矩形。
5. 为什么「偶尔」：**股票 / ETF 有真实成交量 → 正常；场外基金 volume 恒 0 → 异常**。
   所以同一份代码在不同标的上表现不同，不是随机。

---

## 三、白名单（越界即停）

**允许修改：**

| 路径 | 范围 |
|---|---|
| `D:\Project\project01 AI-Accounting\static\invest-v0133.js` | 仅 K 线段：`investKlineNum`(2576)、`investKlinePriceText`(2581)、`investKlineVolumeText`(2589)、`investKlineRender`(2996~3010)、`investKlineOption`(2812~2995)。其余一律不碰 |
| `D:\Project\project01 AI-Accounting\static\invest-kline-v0143.css` | 仅 `.ik-chart-wrap` / `#invest-kline-chart` 相关；可追加，不要改 21~90 行已定稿的弹窗骨架 |
| `D:\Project\project01 AI-Accounting\app.py` | **仅当** `/api/invest/kline`（第 3399 行）返回结构确实缺字段时才改；优先在前端解决 |
| `D:\Project\project01 AI-Accounting\invest_eastmoney.py` | **仅当**需要给基金响应加 `has_volume: false` 标识时才改 `_aggregate_fund_nav`(435) 或 `fetch_kline`(490) 的返回体；**不许改抓取逻辑、不许新增请求** |

**禁止：**

- `D:\Project\project01 AI-Accounting\templates\index.html` —— **A 正在改这个文件（未提交，含主题双模式 UI），一个字都不许动**；
- `D:\Project\project01 AI-Accounting\static\v0151-theme.css` —— 同上，A 占用；
- `D:\Project\project01 AI-Accounting\static\script.js` —— F 的分类图标区（约 8100~8300）；
- `D:\Project\project01 AI-Accounting\static\auth-v012.js`、`database.py`、`ai_service.py`、`static\style.css`；
- 版本号（`APP_VERSION_FALLBACK = "v0.15.2"` / 33 处 `?v=0.15.2` / `CACHE_NAME` / `ASSET_VERSION`）；
- `manifest.json`、`service-worker.js`、`git push`、`git add -A`。

---

## 四、修复要求

### 1) 无成交量时必须「整块隐藏副图」，而不是只隐藏柱子

当 `points` 全部 `volume <= 0`（或响应 `source === "eastmoney-fund"`）时：

- 只渲染 **一个 grid**：`{ left: 62, right: 18, top: 24, bottom: 56 }`（不写死 height，让它自适应容器）；
- 不生成 `xAxis[1]`、`yAxis[1]`、成交量 `bar` series（数组长度各为 1 / 2 即可）；
- `dataZoom` 的 `xAxisIndex` 改为 `[0]`；
- tooltip 的「成交量」行自动省略（现在 `investKlineVolumeText(0)` 返回 `—`，可保留但更好是整行不显示）。

### 2) 有成交量时：刻度必须关闭、绝不出现 0/0.5/1

- `yAxis[1]` 增加 `min: 0`；`axisLabel.show: false`、`splitLine.show: false`（与主图分开，不要在副图印数字）；
- `grid[1]` 改为相对高度（如 `height: "18%"`）+ `bottom: 62`，与主图 `height: "58%"` 拉开，
  不允许出现「副图压住主图」或「副图被 dataZoom 压住」。

### 3) dataZoom 固定在底部，不叠在任何图上

- slider `bottom: 10, height: 18`；
- `inside` 与 `slider` 的 `xAxisIndex` 必须与实际渲染的 xAxis 数量一致（1 个就 `[0]`，2 个才 `[0,1]`）；
- 容器 `#invest-kline-chart` 建议给固定高度（如 320px），CSS 写在 `static\invest-kline-v0143.css`。

### 4) 横轴拥挤与边界

- 数据点 > 180 时 `xAxis.axisLabel.interval` 自适应（保留现有 `rotate: 42` + `hideOverlap: true`）；
- 边界三态都要不崩、不出现 0 刻度：
  - 空数据（`points.length === 0`）→ 走既有 `investKlineShowState("empty", ...)`；
  - 单点（1 根）→ 不崩、不出现 min==max 的空白；
  - 停牌 / 净值无波动（open=close=high=low 全部相同）→ 主图 yAxis 因 `scale:true` 会算成 min==max，
    需要给 `min`/`max` 加 ±0.5% 的 padding，否则轴刻度异常。

---

## 五、验收（必须交数字 + 截图，不许只写「已修复」）

**断言（写进脚本，打印结果）：**

1. 基金 005827 日线（`klt=101`）打开 K 线：
   - `chart.getOption().yAxis.length === 1`、`series.length === 1`、`grid.length === 1`；
   - 截图中**不存在** `0` / `0.5` / `1` 三个刻度（用 OCR 或目视 + 断言 option 里无第二个 yAxis 双证）。
2. 股票/ETF（任一有成交量的标的，如 `510300`）日线：
   - `yAxis.length === 2` 且 `yAxis[1].axisLabel.show === false`；
   - 成交量柱 `series[1].data` 存在非 0 值，柱子肉眼可见。
3. 日 / 周 / 月三周期各切一次，零 console error、零 404。
4. 边界三态（空数据 / 单点 / 停牌）各跑一次，无异常抛出、无 0 刻度。
5. dataZoom 拖到中段再拖到最右，副图与 slider 不重叠（用 `getBoundingClientRect()` 断言
   `grid[1]` 底部 < slider 顶部）。

**截图（至少 3 张，放 `D:\Project\temp\invest-kline\shots\`）：**

| 文件名 | 内容 |
|---|---|
| `01-fund-005827-day.png` | 基金日线，**底部无 0/0.5/1**，主图占满高度 |
| `02-etf-510300-day.png` | ETF 日线，成交量柱可见、副图无数字 |
| `03-fund-zoom-mid.png` | 基金日线 dataZoom 拖到中段，验证不重叠 |

---

## 六、环境（这台机器的坑，照做省两小时）

- 项目 venv 的 base Python 3.12 已被移除，用 uv 的：
  `C:/Users/19370/AppData/Roaming/uv/python/cpython-3.12.14-windows-x86_64-none/python.exe`
- 起隔离服务（已设 `ZHZ_SQLITE_PATH`，端口 5077）：
  `D:\Project\temp\entity-icons\serve.py`
  ⚠️ **任何 python 进程 `import app` 前必须先设 `ZHZ_SQLITE_PATH`**，否则 `init_db()` 会重写主库
  （G、F、D 都踩过，均靠 `records.db.bak-*` 逐字恢复）。
- 浏览器只有 Edge，**必须 `--headless`**（`--headless=new` 会立刻退出，exit 0 但无产物）；
  **服务和浏览器必须与 node 脚本写在同一次 shell 调用里**，否则进程会被回收。
- CDP 连接与登录注入可直接抄 `D:\Project\temp\entity-icons\cdp.mjs`（59/59 跑通过）：
  - token：`D:\Project\temp\biz-v0151\token_v0151.txt`
  - user：`D:\Project\temp\biz-v0151\user_v0151.json`
  - localStorage 键：`ai_accounting_token` / `ai_accounting_user`
  - 弹窗入口：`switchPage('assets')` → 点投资账户 → 持仓行 → K 线弹窗
  - 图表实例：`echarts.getInstanceByDom(document.getElementById("invest-kline-chart"))`

---

## 七、红线

- 不改表结构、不改后台业务路由、不碰 `script.js`/`index.html`/`v0151-theme.css`、不 bump 版本号；
- 测试产物全放 `D:\Project\temp\invest-kline\`，脚本、截图、隔离库副本都在这里；
- 禁 `/register`，只用 `test@test.com`（本地 uid 93）与 `temp_cdp_v0140@example.com`（uid 90），JWT `sub` 必须是字符串；
- 主库 `D:\Project\project01 AI-Accounting\records.db` md5 必须保持 `211d49e67eaf25c9383b2d6d116e18a7`（测前测后各打一次）；
- 不要用 AI 生成的假 K 线图凑验收，必须走真实接口（`/api/invest/kline`）+ 真实浏览器截图。

---

## 八、交付

文件清单（改动文件 + 行数）、根因复述一句（证明你自己验证过，不是照抄）、5 项断言逐条结果、
3 张截图路径、遗留风险；`git add` 只加自己改的文件，不 push，不 bump 版本。

提交信息：`fix(invest): v0.15.3 修复基金无成交量时副图轴 0/0.5/1 刻度与 dataZoom 重叠`
