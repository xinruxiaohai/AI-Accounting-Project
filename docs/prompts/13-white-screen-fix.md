# 13 · 白屏紧急修复（v0.06.4-DEV）

## 需求背景

v0.07 数据库升级后，用户打开首页完全白屏：没有 JS 红字报错，控制台只有一条无关的 PWA meta 弃用警告。需要在不回滚后端升级的前提下恢复三栏布局、图表与账单列表，并封版 v0.06.4-DEV。

## 核心 Prompt

> 前端完全白屏，无 JS 异常，仅一条 PWA meta 警告。请检查 index.html 的 DOM 闭合（尤其三栏和新增弹窗）、script.js 初始化是否读了 v0.07 新增字段、style.css 是否高度坍塌；修复后自测并通过文档与 Tag 封版。

## AI 方案简述

1. 先用 curl 确认 `/`、`style.css`、`script.js`、`/api/records` 全部 200，排除服务与静态资源问题。
2. 用 headless Chrome + CDP 读取 `document.body` 直接子节点与 `.app/.sidebar/.main` 的几何尺寸，发现 body 只剩 `#toast-stack` 与 `#net-banner`，整个 `.app` 被嵌进了横幅内部。
3. 定位到 `templates/index.html` 中 `#net-banner` 只有开始标签、没有结束标签；它又是 `position: fixed` 且默认透明，于是三栏被吞进浮层里，页面只剩白底。
4. 补上 `</div>` 让横幅成为 body 下的空节点，重新渲染验证：侧栏 232px、主区 1192px、图表 canvas 304 宽、13 行账单、资产页 8 张卡、分类弹窗 25 个手柄、右键菜单 3 项、SW active。
5. 同步把手写版本占位与 SW 缓存名升到 v0.06.4，更新 HANDOFF、dev-log 并打 Tag。

## 踩坑结论

- Flask 模板返回 200、正文完整，并不代表 DOM 结构正确；白屏且无 JS 报错时，先看 DOM 树和布局几何，比继续翻 JS 快得多。
- 任何 `position: fixed` 的浮层都必须确认成对闭合，否则会静默把后面的整页内容变成自己的子节点。
- 排查顺序固定为：资源状态 → DOM 直接子节点 → 关键容器尺寸 → 初始化日志，避免同时在前后端来回猜。
