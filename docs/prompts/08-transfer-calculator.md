# 08 · 转账、公式计算与全局 Toast（Prompt 快照）

## 一、这一步要解决什么

v0.05 的账本已经能记收支、分二级、按账户看流水，但还有四个「用起来别扭」的地方：

1. 所有提示都是浏览器原生 `alert()`，白底黑字、和整页风格完全脱节，还挡住页面。
2. 金额框只能敲一个数。真实记账里经常是「三个人 AA，一个人 15.5，两个人 20」，用户得自己掏出计算器算完再填。
3. 借钱还钱、银行卡转余额宝这类「钱从一个账户挪到另一个账户」的操作，只能记成「支出 + 收入」两条，既容易漏记一笔，又会让当月的总支出/总收入虚高。
4. 资产页点【在此账户下记一笔】时，账户下拉被 `disabled` 锁死；万一点错了账户，只能关掉弹窗重来。

这一步要把这四件事一起解决，并保证老数据（10 条账目、8 个账户、24 个分类）一条不丢。

## 二、用户原始 Prompt（摘录）

> 分步执行、绝不一次性全发，每步必须经我确认。四件事：
> ① 全局 Toast 替换所有 alert()，成功绿、失败红；
> ② 高级计算器与公式留存——math.js 下载到 static/vendor/ 本地引用，**严禁 eval**，金额框可输 15.5+20*2，右下角灰字实时显示 = 56.00，保存时 amount 存结果、formula 存公式，编辑时金额框回显公式；
> ③ 转账业务——弹窗加「转账」模式，转账时隐藏分类、显示【转出账户】【转入账户】【手续费(默认0)】，余额联动为「转出 -(金额+手续费)、转入 +金额」，不计入常规收支；
> ④ 资产页快捷记账默认选中当前账户但**不再 disabled**，允许改。
> Step 1 只改 database.py + app.py，写完自己在后台写临时脚本跑边缘测试（负数金额、转入转出相同、余额不足等必须 400），汇报自测结果等我确认。

> 三个判断全票同意。直接进 Step 2 前端：给我 templates/index.html 和 static/script.js 的完整代码。写完代码后，请自己仔细检查 DOM 绑定和 JS 语法，并在浏览器里跑通后再汇报。

（Prompt 为要点摘录，非逐字。）

## 三、AI 给出的方案要点

### database.py（改造）

| 动作 | 代码 | 为什么 |
| --- | --- | --- |
| 新增三列 | `formula TEXT NOT NULL DEFAULT ''`、`to_account TEXT NOT NULL DEFAULT ''`、`fee REAL NOT NULL DEFAULT 0` | 仍走 `ALTER TABLE ... ADD COLUMN`，老库不重建、不丢数据；`fee` 是用户没点名但必须落库的（不落库就没法回显、也没法精确回滚） |
| 类型白名单 | `RECORD_TYPES = ("expense", "income", "transfer")` | 三态取代两态；转账的分类固定为 `TRANSFER_CATEGORY = "转账"`、`category_id` 为 NULL |
| 余额效果表 | `_balance_effects(type, account, to_account, amount, fee)` → `[(账户, 变化量), ...]` | 收入 `[(acc, +amount)]`、支出 `[(acc, -amount)]`、转账 `[(转出, -(amount+fee)), (转入, +amount)]`。删掉旧的 `_signed()`，只留一套规则 |
| 转账校验 | `_transfer_problem(conn, account, to_account, amount, fee)` | 缺转入账户 / 转出=转入 / 账户不存在 / `balance + 1e-9 < amount + fee` 四种情况返回中文原因 |
| 增删改 | `add_record(...)`、`update_record(...)`、`delete_record(...)` | 三者都只调 `_apply_effects`；编辑走「先撤销旧账 → 再校验新账 → 最后施加新账」，校验失败抛 `RecordError` 让撤销一起回滚 |
| 流水筛选 | `WHERE (r.account = ? OR (r.type = 'transfer' AND r.to_account = ?))` | 一笔转账在转出、转入两个账户的流水里都该出现 |
| 账户引用保护 | `delete_account()` 的引用检查补 `to_account` | 否则能删掉还在被当作转入方的账户 |

两处判断（已向用户说明并获同意）：

- **转账要求两个账户真实存在**：支出时账户名打错会自动建号（v0.03 的便利），但转账若也这样，「招行卡」手滑写成「招商卡」就会凭空多出一个账户，钱转进去再也对不上账。
- **余额不足只卡转账**：支出仍允许负余额（v0.03「如实记录」的决定），转账是把钱从一个口袋挪到另一个口袋，余额不够就不是记录而是编造。

### app.py（改造）

- `_parse_formula(value)`：只校验「是字符串且长度 ≤ 200」，不解析算式 —— 结果由前端算好再提交，后端二次计算只会引入「两边算出不同数字」的风险。
- `_parse_record(data)` 按类型分支：转账必须有 `to_account` 且不能为空、`fee` 必须是非负数字、`category` 强制「转账」、`category_id` 置空。
- `create_record` / `update_record` 改为接收 `(结果, 错误)` 二元组，`RecordError` 一律映射成 400 + 中文原因。

### 前端（index.html / script.js / style.css）

- 金额框 `type="number"` → `type="text"`（数字框存不下 `15.5+20*2`），下方 `#amount-hint` 灰字实时显示 `= ¥55.50`，算不出来加 `.is-error` 变红。
- `amountFromInput(raw)`：纯数字走 `Number()` 快速路径（不进 math.js，避免 `0.1+0.2` 的浮点尾）；带运算符才 `window.math.evaluate`，且必须 `Number.isFinite`、`> 0`。
- 类型组加「转账」：`applyTypeUi()` 统一切 `#category-col` / `#to-account-wrap` / `#fee-wrap` 的 `d-none`，并把 `#account-label` 文案改成「转出账户」。
- `toast(message, type)`：顶部居中滑出，绿色成功 / 红色失败，2.4 秒自动消失；12 处 `alert()` 全部替换（删除仍用 `confirm` 保留二次确认）。
- 列表：转账显示 `微信 → 支付宝`、徽章「转账」，金额下方小字「含手续费 ¥1.50」。
- 快捷记账：只预选账户，不再 `disabled`。

## 四、表结构与接口实测

`PRAGMA table_info(records)`（11 列）：

```
(0, 'id', 'INTEGER', 0, None, 1)
(1, 'amount', 'REAL', 1, None, 0)
(2, 'category', 'TEXT', 1, None, 0)
(3, 'note', 'TEXT', 1, "''", 0)
(4, 'date', 'TEXT', 1, None, 0)
(5, 'account', 'TEXT', 1, "'现金'", 0)
(6, 'type', 'TEXT', 1, "'expense'", 0)
(7, 'category_id', 'INTEGER', 0, None, 0)
(8, 'formula', 'TEXT', 1, "''", 0)
(9, 'to_account', 'TEXT', 1, "''", 0)
(10, 'fee', 'REAL', 1, '0', 0)
```

升级后 `records` 10 行、`type='transfer'` 0 行 —— 老数据一条没动。

接口行为（实跑）：

| 请求 | 结果 |
| --- | --- |
| `POST /api/records` `{type:"transfer", account:"微信", to_account:"支付宝", amount:10, fee:1.5}` | 201，`category="转账"`、`category_id=null`；微信 -11.5、支付宝 +10 |
| `POST` 转出与转入同名 / 缺 `to_account` / 账户不存在 / `fee:-1` / `fee:"abc"` / 余额不足 | 全部 400，中文原因 |
| `POST` `{amount:55.5, formula:"15.5+20*2"}` | 201，两字段分别入库，`GET` 原样读回 |
| `PUT /api/records/<id>` 改成余额不足 | 400，且余额一分未动（撤销被一起回滚） |
| `GET /api/records?account=支付宝` | 命中「转入方是支付宝」的转账 |
| `DELETE /api/accounts/微信`（有转账在用） | 409 |

## 五、验证记录（实跑）

- **后端自测 47/47**：迁移 5 条、转账主流程 11 条、非法请求 13 条、公式留存 6 条、编辑删除回滚 7 条、账户保护 1 条、清理 3 条。
- **前端自检 52/52**：Node + DOM 桩跑真实接口，`alert` 0 次。覆盖公式实时结果 `= ¥55.50`、错误公式红字、金额写错只弹 Toast 不落库、公式记账入库 `amount=55.5 / formula=15.5+20*2`、转账 -11.5/+10、转账不计入收支、列表「转账」徽章与 `微信 → 支付宝`、编辑回显公式与转账字段、快捷记账不再 disabled、删除后余额与统计一分不差回基线。
- **Edge headless 复核**：DOM 30663 字符、表格 10 行、账户卡片 8 张、日历 35 格、卡片 `¥0.01 / ¥830.03 / ¥2783.20`、首行 `2026-10-26 09:11 · 支出 · 餐饮 / 晚餐 · 银行卡 · -¥12.00`。
- **清理后基线**：`{"balance_total": 2783.2, "expense_total": 830.03, "income_total": 0.01}`，10 条账目、无测试残留。

## 六、踩坑与结论

1. **`type="number"` 的输入框存不下算式**：`15.5+20*2` 敲进去，浏览器认为不是合法数字，`input.value` 直接是空串（看起来像「输入被吞了」）。必须换 `type="text" inputmode="decimal"`，既保住手机数字键盘，又能存算式。
2. **math.js 的 `evaluate("1/0")` 不抛错，返回 `Infinity`**：只 `try/catch` 不够，还要 `Number.isFinite(result)`；否则 `Infinity` 会一路变成 `amount: Infinity` 再被后端 JSON 序列化成 `Infinity`（非法 JSON）。
3. **`evaluate("alert(1)")` 会抛 `Undefined function alert`**：math.js 是白名单式解析，比 `eval` 安全 —— 但结论是「不能用 eval」，不是「math.js 免检」，仍然要自己判结果类型与有限性。
4. **自检脚本的期望值要基于「紧邻的上一态」**：第一轮 2 条 FAIL 全是断言算错（期望 3380.50、实际 3324.00，漏算了脚本自己刚记的两笔支出）。拿很久以前的基线做绝对比较，失败的一定是脚本。
5. **`records[0]` 不能当「我刚建的那条」**：POST 失败时它指向用户自己记的账，脚本顺手删掉了用户的真实数据。自检必须用唯一备注 `find()` 定位自己造的行。
6. **前端桩子里 `className = "..."` 与 `classList` 是两套存储**：只改 `className` 不会同步 `classList`，断言颜色类名就会失败；桩子要加 `set className` 同步。
