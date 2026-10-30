# v0.12.7 Prompt 快照：图标专业化、个人中心大弹窗、admin 滚动与通知排版

## 需求背景
v0.12.6 的图标仍是 emoji 风格，账单/账户列表观感不专业；个人中心只是小弹窗，缺头像上传、记账天数、
绑定状态与可点击行；/admin 被全局 overflow:hidden 卡住，底部发布按钮无法触达；通知标题过长时
「展开/收起」被挤成竖排。用户提供 4 张参考图要求严格对齐。

## 核心 Prompt（用户要求摘要）
1. 账单流水（首页、账单页、资产页）与账户列表左侧必须渲染分类图标：圆形浅色底 + 系统 SVG 或自定义图片，
   改图标后列表即时刷新。
2. 个人中心改为大弹窗：头像（相机角标上传）、昵称、记账第 X 天、注册日期；UID 可复制；会员/绑定状态
   每行带 › 可点；底部橙色退出。
3. /admin 无视全局 overflow:hidden，页面自身 height:100vh + overflow-y:auto + padding-bottom。
4. 通知列表用 Flex 固定时间与展开按钮在右上角，禁止因长标题变竖排。
5. 必须用真实浏览器/DOM 验证后 commit + tag v0.12.7-DEV，400 字内汇报。

## 实施要点
- script.js：ICON_PATHS + CATEGORY/ACCOUNT_ICON_RULES + entityIconHtml(kind,name,size,variant)；
  feedRowHtml/.feed-badge、.account-row-icon、.bills-entity；修复 categoryLabel(record)。
- database.py users.avatar 迁移 + update_user_avatar；app.py PUT /api/auth/avatar、
  POST /api/auth/avatar/upload（login_required，复用 _save_upload_image）。
- index.html：#profile-modal（pc-hero/pc-avatar/pc-list/profile-logout）；auth-v012.js：applyAvatar、
  fillProfileModal、uploadAvatar、openSettingsAt。
- admin.html 独立滚动；style.css 末尾 v0.12.7 样式块；通知头 .notice-side flex-shrink:0。

## 验证
temp/test_v0127.py 5/5；temp/dom_v0127.mjs（Chrome CDP）检查图标计数、弹窗、上传、admin 滚动与通知布局；
回归 v0126/v0125/v0124/v0123/v0122/v0121/e2e 全绿。
