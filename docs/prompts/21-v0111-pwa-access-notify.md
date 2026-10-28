# v0.11.1 Prompt 快照：窗口控制按钮适配 + 图片快记 + 通知审核 + 全站访问密码

## 一、需求背景

v0.11 已完成截图记账闭环。v0.11.1 继续补四块「让应用像个真正的桌面/手机应用」的能力：

1. 桌面 PWA 窗口的标题栏右侧有系统控制按钮，顶部栏内容会被遮住，需要按 Windows Controls Overlay 规范让出安全区。
2. 悬浮球截图只能记账，AI 快记弹窗里没有入口；用户希望「在 AI 弹窗里也能选一张图」直接识别。
3. 通知目前只能手写发布，希望 AI 先起草、人工审核后再发布，后台需要草稿区与已发布区。
4. 本机应用需要一层「全站访问密码」，未设密码不拦，设了密码就整站遮罩，验证后一段时间内免密，超时立刻重新上锁；改密码等敏感操作超过免密期要重新输一次当前密码。

## 二、核心 Prompt

> 四块一次做完，后台直接写完整代码：
>
> 1. PWA manifest 使用 `display: window-controls-overlay`，CSS 用 `env(titlebar-area-*)` 给 topbar 留出右侧安全边距，按钮区 `no-drag`。
> 2. AI 快记弹窗加【上传图片】按钮、缩略图预览与清除按钮；有图时走 `/api/records/ai/image`，无图时走文本解析；识别过程复用全局非阻塞气泡。
> 3. 通知表加 status（draft / published）。新增 ai_service.generate_notification(topic) 生成「标题 + 1. 2. 3. 序号正文」；`POST /api/notifications/draft` 存草稿，`PUT /api/notifications/<id>/publish` 发布；用户端只返回 published；/admin 加「AI 起草」输入框、「待审核草稿」「已发布通知」两块列表。
> 4. 后台设置齿轮 Modal：密码列表增删、免密时长滑块（10 分钟 ~ 1 天）。全站前端守卫：未设密码不拦；设了密码则遮罩并锁滚动；验证通过把 token 与验证时间存 localStorage，超时或服务端 401 立刻重新上锁。修改/删除密码或调整超时距上次验证超过 5 分钟，必须弹框重新输入当前密码。
>
> 完成后自测、更新交接文档与日志、打 tag v0.11.1-DEV，汇报 <200 字。

## 三、AI 方案简述

- 后端：`admin_config` 存密码哈希与免密时长，`access_sessions` 存一次性验证会话；`before_request` 统一拦截，白名单只放 `/api/access/config` 与 `/api/access/verify`，其余接口无有效 token 返回 `401 {code: access_required}`；敏感操作（改密码/删密码/改超时）额外要求 5 分钟内的新会话，否则返回 `401 {code: reauth_required}`。
- 前端：`static/access-guard.js` 独立成一层，先于主脚本加载。页面启动时拉 `/api/access/config`：免密直接放行；受保护则插入全屏遮罩、锁定滚动，密码正确后写 localStorage 并 `location.reload()`。全局 `fetch` 包一层，任何 401 带 `access_required` 立即重新上锁并保留已填内容。
- 通知：AI 起草复用文本模型与「通知语气」Prompt，输出严格 JSON `{title, content}`；草稿与已发布同表不同 status，管理端一次拉 `?include=drafts` 分区渲染，发布只是把状态改成 published。
- 图片快记：前端复用 v0.11 的 `compressImageFile` 与 `uploadShotForAi`，只是把触发入口从悬浮球搬到 AI 弹窗，并在选图时用 FileReader 生成本地 dataURL 预览，避免先上传再预览。

## 四、踩坑结论

1. `glm-4v-flash` 只接受 Base64 dataURL。前端必须先压缩再转 dataURL，直接传 Blob 会 400。
2. `access_sessions.created_at` 用文本 `YYYY-MM-DD HH:MM:SS`，判断「5 分钟内」不能用字符串减法，必须解析成时间戳再比。
3. 遮罩必须在主脚本之前就位，否则页面会先渲染一帧真实数据，隐私泄露；用独立的 guard 脚本并在 `head` 末尾同步注入。
4. 通知草稿不能出现在用户端轮询里，`/api/notifications` 默认只查 `published`，管理端显式带 `include=drafts`。
5. FileReader 是异步的：测试里点完选图要等 `img.src` 变成 `data:image/` 再断言，否则会误判「没有预览」。
6. 滑块文案「60」要显示成「1 小时」，人读友好；断言时按文案判断而不是数字。
