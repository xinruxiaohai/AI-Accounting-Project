# v0.12.3 Prompt 快照：安全修复、借贷强化与图标素材库

## 需求背景
v0.12.2 的强密码规则把管理员 123456 拦在登录页外；注册页的算术题太容易被脚本绕过；
借贷没有还款日、利息和凭证，点击明细没反应；分类/账户全站只有文字，没有图标体系。

## 核心 Prompt（用户原话摘要）
1. 强密码只限注册/改密，修复 123456 登录，删登录页默认管理员提示；用滑块替代算术题；
   登录页加【忘记密码？】邮箱验证码重置。
2. debts 加 due_date 与 interest，表单加输入；点借贷明细弹 Modal，含提前还款/结清与删除，
   结清自动生成利息收支账单；借出/借入支持凭证图片，明细可看原图。
3. 账单行加极浅灰下划线；新建 icons 表；/admin 加图标素材库 Tab；
   设置 → 个性化可改分类/账户图标（素材库选或自传）并恢复默认。

## 方案简述
- 登录页密码强度校验移进 gateMode==='register' 分支；滑块用 pointer 事件 + setPointerCapture，
  拖到 96% 解锁，resetSlider 在切 Tab 时复位；找回密码 Modal 复用 send-code(purpose=reset)。
- 借贷三列一次 ALTER 补齐；settle_debt 先置 paid 再用 add_record 生成利息账单（借出→利息收入，
  借入→利息支出）；前端弹窗用 bootstrap.Modal 单例，数据从 state.debtCache 取。
- 图标两表：icons(is_system, user_id) 与 user_icon_settings(user_id, kind, name, icon_id)；
  上传 2MB / MIME 白名单，删除系统图标与别人图标一律 400；前端 account 行与账单单元格渲染 <img>。

## 踩坑结论
- contacts 之前只加了表列没改 SQL，新用户建的联系人 user_id 落到 1，导致借贷款 404；
  本轮把 list/get/create 一起补上 user_id 过滤。
- update_record 返回 (bool, err)，settle 里误当布尔用会静默失败。
- 纯数字密码、默认管理员提示这类字符串在自测里要做负向断言，避免旧文案残留。
