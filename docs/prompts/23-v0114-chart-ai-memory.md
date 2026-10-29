# 23 · v0.11.4 图表可读性 / AI 置信度与纠错 / 多图串行 / 防重与记忆库

## 需求背景

- 首页近 30 天趋势图图例压着 toolbox，三条线同色同粗细互相糊住，结余看不清。
- AI 常把商户名当分类返回（「滴滴」「星巴克」），建出一堆无意义分类；解析结果没有可信度，用户不知道哪笔要核对。
- 截图记账一次只能传一张，多图要么并发打爆后端、要么没有进度。
- 10 分钟内可能重复记账同一笔；AI 纠错结果不能沉淀成后续解析的经验；管理端看不到纠错记忆。

## 核心 Prompt（要点）

- 文本版 SYSTEM_PROMPT 字段扩到 16 个，新增 `confidence` 整数 0-100，并加【置信度规则】：每次输出都要带，金额/分类/时间都能从原话明确确定时给 90 以上，靠猜测或默认值补齐时低于 80。
- 【record 规则】补一句：分类必须是标准分类名，绝对不要把商户名当分类，「滴滴」「星巴克」是商户。
- previous_record_id 命中时，_previous_record_block 注入「用户正在补充修改账单，请覆盖原数据」，避免模型另起一笔。
- ai_memory few-shot 块拼在 user 内容前，最多最近 3 条「原话 → 纠正后分类」。

## AI 方案简述

- 后端：ai_service.CATEGORY_MAPPING 在 _normalize_category 里按「完全匹配 + 最长子串包含」强制改写；_as_confidence 夹到 0-100、缺省 80；/api/records/ai 与 SSE 返回体带 confidence，previous_record_id 走覆盖更新分支，force 跳过防重。
- 前端：趋势图 trendOption 重排 legend/toolbox/grid，结余 dashed + z:1 + 渐变 areaStyle，三线 opacity 0.8；上传用 for...of + await 串行，每图独立气泡「识别中 i/N」；confidence<80 气泡变黄提示核对；气泡内输入框与详情【AI 纠错】都调 /api/records/<id>/correction。
- 防重：database.find_recent_duplicate 只看最近 10 分钟且 created_at 非空的记录，金额一致 + 商户/账户 token 相似即命中；保存前 duplicate-check 预检、AI 路径 409 duplicate、force 重发三通道。
- 记忆库：新建 ai_memory 表，纠错成功落一条，解析前取最近 3 条当 few-shot；/admin 新增 Tab 支持查看/新增/删除。

## 踩坑结论

- 分类映射必须按「最长子串」匹配，「滴滴出行」要优先于「滴滴」，否则会被短词截胡。
- 纠错接口与 /api/ai-memory POST 返回结构不同（前者 {"memory","record"}，后者是记忆本体），前端必须分开解析。
- 串行上传不能用 Promise.all，否则并发打爆后端且进度乱序；单张失败只结束该气泡，不能中断队列。
- confidence 是「模型自评」，后端只做夹取与透传，不能拿它反过来改解析结果。
- 沙箱把项目目录设成只读时写 records.db 会报 readonly，端到端自测前先确认目录可写。
