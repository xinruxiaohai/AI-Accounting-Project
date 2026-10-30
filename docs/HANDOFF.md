AI 记账管家 项目动态交接文档

【最高强制规则】

本文档仅保留当前最新状态与下一步计划，严禁堆积流水账。

每次完成“大版本迭代”（已打 Tag 封版），AI 必须自动重写第一板块（当前状态）与第六板块（下一步计划）。

每次大版本封版，必须同步补全 docs/prompts/ 下的 Prompt 快照，并严格按照第三板块的规范更新 docs/dev-log.md。

一、当前项目状态
当前版本：v0.11.8-DEV（账户余额卡品牌渐变 + 全局搜索浮窗分批渲染与点击直达详情）
当前进度：v0.10 已完成五组重构。后端 AI 升级为意图路由 + 代买/报销场景（抽出 is_reimbursable 与 contact_name，报销自动关联联系人并记入待报销），新增 /api/records/ai/stream SSE 分阶段推送解析进度，新增 ai_feedback 表与 /api/feedback（错误文本 / AI 结果 / 用户纠正），/admin 增加「AI 反馈与记忆」Tab。全站骨架锁 100vh 内部各自滚动，manifest 改为 window-controls-overlay 并用 env(titlebar-area-*) 让 topbar 避开窗口控制按钮；首页卡片缩小 20%，资产页左 4 成（净资产卡 + 四统计卡）右 6 成纯流水；新增「账单」页：左侧年月树带当月收支，右侧关键词 / 类型 / 账户 / 日期区间 / 金额区间筛选与八列大表格。交互层：金额语义色全局生效（仅收支红绿，借贷转账深色），侧栏点击后强制收起残留 Tooltip，账单流支持年 / 月 / 日三级折叠（localStorage 记忆），资产统计四卡点击弹明细；悬浮球钢笔径向四分支（普通记账 / AI 文本快记 / AI 截图识别占位 / 帮助），3 秒无操作收回，帮助弹窗含快捷键与功能速览。AI 输入框前置正则极速拦截（如「午饭30」无账户自动补「现金」直接入库），其余指令立即关窗并在右下角弹出可并发气泡，走 SSE 打字机与思考动效，3 秒后淡出、悬停或失焦暂停倒计时，成功气泡点击直达详情。v0.10.1 补丁针对验收反馈修复六处细节：账单页与管理后台的日期字段改成「中文占位文本框 + 全尺寸透明原生选择器覆盖层」，选择后立即回显并同步筛选状态；资产页左右两栏改为 align-items:stretch，右侧流水面板与空态撑满高度；首页图表容器补 min-height:240px，画布 210px 不再被压缩截断；悬浮球四向展开全部改为向左/向上位移，任何窗口宽度都不越出视口；侧栏导航 Tooltip 改为 hover 触发并在点击时 hide()+blur()，不再残留；账户名补 display:block + ellipsis，金额 flex 固定不挤压。v0.10.2 针对真实浏览器验收再修三处：资产页外层改成 flex 高度链（#page-assets.active 撑满 100%，.assets-left / .assets-right 各自 height:100% + overflow-y:auto，右栏流水与空态 flex 撑满），彻底消除右栏下方的灰色留白；首页图表容器强制 280px 画布高度（.chart-box min-height 310px），resize 在 DOM 落定后 100ms 再重绘；悬浮球改用标准圆弧算法（半径 118 的四分之一圆弧，相邻图标中心距 61px），任何窗口宽度下图标都不再重叠也不出视口；同时修掉首页两栏「假独立滚动」——栏内卡片不再被 flex 压缩（日历被日明细遮挡的根因），近 7 天等卡片内部滚动全部移除，滚动统一交给中栏 / 右栏容器；另把首页「本月预算」卡重写为左圆环（固定 96px、垂直居中）+ 右三行（标题/改预算、已花/预算、日均/剩余日均额度 + 贴底长条进度）的紧凑两栏结构。资产页左栏再拆高度链：`.assets-left` 锁 100% 高、净资产卡/统计卡 `flex-shrink:0`，「我的账户」面板 `flex:1 + min-height:0`，内部 `.account-groups` 才是 `overflow-y:auto` 的滚动层。v0.11 实装 AI 截图记账闭环。ai_service 新增 parse_image：用 glm-4v-flash 视觉模型，把图片以 Base64 dataURL 放进多模态 content 数组，配一份和文本版同约束的 VISION_PROMPT（金额只取实付、分类按商户、时间按小票，非账单返回 unknown），输出严格 JSON 后再复用文本版归一化。后端新增 POST /api/records/ai/image（Base64 → 视觉解析 → 复用意图分流入库 → 压缩图落盘 static/uploads/ 并把路径写进 records.image_path），新增 GET /api/records/images 相册列表、DELETE /api/records/<id>/image 图片双删（清库字段 + 删本地文件，账目保留）。前端悬浮球【截图】真正唤起文件选择，Canvas 把最长边压到 800px 的 JPEG 再上传，全程复用非阻塞气泡：正在识别截图 → 截图记账成功可点击进详情；账单详情新增「截图凭证」缩略图与查看原图预览弹窗；「我的」页新增相册卡片，网格相册弹窗支持点图进对应账单、删除图片（本地 + 数据库双删）。悬浮球交互重写：点钢笔或点功能后保持展开不设时限，只有鼠标离开悬浮球及全部子图标范围才开始 3 秒倒计时、移回即取消；子图标文字提示统一固定在图标左侧竖排居中，不再被主球或屏幕边缘遮挡。v0.11.1 完成四块应用化改造。PWA manifest 使用 window-controls-overlay，topbar 通过 env(titlebar-area-*) 让出右侧窗口控制按钮安全区。AI 快记弹窗新增【上传图片】入口：本地 FileReader 生成缩略图预览与「文件名 · 大小 · 发送时自动压到 800px」说明，点发送直接走 /api/records/ai/image 并复用全局气泡；有图时忽略文本框，无图时仍走文本解析。通知体系升级为「AI 起草 + 人工审核」：ai_service.generate_notification 生成标题与序号正文，草稿以 status=draft 入库，用户端只返回 published，/admin 新增 AI 起草输入框与「待审核草稿」「已发布通知」两栏，草稿可发布/编辑/删除。新增全站访问密码：admin_config 存密码哈希与免密时长（10 分钟~1 天可调），access_sessions 存一次性会话；static/access-guard.js 先于主脚本启动，未设密码不拦，设密后整站遮罩并锁滚动，验证通过把 token 与时间存 localStorage，超时或任何 401 立刻重新上锁并保留已填内容；/admin 设置齿轮 Modal 管理密码增删与免密时长，修改/删除密码或改超时距上次验证超过 5 分钟必须弹框重新输入当前密码；首次设密后当前页自动刷新交给遮罩接管。v0.11.2 三项补丁：/admin 顶栏设置按钮从裸 SVG 改成完整的内联齿轮按钮（40×40、11px 圆角、跟随 --surface/--text-main 变量、hover 转 45° 变品牌蓝、深色主题自动适配）；ai_service.generate_notification 会先读 docs/dev-log.md 最新版本记录拼进 Prompt，强制「绝对依据」禁止编造日志之外的功能，并给 DEV_LOG_ENTRY_MAX_CHARS=3600 的截断保护；访问密码改为可回显的新存储格式（p1$ + urlsafe Base64，兼容 v0.11.1 的盐$SHA256 旧格式），密码列表默认只显示 ******，点【查看密码】必须当场输入任意一个当前密码独立二次验证（不受 5 分钟免密期影响，错密只回内联错误），验证通过后该行显示明文并标 is-plain；旧哈希密码无法回显，需删除后重新添加。v0.11.3 三项补丁。鉴权作用域收回 /admin：access-guard.js 只在 /admin 路由建遮罩与超时上锁，用户端首页/账单/资产/我的全部免密；凭证从 localStorage 换 sessionStorage，关标签或浏览器必须重验；查看密码、删除密码、改免密时长等危险操作的二次验证层统一 z-index 100000 !important（backdrop 99999），永远压在设置弹窗之上。后端改为「一切先草稿」：手动 POST /api/notifications 强制 status=draft，必须显式 PUT publish 才对外；@app.before_request 抽成 _needs_access()，/api/access/*、/api/upload 与通知写操作要会话，通知读、账单读、/api/version 公开。首页近 30 天趋势图升级为三线（红-支出、绿-收入、灰-结余），legend 与 tooltip 逐线输出；侧栏版本号去掉「· 开发中」。公告全自动：/api/notifications/draft 不再收主题，服务端用 detect_version() 取当前 tag、ai_service.dev_log_entry_for_version() 从 dev-log 精确抓该版本段落，Prompt 要求标题严格以「[版本号] 版本更新：」开头、纯文本无表情分点 3-5 条、只能基于真实日志；admin 起草区换成单个大按钮【一键起草当前版本更新公告】。v0.11.4 四模块。图表：首页趋势图 legend top:30、toolbox 收到 8/4、grid.top 60，收入/支出实线、结余 dashed 虚线并压 z:1 底层 + 半透明渐变 areaStyle，三线 opacity 0.8。AI 预处理：ai_service 新增 CATEGORY_MAPPING 同义词纠错（滴滴/打撤→交通、星巴克/奶茶→餐饮、淘宝→购物、房租/水电→居住等，归一化阶段强制改写），SYSTEM_PROMPT 字段扩到 16 个并要求每次返回 confidence(0-100)，/api/records/ai 与 SSE 接 previous_record_id 注入「用户正在补充修改账单，请覆盖原数据」并走覆盖更新，解析前取最近 3 条 ai_memory 当 few-shot。前端：截图文件框改 multiple，for...of + await 串行压缩上传（严禁 Promise.all），每张独立气泡显示「识别中 i/N」，confidence<80 成功气泡变黄提示核对，气泡内嵌输入框可「改成微信」带账单 ID 调纠错接口，详情弹窗加【AI 纠错】按钮。防重：保存前查最近 10 分钟金额相同、商户/账户相似记录，命中弹自定义确认框（duplicate-check 预检 + 409 duplicate + force 重发三路已接）；新建 ai_memory 表存纠错记忆，/admin 新增「AI 纠错记忆」Tab 可查看/新增/删除。v0.11.5 三模块。AI 精准度：ai_service 把数据库真实账户/联系人清单注入 Prompt，要求保留用户具体子账户（微信零钱/支付宝余额）；新增 difflib 模糊匹配（阈值 0.8）与 ACCOUNT_ALIASES 别名表（威信/薇信/维信→微信、银行→银行卡等），在归一化阶段强制把账户/联系人换成库中真名，响应体新增 auto_corrected / auto_corrected_msg；解析前按用户这句话的关键词从 ai_memory 模糊匹配 Top 3 当 few-shot（database.search_ai_memories）。气泡多轮纠错：带 previous_record_id 时把原账单完整 JSON（含报销字段）交给 AI，要求未提及字段继承原值并返回完整 JSON；新增 POST /api/records/<id>/ai-revise 走全量 UPDATE，余额由 update_record 先撤旧账再落新账（微信→微信零钱、30→50 两个账户余额都正确回滚/扣除），并写 ai_correction_log 审计。前端气泡用灰色小字展示 auto_corrected_msg，气泡内输入框改调 /ai-revise 支持改金额/账户/分类；/admin 新增「AI 纠错与反馈中心」Tab，左栏 ai_memory 滚动可删、右栏近期纠错审计改前/改后字段对比。v0.11.6 三模块。账户体验：资产页账户行悬停出现编辑图标，内联改账户名与余额（PUT /api/accounts/<name>，后端同步改名到 records.account / to_account / debts.account），右栏流水顶部新增金色渐变的账户余额卡，选中账户即刷新。AI 纠错收尾：ai-revise 跨账户（微信→支付宝）走同一套全量 UPDATE，余额先撤旧账再落新账，双向回滚已实测通过；AI 识别出库里没有的账户时后端自动建户，响应带 is_new_account / new_account_name，气泡高亮提示并给「合并到已有账户」按钮（POST /api/accounts/merge，余额相加、账目迁移后删源账户）。批量与设置：账单页与资产页账户列表加「批量管理」，Ctrl 多选后底部批量栏支持批量删除（软删 + 余额回滚）、批量改分类、账户批量删除；「我的」页新增显示与主题设置（首页卡片显示/隐藏 localStorage 持久化、主题三态浅色/深色/跟随系统 + matchMedia 监听）；style.css 给 standalone / window-controls-overlay 模式加 .topbar padding-right 140px + padding-top 30px 的暴力兜底，service worker 缓存名升到 v0.11.6 强制换新。v0.11.7 三模块。AI 纠错弹窗从「只能改分类」重写成完整表单（金额 / 分类 / 账户 / 备注 / 日期），提交走 POST /api/records/<id>/ai-revise 的结构化分支：不经过自然语言模型，直接按完整字段全量 UPDATE，跨账户仍走 update_record 先撤旧账再落新账（余额回滚已实测）。批量管理实装 Ctrl 语义：账单页与资产页「批量管理」开启后，普通点击单选高亮、Ctrl/Command + 点击追加多选，Ctrl+A 全选当前列表、Esc 退出批量；底部批量栏复用 v0.11.6 的批量删除（软删 + 余额回滚）与批量改分类接口。设置抽离：「我的」页不再内嵌设置卡，改成【打开系统设置】按钮，弹出居中大号 Bootstrap Modal，统一管理主题三态（浅色/深色/跟随系统 + matchMedia 监听）与首页卡片显隐，保存后自动收起；顶栏齿轮也直接打开该弹窗。通知双时间：notifications 新增 visible_at（生效时间），publish_date 只做展示时间；/admin 表单在「发布时间」下面新增「定时发布时间」，发布时间留空自动用它兜底；POST/PUT 同时落两个字段；GET /api/notifications 严格按 status='published' AND visible_at <= 当前时间 过滤，生效时间设在明天的通知今天绝对不可见。v0.11.8 两模块。账户余额卡：renderAccountBalanceCard 按账户名归类（微信绿 / 支付宝蓝 / 银行卡红金 / 现金金 / 理财紫 / 未知蓝灰），在 #account-balance-card 上切换 is-card-wechat 等类名，CSS 各给一套渐变与投影，切换账户即时变色。全局搜索：新增 GET /api/search?q=&limit=（database.search_records，备注 / 分类 / 账户 / 转入账户 / 金额 LIKE，% 与 _ 已转义，上限 500 条），任意页面在顶栏搜索框输入即 300ms 防抖请求；搜索框正下方弹出 fixed 定位的 #search-popover，宽度取 getBoundingClientRect 与输入框严格一致、左对齐，z-index 4000 不被卡片遮挡，max-height 400px 独立滚动；结果每批 10 条首屏渲染，IntersectionObserver 观察底部 sentinel 滚动追加（无 IO 的浏览器退化成 scroll 事件），底部灰色小字显示「已加载 N / 共 M 条结果」；点结果立刻关闭浮窗并用 showRecordDetail 复用详情弹窗（从 openRecordDetail 里拆出来的整条记录入口，搜索结果不必在首页列表里）；Esc、点页面空白、窗口滚动/缩放重定位都已接。下一步进入 v0.12（报销进阶、报表与云存档）。
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

records: id, amount, type(expense/income/transfer), account, to_account, fee, category_id, formula, date, deleted_at(软删除预留), is_reimbursable, reimbursement_contact_id, reimbursed_amount, total_reimbursement, image_path(截图账单本地路径，v0.11 新增)。

accounts: name(PK), balance(唯一真相), group_name。

categories: id, name, parent_id (二级分类)。

ai_feedback: id, raw_text(用户原话), parsed(AI 解析 JSON), corrected(用户纠正 JSON), source, status(pending/processed), created_at。
ai_memory: id, original_text(用户原话), raw_category(AI 原分类), corrected_category(纠正后分类), note, created_at（v0.11.4 新增，AI 纠错 few-shot 记忆）。
ai_correction_log: id, record_id, source(bubble 气泡 / detail 详情 / ai 补改), original_text, before_json, after_json(改前/改后快照), confidence, auto_corrected_msg, created_at（v0.11.5 新增，admin 右栏纠错审计）。
notifications: id, title, content, date(发送日期文本), image_path(配图), created_at, status(draft 草稿 / published 已发布，v0.11.1 新增)。
admin_config: key, value（存访问密码与免密时长 timeout_minutes，v0.11.1 新增；v0.11.2 起密码以 p1$ + urlsafe Base64 存储可回显，旧盐$SHA256 格式仍可校验但不可回显）。
access_sessions: token, created_at, label（访问会话记录，用于免密期与 5 分钟重验证，v0.11.1 新增）。

五、核心后端 API 速查
/api/records (GET/POST/PUT/DELETE)
/api/accounts (GET/POST/PUT/DELETE)
/api/categories (GET/POST/PUT/DELETE)
/api/statistics (GET)
/api/notifications (GET/POST/PUT/DELETE；GET 默认只返回 published，管理端可带 ?include=drafts)
POST /api/notifications/draft AI 起草通知草稿（status=draft）；PUT /api/notifications/<id>/publish 发布草稿。
/api/access/config (GET) 是否受保护、密码数量、免密时长；/api/access/verify (POST) 输入密码换 token。
/api/access/passwords (POST) 新增密码；/api/access/passwords/<index> (DELETE) 删除密码；/api/access/timeout (PUT) 调整免密时长（后两者超过 5 分钟需重新验证）；POST /api/access/passwords/reveal 查看指定密码明文（必须 body.password 当场验证，不受 5 分钟免密期影响）。
/api/upload (POST)
/api/records/ai (POST) AI 意图分流：record / debt / add_contact / unknown（兼容旧调用）。
/api/records/ai/stream (POST) SSE 流式解析：thinking → extracting_amount → resolving_category → saving → done / unknown / error。
/api/feedback (POST/GET) 与 PUT /api/feedback/<id> AI 反馈记忆：记录原始文本、解析结果、用户纠正，状态 pending / processed。
PUT /api/records/<id>/reimbursement 报销开关（只改报销字段，不动余额与统计）。
POST /api/records/ai/image 截图记账（Base64 图片 → glm-4v-flash 视觉解析 → 复用意图分流入库，图片落盘并写 image_path）。
GET /api/records/images 相册列表（所有带截图的账目，仅未删除）。DELETE /api/records/<id>/image 删除图片（清库字段 + 删本地文件，账目保留）。
GET /api/records/trash 回收站列表；PUT /api/records/<id>/restore 恢复；DELETE /api/records/<id>/purge 彻底删除（DELETE /api/records/<id> 现为软删除，余额同步回滚）。
GET /api/records/duplicate-check 防重预检（?amount=&account=&note=&exclude_id=，返回 duplicate/candidate）。
POST /api/records/<id>/correction 详情/气泡纠错：改分类 + 写一条 ai_memory（body corrected_category 必填）。
GET/POST /api/ai-memory 纠错记忆列表与新增；DELETE /api/ai-memory/<id> 删除。
/api/records/ai 与 /api/records/ai/stream 新增 previous_record_id 覆盖更新、force 跳过防重，返回体带 confidence。
POST /api/records/<id>/ai-revise 气泡多轮自然语言纠错：原账单完整 JSON 注入 Prompt → 全量 UPDATE，余额自动回滚/重算。
POST /api/records/<id>/ai-revise 也支持结构化分支（v0.11.7）：body 直接给 amount / category / account / note / date，跳过 AI 走全量覆盖，详情弹窗的完整表单走这里。
GET /api/search?q=关键词&limit=200 全局搜索（v0.11.8）：备注 / 分类 / 账户 / 转入账户 / 金额模糊匹配，返回 {items,total}，前端搜索浮窗按 10 条一批渲染。
通知接口 v0.11.7 带双时间：POST/PUT 接 publish_date（展示时间）与 visible_at（生效时间），发布时间留空用生效时间兜底；GET /api/notifications 只返回已到生效时间的已发布通知。
GET /api/ai-correction-log 纠错审计日志列表（?limit=N，新的在前）。
PUT /api/accounts/<name> 支持 new_name 账户改名（同步 records.account / to_account / debts.account）；POST /api/accounts/merge 把自动建出的账户合并进已有账户（余额相加、账目迁移）。
POST /api/accounts/batch/delete 账户批量删除；POST /api/records/batch/delete 账单批量删除（软删 + 余额回滚）；PUT /api/records/batch/category 账单批量改分类。
v0.11.6 起 AI 记账响应会带 is_new_account / new_account_name（AI 识别出的账户库里不存在时后端自动建户）。
v0.11.5 起 /api/records/ai、/api/records/ai/stream、/api/records/ai/image 都会向 ai_service 传真实账户/联系人列表与关键词命中的 ai_memory，并在响应体带 auto_corrected / auto_corrected_msg。

六、下一步行动计划
当前目标：v0.11.8 已完成（余额卡品牌渐变、全局搜索浮窗与点击直达详情），进入 v0.12 功能深化。
执行步骤：
1. 报销进阶：部分报销进度、按报销人筛选账单、报销记录导出；反馈数据用于纠正 Prompt。
2. 数据安全：一键备份 / 恢复（SQLite 导出导入），导出 CSV 增加报销与截图字段。
3. 报表页：月度/年度趋势与分类占比图表，替代纯文字统计。
4. 云存档：把 static/uploads 的截图上传云端（代码注释已预留接口位置）。
5. 移动端细节与可访问性（焦点顺序、对比度、触控热区）。
6. 封版后 py_compile / node --check 加端到端自测，更新 dev-log 与 prompts；本机暂连不上 GitHub，网络恢复后 push main 与 v0.08.1-DEV / v0.09-DEV / v0.09.1-DEV / v0.09.2-DEV / v0.10-DEV / v0.10.1-DEV / v0.10.2-DEV / v0.11-DEV / v0.11.1-DEV / v0.11.2-DEV / v0.11.3-DEV / v0.11.4-DEV / v0.11.5-DEV / v0.11.6-DEV / v0.11.7-DEV / v0.11.8-DEV 标签。
备注：.env 换 Key 后必须彻底结束旧 Flask 进程再启动，否则旧进程仍持有旧密钥返回 401。
