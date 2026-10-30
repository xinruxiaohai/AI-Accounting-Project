# v0.12.4 Prompt 快照：UI 遗漏强制整改

## 需求背景
用户验收发现 v0.12.1–v0.12.3 承诺的若干 UI 只做了半截：重置密码仍是平铺输入框、昵称入口不明显、
资产页流水没有分割线、侧栏昵称颜色在深色底上看不清、图标选择器只是下拉框且用户感知不到生效。

## 核心 Prompt（用户原话摘要）
1. 删掉【账户与密码】平铺的邮箱/验证码/新密码输入框，只留【忘记旧密码？通过邮箱验证码重置】链接，
   点开独立 Modal 填写。
2. 账户与密码顶部加修改昵称输入框与保存按钮。
3. 资产页右侧流水同日多条之间加极浅灰横线或斑马底；侧栏昵称改成高对比（白色）。
4. 设置→个性化画出真正的图标选择器，选完左侧账户与账单列表实时变；必须有恢复系统默认。
5. 检查 HTML/JS，确认元素真的渲染且可点击。

## 方案简述
- Modal 用 Bootstrap 标准结构，打开事件 shown.bs.modal 带入当前邮箱；JS 只改 getElementById 的 id，
  不复用旧平铺字段，避免两套状态。
- 昵称修改沿用 v0.12.2 已有 PUT /api/auth/profile，补 UI 与保存后 updateSidebarUser。
- 图标选择器把 <select> 隐藏，renderIconChoiceGrid 渲染 .icon-choice-tile 网格，点选写回隐藏 select，
  再 renderIconPreview；保存/重置后 loadIconLibrary + refresh，账户行与账单 td 重新走 iconImgHtml。
- 分割线放 .feed-row（每行天然独立），比给表格加 tr border 稳，跨月/跨日分组都生效。

## 踩坑结论
- 旧测试断言了已删除的 DOM（settings-reset-*、auth-captcha-q），UI 重构后必须同步更新测试断言。
- 迁移初始密码 123456 不满足强密码规则，重置接口会拒绝，测试只能直接写回 werkzeug hash。
- 样式覆盖要放在文件末尾：.sidebar-user 早期规则颜色更暗，同权重下后写的 #fff 才生效。
