# 43 · v0.13.7-DEV 数据越权修复 + 侧边栏重构 + PWA 图标

## 需求背景

用户发现**新注册的账号**在资产页顶部「待报销」卡片里直接显示 ¥20.00，点开明细却是空的——典型的跨用户数据泄漏，且统计口径与明细口径不一致。同一轮还要求：侧边栏品牌区与用户区彻底拆开（品牌区不再显示昵称）、汉堡折叠按钮单独一行居中、头像交互降级（主界面点头像只开个人中心，个人中心里点头像才看大图）、头像大图底部只留两个按钮、后台用户管理补 UID 列、PWA 图标换成真实 Logo。

## 核心 Prompt

1. 「资产页顶部四张卡（借入/借出/待报销/已报销）的统计 SQL 必须全部带上 `WHERE user_id = ? AND deleted_at IS NULL`，并校验前端明细接口，确保统计与明细口径完全一致。」
2. 「侧边栏品牌区独立：最顶部固定 Logo + 「智汇账」，不再显示昵称；其下横向「头像 + 昵称」，宽度不够昵称换行、极长显示省略号。」
3. 「汉堡折叠按钮移到用户区下方单独一行且居中，与其他导航图标垂直对齐。」
4. 「头像交互降级：主界面点侧边栏头像只弹【个人中心】，个人中心弹窗内点头像才触发 Lightbox。」
5. 「Lightbox 底部删除「个人中心」按钮，只留「保存至本地」（主色渐变+图标）与「更换头像」（次级描边），居中均匀。」
6. 「admin.html 用户管理列表/详情新增 UID 列（users.id）。」
7. 「PWA：manifest.json icons 指向真实 Logo，index.html head 补 apple-touch-icon，service-worker CACHE_NAME 升 v0.13.7-r1。」

## 方案简述

- **越权**：根因在 `database.get_statistics()`——报销两个聚合的 WHERE 只过滤了 `type='expense' AND is_reimbursable=1`，漏了 `user_id`，于是全库所有用户的报销单都被算进同一个数字；借入/借出走 `/api/debts` → `list_debts` 本来就带 `d.user_id`，所以只有报销两张卡出事。明细走 `list_records()` 本身按 user_id 过滤，因此出现「卡片有金额、明细为空」。全库 SQL 复核后只有这一处，补齐 `user_id` 与 `deleted_at` 两个条件即闭环。
- **侧边栏**：`#sidebar-brand` 只保留 Logo + 固定文案「智汇账」；新增 `div.sidebar-user` 横排「头像 + 昵称」，昵称用 `-webkit-line-clamp:2` + `overflow-wrap:anywhere` 处理长昵称；`#sidebar-toggle` 从品牌行挪进独立的 `.sidebar-tools`（`justify-content:center`），DOM 顺序在用户区之后。
- **交互降级**：`bindProfileUi()` 里侧边栏头像的 click 从 `openAvatarLightbox` 换成 `openProfileModal`；个人中心 `#profile-avatar-btn` 仍走 Lightbox。
- **Lightbox 按钮**：删掉 `#avatar-lightbox-profile`，保留 `<a download>` 主按钮 + 更换头像次级按钮，容器 flex 居中。
- **后台 UID**：`database.list_users()` 补 `u.id`（同时给出 `record_count` 子查询），新增只读接口 `GET /api/admin/users`；admin.html 加「用户管理」Tab，表格首列 `.user-uid` 渲染 `#<id>`。
- **PWA**：直接用 Chrome CDP + canvas 把 `logo-main.png` 缩放出 192/512/180/64 与 maskable-512 五个尺寸，写进 `static/icons/`；两份 manifest 追加 1024×1024 的真实 Logo 条目；SW 缓存名与预缓存列表同步升级。

## 踩坑结论

- **越权不是「前端缓存」**：一开始怀疑是新账号首屏拿了旧统计，实测同库两个用户对比后确认是 SQL 缺 `user_id`，属于后端根因，改前端无用。
- **CDP 断言要覆盖响应式布局**：headless Chrome 默认视口只有 800×600，侧边栏在这个宽度下会折叠并隐藏昵称，导致「昵称隐藏 / 位置为 0」的假失败。验收前必须 `Emulation.setDeviceMetricsOverride` 到桌面宽度（1440×900）。
- **`compareDocumentPosition` 不要拿 `getBoundingClientRect()` 的返回值用**：DOMRect 没有这个方法，写错会抛 `a.compareDocumentPosition is not a function`；比较顺序要传真实元素。
- **后台接口是双层鉴权**：`_access_guard` 只管「访问密码」，`_identity_guard` 要求所有 `/api/*` 都带 JWT Bearer。单测只带 `X-Access-Token` 会一直 401，必须同时 `app._issue_token(user)`。
- **`.env` 缺 `MAIL_*`** 时注册接口拿不到验证码，浏览器测试账号只能直接 `database.create_user()` 造（第二参必须是 `generate_password_hash()` 的结果），测完立刻删。
- **Flask `--no-reload` 会缓存模板**：改了 `templates/*.html` 必须重启进程，否则 CDP 拿到旧 DOM。
