# 24 · v0.11.5 AI 精准识别、气泡多轮覆盖与纠错反馈中心

## 一、需求背景

v0.11.4 已经能返回 confidence、记录 ai_memory，但真实使用中暴露三个问题：

1. AI 不知道用户库里有哪些账户，常把「微信零钱」当新账户，或把「威信零钱通」这种同音错字原样入库；
2. 气泡里「改成微信零钱，金额 50」只改了分类/金额两个字段，账户余额没有回滚，报销字段也会丢；
3. 后台只能看 ai_memory，看不到「AI 到底改了哪些字段、改前改后对不对」。

## 二、核心 Prompt（ai_service）

- SYSTEM_PROMPT 增加【账户规则】：用户提到具体子账户时原样保留，不要向上合并成大类账户；
- `_accounts_block(accounts, contacts)`：注入数据库真实账户/联系人清单（最多 40 个）；
- `_previous_record_block(previous_record)`：注入原账单**完整** JSON，并写明「用户正在补充修改账单，请覆盖原数据」「用户没提到的字段沿用原账单的值，返回完整 JSON」；
- `_memory_block(memories)`：把关键词命中的 ai_memory Top 3 拼成【用户历史纠错记忆】few-shot 段；
- 输出字段保持 16 个（含 confidence 0-100）。

## 三、方案简述

- **相似度强制替换**：ai_service 用 difflib.SequenceMatcher 计算账户/联系人相似度，阈值 0.8；
  规则顺序：精确同名 → 子账户后缀（品牌写对就保留）→ 别名表（威信→微信）→ difflib 兜底；
  被替换时返回 `auto_corrected` 列表与 `auto_corrected_msg`。
- **多轮全量覆盖**：新增 `POST /api/records/<id>/ai-revise`；后端 `_apply_ai_correction`
  拿到完整 JSON 后调 `database.update_record` 全量 UPDATE，余额由「先撤旧账 → 校验新账 → 落新账」自动回滚/重算；
  报销字段单独同步；改动写 `ai_memory` 与 `ai_correction_log`。
- **前端**：气泡灰色小字展示 `auto_corrected_msg`；气泡输入框改调 `/ai-revise`；
  confidence<80 继续黄牌。
- **后台**：/admin 新增「AI 纠错与反馈中心」Tab，左栏 ai_memory、右栏 ai_correction_log 改前/改后对比。

## 四、踩坑结论

1. 别名表替换一定要判断「品牌本身是否写对」，否则「微信零钱通」会被吞成「微信」；
2. accounts/contacts 参数要在四条 AI 路由上都传，漏一处该链路就退化成不做纠正；
3. 测试 /api/records/ai 前要先撤掉造出来的测试账单，否则会命中 10 分钟防重返回 409；
4. 气泡里改账户必须走后端全量覆盖，不能前端拼部分字段，否则余额与报销字段会不一致。
