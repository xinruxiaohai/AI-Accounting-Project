前端与布局-07-CSS 特异性陷阱：hidden 被 display flex !important 覆盖

问题表现：

系统设置弹窗出现灾难性布局：三个 Tab（个性化与皮肤 / 账户与密码 / 帮助与反馈）的内容全部同时显示。「帮助与反馈」的四大块（联系我们、意见反馈、快捷帮助、快捷键）不但常驻在第一个 Tab 下面，还把弹窗高度顶爆、出现双滚动条。

HTML 里明明写了 `hidden`：

```html
<section id="settings-pane-help" hidden> ... </section>
```

排查过程：

`document.getElementById("settings-pane-help").hidden` 返回 `true`，说明属性在。但 `getComputedStyle(el).display` 是 `flex`。

原因在这条历史规则：

```css
#settings-pane-help {
  display: flex !important;   /* 为了让帮助块在显示时纵向排列 */
  flex-direction: column;
}
```

`hidden` 属性对应的浏览器默认样式是 `[hidden] { display: none }`，它是一条**元素类型选择器级别的低权重规则**（相当于 `(0,0,1)`）；而 `#settings-pane-help` 是 ID 选择器 `(1,0,0)` 且带 `!important`。两者相遇，`display:flex` 完胜，`hidden` 形同虚设。

这不是「忘记加 hidden」，而是「加了也没用」——比忘记更危险，因为看代码会以为已经处理过了。

解决方案：

用**属性选择器把特异性抬到 ID 同级甚至更高**，再叠 `!important` 保证必胜：

```css
/* (1,1,0)，压过 #settings-pane-help 的 (1,0,0) */
[id^="settings-pane-"][hidden],
#settings-pane-help[hidden],
.settings-pane[hidden] {
  display: none !important;
}

/* 只有「没被 hidden」时才允许 flex */
#settings-pane-help:not([hidden]) {
  display: flex !important;
  flex-direction: column;
}
```

顺带把三个 pane 统一成 `class="settings-pane"` + `hidden` 属性驱动，JS 只切换 `hidden`，不碰 `style.display`，避免两套真相并存。

同一类问题在「近 7 天账单折叠」上又出现了一次：`.recent-groups { display:flex }` 会压掉 `hidden`，必须补

```css
.recent-groups[hidden] { display: none !important; }
```

否则点了「收起」毫无反应（`hidden=true` 但视觉上还在）。

教训：

1. `hidden` 属性不是银弹，任何对同一元素写 `display: <非none>` 的规则都会让它失效，尤其是带 `!important` 的 ID 规则。
2. 项目约定「CSS 同权重靠文件末尾覆盖」，但**同权重的前提是特异性相同**，ID 与属性选择器不是同一档。
3. 排查这类问题不要看源码猜，直接 `getComputedStyle` 打印实际生效的 `display`，再用 DevTools 的 Computed 面板看胜出规则来自哪个文件哪一行。
4. 判断「元素是否可见」时也别只信 `el.hidden`——它只反映属性，不反映计算样式；断言要写 `hidden === true && getComputedStyle(el).display === "none"`。
