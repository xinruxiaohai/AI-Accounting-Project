# 22 · v0.11.3 后台限定密码 / 三线趋势 / 版本号自动公告

## 需求背景

v0.11 把访问密码做成了「整站遮罩」，普通用户一打开首页就被要密码，体验与本意都不对；验证凭证存在 localStorage，关掉浏览器再开仍然是免密，等于形同虚设；「查看密码」「删除密码」的二次验证层被设置弹窗盖住点不到。通知侧手动填写的公告点发送就直接对外发布，绕过了人工审核；首页近 30 天趋势只有一条支出线，看不出收支差；侧栏版本号后面挂着「· 开发中」显得没封版。公告起草还要人手填主题，标题也不带版本号。

## 核心 Prompt

- 鉴权作用域：「只有访问 /admin 路由时才触发暗黑遮罩拦截；普通用户访问首页绝对不要弹密码框。」
- 凭证生命周期：「验证凭证存储方式从 localStorage 改为 sessionStorage，关闭标签页或浏览器再打开必定要求重新输入密码。」
- 层级规范：「二次验证弹窗 z-index: 100000 !important，强制置于所有元素最顶层；以后所有危险操作二次验证都必须遵守此层级规范。」
- 公告生成：「后端自动读取当前版本号与 docs/dev-log.md 中该版本的真实更新日志，Prompt：请基于真实日志，为版本 [版本号] 撰写更新公告。标题必须严格以 '[版本号] 版本更新：' 开头，正文纯文本、无表情、平实客观、分点列出。」

## AI 方案简述

access-guard.js 增加 isAdminPage()（/^\/admin(\/|$)/）作为遮罩、超时上锁与 401 重锁的唯一入口，存储层整体切 sessionStorage。app.py 把 @app.before_request 的判断抽成 _needs_access(path, method)：/api/access/*、/api/upload、通知写操作要会话，其余公开；通知写入一律 status=draft。前端图表改 dailyTrendSeries(days) 一次产出支出/收入/结余三组序列，trendOption 配三色与 legend。公告侧新增 ai_service.dev_log_entry_for_version() 与 generate_notification(version, hint)，服务端读 git tag 当版本号、读 dev-log 当依据，模型输出后仍由后端强制重写标题前缀。

## 踩坑结论

- 版本号来源单一：detect_version() 在无 APP_VERSION 时跑 `git describe --tags --abbrev=0`，没打 tag 就永远是上一个版本，所以「一键起草」必须等 tag 打上再验证。
- Bootstrap 弹窗层级不能靠加 class 顺序解决，必须显式给 .modal 与其 .modal-backdrop 分别定 z-index，否则 backdrop 会盖住二次验证框。
- sessionStorage 意味着刷新保留、关标签失效；测试「关掉再开会要密码」用清空 sessionStorage + reload 等价。
- AI 会自作主张加「[v0.11.3-DEV]」方括号或换标题格式，后端必须用正则剥掉旧前缀再拼，不能只靠 Prompt。