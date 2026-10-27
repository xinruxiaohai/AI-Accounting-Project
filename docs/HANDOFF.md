AI 记账管家 项目动态交接文档

【最高强制规则】

本文档仅保留当前最新状态与下一步计划，严禁堆积流水账。

每次完成“大版本迭代”（已打 Tag 封版），AI 必须自动重写第一板块（当前状态）与第六板块（下一步计划）。

每次大版本封版，必须同步补全 docs/prompts/ 下的 Prompt 快照，并严格按照第三板块的规范更新 docs/dev-log.md。

一、当前项目状态
当前版本：v0.07.2-DEV
当前进度：AI 接口代码已全部写完并测试了 Mock 逻辑（顶栏「AI 快记」→ POST /api/records/ai → 智谱解析 → 复用 add_record 写库并联动余额），但真实 API 调用卡在 401 密钥无效，需更换有效 Key 后重启服务验证；v0.07 Step 3 报销与回收站界面仍未开始。
运行方式：Windows PowerShell 在根目录执行 .\venv\Scripts\python.exe app.py

二、AI 核心开发契约

极简输出：直接后台写文件，聊天框禁贴全量代码，只报“改了哪个文件、哪几个函数”，字数<150字。

自主审查：改完必须在后台自测（语法/联动/旧功能），汇报附【自审结论】。

用户通知规范：纯底层修复、样式微调与内部重构只写 dev-log，不在应用内发通知；只有用户能直接感知的新功能或行为变化，才在 /admin 发布一条通知。

安全红线：自动化测试绝不能盲删真实数据，必须用唯一备注定位测试数据。

交互规范：全站禁用 alert()，统一用 Toast；弹窗支持 Enter 提交、Esc 关闭；表格必须防挤压。

三、文档编写与测试纪律（严格遵循）

日志书写规范（试行版，等用户提供最终示例后替换）：docs/dev-log.md 必须按版本里程碑记录。允许使用常规标点符号行文，不要死板使用星号。内容严禁贴大段代码或函数名，但必须清晰概括出每个版本的“核心实现技术路径”（如：后端使用 Flask 结合 sqlite3 实现 CRUD，前端通过原生 fetch 交互等）。每个版本控制在 3-5 句话以内。

Prompt 快照规范：每次完成核心功能，必须在 docs/prompts/ 下按序号生成 md 快照（如 09-form-validation.md）。文件内仅记录：需求背景、核心 Prompt、AI 方案简述、踩坑结论。

专属临时目录：所有测试脚本、截图、无头浏览器缓存等，必须统一存放在 D:\Project\temp 目录下。绝对禁止写入项目源代码目录。常规修改仅需 py_compile 和 node --check 语法检查，严禁乱写测试浪费 Token。

临时文件索引：在 D:\Project\temp 维护 index.md 说明脚本作用，每次迭代后只删无用/错误文件，无需清空。

四、核心数据模型速查

records: id, amount, type(expense/income/transfer), account, to_account, fee, category_id, formula, date, deleted_at(软删除预留)。

accounts: name(PK), balance(唯一真相), group_name。

categories: id, name, parent_id (二级分类)。

五、核心后端 API 速查
/api/records (GET/POST/PUT/DELETE)
/api/accounts (GET/POST/PUT/DELETE)
/api/categories (GET/POST/PUT/DELETE)
/api/statistics (GET)
/api/notifications (GET/POST/PUT/DELETE)
/api/upload (POST)

六、下一步行动计划
当前目标：换到有效密钥后完成 AI 解析的真实联调，通过即封版 v0.08。
执行步骤：
1. 在项目根目录 `.env` 写入有效的 `ZHIPU_API_KEY`，保存后重启 Flask（debug 模式会自动重载，但 .env 只在启动时读一次，建议手动重启）。
2. 运行 `D:\Project\temp\test_ai_real.py`（venv 的 python），必须打印 `STRICT_JSON_OK`，金额 30、类型 expense、日期为「昨天」对应的 `YYYY-MM-DD HH:MM`。
3. 打开首页，在顶栏 AI 快记输入「昨天打车花了 30」，确认 Toast 报出分类与金额、账单列表与本月支出随之刷新、账户余额正确扣减；测试账目用唯一备注定位后删除。
4. 全部通过后：更新 dev-log 与 HANDOFF 为 v0.08-DEV（已封版），提交代码并打 tag `v0.08-DEV` 推送。
备注：若仍 401，先确认 key 未过期且有 glm-4-flash 权限，再用 curl 直打智谱接口排除网络/代理因素。
