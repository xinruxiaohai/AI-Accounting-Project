AI 记账管家 项目动态交接文档

【最高强制规则】

本文档仅保留当前最新状态与下一步计划，严禁堆积流水账。

每次完成“大版本迭代”（已打 Tag 封版），AI 必须自动重写第一板块（当前状态）与第六板块（下一步计划）。

每次大版本封版，必须同步补全 docs/prompts/ 下的 Prompt 快照，并严格按照第三板块的规范更新 docs/dev-log.md。

一、当前项目状态
当前版本：v0.08.1-DEV（后端意图路由已联调通过，前端未重构）
当前进度：AI 能识别记账 / 借贷 / 添加联系人 / 听不懂四种意图，/api/records/ai 按 action 分流写库并联动余额；顶栏仍是 v0.08 的单行 AI 输入框，Step 3 的 AI 弹窗重构、Step 4 的报销开关与资产页统计尚未开始。
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
/api/records/ai (POST) AI 意图分流：record / debt / add_contact / unknown。

六、下一步行动计划
当前目标：完成 v0.08.1-DEV 的前端部分（后端意图路由已联调通过，可直接接）。
执行步骤：
1. Step 3 AI 交互重构：删掉顶栏旧 AI 输入框，在「+ 记一笔」旁加蓝紫渐变星星【AI 快记】按钮，点开 Bootstrap Modal（多行输入 + 发送 Loading + Esc 关闭 + Ctrl+Enter 发送），按后端 action 弹对应 Toast（记账成功 / 借贷已记录 / 联系人已添加 / 无法理解）并刷新看板。
2. Step 4 报销闭环：账单详情弹窗加报销开关（空心变实心黄），开启后选报销人与金额（默认全额）；资产页增加待报销 / 已报销统计。
3. 每步完成跑 py_compile / node --check 与端到端自测，通过后更新 dev-log；全部完成封 v0.08.1-DEV 并打 tag 推送。
备注：.env 换 Key 后必须彻底结束旧 Flask 进程再启动，否则旧进程仍持有旧密钥返回 401。
