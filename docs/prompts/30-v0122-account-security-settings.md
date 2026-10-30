# v0.12.2 Prompt 快照：账号安全、设置中心 Tab 化与基础体验

## 需求背景
v0.12 只有邮箱密码登录，没有昵称、没有失败锁定、密码可以纯数字；设置弹窗只有主题与卡片显隐，
改密码完全没有入口，忘记密码只能干瞪眼。

## 核心 Prompt（用户原话摘要）
1. users 加 nickname，注册表单和接口都要昵称，登录后侧边栏显示昵称；删掉侧边栏退出按钮。
2. 登录连续输错 5 次锁定账号 15 分钟（后端记录、前端明确提示）；密码至少两种字符类型。
3. 设置弹窗顶部 Tab：【个性化与皮肤】【账户与密码】；账户页签放退出登录、旧密码改密、
   忘记旧密码时用邮箱验证码改密。

## 方案简述
- nickname 存 users 表，空值回退邮箱前缀；前端注册额外字段写入 localStorage 的 user，
  侧栏 #sidebar-user-name 由 auth-v012.js 的 updateSidebarUser 渲染。
- 锁定放 login_attempts 表（进程重启也有效，比内存缓存稳），失败 5 次写 locked_until=now+15min；
  锁定状态在登录入口最前面判断，423 + retry_after 方便前端算倒计时。
- 验证码复用 v0.12.1 的 _EMAIL_CODES，但改成 (code, expires, purpose) 三元组：
  purpose=register 时已注册邮箱 409，purpose=reset 时未注册邮箱 404；校验必须用途一致。
- 改密/重置都清空 login_attempts，避免改完还被锁着。

## 踩坑结论
- g.current_user 来自 get_user，故意不带 password_hash，改密校验旧密码必须单独回表取，
  否则 check_password_hash("", old) 永远失败（本次自测第一轮就踩到）。
- 老 E2E 脚本把验证码缓存写成二元组，改三元组后要同步升级测试数据。
