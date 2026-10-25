# 03 · 引入 SQLite 持久化（Prompt 快照）

> 快照时间：2026-10-25
> 对应提交：`feat: 引入 SQLite 持久化账目数据`

## 一、这一步要解决什么

第 2 步的账目存在 Python 列表 `records` 里，进程一重启就清空，等于没存。
这一步把存储换成 SQLite，要求：

- 只用 Python 内置 `sqlite3`，不引入任何新依赖；
- 启动时自动建表，表已存在则跳过；
- 字段固定为 `id, amount, category, note, date`；
- 对外 API 的形状（`POST /api/records`、`GET /api/records`）保持不变，前端不用改。

## 二、用户原始 Prompt（摘录）

> 「下一步行动：Git 搞定后，立刻带我进入第 3 步（引入 SQLite）。请给出 database.py 和修改后的 app.py 代码，要求使用内置 sqlite3，自动建表（字段 id, amount, category, note, date）。」

> 「请现在直接接管我的电脑（项目路径 D:\AI）…… 第三步：启动服务与持久化测试…… 关键测试：重启 Flask 服务，再次 GET，确认数据依然存在（证明 SQLite 持久化成功）。测试完请清空测试数据。」

## 三、AI 给出的方案要点

### database.py（新建）

| 函数 | 职责 | 关键写法 |
| --- | --- | --- |
| `get_conn()` | 开连接 | `sqlite3.connect(DB_PATH)`，`conn.row_factory = sqlite3.Row` |
| `init_db()` | 建表 | `CREATE TABLE IF NOT EXISTS records (...)` |
| `add_record(amount, category, note, date)` | 插入并返回新 id | `conn.execute("INSERT ... VALUES (?, ?, ?, ?)", (...))`，`return cur.lastrowid` |
| `list_records()` | 取全部 | `SELECT ... ORDER BY id DESC`，`[dict(row) for row in rows]` |

两个刻意为之的细节：

1. `DB_PATH = Path(__file__).resolve().parent / "records.db"` —— 数据库跟着代码走，不受启动时的工作目录影响。
2. 连接管理用 `with conn:` 包事务、`finally: conn.close()` 关连接 —— `with` 只负责 commit/rollback，**不会关连接**，漏掉 `close()` 会泄漏。

### app.py（改造）

- 顶部 `import database`，模块级调用 `database.init_db()`（启动即建表）；
- `POST /api/records`：校验逻辑不变，末尾改成 `new_id = database.add_record(...)`，返回 `201` + 入库后的完整记录；
- `GET /api/records`：`rows = database.list_records()`，返回 `{"count": n, "records": [...]}`；
- 原来那个内存列表 `records = []` 整段删除。

## 四、表结构（`PRAGMA table_info(records)` 实测）

```
(0, 'id',       'INTEGER', 0, None, 1)   -- 主键，AUTOINCREMENT
(1, 'amount',   'REAL',    1, None, 0)   -- NOT NULL
(2, 'category', 'TEXT',    1, None, 0)   -- NOT NULL
(3, 'note',     'TEXT',    1, "''", 0)   -- NOT NULL DEFAULT ''
(4, 'date',     'TEXT',    1, None, 0)   -- NOT NULL，ISO 字符串 2026-10-25
```

## 五、验证记录（实跑）

1. `POST` 餐饮 25.5 → `201`，`id: 1`
2. `POST` transport 8 → `201`，`id: 2`
3. `GET /api/records` → `count: 2`
4. **停掉进程 → 重新 `python app.py` → 再 `GET`** → `count: 2`，两条都在 ✅ 持久化成立
5. `POST {"amount": "25"}` → `400`，`{"error": "amount 必须是大于 0 的数字"}`
6. 清理：删除 `records.db`，首次运行由 `init_db()` 重新建表

## 六、踩坑与结论

- `amount` 是 `REAL` 列，写入整数 `8` 读回变成 `8.0`。不是 bug，前端用 `toFixed(2)` 处理即可。
- Windows 控制台默认 GBK，`curl -d "…餐饮…"` 会把中文按 GBK 发出去，Flask 按 UTF-8 解码失败，返回 `400 "请求体必须是 JSON 对象"`。正确做法：把 JSON 写成 UTF-8（无 BOM）文件，再用 `--data-binary "@body.json"`。
- PowerShell 里 `curl` 是 `Invoke-WebRequest` 的别名，不支持 `-X`，必须写 `curl.exe`。
- `.gitignore` 已包含 `*.db`，`records.db` 属于本地数据，不进 Git。
