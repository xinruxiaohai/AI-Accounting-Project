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
