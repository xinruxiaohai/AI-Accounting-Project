前端与交互-06-Bootstrap Tooltip 吞掉 title 属性

问题表现：

侧边栏折叠按钮的悬浮提示（tooltip）文案永远是错的。展开状态下按钮文字是「折叠」，鼠标移上去浮层却说「展开侧栏」；折叠之后反过来。无论怎么改 JS 里的赋值，浮层文案纹丝不动。

排查过程：

先看 `applySidebar()`，逻辑很直白：

```js
const tipText = collapsed ? "展开侧栏" : "折叠侧栏";
button.setAttribute("title", tipText);
button.setAttribute("aria-label", tipText);
```

单独调这段，`title` 属性确实变了。但鼠标移上去还是旧文案。

打开 DevTools 的 Elements 面板，发现 `<button>` 上的 `title` **不见了**，取而代之的是：

```html
<button id="sidebar-toggle" data-bs-toggle="tooltip"
        data-bs-original-title="折叠 / 展开侧栏" ...>
```

对比启动顺序才明白：`boot()` 里先调 `applySidebar()`（设置正确的 title），随后 `initTooltips()` 批量 new Tooltip。**Bootstrap 初始化 Tooltip 时会把 `title` 属性搬到 `data-bs-original-title` 并缓存进内部 `_config.title`**，从此浮层只认这份缓存，再去改 `title` 属性完全无效。

所以「逻辑写反」是假象，真相是「初始化顺序把首屏文案吞掉了，之后再也没同步过」。

解决方案：

三个地方一起覆盖，缺一不可（`_config` 决定下次显示内容，`data-bs-original-title` 决定 Bootstrap 读取源，`setContent` 决定已经渲染出来的浮层）：

```js
const tip = window.bootstrap.Tooltip.getInstance(button);
if (tip) {
  if (tip._config) {
    tip._config.title = tipText;
  }
  button.setAttribute("data-bs-original-title", tipText);
  if (typeof tip.setContent === "function") {
    try { tip.setContent({ ".tooltip-inner": tipText }); } catch (e) { /* 老版本没有 setContent */ }
  }
}
```

彻底解法则更简单：v0.14.0 把按钮改成纯图标后，直接删掉了动态文案逻辑，HTML 上只留一个中性静态 `title="折叠 / 展开侧栏"`，从根上不再有「状态与提示不一致」的可能。

另一个必须记住的点：**绝不 `dispose()` 重建**。在浮层淡出动画期间销毁实例会抛 `TypeError`（`_element` 为 null），表现为偶发白屏报错。要改文案就同步配置，要销毁就等 `hidden.bs.tooltip`。

教训：

Bootstrap 这类「初始化时把 DOM 属性搬进内部状态」的组件（Tooltip、Popover、Dropdown），**初始化之前的赋值会被吞掉、初始化之后的赋值不会同步**。凡是依赖动态文案的场景，要么在初始化时给对值，要么在三处缓存里同步覆盖，绝不能只改 `title` 属性。更稳的做法是：如果没有动态文案的强需求，就别给它加——纯图标 + 静态提示最不容易出错。
