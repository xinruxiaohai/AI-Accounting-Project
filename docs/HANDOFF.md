智汇账 项目交接文档

【最高红线规则 · 未经用户明确指令禁止修改本段】

1. 字数控制：本文件内容超过 10000 字时，AI 必须自动执行精简；超过 7000 字时，AI 应当主动执行精简。
2. 规则保护：除用户下达明确的修改指令外，AI 绝对禁止擅自修改本文件中的核心规则。
3. 每次封版必须同步更新「当前版本」与「下一步计划」，并补 docs/prompts 快照与 docs/dev-log.md。

一、核心规则

- 极简输出：后台直接写文件，聊天框禁贴全量代码，说明改了哪个文件/函数与测试方式；验收类可放宽到 400 字。
- 自主审查：改完必须自测（py_compile / node --check / 接口与 DOM 断言回归），汇报附自审结论。
- 安全红线：自动化测试不得盲删真实数据，测试数据用唯一备注定位并在结束后清理。
- 交互规范：全站禁用 alert()，统一 Toast；弹窗 Enter 提交、Esc 关闭；全中文文案；表格防挤压。
- 文档纪律：dev-log 每版 3-5 句概括技术路径；docs/prompts/NN-xxx.md 只写需求背景/核心 Prompt/方案简述/踩坑结论；测试脚本、截图一律放 D:\Project\temp，D:\Project\AI-Accounting-Project暂存数据不准放到该目录下，并在 temp/index.md 建索引，禁止写进项目目录。

二、并行 Agent 协作声明（2026-11-17 · 多智能体并行期必读）

> 本段为多智能体并行开发期的协作约定。给任一 agent 下任务时，提示词里必须加一句
> 「开工前先读本文件『二、并行 Agent 协作声明』段」，防止互相覆盖。任务全部完成后可删除本段。

当前并行作业分工（含已完成项，供后来者避让）：

| Agent | 职责 | 允许改的文件（白名单） | 状态 |
|---|---|---|---|
| A | 移动端交互重构（账户 → 全屏二级页、移动端导航栈、二级页全屏化） | templates/index.html（仅加 link/script）、新增 static/mobile-stack-v0152.css、新增 static/mobile-stack-v0152.js；**不可碰 static/style.css（G 二轮占用）与 script.js 图标区 8191-8285** | 已完成（commit `587e65e`，3 文件 +1033 行；32/32 断言：`.assets-right` 全屏 `z-index:1052`、`elementFromPoint` 不穿透 tabbar、`history` 连点只 +1、`/api/records` 只发 1 次、桌面 731px 右栏零回归、md5 不变） |
| B | AI 文本识别准确率 | ai_service.py 的 SYSTEM_PROMPT + 文本归一化区 | 已完成（commit `7c5e4f5`；账户/联系人 83.3%→**100%**、文本 502=0、多轮加 `is_revision` 不猜数；confidence 90-100 占比 82.8% 未达 ≤60%，判为指标口径问题挂起） |
| C | 原生弹窗审计 | 只读（0 命中，无改动） | 已完成 |
| D | AI 图像识别准确率 + 图片先识别后压缩 + **重复截图去重** | ai_service.py 的 VISION_PROMPT/parse_image、app.py 图片路由(约1752-1933)、static/script.js 上传入口、database.py 的 records 补列与查重区 | 一段已完成（commit `48a0e5e`：31 张真实样本 字段级 94.5% / 类型 100% / 502=0；去重 9/9 断言，含 `¥11.93 vs ¥23.10 dHash=0 不判重` 反证；`records.image_hash`+`trade_no` 幂等补列）；二段（分类闭集 + trade_no + 真浏览器重复上传）进行中 |
| E | 投资 K 线（日/周/月 + 30min 同步） | app.py 投资路由区(约3138+)、static/invest-v0133.js、templates/index.html 的 K 线 Modal、新增 K 线样式 | 已完成（v0.15） |
| F | 账户与分类图标体系（真品牌 logo + 60 分类图标）；五十五款**应用图标不动**，六主题/可访问性顺带微调 | static/script.js **仅图标区(约8090-8287)**、新增 static/icons/entity/**、新增 static/entity-icons-v0152.css、static/v0151-theme.css、templates/index.html（仅加一行 link） | 已完成（commit `2d34144`，79 文件；账户 15 key / 分类 60 key；遗留：`entity/account/unionpay.svg` 非等比缩放变形、资产页账户行缺视觉截图） |
| G | 业务增强（月度结账单卡 / 周期账单模板 / 报销进阶）+ **二轮：资产页布局修复** | static/biz-v0151.js、static/biz-v0151.css、app.py `/api/biz/*`、templates/index.html 的 `#biz-v0151-root`、static/style.css **仅末尾追加** | 初版完成（v0.15 补修 HTML 注释失闭 / teardown 二次入账，接口 30/30、CDP 25/25）；**二轮进行中**：修复 `#biz-v0151-root` 固定 880px 把 `.assets-split` 挤成 0（1440×900 下「我的账户」整块不可见），详见 docs/prompts 与 48/50 号补充 |

协作铁律（违反即停）：
1. 只改自己白名单内的文件，绝不格式化/重排整个文件，只动必要的行；跨白名单的需求先告诉用户协调。
2. 共用文件串行改：`ai_service.py` 由 B、D 共用——B 改完 D 再动；`app.py` 由 D、E 共用；`static/script.js` 由 A、D、F 共用——**F 只许改图标区（约 8090-8240 行），A 原则上不碰 script.js（用新增 mobile-stack-v0152.js wrap 既有全局函数）**；任何人对共用文件只许定点 Edit，禁止整文件写回，改前记 `git diff --stat`，改后 grep 双向确认（自己的新符号在、别人的标志串如 `_compress_ai_image` / `entityIconHtml` 也在）。
3. 谁都不许自行改版本号（APP_VERSION_FALLBACK / ?v= / CACHE_NAME / manifest），统一由用户最后 bump 发版；当前基线 **v0.15**。
4. 测试一律用 D:\Project\temp 下各自独立子目录，隔离库 + teardown + 主库 records.db 零污染（md5/mtime 前后对比）；禁 /register，只用 test@test.com(本地uid93) 与 temp_cdp_v0140@example.com(uid90)，JWT sub 字符串。
5. git 提交只 `git add` 自己改的文件，绝不 `git add -A`，绝不碰 docs/HANDOFF.md 及其他 agent 的产物。

三、当前环境 / 技术栈

- 系统 Windows；Python venv 在项目内：.\venv\Scripts\python.exe app.py。
- Flask + sqlite3（records.db）+ 原生 JS/CSS + Bootstrap 5 + ECharts + PyJWT + pandas/openpyxl。
- 前端：templates/index.html、static/script.js（主逻辑）、static/charts-v013.js（图表看板）、static/auth-v012.js（JWT fetch 封装 + 登录遮罩 + 品牌图标主题 + 头像 Lightbox）、static/style.css；后台 /admin 由 static/access-guard.js 保护。
- 当前版本：**v0.15.2**（多智能体并行收尾版，2026-11-17 夜）：SW `ai-accounting-v0.15.2`、全站 40 处 `?v=0.15.2`、`APP_VERSION_FALLBACK=v0.15.2`；含 ① 移动端账户详情全屏二级页 + `history.back()` 单一返回入口（A `587e65e`）② AI 文本识别账户/联系人 100%、502=0（B `7c5e4f5`）③ AI 图像 31 张真实样本 94.5% / 类型 100% / 分类闭集 100% + 交易单号去重（D `48a0e5e`+`12467c0`）④ 账户 15 + 分类 60 真品牌图标（F `2d34144`）⑤ 资产页桌面布局挤压修复 + 移动端账户行断行（G `1184858`）⑥ 月度结账单卡/周期模板/报销进阶（G 初版）。上一个封版：v0.15（`47b50ec`，`{"version":"v0.15"}` 核验通过）。
- 历史标签：v0.11.4-DEV ~ v0.11.8-DEV、v0.12-DEV、v0.12.1 ~ v0.12.5-DEV、v0.13.1 ~ v0.13.9-DEV、v0.14.0-TST、v0.14.1 ~ v0.14.3.4、v0.15。
- 已知坑：**Flask 用 `--no-reload` 启动时 Jinja 模板会被缓存，改完 templates/*.html 必须重启进程**（否则 CDP 测试拿到旧 DOM）；东财 search-api 必须保持 ≥1 秒请求间隔（进程级锁），否则 IP 会被封；邮箱验证码只存哈希、明文仅存于发信瞬间，排障时不要指望从库里捞码；.env 换 Key 必须彻底结束旧 Flask 进程再启动；UI 重构后必须同步改旧测试断言；CSS 同权重靠文件末尾覆盖；图标格子不要塞进父级 flex 行，否则被压缩变形；SW 静态资源是 stale-while-revalidate，发版后第一次刷新必然先命中旧缓存——必须同步 bump 模板 `?v=` 与 `CACHE_NAME` 才能一次刷新生效；headless Chrome 默认视口 800×600，侧边栏在该宽度会折叠隐藏昵称，浏览器验收前必须 `Emulation.setDeviceMetricsOverride` 到桌面宽度；后台 `/api/admin/users` 是双层鉴权（`_access_guard` 要访问密码、`_identity_guard` 要 JWT），单测必须同时带 Bearer；移动端覆盖 FAB 位置必须写 `.fab, .fab.fab-menu`（基础样式与 ≤575.98px 断点都是两段类名、还有一条 `bottom:18px`，单写 `.fab` 特异性不足实测不生效）；headless Chrome 的 `Emulation.setEmulatedMedia` 模拟 `display-mode` 不生效（`matchMedia` 恒 false），standalone 相关规则只能断言下发的 CSS 文本、真机行为需用户安装后验证；分类网格点击后不可重建 DOM（只改 .is-active），否则 event.target 被摘出文档，外部点击监听会误收浮层；`data-*` 取出的 id 是字符串而接口 id 是数字，`findRecordById` 必须 `String()` 比对否则明细卡片按钮静默失效；移动端 16px 防缩放必须带 `!important`，否则被 `.form-control` 的 14px 盖掉；**仓库里有两份 SW / manifest（根目录 + static），v0.14.0 已把 `/service-worker.js` 与 `/manifest.json` 路由统一指向 `static/`，根目录副本不再对外服务——改根目录那份等于没改，发版仍要两份同步以防误改**；Bootstrap Tooltip 初始化会把 `title` 搬进 `data-bs-original-title` 并缓存进 `_config.title`，之后改 `title` 属性浮层不会更新，必须三处同步且绝不 `dispose()` 重建；`hidden` 属性永远打不过 `display:flex !important`，折叠类需求一律补 `[hidden]{display:none!important}` 并断言计算样式而不只断言属性；手动记账已与 AI 气泡解绑（`showRecordSuccessBubble` 保留但只给 AI 用），任何手动入口都不要再接它；`.panel + .panel{margin-top:16px}` 是跨页面布局地雷，新页面用 `gap` 不要再依赖它；**任何 Python 脚本 import `app` / `database` 之前必须先设 `ZHZ_SQLITE_PATH`**——`init_db()` 在 import 期执行，不设变量会直接重写主库 `records.db`（2026-11-17 发生过一次：校验 token 时直接 `import app`，主库被幂等迁移重写，靠 `records.db.bak-*` 逐字恢复 + 还原 mtime 才回到 `211d49e67eaf25c9383b2d6d116e18a7`）；**`DELETE /api/records/<id>` 走 `soft_delete_record` 已经回滚余额，测试 teardown 再调 `adjust_balance` 会二次入账**（隔离库曾多出 111.0，2026-11-17 已修 teardown）；手动 patch `templates/index.html` 时锚点里带 `-->` 的注释块，替换串必须同样带回来，丢一个 `-->` 会把后面整段 section 吞进注释（biz-v0151 首轮「移动端面板不可见」的真因，断言 `<!--` 与 `-->` 计数相等可秒查）；**移动端做 fixed 全屏层有三个必踩坑**：① `#page-assets` 的 `.is-entering` 入场动画带 `transform`/`will-change`，会让它成为 `position:fixed` 的包含块，打开二级页前必须先移除，否则切页 300ms 内点账户全屏层直接错位；② 全局跑马灯 `#global-marquee` 的 `z-index:7000` 贴顶 24px，正文靠 `.app{padding-top}` 让位，但 fixed 层吃不到这个 padding，得用 `:root --zhz-stack-top-extra` 单独补（写在页节点上弹窗继承不到）；③ `.main`(`overflow:hidden`) 与 `#page-assets`(`overflow-y:auto`) 是双滚动容器，实测真正在滚的是 `.main`，返回时必须**两个都记录并恢复**。

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
- **v0.15 已封版上线（2026-11-17）**：四模块并行收尾——移动端 UI（头像入口/筛选折叠/暖色，CDP 15/15）、AI 文本识别（中文金额/502 兜底，66 case）、AI 图片识别（原图识别后压缩，4/10→10/10、链路 15/15）、投资 K 线（日/周/月 + 30min 同步，接口 38/38）；commit `47b50ec`，云端已部署核验 v0.15。复盘见 `docs/prompts/46-v015-multiagent-parallel.md` 与 dev-log。
- **v0.15.2 进行中（2026-11-17 夜）**：三条线并行，全部禁止自行 bump 版本，由协调方收口。
  - ✅ B 文本识别：commit `7c5e4f5`（账户/联系人 100%、502=0）。
  - ✅ F 图标体系：commit `2d34144`（账户 15 key + 分类 60 key，真品牌 logo）。
  - ✅ D 图像+去重（一段）：commit `48a0e5e`（31 张真实样本 94.5% / 类型 100% / 502=0；去重 9/9，反证「不能用图片相似度」）。
  - ⏳ D 二段：分类闭集 + `trade_no` 透传 + 真浏览器重复上传（`DOM.setFileInputFiles` 连选两次）。
  - ⏳ G 二轮：修复 `#biz-v0151-root` 固定 880px 导致 `.assets-split` 被挤成 0（1440×900 账户列表不可见）+ 移动端账户行断行 + 分类占比条配色。
  - ✅ A 移动端二级页：commit `587e65e`（`.assets-right` 全屏复用、`history.back()` 单一返回入口、桌面右栏零回归，32/32 断言）。
  - 收口动作（协调方）：统一 checkpoint（补 `biz-v0151.*` / `v0151-theme.css` / `static/icons/brand-*.svg` / `auth-v012.js` 存量 +49 行，GitHub 当前落后云端）→ bump **v0.15.2**（72 处版本串）→ 上云 → `curl /api/version` 核验 → 补 dev-log 与本文件「当前版本」。
- **下一步：续轮优化（已分派 A/B/F/G）**：B 修文本识别账户/联系人召回（33%）与 confidence 校准；E 补 K 线真机 CDP 截图；F 做六套主题 + 图标库 40+ + 可访问性；G 做月度结账单卡 + 周期账单模板 + 报销进阶。均由协调方统一发版，Agent 禁止自行 bump。
- （历史）**代码冻结转入演示录制**：除阻断级 Bug 外不再改动功能——此条为 v0.14.0-TST 时期的旧计划，v0.15 起已解除冻结。
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
