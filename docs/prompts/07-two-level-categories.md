# 07 · 二级分类与资产页（Prompt 快照）

> 快照时间：2026-10-26
> 对应提交：`feat: support two-level categories and grouped accounts` / `feat: add cascading categories, grouped accounts and asset page`

## 一、这一步要解决什么

v0.04 的账本只有一个「分类」文本字段和一个「账户」文本字段：分类只能是一层（餐饮、交通），分不出「早餐」「打车」；账户是一个平铺列表，现金和基金混在一起，资产页看不出「手上有多少钱、存了多少、投了多少」。

这一步要同时改掉「数据结构」和「用户看到的界面」：

- **分类要能分级**：一级「餐饮」下面挂「早餐」「午餐」，记账时先选一级、再选二级，统计与筛选要能按一级分类汇总；
- **账户要能分大类**：资金账户（现金、微信）、储蓄账户（招行卡）、投资账户（余额宝、基金），资产页按大类分组展示；
- **分类和账户都要能自己维护**：比赛演示时现场加一个分类、加一个账户，不能改代码；
- **资产页要能联动记账**：点某个账户 → 看它的流水 → 直接在这个账户下记一笔，进去账户已锁定。

约束同样硬：**老库必须无损升级**，已有账目一条不能少、金额一分不能变。

## 二、用户原始 Prompt（摘录）

> 「v0.05-DEV 的目标：完善账本体验（多级分类、资产账户体系），把接入大模型推迟到 v0.06-DEV。」
>
> 「支持二级分类：比如「餐饮」下面可以选「早餐」「午餐」，「交通」下面可以选「打车」「地铁」。」
>
> 「支持账户大类：资金账户（现金、微信）、储蓄账户（招行卡、建行卡）、投资账户（余额宝、基金）。」
>
> 「支持自定义：前端可以自行增删分类（可以指定父级），以及增删账户（可以指定大类）。」
>
> 「资产页联动：点击资产页的某个账户，下面能显示该账户的流水；并且页面要有一个【在此账户下记一笔】的按钮，点开记账弹窗时，账户自动锁定为该账户。」
>
> 「务必注意旧数据兼容！先只给我 database.py 和 app.py，等我测试通过再写前端。」（m00719）

> 「后端验证通过！老数据 8 条都在，category_id 已回填，接口返回两级树，用 category_id 记账成功。」
>
> 「现在执行第二步：交付前端 UI 与逻辑。请直接给我 templates/index.html、static/script.js、static/style.css 的完整代码。」
>
> 「① 记账弹窗分类级联；② 账户下拉用 optgroup 分组；③ 资产页可以新增/删除账户；④ 加分类管理弹窗，树形展示分类；⑤ 资产页联动 + 在此账户下记一笔。」（m00807）

## 三、AI 给出的方案要点

### 数据模型（database.py）

| 对象 | 改动 | 关键写法 |
| --- | --- | --- |
| `categories` | 新建自关联表 | `CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, parent_id INTEGER REFERENCES categories(id))` |
| 唯一约束 | 同一父级下不重名 | `CREATE UNIQUE INDEX uq_categories ON categories(COALESCE(parent_id, 0), name)` |
| `records` | 加 `category_id` | `ALTER TABLE records ADD COLUMN category_id INTEGER`，可空，兼容老数据 |
| `accounts` | 加 `group_name` | `ALTER TABLE accounts ADD COLUMN group_name TEXT NOT NULL DEFAULT '资金账户'` |
| 默认数据 | 一级 6 类 + 二级 17 个 | `CATEGORY_SEEDS` / `_seed_categories()`，`INSERT` 前先查同名同父级，幂等 |
| 老库回填 | 三步兜底 | `_backfill_category_ids()`：文本分类登记成一级 → 按一级同名回填 → 按任意层级同名兜底 |
| 删除保护 | 不做级联删除 | `delete_category()` 有子分类或有账目即抛错；`delete_account()` 有账目即抛错 |

`init_db()` 里 DDL 与 DML 分成两个 `with conn:`：SQLite 的 DDL 会隐式提交前面的事务，混在一个事务里会让「升级失败 = 什么都没改」这个假设不成立（v0.04 已经踩过一次）。

### 后端接口（app.py）

| 接口 | 说明 |
| --- | --- |
| `GET /api/categories` | 返回两级树 `[{id, name, parent_id, children: []}]` 与总数 |
| `POST /api/categories` | `{name, parent_id?}`；父级不存在 400、同级重名 409、二级下再建三级 400 |
| `PUT /api/categories/<id>` | 改名，同时 `UPDATE records SET category = ?` 同步冗余显示名 |
| `DELETE /api/categories/<id>` | 有子分类或有账目 409 |
| `GET /api/accounts` | 同时给平铺列表 `accounts` 与按大类分组的 `groups` |
| `POST /api/accounts` | `{name, group_name, balance}`；大类白名单校验、重名 409 |
| `PUT /api/accounts/<name>` | 改余额或改大类，名字用 URL 编码传 |
| `DELETE /api/accounts/<name>` | 有账目 409 |
| `GET /api/records` | 新增 `category_id` / `parent_id` 两个筛选参数 |

### 前端交互（index.html / script.js / style.css）

| 需求 | 做法 |
| --- | --- |
| 分类级联 | 一级下拉 `value` 换成分类 id；`change` 时查 `state.categories` 找子分类，有子分类才 `classList.remove("d-none")` 显示二级下拉 |
| 账户分组 | `accountOptionsHtml()` 拼 `<optgroup label="资金账户">`，选项文字带 `（¥余额）` |
| 资产页卡片 | `renderAccountGroups()` 按 `groups` 渲染，每类一个小计，卡片带 `data-account` |
| 点卡片联动 | 事件委托拿到账户名 → `selectAccount()` 高亮卡片 + 拉 `?account=` 流水 + 解除快捷记账禁用 |
| 快捷记账 | `lockAccount()` 设 `select.value` 并 `disabled = true`；`hidden.bs.modal` 时统一复位移除锁定 |
| 分类管理 | 树形 `<ul>` 渲染一级/二级，每行独立删除按钮；新增表单用「作为一级分类 / 挂在某一级下」二选一 |
| 新增账户 | 名称 + 大类下拉 + 初始余额，成功后重拉账户与统计 |

## 四、表结构与接口实测

升级前的真实库（8 条账目、支出 808.14）执行一次 `init_db()`：

```
tables  = ['records', 'sqlite_sequence', 'accounts', 'categories']
records 列 = id, amount, category, note, date, account, type, category_id
accounts 列 = name, balance, group_name
categories 行 = 24（一级 7：餐饮/交通/购物/娱乐/居住/其他/卫浴；二级 17）
records 行 = 8，金额合计 808.14（与升级前一致）
category_id 空值 = 0
```

接口抽样实测：

| 请求 | 结果 |
| --- | --- |
| `POST /api/records {category_id: 2, ...}` | 201，`category: "早餐"`、`category_parent: "餐饮"` |
| `POST /api/records {category: "不存在的分类"}` | 201，自动建一级分类 |
| `POST /api/categories {name: "餐饮"}` | 409 `{"error": "同一父级下已存在同名分类"}` |
| `POST /api/categories {name: "浓缩", parent_id: 二级id}` | 400 `{"error": "最多支持两级分类"}` |
| `DELETE /api/categories/1` | 409（下面有子分类 / 有账目） |
| `PUT /api/categories/2 {name: "早饭"}` | 200，账目里的 `category` 一并变成「早饭」 |
| `POST /api/accounts {group_name: "信用卡"}` | 400 `{"error": "group_name 只能是 资金账户 / 储蓄账户 / 投资账户"}` |
| `GET /api/records?parent_id=1` | 命中「餐饮」自己和它的全部二级分类 |

## 五、验证记录

**一）迁移自检 33 条 + 接口自检 47 条**（全部通过）

- 老库 8 条账目全在、金额 808.14 不变、`category_id` 零空值、重复 `init_db()` 幂等；
- 二级分类记账带 `category_parent`、未知文本自动建一级、重复/层级/删除保护各类 400/409 都对；
- 账户大类白名单、重名、有账目不可删、改名连带改账目全部符合预期；
- 测试在 `records.db` 的副本沙箱里跑，清理后统计回基线。

**二）前端自检 42 条**（Node + 极简 DOM 桩，跑在真实接口上，`alert` 触发 0 次）

| 分组 | 断言要点 |
| --- | --- |
| 级联 | 选「餐饮」后二级下拉出现且含「早餐」，首项是「不细分」；选「其他」时二级下拉隐藏 |
| 分组下拉 | 三个 `<optgroup>` 都在，选项文字带余额 |
| 资产页 | 卡片数 = 账户数，三个大类都渲染，点「微信」后标题变「微信 · 流水」且行数 = 接口条数 |
| 快捷记账 | 弹窗打开后账户 `disabled=true` 且值 = 微信，关窗后解锁 |
| 保存 | 用二级分类保存后账目 +1、`category_parent` = 餐饮、表格行数 = 接口条数 |
| 编辑 | 标题含 `#id`、按钮变「保存修改」、金额 / 一级 / 二级 / 时间全部回填正确 |
| 分类管理 | 新增二级分类后树里出现，删除后回到基线 |
| 账户 | 新增大类正确、初始余额 88.8 正确，删除后回基线 |
| 日历 / 卡片 | 35 格且是 7 的倍数；统计卡片与 `/api/statistics` 完全一致 |

**三）真实浏览器复核**（Edge headless，`--dump-dom --virtual-time-budget=6000`）

DOM 32412 字符；账单表格 9 行，首行 `2026-10-26 09:30`；账户卡片已渲染（没有「正在加载账户」占位）；日历 35 格；总余额卡片 `¥2795.20`，与账户表求和一致。

## 六、踩坑与结论

1. **`NULL` 会让唯一索引失效**：`CREATE UNIQUE INDEX ... ON categories(parent_id, name)` 挡不住两个 `parent_id IS NULL` 的「餐饮」——SQLite 里 `NULL` 互不相等。改成 `COALESCE(parent_id, 0)` 才真正挡住。
2. **DDL 会提前提交事务**：迁移脚本里先 `CREATE TABLE` 再 `INSERT`，中途 `INSERT` 报错时表已经建好了，「升级失败等于没动过」不成立。后续所有迁移都拆成 DDL / DML 两段，并且种子数据一律 `INSERT ... SELECT` 前先查重。
3. **`INSERT ... SELECT` 的列数必须对齐**：`INSERT OR IGNORE INTO accounts (name, balance) SELECT DISTINCT account FROM records` 报 `1 values for 2 columns`，补成 `SELECT DISTINCT account, 0`。
4. **前端只能信接口返回的层级**：二级下拉不能用「名字里有没有斜杠」猜，必须按 `parent_id` 查子分类；`records` 里的 `category` 只是冗余显示名，`category_id` 才是关系。
5. **下拉框的 `value` 与 `text` 要分开**：分类下拉 `value` 用 id、显示用名字；账户下拉的显示文字带余额，但 `value` 只能是账户名，否则 `POST` 会带上「现金（¥100.00）」这种非法值。
6. **自检脚本必须自己定位自己造的数据**：曾经用 `records[0]` 当「刚创建的那条」，POST 失败时它指向了用户手记的一条真实记录，结果被脚本删掉。改用「唯一备注 + `find()`」定位，且每个测试都自己清理。
