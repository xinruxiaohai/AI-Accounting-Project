# 44 · v0.13.7-DEV 终极补丁：移动端响应式 / 文案纠偏 / 云同步 / PWA 全屏化

## 需求背景

用户实机反馈移动端排版"灾难级"：左侧 140px 固定侧边栏占掉近一半屏宽、双列卡片挤压、按钮文字被压成「新增账 / 户」两行、悬浮球压住内容、图表溢出屏幕。同时确认了数据架构——**所有账单/账户/分类在写操作时已实时入库（云端），前端不存在"本地大文件缓存"**，因此"云同步"按钮不应做上传，而应做"强制拉取云端最新数据并覆盖本地显示"。PWA 侧要求达到类原生体验（无地址栏、竖屏锁定）。

## 核心 Prompt（摘要）

1. 用 `@media (max-width: 768px)` 做全站适配：手机端隐藏侧边栏改底部 Tab Bar（或抽屉）、内容区 100% 宽无横向滚动、所有双列/多列降单列、全局按钮 `white-space: nowrap` 且按钮组父容器 `flex-wrap: wrap`、FAB 重新定位避开底栏、ECharts 容器 100% 宽并降高、浮动标签移位防重叠。
2. 「我的」页删除"账本只存在本机 SQLite 里，不联网、不上传……"，替换为"账本数据已安全同步至云端，支持多端随时访问。您也可以随时导入/导出账单备份。"
3. 「云同步」按钮重写为强制刷新：点击图标旋转 → 拉该用户全量数据 → 重渲染当前页面 DOM → Toast「云端数据已强制刷新并覆盖本地显示。」
4. manifest：`display: standalone`、`orientation: portrait`、`start_url: /`，并补 `@media (display-mode: standalone)` 隐藏独立 App 下冗余元素。

## 方案简述

- **底部 Tab Bar 而非抽屉**：App 习惯更接近底栏，且抽屉要额外做遮罩/手势/焦点管理，收益低于成本。底栏 5 键复用侧边导航的 `data-page`，`switchPage()` 里同步两侧 `.active`，避免出现两套导航状态。
- **横向滚动根因不是某个元素超宽，而是外层 `display:flex` + `height:100%` + 内部各自滚动**：首页/资产页在手机端改为 `display:block; overflow:visible`，让整页走浏览器自然滚动，再统一把栅格降单列。
- **按钮被压断行是缺 `white-space`**：Bootstrap `.btn` 本身不设 nowrap，父容器又没有 wrap，于是浏览器优先压缩文字而不是换行按钮。补 `.btn{white-space:nowrap}` + 容器 `flex-wrap:wrap` 后彻底消失。
- **云同步复用既有 `refresh()`**：`refresh()` 已经是 `loadAccounts/loadRecords/loadCalendarRecords/loadContacts/loadReimbSummary/loadDebtSummary` 的全量拉取管线，直接包一层加载态 + Toast 即可，不新造接口（避免两套刷新逻辑漂移）。
- **manifest 的 `display_override` 保留** `[window-controls-overlay, standalone, minimal-ui]`：桌面 WCO 同样没有地址栏，去掉会丢 v0.13 的窗口控件特性；手机端 `display:standalone` 优先命中。
- **顶栏加一个手机端同步按钮**：手机端侧边栏整体隐藏，侧栏底部的同步入口随之消失，所以新增 `#sync-btn-mobile`，与桌面入口共用 `data-sync-trigger` 选择器与同一处理器。

## 踩坑结论

1. **CSS 特异性**：`.fab { bottom: ... }` 覆盖不了基础样式与 ≤575.98px 断点里的 `.fab.fab-menu { bottom: 18px }`，实测 FAB 仍压在底栏上；必须写 `.fab, .fab.fab-menu` 同权重（且靠文件末尾顺序取胜）。
2. **CDP 无法模拟 `display-mode`**：`Emulation.setEmulatedMedia({features:[{name:'display-mode',value:'standalone'}]})` 下 `matchMedia` 恒为 false，standalone 的视觉表现只能在真机「添加到主屏幕」后验证；自动化改为断言下发 CSS 文本结构。
3. **`getComputedStyle(...).height` 永远返回像素**，"height:auto 生效"这类断言必须改判布局关系（grid 列数、子元素上下堆叠位置）。
4. **横向溢出断言要跳过滚动容器**：表格 `.table-responsive` 内部元素天然比视口宽，不排除 `overflow-x:auto` 祖先会得到一堆误报。
5. 改模板后必须重启 `--no-reload` 的 Flask，否则 CDP 拿到旧 DOM（老坑，本轮再次踩到）。
6. headless Chrome 里 toast 淡出很快，断言要轮询 `.toast` 文本而不是点完立刻读。
