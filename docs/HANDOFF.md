AI 记账管家 项目动态交接文档

【最高强制规则】

本文档仅保留当前最新状态与下一步计划，严禁堆积流水账。

每次完成“大版本迭代”（已打 Tag 封版），AI 必须自动重写第一板块（当前状态）与第六板块（下一步计划）。

每次大版本封版，必须同步补全 docs/prompts/ 下的 Prompt 快照，并严格按照第三板块的规范更新 docs/dev-log.md。

一、当前项目状态
当前版本：v0.10.1-DEV（v0.10 全量重构 + 六项 UI 补丁：日期选择器、资产页高度、图表高度、悬浮球越界、Tooltip 残留、长账户名挤压，已自测封版）
当前进度：v0.10 已完成五组重构。后端 AI 升级为意图路由 + 代买/报销场景（抽出 is_reimbursable 与 contact_name，报销自动关联联系人并记入待报销），新增 /api/records/ai/stream SSE 分阶段推送解析进度，新增 ai_feedback 表与 /api/feedback（错误文本 / AI 结果 / 用户纠正），/admin 增加「AI 反馈与记忆」Tab。全站骨架锁 100vh 内部各自滚动，manifest 改为 window-controls-overlay 并用 env(titlebar-area-*) 让 topbar 避开窗口控制按钮；首页卡片缩小 20%，资产页左 4 成（净资产卡 + 四统计卡）右 6 成纯流水；新增「账单」页：左侧年月树带当月收支，右侧关键词 / 类型 / 账户 / 日期区间 / 金额区间筛选与八列大表格。交互层：金额语义色全局生效（仅收支红绿，借贷转账深色），侧栏点击后强制收起残留 Tooltip，账单流支持年 / 月 / 日三级折叠（localStorage 记忆），资产统计四卡点击弹明细；悬浮球钢笔径向四分支（普通记账 / AI 文本快记 / AI 截图识别占位 / 帮助），3 秒无操作收回，帮助弹窗含快捷键与功能速览。AI 输入框前置正则极速拦截（如「午饭30」无账户自动补「现金」直接入库），其余指令立即关窗并在右下角弹出可并发气泡，走 SSE 打字机与思考动效，3 秒后淡出、悬停或失焦暂停倒计时，成功气泡点击直达详情。v0.10.1 补丁针对验收反馈修复六处细节：账单页与管理后台的日期字段改成「中文占位文本框 + 全尺寸透明原生选择器覆盖层」，选择后立即回显并同步筛选状态；资产页左右两栏改为 align-items:stretch，右侧流水面板与空态撑满高度；首页图表容器补 min-height:240px，画布 210px 不再被压缩截断；悬浮球四向展开全部改为向左/向上位移，任何窗口宽度都不越出视口；侧栏导航 Tooltip 改为 hover 触发并在点击时 hide()+blur()，不再残留；账户名补 display:block + ellipsis，金额 flex 固定不挤压。下一步进入 v0.11（报销进阶与报表）。
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

ai_feedback: id, raw_text(用户原话), parsed(AI 解析 JSON), corrected(用户纠正 JSON), source, status(pending/processed), created_at。

五、核心后端 API 速查
/api/records (GET/POST/PUT/DELETE)
/api/accounts (GET/POST/PUT/DELETE)
/api/categories (GET/POST/PUT/DELETE)
/api/statistics (GET)
/api/notifications (GET/POST/PUT/DELETE)
/api/upload (POST)
/api/records/ai (POST) AI 意图分流：record / debt / add_contact / unknown（兼容旧调用）。
/api/records/ai/stream (POST) SSE 流式解析：thinking → extracting_amount → resolving_category → saving → done / unknown / error。
/api/feedback (POST/GET) 与 PUT /api/feedback/<id> AI 反馈记忆：记录原始文本、解析结果、用户纠正，状态 pending / processed。
PUT /api/records/<id>/reimbursement 报销开关（只改报销字段，不动余额与统计）。
GET /api/records/trash 回收站列表；PUT /api/records/<id>/restore 恢复；DELETE /api/records/<id>/purge 彻底删除（DELETE /api/records/<id> 现为软删除，余额同步回滚）。

六、下一步行动计划
当前目标：v0.10-DEV 已完成（AI 流式解析与报销入库、反馈记忆库、PWA 骨架、账单页、全局气泡与四向悬浮球），进入 v0.11 功能深化。
执行步骤：
1. AI 截图识别：接入视觉模型把账单截图转成结构化记录，复用现有 SSE 气泡链路。
2. 报销进阶：部分报销进度、按报销人筛选账单、报销记录导出；反馈数据用于纠正 Prompt。
3. 数据安全：一键备份 / 恢复（SQLite 导出导入），导出 CSV 增加报销字段。
4. 报表页：月度/年度趋势与分类占比图表，替代纯文字统计。
5. 移动端细节与可访问性（焦点顺序、对比度、触控热区）。
6. 封版后 py_compile / node --check 加端到端自测，更新 dev-log 与 prompts；本机暂连不上 GitHub，网络恢复后 push main 与 v0.08.1-DEV / v0.09-DEV / v0.09.1-DEV / v0.09.2-DEV / v0.10-DEV 标签。
备注：.env 换 Key 后必须彻底结束旧 Flask 进程再启动，否则旧进程仍持有旧密钥返回 401。
