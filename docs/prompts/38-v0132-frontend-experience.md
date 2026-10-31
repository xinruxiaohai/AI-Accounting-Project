# 38 · v0.13.2 前端体验优化（流水默认展开 / 页面动效 / 数字滚动）

## 需求背景

v0.13.1 封版后做纯体验层优化，三个独立子任务：

1. 资产页右侧流水：进来默认全展开，但仍要能手动点收起
2. 页面切换要有平滑切入动效
3. 核心金额数字要有滚动（Count-up）

## 核心 Prompt（要点，非原文）

- 废弃折叠状态缓存，确保每次进入资产页所有分组强制展开，"全部收起/展开"按钮默认显示为"全部展开"
- `@keyframes fadeSlideUp`（opacity 0→1、translateY 12px→0），250ms ease-out，`will-change`，
  必须带 `prefers-reduced-motion` 降级
- `animateNumber()` 用 `requestAnimationFrame`，禁第三方库；只对总资产/各账户余额/本月收支生效，
  流水单笔金额不要加；滚动中保留千分位与两位小数

## 方案简述

### 流水折叠：会话内记忆

- `isCollapsed` / `toggleCollapseState` 对流水 key 走内存 Map `sessionCollapseMaps`
- 初始化不读任何历史缓存 → 每次进来全展开；手动点之后本次会话保持；**不跨刷新记忆**
- 账户分组 `LS_ACCOUNT_COLLAPSE` 仍按原样持久化，两者互不影响

> 第一版做错了：用 `forceExpand` 把渲染钉死成永远展开，等于**禁用了点击**。
> 需求是"默认展开且可点"，不是"不可点"。已撤销。

### 页面切入动效

- `.page.is-entering { animation: fadeSlideUp 250ms ease-out both; will-change: transform, opacity }`
- 用 `setTimeout(300)` 收尾而**不是** `animationend`：减弱动态效果时动画为 `none`，
  `animationend` 永不触发，类名会永久残留并把 `will-change` 长期挂住占合成层
- 连续点同一导航项：先移除类 → 读一次 `offsetWidth` 强制结算 → 再加回，才能重放

### 数字滚动

- `animateNumber(el, from, to, duration)`：rAF + easeOutCubic，令牌作废旧帧防多个 rAF 抢写
- `setAmountAnimated(key, el, value)`：首次出现 **从 0 滚到目标值**；之后只有新旧不同才滚（500ms）
- 金额容器加 `font-variant-numeric: tabular-nums` + `nowrap` → 滚动全程宽度恒定不抖
- `money()` 收进千分位，避免核心数字带逗号、汇总不带逗号的同屏混用

## 踩坑结论

| 坑 | 结论 |
|---|---|
| **数字在隐藏页面上滚完了** | 资产页核心数字在页面还隐藏时就渲染完，`0→目标值` 跑在看不见的页面上，用户切过去动画早已结束，表现为"完全没效果"。加 `rollAmountsOnFirstEnter()`：首次进入某页才补滚 |
| **首帧无旧值** | 原来 `previous === undefined` 时直接落值，等于首次加载永远没有动画。改成从 0 滚 |
| **可见节点选错** | 用户眼里的"总资产"是 `#asset-net`（总净资产）；`#asset-total` 自 v0.10 起被 `.visually-hidden` 隐藏只作数据承载，给它做动画没人看得见 |
| **断言在 display:none 上量尺寸** | `scrollWidth/offsetWidth` 全是 0，断言变成空转假绿。必须先切到目标页并断言 `offsetWidth > 0` |
| **`scrollWidth` 含装饰伪元素** | 父容器 `::after { right: -60px }` 会被算进 `scrollWidth`，判溢出会误报。改用两者 `getBoundingClientRect()` 比对 |
| **动画中量 `rect.top`** | 含 `translateY(12px)`，跟结束后的值比必然差 12。要用不受 transform 影响的 `offsetTop` |
| **字典序当终值** | `sorted(set(samples))[-1]` 在字符串下 `¥9,999` 排在 `¥5,234` 前面。应跟实时读到的值比 |
| **`will-change` 风险** | 会创建包含块，可能让内部 `position: fixed` 元素错位。只在动画期间挂，动画结束立刻摘 |

## 验证

真实 Chrome CDP，40/40 通过（`D:\Project\temp\cdp_v0132_ui.py`）：

- 滚动：首次进入资产页采样到 13 个不同中间值 `¥983.16 → … → ¥5,234.20`；借入卡同样滚
- 折叠：点年份表头 10 行 → 0 行，再点回 10 行；切走再回来仍收起；刷新后回到全展开
- 回归：`test_v0130` 5/5、`test_v0126` 10/10、`test_v0125` 26/26、
  `test_v0131_iso` 49/49、`test_v0131_t05_api` 67/67；console 0 error
