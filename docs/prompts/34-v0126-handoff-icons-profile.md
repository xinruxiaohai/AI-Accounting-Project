# v0.12.6 Prompt 快照：HANDOFF 瘦身、图标渲染、侧栏头像与个人中心

## 需求背景
交接文档堆到 3 万多字全是历史流水账，新会话读不动；设置里选完图标，账单和账户列表仍然只有文字；
侧边栏底部昵称+UID 在折叠时被挤压变形；左上角还是 AI Logo；改密与忘记密码分散在两处；导入导出两张卡
文案又长又技术。

## 核心 Prompt（用户要求摘要）
1. HANDOFF.md 只保留【核心规范】【当前环境/技术栈】【核心数据模型】【下一步计划】，开头写死两条红线：
   超过 10000 字必须自动精简、超过 7000 字应主动精简；除明确指令外禁止改核心规则；汇报前后字数。
2. 账单/账户列表文字左侧必须真正渲染系统默认或自定义图标，设置更改后实时刷新。
3. 删除侧栏底部昵称+UID；左上角换用户头像（无头像用昵称首字母色块）；点头像弹个人中心：
   大头像、昵称、记账第 X 天、UID+复制、注册日期、绑定状态、橙色退出登录。
4. 忘记旧密码链接移入修改密码弹窗，点击关闭当前弹窗再开邮箱验证码重置弹窗。
5. 导入/导出合并成一张卡片，去掉 UTF-8/BOM/#### 等说明，改成人话。

## 方案简述
- iconImgHtml 增加 DEFAULT_ICON_GLYPHS 映射与 defaultIconSvg()：先查 userIcons，命中返回 <img>；
  否则按分类/账户名做包含匹配输出 emoji 内联 SVG，账户头像格与账单两列共用。
- 侧栏 brand 改成 <button id="sidebar-avatar">（.brand-avatar 首字母 + #sidebar-brand-name），
  auth-v012.js 的 updateSidebarUser 改写为填充头像/昵称；新增 fillProfileModal/accountingDays/copyUid。
- 个人中心用 Bootstrap Modal，#profile-days 由 created_at 计算天数，复制用 navigator.clipboard 兜底 execCommand。
- 忘记密码监听改绑 #change-forgot-link：先 hide 改密 Modal，200ms 后 show 重置 Modal 并带入邮箱。
- 导入导出保留原按钮 id，合并到 .import-export-card，.export-actions 两按钮并排。

## 踩坑结论
- 旧回归大量断言已删除的 DOM（settings-forgot-link / sidebar-user-name / 导入卡顺序），必须同步改断言。
- Bootstrap Modal 用 getOrCreateInstance 前确认版本；改密弹窗 hide 后立刻 show 另一个会冲突，需 setTimeout。
- 图标兜底要放在 iconImgHtml 内部，才能同时覆盖账户头像格与账单表两处调用点。
