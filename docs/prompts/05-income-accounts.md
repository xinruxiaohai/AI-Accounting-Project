# 05 · 收支类型与账户余额（Prompt 快照）

> 快照时间：2026-10-25
> 对应提交：`feat: support income/expense with account balances`

## 一、这一步要解决什么

到 v0.03 时，账本只能记「花出去多少」，看不到「钱从哪个账户出、还剩多少」。
这一步把账本从「一张流水表」升级成「带账户余额的小账本」，要求：

- 账目区分支出 / 收入（`type`）；
- 每个账户有独立余额，记一笔就自动加减；
- 统计口径从「今日 / 本月支出」改成「总收入 / 总支出 / 总余额」；
- 列表能按账户筛选，账户余额能手工修正；
- 老数据（此前的 4 条记录）一条不能丢。

## 二、用户原始 Prompt（摘录）

> 「v0.03-DEV 之前先把『完整基础账本』做进去：records 加 type（expense/income），新建 accounts 表（name 主键、balance），预置现金/微信/支付宝/银行卡；增删改账目时自动联动账户余额，收入加、支出减；加 GET /api/accounts 和 PUT /api/accounts/<name>；GET /api/records 支持 ?account= 过滤；statistics 改成返回总收入/总支出/总余额。」

> 「先梳理一下表结构升级方案，保证老数据兼容……确认 100% 明白后，先只给我 database.py 和 app.py，我测完再给前端。」

> 「选b如实记录。」（账户余额出现负数时，选择如实反映历史，不静默归零）

## 三、AI 给出的方案要点

### database.py（改造）

| 函数 | 职责 | 关键写法 |
| --- | --- | --- |
| `_signed(amount, record_type)` | 把账目换算成对余额的增量 | 收入为正、支出为负 |
| `_apply_balance(conn, account, delta)` | 改账户余额 | 先 `INSERT OR IGNORE INTO accounts(name, balance) VALUES(?, 0)`，再 `UPDATE accounts SET balance = balance + ?` |
| `init_db()` | 迁移 + 建表 + 种子 | `PRAGMA table_info` 判缺列 → `ALTER TABLE records ADD COLUMN type TEXT NOT NULL DEFAULT 'expense'`；建 `accounts`；`INSERT OR IGNORE` 预置 4 个账户；再从 records 里补自定义账户 |
| `add_record(...)` | 新增账目 + 加余额 | 记录与余额在**同一个 `with conn:` 事务**里 |
| `update_record(...)` | 修改账目 | **先撤销旧账**（`-_signed(old.amount, old.type)`）**再记新账**，改账户时余额要跟着搬家 |
| `delete_record(...)` | 删除账目 | 反向冲销余额 |
| `list_records(account=None)` | 列表 | `WHERE account = ?` + `ORDER BY id DESC` |
| `list_accounts()` | 账户与余额 | `ORDER BY rowid`，保持预置顺序 |
| `update_account_balance(name, balance)` | 手工改余额 | 不存在返回 `None`，由路由转 404 |
| `get_statistics()` | 统计 | 收入/支出按 `type` 分组求和；**总余额取 `SUM(accounts.balance)`**，不是收入减支出 |

### app.py（改造）

- `_parse_record(data)` 抽出共享校验，POST 与 PUT 用同一份规则，新增 `type` 白名单；
- `GET /api/records` 的 `?account=` 空串视为「不筛选」；
- 新增 `GET /api/accounts`、`PUT /api/accounts/<name>`（余额必须是数字、允许负数、四舍五入到分）；
- `GET /api/statistics` 返回 `income / expense / balance_total`；
- `PUT /api/records/<id>` 保持「整条覆盖」语义。

### 前端

- 顶部三张卡片：总收入（绿）/ 总支出（红）/ 总余额（正黑负红）；
- 支出、收入做成分段单选按钮（`btn-check` + `btn-outline-danger/success`）；
- 列表改 `<table class="table table-hover">`，类型用徽章，金额按 `-¥` / `+¥` 渲染；
- 卡片 header 内嵌账户筛选下拉，切换只重拉列表、不动统计；
- 「账户管理」弹窗逐行改余额，保存调 `PUT /api/accounts/<name>`，成功按钮闪「已保存」；
- 负余额统一标红，`money()` 先取绝对值再加前置负号，避免出现 `¥-773.23`。

## 四、表结构（实测）

```
records:
(0, 'id',       'INTEGER', 0, None,   1)
(1, 'amount',   'REAL',    1, None,   0)
(2, 'category', 'TEXT',    1, None,   0)
(3, 'note',     'TEXT',    1, "''",   0)
(4, 'date',     'TEXT',    1, None,   0)
(5, 'account',  'TEXT',    1, "'现金'", 0)
(6, 'type',     'TEXT',    1, "'expense'", 0)

accounts:
(0, 'name',    'TEXT', 0, None, 1)   -- 主键
(1, 'balance', 'REAL', 1, '0',  0)   -- NOT NULL DEFAULT 0
```

## 五、验证记录（实跑）

**接口层（24 条断言全过）**

1. 迁移后 `tables = ['records', 'sqlite_sequence', 'accounts']`，`records` 多出 `account`、`type` 两列；
2. 老数据 `count` 不变，4 条一条没少，`account` 补成「现金」、`type` 补成 `expense`；
3. 支出 50（现金）→ 现金余额 -50；收入 200 → 现金 +150、总收入 +200；
4. 支出 66 记到不存在的「测试卡」→ 自动建账户，余额 -66；
5. `?account=现金 / 微信 / 测试卡` → 6 / 0 / 1 条；
6. `PUT` 把「支出 50 / 现金」改成「收入 30 / 微信」→ 现金回到 200、微信 30（旧账撤销 + 新账生效）；
7. `DELETE` → 微信余额归 0；
8. `PUT /api/accounts/现金` → 1000，总余额 = 各账户之和 934；
9. `PUT` 不存在账户 → 404；`balance: "abc"` → 400；`type: "transfer"` → 400 `{"error": "type 只能是 expense 或 income"}`。

**界面层（31 条断言全过，用 DOM 桩跑真实 script.js）**

1. 首屏卡片：`¥0.00` / `¥773.23` / `-¥773.23`，总余额带 `text-danger`；
2. 表格 4 行，第一行「2026-10-25 | 支出 | 餐饮 | 现金 | -¥232.23」金额标红；
3. 账户弹窗 4 行，现金 `-¥773.23` 标红；
4. 筛选「微信」→ 0 行，空提示「「微信」还没有记录」；回「全部」→ 4 行；
5. 点「编辑」→ 标题「正在编辑 #9」、按钮「保存修改」、金额/日期/分类/类型全部回填；点「取消」→ 复位成「记一笔」+ 蓝色主按钮。

**余额口径对账**

`总余额 -773.23 == 总收入 0 - 总支出 773.23`，恒等式成立，说明增量记账没有漏账。

## 六、踩坑与结论

- **`INSERT OR IGNORE ... SELECT` 列数必须对齐**：`INSERT OR IGNORE INTO accounts (name, balance) SELECT DISTINCT account FROM records` 报
  `sqlite3.OperationalError: 1 values for 2 columns`，改成 `SELECT DISTINCT account, 0 FROM records`。
- **SQLite 的 DDL 会先提交已有事务**：迁移脚本报错那一刻，`accounts` 表其实已经建好并提交了，所以「迁移失败 = 数据库没动过」不成立。补救靠 `INSERT OR IGNORE` 种子 + 重启自愈，而不是回滚。
- **账户不存在时 `UPDATE` 影响 0 行**：直接 `UPDATE accounts SET balance = balance + ?` 会静默丢余额，必须先 `INSERT OR IGNORE` 兜底。
- **余额可以先为负**：本项目的决策是「如实记录历史」，不自动把负数归零；卡片与弹窗对负余额标红提示。
- **PowerShell 的 `curl.exe -s` 返回字符串数组**：`$html.Contains('xxx')` 变成数组精确匹配，全部 MISS；要 `(...) -join "`n"` 后再判断。
