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
- 当前版本：v0.13.1-DEV（**已打 tag，唯一的稳定回退点**）；其上还有未发版的 v0.13.2 前端体验优化改动（流水默认展开且可手动折叠、页面切入动效、核心数字滚动、金额统一千分位），静态资源版本串已 bump 到 `?v=0.14.0`。v0.13.0 全部能力 + 全局语义色令牌 `--color-expense/-income/-transfer` 与 `window.__chartColors()` 单一色源、设置弹窗精修、分类 `user_id` 完全隔离与停用/合并、T05 静默改分类修复、图表页缓存与 31 号翻页修复）。
- 历史标签：v0.11.4-DEV ~ v0.11.8-DEV、v0.12-DEV、v0.12.1 ~ v0.12.5-DEV。
- 已知坑：.env 换 Key 必须彻底结束旧 Flask 进程再启动；UI 重构后必须同步改旧测试断言；CSS 同权重靠文件末尾覆盖；图标格子不要塞进父级 flex 行，否则被压缩变形；分类网格点击后不可重建 DOM（只改 .is-active），否则 event.target 被摘出文档，外部点击监听会误收浮层。

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
- 鉴权：/api/auth/register、login、me、profile、avatar（PUT 路径 / avatar/upload 直传文件）、change-password、send-code、reset-password；sms-login 返回 501 占位。JWT HS256 7 天，未登录统一 401 auth_required。
- 其它：/api/import/parse|confirm、/api/debts/<id>/settle、/api/icons、/api/user-icons、/api/notifications（draft/publish/visible_at）、/api/access/*（后台密码）、/api/version（优先 Git Tag，其次 APP_VERSION_FALLBACK）。

五、下一步计划
- v0.13.1 已完成：全局语义色令牌（支出红/收入绿/结余灰）与 `window.__chartColors()` 单一色源，图表/列表/看板 100% 同步且切主题免刷新；设置弹窗精修（文案精简、图标网格化、下拉等宽、Checkbox 3 列、按钮像素对齐、单层滚动）；分类按 `user_id` 完全隔离 + 停用/合并 + 「已停用」管理区；T05 静默改分类用「双清单」修复；顺带修图表页数据陈旧、月份翻页 31 号失效、深色下图标选中态被同权重覆盖、1×1 退化图被放大成色块。
- 已知遗留：季度翻页真正翻错的是 7-31 / 12-31（今日非触发日，已用 365 天枚举证明修复完整）；`max == min` 时 markLine 两标签重叠（现实数据不出现）；`entityIconHtml()` 对 1×1 退化图仍会显示色块（`guardIconImage()` 可直接复用，建议单排任务）；Bootstrap 徽标色与 `--color-expense` 的极轻微差异。
- v0.14 方向：1) 设计文档 `docs/design-v0131.md` 中未实现的 T02 六套主题、T03 图标库扩到 40+、T04 月度结账单卡、C3 周期账单模板（只提醒+手动生成）；2) 报销进阶（部分报销进度、按报销人筛选、报销导出）；3) 数据安全（SQLite 一键备份/恢复，CSV 增加报销与截图字段）；4) 云存档（static/uploads 截图上云）；5) 移动端与可访问性细节。
- 封版流程：语法检查 → 接口回归 → 更新 dev-log/prompts → commit + tag → detect_version() 验证。
- 备注：本机暂连不上 GitHub，网络恢复后 push main 与全部历史 tag。
