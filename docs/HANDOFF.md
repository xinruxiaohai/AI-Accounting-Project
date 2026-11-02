AI 记账管家 项目交接文档

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
- 前端：templates/index.html、static/script.js（主逻辑）、static/charts-v013.js（图表看板）、static/auth-v012.js（JWT fetch 封装 + 登录遮罩）、static/style.css；后台 /admin 由 static/access-guard.js 保护。
- 当前版本：v0.13.5-DEV（注册安全校验与登录页美化：密码强度校验**只作用于注册**——`submitGate()` 拆成「非空共同前置 + 注册专属校验」，后端 `_register_password_error()`（≥8 位含字母数字）只挂 `/api/auth/register`，登录接口无任何强度判断，老账号纯数字 `123456` 照常登录；注册新增「确认密码」与滑块闸门 `syncRegisterLock()`（未解锁时「发送验证码」「注册并进入」置灰，用 `data-counting` 标记与 60 秒倒计时解耦）；登录卡片改磨砂玻璃 `rgba(255,255,255,0.7)` + `backdrop-filter: blur(18px)`，深色 `rgba(19,28,43,0.66)`，输入框 10px 圆角 + 聚焦发光，主按钮渐变蓝 + hover 提亮，小屏内部滚动不贴边）。静态资源版本串为 `0.13.5`、两处 SW 缓存名为 `ai-accounting-v0.13.5-r1`（每次发版必须同步 bump，否则 stale-while-revalidate 会让用户刷新一次仍吃旧 JS）。v0.13.1~v0.13.4 的全部能力均含在内。
- 历史标签：v0.11.4-DEV ~ v0.11.8-DEV、v0.12-DEV、v0.12.1 ~ v0.12.5-DEV。
- 已知坑：东财 search-api 必须保持 ≥1 秒请求间隔（进程级锁），否则 IP 会被封；邮箱验证码只存哈希、明文仅存于发信瞬间，排障时不要指望从库里捞码；.env 换 Key 必须彻底结束旧 Flask 进程再启动；UI 重构后必须同步改旧测试断言；CSS 同权重靠文件末尾覆盖；图标格子不要塞进父级 flex 行，否则被压缩变形；SW 静态资源是 stale-while-revalidate，发版后第一次刷新必然先命中旧缓存——必须同步 bump 模板 `?v=` 与 `CACHE_NAME` 才能一次刷新生效；分类网格点击后不可重建 DOM（只改 .is-active），否则 event.target 被摘出文档，外部点击监听会误收浮层。

三、核心数据模型
- users：id, email UNIQUE, password_hash, phone, nickname, avatar, created_at。管理员 id=1（1937097795@qq.com / 123456），1-9 预留，普通注册从 10 起。
- accounts：(user_id, name) 复合主键，balance 为资金唯一真相，group_name 分组。
- records：id, user_id, amount, type(expense/income/transfer), account, to_account, fee, category_id, formula, date, deleted_at 软删除, 报销字段(is_reimbursable/reimbursed_amount/...), image_path。
- categories：id, user_id, name, parent_id（二级分类）。
- debts：id, user_id, account, amount, due_date, interest, image_path, status 等。
- contacts：id, user_id, name 等；ai_memory：id, user_id, original_text, raw_category, corrected_category, keywords, note, created_at（Few-Shot 记忆库）。
- ai_correction_log / ai_feedback：纠错审计与反馈；notifications：status(draft/published) + visible_at；import_history、login_attempts、icons、user_icon_settings、admin_config、access_sessions。
- 规则：任何账单增删改都必须联动 accounts.balance，禁止只改 records。

四、核心 API 速查
- 账单/账户/统计：/api/records（增删改查、trash/restore/purge、batch/delete、batch/category、duplicate-check）、/api/accounts（改名/合并/批量删）、/api/categories、/api/statistics、/api/search。
- AI：/api/records/ai、/api/records/ai/stream（SSE）、/api/records/ai/image；均支持 previous_record_id 覆盖更新、force 跳过防重，返回 confidence/auto_corrected；/api/records/<id>/ai-revise（自然语言或结构化全量覆盖）、/api/records/<id>/correction、/api/ai-memory、/api/ai-correction-log、/api/feedback。
- 鉴权：/api/auth/register、login、me、profile、avatar（PUT 路径 / avatar/upload 直传文件）、change-password、send-code（v0.13.4 落库防刷）、verify-code、reset-password；sms-login 返回 501 占位。JWT HS256 7 天，未登录统一 401 auth_required。
- 投资：/api/invest/*（12 条，均 login_required + user_id 隔离）；`/api/invest/search` 由后端代理东财 search-api，返回 `{code,name,category,type}` 并兼容旧 `{ticker,asset_type,price,source}`。
- 其它：/api/import/parse|confirm、/api/debts/<id>/settle、/api/icons、/api/user-icons、/api/notifications（draft/publish/visible_at）、/api/access/*（后台密码）、/api/version（优先 Git Tag，其次 APP_VERSION_FALLBACK）。

五、下一步计划
- v0.13.1 已完成：全局语义色令牌（支出红/收入绿/结余灰）与 `window.__chartColors()` 单一色源，图表/列表/看板 100% 同步且切主题免刷新；设置弹窗精修（文案精简、图标网格化、下拉等宽、Checkbox 3 列、按钮像素对齐、单层滚动）；分类按 `user_id` 完全隔离 + 停用/合并 + 「已停用」管理区；T05 静默改分类用「双清单」修复；顺带修图表页数据陈旧、月份翻页 31 号失效、深色下图标选中态被同权重覆盖、1×1 退化图被放大成色块。
- v0.13.3 已完成：投资账户体系（`accounts.type`、三张新表、12 条 `/api/invest/*`、Mock 行情）、投资看板双视图（双 Tab 默认持仓、ticker 小字灰、当日盈亏骨架、平台折叠、防抖搜索、账户类型下拉）、AI `invest_buy` 意图（SSE 与非流式双路发 `need_confirm`，AI 只提示不写库）、**金额规范化同构**（`amount` 主导，堵住"卡片 1000 实际扣 500"）；封版前再补：**交易日顺延**（DCA 扣款日落在周末顺延到下一工作日）、黄金独立资产类型（下拉新增「黄金」）、扣款来源账户（`dca_plans.source_account`，可指定微信/现金扣款）、前端金额三数联动与自绘下拉（深色模式原生 `<select>` 白底刺眼）。
- v0.13.4 已完成：邮箱验证码后端（表 + 双接口 + 防刷/限次/哈希/过期，SMTP_SSL 465 HTML 邮件）、投资标的搜索接入东财 search-api（≥1 秒最小间隔、失败/超时降级本地 Mock、前端 500ms 防抖与三字段自动回填）；搜索**固定走 API**（删掉前端 `investMockEnabled()` 分支，残留调试标记不再能把中文名搜索拽回本地字典），降级时接口回 `fallback/notice`、候选框明示「已回退本地字典」；顺手修 `openHoldingModal()` 把 bootstrap 实例当 DOM 传给 `investEnhanceSelects()` 的既有 Bug。
- v0.13.5 已完成：注册校验与登录解耦（注册 ≥8 位含字母数字、确认密码一致性、滑块未解锁双按钮置灰；登录只校验非空，`123456` 老账号实测可登录）、登录/注册卡片 Glassmorphism 重做（磨砂、柔和阴影、输入框聚焦发光、渐变主按钮、深色自适应、小屏不贴边）。
- v0.13.4 遗留：`.env` 缺 `MAIL_*`，真实投递验收未做（补齐后跑 `D:\Project\temp\test_v0134_send_real.py`）；`ai_service._invest_lookup` 仍用本地字典（避免流式多等 5 秒，可后续按需切东财）。
- 已知遗留（v0.14 待办）：
  - **投资**：`parsed.platform` 被忽略，说「用天天基金买 1000」会落到「默认」平台（**v0.14 按方案 B 做**：命中就用、没命中回落默认；**不要改成自动建**——该字段源头是 LLM，会造出删不掉的脏分组）；`holdings.record_id` 恒 NULL 是死列，将来做「删账目联动清仓」或 CSV 回溯前必须先决定删列还是真正写入；`GET /api/invest/dca-plans` 列表路由未做（数据层已就绪，看板里 holdings 已带 `dca_plans`）；AI 确认卡不支持换标的（后端已返 `candidates`）；加仓后不自动展开对应平台；弹窗内无行内错误红字
  - **既有**：季度翻页真正翻错的是 7-31 / 12-31（已用 365 天枚举证明修复完整）；`max == min` 时 markLine 两标签重叠；`entityIconHtml()` 对 1×1 退化图仍显示色块；Bootstrap 徽标色与 `--color-expense` 的极轻微差异
- v0.14 方向：1) 设计文档 `docs/design-v0131.md` 中未实现的 T02 六套主题、T03 图标库扩到 40+、T04 月度结账单卡、C3 周期账单模板（只提醒+手动生成）；2) 报销进阶（部分报销进度、按报销人筛选、报销导出）；3) 数据安全（SQLite 一键备份/恢复，CSV 增加报销与截图字段）；4) 云存档（static/uploads 截图上云）；5) 移动端与可访问性细节。
- 封版流程：语法检查 → 接口回归 → 更新 dev-log/prompts → commit + tag → detect_version() 验证。
- 备注：本机暂连不上 GitHub，网络恢复后 push main 与全部历史 tag。
