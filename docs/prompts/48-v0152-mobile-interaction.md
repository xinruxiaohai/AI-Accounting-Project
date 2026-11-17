# 48 · v0.15.2 移动端交互重构（账户 → 全屏二级页）· Agent A

> 交付对象：**Agent A**（沿用原 A 模块，不新开代号）。
> 用户原话：「手机端设计有很大的问题，手机的交互逻辑和电脑是完全不同的……比如你那个账户界面手机端问题很大，点击对应账户应该是弹出一个全屏的窗口显示其账单页面，而不是在下方呼出一个小窗口。」

---

## 〇、开工第一句必须自报（防串任务）

在你动手做任何事之前，回复的第一句话必须是：

> **我是 Agent A，本轮任务是「移动端账户详情全屏二级页」，产出文件为 `static/mobile-stack-v0152.js` / `.css` + `index.html` 两行挂载，不涉及图标、AI 识别、业务面板。**

理由：本会话此前被误派过两个任务（图标体系、文本识别），上下文里可能残留「图标 / SVG / 分类 key / ai_service.py」等无关线索。**只要你的输出开始出现 ICON_PATHS、twemoji、entity 图标、VISION_PROMPT 这类词，就是串任务了，立即停下并说明。**
当前事实：`static/mobile-stack-v0152.js` 与 `.css` **尚不存在**，`index.html` 未挂载 —— 若你发现它们已存在，说明上一轮跑了一半，接着做而不是重写。

---

## 一、开工前必读

1. `docs/HANDOFF.md`「二、并行 Agent 协作声明」——白名单 / 串行 / 禁自行 bump 版本 / 测试隔离 / git 只 add 自己文件。
2. 你是 **Agent A**，与 D（AI 图像识别）、F（账户与分类图标，只动 `script.js` 图标区 8090-8240）、B（AI 文本识别）可能并行。

## 二、白名单

允许：
- 新增 `static/mobile-stack-v0152.js`（**主战场，全部交互逻辑写这里**）
- 新增 `static/mobile-stack-v0152.css`（**全部新样式写这里**）
- `templates/index.html` —— 仅允许加 1 个 `<link>` + 1 个 `<script src="/static/mobile-stack-v0152.js?v=0.15" defer>`（放在 `script.js` 之后）
- `static/v01435.css` —— 仅当必须覆盖既有移动端规则（可选）

禁止：
- `static/script.js` 原则上 **0 改动**：用新文件 wrap 既有全局函数（`selectAccount`、`switchPage` 都是全局函数声明，直接在 `window` 上可覆写）。
- `ai_service.py` / `app.py` / `database.py` / `invest_*.py` / 任何 SQL / 表结构。
- 版本号（`APP_VERSION_FALLBACK` / `?v=` / `CACHE_NAME`）、`manifest.json`、`service-worker.js`。
- `docs/HANDOFF.md`、`git push`、`git add -A`。

## 三、判断依据（已核实，含行号，别重复排查）

**为什么现在像"下方小窗口"**
- `static/script.js:9034` 在 `#account-groups` 上做事件委托，命中行就 `selectAccount(name)`；`selectAccount`（`script.js:2254`）把数据渲染进 `#account-records` / `#detail-title` / `#account-balance-card` / `#invest-board`。
- 这些节点全在 `.assets-right` 里（`templates/index.html:498-526`），而 `style.css:6268` 起的 `@media (max-width:1023.98px)` 把 `.assets-split` 两栏改成 `height:auto; overflow:visible` 上下堆叠 —— 于是手机点账户只是「往页面下面滚出一块流水」，不是进入二级页。这就是用户说的"下方呼出一个小窗口"。

**其它已确认缺口**
- 全项目 `pushState` / `popstate` **0 命中** → 安卓返回键/侧滑手势直接退出应用，二级页无法返回。
- Bootstrap **5.3.3**，`.assets-right` 无任何移动端全屏层实现；`.mobile-tabbar`（`index.html:2705`，`.mtab-item[data-page]`）与 `.fab` 在详情打开时不会让位。
- 页面容器：`#page-home / #page-assets / #page-bills / #page-charts / #page-profile`，切页统一走 `switchPage()`（`script.js:6669`）。
- `style.css` 已有 14 处 `env(safe-area-inset-*)`，可复用写法。

## 四、设计原则（先立规矩，再改代码）

1. **移动端是「页面栈」，不是「把电脑的双栏压成上下堆叠」。** 点条目 = push 一层全屏二级页；返回 = pop。
2. **BottomSheet 只承载「临时选择/快捷操作」**（日期、筛选、分享、"更多"，高度 ≤ 60vh）。**主内容导航一律全屏二级页** —— 这正是用户不满的点。
3. **桌面 hover 才出现的操作按钮，在触屏上不存在。** 行内三按钮（改余额/编辑/删除）在 390px 下必然挤爆，必须收敛进二级页。
4. 触控目标 ≥ 44×44，行高 ≥ 56px，`touch-action: manipulation`。
5. 系统返回键 = 页面返回键（安卓/侧滑），没有例外。

## 五、P0：账户 → 全屏二级页（必须做对）

**核心做法：复用同一份 DOM，不要复制一份移动端详情页。**
- 移动端点击账户：给 `#page-assets` 加 `.is-account-open`（JS 加），CSS 在移动端断点下让 `.assets-right` 变 `position:fixed; inset:0; z-index:70`（先读出 `.mobile-tabbar` / `.fab` 实际 `z-index` 再定，必须压住它们）。
- `.assets-left` 用 `visibility:hidden; pointer-events:none` 隐藏（**不要 `display:none`**，会丢滚动位置），或记录 scrollTop 后恢复。
- 顶部 sticky 头：JS 运行时插入 `.stack-head`（`‹ 返回` + 账户名 + 右侧 `⋯` 操作），不挪动 `#detail-title`，桌面端该节点 `hidden`。返回箭头仅在「移动端 + is-account-open」显示。
- 动画：`transform: translateX(100%) → translateX(0)`，`280ms cubic-bezier(.32,.72,0,1)`；关闭反向；`prefers-reduced-motion: reduce` 时 0ms。**用 transform 不用 left/top**。
- 滚动锁：记录 `.main` 的 scrollTop → `overflow:hidden`（iOS 用 `position:fixed` 兜底，二选一并写明理由）→ 关闭时精确恢复 scrollTop。
- 安全区：底部 `padding-bottom: env(safe-area-inset-bottom)`，头部 `padding-top: env(safe-area-inset-top)`。
- **返回栈（关键）**：只在移动端打开时 `history.pushState({ zhz:'account', name }, '')`；`popstate` 里判断 `#page-assets.classList.contains('is-account-open')` → 关闭二级页而不是切页/退出；关闭按钮、左滑手势、安卓返回键**统一走 `history.back()` 单一入口**；用 flag 防重复入栈（连点两次账户不能压两层）。
- 投资账户照旧：`selectAccount` 内部已切 `#invest-board`，全屏页里也要正常（余额卡 + 持仓/流水 Tab 都能滚）。

## 六、P0：行内按钮收敛

- 移动端隐藏 `.account-row-adjust / -edit / -del` 三个行内按钮（桌面保留原样），统一进 `.stack-head` 的「⋯」菜单：编辑账户 / 修改余额 / 删除账户。
- 删除走既有 `confirmAction`（**不要 `alert`/`confirm`**），文案改成"删除后该账户下 N 条账单也会被处理"这类明确后果。
- 行整体可点（`role="button"` 已有），`event.target.closest()` 逻辑保持，别把行内按钮的点击冒泡成"进入二级页"。

## 七、P1：二级页/弹窗全屏化清单（有余力按序做，每条都要截图）

1. `#record-detail-modal`（账单详情）→ 加 `modal-fullscreen-sm-down`（Bootstrap 5.3.3 原生支持，已验证存在）。
2. `#stat-detail-modal`（统计明细）→ 同上。
3. 改余额弹窗 → 同上（表单短，也可保持居中，二选一给理由）。
4. 分类管理（先核实实际 modal id）→ 全屏 + 点列表项进编辑，不要在 390px 里塞"合并/删除/拖动"三按钮。
5. 新建/编辑账户：现在是行内展开 `.account-row.is-editing`（`script.js:2021`），390px 拥挤 → 改全屏表单页。
6. 账单筛选面板 → 全屏 sheet + 底部固定「应用 / 重置」。

## 八、验收（必须交数字和截图，不接受"感觉好了"）

CDP 脚本放 `D:\Project\temp\mobile-stack\`，无头 Chrome，`Emulation.setDeviceMetricsOverride` 390×844（deviceScaleFactor 2）+ 1440×900 对照；账号只用 `test@test.com`（本地 uid 93），JWT `sub` 字符串，禁 `/register`，teardown 清理。

1. 390×844 点账户后：`.assets-right` 的 `getBoundingClientRect()` = `{x:0,y:0,w:390,h:844}`（±1），计算样式 `position:fixed`。
2. `document.elementFromPoint(195, 815)` 命中详情页元素，**不是** `.mobile-tabbar` 的后代（证明 tabbar 已让位）。
3. `history.length` +1；执行 `history.back()` 后：`.is-account-open` 移除、`.assets-right` 回 `position:static`、`.main.scrollTop` 恢复到打开前的值（±2）。
4. 连点账户两次，`history.length` 只 +1（防重复入栈）。
5. 打开一次只发 **1 次** `/api/records?account=`（Network 计数，防重复渲染）。
6. 桌面 1440：`.assets-right` 宽 ≥ 500、`position:static`、`.stack-head` 不可见（`offsetParent === null`）。
7. 零 console error、零 404；`records.db` 测前测后 md5 一致。
8. 截图 6 张：资产列表 → 详情顶部 → 滚动中（sticky 头还在）→ 滚到底（安全区不压内容）→ 返回后（滚动位置恢复）→ 桌面同页对照。
9. **回归**：上一轮 A 的移动端 CDP 用例（15/15、9/9）重跑必须全绿。

## 九、交付

文件清单（新增/修改 + 行数）、断言统计（9 项逐条 通过/失败）、截图路径清单、遗留风险；`git add` 只加自己文件，不 push，不 bump 版本。提交信息：`feat(mobile): v0.15.2 账户详情全屏二级页与移动端导航栈`。
