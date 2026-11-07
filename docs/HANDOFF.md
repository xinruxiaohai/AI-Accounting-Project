智汇账 项目交接文档

【最高红线规则 · 未经用户明确指令禁止修改本段】
1. 字数控制：本文件内容超过 10000 字时，AI 必须自动执行精简；超过 7000 字时，AI 应当主动执行精简。
2. 规则保护：除用户下达明确的修改指令外，AI 绝对禁止擅自修改本文件中的核心规则。
3. 每次封版必须同步更新「当前版本」与「下一步计划」，并补 docs/prompts 快照与 docs/dev-log.md。

一、核心规范
- 极简输出：后台直接写文件，聊天框禁贴全量代码，说明改了哪个文件/函数与测试方式；验收类可放宽到 400 字。
- 自主审查：改完必须自测（py_compile / node --check / 接口与 DOM 断言回归），汇报附自审结论。
- 安全红线：自动化测试不得盲删真实数据，测试数据用唯一备注定位并在结束后清理。
- 交互规范：全站禁用 alert()，统一 Toast；弹窗 Enter 提交、Esc 关闭；全中文文案；表格防挤压。
- 文档纪律：dev-log 每版 3-5 句概括技术路径；docs/prompts/NN-xxx.md 只写需求背景/核心 Prompt/方案简述/踩坑结论；测试脚本、截图一律放 D:\Project\temp，并在 temp/index.md 建索引，禁止写进项目目录。

二、当前环境 / 技术栈
- 系统 Windows；Python venv 在项目内：.\venv\Scripts\python.exe app.py。
- Flask + sqlite3（records.db）+ 原生 JS/CSS + Bootstrap 5 + ECharts + PyJWT + pandas/openpyxl。
- 前端：templates/index.html、static/script.js（主逻辑）、static/charts-v013.js（图表看板）、static/auth-v012.js（JWT fetch 封装 + 登录遮罩 + 品牌图标主题 + 头像 Lightbox）、static/style.css；后台 /admin 由 static/access-guard.js 保护。
- 当前版本：v0.14.0-TST（商业级质感收尾版：SW `ai-accounting-v0.14.0-tst5`、全站 `?v=0.14.0-tst5`；核心修复为「总资产纳入投资持仓市值」与「快捷修改账户余额（可按差额生成带备注的平账流水）」；交互上手动记账与 AI 气泡彻底解绑、近 7 天账单实时刷新并支持折叠；UI 完成侧边栏纯图标极简重构、多页面双栏独立滚动、全局纯蓝按钮磨砂化、卡片按钮贴底、图标实时预览；后台三个 AI Tab 合并为「AI 大脑管理」；演示数据 326 条账单 + 3 个持仓）。
- 历史标签：v0.11.4-DEV ~ v0.11.8-DEV、v0.12-DEV、v0.12.1 ~ v0.12.5-DEV、v0.13.1 ~ v0.13.9-DEV、v0.14.0-TST。
- 已知坑：**Flask 用 `--no-reload` 启动时 Jinja 模板会被缓存，改完 templates/*.html 必须重启进程**（否则 CDP 测试拿到旧 DOM）；东财 search-api 必须保持 ≥1 秒请求间隔（进程级锁），否则 IP 会被封；邮箱验证码只存哈希、明文仅存于发信瞬间，排障时不要指望从库里捞码；.env 换 Key 必须彻底结束旧 Flask 进程再启动；UI 重构后必须同步改旧测试断言；CSS 同权重靠文件末尾覆盖；图标格子不要塞进父级 flex 行，否则被压缩变形；SW 静态资源是 stale-while-revalidate，发版后第一次刷新必然先命中旧缓存——必须同步 bump 模板 `?v=` 与 `CACHE_NAME` 才能一次刷新生效；headless Chrome 默认视口 800×600，侧边栏在该宽度会折叠隐藏昵称，浏览器验收前必须 `Emulation.setDeviceMetricsOverride` 到桌面宽度；后台 `/api/admin/users` 是双层鉴权（`_access_guard` 要访问密码、`_identity_guard` 要 JWT），单测必须同时带 Bearer；移动端覆盖 FAB 位置必须写 `.fab, .fab.fab-menu`（基础样式与 ≤575.98px 断点都是两段类名、还有一条 `bottom:18px`，单写 `.fab` 特异性不足实测不生效）；headless Chrome 的 `Emulation.setEmulatedMedia` 模拟 `display-mode` 不生效（`matchMedia` 恒 false），standalone 相关规则只能断言下发的 CSS 文本、真机行为需用户安装后验证；分类网格点击后不可重建 DOM（只改 .is-active），否则 event.target 被摘出文档，外部点击监听会误收浮层；`data-*` 取出的 id 是字符串而接口 id 是数字，`findRecordById` 必须 `String()` 比对否则明细卡片按钮静默失效；移动端 16px 防缩放必须带 `!important`，否则被 `.form-control` 的 14px 盖掉；**仓库里有两份 SW / manifest（根目录 + static），v0.14.0 已把 `/service-worker.js` 与 `/manifest.json` 路由统一指向 `static/`，根目录副本不再对外服务——改根目录那份等于没改，发版仍要两份同步以防误改**；Bootstrap Tooltip 初始化会把 `title` 搬进 `data-bs-original-title` 并缓存进 `_config.title`，之后改 `title` 属性浮层不会更新，必须三处同步且绝不 `dispose()` 重建；`hidden` 属性永远打不过 `display:flex !important`，折叠类需求一律补 `[hidden]{display:none!important}` 并断言计算样式而不只断言属性；手动记账已与 AI 气泡解绑（`showRecordSuccessBubble` 保留但只给 AI 用），任何手动入口都不要再接它；`.panel + .panel{margin-top:16px}` 是跨页面布局地雷，新页面用 `gap` 不要再依赖它。

三、核心数据模型
- users：id, email UNIQUE, password_hash, phone, nickname, avatar, created_at。管理员 id=1（[管理员邮箱已脱敏] / [默认口令已脱敏]），1-9 预留，普通注册从 10 起。
- accounts：(user_id, name) 复合主键，balance 为资金唯一真相，group_name 分组。
- records：id, user_id, amount, type(expense/income/transfer), account, to_account, fee, category_id, formula, date, deleted_at 软删除, 报销字段(is_reimbursable/reimbursed_amount/...), image_path。
- categories：id, user_id, name, parent_id（二级分类）。
- debts：id, user_id, account, amount, repaid（v0.13.8 新增，已还本金）, due_date, interest, image_path, status 等；剩余 = amount - repaid。
- contacts：id, user_id, name 等；ai_memory：id, user_id, original_text, raw_category, corrected_category, keywords, note, created_at（Few-Shot 记忆库）。
- ai_correction_log / ai_feedback：纠错审计与反馈；notifications：status(draft/published) + visible_at；import_history、login_attempts、icons、user_icon_settings、admin_config、access_sessions。
- 规则：任何账单增删改都必须联动 accounts.balance，禁止只改 records。

四、核心 API 速查
- 账单/账户/统计：/api/records（增删改查、trash/restore/purge、batch/delete、batch/category、duplicate-check）、/api/accounts（改名/合并/批量删）、/api/categories、/api/statistics、/api/search。
- AI：/api/records/ai、/api/records/ai/stream（SSE）、/api/records/ai/image；均支持 previous_record_id 覆盖更新、force 跳过防重，返回 confidence/auto_corrected；/api/records/<id>/ai-revise（自然语言或结构化全量覆盖）、/api/records/<id>/correction、/api/ai-memory、/api/ai-correction-log、/api/feedback。
- 鉴权：/api/auth/register、login、me、profile、avatar（PUT 路径 / avatar/upload 直传文件）、change-password、send-code（v0.13.4 落库防刷）、verify-code、reset-password；sms-login 返回 501 占位。JWT HS256 7 天，未登录统一 401 auth_required。
- 投资：/api/invest/*（12 条，均 login_required + user_id 隔离）；`/api/invest/search` 由后端代理东财 search-api，返回 `{code,name,category,type}` 并兼容旧 `{ticker,asset_type,price,source}`。
- 其它：/api/import/parse|confirm、/api/debts/<id>/repay（v0.13.8 部分/全额还款，扣账户+生成流水）、/api/records/<id>/reimburse（v0.13.8 报销入账+生成收入流水）、/api/debts/<id>/settle、/api/icons、/api/user-icons、/api/notifications（draft/publish/visible_at）、/api/access/*（后台密码）、/api/version（v0.14.0 起钉死 `APP_VERSION_FALLBACK`，不再读 Git Tag——本地旧 Tag 曾把版本号串成 v0.13.9；仍可用 `APP_VERSION` 环境变量覆盖）、/api/accounts/&lt;name&gt;/adjust_balance（v0.14.0 快捷改余额，按差额生成平账流水）。

五、下一步计划
- **v0.14.0-TST 已完成并封版（代码冻结）**：系统已具备商业级质感与严密的财务逻辑——资产口径把投资持仓市值算进总资产、账户余额可在三处入口一键改平并留痕、手动记账与 AI 对话完全解耦、近 7 天账单实时刷新且可折叠、全套 UI（磨砂、骨架屏、粒子登录页、侧栏极简、双栏独立滚动、卡片贴底）达到可对外演示的水准；演示数据（`test@test.com / [演示口令已脱敏]`，未删除账单 330 条 = 326 条基线 + 4 条验收期平账/转账流水，3 个持仓 + 2 个投资账户）已就绪，可直接用于比赛演示。
- **下一步：代码已冻结，全面转入比赛演示视频录制与交付材料整理。** 除演示中暴露的阻断级 Bug 外不再改动功能；新增需求一律记录到 v0.15 待办，等比赛结束后再开分支处理。
- 交付材料清单：演示视频（按 `docs/video-script.md` 分镜）、技术报告（`docs/tech-report.md`）、项目说明与架构图（`docs/tech-report.md` 第 1 章 + `docs/archive/design-v0133.md` 与归档目录内三张 mermaid）、开发日志与踩坑集（`docs/dev-log.md`、`docs/bugs-and-solutions/`）、Prompt 复盘（`docs/prompts/README.md`）、可运行包与演示账号说明。
- v0.13.1 ~ v0.13.6 已完成（细节见 dev-log）：语义色令牌与 `window.__chartColors()` 单一色源（切主题免刷新）、分类按 `user_id` 隔离与停用/合并；投资账户体系（`accounts.type` + 三张新表 + 12 条 `/api/invest/*` + Mock 行情）与投资看板双视图、AI `invest_buy` 意图；邮箱验证码后端与东财 search-api 接入（≥1 秒间隔、降级 Mock）；注册校验与登录解耦 + 登录卡片 Glassmorphism；全局品牌化「智汇账」+ 头像 Lightbox + 品牌图标 8 选 1。
- v0.13.7 ~ v0.13.9 已完成（细节见 dev-log）：数据越权修复（报销统计补 `user_id`/`deleted_at`）、侧边栏三段式、后台用户管理 UID、PWA 图标与全屏化；移动端 `@media (max-width:768px)` 全局重构 + 真机安全区/16px 防缩放 + 借贷报销闭环（还款扣账户、报销生成入账流水、已结清置灰，自测 `test_v0138_logic.py` 27/27、`cdp_v0138_test.mjs` 35/35）；登录页 Canvas 粒子背景、骨架屏、Toast 磨砂 + Kaomoji 重构、分类字典重写与「213」脏分类清洗、帮助与反馈 Tab 隔离 + 10 秒防刷。
- v0.13.7 终极补丁遗留：真机安装效果（无地址栏、竖屏锁定、图标）需用户在 Chrome 清除站点数据后「添加到主屏幕」确认；iOS Safari 与 Android Chrome 的 PWA 细节存在差异。
- v0.13.4 遗留：`.env` 缺 `MAIL_*`，真实投递验收未做（补齐后跑 `D:\Project\temp\test_v0134_send_real.py`）；`ai_service._invest_lookup` 仍用本地字典（避免流式多等 5 秒，可后续按需切东财）。
- 已知遗留（v0.15 待办）：
  - **投资**：`parsed.platform` 被忽略，说「用天天基金买 1000」会落到「默认」平台（方案 B：命中就用、没命中回落默认；**不要改成自动建**——该字段源头是 LLM，会造出删不掉的脏分组）；`holdings.record_id` 恒 NULL 是死列，将来做「删账目联动清仓」或 CSV 回溯前必须先决定删列还是真正写入；`GET /api/invest/dca-plans` 列表路由未做（数据层已就绪，看板里 holdings 已带 `dca_plans`）；AI 确认卡不支持换标的（后端已返 `candidates`）；加仓后不自动展开对应平台；弹窗内无行内错误红字
  - **既有**：季度翻页真正翻错的是 7-31 / 12-31（已用 365 天枚举证明修复完整）；`max == min` 时 markLine 两标签重叠；`entityIconHtml()` 对 1×1 退化图仍显示色块；Bootstrap 徽标色与 `--color-expense` 的极轻微差异
- v0.15 方向：1) 设计文档 `docs/archive/design-v0131.md` 中未实现的 T02 六套主题、T03 图标库扩到 40+、T04 月度结账单卡、C3 周期账单模板（只提醒+手动生成）；2) 报销进阶（部分报销进度、按报销人筛选、报销导出）；3) 数据安全（SQLite 一键备份/恢复，CSV 增加报销与截图字段）；4) 云存档（static/uploads 截图上云）；5) 移动端与可访问性细节。
- 封版流程：语法检查 → 接口回归 → 更新 dev-log/prompts → commit + tag → 验证 `/api/version`。
- 备注：本机暂连不上 GitHub，恢复后 push main 与全部历史 tag。
