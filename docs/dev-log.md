开发日志

版本命名规则：
格式：v[主版本].[次版本].[修订号]-[阶段标识]
主版本：目前开发期为 0；比赛最终交卷时升级为 1。
次版本：代表核心功能大迭代，固定两位数递增（01, 02...），绝不重置倒退。
修订号：可选。代表在核心功能基础上的小补丁或细节优化（01, 02...）。
阶段标识（三个全大写字母）：
1. DEV（Development）：研发版。功能正在开发、联调中。
2. TST（Testing）：测试版。功能开发完毕，正在集中测试找 Bug。
3. REL（Release）：正式版。准备交卷或发布的最终稳定版本。

打标原则：
不按每次 Commit 打标，而是按“功能里程碑”打标。完成一个完整大功能后才打一次 Tag，并同步更新交接文档与日志。

————————————————————————

v0.01-DEV 2026-10-25 项目基建与基础 CRUD
对应提交：54b13fc → da15180

技术路径：
1. 用 winget 安装 Python 3.12.10。项目根目录建 venv，安装 Flask 3.1.3，依赖锁进 requirements.txt。
2. .gitignore 排除 venv/、__pycache__/、*.db、.env。环境、缓存、本地数据和密钥不进 Git。
3. database.py 使用内置 sqlite3。提供 get_conn()、init_db()、add_record()、list_records() 四个函数。
4. 启动时执行 CREATE TABLE IF NOT EXISTS records，建表幂等，重启不重复建表。
5. 前端使用 templates/index.html、static/style.css、static/script.js，原生 JS，不引框架。表单 POST 成功后清空输入并刷新列表。
6. 项目迁移到 D:\Project\AI-Accounting-Project，保留 .git 历史，重建 venv。

验证：
1. 杀进程再重启，GET /api/records 数据仍在，count 不变。
2. 零新增依赖，requirements.txt 只有 flask>=3.0。

————————————————————————

v0.02-DEV 2026-10-25 文档与版本规范
对应提交：docs: complete dev log, bug tracker, and prompt snapshots

技术路径：
1. 确立功能里程碑 Tag 策略。Tag 使用 git tag -a，带打标人和说明。
2. 补齐 docs/prompts/ 三份 Prompt 快照。固定记录目标、原始 Prompt、AI 方案、验证记录、踩坑结论。
3. 新增 docs/bugs-and-solutions.md，沉淀终端切盘、Git root-commit、Python 商店占位符三个问题。
4. docs/dev-log.md 改为按里程碑分段，作为版本演进时间线。

————————————————————————

v0.03-DEV 2026-10-25 基础账本与账户余额
对应提交：feat: support income/expense with account balances → docs: add v0.03 dev log and income-accounts prompt snapshot

技术路径：
1. records 用 ALTER TABLE ADD COLUMN 增加 account 和 type。带默认值加列，老数据不丢，迁移幂等。
2. 补齐 DELETE /api/records/<id> 和 PUT /api/records/<id>。PUT 采用整条覆盖语义，避免漏传字段被静默清空。
3. GET /api/records 显式 ORDER BY id DESC，把倒序写入接口契约。
4. 新建 accounts(name 主键, balance)，预置现金、微信、支付宝、银行卡。写账目时账户不存在会自动落库。
5. 增、改、删账目都在同一个 with conn: 事务里改记录和余额。修改时先撤销旧账，再记新账。
6. GET /api/statistics 返回总收入、总支出、总余额。总余额取 SUM(accounts.balance)，允许手工修正余额。
7. 余额口径选择如实记录历史，允许负余额。界面标红提示，不做静默归零。
8. 前端引入 Bootstrap 5.3.3 CDN。增加统计卡片、表格、账户管理弹窗、账户筛选和收支分段按钮。

决策：
1. 负余额不归零。现金 -773.23 如实展示。
2. 账户筛选只重拉列表，不动统计。

————————————————————————

v0.04-DEV 2026-10-26 PC 后台与分钟级时间
对应提交：feat: support minute-level record time → docs: add v0.04 dev log and prompt snapshot

技术路径：
1. 老数据只有 YYYY-MM-DD。normalize_date() 只在读时补 00:00，库中物理值不动。
2. 新数据写入 16 位 YYYY-MM-DD HH:MM。_parse_datetime() 接受多种常见格式，秒截断到分，空值取当前时间，非法格式返回 400。
3. 前端使用 <input type="datetime-local">，默认值由服务端注入，避免时区导致空白。
4. PC 后台改为左侧 220px 深色侧边栏加右侧主区。100vh 不出整页滚动条，只有 .content 滚动。
5. 顶栏固定 64px。记账改为居中 Bootstrap Modal。弹窗关闭时统一复位表单。
6. Bootstrap 改为本地引用，放在 static/vendor/，断网可运行。
7. script.js 重写为“拉数据、渲染、事件委托”三段式。refresh() 用 Promise.all 拉统计、账户、记录。
8. 编辑复用同一个弹窗，用 editingId 区分 POST 和 PUT。hidden.bs.modal 事件里复位状态。
9. 表格行和账户行动态生成，用事件委托绑定，重渲染不丢监听。
10. 日历不额外请求接口，直接复用列表数据按日期聚合。

验证：
1. Node 加 DOM 桩跑真实接口，34 条断言通过，alert 触发 0 次。
2. Edge headless 复核真实页面，统计卡片、表格、资产页、日历均正常。

————————————————————————

v0.05-DEV 2026-10-26 二级分类与资产页
对应提交：feat: support two-level categories and grouped accounts → docs: add v0.05 dev log and prompt snapshot

技术路径：
1. 新增 categories(id, name, parent_id) 自关联表。parent_id IS NULL 表示一级分类。
2. 唯一索引建在 COALESCE(parent_id, 0) 上，保证同一父级下不重名，一级分类也能正确去重。
3. records 增加可空 category_id，同时保留 category 文本列作为显示名。改名时两处同步，旧接口和导出不受影响。
4. accounts 增加 group_name，默认“资金账户”。账户从一维列表变成“大类到账户”两层。余额仍按单账户记，大类金额前端求和。
5. 升级只用 ALTER TABLE ADD COLUMN 和 CREATE TABLE IF NOT EXISTS，不重建表。DDL 和 DML 分两个 with conn:，避免 SQLite 隐式提交破坏事务预期。
6. 启动时 _backfill_category_ids() 三步回填：登记文本分类为一级分类，按一级同名回填，再按任意层级同名兜底。
7. 记账接口仍接受纯文本 category。未知分类自动建一级分类，旧页面不改也能继续记账。
8. 新增分类接口：GET/POST /api/categories、PUT/DELETE /api/categories/<id>。
9. 账户接口返回平铺列表和大类分组，支持新增、改余额或大类、删除。
10. 删除带保护。分类下有子分类或有账目在用、账户下还有账目时返回 409 和中文原因，不做级联删除。
11. GET /api/records 增加 category_id 和 parent_id 筛选。parent_id 同时命中该一级分类和它的二级分类。
12. 前端一级分类下拉由分类表重建。有子分类时才显示二级下拉。提交时优先取二级 id，没有二级用一级 id。
13. 账户下拉用 <optgroup> 按大类分组，选项文字带当前余额。
14. 资产页按大类渲染账户卡片，点卡片选中并显示该账户专属流水。
15. 快捷记账预选当前账户。弹窗关闭时复位锁定状态。
16. 分类管理弹窗树形展示，可新增一级或二级分类。删除失败时直接显示后端原因。

验证：
1. 迁移 33 条断言、接口 47 条断言通过。
2. 前端 42 条断言通过，alert 0 次。
3. Edge headless 复核真实页面，账户卡片、日历、总余额均正常。

————————————————————————

v0.06-DEV 2026-10-26 转账、公式与 Toast

技术路径：
1. records 新增 formula、to_account、fee 三列。仍用 ALTER TABLE ADD COLUMN，老库升级不丢数据。
2. type 扩展为 expense / income / transfer。转账分类固定为“转账”，category_id 置 NULL。
3. 新增 _balance_effects()，把一笔账对余额的影响统一成“账户和变化量”列表。收入加金额，支出减金额，转账转出减金额加手续费，转入加金额。
4. 删除旧的 _signed()。新增、编辑、删除都走同一份效果表。编辑时先按旧值撤销，再按新值施加。
5. 校验集中到 _transfer_problem()。转出和转入不能同名，两个账户必须存在，余额不足拒绝。加 1e-9 容差避免浮点误差。
6. 转账要求账户必须存在。避免手滑写错账户名时凭空建新账户，导致钱对不上。
7. 余额不足只卡转账。支出仍允许负余额，延续 v0.03 的如实记录原则。
8. 后端接收 formula、to_account、fee。转账时强制分类为“转账”，category_id 置空。
9. GET /api/records?account= 同时匹配转出账户和转入账户。一笔转账在两个账户流水里都能看到。
10. 删除账户的引用检查补上 to_account。
11. _parse_formula() 只校验类型和长度，不解析算式。结果由前端算好再提交，避免两边算出不同结果。
12. 前端金额框改为文本输入。输入带运算符时实时显示结果，算不出来红字提示。保存时提交结果金额和原公式。
13. 计算用本地 math.js，不用 eval。alert() 全部换成全局 toast()，删除操作保留 confirm。
14. 转账时隐藏分类，显示转入账户和手续费。列表显示“转出到转入”和转账徽章。转账不计入总收入总支出，但改变总余额和两个账户余额。

验证：
1. 后端自测 47/47 通过，覆盖转账主流程、非法请求、公式留存、编辑删除回滚、账户保护。
2. 前端自检 52/52 通过，alert 0 次。
3. Edge headless 复核真实页面，表格、账户卡片、日历、统计卡片均正常。

————————————————————————

v0.06.2-DEV 2026-10-27 三栏看板、详情弹窗、通知中心、视觉修复

技术路径：
1. 首页改三栏看板。中栏放主卡、预算环、近 7 天分组、全部账单。右栏放日历和当日明细。
2. 顶栏用 grid 三段布局，搜索框居中。右侧放信封、主题切换、记一笔。
3. 侧栏支持汉堡折叠，宽度 76px。小于 1200px 自动收起。用户手动选择存 localStorage。
4. 主题变量拆成 :root 和 [data-theme="dark"] 两套。切换主题不闪。
5. 图标按钮统一挂 Bootstrap tooltip，悬停 0.5 秒出现。
6. 表格删除最后一列“编辑、删除”按钮列。整行可点击，支持键盘 Enter 和空格，打开详情弹窗。
7. 详情弹窗支持 Esc 关闭，Enter 进入编辑。按钮和输入框自己的 Enter 不被抢。
8. 表格设置最小宽度和响应式容器。1439px 隐藏账户列，1199px 隐藏备注列，金额始终可见。
9. 热力图透明度封顶 0.35。删除深色底白字规则，结余固定深灰，收入绿，支出红。
10. 通知中心后端新增 notifications 表，提供列表、创建、删除接口。空表时插入一条上线通知。
11. 新增上传接口 POST /api/upload。支持常见图片格式，限制 5MB，uuid 重命名存 static/uploads/。
12. 新增 /admin 发布台。支持标题计数、contenteditable 富文本、封面上传、发布时间可空、右侧列表删除。
13. 前台信封打开右侧滑出面板。通知倒序、图文混排。富文本用 DOMParser 白名单清洗后插入。未读红点打开面板后写 localStorage 已读。
14. 前端新增 recordRowHtml、accountRowHtml、listRowHtml，去掉操作列。行点击、键盘、最近记录用事件委托。
15. 修复 refresh() 调用不存在的 loadStatistics() 导致首页渲染失败。改为拉账户、记录、日历记录后统一 renderDashboard()。

验证：
1. py_compile 和 node --check 通过。
2. Edge headless 访问主要页面和接口均 200。
3. 同源 iframe 模拟点击 19 条断言全 PASS，页面 0 报错。
4. 接口自测完成通知创建、图片上传、访问图片、删除通知。

遗留：
1. ECharts 饼图和 30 天折线、悬浮球、分页、CSV 导出、PWA 尚未进入本版。
2. style.css 仍有少量旧规则，已不再被 DOM 命中，暂不影响。

————————————————————————

v0.06.3-DEV 2026-10-27 ECharts 图表、预算悬浮球、账单分页与滚动加载

技术路径：
1. ECharts 下载到 static/vendor/echarts.min.js，本地引用，不走 CDN。
2. 中栏预算卡下方增加图表面板，包含饼图和趋势图。副标题实时显示本月支出笔数和近 30 天合计。
3. monthExpenseByCategory() 按分类汇总本月支出，超过 8 类时前 7 类加“其他”。
4. dailyExpenseSeries(30) 用 shiftDateKey 补零，保证折线固定 30 个点。
5. 饼图和折线图共用 Toolbox，支持保存图片和恢复。restore 事件回灌最新数据。
6. 图表实例懒初始化。renderDashboard() 里调用 renderCharts()。切页、切主题、容器变宽都重画。
7. 右下角悬浮球展开预算面板。显示本月预算剩余、进度条、已花和上限。超支时剩余金额转红，进度条封顶 100%。
8. 全局快捷键：N 记一笔，Ctrl+K 聚焦搜索，Esc 关闭弹窗或面板。输入框内打字不抢键。
9. 账单分页支持 20、50、100、不分页。选择存 localStorage。
10. 分页模式渲染页码条，显示总笔数、当前区间和页码按钮。
11. 不分页模式先渲染 20 条。底部哨兵用 IntersectionObserver 监听，滚到底追加 20 条。滚动容器是 .content，监听用 capture。
12. 搜索或新增账单后 resetPaging() 回第一页。新账目按时间倒序在第一行，避免停在旧页以为没存上。
13. 修复侧栏折叠后图表宽度不更新。window.resize 在回流前触发，改为 ResizeObserver 加 rAF 防抖。
14. 容器宽度为 0 时跳过 resize，避免 ECharts 把画布压成 0。
15. 修复空列表显示“第 0–0 条”。renderPager 增加 total=0 分支，只显示“共 0 笔”。

验证：
1. node --check 通过。
2. Chrome headless 加 CDP 驱动 9 组脚本打真实页面。
3. 饼图 6 类，折线 30 点，Toolbox 保存图片存在。
4. 分页验证 45 条数据，默认 3 页，每页 50 变 1 页并写 localStorage。不分页从 20 到 40 到 45，无重复。
5. 悬浮球预算剩余、已花、进度条、超支红字、快捷键均通过。
6. 端到端新增一笔 1.23，首行即新账，饼图对应分类加 1.23。删除后数据和统计回到基线。
7. 1280、1024、768、390 宽度无横向溢出。图表宽度与容器一致。页面 0 报错，仅既有 favicon 404。

遗留：
1. CSV 导出、PWA、软删除、借贷、桑基图、分享长图按蓝图 Step 6 到 10 继续。
————————————————————————

v0.06.3-DEV 2026-10-27 终极补丁：PWA、CSV 导出、极客交互与系统兜底

技术路径：PWA 用根目录 manifest.json 和 service-worker.js，由 Flask 显式路由返回并声明 Service-Worker-Allowed，前端注册后导航请求走 network-first，静态资源走 stale-while-revalidate，接口与管理页不缓存；导出接口读取 sqlite3 记录后用 csv.writer 写流，首部拼接 \uFEFF BOM，前端 fetch 取 blob 触发下载，版本接口优先环境变量、否则读取 git describe，模块级缓存后注入侧栏与我的页。

交互层用原生事件完成，全局 keydown 接管 Ctrl+K 与 N，账单列表代理 contextmenu 弹自绘菜单并按视口钳位，分类与账户引入本地 Sortable.js，排序结果写入新增的 sort_order 列，接口校验同一父级后按数组下标回写；兜底部分统一封装 fetch 用 AbortController 控制 10 秒超时，online/offline 驱动顶部红绿横幅，404 由 errorhandler 分流为 JSON 或独立模板。

踩坑结论：Sortable 实例在列表重绘后必须 destroy 重建，Service Worker 注册不能挂在 window.load，CSV 的 mimetype 只写 text/csv 避免重复 charset，headless 合成拖拽不可靠，最终以接口幂等和 DOM 结构断言兜底。

v0.06.4-DEV 2026-10-27 白屏紧急修复：断网横幅未闭合

技术路径：浏览器按 HTML 容错解析后，断网横幅的 div 一直没闭合，把整个 .app 三栏布局吞成了自己的子节点；横幅是 position: fixed 且默认透明，于是页面只剩白底，控制台没有 JS 报错，只剩一条无关的 PWA meta 警告。修复为给 #net-banner 补上结束标签，让它成为 body 下的空占位节点。

排查手段：先用 curl 确认页面与静态资源均 200，再用 headless Chrome 加 CDP 读取 body 直接子节点、.app/.sidebar/.main 的几何尺寸和 canvas 宽度，发现 body 只剩 toast-stack 与 net-banner，最终定位到未闭合标签。修复后侧栏回到 232px、主区 1192px，图表 canvas 恢复 304 宽。

踩坑结论：Flask 模板能正常渲染不代表 DOM 结构正确，白屏且无 JS 报错时优先用 DOM 树和布局几何定位，而不是继续翻 JS；新增 fixed 浮层务必确认成对闭合，否则会静默吞掉整页。

————————————————————————

v0.07.0-DEV 2026-10-27 通讯录与双向借贷前端

技术路径：通讯录放在“我的”页底部，左侧联系人列表、右侧详情卡，点开时按 /api/debts?contact_id= 拉取该人的全部借贷并汇总待收/待还。记账弹窗类型增加“借贷”，复用同一套表单：切换后隐藏分类与备注，显示联系人下拉、借出/借入单选和资金账户。余额联动放在数据库事务里，借出扣减、借入增加，改金额或换账户时先回滚旧影响再套用新值，避免前端两步请求出现半成功状态。

验证：接口 18 项断言（重名 409、金额校验、按联系人/状态筛选、结清不改余额、删除借贷精确回滚、有借贷时联系人不可删）；headless 实测新增联系人、借出 30 后现金 20517→20487、删除后回到 20517，普通支出保存无回归。

v0.07.1-DEV 2026-10-27 CSV 日期、通知编辑与通讯录对齐

本版把导出 CSV 的日期列强制按文本输出，Excel 不再把它误认成数字而只显示一串井号，文件开头的 BOM 与中文编码保持不变。开发者后台补上通知编辑：点已有通知即可把标题、正文、封面与时间回填到表单，保存时走更新接口，也可以随时取消编辑。通讯录的说明文字补齐了与卡片标题一致的左内边距，通知抽屉的硬边框换成了柔和阴影。测试覆盖导出内容、更新与取消编辑、浅色与深色下的面板样式。

v0.07.2-DEV 2026-10-27 通知正文去黑

通知面板发黑的根源不在容器，而是通知正文从聊天界面粘贴时自带了深色背景和浅色文字。本版在展示层统一清掉正文及其子元素的背景色，让文字跟随主题，浅色模式下面板固定纯白底、淡边框与极轻阴影，只有深色模式才使用深灰底。遮罩透明度同时下调，浅色下几乎不压暗页面。headless 截图复核两种主题均无黑块。

v0.08-DEV 2026-10-27 AI 快记：一句话记账真实联调通过

顶栏新增「AI 快记」输入框，用户输入一句话后由后端转交智谱 GLM-4-Flash 解析成金额、类型、分类、账户、日期等字段，再复用普通记账的入库逻辑写库并联动余额。模型只负责抽字段，金额、类型、日期到本地还会再过一遍校验，分类不存在时自动建一级分类，写库失败与转账余额不足仍按原规则返回 400。密钥继续只从 .env 读取，不落日志、不进代码。

真实联调结果：「昨天打车花了30」解析出金额 30、type expense、分类交通、date 2026-10-26 00:00；POST /api/records/ai 落库 id=97，现金 10517→10487、本月支出 +30，删除后统计与余额精确回到基线。此前 401 的根因是 5000 端口残留旧 Flask 进程仍在用旧密钥，验证必须在读取新 .env 的干净进程里做。

v0.08.1-DEV 2026-10-27 AI 意图路由 + 快记弹窗 + 报销闭环

本版把 AI 从「只会记账」升级成意图路由：模型先判断一句话属于记账、借贷、添加联系人还是听不懂，再只抽该分支需要的字段，后端 /api/records/ai 按 action 分流到 add_record、create_debt（按姓名查联系人，没有就自动建，写库失败回滚）与 create_contact，听不懂返回 400「AI 无法理解您的指令」。前端删掉顶栏单行输入，改成「+ 记一笔」旁的蓝紫渐变【AI 快记】按钮，点开多行弹窗，发送时按钮转圈，成功关窗并按 action 弹对应 Toast，听不懂保留原文并提示，支持 Esc 关闭与 Ctrl+Enter 发送。报销闭环同期落地：账单详情弹窗加报销开关，开启后选报销人与金额（默认全额），可标记已报销；后端新增 PUT /api/records/<id>/reimbursement，资产页顶部实时显示待报销与已报销金额，报销变化不影响账户余额。

真实联调：四种意图全部命中，借出 20 现金 -20、借入 100 现金 +100；报销链路跑通开启 / 已报销 / 关闭并精确回基线，超额、收入账目与非 bool 参数均被拦截。踩坑：GLM-4-Flash 会把姓名里的「测试」前缀或数字当废话删掉，Prompt 必须明确「姓名原样保留」；Bootstrap 弹窗开合动画期间 hide() 会被忽略，保存后立刻关闭需补一次延时重试。
