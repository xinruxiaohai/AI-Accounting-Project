# 49 · v0.15.2 AI 文本识别准确率收尾 · Agent B

> 交付对象：**Agent B**（沿用原 B 模块）。上一轮已改 SYSTEM_PROMPT（中文口语金额 / confidence 分档 / 微信零钱与转账人名 few-shot），但**尚未复跑对照**，本轮以复跑数据为唯一依据继续提准确率。

## 必读
- `docs/HANDOFF.md`「二、并行 Agent 协作声明」
- `D:\Project\temp\ai-qa-v01434\accuracy_report.md`（66 case 基线：51/66 = 77.3%）
- `D:\Project\temp\ai-qa-v01434\PROMPT_SUGGESTIONS.md`（A1–A6 建议清单）
- `D:\Project\temp\ai-qa-v01434\compare_test.py` + `cases.jsonl`（现成对照脚本）

## 基线短板（必须盯死）
| 指标 | 基线 | 目标 |
|---|---|---|
| 总通过率 | 51/66 = 77.3% | ≥ 60/66 = 90% |
| 账户/联系人匹配 | 4/12 = 33.3% | ≥ 75% |
| confidence 90-100 占比 | 58/62 = 93.5% | ≤ 60%，且至少 5 个 < 70 |
| AIServiceError（线上 502） | 3 个 case | 0 |

## 白名单
`ai_service.py`：
- `SYSTEM_PROMPT` 文本段（约 137–292 行）
- `_normalize_record` / `_normalize_debt`（约 818–880 行）
- `_match_contact`（联系人模糊匹配）

其它文件一律禁止。**`ai_service.py` 与 D 共用**：先确认 D 不在跑，或约定「B 先改完提交 → D 再动」。

## 任务
1. **先复跑，不要先改**：用 `compare_test.py` + `cases.jsonl` 在隔离库跑一遍，产出 before/after 逐 case 对照表（pass/fail + 字段 diff）。这是后续所有改动的依据。
2. **账户召回 ≥75%**：规则前移强抽取——「句子里出现具体渠道或商户名（微信/支付宝/银行卡/信用卡/现金/某店名）时 `account` 必须原样填，不得留空；完全没提渠道才填空串」；子账户（零钱/余额/零钱通/储蓄卡/信用卡）连同品牌整体输出；few-shot 补三条：`微信零钱付款30元 → account:"微信零钱"`、`支付宝余额付款50 → "支付宝余额"`、`在屈臣氏买洗发水60 → account:"屈臣氏"`。
3. **联系人全称保留**：身份称呼（同事/室友/房东/表妹/同学）整体保留，不得只取名；few-shot 改 `借给同事小王20元 → contact_name:"同事小王"`；工程侧 `_match_contact` 增加**包含关系兜底**（一方是另一方子串且长度差 ≤3 视为同一人），**不要全局下调阈值**（会误配）。
4. **confidence 校准**：所有 unknown / 含糊示例的 confidence 改到 **20–45**（示例是 glm-4-flash 最强模仿源，示例给 95 直接导致未知也高分）；明确「金额缺失、字段靠默认值补齐、多金额需猜测 → < 80」「action=unknown → ≤ 50」。
5. **消灭 502**：`ai_service.py:818`「金额必须大于 0」直接 `raise` → 无金额输入（C04「昨天打车」）线上 502。改为返回合法 JSON（`need_confirm` 或低置信 + note「没识别到金额，请补充」），**保持"绝不猜金额"原则**；`ai_service.py:822` 的转账缺 `to_account` 兜底已存在，不要回退。

## 红线
- 不改表结构 / 路由 / 前端；**不动 `VISION_PROMPT`（D 的地盘）**；不 bump 版本号。
- 测试隔离：`ZHZ_SQLITE_PATH` 指向 `D:\Project\temp\ai-qa-v0152-text\` 副本，teardown 清理，主库 `records.db` md5 前后一致。
- 禁 `/register`，只用 `test@test.com`（本地 uid 93）/ `temp_cdp_v0140@example.com`（uid 90），JWT `sub` 字符串。
- 真实调用智谱 API，Key 从 `.env` 读，**绝不写死**。

## 验收
1. 66 case 复跑：总通过率 ≥ 90%、账户/联系人 ≥ 75%、confidence 90-100 占比 ≤ 60% 且出现 ≥5 个 <70、`AIServiceError` = 0。
2. 逐 case before/after 对照表（字段级 diff）。
3. 不回归：意图分类 12/12、多轮补改 10/10、余额回滚 1/1。
4. 主库 md5 不变。

## 交付
文件清单 + 改动行号 + 对照表 + 遗留；`git add` 只加 `ai_service.py`；提交信息：
`feat(ai-text): v0.15.2 文本识别账户/联系人召回与置信度校准`
