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

v0.09-DEV 2026-10-28 全站骨架 5:5 与「我的」页四卡统一

本版只动布局骨架，先把全站分块从 6:4 调成 5:5，左侧深色侧栏由 232px 收到 176px，刚好容纳导航与品牌文字；窗口低于 1024px 时主区自动降级单列堆叠，窄屏不再横向挤压。

「我的」页把原先占满下半屏的通讯录收成与「我的账本」同尺寸的小卡片，联系人列表与详情整体移入弹窗，按钮通过 data-bs-toggle 打开，原展开/收起逻辑随之删除；同排新增回收站占位卡，四张卡片统一内边距 22px、圆角与间距，并用 grid-auto-rows:1fr 让它们等高。

验证：无头浏览器断言侧栏 176px、首页两栏各 591px、四卡同为 246px 且无内容溢出、通讯录弹窗宽 840px 正常展开、900px 首页单列与 780px「我的」页单列均无横向滚动。

v0.09.1-DEV 2026-10-28 资产页重构 + 回收站实装 + 日历与预算细节

资产页整段重写：顶部渐变卡展示总净资产，下方小字拆出总资产（正余额账户 + 待收借出）与总负债（负余额账户 + 待还借入），再用四张小卡显示借入、借出、待报销、已报销；账户仍按大类分组，点账户后流水按日期分块，每块先给当日收/支小计再列明细。

回收站接上 records.deleted_at：DELETE 改为软删并回滚余额，新增回收站列表 / 恢复 / 彻底删除三个接口，「我的」页卡片点开弹窗，恢复会重新扣减余额，彻底删除只在软删数据上生效。预算从 window.prompt 换成 Bootstrap 弹窗（Enter 提交、Esc 关闭、非法值红框），日历用 repeat(7,minmax(0,1fr)) 锁死七列等分，今天改淡蓝高亮、年月按钮圆角、图例居中，深色模式把红绿提亮并略提透明度。

踩坑与修复：Bootstrap 弹窗动画期间 hide() 会被忽略，抽了 hideModalSafe 统一兜底；软删必须与余额回滚同事务，否则回收站里的账仍占着余额。验证：回收站全链路（软删→列表→恢复→再删→彻底删→404）与无头 UI 断言（侧栏 176px、日历七列 73px 等宽、净资产卡与四小卡、流水 3 天分组、预算弹窗 5200、回收站弹窗恢复与彻底删除）全部通过，测试后余额回基线。

补丁：用户验收提出资产页必须左右分块，遂把账户列表与流水包进 .assets-split（左 4 成、右 6 成），进入页面默认选中「现金」并直接出流水，选中卡片改为淡蓝底 + 左侧蓝色竖条，1024px 以下自动上下单列。

v0.09.2-DEV 2026-10-28 全站账单流去表格化 + 资产页与悬浮球重构 + 金额语义色

全站金额改为语义上色：只有 type=income 用绿色、type=expense 用红色，转账与借贷资金流转统一回正文深灰，日历、首页、资产页共用同一套 amt-income / amt-expense / amt-neutral 类。首页账单、日历当日明细、资产页流水三处 <table> 全部换成 App 列表流（feed）：月表头带当月收支汇总，日表头只写「25日」并省略年份，行内左侧灰色时间、中间分类与备注、右侧金额加当时余额快照；余额快照按账户当前余额倒推每笔流水影响计算，因此老数据也能直接显示。资产页把净资产卡收窄到左 4 成，新增小眼睛一键隐藏金额与自定义背景图（图片压到 1600px 转 JPEG 存 localStorage，代码里留了后续上云同步的 TODO），右侧借入/借出/待报销/已报销四卡压成 2×2 并可点开明细弹窗，账户列表改为彩色圆标列表流。右下角悬浮球换成蓝色钢笔，点击径向弹出普通记账、AI 文本快记、AI 截图识别三个分支，悬停 0.5 秒出 Tooltip，3 秒无操作或再点钢笔自动收回，截图识别先留文件入口。侧栏锁死 140px 并缩按钮内边距，导航文字保持不截断，ECharts 两个实例补上 resize 防抖。

踩坑与验证：AI 借贷余额联动本来就由 database.create_debt 在同一事务里调用 _apply_effects 完成，真实接口回归「借给测试乙12.5元」现金 -8272 → -8284.50、「向测试丙借了8元」→ -8276.50，删借贷后回 -8272 基线；但姓名里带数字（如 测试乙41215）会让模型把数字当金额解析成 6607712.5，测试数据必须用干净姓名。验证：node --check、账单流/侧栏/资产页/统计弹窗/悬浮球/图表 resize 的无头断言全部通过，样式探针确认真实比例为 40:60、统计卡 2 列、净资产卡占 40%、支出 rgb(220,38,38) 与收入 rgb(5,150,105) 不同色，测试后库内 15 条账目、联系人回收站均回基线。

v0.10-DEV 2026-10-28 AI 流式解析 + PWA 骨架 + 账单页 + 全局气泡与四向悬浮球

本版先补后端 AI 底座：智谱解析从一次性 JSON 升级为意图路由加代买报销场景，模型先判断记账 / 借贷 / 加联系人 / 听不懂，再把 is_reimbursable 与 contact_name 一并抽出，报销账目自动关联联系人并按金额计入待报销；金额提取强制「只认带元、块、¥ 等货币单位的数字」，姓名原样保留。新增 /api/records/ai/stream 用 Flask stream_with_context 以 SSE 分阶段推送 thinking → 识别金额 → 匹配分类 → 写入 → done / unknown / error，另建 ai_feedback 表与反馈接口记录原始文本、AI 结果与用户纠正，/admin 补上「AI 反馈与记忆」Tab 可标记已处理。

全站骨架改为锁 100vh、body 不滚动，左侧导航、中栏、右栏各自 overflow-y:auto；manifest 切到 window-controls-overlay，用 env(titlebar-area-*) 给顶栏留出窗口控制按钮安全区并设拖拽区，首页卡片整体缩 20%，资产页收成左 4 成（净资产卡 + 借入 / 借出 / 待报销 / 已报销四卡）右 6 成流水。新增「账单」页：左侧年月树带当月收支，右侧关键词、类型、账户、日期区间、金额区间筛选配八列大表格，账单流统一支持年 / 月 / 日三级折叠并记住状态；金额语义色全局生效，侧栏点击后强制收起残留 Tooltip，资产统计四卡点击弹对应明细。

交互层把 AI 入口做成「极速拦截 + 气泡」：输入框先过正则，命中「午饭30」这类格式且未写账户就自动补现金，直接 POST /api/records 入库并弹成功气泡；其余指令立即关闭弹窗，在右下角生成可并发气泡，走 SSE 接口做打字机与思考动效，成功后带标识并可点击打开详情，3 秒后淡出，悬停或页面失焦暂停倒计时。悬浮球钢笔改为径向四分支（普通记账、AI 文本快记、AI 截图识别占位、帮助），3 秒无操作自动收回，帮助弹窗列出快捷键与功能速览。

踩坑与验证：Bootstrap 弹窗在开合动画中会忽略 hide()，重试从单次 400ms 改为 200ms 轮询 15 次才稳定关闭；SSE 的 done 事件里记录 id 在 payload.id 而不是 payload.record.id，前端取错会丢详情入口；unknown 的 status 是字符串而非 HTTP 400，气泡与旧接口 400 需分开判断。验证：py_compile 与 node --check 通过，SSE 事件序列、报销落库（现金 -12.5、待报销 +12.5、联系人小王）、反馈 POST → processed → 清理、旧接口 400 兜底全部断言通过；无头浏览器实测三级折叠、账单页树与筛选、资产页 4:6、四统计卡明细、悬浮球四分支与 3 秒收回、极速拦截生成「现金 / 餐饮 / 30」并出气泡、SSE 报销气泡点击进详情、unknown 恢复原文，测试数据全部清理，余额回 -8272 基线。

v0.10.1-DEV 2026-10-28 视觉与布局六项补丁

本补丁只修验收中暴露的前端细节，不动业务逻辑。日期字段原先用原生 date/datetime-local，占位符固定英文 yyyy/mm/日，用户端与 /admin 发布时间都无法直观回显；改为「可见 text 输入框（占位 年 / 月 / 日）+ 全尺寸透明原生选择器覆盖层」，原生 change 时把值写回文本框并触发 input 事件，重置按钮同时清空两层，管理后台编辑回填也同步。资产页右侧大面积留白源于 .assets-split 的 align-items:start，改为 stretch 并让右栏 flex 撑满，空账户时也保留 220px 空态高度；首页图表被 #page-home 覆盖压到 188px，补容器 min-height 240px、画布 210px；悬浮球四向坐标原先带正 X 位移，1440 宽下 AI 截图与帮助图标越出右边界，全部改为向左上方展开并同步窄屏断点；侧栏 Tooltip 的 trigger 含 focus，点击后会被重新唤起，改为 nav 仅 hover 触发、点击时 hide() 并 blur()；账户名补 ellipsis 与块级宽度，余额 flex:0 0 auto 不再被挤。

踩坑与验证：原生 date 输入框在浅色主题下文字颜色继承主题变量，视觉上容易误判为「没回显」，实际值是正常的，换成人眼可见的文本框后问题彻底消失。无头浏览器断言：图表盒 249px / 画布 210px 且底部未被切、资产页左右均 817px 等高、空账户仍留 220px 空态、FAB 四图标右边界 1280-1374 全部小于视口、Tooltip 悬停出现且点击后 0 残留、长账户名省略号且与金额仍留 10px 间距、账单页选 2026-10-01 后文本框回显且 billsFilter.dateFrom 同步、重置两层皆空、/admin 选 2026-11-05 10:30 后文本框回显为「2026-11-05 10:30」，浅色与深色主题下日期文字颜色都跟随 --text-main，页面无 JS 报错。

v0.10.2-DEV 2026-10-28 真实浏览器布局抢救：资产页高度链 / 图表 280px / 悬浮球圆弧

本补丁针对用户在真实浏览器强刷后仍看到的三处观感问题，只动 layout 不动业务。资产页原来只靠 .assets-split 的 align-items:stretch 撑高，实际上外层没有高度约束，左右两栏按内容高度渲染，右栏流水少或账户为空时下方漏出一大片灰底；改为 #page-assets.active 自身 display:flex、flex-direction:column、overflow:hidden，.assets-split flex:1 1 auto + height:100% + min-height:0，左右两栏各自 height:100% + overflow-y:auto，右栏 panel 再套一层 flex column 让 .bill-feed-scroll 用 flex:1 吃掉头部以外的全部高度，空态也 flex 撑满，整页高度链才算闭环。

首页 ECharts 之前只补了 min-height 240 / 画布 210，真实浏览器里仍显得扁且图例挤在一起；这次直接给 #page-home .chart-canvas 锁 height:280px !important、外层 .chart-box min-height:310px，窄屏降为 240 / 270，并把 scheduleChartResize 的节流改为 setTimeout 100ms、initCharts 末尾补一次延迟 resize，等 CSS 高度落定后再让 ECharts 量容器，画布不再按旧尺寸绘制导致折线下半截被裁。

悬浮球原先四个方向各自手写位移，数值过近导致图标叠在一起；改成标准圆弧算法：以主球圆心为中心、半径 118px 取 180° / 150° / 120° / 90° 四个角度（record -118,0 / help -102,-59 / ai -59,-102 / shot 0,-118），相邻中心距 61px，1024px 与 576px 断点分别缩到半径 104 / 92，保证窄屏也不重叠、不出视口。

踩坑与验证：v0.10.2 的媒体查询一度把 #page-assets.active 在 1023px 以下改回 display:block，导致单列时高度链断裂，回退必须只保留给 .assets-split；圆弧展开是否重叠要用图标中心距而不是肉眼估。用真实 Chrome（headless=new）在 1440x1000 / 1920x1080 / 1366x768 / 900x1000 四档拉缩断言：资产页 split 高度与可用高度一致、左右栏等高、右栏流水与空态均撑满且无灰带；画布 280（900 宽 240）上下未裁切、图例不重叠；FAB 图标中心距 61px、右边界全部小于视口，悬停 0.5 秒 tooltip 正常，页面无 JS 报错。


补充修复（同日）：首页中栏 / 右栏此前虽然写了 overflow-y:auto，但栏内的卡片是 flex 子项、默认 flex-shrink:1，会被固定高度的栏压缩到 327px / 158px，内容从卡片盒子里溢出来压住下一张卡——日历网格底部被「账单明细」盖住、近 7 天账单也只在自己内部滚。修复给 `.dash-center > .panel` / `.dash-rail > .panel` 加 `flex: 0 0 auto`，卡片按自身内容自然撑开，滚动全部交给中栏 / 右栏两个外层容器；同时删掉 `.recent-groups` 的 max-height:460 与 `#page-home .bill-feed` 的内部滚动，让外层统一接管。1440 / 1920 / 1366 / 900 四档实测：中栏 scrollHeight 2833、右栏 1963，各自 scrollTop 可独立到 333 / 222，整页 window.scrollY 恒为 0，日历卡底边 <= 日明细顶边（不遮挡），近 7 天内部不再出现滚动条。


补充修复 2（同日）：首页「本月预算」卡片重写为左右两栏。左栏固定 96px、只放环形进度（19px 百分比 + 「已用」）并垂直居中；右栏 flex:1，三段式纵向排布——顶部「本月预算」+ 右对齐「改预算」、中间「已花 ¥xxx / 预算 ¥xxx」、底部「日均 / 剩余日均额度」+ 8px 长条进度条，进度条贴底且撑满右栏宽度。原先卡片在 1280px 以下被旧媒体查询强制竖排、圆环与文字上下堆叠造成大面积留白；现在明确 flex-direction:row，仅 576px 以下才堆叠。四档视口实测卡片高 131px（原 141px）、圆环上下留白各 17/18px（等于内边距，无多余空白）、右栏与圆环等高、三行间距各 5px、进度条宽 = 右栏宽。


补充修复 3（同日）：资产页左栏滚动层错位。原先 `overflow-y:auto` 加在 `.assets-left`（整列）上，账户一多就是整列一起滚、净资产卡和统计卡被顶走，面板本身也没有真正受限高度。改为标准高度链：`#page-assets .assets-left` 用 `display:flex;flex-direction:column;height:100%;min-height:0;overflow:hidden`；`.assets-hero`/`.asset-stats` 设 `flex:0 0 auto` 不被压缩；`.accounts-panel` 设 `flex:1 1 auto;min-height:0;display:flex;flex-direction:column;overflow:hidden`；真正滚动的是内部 `.account-groups`（`flex:1;min-height:0;overflow-y:auto;overscroll-behavior:contain`），`.panel-head` 固定不滚。1440/1920/1366/1200 四档实测：账户列表 scrollHeight 1513、可视 491/571/259/391，滚动位移 1022/942/1254/1122，左栏自身滚动位移恒为 0，净资产卡 150px、统计卡 157px 始终不被压，滚动到底部最后一个账户完整可见；<1024 单列时回退为页面滚动 + 列表 60vh 上限。

v0.11-DEV 2026-10-28 AI 截图记账闭环：视觉模型解析 + 图片持久化 + 相册与悬浮球交互

本版把「截图记账」从占位提示做成完整闭环。后端 ai_service 增加 parse_image：图片以 Base64 dataURL 塞进多模态 content 数组，交给 glm-4v-flash，配一份与文本版同约束的视觉 Prompt（金额只取实付、分类按商户、时间按小票，非账单返回 unknown），模型返回严格 JSON 后复用文本版的归一化与字段校验。app.py 新增 POST /api/records/ai/image：校验并解码 Base64（限制 5MB）→ 调视觉模型 → 命中 record 时复用原有意图分流入库 → 把前端压缩后的图片写入 static/uploads/ 并把路径回填 records.image_path（新增列，走既有 PRAGMA 迁移）；未知/非账单返回 422，图片解析失败 502。同时补 GET /api/records/images 相册列表与 DELETE /api/records/<id>/image 双删（清空 image_path 并删本地文件，账目本身保留）。

前端把悬浮球【截图】换成真实文件选择：Canvas 按最长边 800px 等比缩放、白底转 JPEG（质量 0.82）再上传，避免大图超时；上传全程复用非阻塞气泡，先显示「正在识别截图…」，成功后标题「截图记账成功」并带 recordId 可点击直达详情，失败弹红色「无法识别该截图」。账单详情在有 image_path 时多一块「截图凭证」缩略图，点开走统一的「查看原图」预览弹窗；「我的」页新增相册卡片，弹窗以三列网格展示所有带图账目，点缩略图先收起相册再开对应账单详情，右上角删除按钮同时清库与删本地文件。悬浮球收回逻辑重写：点钢笔展开后不设倒计时，点菜单功能也保持展开，只有鼠标离开悬浮球及全部子图标范围才启动 3 秒计时，移回立即取消；子图标的文字提示统一改到图标左侧竖排居中，彻底避开主球与屏幕右/上边缘。

踩坑与验证：视觉 Prompt 里自带 JSON 花括号，若用 str.format 注入当前时间会抛 KeyError(action)，改成占位符 replace；Base64 解码用逐字节 decode 会因跨 chunk 断开 UTF-8 而报错，改为一次性解码并只做长度/前缀校验；前端相册项的角标按 data-album-open 挂在按钮上，测试若按 data-record-id 取会拿不到，补了 item 级 data-record-id 才统一。真实 Chrome（headless=new）E2E 断言 31/31 通过：悬浮球展开 4.2 秒不收回、四子图标圆形中心距 61px 且全在视口内、提示居中在图标左侧且不压主球、选中 1600x1022 的图后压缩为 800x511、账目落库 amount 30/餐饮/expense/image_path 且文件在 uploads、成功气泡可点、相册网格出现 ¥30.00、详情显示截图凭证、原图预览同图、删图后账目仍在而本地文件消失、移出 3 秒收回且移回取消倒计时、页面无 JS 报错；后端脚本断言识别/落盘/相册/双删/非账单 422/坏 Base64 400 全通过，测试账目全部清理、余额与 uploads 回基线。

v0.11.1-DEV 2026-10-28 应用化四件套：窗口控制按钮适配 / 图片快记 / 通知起草审核 / 全站访问密码

本补丁把项目再往「真正可交付的本机应用」推一步，四块一起做。PWA 侧 manifest 改为 window-controls-overlay，CSS 用 env(titlebar-area-*) 把 topbar 的右侧让给系统窗口按钮，按钮区标记 no-drag。AI 快记弹窗新增【上传图片】入口，文件选择后用 FileReader 本地生成 dataURL 缩略图，旁边标注文件名、大小与「发送时自动压到 800px」，点发送时优先走 /api/records/ai/image 并复用全局气泡，无图仍走文本解析。

通知体系升级为「AI 起草 + 人工审核」：ai_service.generate_notification 按主题生成标题与 1./2./3. 序号正文，草稿以 status=draft 存进 notifications 表；GET /api/notifications 默认只返回 published，管理端显式 ?include=drafts；/admin 新增 AI 起草输入框、待审核草稿（可发布/编辑/删除）与已发布通知两栏，PUT /api/notifications/<id>/publish 只改状态。全站访问密码用 admin_config 存密码哈希与免密时长（10 分钟~1 天滑块可调）、access_sessions 存验证会话：未设密码不拦；设了密码后 static/access-guard.js 先于主脚本启动，插全屏遮罩并锁滚动，验证通过把 token 与验证时间写 localStorage 并刷新，超时或任何 401 access_required 立刻重新上锁且保留已填内容；/admin 设置齿轮 Modal 管理密码增删与时长，改密、删密、调时长距上次验证超过 5 分钟必须弹框重新输当前密码，服务端同样以 5 分钟会话二次校验兜底。

踩坑与验证：首次设置密码的瞬间全站进入保护态，但当前页还没有 token，随后 loadSettings 会 401，导致密码列表空白——改为首次设密成功后自动刷新，交给遮罩接管登录；测试模拟「免密期已过」必须同时回拨浏览器 localStorage 验证时间与服务端会话时间，只改数据库时前端仍认为在 5 分钟内。验证：py_compile 与 node --check（含 admin 两段行内脚本提取后检查）通过；后端脚本 31/31 通过（保护开关、401 拦截、错误密码、5 分钟重验证、草稿发布、测试数据回基线）；真实 Chrome（headless=new）E2E 全绿——AI 弹窗选图后缩略图 84px、dataURL 预览、说明含大小与压缩提示、发送后气泡成功且可点、入库 30/餐饮/招商银行储蓄卡/image_path 落盘；/admin AI 起草出草稿并可发布到已发布列表、设置面板空态与滑块 60↔30 双向保存、新增密码后自动刷新出遮罩（z-index 9999、锁滚动、接口 401）、错误密码提示「密码不正确」、正确密码解锁并写入 token、回拨 10 分钟后删密码弹出重新验证、验证后密码删空恢复免密，测试账目/通知/上传图全部清理，余额回 -8272、通知回 14 条。


v0.11.2-DEV 2026-10-29 后台齿轮图标 / 日志驱动通知起草 / 密码明文查看

本补丁按验收反馈补三处「能看见的小毛病」。/admin 顶栏设置按钮此前只塞了一个 SVG、没有任何样式，浏览器按默认按钮渲染成一个丑白框；这次补全 .admin-gear-btn：40×40、11px 圆角、1px 描边、var(--surface)/var(--text-main)/var(--shadow-sm) 跟随主题变量，hover 旋转 45° 并切到品牌蓝底白图标，focus-visible 描蓝边，深色主题下底色自动变成 #131c2b、图标变浅灰。

通知 AI 起草以前只看主题自己编，容易写出日志里不存在的功能；ai_service 新增 latest_dev_log_entry()，先把 docs/dev-log.md 最后一个版本段的正文读出来（去尾部分隔线、截断到 3600 字符），拼进 NOTIFICATION_PROMPT 的【绝对依据】段落，并明确要求「只能基于日志已有内容润色成面向用户的公告，不得编造」。读不到日志时给保守兜底提示，不会让模型自由发挥。

访问密码改为可回显的新格式：v0.11.1 存的是「盐$SHA256」，单向不可逆，无法做「查看明文」。v0.11.2 起新密码存 p1$ + urlsafe Base64（_encode_password/_decode_password），_password_matches 同时兼容旧格式校验；密码列表接口只回序号与掩码，绝不回明文或哈希。新增 POST /api/access/passwords/reveal：必须 body.password 当场验证任意一个当前密码（走 _fresh_admin_check 之外的独立校验，会话超 5 分钟也照样能查），验证通过返回该序号明文；旧格式密码返回「这个密码是旧版哈希存储，无法回显；请删除后重新添加」。前端密码列表默认全是 ******，点【查看密码】弹独立小窗输当前密码，错密只回内联错误、不泄露明文，验证通过后该行变明文并加 is-plain 标记，Enter 可直接提交。

踩坑与验证：Bootstrap 弹窗刚弹出就立刻验证时还处在入场动画里，hide() 会被忽略导致弹窗卡住不关，补 350ms 延时兜底重试一次；测试要模拟「免密过期」必须同时回拨 localStorage 的 verifiedAt 与服务端会话时间。后端脚本 27/27 通过（旧哈希可登录但提示无法回显、新格式可回显、任意当前密码可验证、错密 401/缺密 400/越界 400、超 5 分钟 reveal 仍独立通过、AI 起草正文引用真实日志关键词、草稿不出现在用户端、测试后配置逐字恢复）；真实 Chrome E2E 38/38 通过（遮罩 z-index 9999 与滚动锁、齿轮 40×40 + SVG 21×21 + 11px 圆角、hover 蓝底 rgb(37,99,235) 且 matrix 旋转 0.7071、深色底色 #131c2b、密码两行全掩码、独立弹窗错密内联报错、Enter 验证回显 test1234 且第二行仍掩码、回拨 10 分钟后仍可查看第二行 second5678、AI 起草卡片引用「通知/密码/访问」并清理、页面无 JS 报错、admin_config 与 access_sessions 逐字恢复）。
v0.11.3-DEV 2026-10-29 后台限定密码 / 三线趋势图 / 版本号自动公告

密码鉴权收回到后台。static/access-guard.js 新增 isAdminPage()，只有 URL 命中 /admin 时才建遮罩、开超时上锁与 401 重锁；用户端首页、账单、资产、我的全部免密直接可用。验证凭证从 localStorage 换成 sessionStorage，关掉标签页或浏览器再打开必定重新输密码。所有危险操作（查看密码、删除密码、改免密时长）的二次验证层统一加 .modal.verify-top-modal / .settings-reauth，z-index 固定 100000 !important 并配套 99999 的 backdrop，永远压在设置弹窗之上。

后端两处行为修正：手动 POST /api/notifications 强制 status=draft，AI 起草与人工填写都先落在「待审核草稿」，发布必须显式走 PUT /api/notifications/<id>/publish；访问守卫抽成 _needs_access()，/api/access/*、/api/upload 与通知写操作需要有效会话，通知读、账单读、版本号等公开。首页近 30 天趋势图从单线改为三线：红-每日支出、绿-每日收入、灰-每日结余，dataZoom 去掉、legend 与 tooltip 逐条输出金额，空态文案保留；侧栏版本号去掉「· 开发中」。

版本公告全自动：/api/notifications/draft 不再要求主题，服务端用 detect_version() 取当前 tag，ai_service.dev_log_entry_for_version() 从 docs/dev-log.md 精确抓该版本段落，拼进「版本公告撰稿人」Prompt，要求标题严格以「[版本号] 版本更新：」开头、纯文本无表情分点 3-5 条、只能基于真实日志不得编造；后端再兜底重写标题前缀。admin 起草区从「输入主题 + 起草」换成单个大按钮【一键起草当前版本更新公告】，空请求、成功后刷新草稿箱。

踩坑与验证：版本号来源单一，detect_version() 依赖 git tag，没打 tag 时一键起草会拿到上一版，所以必须先 tag 再验证；Bootstrap 弹窗层级不能靠 DOM 顺序，必须给 .modal 与 .modal-backdrop 显式 100000/99999；sessionStorage 下「刷新保留、关标签失效」，测试关标签等价于清空 sessionStorage 再 reload；AI 会自作主张在标题加方括号或换格式，后端必须剥旧前缀再拼。后端脚本 28/28 通过（版本号公开、用户端读接口免 token、通知写与设置接口 401、手动通知落 draft 且公开列表不可见、发布后可见、一键起草标题「v0.11.3-DEV 版本更新：后台安全与趋势图优化」且正文分点引用真实日志、测试后通知 15 条/草稿 0/密码与会话逐字回基线）；真实 Chrome E2E 23/23 通过（首页无遮罩无 localStorage token、侧栏「v0.11.3-DEV」无「开发中」、趋势图 3 条 series 支出#dc2626/收入#059669/结余#9ca3af 各 30 点、/admin 弹遮罩、验证后 token 只进 sessionStorage、清空 sessionStorage 重载再次要密码、查看密码弹窗 z-index 100000 且 backdrop 99999、elementFromPoint 命中 reveal-password、一键起草出「v0.11.3-DEV 版本更新：后台密码与趋势图优化」并清理、页面无 JS 报错、余额 -8272 与通知 15 条不变）。

v0.11.4-DEV 2026-10-30 趋势图可读性 / AI 同义词与置信度 / 多图串行识别 / 防重与 AI 记忆库

四组改动一起封版。首页近 30 天趋势图把 legend 放到 top:30、toolbox 收到右上角，grid.top 留到 60；收入、支出两条实线，结余改用 dashed 虚线并压到 z:1 底层，补半透明渐变 areaStyle，三线统一 opacity 0.8，图例不再压线、三条线不再糊成一团。

AI 预处理层：ai_service 新增 CATEGORY_MAPPING（滴滴/打撤→交通、星巴克/奶茶→餐饮、淘宝→购物、房租/水电→居住等），在归一化阶段强制把商户名式分类改写成标准分类；SYSTEM_PROMPT 字段扩到 16 个并要求每次返回 confidence（0-100 整数），同时明确「分类必须是标准分类名、不要把商户名当分类」；/api/records/ai 与 /api/records/ai/stream 接收 previous_record_id，命中时往 Prompt 注入「用户正在补充修改账单，请覆盖原数据」并走覆盖更新分支，返回体带 confidence；解析前还会取最近 3 条 ai_memory 当 few-shot 注入。

前端交互：截图入口 input 改 multiple，上传改成 for...of + await 的串行队列（严禁 Promise.all），每张最长边压到 800px 后逐张 POST，独立气泡显示「识别中 i/N」；成功气泡按 confidence<80 变黄并提示核对；气泡内嵌迷你输入框，用户输入「改成微信」后带账单 ID 调纠错接口，文案提示「已改为 X（已记入 AI 记忆）」；详情弹窗新增【AI 纠错】按钮走同一纠错接口。防重：保存前用 /api/records/duplicate-check 预检最近 10 分钟金额相同、商户/账户相似的账目，命中弹自定义确认框，SSE/JSON/截图三条路径都接 409 duplicate 与 force 重发。

AI 记忆库：新建 ai_memory 表（original_text / raw_category / corrected_category / note / created_at），纠错成功即落一条，解析前取最近 3 条注入 Prompt；/admin 新增「AI 纠错记忆」Tab，可查看、手动补一条、删除。

踩坑与验证：本机沙箱一度把项目目录设成只读（写 records.db 报 readonly），端到端测试前必须先确认目录可写；纠错接口返回记忆对象形如 {"memory":..,"record":..}，而 /api/ai-memory POST 直接返回记忆本体，前端两个调用要分开解析。后端脚本 14/14 通过（三文件语法、首页与管理页 200 且新弹窗/多选结构命中、ai_memory 增删查、纠错接口 其他→交通且写记忆、防重命中与不同金额不命中、分类映射、confidence 夹取），node --check 通过，测试数据全部按唯一备注清理、数据库回到原状；未做真实浏览器点测（本机未起服务）。

v0.11.5-DEV 2026-10-30 AI 账户/联系人精准匹配 / 气泡多轮全量覆盖 / 纠错反馈中心

三模块一起封版。AI 精准度：ai_service 把数据库里真实存在的账户与联系人清单注入 Prompt，明确要求「用户提到具体子账户（微信零钱、支付宝余额、招行卡尾号1234）时原样保留、不要向上合并」；新增 difflib 模糊匹配（阈值 0.8）与 ACCOUNT_ALIASES 别名表（威信/薇信/维信/威信支付→微信、银行/银行卡支付→银行卡、支付宝账户→支付宝），归一化阶段把账户名与联系人名强制换成库中真名，并返回 auto_corrected / auto_corrected_msg（如「识别到相似账户，已自动匹配为「微信」」）；解析前用用户这句话的关键词去 ai_memory 做模糊匹配取 Top 3 注入 Prompt，当 few-shot 参考。

气泡多轮纠错彻底重做：带 previous_record_id 时不再只给 9 个字段的快照，而是把原账单完整 JSON（含报销字段）交给 AI，Prompt 明确「用户没提到的字段必须继承原值、返回完整 JSON」；新增 POST /api/records/<id>/ai-revise，后端拿 AI 返回的完整 JSON 执行全量 UPDATE，余额由 update_record 内部「先撤旧账 → 校验新账 → 落新账」保证——「微信 → 微信零钱」「30 → 50」时两个账户的余额都正确回滚/扣除；报销字段同步更新，分类被改动时写 ai_memory，并把改前/改后快照写进新表 ai_correction_log。

前端与后台：气泡收到 auto_corrected_msg 用灰色小字展示，confidence<80 保持黄牌提示核对；气泡内迷你输入框从「只改分类」升级为自然语言改任意字段，改调 /ai-revise，成功后展示新的账单摘要；/admin 新增「AI 纠错与反馈中心」Tab，左栏 ai_memory 记录可滚动、可删除，右栏近期纠错审计按字段展示改前 → 改后差异与置信度，两个列表串行加载避免并发压库。

踩坑与验证：别名表替换必须放在「子账户后缀」判断之后并校验品牌是否本来就写对，否则「微信零钱通」会被别名表吞成「微信」；parse_intent 新增的 accounts/contacts 参数必须在 /ai、/ai/stream、/ai/image、/ai-revise 四处都传，漏一处就整条链路失去纠正；防重逻辑会干扰测试，mock 解析后要先把测试账单撤掉再测 /api/records/ai。后端脚本 17/17 通过（Prompt 注入账户列表与 few-shot、威信零钱通→微信且带提示语、微信零钱不被误吞、confidence 透传、ai-revise 全量覆盖 30→50 且微信/微信零钱余额双向回滚、审计日志写入与接口可用、AI 接口透传 auto_corrected_msg、清理后余额复原），node --check 与 py_compile 通过；真实模型三场景联调全部 PASS（「用微信零钱付午饭30」→ 餐饮 30 微信 置信度 95；「用威信零钱通付午饭30」→ 强制纠正为微信并带「识别到相似账户，已自动匹配为「微信」」；带原账单「改成微信零钱，金额50」→ 金额 50、账户微信零钱、分类/备注继承原值）。

v0.11.6-DEV 2026-10-30 账户编辑与余额卡 / AI 跨账户纠错与自动建户 / 批量管理与设置中心

三模块一起封版。账户体验：资产页账户列表每行悬停出现编辑图标，点开变成内联表单（名称 + 余额 + 保存/取消），改名走 PUT /api/accounts/<name> 的 new_name，后端在同一个事务里同步 accounts 主键和 records.account / to_account / debts.account，重名返回 409；资产页右栏流水顶部新增金色渐变的账户余额卡，选中账户即刷新名称与余额。AI 纠错：ai-revise 的跨账户场景（微信 → 支付宝）复用全量 UPDATE，余额先撤旧账再落新账，实测旧账户退回、新账户扣款都对；AI 识别出的账户在库里不存在时自动建空账户，响应带 is_new_account / new_account_name，气泡高亮提示「已为您自动创建新账户：xxx」并提供「合并到已有账户」按钮，合并接口把余额相加、账目与借贷迁移后删掉源账户。批量与设置：账单页和资产页账户列表加「批量管理」，开启后 Ctrl 多选，底部悬浮批量栏支持批量删除（软删并逐条回滚余额）、批量改分类（只动分类字段）、账户批量删除（仍挂账目的账户跳过并回报原因）；「我的」页新增显示与主题设置，首页卡片显示/隐藏写 localStorage，主题支持浅色/深色/跟随系统并用 matchMedia 监听系统变化；style.css 在 standalone / window-controls-overlay 模式下给 .topbar 加 padding-right 140px !important + padding-top 30px !important 作为 PWA 遮挡兜底，service worker 缓存名升到 ai-accounting-v0.11.6 让旧缓存自动失效。

踩坑与验证：批量改分类不能再调 ensure_category 的返回值当元组用，它只返回分类字典、失败抛 RecordError；账户改名必须同时改 records 的 account 与 to_account，否则转账旧名字会变成幽灵账户；交叉账户回滚不需要新写逻辑，update_record 的「先撤旧账 → 校验 → 落新账」已经覆盖，测试里 30→50 + 微信→支付宝一次通过。后端脚本 24/24 通过（跨账户双向回滚、自动建户 + is_new_account + 合并迁移、改名同步账目与重名 409、批量删账单与批量改分类、批量删账户、清理后余额复原），py_compile 通过；前端 node --check 通过、首页/管理页 200 且新 DOM 与文案命中。

v0.11.7-DEV 2026-10-30 AI 纠错完整表单 / Ctrl 多选批量 / 系统设置弹窗 / 通知双时间

三个补丁一起封版。AI 纠错：详情弹窗的【AI 纠错】从「只能选分类」重写成完整表单，金额、分类、账户、备注、日期都能改；提交不再拼自然语言，而是直接把结构化字段 POST 给 /api/records/<id>/ai-revise，后端识别到 amount/category/account/note/date 就跳过 AI 解析，按完整字段走 _apply_ai_correction 的全量 UPDATE，跨账户余额仍由 update_record 先撤旧账再落新账（微信 30 改支付宝 50 实测双向回滚正确），并写 ai_correction_log 审计。批量管理：账单页和资产页的「批量管理」补上真正的 Ctrl 语义——普通点击单选高亮、Ctrl/Command + 点击追加或取消多选，Ctrl+A 全选当前列表、Esc 退出批量；底部批量栏的批量删除（软删 + 余额回滚）与批量改分类复用 v0.11.6 接口。设置抽离：「我的」页不再内嵌显示与主题卡片，只留【打开系统设置】按钮，点击弹出居中的大号 Bootstrap Modal，主题三态与首页卡片显隐、保存 / 恢复默认都在弹窗里完成，保存后自动收起；顶栏齿轮也改为直接打开这个弹窗，不再跳页滚动。通知双时间：notifications 新增 visible_at 列（老库自动 ALTER + 用 publish_date 回填），publish_date 从此只负责列表展示时间；后台表单在发布时间下方新增「定时发布时间（生效时间）」，发布时间留空时前端自动用它兜底；POST/PUT 同时保存两个时间，发布草稿不再把排好的生效时间刷掉；GET /api/notifications 严格按 status='published' AND visible_at <= 当前时间 过滤，生效时间在明天的通知今天绝对不可见。

踩坑与验证：结构化分支一开始直接把表单字符串金额传给余额计算，抛 TypeError 变成 500，后来在路由里先 float 归一 + >0 校验才返回 400；update_record 会把日期补成「YYYY-MM-DD 00:00」，前端表单提交日期后断言要按前 10 位比较。自测 temp/test_v0117.py 20/20（通知未来生效不可见 / 生效到了可见 / 发布时间留空兜底 / POST 只传 visible_at / 结构化纠正金额与账户覆盖 / 微信回滚 + 支付宝扣款 / 审计 / 非法金额 400 / 清理后余额复原），temp/smoke_v0117_frontend.py 25/25（首页与管理页 200、新弹窗 DOM、无重复 id、Ctrl 分支与设置弹窗代码命中、无 alert），py_compile 与 node --check 通过，/admin 内联 JS 语法校验通过。
