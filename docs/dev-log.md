# 开发日志

> 版本策略：按「功能里程碑」打 Tag，而不是每次 commit 都升版本。
> 命名规则：`v0.XX-DEV`，`XX` 为里程碑序号，尾缀 `-DEV` 表示开发中、接口随时可能调整。

## v0.01-DEV (2026-10-25) 项目基建与基础 CRUD 跑通：涵盖环境搭建、SQLite接入、前端极简UI。

对应提交：`54b13fc` → `da15180`（共 7 个 commit，Tag 打在 `da15180`）

**环境搭建**

- 机器上原本没有 Python：`python` 指向微软商店占位符，执行即报 `Python was not found`。
- 用 `winget install Python.Python.3.12 --scope user` 装好 Python 3.12.10，用户级 PATH 自动带上 `Python312` 与 `Scripts`。
- 在项目根目录建 `venv`，`pip install -r requirements.txt` 装上 Flask 3.1.3，依赖清单锁进 `requirements.txt`。
- `.gitignore` 覆盖 `venv/`、`__pycache__/`、`*.db`、`.env` —— 环境、缓存、本地数据、密钥一律不进 Git。

**SQLite 接入**

- `database.py` 用内置 `sqlite3`，四个函数：`get_conn()` / `init_db()` / `add_record()` / `list_records()`。
- `CREATE TABLE IF NOT EXISTS records (id, amount, category, note, date)`，启动即建表，重启不重复建。
- 持久化用「杀进程 → 重启 → 再 GET」验证通过：`count` 不变，数据仍在。
- 整个过程零新增依赖，`requirements.txt` 始终只有一行 `flask>=3.0`。

**前端极简 UI**

- `templates/index.html` + `static/style.css` + `static/script.js`，原生 JS，不引任何框架。
- 金额 / 分类 / 备注三个输入框 +「记一笔」按钮，`fetch` POST 成功后弹窗提示、清空输入框、自动刷新列表。
- 首屏自动 `GET /api/records` 渲染 `<ul id="record-list">`，空库显示「还没有记录，先记一笔吧」。
- `/` 由 JSON 探针改为 `render_template("index.html")`，`/health` 与 `/api/records` 行为保持不变。

**目录重构**

- 项目从杂乱的 `D:\AI` 迁到 `D:\Project\AI-Accounting-Project`，同盘符移动 `.git` 保留全部历史。
- 旧环境 `venv` 删除后重建，旧目录里的项目文件清理干净，私人文件夹（backup、Deepseek harness 等）未动。

## v0.02-DEV (2026-10-25) 完善比赛文档与版本规范：涵盖补齐 Prompt 快照与踩坑记录。

对应提交：`docs: complete dev log, bug tracker, and prompt snapshots`（Tag 打在本次提交）

**版本规范**

- 确立「功能里程碑 Tag」策略：`v0.01-DEV` 覆盖基建 + CRUD + 前端，`v0.02-DEV` 覆盖文档补齐。
- Tag 使用 annotated（`git tag -a`），带打标人与说明文字，`git log --oneline --decorate` 里可直接看出里程碑边界。

**文档资产补齐**

- `docs/prompts/` 三份 Prompt 快照齐全：`01-flask-skeleton.md`、`02-memory-api.md`、`03-sqlite.md`。
  每份固定记录「这一步要解决什么 / 用户原始 Prompt 摘录 / AI 给出的方案要点 / 验证记录 / 踩坑与结论」。
- `docs/bugs-and-solutions.md` 沉淀真实踩过的三个坑：终端切盘、Git root-commit、Python 商店占位符。
- `docs/dev-log.md`（本文件）改为按里程碑分段，成为版本演进的唯一时间线。

## v0.03-DEV (2026-10-25) 完整基础账本：涵盖账户维度、CRUD 补全、收支类型与余额联动、Bootstrap 界面升级。

对应提交：`feat: support income/expense with account balances` → `docs: add v0.03 dev log and income-accounts prompt snapshot`（共 3 个 commit，Tag 打在最后一次提交）

**账目维度与 CRUD**

- `records` 用 `ALTER TABLE ADD COLUMN` 加了 `account`（默认「现金」）与 `type`（默认 `expense`），带非空默认值的加列只改表定义，老数据零丢失、迁移幂等。
- 补齐 `DELETE /api/records/<id>` 与 `PUT /api/records/<id>`；PUT 采用「整条覆盖」语义，避免漏传字段被静默清空。
- GET 显式 `ORDER BY id DESC`，把「内存版正序 → SQLite 倒序」的顺序变化写进接口契约，不再依赖存储层默认行为（v0.02 记下的技术债在此结清）。

**收支与账户余额**

- 新建 `accounts(name 主键, balance)`，预置现金 / 微信 / 支付宝 / 银行卡；写账目时账户不存在会自动落库，避免余额更新影响 0 行。
- 增、改、删账目都在**同一个 `with conn:` 事务**里改记录与余额；修改 = 先撤销旧账、再记新账，账户从 A 换到 B 时两边余额一起搬。
- `GET /api/statistics` 收敛为总收入 / 总支出 / 总余额；总余额取 `SUM(accounts.balance)` 而非收入减支出，因为允许手工修正余额。
- 余额口径决策：选择「如实记录历史」，账户余额可以为负（当前现金 `-773.23`，等于 0 - 773.23 支出），不做静默归零，界面标红提示。

**界面升级**

- 引入 Bootstrap 5.3.3（CDN）+ 自有 `style.css`：Navbar、三张统计卡片、表单栅格、`table-hover` 表格、账户管理弹窗。
- 支出 / 收入做成分段单选按钮，列表用徽章区分类型（支出红、收入绿），金额按 `-¥` / `+¥` 渲染。
- 卡片 header 内嵌账户筛选下拉，对应 `GET /api/records?account=微信`；切换筛选只重拉列表、不动统计。
- 「账户管理」弹窗可逐个改余额，直接调 `PUT /api/accounts/<name>`；负余额在卡片与弹窗中统一标红。

## v0.04-DEV (2026-10-26) PC 端后台改版与分钟级时间：涵盖后台布局、分钟级时间、编辑与删除、资产页与日历。

对应提交：`feat: support minute-level record time` → `docs: add v0.04 dev log and prompt snapshot`（共 4 个 commit，Tag 打在最后一次提交）

**分钟级时间**

- 老数据只有 `YYYY-MM-DD`，`normalize_date()` 只在**读时**补 `00:00`，库里物理值不动；新数据写入即 16 位 `YYYY-MM-DD HH:MM`。
- `_parse_datetime()` 同时接受 `YYYY-MM-DD`、`YYYY-MM-DD HH:MM`、`YYYY-MM-DDTHH:MM` 以及带秒的两种；秒被截断到分；空值取当前时间；其余格式一律 400。
- 前端改用 `<input type="datetime-local">`，默认值由服务端注入（带 `T`），避免浏览器与服务器时区不一致时显示成空白。

**PC 端后台布局**

- 左侧 220px 深色侧边栏（`#1e293b`）承载 Logo + 首页 / 日历 / 资产 / 我的，右侧主区吃满剩余宽度，`100vh` 不出整页滚动条，只有 `.content` 自己滚。
- 顶栏固定 64px 白底带阴影，左侧标题跟随菜单变化，右侧「+ 记一笔」是唯一主按钮。
- 记账从页内表单改为居中的 Bootstrap Modal（`modal-dialog-centered`），弹窗关闭时统一复位表单。
- Bootstrap 5.3.3 改为**本地引用**（`static/vendor/`，CSS 232803 B + JS 80721 B），断网也能跑 —— 比赛现场网络不可控。
- 资产页承载账户余额编辑（每行一个输入框 + 保存），日历页做当月网格，格子里的数字是当天支出合计。

**前端业务逻辑**

- `script.js` 重写为「拉数据 → 渲染 → 事件委托」三段式：`refresh()` = `Promise.all([loadStatistics(), loadAccounts(), loadRecords()])`，写操作成功后只重拉数据，页面不刷新。
- 编辑复用同一个弹窗：`editingId` 区分 POST / PUT，标题变「编辑记录 #id」、按钮变「保存修改」；`hidden.bs.modal` 事件里复位，取消编辑不会把状态带进下一次新增。
- 动态生成的表格行与账户行用**事件委托**（`#record-list`、`#account-list` 各绑一次），重渲染不会丢监听。
- `ensureOption()` / `clearTempOptions()` 处理「卫浴」这类不在下拉选项里的分类，避免 `select.value = xxx` 静默失败。
- 日历不额外请求接口，直接复用列表数据按日期聚合，切页零延迟。

**联调验证**

- Node + 极简 DOM 桩把 `script.js` 真跑在真实接口上：34 条断言全过（首屏卡片 / 表格 / 资产页 / 日历、POST 后不刷新即更新、编辑回填、PUT、筛选、DELETE、改余额、切页），全程 `alert` 触发 0 次。
- 再用 Edge headless 渲染真实页面复核：卡片 `¥0.01 / ¥783.13 / ¥2830.10`，表格首行 `2026-10-26 14:30 | 支出 | 餐饮 | 微信 | -¥9.90`，日历 34 格，资产页 4 个账户。

## v0.05-DEV (2026-10-26) 二级分类与资产页：涵盖分类树、账户大类、级联选择与账户专属流水。

对应提交：`feat: support two-level categories and grouped accounts` → `docs: add v0.05 dev log and prompt snapshot`（共 3 个 commit，Tag 打在最后一次提交）

**数据模型升级**

- 新增 `categories(id, name, parent_id)` 自关联表，用 `parent_id IS NULL` 表示一级分类；唯一索引建在 `COALESCE(parent_id, 0)` 上，让「同名但父级不同」合法、同一父级下不允许重名（`NULL` 在 SQLite 里互不相等，直接建 `(parent_id, name)` 唯一索引会漏掉一级分类的重复）。
- `records` 加可空 `category_id` 指向分类表，同时**保留** `category` 文本列作为显示名：改名时两处一起同步，旧接口、旧页面、导出都不受影响。
- `accounts` 加 `group_name`（默认「资金账户」），把「账户」从一维列表变成「大类 → 账户」两层；余额仍按单个账户记，大类金额前端求和。
- 升级全程只有 `ALTER TABLE ADD COLUMN` 与 `CREATE TABLE IF NOT EXISTS`，不重建表；DDL 与 DML 分成两个 `with conn:`，因为 SQLite 的 DDL 会隐式提交事务，混在一起会破坏「要么全成、要么全不成」的预期。

**老数据兼容**

- 启动时 `_backfill_category_ids()` 三步回填：先把库里出现过的文本分类登记成一级分类 → 再按一级同名回填 `category_id` → 最后按任意层级同名兜底。
- 记账接口仍然接受纯文本 `category`：遇到不存在的名字自动建一级分类，v0.04 的页面与脚本不改也能继续记账。
- 实际升级结果：8 条老账目一条没少，金额合计 808.14 不变，`category_id` 空值 0 条，老分类「卫浴」自动成为一级分类，重复执行 `init_db()` 无副作用。

**后端接口**

- 分类：`GET /api/categories`（两级树）、`POST`（可带 `parent_id`）、`PUT /<id>` 改名（连带改账目里的冗余名）、`DELETE /<id>`。
- 账户：`GET /api/accounts` 同时返回平铺列表与大类分组；`POST` 新增（名称 + 大类 + 初始余额）、`PUT /<name>` 改余额或大类、`DELETE /<name>`。
- 删除都带保护：分类下有子分类或有账目在用、账户下还有账目时返回 409 与中文原因，不做级联删除。
- `GET /api/records` 新增 `category_id` 与 `parent_id` 筛选，`parent_id` 会同时命中该一级分类自己和它的全部二级分类。

**前端交互**

- 记账弹窗的一级分类下拉由分类表重建（`value` 是分类 id），选中后若该分类有子分类才显示「二级分类」下拉，提交时优先取二级 id、没有二级就用一级 id。
- 账户下拉用 `<optgroup>` 按「资金账户 / 储蓄账户 / 投资账户」分组，选项文字带上当前余额，方便记账时先看一眼钱在哪。
- 资产页按大类渲染账户卡片（含该类小计），点卡片即选中：卡片描边高亮、下方表格切到该账户的专属流水、「在此账户下记一笔」解除禁用。
- 快捷记账把账户下拉设为 `disabled` 并锁定为当前账户，弹窗关闭时统一复位移除锁定，避免下一次新增被悄悄绑到某个账户上。
- 「分类管理」弹窗树形展示所有分类，可新增一级或挂在某个一级下的二级，删除按钮逐节点独立，失败时把后端的拒绝原因直接 `alert` 出来。

**验证**

- 迁移与接口自检：迁移 33 条 + 接口 47 条断言全过（二级分类记账返回 `category_parent`、未知分类文本自动建一级、重复分类 409、二级下再建三级被拒、有子分类或有账目不可删、改名连带改账目、未知大类 400、有账目不可删账户、`?account=` 与 `?parent_id=` 筛选均正确）。
- 前端自检：Node + DOM 桩跑真实接口 42 条断言全过、`alert` 0 次（级联出现与隐藏、optgroup 三组、卡片数=账户数、点卡片出专属流水、快捷记账锁定与解锁、二级分类保存后 `category_parent` 正确、编辑回填五字段、删除回基线、分类与账户的新增删除、日历 35 格、统计卡片与接口一致）。
- Edge headless 复核真实页面：DOM 32412 字符，表格 9 行，首行 `2026-10-26 09:30`，账户卡片已渲染，日历 35 格，总余额 `¥2795.20` 与账户表一致。

## v0.06-DEV (2026-10-26) 转账、公式与 Toast

**数据模型升级**

- `records` 新增三列：`formula TEXT NOT NULL DEFAULT ''`（金额算式原式）、`to_account TEXT NOT NULL DEFAULT ''`（转账转入账户）、`fee REAL NOT NULL DEFAULT 0`（转账手续费）。仍是 `ALTER TABLE ... ADD COLUMN`，老库升级不丢数据。
- `type` 的合法值从两种扩到三种：`expense / income / transfer`。转账的分类固定记成「转账」、`category_id` 置 NULL —— 它不属于任何收支分类。

**余额联动的统一写法**

- 新增 `_balance_effects(record_type, account, to_account, amount, fee)`，把一笔账对余额的影响统一算成 `[(账户, 变化量), ...]`：收入 `+amount`、支出 `-amount`、转账 `[(转出, -(amount+fee)), (转入, +amount)]`。
- 删掉旧的 `_signed()`，避免「加法在一处、判断在另一处」两套规则各自演化。新增、编辑、删除三个动作都走这一份效果表：编辑时先按旧值撤销、再按新值施加。
- 校验集中到 `_transfer_problem()`：转出与转入不能同名、两个账户都必须真实存在、余额不足（`balance + 1e-9 < amount + fee`）一律拒绝。加 `1e-9` 是让 `0.1 + 0.2` 这类浮点误差不至于误伤「刚好够」的转账。

**为什么转账要求账户必须存在**

支出记账时账户名打错会自动建一个新账户（v0.03 留下的便利），但转账若也这样，`银行卡 → 招行卡` 手滑写成「招商卡」就会凭空多出一个账户，钱转进去再也对不上账。所以转账的两个账户都必须是已存在的账户，写错直接 400。

**为什么余额不足只卡转账**

支出允许把余额记成负数（v0.03 定下的「如实记录」），但转账是把钱从一个口袋挪到另一个口袋，余额不够就不是「记录」而是「编造」。所以只有转账做余额校验。

**后端接口**

- `POST /api/records` 与 `PUT /api/records/<id>` 接收 `formula`、`to_account`、`fee`；转账时后端强制把 `category` 写成「转账」、`category_id` 置空。
- `GET /api/records?account=` 的筛选条件改成 `(r.account = ? OR (r.type = 'transfer' AND r.to_account = ?))` —— 一笔转账在转出、转入两个账户的流水里都该看到。
- `DELETE /api/accounts/<name>` 的引用检查补上 `to_account`，避免删掉还在被当作转入方的账户。
- 新增 `_parse_formula()`：只校验类型与长度（≤ 200 字符），不解析算式 —— 结果由前端算好再提交，后端不做二次计算，避免两边算出不同的数。

**前端**

- 金额框从 `type="number"` 改成 `type="text"`（HTML 的数字框根本存不下 `15.5+20*2`），输入里带运算符时下方实时显示 `= ¥55.50`，算不出来就红字提示；保存时 `amount` 提交结果、`formula` 提交原式；编辑时金额框回显公式，还能接着改。
- 计算用 math.js（`13.2.3`，本地 `static/vendor/math.min.js`），不用 `eval`；`math.js` 的 `evaluate("alert(1)")` 会抛 `Undefined function`，比 `eval` 安全。
- 记账弹窗的类型加了「转账」：选中后隐藏一级/二级分类，显示「转入账户」与「手续费」，账户标签从「账户」变成「转出账户」。
- 列表里转账显示 `微信 → 支付宝`、徽章「转账」，金额下方小字标出「含手续费 ¥1.50」；转账不计入总收入/总支出，但会改变总余额与两个账户的余额。
- 全局 `toast(message, type)`：顶部居中滑出，成功绿、失败红，2.4 秒后自动消失；原来所有 `alert()` 都换成它，删除操作改用 `confirm` 保留二次确认。
- 资产页快捷记账只预选账户、不再 `disabled`：点开之后想改账户随时能改。

**验证**

- 后端自测 47/47：迁移 5 条、转账主流程 11 条、非法请求 13 条（负数、0、字符串金额、转出=转入、缺转入账户、账户不存在、手续费负数/非数字、余额不足、未知 type、公式超长/非数字）、公式留存 6 条、编辑删除回滚 7 条、账户保护 1 条、清理 3 条。
- 前端自检 52/52（Node + DOM 桩跑真实接口，`alert` 0 次）：卡片与接口一致、公式实时结果 `= ¥55.50`、错误公式红字、金额写错只弹 Toast 不落库、公式记账入库为 `amount=55.5 / formula=15.5+20*2`、转账转出 -11.5 转入 +10、转账不计入收支、列表出现「转账」徽章与 `微信 → 支付宝`、编辑回显公式与转账字段、快捷记账不再 disabled、删除后余额与统计一分不差地回到基线。
- Edge headless 复核真实页面：DOM 30663 字符，表格 10 行，账户卡片 8 张，日历 35 格，三张卡片 `¥0.01 / ¥830.03 / ¥2783.20`，首行 `2026-10-26 09:11 · 支出 · 餐饮 / 晚餐 · 银行卡 · -¥12.00`。



