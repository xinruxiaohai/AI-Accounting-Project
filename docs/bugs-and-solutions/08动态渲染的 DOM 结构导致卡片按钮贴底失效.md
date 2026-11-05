前端与布局-08-动态渲染的 DOM 结构导致卡片按钮贴底失效

问题表现：

「我的」页面卡片里的操作按钮（导出账单 / 导入账单等）在半数卡片上悬在半空，卡片底部留出一大片空白，同一行左右两张卡片高度还差 16px。

按常规写法加了贴底规则，只对部分卡片生效：

```css
#page-profile .panel { display: flex; flex-direction: column; height: 100%; }
#page-profile .panel > div:last-child { margin-top: auto; }
```

排查过程：

第一步，`getComputedStyle` 量 `margin-top`，发现返回值是像素而不是 `"auto"`——因为 flex 布局下 `auto` 会被解析成吸收剩余空间后的实际值，这个不是问题（一开始误判成断言失败）。

第二步，逐张卡片打印 `panel.lastElementChild` 的标签名，真相出现：

```
我的账本        → UL.profile-tips
导入导出        → P.export-hint      ← 不是 div！
账户安全        → DIV.settings-actions
```

「导入导出」卡片的 HTML 顺序是：

```html
<div class="export-actions"> 按钮 */}
<p class="export-hint">导入先预览、重复项默认不勾选…</p>
```

按钮容器后面还跟了一个 `<p>` 提示。`> div:last-child` 这个选择器要求「既是最后一个子元素、又是 div」，而最后一个子元素是 `<p>`，于是规则完全没命中，按钮自然不贴底。

第三步，右侧卡片高度差 16px 的原因另有一条：`.panel + .panel { margin-top: 16px }`（v0.05 给资产页写的通用相邻兄弟规则）在「我的」页把第二张卡片整体往下推了 16px，`align-items: stretch` 因此少拉伸 16px，顶部对不齐。

解决方案：

1. **调整 DOM 顺序**，让按钮容器成为卡片真正的最后一个子元素（提示文字移到按钮上方）：

```html
<p class="export-hint">导入先预览…</p>
<div class="export-actions"> …两个按钮… </div>
```

2. CSS 侧不只依赖 `> div:last-child`，再补一层「按类名兜底」，这样即使将来又有人往末尾加提示语也不会失效：

```css
#page-profile .panel > div:last-child { margin-top: auto !important; }

/* 兜底：哪怕末尾多出提示文字 / 徽章，按钮容器也照样贴底 */
#page-profile .panel > .profile-actions,
#page-profile .panel > .export-actions,
#page-profile .panel > .settings-actions {
  margin-top: auto !important;
  flex: 0 0 auto !important;
}
```

3. 网格容器显式 `align-items: stretch`，并清掉误伤的相邻兄弟外边距：

```css
#page-profile .profile-grid {
  display: grid; grid-template-columns: 1fr 1fr;
  align-items: stretch; gap: 20px;
}
#page-profile .profile-grid > .panel {
  height: auto; min-height: 0;
  margin-top: 0 !important;   /* 关键：抵掉 .panel + .panel 的 16px */
  margin-bottom: 0 !important;
}
```

实测左右卡片从 233 / 217 变为 233 / 233，底边 Δ=0。

教训：

1. `:last-child` 是**结构选择器**，它描述的是「DOM 里的位置」，不是「视觉上的分组」。模板里多一行提示文字就能让它整条失效，而代码看起来毫无问题。
2. 用 `:last-child` 做布局时，必须同时确认「最后一个子元素确实是你要的那个」，最好在 CSS 里加一条按业务类名的兜底。
3. `margin-top: auto` 在 flex 布局里不能用 `"auto"` 字符串断言，要量实际像素间距或者比较兄弟元素的底边。
4. 通用相邻兄弟规则（`.panel + .panel`）是布局地雷，跨页面复用 `.panel` 时一定会被误伤，宁可把间距写在容器的 `gap` 上。
