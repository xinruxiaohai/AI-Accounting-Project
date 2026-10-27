# AI 记账管家 · 项目交接文件（HANDOFF）

> 生成时间：2026-10-26　｜　用途：跨会话无损接续　｜　请连同「终极蓝图」一起发给新会话
>
> 本文件已在 2026-10-26 20:20 左右于本机**实测核验**（git / SQLite / Flask 路由），
> 凡与旧记录不符处均已按实测修正，并在文中标注「〔核验〕」。

## 零、交接核验快照（2026-10-26 实测，优先于任何口述记忆）

**Git**

- 当前分支 `main`，HEAD = **`5cc22ca`** `feat: complete calendar views and UX polish`
- 标签：`v0.01-DEV v0.02-DEV v0.03-DEV v0.04-DEV v0.05-DEV v0.06-DEV`（`v0.06.1` 尚未打）
- `git status --short`：

  ```
   M static/script.js
   M static/style.css
   M templates/index.html
  ```

  未提交差异 **+698 / −112 行**（script.js +551/−95、style.css +127/−0、index.html +20/−17）。
  **这批未提交改动 = v0.06.1 Step 1「防呆 + Loading + 快捷键 + 空态」已经写进工作区，但没提交。**
  详见第九节。

**运行能力**（未启动常驻服务，用 Flask test_client 打真实路由）

| 检查 | 结果 |
|---|---|
| `node --check static/script.js` | 通过（exit 0） |
| `python -m py_compile app.py database.py` | 通过（exit 0） |
| `GET /health` | 200 `{"health":"good"}` |
| `GET /` | 200，20032 bytes，正常渲染 |
| `GET /api/records` | 200，`count: 11` |
| `GET /api/statistics` | 200 `{"balance_total":2883.2,"expense_total":830.03,"income_total":100.01}` |
| `GET /api/accounts` | 200，6 个账户 |
| `GET /api/categories` | 200，树形返回 |
| script.js 引用的 57 个元素 id | 全部在 index.html 中存在（无缺失） |

**数据库实测**（`records.db`）

- 账目 **11 条**，时间全在 `2026-10`
- 收入合计 `100.01`、支出合计 `830.03`、总余额 `2883.20`（与统计接口一致）
- 分类 **24 条**，一级 7 个：餐饮 / 交通 / 购物 / 娱乐 / 居住 / 其他 / 卫浴
- 账户 **6 个**〔核验修正：旧记录写 8 个〕：

  | 大类 | 账户 | 余额 |
  |---|---|---|
  | 储蓄账户 | 招行卡 | 100.00 |
  | 投资账户 | 余额宝 | 0.00 |
  | 资金账户 | 微信 | 78.20（库内存 `78.19999999999999`，显示前必须 `round(x,2)`） |
  | 资金账户 | 支付宝 | 100.00 |
  | 资金账户 | 现金 | -796.00 |
  | 资金账户 | 银行卡 | 3401.00 |

  旧记录里的「建行卡」「基金」并不存在（未创建或被删）。负余额属正常（收支允许负余额）。
- 根目录另有 `.env`（0 字节，已在 .gitignore），`venv\`、`records.db` 均被忽略。

## 一、项目定位与硬约束

- 项目：《基于多模态大模型的 AI 记账管家》，传智杯 AI 创新应用挑战赛参赛作品
- 形态：浏览器 Web 应用（PC 端后台管理布局，**不做手机底部导航**）
- 技术栈（已锁定，不得引入框架级依赖）：Flask 单文件 `app.py` + SQLite（标准库 sqlite3）+ 原生 HTML/CSS/JS + Bootstrap 5（**本地 vendor，不用 CDN**）+ math.js（本地）
- 明确排除：Flask 工厂函数、Blueprint、SQLAlchemy、前端框架（Vue/React）、eval
- 用户角色设定：AI 是「Python Flask 开发导师」，用户是大一新生（C 语法过关、Python 边做边学）
- 交互硬规则：
  1. 后台直接写**完整可运行**代码，绝不写片段
  2. 聊天框只报「改了哪个文件、替换/新增哪几个函数」+ **3 条核心测试点**，不贴全量代码
  3. 严格按 Step 推进，**每步自审后停下等验收**，禁止一口气写完
  4. 需求有歧义或把握不足 99% 时必须先提问

## 二、环境与运行

| 项 | 值 |
|---|---|
| 项目根 | `D:\Project\AI-Accounting-Project` |
| Python | `D:\Project\AI-Accounting-Project\venv\Scripts\python.exe`（Python 3.12.10） |
| 依赖 | flask 3.1.3（requirements.txt 仅 `flask>=3.0`） |
| 数据库 | 同目录 `records.db`（不进 Git，已在 .gitignore） |
| 服务 | 启动后为 `http://127.0.0.1:5000`（debug 模式，改 .py 自动重载并重跑 init_db）〔核验〕交接时**服务未在运行**，需手动启动 |

启动（PowerShell）：

```powershell
cd /d D:\Project\AI-Accounting-Project
.\venv\Scripts\python.exe app.py
```

验证：`curl.exe -s http://127.0.0.1:5000/health` → `{"health":"good"}`

## 三、目录结构

```
D:\Project\AI-Accounting-Project\
├─ app.py                 # 路由与校验（Flask 单文件）
├─ database.py            # 数据层（连接、建表/迁移、CRUD、统计）
├─ requirements.txt
├─ .gitignore
├─ .env                   # 空文件，忽略
├─ records.db             # 运行数据（忽略）
├─ templates\index.html   # 单页应用（四页 + 三个弹窗）
├─ static\
│  ├─ style.css
│  ├─ script.js
│  └─ vendor\             # bootstrap.min.css / bootstrap.bundle.min.js / math.min.js
└─ docs\
   ├─ HANDOFF.md          # 本文件
   ├─ dev-log.md
   ├─ bugs-and-solutions.md
   └─ prompts\            # 01~08 各版本 Prompt 快照（比赛要求）
```

## 四、数据模型（当前最终形态）

**records**
| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK | 自增 |
| amount | REAL | 正数；实际方向由 type 决定 |
| category | TEXT | 冗余显示名（改名时同步） |
| category_id | INTEGER NULL | 指向 categories.id |
| account | TEXT | 账户名（冗余） |
| to_account | TEXT DEFAULT '' | 转账转入账户 |
| fee | REAL DEFAULT 0 | 转账手续费 |
| type | TEXT DEFAULT 'expense' | expense / income / transfer |
| formula | TEXT DEFAULT '' | 原始算式（如 15.5+20*2） |
| date | TEXT | `YYYY-MM-DD HH:MM`（旧数据 10 位，读时补 `00:00`） |
| note | TEXT DEFAULT '' | 备注 |

**categories**：`id, name, parent_id(自关联)`，唯一索引 `uq_categories ON (COALESCE(parent_id,0), name)`，最多两级

**accounts**：`name TEXT PK, balance REAL, group_name TEXT DEFAULT '资金账户'`，大类固定三种：资金账户 / 储蓄账户 / 投资账户

## 五、后端 API

| 方法 | 路径 | 要点 |
|---|---|---|
| GET | `/` | 渲染 index.html（注入 categories 一级、accounts、now） |
| GET | `/health` | 健康检查 |
| GET/POST | `/api/records` | 列表支持 `?account=` `?category_id=` `?parent_id=`；POST 校验后写库并联动余额 |
| PUT/DELETE | `/api/records/<int:id>` | PUT **整条覆盖**；DELETE 回滚余额 |
| GET | `/api/statistics` | `income_total / expense_total / balance_total`（总余额取 accounts 求和） |
| GET/POST | `/api/accounts` | POST `{name, group_name, balance}` |
| PUT/DELETE | `/api/accounts/<name>` | 改余额/大类；有账目时删除返回 409 |
| GET/POST | `/api/categories` | POST `{name, parent_id?}`；树形返回 |
| PUT/DELETE | `/api/categories/<int:id>` | 改名同步 records.category；有子分类/账目时 409 |

业务规则（不可回退的决策）：

- 余额联动：income `+amount`、expense `-amount`、transfer `转出 -(amount+fee)` / `转入 +amount`，同一事务内完成
- 编辑 = 先撤销旧账 → 再校验新账 → 再加新账（校验失败整体回滚）
- **余额不足只拦截转账**，收支允许负余额（"如实记录"原则）
- 转账要求转出/转入账户**真实存在**（不自动建账户，防写进空气）
- 业务错误统一 400 + `{"error": "中文说明"}`；冲突 409

## 六、前端结构

**单页四区**（`.page` + `data-page`）：`page-home` / `page-calendar` / `page-assets` / `page-profile`
**三个弹窗**：`#record-modal`（记账）、`#account-modal`（新增账户）、`#category-modal`（分类管理）
**关键 id**：`record-list` / `day-records` / `account-records` / `account-list` / `calendar-grid` / `calendar-year-grid` / `toast-stack` / `amount-hint` / `cal-stat-income|expense|net` / `cal-prev|next|year-btn`

前端约定：

- 所有提示走 `toast(msg, "success"|"error")`，**全站 0 次 alert()**
- 金额框 `type="text"`，可输算式；`amountFromInput()` 用 math.js 求值（纯数字走快速路径），保存时提交 `amount` + `formula`
- 表格行编辑/删除用**事件委托**（`[data-action="edit|delete"]`）
- 日历：月视图按天汇总，`is-income`(绿) / `is-expense`(红) / `is-mixed`(斜切) / `is-selected`；年视图 12 格
- 长文本备注 `.note-cell` 省略号

## 七、已完成里程碑

| 版本 | 内容 | 提交 |
|---|---|---|
| v0.01-DEV | 环境、SQLite CRUD、前端极简 UI | `v0.01-DEV → da15180` |
| v0.02-DEV | 文档体系、Prompt 快照、踩坑记录 | `v0.02-DEV → 4187022` |
| v0.03-DEV | account 字段、DELETE、统计卡、Bootstrap、PUT 编辑、收支+账户余额+资产页 | `v0.03-DEV → aefa523` |
| v0.04-DEV | 分钟级时间、PC 后台布局、联调 34 条断言 | `v0.04-DEV → 767187f` |
| v0.05-DEV | 二级分类、账户大类、分类/账户增删、资产页联动 | `v0.05-DEV → bb83bd8` |
| v0.06-DEV | 转账、手续费、公式计算器、全局 Toast | `v0.06-DEV → 92bf701` |
| 日历重构 | 三卡 / 红绿格 / 年月切换 / 年视图 / 点天看明细 + 公式静默 | **已提交 `5cc22ca`**（tag 未打，建议命名 `v0.06.1-DEV` 或先补 `v0.06.0-DEV`） |
| **v0.06.1-DEV Step 1** | 防呆 + Loading + Enter/Esc + Skeleton/空态 | **已写进工作区，未提交、未验收**（见第九节） |

## 八、当前数据基线〔核验〕

- 11 条账目，全部在 2026-10
- 总收入 `100.01`、总支出 `830.03`、总余额 `2883.20`
- 分类 24 条（一级：餐饮/交通/购物/娱乐/居住/其他/卫浴）
- 账户 **6 个**分三组（资金：现金 -796.00 / 微信 78.20 / 支付宝 100.00 / 银行卡 3401.00；储蓄：招行卡 100.00；投资：余额宝 0.00）

## 九、下一步：v0.06.1-DEV Step 1（**代码已存在，待验收 + 待提交**）

全站表单防呆与交互，5 项需求：

1. 必填项 label 加红 `*`（金额/分类/账户/时间/转入账户/账户名/大类/分类名）
2. 提交时拦截空项并用 Toast 提示（指名缺哪一项）
3. 优雅 Loading：按钮内嵌 spinner + 「保存中…」，**不禁用按钮**，用 JS 并发锁防狂点
4. 快捷键：弹窗内 Enter 提交、Esc 关闭
5. 全局兜底：表格加载 Skeleton 遮罩；无数据显示「暂无数据」图标

〔核验〕工作区未提交改动**已经把 5 项全部实现**，落点如下（新会话请勿重写）：

| 文件 | 新增/改动 |
|---|---|
| `static/script.js` | `fieldHolder()` L127、`setFieldError()` L137、`clearFieldError()` L155、`clearFormErrors()` L171、`reportIssues()` L189、`lockAction()` L213、`unlockAction()` L221、`setButtonBusy()` L229（spinner + 保存中…，不禁用）、`emptyStateInner()` L259、`emptyStateHtml()` L274、`emptyBlockHtml()` L281、`skeletonRowsHtml()` L285、`beginTableLoad()` L304、`groupsSkeletonHtml()` L322、`beginGroupsLoad()` L341、`bindEnterSubmit()` L362、`bindErrorClearing()` L385、`bindEscClose()` L404、`collectRecordValues()` L1485、`collectAccountValues()` L1539、`collectCategoryValues()` L1562 |
| `templates/index.html` | 5 处 label 加 `<span class="req">*</span>`；三个 modal 加 `data-bs-keyboard="true"`；分类弹窗新增 `.category-add-wrap` + label；侧栏版本号改 `v0.06.1-DEV` |
| `static/style.css` | `.req` L902、`.field-error` L909、`.empty-state` L950、`.skeleton-row td` L987、`.account-card.is-skeleton` L1011/1019/1023 |

已完成的机器核验：`node --check` 通过、`py_compile` 通过、6 条路由全 200、JS 引用的 57 个 id 在 HTML 中全存在。

**还缺（下一步的工作）**：

1. 真机交互验收（浏览器里点一遍：spinner 是否内嵌、连点是否被锁、Enter/Esc、Skeleton 是否闪一下、空态图）
2. 验收通过后 `git commit`（建议信息 `feat: add form guards, loading states and modal shortcuts`）并打 `v0.06.1-DEV`
3. 之后才进 Step 2

## 十、全局蓝图（后续 Step 2~10，已确认，勿丢）

- **Step 2（v0.06.1）**：日历纯色热力图（绿 #059669 / 红 #dc2626，透明度按月最大盈亏动态；深色底文字转白；废弃斜切）；顶部 `<<` `>>` 快切年份；响应式（大屏三行/中屏仅结余/极小屏仅底色）
- **Step 3（v0.06.2）**：首页 Dashboard（巨型本月支出卡 + 收入/结余）、预算系统（环形进度、超支标红、日均、剩余日均额度）、近 7 天分组卡片列表（今天/昨天）、资产页总资产卡、ECharts 饼图 + 30 天折线（Toolbox）
- **Step 4（v0.06.2）**：右下悬浮球（收支速览 + 快捷键面板）、列表分页/分批渲染（滚动加载）、Tab 状态保持、剪贴板解析、表头吸顶 + 备注 Tooltip
- **Step 5（v0.06.2）**：响应式（侧栏折叠、卡片换行、小屏隐藏次要列）、「我的」实装（深色模式、CSV 导出带 BOM、草稿恢复确认）、系统级（断网横幅、超时重试、动态版本号、自定义 404）
- **Step 6（v0.07）**：contacts 表、debts 表（双向借贷）、records 加报销字段 + `deleted_at` 软删除
- **Step 7（v0.07）**：通讯录前端 + 资金往来明细、记账弹窗「借贷」模式、敏感操作输入 `DELETE` 确认
- **Step 8（v0.07）**：报销开关/报销人/金额或比例、右键菜单、全局快捷键（N 记账、Ctrl+K 搜索）、拖拽排序、回收站、一键复制、分类预算超支高亮、离开页面拦截
- **Step 9（v0.07.1）**：ECharts 桑基图（资产/负债流向）、环形图（中心总计 + Tab 切换）、净资产折线（年/月/日 + 明细表联动）
- **Step 10（v0.07.1）**：html2canvas 月度分享长图、PWA（manifest + Service Worker，可安装 + 离线）

## 十一、踩坑清单（务必沿用）

| 坑 | 解法 |
|---|---|
| PowerShell 里 `curl` 是 IWR 别名 | 一律写 `curl.exe` |
| 中文 JSON 直传报 400 | 写 UTF-8 无 BOM 文件 + `--data-binary "@body.json"` |
| 控制台 GBK 乱码 | `[Console]::OutputEncoding=[Text.Encoding]::UTF8`；读文件加 `-Encoding UTF8` |
| Python 打印中文到管道乱码 | 另加 `$env:PYTHONIOENCODING='utf-8'` |
| PowerShell 5.1 不支持三元运算符 | 写 if/else |
| `Get-Content -Raw` + `.Replace` 对 LF 文件失效 | 用 edit 工具改文件 |
| Flask debug 派生多个 python 进程 | 正常；别用管道接 `Select-Object -First`，会打死服务 |
| 想验后端又不想起服务 | 用 `app.test_client()` 直接打路由（已用过，安全） |
| `py_compile` 产生 `__pycache__` | 测完删，已在 .gitignore |
| math.js `1/0` 返回 Infinity 不抛错 | 必须判 `Number.isFinite` 且 `> 0` |
| `<input type="number">` 存不下算式 | 改 `type="text" inputmode="decimal"` |
| SQLite 的 DDL 会先提交事务 | 迁移的 DDL 与 DML 分两个 `with conn:` |
| 自测脚本用 `records[0]` 定位新数据 | 用唯一备注 `find()`，否则会误删用户真实账目（真实发生过） |
| 测试脚本 query 带中文 | `urllib.parse.quote()` |
| 浮点余额尾巴 -773.2199999 | 比较与显示统一 `round(x,2)`；库里微信现为 `78.19999999999999` |
| `git diff` 报 `LF will be replaced by CRLF` | 属 `core.autocrlf` 正常提示，不是错误 |
| PowerShell 里 `python -c "..."` 含引号易炸 | 写成临时 `.py` 脚本再跑，跑完删 |

## 十二、新会话启动模板

> 这是 AI 记账管家项目的接续会话。附件是 `docs/HANDOFF.md` 与「终极蓝图」。
> 请先读 HANDOFF 确认项目现状与规范，回复一句现状确认，然后等我下达 Step 指令。

## 十三、v0.06.2-DEV 现状补记（2026-10-27）

上一节描述的是 v0.06.1；此后已完成 v0.06.2-DEV 的四个阶段，实际落地：

| 文件 | 变化 |
|---|---|
| `templates/index.html` | 三栏 Dashboard、顶栏搜索/信封/主题、侧栏折叠、详情弹窗、通知面板（**不再有 `page-calendar` 页，日历进右栏**） |
| `templates/admin.html` | **新增**：开发者通知发布台（富文本 + 图片上传） |
| `static/style.css` | 主题变量两套（含 `[data-theme="dark"]`）、`.dash-grid`、表格 `min-width` + 隐藏次要列、通知面板、详情弹窗；删除 `.is-deep` 白字规则 |
| `static/script.js` | 行点击 → 详情弹窗；主题/侧栏/搜索/预算/通知/Tooltip 全部接线；修复 `refresh()` 调用不存在的 `loadStatistics()` 的崩溃 |
| `app.py` | 通知 CRUD、`/api/upload`、`/admin` |
| `database.py` | `notifications` 表 + 种子通知 |

前端约定更新（覆盖第六节）：

- 表格行不再有编辑/删除按钮，**点整行**弹 `#record-detail-modal`，按钮为 outline 幽灵样式
- 弹窗快捷键：详情 Esc 关闭 / Enter 编辑；记账弹窗 Enter 提交 / Esc 关闭
- 全站图标按钮统一 `data-bs-toggle="tooltip"`，悬停 0.5s 出现
- 深色模式：`document.documentElement[data-theme]`，存 `localStorage["ai-accounting-theme"]`

自测：19 条 headless 点击断言全通过，7 条路由全 200，0 页面报错。

## 十四、v0.06.3-DEV 补记（2026-10-27）

v0.06.2 遗留的「ECharts 饼图 / 30 天折线、右下悬浮球、分页」已在 v0.06.3 全部落地：

| 文件 | 变化 |
|---|---|
| `static/vendor/echarts.min.js` | **新增**：ECharts 13 本地包（1,030,855 字节），本地引用不用 CDN |
| `templates/index.html` | 中栏预算卡下加 `.charts-panel`（`#chart-pie` / `#chart-trend` / `#charts-sub`）；账单 panel 加分页条（`#record-pager` / `#pager-info` / `#page-size` / `#pager-pages`）；页尾加 `#fab`（预算剩余 + 快捷键面板） |
| `static/style.css` | 图表卡、分页条、悬浮球与展开面板、超支红字，深色模式同步适配 |
| `static/script.js` | 图表：`monthExpenseByCategory / dailyExpenseSeries / chartToolbox / pieOption / trendOption / initCharts / renderCharts / resizeCharts / watchChartResize`；分页：`readPageSize / pageCountOf / pageButtonsHtml / renderPager / resetPaging`；滚动加载：`sentinelText / sentinelRowHtml / observeScrollSentinel / maybeAppendOnScroll / appendMoreRecords`；悬浮球与快捷键：`renderFab / openFab / closeFab / toggleFab / isTypingTarget / onGlobalKeydown` |

关键行为：

- 图表 Toolbox 可存图；`restore` 事件回灌最新数据，不会退回初始 option。
- 分页每页 20 / 50 / 100 /「不分页」，选择存 `localStorage["ai-accounting-page-size"]`；「不分页」先出 20 条，滚到底自动追加 20 条，到底显示「已经到底啦，共 N 笔」。
- N 记一笔 / Ctrl+K 聚焦搜索 / Esc 关弹窗与面板；输入框内打字不抢键。
- 已知不修：弹窗淡入未结束（约 300ms）时点保存，Bootstrap 的 `hide()` 会被 `_isTransitioning` 吃掉、弹窗不关；真人填表快不到这个程度。
- 浏览器控制台唯一的报错是既有 `/favicon.ico` 404，与本版无关。

数据现状（2026-10-27 自测后）：13 条账目（收入 21413.01、支出 865.03、总余额 24161.20），分类 24 条，账户 8 个三组；`records.db` 不进 Git。
