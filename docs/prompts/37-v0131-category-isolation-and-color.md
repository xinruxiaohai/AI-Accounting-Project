# 37 · v0.13.1 分类隔离 / 全局语义色 / 设置弹窗精修

## 需求背景

v0.13.0 时分类是**全局共享**的：多个用户看到的分类列表是同一份，A 建的分类 B 也能选。
同时界面上的收支颜色散落在 4 处（CSS 变量、JS 常量、ECharts 配置、内联样式），
改主题时经常只改了一处，出现「列表是红的、图表是橙的」。
设置弹窗则有一句说了两遍的底部说明，图标网格里还出现过一整块红。

## 核心 Prompt（要点，非原文）

1. 分类按 `user_id` 完全隔离：迁移要幂等、迁移前必须备份、回填 `user_id=1` 必须在建唯一索引之前
2. 建全局语义色令牌（`--color-expense/--income/-transfer`），JS 侧只有 `window.__chartColors()` 一个出口
3. 设置弹窗：底部说明精简为一句，图标网格化、下拉等宽、按钮像素对齐、深色下不能重叠
4. T05：分类停用后编辑旧账单，分类不能「静默变成列表第一项」
5. 每个改动都要真实浏览器验证，不是静态自审

## 方案简述

### 分类隔离（T01）

- `_migrate_category_isolation()` 九步：**备份 → 补 6 列 → 回填 user_id=1 → 建 `uq_categories_user` → 再 DROP 旧 `uq_categories`**
- 顺序不能反：SQLite 视 NULL 互不相等，先建索引会静默漏掉约束；索引不能修改，只能新建后删除
- 9 个分类函数全部加 `WHERE user_id = ?`；种子函数改成显式收 `user_id`（ContextVar 默认是 1，不显式传就会把新用户的分类种到管理员名下）
- **F2 安全修复**：`set_current_user()` 原写 `int(user_id or ADMIN_USER_ID)`，`0 or 1` 求值为 1，公开路径调 `set_current_user(0)` 会以管理员身份查库 → 改成只判断 `is None`

### 语义色

- `style.css :root` 建 9 个令牌，`--pos/--neg` 改成别名指向它们 → 全站 41 处旧规则零改动同步
- `window.__chartColors()` 用 `getComputedStyle` 读真值，`dark` 由 `data-theme`/`data-mode` 判定
- 浅色 `#dc2626/#047857/#64748b`、深色 `#f87171/#34d399/#94a3b8`

### T05 静默改分类（双清单）

- `state.recordOnlyCategories` 只装「当前账单自带、但正式树里已没有」的分类
- 唯一入口 `categorySource()`：编辑态 = 正式树 + 临时节点；新增态 = 原样 `state.categories`
- `fillCategoryParent()` 显式赋值，回落首项时强制补 option

### 设置弹窗

- 底部说明 →「自定义图标仅影响当前设备显示，不改变账本底层数据。」
- `guardIconImage()`：`naturalWidth ≤ 2` 或裂图判定退化，显示占位 SVG

## 踩坑结论

| 坑 | 结论 |
|---|---|
| **1×1 像素 PNG** | 被 `object-fit:contain` 放大成 30×30 就是一整块实心色。不是 CSS 兜底色，是文件本身退化 |
| **深色同权重覆盖** | `[data-theme="dark"] .x` 与 `.x.is-active` 同权重，靠后规则把选中态整条吃掉，深色下分不清选了哪个 |
| **`#059669` 对比度** | 白底只有 3.77:1，不达 WCAG AA。改用 `#047857`（5.55:1），可读性优先于"好看" |
| **图表页数据陈旧** | `switchPage` 调 `renderChartsPage()` 不带 force，命中 `loadRecords()` 缓存；改用一直没人调的 `reloadChartsPage()` |
| **`Date.setMonth` 溢出** | `10-31` 减一个月被算成 `9-31` → 进位 `10-01`，月份翻页原地不动。按目标月最后一天 `Math.min` 钳制 |
| **测试要双向** | 只测「红转绿」会被"一刀切"蒙混过关；必须同时测「不该变红的地方仍是绿的」 |
| **红基线** | 先跑出 11 PASS / 5 FAIL 证明 bug 真实存在，修复后 27/28、补齐后 35/35，比"改完就绿"可信得多 |
