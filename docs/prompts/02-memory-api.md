# 02 · 内存版账目接口（Prompt 快照）

> 快照时间：2026-10-25
> 对应提交：`feat: 首页与健康检查接口 + 内存版账目接口`（`app.py`，64 行）

## 一、这一步要解决什么

第 1 步只有探针路由，没有任何业务。这一步要把「记一笔」和「看列表」的**接口契约**先定下来：

- `POST /api/records` 接收一笔账，返回入库后的完整记录；
- `GET /api/records` 返回 `{"count": n, "records": [...]}`；
- 校验规则在这个阶段就钉死，后面换成 SQLite 时接口形状一个字都不改。

存储刻意**先不接数据库**，只用一个模块级列表 `records = []`。理由：先把「前端 → 接口 → 数据形状」这条链路跑通，数据库只是替换其中一格，混在一起调试会分不清是 API 的锅还是 SQL 的锅。

## 二、用户原始 Prompt（要点摘录）

以下为当时指令的概括（非逐字）：

> 「进入第 2 步：实现内存版账目接口。给我 POST 和 GET 两个接口，数据先放内存里。只给代码、运行命令和验证命令，不要解释原理。」

> 「顺便告诉我怎么在终端切到 D 盘的项目目录。」（这就是坑 1 的来源，详见 `docs/bugs-and-solutions.md`）

## 三、AI 给出的方案要点

### 数据与状态

```python
# 内存里的账目列表：进程一重启就清空。第 2 步刻意这么干，先只验证数据流，不掺数据库
records = []
```

### `POST /api/records`

| 步骤 | 写法 | 关键点 |
| --- | --- | --- |
| 取 JSON | `data = request.get_json(silent=True)` | `silent=True` 避免非 JSON 请求直接 415/400 抛异常，改由自己返回可读错误 |
| 类型兜底 | `if not isinstance(data, dict)` → `400 {"error": "请求体必须是 JSON 对象"}` | 前端 `fetch` 忘带 `Content-Type: application/json` 时最容易踩 |
| `amount` 校验 | `isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0` | **`bool` 是 `int` 的子类**，不先排掉的话 `true` 会被当成 `1` 放过去 |
| `category` 校验 | `not isinstance(category, str) or not category.strip()` | 空串、纯空格一律拒绝 |
| `note` | `(data.get("note") or "").strip()` | 可不填，缺省空串 |
| `date` | `data.get("date") or date.today().isoformat()` | 前端不传就用服务端当天，格式 `2026-10-25` |
| `id` | `len(records) + 1` | 内存版够用；接 SQLite 后由 `AUTOINCREMENT` 接管 |
| 返回 | `jsonify(record), 201` | `201 Created` 比 `200` 语义准确 |

### `GET /api/records`

```python
return jsonify(count=len(records), records=records)
```

`records` 是 `append` 追加的，所以内存版按**插入正序**返回，最新的在最后。

## 四、验证记录（实跑）

| 请求 | 结果 |
| --- | --- |
| `POST` 合法账目 | `201`，返回体含后端生成的 `id` |
| `GET /api/records` | `count` 与已提交条数一致，`records` 为数组 |
| `POST {"amount": "25"}`（字符串） | `400`，`{"error": "amount 必须是大于 0 的数字"}` |
| 重启进程后 `GET` | `count: 0` —— 内存清零，符合预期，也正是第 3 步要换成 SQLite 的直接原因 |

## 五、踩坑与结论

- **顺序不一致是后来才发现的小债**：内存版 `GET` 是正序，第 3 步换 SQLite 后 `SELECT ... ORDER BY id DESC` 变成倒序。因为前端是最后接的，页面上没有感知；如果先做了前端再换存储，这里就会变成「刷新后顺序突然反了」的隐蔽 bug。教训：**接口契约里应显式写明排序规则**，而不依赖存储层默认行为。
- **`silent=True` 是必须的**：默认 `request.get_json()` 遇到非 JSON 内容会直接抛 415，前端拿到的错误信息就不可读了。
- **校验写在接口里、不写在存储里**：所以第 3 步换 SQLite 时校验逻辑可以原样搬过去，`create_record` 只改最后两行。
- 内存列表故意留着 `records.append()` 而不是 `insert(0, ...)`：不在这一步提前优化展示顺序，避免和后面真实排序规则打架。
