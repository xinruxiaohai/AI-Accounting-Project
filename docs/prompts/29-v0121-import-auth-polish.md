# v0.12.1 Prompt 快照：导入入口 / 注册安全 / 异常兜底 / 通知折叠

## 需求背景
v0.12 的账单导入只挂在「账单」页，用户从「我的」页找不到入口；注册没有任何人机校验，
邮箱也能随便填；后端 500 或断网时前端只白屏；通知列表一次全展开，长通知把面板撑爆。

## 核心 Prompt（用户原话摘要）
1. 我的页【导出全部账单】旁边或下方增加【导入账单】，点击弹 Modal，支持 .csv/.xlsx，
   真实调用 /api/import/parse 渲染预览（重复高亮默认不勾），确认调 /api/import/confirm 并刷新。
2. 注册加算术题校验 + 邮箱验证码：POST /api/auth/send-code 控制台打印 6 位码（Mock），
   register 校验验证码（内存暂存 5 分钟）。
3. 全局 fetch 封装：断网与 500 给幽默提示，不许白屏卡死。
4. 通知面板默认展开最新 3 条，第 4 条起折叠为标题+时间，点标题平滑展开。

## 方案简述
- 复用已有 #import-modal，仅新增入口按钮并让 initImportUi 接受多个 trigger。
- 验证码存 app.py 模块级 _EMAIL_CODES（email -> (code, expires_at)），常驻进程内存；
  注册成功即消费，过期/错误/未获取都返回 400；send-code 对已注册邮箱返回 409。
- auth-v012.js 包 fetch 后统一处理 reject 与 status>=500，.funny-toast 固定顶部展示。
- renderNotifications 给第 4 条起加 is-collapsed，正文包 .notice-body 做 max-height 过渡，
  事件委托在 #notification-list 上只绑一次。

## 踩坑结论
- Flask debug 子进程的 print 在部分后台任务里看不到缓冲输出，属捕获问题，真实终端可见。
- 折叠用 max-height 过渡必须给展开态一个足够大的上限（2400px），否则长正文会被截断。
- 注册强制验证码后，既有 E2E 脚本必须同步改为先 send-code 再读进程内验证码，否则全挂。
