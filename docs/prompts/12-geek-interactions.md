# 12 · 极客交互与系统兜底（Prompt 快照）

## 一、这一步要解决什么

到 v0.06.3 功能已经齐了，但离「像个成熟产品」还差一层：

1. 只能在线用，断网就白屏；装不到桌面，也不像应用。
2. 数据只能在页面里看，想拿去 Excel 分析没有出口。
3. 侧栏版本号是写死的，发版后经常忘了改。
4. 高频操作全靠鼠标：搜索要移到顶部点、改一笔要先进详情、分类顺序改不了。
5. 断网、接口卡死都没有任何提示；输错 URL 得到的是 Flask 默认的英文 404。

这一步补齐这五类「系统级」体验，并保持零框架依赖。

## 二、用户原始 Prompt（摘录）

> ① PWA：根目录和 static 下都要有 manifest.json 与 service-worker.js，index 加 meta 和图标，能装到桌面、断网还能看基本页面；备注列必须省略号 + 悬停看全。
> ② 导出 CSV：/api/export，开头必须拼 \uFEFF，Excel 打开不能乱码；版本号从 Git Tag 动态读，侧栏底部显示。
> ③ 快捷键 Ctrl+K 聚焦搜索；账单行右键弹自定义菜单（编辑/删除/复制此账单）；分类管理和账户管理弹窗支持拖拽排序（可以本地引 Sortable.js）。
> ④ 断网弹红色横幅、恢复弹绿色；fetch 统一 10 秒超时；404 要自定义页面，有人情味、深浅色都好看、有【返回首页】和快捷记账入口。

（Prompt 为要点摘录，非逐字。）

## 三、AI 给出的方案要点

### PWA

| 文件 | 要点 |
| --- | --- |
| `manifest.json` | `id/start_url/scope` 都是 `/`，`display: standalone`，主题色 `#2563eb`；192/512 普通图标 + 512 maskable；shortcuts 直达 `/?action=new` |
| `service-worker.js` | `CACHE_NAME = ai-accounting-v0.06.3`；install 预缓存 `/`、样式、脚本、Bootstrap/math/ECharts/Sortable、图标；导航请求 network-first 并回写缓存，静态资源 stale-while-revalidate；`/api/`、`/health`、`/admin` 一律不缓存 |
| 注册 | `registerServiceWorker()` 在 `document.readyState === "complete"` 时直接注册，否则等 `load`；`file://` 下跳过 |

Flask 增加 `/manifest.json`、`/service-worker.js`（`Service-Worker-Allowed: /` + no-cache）、`/favicon.ico` 三个路由。

### 导出与版本

- `GET /api/export`：`io.StringIO` 先写 `\ufeff`，再 `csv.writer` 写表头与 13 条账目；`text/csv` + attachment，文件名 `ai-accounting-YYYYMMDD-HHMM.csv`。
- 前端用 `fetch` 拿 blob 再触发 `<a download>`，接口报错时弹 Toast，不会把整页导航到 JSON。
- `GET /api/version`：优先环境变量 `APP_VERSION`，否则 `git describe --tags --abbrev=0`，再退 `git rev-parse --short HEAD`，全失败回落 `v0.06.3-DEV`；模块级缓存，避免每次请求都开子进程。

### 极客交互

- `Ctrl/⌘ + K` 聚焦并全选顶部搜索框；`N` 记一笔、`Esc` 关弹窗/面板；输入框内不抢键。
- 右键菜单：`#record-list` 上代理 `contextmenu`，自绘 `#ctx-menu`，按视口钳位；编辑/复制/删除三个动作；点外部、滚动、Esc 关闭；复制走 `navigator.clipboard`，失败回落 `textarea + execCommand`。
- 拖拽排序：分类树一级与每个二级 `ul` 各自一个 Sortable 实例，账户弹窗有独立的「已有账户」列表；顺序落库到 `sort_order` 列，接口 `PUT /api/categories/order`、`PUT /api/accounts/order`；只允许同一父级内重排，跨级直接 400。
- 备注列：`max-width: 260px` + `text-overflow: ellipsis` + `white-space: nowrap`，并给 `<td>` 加 `title`，悬停看全文。

### 系统兜底

- `offline` 事件显示红色常驻横幅，`online` 换成绿色并在 2.5s 后自动收起；首屏 `navigator.onLine === false` 时直接显示。
- `api()` 用 `AbortController` 统一 10 秒超时：超时提示「请求超时（10 秒），请检查网络后重试」，断网提示「网络连接失败，请确认后端服务已启动」。
- `@app.errorhandler(404)`：`/api/` 前缀返回 JSON，其余渲染 `templates/404.html`。404 页独立内联样式，复用品牌色，跟随 `data-theme` 与 `prefers-color-scheme`；文案「哎呀，这笔账好像记丢了……」，按钮「返回首页」与「去记一笔」（`/?action=new`）。

## 四、结果

- Lighthouse PWA 可安装；断网后首页、样式、脚本仍能打开（API 数据除外）。
- CSV 用 Excel 打开中文正常；版本号随 tag 变化。
- 右键菜单、拖拽排序、快捷键、断网横幅、404 页均通过 headless 断言；页面 0 报错（favicon 404 已在本次修掉）。
